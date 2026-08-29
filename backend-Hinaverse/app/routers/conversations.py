"""
会话路由：列表 / 新建 / 消息游标分页 / 已读清零。
数据访问全部走 conversation_repo / message_repo（DAO）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Conversation, Message, User
from app.repositories import conversation_repo, message_repo
from app.schemas import ConversationOut, MessageListResponse, MessageOut
from app.security import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationOut]:
    """当前用户的会话列表，按创建时间倒序，含 last_message 和 unread_count"""
    return [ConversationOut.model_validate(c) for c in conversation_repo.list_by_user(db, current_user.id)]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationOut:
    """
    新建会话：同步生成日奈的开场白消息并落库。
    这样前端一打开会话就能看到日奈的欢迎语。
    """
    conv = conversation_repo.create_with_opening(db, current_user.id)
    return ConversationOut.model_validate(conv)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: int,
    before_id: int | None = Query(None, description="返回 id < before_id 的消息，用于游标分页"),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """
    游标分页拉取历史消息。
    - 默认拉最新的 limit 条
    - 传 before_id 时拉该 id 之前的 limit 条（向上翻页）
    - 返回 has_more 标识是否还有更早消息
    """
    # 鉴权：会话必须属于当前用户
    if conversation_repo.get_owned(db, conversation_id, current_user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    messages, has_more = message_repo.list_page(db, conversation_id, before_id, limit)
    return MessageListResponse(
        messages=[MessageOut.model_validate(m) for m in messages],
        has_more=has_more,
    )


@router.post("/{conversation_id}/read")
def mark_read(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """用户打开会话读到最后一条时，未读数清零"""
    conv = conversation_repo.get_owned(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    conversation_repo.mark_read(db, conv)
    return {"ok": True}
