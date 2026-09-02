"""
send_message_repo —— 主动关心消息队列（send_messages）数据访问。

队列语义（见 models.SendMessage）：
    create_pending   生成端落库（落库前先 cancel_pending 保证每用户至多一条待发送）
    cancel_pending   用户又说话了 → 撤销所有待发送（人都来了，不用发消息关心）
    fetch_due        扫描循环取到点消息（status=pending AND scheduled_at<=now）
    mark_sent / mark_expired / bump_fail  状态机推进（失败累计≥MAX_FAIL 直接 cancelled）
"""
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import SendMessage

# 推送失败重试上限：达到即 cancelled，防止坏数据把扫描卡成死循环
MAX_FAIL = 3


def create(db: Session, user_id: int, content: str, scheduled_at: datetime) -> SendMessage:
    """插入一条消息并提交，返回带 id 的记录（旧 /api/send-message 接口在用）"""
    msg = SendMessage(user_id=user_id, content=content, scheduled_at=scheduled_at)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_by_id(db: Session, msg_id: int) -> SendMessage | None:
    """按主键读取，不存在返回 None"""
    return db.get(SendMessage, msg_id)


# ═══════════════════════════════════════════════════════════════════
# 队列操作（主动关心链路专用）
# ═══════════════════════════════════════════════════════════════════

def create_pending(db: Session, user_id: int, content: str, scheduled_at: datetime) -> SendMessage:
    """落一条待发送的主动关心（调用方负责先 cancel_pending，或直接用 active_message.accept_spontaneous）"""
    return create(db, user_id, content, scheduled_at)


def cancel_pending(db: Session, user_id: int) -> int:
    """
    撤销该用户全部待发送消息（收新消息时调用）。
    返回撤销条数——正常至多 1 条，>1 说明有 bug，让日志喊出来。
    """
    result = db.execute(
        update(SendMessage)
        .where(SendMessage.user_id == user_id, SendMessage.status == "pending")
        .values(status="cancelled")
    )
    db.commit()
    return result.rowcount or 0


def fetch_due(db: Session, now: datetime, limit: int = 20) -> list[SendMessage]:
    """取到点的待发送消息（时间升序，一次最多 limit 条，防单轮扫描过长）"""
    stmt = (
        select(SendMessage)
        .where(SendMessage.status == "pending", SendMessage.scheduled_at <= now)
        .order_by(SendMessage.scheduled_at)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def mark_sent(db: Session, msg: SendMessage) -> None:
    """推送成功 → sent（终态，正文留在表里好排查）"""
    msg.status = "sent"
    db.commit()


def mark_expired(db: Session, msg: SendMessage) -> None:
    """错过发送窗（静默时段顺延太久/危机占用太久）→ 作废，迟到的关心是骚扰"""
    msg.status = "expired"
    db.commit()


def bump_fail(db: Session, msg: SendMessage) -> None:
    """推送失败计一次；到上限直接 cancelled，不再重试"""
    msg.fail_count += 1
    if msg.fail_count >= MAX_FAIL:
        msg.status = "cancelled"
    db.commit()
