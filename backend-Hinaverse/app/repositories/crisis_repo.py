"""
crisis_repo —— 危机事件表数据访问（运营端闭环）。
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CrisisEvent

# 风险等级序：数字越大越严重（去重升级用）
_RISK_ORDER = {"低危": 1, "中危": 2, "高危": 3}
# 未关闭状态（这些状态下同一用户不再新建事件；resolved 后允许新建）
_OPEN_STATUSES = ("pending_human", "comforting", "handling")


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
    """落库一条危机事件（多用户隔离：必须带 user_id）。
    ⚠️ 业务侧一般应调 upsert_open（同用户单开放事件），不要直接 create。
    """
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


def find_open(db: Session, user_id: int) -> CrisisEvent | None:
    """该用户当前最近一条未关闭事件（pending_human/comforting/handling）"""
    stmt = (
        select(CrisisEvent)
        .where(CrisisEvent.user_id == user_id, CrisisEvent.status.in_(_OPEN_STATUSES))
        .order_by(CrisisEvent.created_at.desc())
    )
    return db.execute(stmt).scalars().first()


def upsert_open(
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
    """
    安全检测触发时的事件入口：**一个用户同一时刻只保留一条未关闭事件**。

    没有开放事件 → 新建；已有 → 就地升级（不新增行），杜绝"同一用户高危+中危
    两条并存、两个运营各点一条接管同一账号"的问题：
      - 风险等级取更高（中→高 就地把已有事件升到高危）
      - 新触发需人工（pending_human）而已有还在 comforting → 状态升 pending_human；
        已有 handling（已有人在处理）则不动状态，免得抢走正在跟进的运营
      - 刷新 trigger/signal/summary 为最新检测上下文（人工干预结果不动）
    事件 resolved 后用户再次触发，会正常新建（新一轮危机）。
    """
    existing = find_open(db, user_id)
    if existing is None:
        return create(
            db, user_id, conversation_id, risk_level, trigger, signal,
            status, summary, comfort_log,
        )

    changed = False
    if _RISK_ORDER.get(risk_level, 0) > _RISK_ORDER.get(existing.risk_level, 0):
        existing.risk_level = risk_level
        changed = True
    if status == "pending_human" and existing.status == "comforting":
        existing.status = "pending_human"
        changed = True
    if trigger:
        existing.trigger = trigger
        changed = True
    if signal:
        existing.signal = signal
        changed = True
    if summary:
        existing.summary = summary
        changed = True
    if changed:
        db.commit()
        db.refresh(existing)
    return existing


def list_filter(
    db: Session,
    status_filter: str | None = None,
    risk_level: str | None = None,
    user_id: int | None = None,
    limit: int = 50,
) -> list[CrisisEvent]:
    """运营端列表：按状态/风险等级/用户过滤，创建时间倒序"""
    stmt = select(CrisisEvent)
    if status_filter:
        stmt = stmt.where(CrisisEvent.status == status_filter)
    if risk_level:
        stmt = stmt.where(CrisisEvent.risk_level == risk_level)
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


def list_by_status(db: Session, user_id: int, status: str) -> list[CrisisEvent]:
    """查某用户的指定状态事件（ws 层判断人工接管中是否要中断 agent 用）"""
    return list(db.execute(
        select(CrisisEvent)
        .where(CrisisEvent.user_id == user_id, CrisisEvent.status == status)
        .order_by(CrisisEvent.created_at.desc())
    ).scalars())


def set_status(db: Session, event: CrisisEvent, status: str) -> CrisisEvent:
    """直接改事件状态（人工接管 handling / 释放还原 pending_human），改完提交"""
    event.status = status
    db.commit()
    db.refresh(event)
    return event


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
