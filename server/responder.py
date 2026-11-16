from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from models import (
    ChatMessageCreate,
    ChatSender,
    ProgressEventCreate,
    ProgressLevel,
    ProjectRoom,
    TaskStatus,
    TaskUpdate,
    TokenUsageAdd,
)
from store import BridgeStore


def _has_api_key() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _is_agent_watcher_online(data_dir: Path, max_age_sec: float = 6.0) -> bool:
    hb_file = data_dir / ".watcher_heartbeat.json"
    if not hb_file.exists():
        return False
    try:
        data = json.loads(hb_file.read_text(encoding="utf-8"))
        updated_at = float(data.get("updated_at") or 0)
        return (time.time() - updated_at) <= max_age_sec
    except Exception:
        return False


def _call_gemini(
    room: ProjectRoom,
    history_text: str,
    user_message: str,
    model_name: str,
    thinking_depth: str,
) -> tuple[str, int, int]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return (f"已收到你在「{room.name}」的指令（模型：{model_name} / 深度：{thinking_depth}），正在交由 Antigravity 處理中...", 0, 0)

    from google import genai

    client = genai.Client(api_key=api_key)
    system_prompt = (
        f"你是 Antigravity 遠端助理，目前正在「{room.name}」專案聊天室與使用者對話。\n"
        f"專案說明：{room.description or '無'}\n"
        f"思考深度：{thinking_depth}\n"
        "請用繁體中文回覆，不需要附帶完整檔案內容，只要提供清楚、精簡的「成果摘要、重點結論與下一步建議」。"
    )
    prompt = f"{system_prompt}\n\n近期對話紀錄：\n{history_text}\n\n使用者最新訊息：{user_message}"
    response = client.models.generate_content(model=model_name, contents=prompt)
    text = (response.text or "").strip() or "（已完成處理，但未產生文字摘要）"
    meta = getattr(response, "usage_metadata", None)
    in_tok = int(getattr(meta, "prompt_token_count", 0) or 0)
    out_tok = int(getattr(meta, "candidates_token_count", 0) or 0)
    return text, in_tok, out_tok


async def handle_user_chat_message(
    store: BridgeStore,
    broadcast: Callable[[str, Any], Awaitable[None]],
    room: ProjectRoom,
    user_message: str,
    task_id: str | None = None,
) -> None:
    """Process a user chat message asynchronously and push progress + summary reply in real time."""
    step_evt = store.append_progress(
        ProgressEventCreate(
            task_id=task_id,
            agent=f"Chat/{room.name}",
            level=ProgressLevel.STEP,
            message=f"[{room.name}] 收到訊息：{user_message[:60]}",
            progress=20,
        )
    )
    await broadcast("progress_event", step_evt.model_dump(mode="json"))

    recent = store.list_messages(room.id, limit=12)
    history_lines = [
        f"{'使用者' if m.sender == ChatSender.USER else '助理'}: {m.content}"
        for m in recent[:-1]
    ]
    history_text = "\n".join(history_lines) if history_lines else "（尚無歷史對話）"

    has_key = _has_api_key()
    watcher_online = _is_agent_watcher_online(store.data_dir)
    cfg = store.get_model_config()
    try:
        if has_key:
            reply_text, in_tok, out_tok = await asyncio.to_thread(
                _call_gemini, room, history_text, user_message, cfg.model, cfg.thinking_depth
            )
            if in_tok or out_tok:
                usage = store.add_token_usage(TokenUsageAdd(input_tokens=in_tok, output_tokens=out_tok))
                await broadcast("token_usage_updated", usage.model_dump(mode="json"))
            level = ProgressLevel.SUCCESS
            status_msg = f"[{room.name}] 已回覆成果摘要"
        elif watcher_online:
            reply_text = f"✅ 已送達 Antigravity 背景監聽器（模型：{cfg.model} / 深度：{cfg.thinking_depth}），Agent 已收到並開始處理中..."
            level = ProgressLevel.STEP
            status_msg = f"[{room.name}] 已送達 Agent，處理中..."
        else:
            reply_text = "⚠️ 目前沒有啟用中的 Antigravity 背景監聽器，指令已暫存於伺服器佇列，尚未送達 Agent 執行。請先於電腦端開啟或喚醒 Antigravity 對話再通知處理。"
            level = ProgressLevel.WARNING
            status_msg = f"[{room.name}] 等待 Agent 上線（監聽器離線）"
    except Exception as exc:
        reply_text = f"即時回覆執行時發生錯誤：{exc}"
        level = ProgressLevel.ERROR
        status_msg = f"[{room.name}] 回覆失敗：{exc}"

    assistant_msg = store.append_message(
        room.id,
        ChatMessageCreate(sender=ChatSender.ASSISTANT, content=reply_text),
    )
    if assistant_msg:
        await broadcast("chat_message", assistant_msg.model_dump(mode="json"))
        updated_room = store.get_room(room.id)
        if updated_room:
            await broadcast("room_updated", updated_room.model_dump(mode="json"))

    if task_id and level in (ProgressLevel.STEP, ProgressLevel.WARNING):
        updated_task = store.update_task(
            task_id,
            TaskUpdate(
                status=TaskStatus.IN_PROGRESS if level == ProgressLevel.STEP else TaskStatus.PENDING,
                progress=25 if level == ProgressLevel.STEP else 0,
                current_step=status_msg,
            ),
        )
        if updated_task:
            await broadcast("task_updated", updated_task.model_dump(mode="json"))

    done_evt = store.append_progress(
        ProgressEventCreate(
            task_id=task_id,
            agent=f"Chat/{room.name}",
            level=level,
            message=status_msg,
            progress=100 if level == ProgressLevel.SUCCESS else 25,
        )
    )
    await broadcast("progress_event", done_evt.model_dump(mode="json"))
    if task_id:
        latest_task = store.get_task(task_id)
        if latest_task:
            await broadcast("task_updated", latest_task.model_dump(mode="json"))
