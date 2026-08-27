"""
开发期调试路由：触发一次主动消息，验证「生成 → 落库 → 推送」链路通畅。

生产环境应删除或加管理员鉴权。本轮开放调用，但注释清楚。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Conversation, Message, User
from app.schemas import ActiveRequest
from app.security import get_current_user
from app.ws.Hub import outbound_hub
from app.ws.services.agent_service import generate_reply
from app.utils import now_hm

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/active")
async def trigger_active_message(
    body: ActiveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    主动触发一次日奈消息生成：
    1. 调 agent_service.generate_reply 生成回复
    2. 落库（role=hina）
    3. 走推送通道：在线 WS 收到 type=active，离线走极光
    """
    # 校验会话归属
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == body.conversation_id, Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    # 取最近几条历史作为上下文
    hist_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.id.desc())
        .limit(10)
    )
    history = [
        {"role": m.role, "content": m.content} for m in reversed(hist_result.scalars().all())
    ]
    user_profile = {"nickname": current_user.nickname, "avatar": current_user.avatar}

    # 生成回复
    reply = await generate_reply("（主动消息）", user_profile, history)

    # 落库
    msg = Message(
        conversation_id=conv.id,
        role="hina",
        content=reply,
        time=now_hm(),
    )
    db.add(msg)
    conv.last_message = reply
    conv.unread_count += 1
    await db.commit()
    await db.refresh(msg)

    # 推送：统一走 outbound_hub（在线 WS，离线极光；_reg_id 给极光用）
    push_msg = {
        "type": "active",
        "conversation_id": conv.id,
        "msg": {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "time": msg.time,
        },
        "_reg_id": current_user.reg_id,
    }
    delivered = await outbound_hub.push(current_user.id, push_msg)

    return {"ok": True, "delivered": delivered, "message": reply}
