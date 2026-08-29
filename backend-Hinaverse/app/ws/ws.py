"""
WebSocket 端点：ws://host/ws?token=<jwt>

职责：
- 握手校验 token，失败关闭连接（不接受）
- 维护连接到 outbound_hub（在线推送走这里）
- 心跳：每 30s 发 ping，60s 无任何入站消息则断开
- 消息分发：receive 循环拿到 {type:...} 后丢给 inbound_hub，
  由已注册的 handler 处理（如 message → 落库/安全检测/生成回复/推送）

Hub 约定（见 Hub.py）：
  InboundHub  只管 type → handler 分发，业务留在本文件的 _handle_message
  OutboundHub 统一出口，所有下发（回复/typing/system/主动消息）都经过它
"""
import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import SyncSessionLocal
from app.models import Conversation, CrisisEvent, Message, User
from app.security import decode_token
from app.services.agent_memory import echo_async
from app.ws.Hub import inbound_hub, outbound_hub
from app.ws.services.agent_service import generate_reply
from app.ws.services.safety_service import (
    check_message,
    generate_crisis_summary,
    generate_high_risk_reply,
)
from app.utils import now_hm
from app.ws import protocol as P

logger = logging.getLogger(__name__)

router = APIRouter()

# 心跳参数
PING_INTERVAL = 30      # 每 30s 发一次 ping
IDLE_TIMEOUT = 60       # 60s 无入站消息则断开


# ── 注册 InboundHub 处理器：以后新增消息类型（如 diary），在这里多注册一个 ──
inbound_hub.register(P.TYPE_MESSAGE, lambda ws, user, data: _handle_message(user, data))


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
    outbound_hub.register_ws(user.id, websocket)
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

    # ── 3. 接收循环：交给 InboundHub 分发 ──
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

            # 分发到 InboundHub；未注册的类型（如预留的 diary）直接忽略
            handled = await inbound_hub.handle(msg_type, websocket, user, data)
            if not handled:
                logger.debug(f"[ws] 用户 {user.id} 发送了未注册类型: {msg_type}")
    except WebSocketDisconnect:
        logger.info(f"[ws] 用户 {user.id} 断开连接")
    except Exception as e:
        logger.error(f"[ws] 用户 {user.id} 异常: {e}")
    finally:
        hb_task.cancel()
        outbound_hub.unregister_ws(user.id)


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


async def _handle_message(user: User, data: dict[str, Any]) -> None:
    """
    处理一条用户消息：校验会话 → 落库用户消息 → 安全检测 → 生成回复 → 落库 → 推送。
    从 InboundHub 注册进来，所有下发走 outbound_hub（在线 WS / 离线极光）。
    """
    conversation_id = data.get("conversation_id")
    content = (data.get("content") or "").strip()
    if not conversation_id or not content:
        return

    with SyncSessionLocal() as db:
        # 0. 校验会话归属（越权返回，什么都不做）
        conv = db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user.id
            )
        ).scalar_one_or_none()
        if conv is None:
            await outbound_hub.send_system(user.id, "会话不存在")
            return

        # 1. 落库用户消息
        user_msg = Message(
            conversation_id=conv.id, role="user", content=content, time=now_hm()
        )
        db.add(user_msg)
        conv.last_message = content
        db.commit()
        db.refresh(user_msg)

        # 1.5 记忆管线回显（后台异步，不阻塞回复；role 分清是谁说的话）
        echo_async(user.id, "user", content)

        # 2. 取最近历史上下文（供安全检测 + agent 复用）
        hist = db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.desc())
            .limit(20)
        ).scalars().all()
        history = [{"role": m.role, "content": m.content} for m in reversed(hist)]
        # 安全检测用的最近上下文字符串（最近 5 条）
        recent_context = "\n".join(
            f"{h['role']}: {h['content']}" for h in history[-5:]
        )

        # 3. 安全检测（三阶段漏斗）
        safety = await check_message(user.id, content, recent_context)

        # ── 分支 A：违禁词拦截 ──
        if safety.blocked:
            # 不进入 agent，记录事件后直接返回拦截提示
            _save_crisis_event(db, user.id, conv.id, safety, status="pending_human")
            db.commit()
            await outbound_hub.send_system(user.id, "这条消息无法发送。")
            return

        # ── 分支 B：高危 → 过渡话术 + 转人工，不调 agent ──
        if safety.risk_level == "高危":
            transition = await generate_high_risk_reply(content)
            # 落库危机事件 + 自动生成摘要（best-effort）
            summary = await generate_crisis_summary(
                trigger_reason=safety.reason,
                recent_messages=recent_context,
                llm_comfort_log=transition,
            )
            _save_crisis_event(
                db, user.id, conv.id, safety,
                status="pending_human", summary=summary, comfort_log=transition,
            )
            db.commit()
            # 落库日奈过渡消息
            hina_msg = Message(
                conversation_id=conv.id, role="hina", content=transition, time=now_hm()
            )
            db.add(hina_msg)
            conv.last_message = transition
            db.commit()
            db.refresh(hina_msg)
            # 高危转人工话术也是日奈说的话，同样进记忆管线（后台异步）
            echo_async(user.id, "ai", transition)
            await outbound_hub.send_message(user.id, conv.id, {
                "id": hina_msg.id,
                "role": hina_msg.role,
                "content": hina_msg.content,
                "time": hina_msg.time,
            })
            return

        # ── 分支 C：中/低危 → 正常 agent，但开启深度安抚 ──
        needs_deep_comfort = safety.risk_level in ("中危")
        if needs_deep_comfort:
            # 落库危机事件（LLM 安抚中）
            _save_crisis_event(db, user.id, conv.id, safety, status="comforting")
            db.commit()

        # 4. 通知前端「正在输入」
        await outbound_hub.send_typing(user.id, conv.id)

        # 5. 生成回复（真实接入 agent 图：先回复，压缩后台异步）
        user_profile = {"nickname": user.nickname, "avatar": user.avatar}
        reply = await generate_reply(
            content,
            user_profile,
            history,
            needs_deep_comfort=needs_deep_comfort,
            user_id=user.id,
        )

        # 6. 落库日奈消息
        hina_msg = Message(
            conversation_id=conv.id, role="hina", content=reply, time=now_hm()
        )
        db.add(hina_msg)
        conv.last_message = reply
        db.commit()
        db.refresh(hina_msg)

        # 6.5 记忆管线回显（后台异步）：日奈的回复是 ai 角色
        echo_async(user.id, "ai", reply)

        # 7. 推送给前端
        await outbound_hub.send_message(user.id, conv.id, {
            "id": hina_msg.id,
            "role": hina_msg.role,
            "content": hina_msg.content,
            "time": hina_msg.time,
        })


def _save_crisis_event(
    db,
    user_id: int,
    conversation_id: int,
    safety,
    status: str,
    summary: dict | None = None,
    comfort_log: str = "",
) -> None:
    """落库一条危机事件（多用户隔离：带 user_id）"""
    event = CrisisEvent(
        user_id=user_id,
        conversation_id=conversation_id,
        risk_level=safety.risk_level,
        trigger=safety.reason,
        signal=safety.signal,
        status=status,
        summary=summary,
        comfort_log=comfort_log,
    )
    db.add(event)