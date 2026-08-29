"""
开发期调试路由：触发一次主动消息，验证「生成 → 落库 → 推送」链路通畅。
数据访问走 conversation_repo / message_repo（DAO）。

生产环境应删除或加管理员鉴权。本轮开放调用，但注释清楚。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import conversation_repo, message_repo
from app.schemas import ActiveRequest
from app.security import get_current_user
from app.ws.Hub import outbound_hub
from app.ws.services.agent_service import generate_reply

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/active")
async def trigger_active_message(
    body: ActiveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    主动触发一次日奈消息生成：
    1. 调 agent_service.generate_reply 生成回复（LLM 异步）
    2. 落库（role=hina）
    3. 走推送通道：在线 WS 收到 type=active，离线走极光

    注：DB 操作为同步 DAO 调用（毫秒级），LLM 等待才是大头。
    """
    # 校验会话归属
    conv = conversation_repo.get_owned(db, body.conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    user_profile = {"nickname": current_user.nickname, "avatar": current_user.avatar}

    # 生成回复（历史上下文由 agent checkpoint 按 thread_id 自动累积）
    reply = await generate_reply("（主动消息）", user_profile, user_id=current_user.id)

    # 落库 + 未读 +1（主动消息用户没在线看）
    msg = message_repo.insert_one(db, conv.id, "hina", reply)
    conversation_repo.update_last_message(db, conv, reply, unread_delta=1)

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
