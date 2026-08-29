"""
conversation_repo —— 会话表数据访问。
"""
import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, Message

# 新建会话时日奈的开场白
_OPENING_LINES = [
    "我是日奈。夜空已经安静了，你可以开始说第一颗星了。",
    "欢迎回来。今天想聊点什么？不用急，慢慢说。",
    "你来了。我把灯调暗了一点，这样说话会更自在。",
]


def list_by_user(db: Session, user_id: int) -> list[Conversation]:
    """当前用户的会话列表（创建时间倒序）"""
    return list(db.execute(
        select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.created_at.desc())
    ).scalars())


def create_with_opening(db: Session, user_id: int) -> Conversation:
    """
    新建会话：同步生成日奈开场白消息并落库。
    返回带 id 的 Conversation（前端一打开就能看到欢迎语）。
    """
    conv = Conversation(user_id=user_id, title="新会话", unread_count=0)
    db.add(conv)
    db.flush()  # 拿到 conv.id

    opening = random.choice(_OPENING_LINES)
    msg = Message(
        conversation_id=conv.id, role="hina", content=opening,
        time=datetime.now().strftime("%H:%M"),
    )
    db.add(msg)
    conv.last_message = opening
    db.commit()
    db.refresh(conv)
    return conv


def get_by_id(db: Session, conversation_id: int) -> Conversation | None:
    """按主键查会话（运营人工回复更新 last_message 用）"""
    return db.get(Conversation, conversation_id)


def get_owned(db: Session, conversation_id: int, user_id: int) -> Conversation | None:
    """取属于指定用户的会话（越权返回 None）"""
    return db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    ).scalar_one_or_none()


def get_latest_by_user(db: Session, user_id: int) -> Conversation | None:
    """取用户最近的一个会话（日终总结等主动消息落库用）"""
    return db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def update_last_message(
    db: Session,
    conv: Conversation,
    content: str,
    unread_delta: int = 0,
) -> None:
    """更新会话最后一条消息（可选未读数增量，离线/主动消息时 +1）"""
    conv.last_message = content
    if unread_delta:
        conv.unread_count = (conv.unread_count or 0) + unread_delta
    db.commit()


def mark_read(db: Session, conv: Conversation) -> None:
    """用户打开会话读到最后一条时未读数清零"""
    conv.unread_count = 0
    db.commit()
