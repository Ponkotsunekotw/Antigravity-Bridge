from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class FcmRegisterRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=4096)
    device_name: str = Field(default="android", max_length=120)


class FcmSendRequest(BaseModel):
    title: str = Field(default="Antigravity 提醒", min_length=1, max_length=120)
    body: str = Field(default="收到一則新的遠端指揮通知", min_length=1, max_length=500)
    push_type: Literal["notify", "alarm"] = "notify"
    room_id: Optional[str] = None


class FcmStatusResponse(BaseModel):
    fcm_sdk_installed: bool
    service_account_configured: bool
    service_account_path: str
    registered_tokens: int


class FcmService:
    """Manages FCM device tokens and high-priority push delivery."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.tokens_file = data_dir / "fcm_tokens.json"
        self._firebase_app: Any = None

    def _service_account_path(self) -> Path:
        env_path = os.getenv("FCM_SERVICE_ACCOUNT_PATH", "").strip()
        if env_path:
            return Path(env_path)
        return self.data_dir / "serviceAccountKey.json"

    def _load_tokens(self) -> list[dict[str, str]]:
        if not self.tokens_file.exists():
            return []
        try:
            raw = json.loads(self.tokens_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict) and item.get("token")]
        except Exception:
            pass
        return []

    def _save_tokens(self, tokens: list[dict[str, str]]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_file.write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def register_token(self, token: str, device_name: str = "android") -> int:
        tokens = [t for t in self._load_tokens() if t.get("token") != token]
        tokens.append(
            {
                "token": token,
                "device_name": device_name,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._save_tokens(tokens)
        return len(tokens)

    def get_status(self) -> FcmStatusResponse:
        sdk_ok = False
        try:
            import firebase_admin  # noqa: F401

            sdk_ok = True
        except ImportError:
            sdk_ok = False

        sa_path = self._service_account_path()
        return FcmStatusResponse(
            fcm_sdk_installed=sdk_ok,
            service_account_configured=sa_path.exists(),
            service_account_path=str(sa_path),
            registered_tokens=len(self._load_tokens()),
        )

    def _ensure_firebase_app(self) -> tuple[Any, Optional[str]]:
        try:
            import firebase_admin
            from firebase_admin import credentials
        except ImportError:
            return None, "firebase-admin 尚未安裝"

        sa_path = self._service_account_path()
        if not sa_path.exists():
            return None, f"尚未找到服務帳戶金鑰：{sa_path}"

        if self._firebase_app is not None:
            return self._firebase_app, None

        app_name = f"antigravity_bridge_{abs(hash(str(sa_path)))}"
        try:
            self._firebase_app = firebase_admin.get_app(app_name)
        except ValueError:
            cred = credentials.Certificate(str(sa_path))
            self._firebase_app = firebase_admin.initialize_app(cred, name=app_name)
        return self._firebase_app, None

    def send_push(
        self,
        title: str,
        body: str,
        push_type: Literal["notify", "alarm"] = "notify",
        room_id: Optional[str] = None,
    ) -> dict[str, Any]:
        tokens_data = self._load_tokens()
        if not tokens_data:
            return {
                "status": "no_tokens",
                "sent": 0,
                "failed": 0,
                "detail": "尚無已註冊的手機 FCM Token",
            }

        app, err = self._ensure_firebase_app()
        if err or app is None:
            return {
                "status": "not_configured",
                "sent": 0,
                "failed": 0,
                "detail": err or "Firebase 尚未設定",
            }

        from firebase_admin import messaging

        data_payload = {
            "type": push_type,
            "title": title,
            "body": body,
        }
        if room_id:
            data_payload["room_id"] = room_id

        sent = 0
        failed = 0
        invalid_tokens: set[str] = set()
        errors: list[str] = []

        for entry in tokens_data:
            token = entry["token"]
            msg = messaging.Message(
                data=data_payload,
                token=token,
                android=messaging.AndroidConfig(priority="high"),
            )
            try:
                messaging.send(msg, app=app)
                sent += 1
            except Exception as exc:
                failed += 1
                err_text = str(exc)
                errors.append(err_text)
                if "registration-token-not-registered" in err_text.lower() or "unregistered" in err_text.lower():
                    invalid_tokens.add(token)

        if invalid_tokens:
            remaining = [t for t in tokens_data if t["token"] not in invalid_tokens]
            self._save_tokens(remaining)

        return {
            "status": "sent" if sent > 0 else "failed",
            "sent": sent,
            "failed": failed,
            "errors": errors[:5],
        }

    def send_data_only(self, data_payload: dict[str, str]) -> dict[str, Any]:
        """Send a silent high-priority data-only FCM message to all registered devices."""
        from firebase_admin import messaging

        app, err = self._ensure_firebase_app()
        if err or app is None:
            return {"status": "skipped", "sent": 0, "reason": err or "not configured"}

        tokens_data = self._load_tokens()
        if not tokens_data:
            return {"status": "skipped", "sent": 0, "reason": "no tokens"}

        sent = 0
        for entry in tokens_data:
            try:
                messaging.send(
                    messaging.Message(
                        data=data_payload,
                        token=entry["token"],
                        android=messaging.AndroidConfig(priority="high"),
                    ),
                    app=app,
                )
                sent += 1
            except Exception:
                pass
        return {"status": "sent" if sent > 0 else "failed", "sent": sent}
