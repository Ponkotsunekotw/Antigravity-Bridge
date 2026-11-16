from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("BRIDGE_TOKEN", "test-secret-token")
    monkeypatch.setenv("BRIDGE_PROJECTS_ROOT", str(tmp_path / "projects"))
    app = create_app(data_dir=tmp_path)
    return TestClient(app)


AUTH = {"X-Auth-Token": "test-secret-token"}


def test_health_no_auth_required(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_auth_required_for_tasks(client: TestClient) -> None:
    resp = client.get("/api/tasks")
    assert resp.status_code == 401

    resp_ok = client.get("/api/tasks", headers=AUTH)
    assert resp_ok.status_code == 200
    assert resp_ok.json() == []


def test_task_lifecycle_progress_and_approval(client: TestClient) -> None:
    # 1. Create task from Android
    create_resp = client.post(
        "/api/tasks",
        headers=AUTH,
        json={
            "title": "重構登入模組",
            "instruction": "請協助重構 auth.py 並補上單元測試",
            "priority": "high",
        },
    )
    assert create_resp.status_code == 201
    task = create_resp.json()
    task_id = task["id"]
    assert task["status"] == "pending"
    assert task["progress"] == 0

    # 2. Report step progress
    prog_resp = client.post(
        "/api/progress",
        headers=AUTH,
        json={
            "task_id": task_id,
            "level": "step",
            "message": "正在分析 auth.py 結構",
            "progress": 45,
        },
    )
    assert prog_resp.status_code == 201

    task_after_step = client.get(f"/api/tasks/{task_id}", headers=AUTH).json()
    assert task_after_step["status"] == "in_progress"
    assert task_after_step["progress"] == 45

    # 3. Request approval from user
    app_req = client.post(
        "/api/progress",
        headers=AUTH,
        json={
            "task_id": task_id,
            "level": "approval",
            "message": "是否允許覆寫 auth.py？",
        },
    )
    assert app_req.status_code == 201
    task_waiting = client.get(f"/api/tasks/{task_id}", headers=AUTH).json()
    assert task_waiting["status"] == "waiting_approval"
    assert task_waiting["approval_prompt"] == "是否允許覆寫 auth.py？"

    # 4. User approves on Android
    approve_resp = client.post(
        f"/api/tasks/{task_id}/approve",
        headers=AUTH,
        json={"approved": True, "note": "同意，請繼續"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "in_progress"

    # 5. Complete task
    done_resp = client.post(
        "/api/progress",
        headers=AUTH,
        json={
            "task_id": task_id,
            "level": "success",
            "message": "重構完成",
            "progress": 100,
            "artifact_path": "auth_report.md",
        },
    )
    assert done_resp.status_code == 201
    final_task = client.get(f"/api/tasks/{task_id}", headers=AUTH).json()
    assert final_task["status"] == "completed"
    assert final_task["progress"] == 100
    assert "auth_report.md" in final_task["artifacts"]


def test_websocket_snapshot_and_broadcast(client: TestClient) -> None:
    with client.websocket_connect("/ws?token=test-secret-token") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert "tasks" in snapshot["data"]
        assert "progress" in snapshot["data"]

        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] == "pong"


def test_outputs_path_traversal_blocked(client: TestClient, tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    (outputs / "report.txt").write_text("hello world", encoding="utf-8")

    list_resp = client.get("/api/outputs", headers=AUTH)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    read_resp = client.get("/api/outputs/read", params={"path": "report.txt"}, headers=AUTH)
    assert read_resp.status_code == 200
    assert read_resp.json()["content"] == "hello world"

    bad_resp = client.get("/api/outputs/read", params={"path": "../../etc/passwd"}, headers=AUTH)
    assert bad_resp.status_code == 400


def test_project_rooms_and_chat_messages(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    # Default seeded rooms: 手機app, Diana-Bot - gemini
    rooms_resp = client.get("/api/rooms", headers=AUTH)
    assert rooms_resp.status_code == 200
    rooms = rooms_resp.json()
    assert len(rooms) >= 2
    names = {r["name"] for r in rooms}
    assert {"手機app", "Diana-Bot - gemini"}.issubset(names)

    # Create a new project room and verify desktop folder is created
    new_room = client.post(
        "/api/rooms",
        headers=AUTH,
        json={"name": "新專案", "description": "測試聊天室"},
    )
    assert new_room.status_code == 201
    room_data = new_room.json()
    room_id = room_data["id"]
    assert Path(room_data["workspace_path"]).exists()

    # Send a user message; responder should also append a reply
    msg_resp = client.post(
        f"/api/rooms/{room_id}/messages",
        headers=AUTH,
        json={"content": "請回報目前進度"},
    )
    assert msg_resp.status_code == 201
    assert msg_resp.json()["sender"] == "user"

    list_resp = client.get(f"/api/rooms/{room_id}/messages", headers=AUTH)
    assert list_resp.status_code == 200
    messages = list_resp.json()
    assert len(messages) >= 1
    assert messages[0]["content"] == "請回報目前進度"


def test_room_file_upload(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    upload_resp = client.post(
        "/api/rooms/room-mobile-app/upload",
        headers=AUTH,
        files={"file": ("sample.txt", b"hello from android", "text/plain")},
        data={"note": "請幫我分析這個檔案"},
    )
    assert upload_resp.status_code == 201
    data = upload_resp.json()
    assert data["attachment_name"] == "sample.txt"
    assert "請幫我分析這個檔案" in data["content"]
    assert data["attachment_path"].startswith("uploads/room-mobile-app/")
    saved = tmp_path / data["attachment_path"]
    assert saved.exists()
    assert saved.read_bytes() == b"hello from android"
