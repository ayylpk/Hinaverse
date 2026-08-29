"""
crisis_repo —— 危机事件表数据访问（运营端闭环）。
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CrisisEvent


def create(
    db: Session,
    user_id: int,
    conversation_id: int | None,
    risk_level: str,
    trigger: str,
    signal: str,
    status: str,
    summary: dict | None = None,
    comfort_log: str = "",
) -> CrisisEvent:
    """落库一条危机事件（多用户隔离：必须带 user_id）"""
    event = CrisisEvent(
        user_id=user_id,
        conversation_id=conversation_id,
        risk_level=risk_level,
        trigger=trigger,
        signal=signal,
        status=status,
        summary=summary,
        comfort_log=comfort_log,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_filter(
    db: Session,
    status_filter: str | None = None,
    user_id: int | None = None,
    limit: int = 50,
) -> list[CrisisEvent]:
    """运营端列表：按状态/用户过滤，创建时间倒序"""
    stmt = select(CrisisEvent)
    if status_filter:
        stmt = stmt.where(CrisisEvent.status == status_filter)
    if user_id is not None:
        stmt = stmt.where(CrisisEvent.user_id == user_id)
    return list(db.execute(stmt.order_by(CrisisEvent.created_at.desc()).limit(limit)).scalars())


def list_by_user(db: Session, user_id: int) -> list[CrisisEvent]:
    """当前用户的危机事件（多用户隔离）"""
    return list(db.execute(
        select(CrisisEvent).where(CrisisEvent.user_id == user_id).order_by(CrisisEvent.created_at.desc())
    ).scalars())


def get_by_id(db: Session, event_id: int) -> CrisisEvent | None:
    return db.get(CrisisEvent, event_id)


def mark_intervention(
    db: Session,
    event: CrisisEvent,
    intervention_result: str,
    resolved: bool = True,
) -> CrisisEvent:
    """标记人工干预结果，可同时标记已解决"""
    event.intervention_result = intervention_result
    if resolved:
        event.status = "resolved"
        event.resolved_at = datetime.now()
    db.commit()
    db.refresh(event)
    return event
