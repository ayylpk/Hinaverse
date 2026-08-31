"""
ORM 模型：User / Conversation / Message / CrisisEvent / Checkin。
字段命名与前端协议对齐，方便以后直接做响应序列化。
数据操作请走 app/repositories/（DAO 层），本文件只定义表结构。
"""
from datetime import date as date_type, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    # 角色：user（普通用户）/ admin（运营管理员）。admin 由运维手工 SQL 置位，无注册入口
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    # 头像只存 URL，空串表示未设置（本轮不做文件上传）
    avatar: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    # 极光推送设备 ID，按用户维度存储
    reg_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Conversation(Base):
    """会话表：一个用户可有多条会话"""
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="新会话", nullable=False)
    # 未读消息数：用户打开会话读到最后一条时清零
    unread_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    # 冗余最后一条消息，列表查询时不用 join
    last_message: Mapped[str] = mapped_column(String(512), default="", nullable=False)

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.id"
    )


class Message(Base):
    """消息表：所有消息（用户/日奈/系统）都落这里，重启不丢"""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), index=True, nullable=False
    )
    # role: 'user' | 'hina' | 'system'（拦截/接管提示） | 'operator'（运营人工回复，
    # 用户端归入日奈气泡渲染），与前端 chat store 的映射逻辑严格对齐
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # time 字段存 HH:mm，前端直接显示
    time: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")



class CrisisEvent(Base):
    """
    危机事件表：安全检测触发时落库，用于人工介入闭环。
    多用户隔离：所有事件带 user_id。
    """
    __tablename__ = "crisis_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # 关联会话（可选），便于回溯上下文
    conversation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=True
    )
    # 风险等级：高危 / 中危 / 低危
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    # 触发原因（检测理由）
    trigger: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 触发判定的关键原句
    signal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 状态：pending_human（待人工）/ comforting（LLM 安抚中）/ resolved（已处理）
    status: Mapped[str] = mapped_column(String(32), default="pending_human", nullable=False)
    # 危机摘要（dict：高危存 {"quick_summary": ...}，快速浓缩文本）
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 人工干预结果：成功安抚 / 转介医院 / 报警 / 用户拒绝沟通 / 误报 等
    intervention_result: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # LLM 安抚记录
    comfort_log: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()


class SendMessage(Base):
    """极简消息存取（sendMessage 接口）：id / user_id / content。"""
    __tablename__ = "send_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class Diary(Base):
    """日记：id / user_id / content / created_at（按用户隔离）"""
    __tablename__ = "diaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class HighRiskSummary(Base):
    """高危摘要：确认高危后快速生成的对话浓缩（id / user_id / content 三列）。
    独立表存高危摘要，与普通消息/日记隔离。"""
    __tablename__ = "high_risk_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class Checkin(Base):
    """打卡记录：用户自建记录/打卡（todo/done 状态机，按用户隔离）。
    星历模块：date 是打卡归属日（允许选过去/未来，缺省当天由路由层填）。"""
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 打卡归属日（纯日期，无时区）
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    # 完成标记：todo（未完成）/ done（已完成）；MySQL 原生 ENUM，sqlite 测试降级 VARCHAR+CHECK
    status: Mapped[str] = mapped_column(Enum("todo", "done", name="checkin_status"), default="todo", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

