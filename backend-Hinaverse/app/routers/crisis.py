"""
危机事件路由（运营端）：列表查询 / 标记人工干预结果。
数据访问全部走 crisis_repo（DAO）。

注：当前项目无「管理员」角色概念，列表接口暂对所有登录用户开放。
生产环境应叠加管理员鉴权（如 User.role == "admin"）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import crisis_repo
from app.schemas import CrisisEventOut, CrisisInterventionRequest
from app.security import get_current_user

router = APIRouter(prefix="/api/crisis", tags=["crisis"])


@router.get("", response_model=list[CrisisEventOut])
def list_crisis_events(
    status_filter: str | None = Query(None, description="按状态过滤：pending_human/comforting/resolved"),
    user_id: int | None = Query(None, description="按用户过滤"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CrisisEventOut]:
    """运营端：危机事件列表，按创建时间倒序"""
    events = crisis_repo.list_filter(db, status_filter=status_filter, user_id=user_id, limit=limit)
    return [CrisisEventOut.model_validate(e) for e in events]


@router.get("/me", response_model=list[CrisisEventOut])
def list_my_crisis_events(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CrisisEventOut]:
    """当前用户的危机事件（多用户隔离）"""
    events = crisis_repo.list_by_user(db, current_user.id)
    return [CrisisEventOut.model_validate(e) for e in events]


@router.post("/{event_id}/intervention", response_model=CrisisEventOut)
def mark_intervention(
    event_id: int,
    body: CrisisInterventionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CrisisEventOut:
    """运营端：标记人工干预结果，可同时标记为已解决"""
    event = crisis_repo.get_by_id(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="危机事件不存在")
    event = crisis_repo.mark_intervention(db, event, body.intervention_result, resolved=body.resolved)
    return CrisisEventOut.model_validate(event)
