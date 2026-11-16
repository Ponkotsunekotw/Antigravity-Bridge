from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models import (
    AppReleaseInfo,
    ApprovalAction,
    ChatMessage,
    ChatMessageCreate,
    ChatSender,
    FileContentResponse,
    FileEntry,
    ModelConfig,
    ModelConfigUpdate,
    ProgressEvent,
    ProgressEventCreate,
    ProgressLevel,
    ProjectRoom,
    ProjectRoomCreate,
    QuotaItem,
    QuotaUsage,
    Task,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
    TokenUsage,
    TokenUsageAdd,
    utc_now_iso,
)


class BridgeStore:
    """Thread-safe local storage for Antigravity workspace tasks, progress logs, and outputs."""

    def __init__(self, data_dir: Path, projects_root: Optional[Path] = None) -> None:
        self.data_dir = data_dir.resolve()
        env_root = os.getenv("BRIDGE_PROJECTS_ROOT")
        self.projects_root = (projects_root or (Path(env_root) if env_root else self.data_dir.parent.parent)).resolve()
        self.tasks_file = self.data_dir / "tasks.json"
        self.progress_file = self.data_dir / "progress.jsonl"
        self.outputs_dir = self.data_dir / "outputs"
        self.rooms_file = self.data_dir / "rooms.json"
        self.rooms_dir = self.data_dir / "rooms"
        self.uploads_dir = self.data_dir / "uploads"
        self.releases_dir = self.data_dir / "releases"
        self.usage_file = self.data_dir / "token_usage.json"
        self.model_config_file = self.data_dir / "model_config.json"
        self.quota_file = self.data_dir / "quota_usage.json"
        self._lock = threading.RLock()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.rooms_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.releases_dir.mkdir(parents=True, exist_ok=True)
        if not self.tasks_file.exists():
            self._write_tasks([])
        if not self.progress_file.exists():
            self.progress_file.write_text("", encoding="utf-8")
        if not self.rooms_file.exists():
            now = utc_now_iso()
            self._write_rooms([
                ProjectRoom(
                    id="room-mobile-app",
                    name="手機app",
                    description="Android 遠端指揮 App 與橋接伺服器專案",
                    workspace_path=str(self.projects_root / "手機app"),
                    created_at=now,
                    updated_at=now,
                ),
                ProjectRoom(
                    id="room-bot",
                    name="Diana-Bot - gemini",
                    description="桌面 Diana-Bot - gemini 專案",
                    workspace_path=str(self.projects_root / "Diana-Bot - gemini"),
                    created_at=now,
                    updated_at=now,
                ),
            ])

    def _read_tasks(self) -> list[Task]:
        raw = self.tasks_file.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        data = json.loads(raw)
        return [Task.model_validate(item) for item in data]

    def _write_tasks(self, tasks: list[Task]) -> None:
        payload = [task.model_dump(mode="json") for task in tasks]
        tmp_file = self.tasks_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(self.tasks_file)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[Task]:
        with self._lock:
            tasks = self._read_tasks()
            if status is not None:
                tasks = [t for t in tasks if t.status == status]
            return sorted(tasks, key=lambda t: t.updated_at, reverse=True)

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            for task in self._read_tasks():
                if task.id == task_id:
                    return task
            return None

    def create_task(self, payload: TaskCreate) -> tuple[Task, ProgressEvent]:
        with self._lock:
            now = utc_now_iso()
            task = Task(
                id=f"task-{uuid.uuid4().hex[:8]}",
                title=payload.title.strip(),
                instruction=payload.instruction.strip(),
                priority=payload.priority,
                workspace=payload.workspace.strip() or "default",
                source=payload.source.strip() or "android",
                status=TaskStatus.PENDING,
                progress=0,
                current_step="等待 Antigravity 接收指令",
                created_at=now,
                updated_at=now,
            )
            tasks = self._read_tasks()
            tasks.append(task)
            self._write_tasks(tasks)

            event = self.append_progress(
                ProgressEventCreate(
                    task_id=task.id,
                    agent=task.source,
                    level=ProgressLevel.INFO,
                    message=f"收到新指令：{task.title}",
                    progress=0,
                )
            )
            return task, event

    def update_task(self, task_id: str, patch: TaskUpdate) -> Optional[Task]:
        with self._lock:
            tasks = self._read_tasks()
            updated: Optional[Task] = None
            for idx, task in enumerate(tasks):
                if task.id != task_id:
                    continue
                data = task.model_dump()
                patch_data = patch.model_dump(exclude_unset=True)
                data.update(patch_data)
                data["updated_at"] = utc_now_iso()
                updated = Task.model_validate(data)
                tasks[idx] = updated
                break
            if updated is None:
                return None
            self._write_tasks(tasks)
            return updated

    def resolve_approval(self, task_id: str, action: ApprovalAction) -> Optional[tuple[Task, ProgressEvent]]:
        with self._lock:
            tasks = self._read_tasks()
            updated: Optional[Task] = None
            for idx, task in enumerate(tasks):
                if task.id != task_id:
                    continue
                new_status = TaskStatus.IN_PROGRESS if action.approved else TaskStatus.CANCELLED
                step_msg = (
                    "使用者已核准，繼續執行"
                    if action.approved
                    else "使用者已拒絕 / 取消此操作"
                )
                if action.note.strip():
                    step_msg = f"{step_msg}：{action.note.strip()}"
                updated = task.model_copy(
                    update={
                        "status": new_status,
                        "current_step": step_msg,
                        "approval_note": action.note.strip() or None,
                        "updated_at": utc_now_iso(),
                    }
                )
                tasks[idx] = updated
                break
            if updated is None:
                return None
            self._write_tasks(tasks)
            event = self.append_progress(
                ProgressEventCreate(
                    task_id=updated.id,
                    agent="User (Android)",
                    level=ProgressLevel.SUCCESS if action.approved else ProgressLevel.WARNING,
                    message=updated.current_step,
                    progress=updated.progress,
                )
            )
            return updated, event

    def append_progress(self, payload: ProgressEventCreate) -> ProgressEvent:
        with self._lock:
            event = ProgressEvent(
                id=f"evt-{uuid.uuid4().hex[:8]}",
                timestamp=utc_now_iso(),
                **payload.model_dump(),
            )
            with self.progress_file.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")

            if event.task_id:
                tasks = self._read_tasks()
                changed = False
                for idx, task in enumerate(tasks):
                    if task.id != event.task_id:
                        continue
                    updates: dict = {"updated_at": event.timestamp}
                    if event.progress is not None:
                        updates["progress"] = event.progress
                    if event.message:
                        updates["current_step"] = event.message[:500]
                    if event.level == ProgressLevel.APPROVAL:
                        updates["status"] = TaskStatus.WAITING_APPROVAL
                        updates["approval_prompt"] = event.message
                    elif event.level == ProgressLevel.ERROR:
                        updates["status"] = TaskStatus.FAILED
                    elif event.level == ProgressLevel.SUCCESS and event.progress == 100:
                        updates["status"] = TaskStatus.COMPLETED
                    elif task.status == TaskStatus.PENDING and event.agent != "android":
                        updates["status"] = TaskStatus.IN_PROGRESS
                    if event.artifact_path and event.artifact_path not in task.artifacts:
                        updates["artifacts"] = [*task.artifacts, event.artifact_path]
                    tasks[idx] = task.model_copy(update=updates)
                    changed = True
                    break
                if changed:
                    self._write_tasks(tasks)
            return event

    def list_progress(self, limit: int = 100, task_id: Optional[str] = None) -> list[ProgressEvent]:
        with self._lock:
            if not self.progress_file.exists():
                return []
            events: list[ProgressEvent] = []
            for line in self.progress_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                evt = ProgressEvent.model_validate_json(line)
                if task_id is not None and evt.task_id != task_id:
                    continue
                events.append(evt)
            return events[-limit:]

    def _safe_output_path(self, rel_path: str) -> Path:
        candidate = (self.outputs_dir / rel_path).resolve()
        if candidate != self.outputs_dir and self.outputs_dir not in candidate.parents:
            raise ValueError("Invalid path outside outputs directory")
        return candidate

    def list_outputs(self, rel_path: str = "") -> list[FileEntry]:
        target = self._safe_output_path(rel_path)
        if not target.exists() or not target.is_dir():
            return []
        entries: list[FileEntry] = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            stat = item.stat()
            entries.append(
                FileEntry(
                    name=item.name,
                    path=item.relative_to(self.outputs_dir).as_posix(),
                    is_dir=item.is_dir(),
                    size=0 if item.is_dir() else stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                )
            )
        return entries

    def read_output_file(self, rel_path: str, max_bytes: int = 65536) -> Optional[FileContentResponse]:
        target = self._safe_output_path(rel_path)
        if not target.exists() or not target.is_file():
            return None
        raw = target.read_bytes()
        truncated = len(raw) > max_bytes
        text = raw[:max_bytes].decode("utf-8", errors="replace")
        return FileContentResponse(
            path=target.relative_to(self.outputs_dir).as_posix(),
            content=text,
            truncated=truncated,
        )

    # --- Project Chat Rooms ---

    def _read_rooms(self) -> list[ProjectRoom]:
        raw = self.rooms_file.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        return [ProjectRoom.model_validate(item) for item in json.loads(raw)]

    def _write_rooms(self, rooms: list[ProjectRoom]) -> None:
        payload = [room.model_dump(mode="json") for room in rooms]
        tmp_file = self.rooms_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(self.rooms_file)

    def _room_messages_file(self, room_id: str) -> Path:
        safe_id = "".join(ch for ch in room_id if ch.isalnum() or ch in ("-", "_"))
        if not safe_id:
            raise ValueError("Invalid room_id")
        return self.rooms_dir / f"{safe_id}.jsonl"

    def list_rooms(self) -> list[ProjectRoom]:
        with self._lock:
            return sorted(self._read_rooms(), key=lambda r: r.updated_at, reverse=True)

    def get_room(self, room_id: str) -> Optional[ProjectRoom]:
        with self._lock:
            for room in self._read_rooms():
                if room.id == room_id:
                    return room
            return None

    def create_room(self, payload: ProjectRoomCreate) -> ProjectRoom:
        with self._lock:
            now = utc_now_iso()
            name = payload.name.strip()
            raw_ws = payload.workspace_path.strip()
            if raw_ws:
                target_dir = Path(raw_ws).resolve()
            else:
                safe_folder = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or f"project-{uuid.uuid4().hex[:6]}"
                target_dir = (self.projects_root / safe_folder).resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            room = ProjectRoom(
                id=f"room-{uuid.uuid4().hex[:8]}",
                name=name,
                description=payload.description.strip() or f"桌面專案：{target_dir}",
                workspace_path=str(target_dir),
                created_at=now,
                updated_at=now,
            )
            rooms = self._read_rooms()
            rooms.append(room)
            self._write_rooms(rooms)
            self._room_messages_file(room.id).touch(exist_ok=True)
            return room

    def list_messages(self, room_id: str, limit: int = 100) -> list[ChatMessage]:
        with self._lock:
            msg_file = self._room_messages_file(room_id)
            if not msg_file.exists():
                return []
            items: list[ChatMessage] = []
            for line in msg_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                items.append(ChatMessage.model_validate_json(line))
            return items[-limit:]

    def append_message(self, room_id: str, payload: ChatMessageCreate) -> Optional[ChatMessage]:
        with self._lock:
            rooms = self._read_rooms()
            target_idx = next((i for i, r in enumerate(rooms) if r.id == room_id), None)
            if target_idx is None:
                return None
            msg = ChatMessage(
                id=f"msg-{uuid.uuid4().hex[:8]}",
                room_id=room_id,
                sender=payload.sender,
                content=payload.content.strip(),
                attachment_name=payload.attachment_name,
                attachment_path=payload.attachment_path,
                timestamp=utc_now_iso(),
            )
            msg_file = self._room_messages_file(room_id)
            with msg_file.open("a", encoding="utf-8") as fh:
                fh.write(msg.model_dump_json() + "\n")

            preview = msg.content.replace("\n", " ")[:80]
            rooms[target_idx] = rooms[target_idx].model_copy(
                update={"last_message": preview, "updated_at": msg.timestamp}
            )
            self._write_rooms(rooms)
            return msg

    def save_upload(self, room_id: str, filename: str, data: bytes) -> tuple[str, str]:
        safe_room = "".join(ch for ch in room_id if ch.isalnum() or ch in ("-", "_")) or "default"
        clean_name = Path(filename).name.strip() or "upload.bin"
        dest_dir = self.uploads_dir / safe_room
        dest_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"{uuid.uuid4().hex[:8]}_{clean_name}"
        dest = dest_dir / unique_name
        dest.write_bytes(data)
        rel_path = dest.relative_to(self.data_dir).as_posix()
        return clean_name, rel_path

    # --- App Self-Update Releases ---

    def get_latest_release(self) -> AppReleaseInfo:
        meta_file = self.releases_dir / "latest.json"
        apk_file = self.releases_dir / "app-latest.apk"
        if not meta_file.exists() or not apk_file.exists():
            return AppReleaseInfo(available=False)
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        return AppReleaseInfo(
            available=True,
            version_code=int(data.get("version_code", 0)),
            version_name=str(data.get("version_name", "")),
            size=apk_file.stat().st_size,
            sha256=str(data.get("sha256", "")),
            notes=str(data.get("notes", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    def get_release_apk_path(self) -> Optional[Path]:
        apk_file = self.releases_dir / "app-latest.apk"
        return apk_file if apk_file.exists() else None

    # --- Token Usage & Model Config ---

    def get_token_usage(self) -> TokenUsage:
        with self._lock:
            if not self.usage_file.exists():
                usage = TokenUsage()
                self.usage_file.write_text(usage.model_dump_json(indent=2), encoding="utf-8")
                return usage
            return TokenUsage.model_validate_json(self.usage_file.read_text(encoding="utf-8"))

    def add_token_usage(self, delta: TokenUsageAdd) -> TokenUsage:
        with self._lock:
            cur = self.get_token_usage()
            new_in = cur.input_tokens + delta.input_tokens
            new_out = cur.output_tokens + delta.output_tokens
            updated = TokenUsage(
                input_tokens=new_in,
                output_tokens=new_out,
                total_tokens=new_in + new_out,
                requests_count=cur.requests_count + 1,
                updated_at=utc_now_iso(),
            )
            self.usage_file.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
            return updated

    def get_model_config(self) -> ModelConfig:
        with self._lock:
            if not self.model_config_file.exists():
                cfg = ModelConfig(
                    model=os.getenv("GEMINI_MODEL", "Gemini 4 Hydrogen"),
                    thinking_depth="medium",
                )
                self.model_config_file.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
                return cfg
            return ModelConfig.model_validate_json(self.model_config_file.read_text(encoding="utf-8"))

    def update_model_config(self, payload: ModelConfigUpdate) -> ModelConfig:
        with self._lock:
            cfg = ModelConfig(
                model=payload.model.strip(),
                thinking_depth=payload.thinking_depth.strip().lower() or "medium",
                updated_at=utc_now_iso(),
            )
            self.model_config_file.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
            return cfg

    def get_quota_usage(self) -> QuotaUsage:
        with self._lock:
            if not self.quota_file.exists():
                default_quota = QuotaUsage(
                    items=[
                        QuotaItem(group="Gemini Models", label="Weekly limit", percent_left=94, resets_in="Resets in 6d 4h"),
                        QuotaItem(group="Gemini Models", label="5h limit", percent_left=85, resets_in="Resets in 2h 31m"),
                        QuotaItem(group="Claude and GPT models", label="Weekly limit", percent_left=44, resets_in="Resets in 6d 13h"),
                        QuotaItem(group="Claude and GPT models", label="5h limit", percent_left=100, resets_in=""),
                        QuotaItem(group="Gemini 4 Argon", label="Weekly limit", percent_left=5, resets_in="Resets in 2d 10h"),
                    ]
                )
                self.quota_file.write_text(default_quota.model_dump_json(indent=2), encoding="utf-8")
                return default_quota
            return QuotaUsage.model_validate_json(self.quota_file.read_text(encoding="utf-8"))

    def update_quota_usage(self, payload: QuotaUsage) -> QuotaUsage:
        with self._lock:
            updated = QuotaUsage(items=payload.items, updated_at=utc_now_iso())
            self.quota_file.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
            return updated
