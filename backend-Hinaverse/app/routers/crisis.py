"""
危机事件路由（运营端）：列表查询 / 标记人工干预结果。

注：当前项目无「管理员」角色概念，列表接口暂对所有登录用户开放。
生产环境应叠加管理员鉴权（如 User.role == "admin"）。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CrisisEvent, User
from app.schemas import CrisisEventOut, CrisisInterventionRequest
from app.security import get_current_user

router = APIRouter(prefix="/api/crisis", tags=["crisis"])


@router.get("", response_model=list[CrisisEventOut])
async def list_crisis_events(
    status_filter: str | None = Query(None, description="按状态过滤：pending_human/comforting/resolved"),
    user_id: int | None = Query(None, description="按用户过滤"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CrisisEventOut]:
    """运营端：危机事件列表，按创建时间倒序"""
    stmt = select(CrisisEvent)
    if status_filter:
        stmt = stmt.where(CrisisEvent.status == status_filter)
    if user_id is not None:
        stmt = stmt.where(CrisisEvent.user_id == user_id)
    stmt = stmt.order_by(CrisisEvent.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    events = result.scalars().all()
    return [CrisisEventOut.model_validate(e) for e in events]


@router.get("/me", response_model=list[CrisisEventOut])
async def list_my_crisis_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CrisisEventOut]:
    """当前用户的危机事件（多用户隔离）"""
    result = await db.execute(
        select(CrisisEvent)
        .where(CrisisEvent.user_id == current_user.id)
        .order_by(CrisisEvent.created_at.desc())
    )
    events = result.scalars().all()
    return [CrisisEventOut.model_validate(e) for e in events]


@router.post("/{event_id}/intervention", response_model=CrisisEventOut)
async def mark_intervention(
    event_id: int,
    body: CrisisInterventionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CrisisEventOut:
    """运营端：标记人工干预结果，可同时标记为已解决"""
    result = await db.execute(select(CrisisEvent).where(CrisisEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="危机事件不存在")

    event.intervention_result = body.intervention_result
    if body.resolved:
        event.status = "resolved"
        event.resolved_at = datetime.now()
    await db.commit()
    await db.refresh(event)
    return CrisisEventOut.model_validate(event)
