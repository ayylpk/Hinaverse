"""
会话路由：列表 / 新建 / 消息游标分页 / 已读清零。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Conversation, Message, User
from app.schemas import ConversationOut, MessageListResponse, MessageOut
from app.security import get_current_user
from app.services.agent_service import generate_reply
from app.utils import now_hm

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

# 新建会话时日奈的开场白
_OPENING_LINES = [
    "我是日奈。夜空已经安静了，你可以开始说第一颗星了。",
    "欢迎回来。今天想聊点什么？不用急，慢慢说。",
    "你来了。我把灯调暗了一点，这样说话会更自在。",
]


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationOut]:
    """当前用户的会话列表，按创建时间倒序，含 last_message 和 unread_count"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
    )
    conversations = result.scalars().all()
    return [ConversationOut.model_validate(c) for c in conversations]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    """
    新建会话：同步生成日奈的开场白消息并落库。
    这样前端一打开会话就能看到日奈的欢迎语。
    """
    import random
    conv = Conversation(user_id=current_user.id, title="新会话", unread_count=0)
    db.add(conv)
    await db.flush()  # 拿到 conv.id

    opening = random.choice(_OPENING_LINES)
    msg = Message(
        conversation_id=conv.id,
        role="hina",
        content=opening,
        time=now_hm(),
    )
    db.add(msg)
    conv.last_message = opening
    await db.commit()
    await db.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: int,
    before_id: int | None = Query(None, description="返回 id < before_id 的消息，用于游标分页"),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    """
    游标分页拉取历史消息。
    - 默认拉最新的 limit 条
    - 传 before_id 时拉该 id 之前的 limit 条（向上翻页）
    - 返回 has_more 标识是否还有更早消息
    """
    # 鉴权：会话必须属于当前用户
    conv = await _get_conversation(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    # 按 id 倒序取 limit 条，再反转为正序返回（前端按时间正序展示）
    stmt = stmt.order_by(Message.id.desc()).limit(limit)
    result = await db.execute(stmt)
    messages = list(reversed(result.scalars().all()))

    # 判断是否还有更早消息
    has_more = False
    if messages:
        earliest_id = messages[0].id
        count_result = await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation_id, Message.id < earliest_id
            )
        )
        has_more = count_result.scalar() > 0

    return MessageListResponse(
        messages=[MessageOut.model_validate(m) for m in messages],
        has_more=has_more,
    )


@router.post("/{conversation_id}/read")
async def mark_read(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户打开会话读到最后一条时，未读数清零"""
    conv = await _get_conversation(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    conv.unread_count = 0
    await db.commit()
    return {"ok": True}


async def _get_conversation(
    db: AsyncSession, conversation_id: int, user_id: int
) -> Conversation | None:
    """取出属于指定用户的会话，越权返回 None"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    return result.scalar_one_or_none()
