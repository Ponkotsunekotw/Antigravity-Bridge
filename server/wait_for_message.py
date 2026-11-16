from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent / "bridge_data"
ROOMS_FILE = DATA_DIR / "rooms.json"
ROOMS_DIR = DATA_DIR / "rooms"
CURSOR_FILE = DATA_DIR / ".watcher_cursor.json"
HEARTBEAT_FILE = DATA_DIR / ".watcher_heartbeat.json"


def write_heartbeat() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(
            json.dumps({"pid": os.getpid(), "updated_at": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_cursor() -> dict[str, int]:
    if not CURSOR_FILE.exists():
        # Initialize cursor to current line counts so we only wake on NEW messages
        cursor: dict[str, int] = {}
        if ROOMS_DIR.exists():
            for f in ROOMS_DIR.glob("*.jsonl"):
                cursor[f.stem] = len([ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()])
        save_cursor(cursor)
        return cursor
    return json.loads(CURSOR_FILE.read_text(encoding="utf-8"))


def save_cursor(cursor: dict[str, int]) -> None:
    CURSOR_FILE.write_text(json.dumps(cursor, indent=2), encoding="utf-8")


def room_names() -> dict[str, str]:
    if not ROOMS_FILE.exists():
        return {}
    return {r["id"]: r["name"] for r in json.loads(ROOMS_FILE.read_text(encoding="utf-8"))}


def check_new_user_messages(cursor: dict[str, int]) -> list[dict]:
    found: list[dict] = []
    if not ROOMS_DIR.exists():
        return found
    names = room_names()
    for f in sorted(ROOMS_DIR.glob("*.jsonl")):
        room_id = f.stem
        lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        seen = cursor.get(room_id, 0)
        if len(lines) > seen:
            for ln in lines[seen:]:
                msg = json.loads(ln)
                if msg.get("sender") == "user":
                    found.append({
                        "room_id": room_id,
                        "room_name": names.get(room_id, room_id),
                        "message_id": msg.get("id"),
                        "content": msg.get("content"),
                        "timestamp": msg.get("timestamp"),
                    })
            cursor[room_id] = len(lines)
    return found


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cursor = load_cursor()
    while True:
        write_heartbeat()
        new_msgs = check_new_user_messages(cursor)
        if new_msgs:
            save_cursor(cursor)
            print(json.dumps(new_msgs, ensure_ascii=False, indent=2), flush=True)
            return 0
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
