"""
WebSocket 端点：ws://host/ws?token=<jwt>

职责：
- 握手校验 token，失败关闭连接（不接受）
- 维护连接到 push_channel（在线推送走这里）
- 心跳：每 30s 发 ping，60s 无任何入站消息则断开
- 处理 {type:"message"}：落库用户消息 → 发 typing → 生成回复 → 落库 → 推送
"""
import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import SyncSessionLocal
from app.models import Conversation, Message, User
from app.security import decode_token
from app.services.agent_service import generate_reply
from app.services.push import push_channel
from app.utils import now_hm
from app.ws import protocol as P

logger = logging.getLogger(__name__)

router = APIRouter()

# 心跳参数
PING_INTERVAL = 30      # 每 30s 发一次 ping
IDLE_TIMEOUT = 60       # 60s 无入站消息则断开


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    # ── 1. 握手校验 token ──
    token = websocket.query_params.get("token") or ""
    user = await _authenticate(token)
    if user is None:
        # 校验失败：接受后立即关闭，code=4003 对应鉴权失败
        await websocket.accept()
        await websocket.close(code=4003, reason="invalid token")
        return

    await websocket.accept()
    push_channel.register_ws(user.id, websocket)
    logger.info(f"[ws] 用户 {user.id}({user.nickname}) 已连接")

    # 最后一次收到消息的时间戳，用于心跳判断
    last_rx = time.monotonic()

    # ── 2. 心跳任务：定期发 ping + 检测空闲超时 ──
    async def heartbeat() -> None:
        nonlocal last_rx
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                now = time.monotonic()
                if now - last_rx > IDLE_TIMEOUT:
                    logger.info(f"[ws] 用户 {user.id} 心跳超时，断开")
                    await websocket.close(code=4000, reason="idle timeout")
                    return
                # 发应用层 ping
                try:
                    await websocket.send_json({"type": P.TYPE_PING})
                except Exception:
                    return
        except asyncio.CancelledError:
            pass

    hb_task = asyncio.create_task(heartbeat())

    # ── 3. 接收循环 ──
    try:
        while True:
            raw = await websocket.receive_text()
            last_rx = time.monotonic()

            try:
                data = json.loads(raw)
            except ValueError:
                continue

            msg_type = data.get("type")

            # 心跳响应：只更新 last_rx，不做处理
            if msg_type == P.TYPE_PONG:
                continue

            # 用户发消息
            if msg_type == P.TYPE_MESSAGE:
                await _handle_message(websocket, user, data)
            # 其他类型忽略
    except WebSocketDisconnect:
        logger.info(f"[ws] 用户 {user.id} 断开连接")
    except Exception as e:
        logger.error(f"[ws] 用户 {user.id} 异常: {e}")
    finally:
        hb_task.cancel()
        push_channel.unregister_ws(user.id)


async def _authenticate(token: str) -> User | None:
    """从 token 解析并查库返回用户，无效返回 None"""
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except Exception:
        return None

    with SyncSessionLocal() as db:
        result = db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


async def _handle_message(websocket: WebSocket, user: User, data: dict[str, Any]) -> None:
    """处理一条用户消息：校验会话 → 落库用户消息 → typing → 生成回复 → 落库 → 推送"""
    conversation_id = data.get("conversation_id")
    content = (data.get("content") or "").strip()
    if not conversation_id or not content:
        return

    with SyncSessionLocal() as db:
        # 校验会话归属
        conv = db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user.id
            )
        ).scalar_one_or_none()
        if conv is None:
            await websocket.send_json({"type": P.TYPE_SYSTEM, "content": "会话不存在"})
            return

        # 1. 落库用户消息
        user_msg = Message(
            conversation_id=conv.id, role="user", content=content, time=now_hm()
        )
        db.add(user_msg)
        conv.last_message = content
        db.commit()
        db.refresh(user_msg)

        # 2. 通知前端「正在输入」
        await websocket.send_json({"type": P.TYPE_TYPING, "conversation_id": conv.id})

        # 3. 取最近历史上下文
        hist = db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.desc())
            .limit(20)
        ).scalars().all()
        history = [{"role": m.role, "content": m.content} for m in reversed(hist)]
        user_profile = {"nickname": user.nickname, "avatar": user.avatar}

        # 4. 生成回复（mock，真实接入时只改 agent_service）
        reply = await generate_reply(content, user_profile, history)

        # 5. 落库日奈消息
        hina_msg = Message(
            conversation_id=conv.id, role="hina", content=reply, time=now_hm()
        )
        db.add(hina_msg)
        conv.last_message = reply
        db.commit()
        db.refresh(hina_msg)

        # 6. 推送给前端
        await websocket.send_json({
            "type": P.TYPE_MSG,
            "conversation_id": conv.id,
            "msg": {
                "id": hina_msg.id,
                "role": hina_msg.role,
                "content": hina_msg.content,
                "time": hina_msg.time,
            },
        })
