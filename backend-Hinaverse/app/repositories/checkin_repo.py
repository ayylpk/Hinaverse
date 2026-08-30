"""
checkin_repo —— 打卡表（checkins）数据访问。

按用户隔离：所有查询都带 user_id，归属校验走 get_owned（跨用户返回 None）。
"""
from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Checkin


def create(db: Session, user_id: int, content: str, date: date_type) -> Checkin:
    """插入一条打卡并提交，返回带 id 的记录"""
    checkin = Checkin(user_id=user_id, content=content, date=date)
    db.add(checkin)
    db.commit()
    db.refresh(checkin)
    return checkin


def list_by_user(
    db: Session,
    user_id: int,
    date: date_type | None = None,
) -> list[Checkin]:
    """当前用户全部打卡；可选按归属日过滤。
    排序：date 倒序（最新在前），date 相同再 id 倒序（后建的在前）。"""
    stmt = (
        select(Checkin)
        .where(Checkin.user_id == user_id)
        .order_by(Checkin.date.desc(), Checkin.id.desc())
    )
    if date is not None:
        stmt = stmt.where(Checkin.date == date)
    return list(db.execute(stmt).scalars())


def get_owned(db: Session, checkin_id: int, user_id: int) -> Checkin | None:
    """取属于指定用户的打卡（跨用户/不存在 → None，路由层据此 404）"""
    return db.execute(
        select(Checkin).where(Checkin.id == checkin_id, Checkin.user_id == user_id)
    ).scalar_one_or_none()


def update_status(db: Session, checkin: Checkin, status: str) -> Checkin:
    """改打卡状态（done/todo）并提交"""
    checkin.status = status
    db.commit()
    db.refresh(checkin)
    return checkin


def delete(db: Session, checkin: Checkin) -> None:
    """删除一条打卡并提交"""
    db.delete(checkin)
    db.commit()
