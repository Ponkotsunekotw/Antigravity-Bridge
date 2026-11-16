from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish built APK for Android in-app self-update")
    parser.add_argument("--apk", default="../android-app/app/build/outputs/apk/debug/app-debug.apk")
    parser.add_argument("--version-code", type=int, required=True)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    apk_src = (Path(__file__).parent / args.apk).resolve()
    if not apk_src.exists():
        raise FileNotFoundError(f"APK not found: {apk_src}")

    releases_dir = Path(__file__).parent / "bridge_data" / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    apk_dst = releases_dir / "app-latest.apk"
    shutil.copy2(apk_src, apk_dst)

    sha256 = hashlib.sha256(apk_dst.read_bytes()).hexdigest()
    meta = {
        "version_code": args.version_code,
        "version_name": args.version_name,
        "sha256": sha256,
        "notes": args.notes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (releases_dir / "latest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    port = os.getenv("BRIDGE_PORT", "8765")
    token = os.getenv("BRIDGE_TOKEN", "change-me-to-a-strong-secret")
    try:
        httpx.post(f"http://127.0.0.1:{port}/api/app/notify", headers={"X-Auth-Token": token}, timeout=5.0)
    except Exception:
        pass
    print(f"Published APK v{args.version_name} ({args.version_code}), sha256={sha256[:12]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
