"""
diary_repo —— 日记表（diaries）数据访问。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Diary


def create(db: Session, user_id: int, content: str) -> Diary:
    """插入一篇日记并提交，返回带 id 的记录"""
    diary = Diary(user_id=user_id, content=content)
    db.add(diary)
    db.commit()
    db.refresh(diary)
    return diary


def list_by_user(db: Session, user_id: int) -> list[Diary]:
    """按用户读取全部日记（创建时间倒序，最新在前）"""
    return list(db.execute(
        select(Diary)
        .where(Diary.user_id == user_id)
        .order_by(Diary.created_at.desc(), Diary.id.desc())
    ).scalars())
