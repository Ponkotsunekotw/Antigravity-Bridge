from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _base_url() -> str:
    port = os.getenv("BRIDGE_PORT", "8765")
    return os.getenv("BRIDGE_LOCAL_URL", f"http://127.0.0.1:{port}")


def _headers() -> dict[str, str]:
    token = os.getenv("BRIDGE_TOKEN", "change-me-to-a-strong-secret")
    return {"X-Auth-Token": token}


def main() -> int:
    parser = argparse.ArgumentParser(description="Antigravity Workspace Bridge CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pending", help="List pending tasks from Android")

    p_report = sub.add_parser("report", help="Send a progress update to Android")
    p_report.add_argument("--task-id", required=False)
    p_report.add_argument("--progress", type=int, required=False)
    p_report.add_argument("--level", default="step", choices=["info", "step", "success", "warning", "error", "approval"])
    p_report.add_argument("--message", required=True)
    p_report.add_argument("--artifact", required=False)

    p_approve = sub.add_parser("ask-approval", help="Request user approval on Android")
    p_approve.add_argument("--task-id", required=True)
    p_approve.add_argument("--message", required=True)

    p_done = sub.add_parser("complete", help="Mark task as completed (100%)")
    p_done.add_argument("--task-id", required=True)
    p_done.add_argument("--message", default="任務已完成")
    p_done.add_argument("--artifact", required=False)

    p_send_file = sub.add_parser("send-file", help="Send a .zip or .apk deliverable to a chat room")
    p_send_file.add_argument("--room-id", required=True)
    p_send_file.add_argument("--file", required=True)
    p_send_file.add_argument("--note", default="")

    args = parser.parse_args()
    base = _base_url()
    headers = _headers()

    with httpx.Client(base_url=base, headers=headers, timeout=10.0) as client:
        if args.cmd == "pending":
            resp = client.get("/api/tasks", params={"status": "pending"})
            resp.raise_for_status()
            tasks = resp.json()
            if not tasks:
                print("目前沒有待處理指令。")
            for t in tasks:
                print(f"[{t['id']}] ({t['priority']}) {t['title']}\n  指令: {t['instruction']}\n")
            return 0

        if args.cmd == "report":
            payload = {
                "task_id": args.task_id,
                "level": args.level,
                "message": args.message,
                "progress": args.progress,
                "artifact_path": args.artifact,
            }
            resp = client.post("/api/progress", json=payload)
            resp.raise_for_status()
            print("已送出進度回報:", resp.json()["id"])
            return 0

        if args.cmd == "ask-approval":
            payload = {
                "task_id": args.task_id,
                "level": "approval",
                "message": args.message,
            }
            resp = client.post("/api/progress", json=payload)
            resp.raise_for_status()
            print("已向手機端發送核准請求:", resp.json()["id"])
            return 0

        if args.cmd == "complete":
            payload = {
                "task_id": args.task_id,
                "level": "success",
                "message": args.message,
                "progress": 100,
                "artifact_path": args.artifact,
            }
            resp = client.post("/api/progress", json=payload)
            resp.raise_for_status()
            print("已回報任務完成:", resp.json()["id"])
            return 0

        if args.cmd == "send-file":
            fp = Path(args.file)
            if not fp.is_file():
                raise FileNotFoundError(f"找不到檔案: {fp}")
            with fp.open("rb") as f:
                resp = client.post(
                    f"/api/rooms/{args.room_id}/agent-attachment",
                    files={"file": (fp.name, f, "application/octet-stream")},
                    data={"note": args.note},
                    timeout=120.0,
                )
            resp.raise_for_status()
            print("已傳送檔案至聊天室:", resp.json()["id"], fp.name)
            return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
