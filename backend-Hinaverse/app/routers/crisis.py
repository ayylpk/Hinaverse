"""
危机事件路由（运营端）：列表查询 / 事件详情 / 标记人工干预结果 / 人工回复 / 接管。
数据访问全部走 crisis_repo / message_repo / conversation_repo（DAO）。

鉴权说明：
  - GET /（全量列表）、POST /{id}/intervention、GET /{id}、POST /{id}/reply、POST /{id}/takeover
    仅管理员（role == "admin"）可用
  - GET /me 是用户端「我的危机事件」，保持原样（任何登录用户）
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import conversation_repo, crisis_repo, message_repo
from app.schemas import (
    CrisisEventDetailOut,
    CrisisEventOut,
    CrisisInterventionRequest,
    CrisisReplyRequest,
    CrisisTakeoverRequest,
    MessageOut,
)
from app.security import get_current_user
from app.ws.Hub import outbound_hub

router = APIRouter(prefix="/api/crisis", tags=["crisis"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """管理员校验：非 admin 一律 403（叠加在 get_current_user 之上）"""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限，仅管理员可访问")
    return current_user


def _with_nickname(out: CrisisEventOut, event) -> CrisisEventOut:
    """从事件关联的 user 关系填充 user_nickname（列表/详情共用）"""
    out.user_nickname = event.user.nickname if event.user else ""
    return out


@router.get("", response_model=list[CrisisEventOut])
def list_crisis_events(
    status_filter: str | None = Query(None, description="按状态过滤：pending_human/comforting/resolved"),
    risk_level: str | None = Query(None, description="按风险等级过滤：高危/中危/低危"),
    user_id: int | None = Query(None, description="按用户过滤"),
    limit: int = Query(200, ge=1, le=500),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[CrisisEventOut]:
    """运营端：危机事件列表，按创建时间倒序（仅管理员）"""
    events = crisis_repo.list_filter(
        db, status_filter=status_filter, risk_level=risk_level, user_id=user_id, limit=limit
    )
    return [_with_nickname(CrisisEventOut.model_validate(e), e) for e in events]


@router.get("/me", response_model=list[CrisisEventOut])
def list_my_crisis_events(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CrisisEventOut]:
    """当前用户的危机事件（多用户隔离）"""
    events = crisis_repo.list_by_user(db, current_user.id)
    return [CrisisEventOut.model_validate(e) for e in events]


@router.get("/{event_id}", response_model=CrisisEventDetailOut)
def get_crisis_event(
    event_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CrisisEventDetailOut:
    """事件详情（仅管理员）：危机事件字段 + 关联会话最近 20 条消息 + 高危摘要（在 summary 内）"""
    event = crisis_repo.get_by_id(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="危机事件不存在")

    detail = CrisisEventDetailOut.model_validate(event)
    detail.user_nickname = event.user.nickname if event.user else ""
    if event.conversation_id is not None:
        recent = message_repo.get_recent(db, event.conversation_id, limit=20)
        detail.messages = [MessageOut.model_validate(m) for m in recent]
    return detail


@router.post("/{event_id}/intervention", response_model=CrisisEventOut)
def mark_intervention(
    event_id: int,
    body: CrisisInterventionRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CrisisEventOut:
    """运营端：标记人工干预结果，可同时标记为已解决（仅管理员）"""
    event = crisis_repo.get_by_id(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="危机事件不存在")
    event = crisis_repo.mark_intervention(db, event, body.intervention_result, resolved=body.resolved)
    out = CrisisEventOut.model_validate(event)
    out.user_nickname = event.user.nickname if event.user else ""
    return out


@router.post("/{event_id}/reply", response_model=MessageOut)
async def reply_crisis_event(
    event_id: int,
    body: CrisisReplyRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MessageOut:
    """
    运营人工回复（仅管理员）：
    以 operator 角色落库——用户端渲染成日奈同款气泡（接管期间人工=代日奈发言），
    与 system 角色的"人工客服已接管"提示区分开；更新会话最后一条，
    并实时推送给用户（在线 WS / 离线极光，走 outbound_hub 统一出口）。
    """
    event = crisis_repo.get_by_id(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="危机事件不存在")
    if event.conversation_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该事件无关联会话")

    msg = message_repo.insert_one(db, event.conversation_id, "operator", body.content)
    conv = conversation_repo.get_by_id(db, event.conversation_id)
    if conv is not None:
        conversation_repo.update_last_message(db, conv, body.content)
    # 推送给用户端（type=message，前端把 operator 归到日奈气泡样式渲染）
    await outbound_hub.send_message(event.user_id, event.conversation_id, {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "time": msg.time,
    })
    return MessageOut.model_validate(msg)


@router.post("/{event_id}/takeover", response_model=CrisisEventOut)
def takeover_crisis_event(
    event_id: int,
    body: CrisisTakeoverRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CrisisEventOut:
    """
    人工接管/释放（仅管理员）：
      takeover=True  仅 pending_human → handling（人工处理中），否则 409
      takeover=False 仅 handling → 还原 pending_human（待人工），已 resolved 则 409
    """
    event = crisis_repo.get_by_id(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="危机事件不存在")

    if body.takeover:
        if event.status != "pending_human":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该事件已被接管或处理，无法接管",
            )
        event = crisis_repo.set_status(db, event, "handling")
    else:
        if event.status == "resolved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该事件已处理完成，无法释放",
            )
        if event.status != "handling":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该事件当前无需释放",
            )
        event = crisis_repo.set_status(db, event, "pending_human")

    out = CrisisEventOut.model_validate(event)
    out.user_nickname = event.user.nickname if event.user else ""
    return out
