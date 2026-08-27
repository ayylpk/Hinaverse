"""
ORM 模型：User / Conversation / Message / CrisisEvent。
字段命名与前端协议对齐，方便以后直接做响应序列化。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    # SQLite 自增主键必须用 Integer（BIGINT 不支持 AUTOINCREMENT）
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False)
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
    # role: 'user' | 'hina' | 'system'，与前端 chat store 严格对齐
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
    # 危机摘要（JSON，build_safety_summary_prompt 生成）
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 人工干预结果：成功安抚 / 转介医院 / 报警 / 用户拒绝沟通 / 误报 等
    intervention_result: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # LLM 安抚记录
    comfort_log: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()

def insert_message(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    time: Optional[str] = None
) -> Message:
    """
    插入一条消息到数据库
    
    Args:
        db: 数据库会话
        conversation_id: 会话ID
        role: 角色 ('user' | 'hina' | 'system')
        content: 消息内容
        time: 显示时间 (HH:mm)，不传则自动生成
    
    Returns:
        插入的 Message 对象
    """
    if time is None:
        time = datetime.now().strftime("%H:%M")
    
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        time=time
    )
    
    db.add(message)
    db.commit()
    db.refresh(message)
    
    return message


def insert_messages_batch(
    db: Session,
    conversation_id: int,
    messages: list[dict]
) -> list[Message]:
    """
    批量插入消息
    
    Args:
        db: 数据库会话
        conversation_id: 会话ID
        messages: 消息列表，每项为 {'role': str, 'content': str}
    
    Returns:
        插入的 Message 对象列表
    """
    inserted = []
    now = datetime.now().strftime("%H:%M")
    
    for msg in messages:
        message = Message(
            conversation_id=conversation_id,
            role=msg['role'],
            content=msg['content'],
            time=msg.get('time', now)
        )
        db.add(message)
        inserted.append(message)
    
    db.commit()
    for msg in inserted:
        db.refresh(msg)
    
    return inserted
