"""
message_repo —— 聊天记录数据访问（消息表）。

涵盖：单条/批量插入、游标分页取历史、最近 N 条。
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Message


def _now_hm() -> str:
    return datetime.now().strftime("%H:%M")


def insert_one(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    time: str | None = None,
) -> Message:
    """插入一条消息并提交（role: 'user' | 'hina' | 'system'）"""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        time=time or _now_hm(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def insert_batch(
    db: Session,
    conversation_id: int,
    messages: list[dict],
) -> list[Message]:
    """批量插入消息（每项 {'role', 'content', 'time'?}）并提交"""
    now = _now_hm()
    inserted: list[Message] = []
    for m in messages:
        msg = Message(
            conversation_id=conversation_id,
            role=m["role"],
            content=m["content"],
            time=m.get("time", now),
        )
        db.add(msg)
        inserted.append(msg)
    db.commit()
    for msg in inserted:
        db.refresh(msg)
    return inserted


def get_recent(db: Session, conversation_id: int, limit: int = 20) -> list[Message]:
    """取最近 limit 条消息（按 id 正序返回，WS 上下文/安全检测用）"""
    rows = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).scalars().all()
    return list(reversed(rows))


def list_page(
    db: Session,
    conversation_id: int,
    before_id: int | None = None,
    limit: int = 50,
) -> tuple[list[Message], bool]:
    """
    游标分页拉历史：默认最新 limit 条；before_id 时拉该 id 之前的。
    返回 (正序消息列表, has_more)。
    """
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = list(reversed(db.execute(stmt.order_by(Message.id.desc()).limit(limit)).scalars().all()))

    has_more = False
    if rows:
        earliest_id = rows[0].id
        has_more = db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation_id, Message.id < earliest_id
            )
        ).scalar() > 0
    return rows, has_more
