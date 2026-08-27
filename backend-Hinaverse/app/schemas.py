"""
Pydantic 请求/响应模型。字段命名与前端协议严格对齐。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════
# 认证相关
# ═══════════════════════════════════════

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    """返回给前端的用户信息（不含密码）"""
    id: int
    username: str
    nickname: str
    avatar: str = ""

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    """登录/注册响应：{token, user}"""
    token: str
    user: UserOut


class ProfileUpdateRequest(BaseModel):
    """修改资料：昵称/头像/改密码均可选"""
    nickname: str | None = Field(None, min_length=1, max_length=64)
    avatar: str | None = None
    current_password: str | None = None
    new_password: str | None = Field(None, min_length=6, max_length=128)


# ═══════════════════════════════════════
# 会话 / 消息
# ═══════════════════════════════════════

class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    last_message: str = ""
    unread_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    """单条消息，字段与前端 ChatMessage 完全一致"""
    id: int
    role: str
    content: str
    time: str

    model_config = ConfigDict(from_attributes=True)


class MessageListResponse(BaseModel):
    messages: list[MessageOut]
    # 是否还有更早的消息（游标分页用）
    has_more: bool


# ═══════════════════════════════════════
# 设备 / 开发调试
# ═══════════════════════════════════════

class RegIdRequest(BaseModel):
    reg_id: str = Field(..., min_length=1)


class ActiveRequest(BaseModel):
    conversation_id: int


# ═══════════════════════════════════════
# 危机事件（运营端）
# ═══════════════════════════════════════

class CrisisEventOut(BaseModel):
    id: int
    user_id: int
    conversation_id: int | None = None
    risk_level: str
    trigger: str = ""
    signal: str = ""
    status: str = "pending_human"
    summary: dict | None = None
    intervention_result: str = ""
    comfort_log: str = ""
    created_at: datetime
    resolved_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CrisisInterventionRequest(BaseModel):
    """人工标记干预结果"""
    intervention_result: str = Field(..., min_length=1, max_length=64)
    resolved: bool = Field(True, description="是否标记为已解决")
