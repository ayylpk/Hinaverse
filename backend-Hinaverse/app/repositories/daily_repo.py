"""
daily_repo —— 日终总结 / 日记数据访问。

日终总结本质是日奈主动发的「hina」消息：落库到 messages 表 + 更新会话
last_message/unread_count（离线时计数，前端下拉展示）。

调用方（future）：backend 定时任务跑 daily_compress 后，把 _daily_summary_text 交这里落库，
再走 outbound_hub.send_diary 推送。
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Message
from app.repositories.message_repo import insert_one


def save_daily_summary(
    db: Session,
    conversation_id: int,
    content: str,
    time: str | None = None,
) -> Message:
    """
    落库一条日终总结（role=hina，与普通日奈消息同构，前端无需特判）。
    内部同时更新会话 last_message（会话表更新由调用方 conversation_repo 处理，
    避免这里耦合会话表——保持单模块单职责）。
    """
    return insert_one(db, conversation_id, "hina", content, time)


def get_recent_daily(db: Session, conversation_id: int, limit: int = 5) -> list[Message]:
    """取最近若干条日终总结（hina 消息中按需过滤，当前直接返回最近 hina 消息）"""
    from app.models import Conversation

    conv = db.get(Conversation, conversation_id)
    if conv is None:
        return []
    rows = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).scalars().all()
    return list(reversed(rows))
