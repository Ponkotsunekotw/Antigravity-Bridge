from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    instruction: str = Field(..., min_length=1, max_length=10000)
    priority: TaskPriority = TaskPriority.NORMAL
    workspace: str = Field(default="default", max_length=120)
    source: str = Field(default="android", max_length=60)


class TaskUpdate(BaseModel):
    status: Optional[TaskStatus] = None
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    current_step: Optional[str] = Field(default=None, max_length=500)
    summary: Optional[str] = Field(default=None, max_length=4000)
    approval_prompt: Optional[str] = Field(default=None, max_length=2000)
    artifacts: Optional[list[str]] = None


class ApprovalAction(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=2000)


class Task(BaseModel):
    id: str
    title: str
    instruction: str
    priority: TaskPriority = TaskPriority.NORMAL
    workspace: str = "default"
    source: str = "android"
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    current_step: str = ""
    summary: str = ""
    approval_prompt: Optional[str] = None
    approval_note: Optional[str] = None
    artifacts: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ProgressLevel(str, Enum):
    INFO = "info"
    STEP = "step"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    APPROVAL = "approval"


class ProgressEventCreate(BaseModel):
    task_id: Optional[str] = None
    agent: str = Field(default="Antigravity", max_length=80)
    level: ProgressLevel = ProgressLevel.INFO
    message: str = Field(..., min_length=1, max_length=4000)
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    artifact_path: Optional[str] = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProgressEvent(ProgressEventCreate):
    id: str
    timestamp: str = Field(default_factory=utc_now_iso)


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified_at: str


class FileContentResponse(BaseModel):
    path: str
    content: str
    truncated: bool = False


class ProjectRoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    workspace_path: str = Field(default="", max_length=500)


class ProjectRoom(BaseModel):
    id: str
    name: str
    description: str = ""
    workspace_path: str = ""
    last_message: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ChatSender(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    sender: ChatSender = ChatSender.USER
    attachment_name: Optional[str] = Field(default=None, max_length=255)
    attachment_path: Optional[str] = Field(default=None, max_length=500)


class ChatMessage(BaseModel):
    id: str
    room_id: str
    sender: ChatSender
    content: str
    attachment_name: Optional[str] = None
    attachment_path: Optional[str] = None
    timestamp: str = Field(default_factory=utc_now_iso)


class AppReleaseInfo(BaseModel):
    available: bool
    version_code: int = 0
    version_name: str = ""
    size: int = 0
    sha256: str = ""
    notes: str = ""
    updated_at: str = ""


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    requests_count: int = 0
    updated_at: str = Field(default_factory=utc_now_iso)


class TokenUsageAdd(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ModelConfig(BaseModel):
    model: str = Field(default="gemini-2.5-flash", max_length=80)
    thinking_depth: str = Field(default="medium", max_length=40)
    updated_at: str = Field(default_factory=utc_now_iso)


class ModelConfigUpdate(BaseModel):
    model: str = Field(..., min_length=1, max_length=80)
    thinking_depth: str = Field(default="medium", max_length=40)


class QuotaItem(BaseModel):
    group: str
    label: str
    percent_left: int = Field(ge=0, le=100)
    resets_in: str = ""


class QuotaUsage(BaseModel):
    items: list[QuotaItem] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)
