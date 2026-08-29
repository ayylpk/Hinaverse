"""
send_message_repo —— 极简消息表（send_messages）数据访问。
"""
from sqlalchemy.orm import Session

from app.models import SendMessage


def create(db: Session, user_id: int, content: str) -> SendMessage:
    """插入一条消息并提交，返回带 id 的记录"""
    msg = SendMessage(user_id=user_id, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_by_id(db: Session, msg_id: int) -> SendMessage | None:
    """按主键读取，不存在返回 None"""
    return db.get(SendMessage, msg_id)
