from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
    ProjectRoom,
    ProjectRoomCreate,
    QuotaUsage,
    Task,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
    TokenUsage,
    TokenUsageAdd,
)
from fcm_service import FcmRegisterRequest, FcmSendRequest, FcmService, FcmStatusResponse
from responder import handle_user_chat_message
from store import BridgeStore

load_dotenv()


def get_bridge_token() -> str:
    return os.getenv("BRIDGE_TOKEN", "change-me-to-a-strong-secret")


def get_data_dir() -> Path:
    return Path(os.getenv("BRIDGE_DATA_DIR", "./bridge_data"))


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, event_type: str, payload: Any) -> None:
        dead: list[WebSocket] = []
        message = {"type": event_type, "data": payload}
        for conn in list(self._connections):
            try:
                await conn.send_json(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)


def _is_valid_token(candidate: Optional[str]) -> bool:
    expected = get_bridge_token()
    if not candidate:
        return False
    return secrets.compare_digest(candidate, expected)


def require_auth(
    authorization: Optional[str] = Header(default=None),
    x_auth_token: Optional[str] = Header(default=None),
) -> str:
    token = x_auth_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not _is_valid_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication token",
        )
    return token  # type: ignore[return-value]


def create_app(data_dir: Optional[Path] = None) -> FastAPI:
    app = FastAPI(
        title="Antigravity Workspace Bridge",
        version="1.0.0",
        description="VPN Intranet Bridge for Android Progress Reporting & Command Dispatch",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    resolved_data_dir = data_dir or get_data_dir()
    store = BridgeStore(resolved_data_dir)
    fcm_service = FcmService(resolved_data_dir)
    ws_manager = ConnectionManager()
    app.state.store = store
    app.state.fcm_service = fcm_service
    app.state.ws_manager = ws_manager

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "antigravity-bridge"}

    @app.get("/api/auth/verify", dependencies=[Depends(require_auth)])
    def verify_auth() -> dict[str, bool]:
        return {"authenticated": True}

    @app.get("/api/tasks", response_model=list[Task], dependencies=[Depends(require_auth)])
    def list_tasks(status_filter: Optional[TaskStatus] = Query(default=None, alias="status")) -> list[Task]:
        return store.list_tasks(status=status_filter)

    @app.get("/api/tasks/{task_id}", response_model=Task, dependencies=[Depends(require_auth)])
    def get_task(task_id: str) -> Task:
        task = store.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.post("/api/tasks", response_model=Task, status_code=201, dependencies=[Depends(require_auth)])
    async def create_task(payload: TaskCreate) -> Task:
        task, event = store.create_task(payload)
        await ws_manager.broadcast("task_created", task.model_dump(mode="json"))
        await ws_manager.broadcast("progress_event", event.model_dump(mode="json"))
        return task

    @app.patch("/api/tasks/{task_id}", response_model=Task, dependencies=[Depends(require_auth)])
    async def update_task(task_id: str, patch: TaskUpdate) -> Task:
        task = store.update_task(task_id, patch)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        await ws_manager.broadcast("task_updated", task.model_dump(mode="json"))
        return task

    @app.post("/api/tasks/{task_id}/approve", response_model=Task, dependencies=[Depends(require_auth)])
    async def approve_task(task_id: str, action: ApprovalAction) -> Task:
        result = store.resolve_approval(task_id, action)
        if not result:
            raise HTTPException(status_code=404, detail="Task not found")
        task, event = result
        await ws_manager.broadcast("task_updated", task.model_dump(mode="json"))
        await ws_manager.broadcast("progress_event", event.model_dump(mode="json"))
        return task

    @app.get("/api/progress", response_model=list[ProgressEvent], dependencies=[Depends(require_auth)])
    def list_progress(
        limit: int = Query(default=100, ge=1, le=500),
        task_id: Optional[str] = Query(default=None),
    ) -> list[ProgressEvent]:
        return store.list_progress(limit=limit, task_id=task_id)

    @app.post("/api/progress", response_model=ProgressEvent, status_code=201, dependencies=[Depends(require_auth)])
    async def create_progress(payload: ProgressEventCreate) -> ProgressEvent:
        event = store.append_progress(payload)
        await ws_manager.broadcast("progress_event", event.model_dump(mode="json"))
        if event.task_id:
            updated_task = store.get_task(event.task_id)
            if updated_task:
                await ws_manager.broadcast("task_updated", updated_task.model_dump(mode="json"))
        return event

    @app.get("/api/outputs", response_model=list[FileEntry], dependencies=[Depends(require_auth)])
    def list_outputs(path: str = Query(default="")) -> list[FileEntry]:
        try:
            return store.list_outputs(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/outputs/read", response_model=FileContentResponse, dependencies=[Depends(require_auth)])
    def read_output(path: str = Query(...)) -> FileContentResponse:
        try:
            content = store.read_output_file(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not content:
            raise HTTPException(status_code=404, detail="Output file not found")
        return content

    # --- Project Chat Rooms ---

    @app.get("/api/rooms", response_model=list[ProjectRoom], dependencies=[Depends(require_auth)])
    def list_rooms() -> list[ProjectRoom]:
        return store.list_rooms()

    @app.post("/api/rooms", response_model=ProjectRoom, status_code=201, dependencies=[Depends(require_auth)])
    async def create_room(payload: ProjectRoomCreate) -> ProjectRoom:
        room = store.create_room(payload)
        await ws_manager.broadcast("room_created", room.model_dump(mode="json"))
        return room

    @app.get("/api/rooms/{room_id}/messages", response_model=list[ChatMessage], dependencies=[Depends(require_auth)])
    def list_room_messages(room_id: str, limit: int = Query(default=100, ge=1, le=500)) -> list[ChatMessage]:
        if not store.get_room(room_id):
            raise HTTPException(status_code=404, detail="Room not found")
        return store.list_messages(room_id, limit=limit)

    @app.post("/api/rooms/{room_id}/messages", response_model=ChatMessage, status_code=201, dependencies=[Depends(require_auth)])
    async def post_room_message(room_id: str, payload: ChatMessageCreate) -> ChatMessage:
        room = store.get_room(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        msg = store.append_message(room_id, payload)
        assert msg is not None
        await ws_manager.broadcast("chat_message", msg.model_dump(mode="json"))
        updated_room = store.get_room(room_id)
        if updated_room:
            await ws_manager.broadcast("room_updated", updated_room.model_dump(mode="json"))

        if payload.sender == ChatSender.USER:
            title_preview = msg.content.replace("\n", " ")[:40]
            chat_task, _ = store.create_task(
                TaskCreate(
                    title=f"[{room.name}] {title_preview}",
                    instruction=msg.content,
                    workspace=room.name,
                    source=f"chat:{room.id}",
                )
            )
            chat_task = store.update_task(
                chat_task.id,
                TaskUpdate(
                    status=TaskStatus.IN_PROGRESS,
                    progress=15,
                    current_step=f"[{room.name}] 已收到指令，處理中...",
                ),
            ) or chat_task
            await ws_manager.broadcast("task_created", chat_task.model_dump(mode="json"))
            asyncio.create_task(
                handle_user_chat_message(
                    store=store,
                    broadcast=ws_manager.broadcast,
                    room=room,
                    user_message=msg.content,
                    task_id=chat_task.id,
                )
            )
        elif payload.sender == ChatSender.ASSISTANT:
            # Complete any active chat tasks in this room when assistant posts final summary
            for t in store.list_tasks():
                if t.source == f"chat:{room.id}" and t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
                    done = store.update_task(
                        t.id,
                        TaskUpdate(
                            status=TaskStatus.COMPLETED,
                            progress=100,
                            current_step=f"[{room.name}] 已完成並回覆摘要",
                        ),
                    )
                    if done:
                        await ws_manager.broadcast("task_updated", done.model_dump(mode="json"))
            usage = store.add_token_usage(TokenUsageAdd(input_tokens=0, output_tokens=0))
            asyncio.create_task(
                asyncio.to_thread(
                    fcm_service.send_push,
                    f"[{room.name}] 新回覆",
                    msg.content.replace("\n", " ")[:140],
                    "notify",
                    room.id,
                )
            )
            await ws_manager.broadcast("token_usage_updated", usage.model_dump(mode="json"))
        return msg

    @app.post("/api/rooms/{room_id}/upload", response_model=ChatMessage, status_code=201, dependencies=[Depends(require_auth)])
    async def upload_room_file(
        room_id: str,
        file: UploadFile = File(...),
        note: str = Form(default=""),
    ) -> ChatMessage:
        room = store.get_room(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        raw = await file.read()
        if len(raw) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large (max 25 MB)")
        clean_name, rel_path = store.save_upload(room_id, file.filename or "upload.bin", raw)
        note_text = note.strip()
        attachment_tag = f"[附件：{clean_name} ({len(raw)} bytes) | 儲存位置：{rel_path}]"
        full_content = f"{note_text}\n\n{attachment_tag}" if note_text else attachment_tag
        msg = store.append_message(
            room_id,
            ChatMessageCreate(
                sender=ChatSender.USER,
                content=full_content,
                attachment_name=clean_name,
                attachment_path=rel_path,
            ),
        )
        assert msg is not None
        await ws_manager.broadcast("chat_message", msg.model_dump(mode="json"))
        updated_room = store.get_room(room_id)
        if updated_room:
            await ws_manager.broadcast("room_updated", updated_room.model_dump(mode="json"))
        task_title = f"[{room.name}] {note_text[:30]}" if note_text else f"[{room.name}] 檔案：{clean_name}"
        chat_task, _ = store.create_task(
            TaskCreate(
                title=task_title,
                instruction=msg.content,
                workspace=room.name,
                source=f"chat:{room.id}",
            )
        )
        chat_task = store.update_task(
            chat_task.id,
            TaskUpdate(
                status=TaskStatus.IN_PROGRESS,
                progress=15,
                current_step=f"[{room.name}] 已收到檔案 {clean_name}，處理中...",
            ),
        ) or chat_task
        await ws_manager.broadcast("task_created", chat_task.model_dump(mode="json"))
        asyncio.create_task(
            handle_user_chat_message(
                store=store,
                broadcast=ws_manager.broadcast,
                room=room,
                user_message=msg.content,
                task_id=chat_task.id,
            )
        )
        return msg

    @app.post("/api/rooms/{room_id}/agent-attachment", response_model=ChatMessage, status_code=201, dependencies=[Depends(require_auth)])
    async def upload_agent_attachment(
        room_id: str,
        file: UploadFile = File(...),
        note: str = Form(default=""),
    ) -> ChatMessage:
        room = store.get_room(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        raw = await file.read()
        if len(raw) > 100 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
        clean_name, rel_path = store.save_upload(room_id, file.filename or "package.zip", raw)
        size_mb = len(raw) / (1024 * 1024)
        size_label = f"{size_mb:.2f} MB" if size_mb >= 0.1 else f"{len(raw) / 1024:.1f} KB"
        note_text = note.strip()
        summary_line = f"📦 {clean_name} ({size_label})"
        full_content = f"{note_text}\n\n{summary_line}" if note_text else summary_line
        msg = store.append_message(
            room_id,
            ChatMessageCreate(
                sender=ChatSender.ASSISTANT,
                content=full_content,
                attachment_name=clean_name,
                attachment_path=rel_path,
            ),
        )
        assert msg is not None
        await ws_manager.broadcast("chat_message", msg.model_dump(mode="json"))
        updated_room = store.get_room(room_id)
        if updated_room:
            await ws_manager.broadcast("room_updated", updated_room.model_dump(mode="json"))
        await asyncio.to_thread(
            fcm_service.send_push,
            f"[{room.name}] 收到可下載檔案",
            f"{clean_name} ({size_label})",
            "notify",
            room_id,
        )
        return msg

    @app.get("/api/attachments/download", dependencies=[Depends(require_auth)])
    def download_attachment(path: str = Query(..., min_length=1)) -> FileResponse:
        base_dir = store.data_dir.resolve()
        target = (base_dir / path).resolve()
        if not str(target).startswith(str(base_dir)) or not target.is_file():
            raise HTTPException(status_code=404, detail="Attachment not found")
        return FileResponse(
            path=str(target),
            filename=target.name,
            media_type="application/octet-stream",
        )

    # --- App Self-Update ---

    @app.get("/api/app/latest", response_model=AppReleaseInfo, dependencies=[Depends(require_auth)])
    def get_latest_app() -> AppReleaseInfo:
        return store.get_latest_release()

    @app.get("/api/app/download", dependencies=[Depends(require_auth)])
    def download_latest_app() -> FileResponse:
        apk_path = store.get_release_apk_path()
        if not apk_path:
            raise HTTPException(status_code=404, detail="No APK release available")
        return FileResponse(
            path=apk_path,
            media_type="application/vnd.android.package-archive",
            filename="antigravity-bridge-latest.apk",
        )

    @app.post("/api/app/notify", response_model=AppReleaseInfo, dependencies=[Depends(require_auth)])
    async def notify_app_update() -> AppReleaseInfo:
        info = store.get_latest_release()
        if info.available:
            await ws_manager.broadcast("app_update_available", info.model_dump(mode="json"))
        return info

    # --- Token Usage & Model Config ---

    @app.get("/api/usage", response_model=TokenUsage, dependencies=[Depends(require_auth)])
    def get_usage() -> TokenUsage:
        return store.get_token_usage()

    @app.post("/api/usage", response_model=TokenUsage, dependencies=[Depends(require_auth)])
    async def add_usage(payload: TokenUsageAdd) -> TokenUsage:
        usage = store.add_token_usage(payload)
        await ws_manager.broadcast("token_usage_updated", usage.model_dump(mode="json"))
        return usage

    @app.get("/api/config/model", response_model=ModelConfig, dependencies=[Depends(require_auth)])
    def get_model_config() -> ModelConfig:
        return store.get_model_config()

    @app.post("/api/config/model", response_model=ModelConfig, dependencies=[Depends(require_auth)])
    async def update_model_config(payload: ModelConfigUpdate) -> ModelConfig:
        cfg = store.update_model_config(payload)
        await ws_manager.broadcast("model_config_updated", cfg.model_dump(mode="json"))
        return cfg

    @app.get("/api/quota", response_model=QuotaUsage, dependencies=[Depends(require_auth)])
    def get_quota() -> QuotaUsage:
        return store.get_quota_usage()

    @app.post("/api/quota", response_model=QuotaUsage, dependencies=[Depends(require_auth)])
    async def update_quota(payload: QuotaUsage) -> QuotaUsage:
        quota = store.update_quota_usage(payload)
        await ws_manager.broadcast("quota_updated", quota.model_dump(mode="json"))
        return quota

    @app.get("/api/fcm/status", response_model=FcmStatusResponse, dependencies=[Depends(require_auth)])
    def get_fcm_status() -> FcmStatusResponse:
        return fcm_service.get_status()

    @app.post("/api/fcm/register", dependencies=[Depends(require_auth)])
    def register_fcm_token(payload: FcmRegisterRequest) -> dict[str, Any]:
        count = fcm_service.register_token(payload.token, payload.device_name)
        return {"ok": True, "registered_tokens": count}

    @app.post("/api/fcm/send", dependencies=[Depends(require_auth)])
    async def send_fcm_push(payload: FcmSendRequest) -> dict[str, Any]:
        fcm_result = await asyncio.to_thread(
            fcm_service.send_push,
            payload.title,
            payload.body,
            payload.push_type,
            payload.room_id,
        )
        await ws_manager.broadcast(
            "push_alert",
            {
                "type": payload.push_type,
                "title": payload.title,
                "body": payload.body,
                "room_id": payload.room_id,
            },
        )
        return fcm_result

    @app.post("/api/fcm/sync-url", dependencies=[Depends(require_auth)])
    async def sync_fcm_url(payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("server_url") or "").strip().rstrip("/")
        if not url:
            raise HTTPException(status_code=400, detail="server_url 不可為空")
        return await asyncio.to_thread(
            fcm_service.send_data_only,
            {"type": "server_url_update", "server_url": url},
        )

    @app.websocket("/ws")
    async def websocket_endpoint(
        websocket: WebSocket,
        token: Optional[str] = Query(default=None),
    ) -> None:
        header_token = websocket.headers.get("x-auth-token")
        if not _is_valid_token(token or header_token):
            await websocket.close(code=4401)
            return

        await ws_manager.connect(websocket)
        try:
            rooms = store.list_rooms()
            initial_room_id = rooms[0].id if rooms else None
            initial_messages = (
                [m.model_dump(mode="json") for m in store.list_messages(initial_room_id, limit=100)]
                if initial_room_id
                else []
            )
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "data": {
                        "tasks": [t.model_dump(mode="json") for t in store.list_tasks()],
                        "progress": [e.model_dump(mode="json") for e in store.list_progress(limit=50)],
                        "rooms": [r.model_dump(mode="json") for r in rooms],
                        "active_room_id": initial_room_id,
                        "messages": initial_messages,
                        "token_usage": store.get_token_usage().model_dump(mode="json"),
                        "model_config": store.get_model_config().model_dump(mode="json"),
                        "quota_usage": store.get_quota_usage().model_dump(mode="json"),
                    },
                }
            )
            while True:
                # Keep connection alive; clients can send "ping"
                msg = await websocket.receive_text()
                if msg.strip().lower() == "ping":
                    await websocket.send_json({"type": "pong", "data": {}})
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception:
            ws_manager.disconnect(websocket)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("BRIDGE_HOST", "0.0.0.0")
    port = int(os.getenv("BRIDGE_PORT", "8765"))
    uvicorn.run("main:app", host=host, port=port, reload=False)
