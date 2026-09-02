"""
Pydantic 请求/响应模型。字段命名与前端协议严格对齐。
"""
from datetime import date as date_type, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════
# 认证相关
# ═══════════════════════════════════════

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    # 运营台首管理员注册：缺省 False = 普通用户注册（用户端行为完全不变）；
    # True 时走部署码校验链（码非空→码相等→全库无 admin），通过才创建 role=admin
    is_admin: bool = False
    init_code: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    """返回给前端的用户信息（不含密码）"""
    id: int
    username: str
    nickname: str
    avatar: str = ""
    role: str = "user"

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
    # 状态：pending_human（待人工）/ comforting（LLM 安抚中）/ handling（人工处理中）/ resolved（已处理）
    status: str = "pending_human"
    summary: dict | None = None
    intervention_result: str = ""
    comfort_log: str = ""
    created_at: datetime
    resolved_at: datetime | None = None
    # 关联用户昵称（运营端列表展示用，由路由层从 user 关系填充）
    user_nickname: str = ""

    model_config = ConfigDict(from_attributes=True)


class CrisisEventDetailOut(CrisisEventOut):
    """事件详情：危机事件 + 关联会话最近对话（人工介入回溯上下文）"""
    messages: list[MessageOut] = []


class CrisisInterventionRequest(BaseModel):
    """人工标记干预结果"""
    intervention_result: str = Field(..., min_length=1, max_length=64)
    resolved: bool = Field(True, description="是否标记为已解决")


class CrisisReplyRequest(BaseModel):
    """运营人工回复：以 operator 角色落库并实时推送到用户端（用户端按日奈气泡展示）"""
    content: str = Field(..., min_length=1, max_length=2000)


class CrisisTakeoverRequest(BaseModel):
    """人工接管/释放：接管置 handling（处理中），释放还原 pending_human（待人工）"""
    takeover: bool = Field(True, description="true=接管→handling，false=释放→pending_human")


# ═══════════════════════════════════════
# 极简消息（sendMessage 接口）
# ═══════════════════════════════════════

class SendMessageCreate(BaseModel):
    """插入消息：user_id 不传（由 JWT token 决定当前用户）；scheduled_at = 期望送达时间"""
    content: str = Field(..., min_length=1, max_length=10000)
    scheduled_at: datetime


class SendMessageOut(BaseModel):
    id: int
    user_id: int
    content: str
    scheduled_at: datetime
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════
# 日记（dairy 接口）
# ═══════════════════════════════════════

class DiaryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)


class DiaryOut(BaseModel):
    id: int
    user_id: int
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════
# 打卡（checkin 接口，星历模块）
# ═══════════════════════════════════════

class CheckinCreate(BaseModel):
    """新建打卡：内容必填（1..500）；date 可选（归属日，缺省当天，允许过去/未来）"""
    content: str = Field(..., min_length=1, max_length=500)
    date: date_type | None = None


class CheckinUpdate(BaseModel):
    """打卡/取消打卡标记：仅 status 可改"""
    status: Literal["done", "todo"]


class CheckinOut(BaseModel):
    id: int
    user_id: int
    content: str
    date: date_type
    status: str = "todo"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
