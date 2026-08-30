"""
WebSocket 端点：ws://host/ws?token=<jwt>

职责：
- 握手校验 token，失败关闭连接（不接受）
- 维护连接到 outbound_hub（在线推送走这里）
- 心跳：每 30s 发 ping，60s 无任何入站消息则断开
- 消息分发：receive 循环拿到 {type:...} 后丢给 inbound_hub，
  由已注册的 handler 处理（如 message → 落库/安全检测/生成回复/推送）

数据访问：全部走 app/repositories/（DAO），本文件不裸写查询。
DB 为同步 Session（SyncSessionLocal），在 async 流程里直接调用毫秒级 CRUD，
与之前 SyncSessionLocal 用法一致。

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

from app.database import SyncSessionLocal
from app.models import User
from app.repositories import (
    conversation_repo,
    crisis_repo,
    high_risk_repo,
    message_repo,
    user_repo,
)
from app.security import decode_token
from app.services.agent_memory import echo_async
from app.ws.Hub import inbound_hub, outbound_hub
from app.ws.services.agent_service import generate_reply
from app.ws.services.safety_service import (
    check_message,
    generate_high_risk_summary,
)
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
        return user_repo.get_by_id(db, user_id)


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
        conv = conversation_repo.get_owned(db, conversation_id, user.id)
        if conv is None:
            await outbound_hub.send_system(user.id, "会话不存在")
            return

        # 1. 落库用户消息 + 更新会话最后一条
        message_repo.insert_one(db, conv.id, "user", content)
        conversation_repo.update_last_message(db, conv, content)

        # 1.5 记忆管线回显（后台异步，不阻塞回复；role 分清是谁说的话）
        echo_async(user.id, "user", content)

        # 1.6 人工接管：该会话存在 handling（人工处理中）事件 → agent 层 interrupt
        #     （图在 wait_human 节点用 LangGraph 原生 interrupt 暂停，不产自动回复），
        #     这里落一条系统提示并推送；运营提交干预结果（resolved）后 handling 消失，
        #     下一条消息不再传 human_takeover，agent 自动回复自动恢复
        if any(e.conversation_id == conv.id for e in crisis_repo.list_by_status(db, user.id, "handling")):
            user_profile = {"nickname": user.nickname, "avatar": user.avatar}
            reply = await generate_reply(content, user_profile, human_takeover=True, user_id=user.id)
            if reply is None:
                tip = message_repo.insert_one(db, conv.id, "system", "人工客服已接管对话，请稍候，会由人工回复你。")
                conversation_repo.update_last_message(db, conv, tip.content)
                await outbound_hub.send_message(user.id, conv.id, {
                    "id": tip.id,
                    "role": tip.role,
                    "content": tip.content,
                    "time": tip.time,
                })
            return

        # 2. 取最近历史上下文（供安全检测 + agent 复用）
        history = [
            {"role": m.role, "content": m.content}
            for m in message_repo.get_recent(db, conv.id, limit=20)
        ]
        # 安全检测用的最近上下文字符串（最近 5 条）
        recent_context = "\n".join(
            f"{h['role']}: {h['content']}" for h in history[-5:]
        )

        # 3. 安全检测（三阶段漏斗）
        safety = await check_message(user.id, content, recent_context)

        # ── 分支 A：违禁词拦截 ──
        if safety.blocked:
            # 不进入 agent，记录事件后直接返回拦截提示
            crisis_repo.create(
                db, user.id, conv.id, safety.risk_level,
                trigger=safety.reason, signal=safety.signal, status="pending_human",
            )
            await outbound_hub.send_system(user.id, "这条消息无法发送。")
            return

        # ── 分支 B：高危 → 快速摘要落库 + AI 持续深度安抚（引导热线，不结束对话）──
        if safety.risk_level == "高危":
            # 1. 快速摘要（最近 10 条对话浓缩，短超时 + 截断兜底）→ 独立表落库
            recent_10 = "\n".join(f"{h['role']}: {h['content']}" for h in history[-10:])
            summary = await generate_high_risk_summary(recent_10)
            high_risk_repo.create_summary(db, user.id, summary)
            # 2. 危机事件落库（pending_human，人工入口记录；summary 存新摘要）
            crisis_repo.create(
                db, user.id, conv.id, "高危",
                trigger=safety.reason, signal=safety.signal,
                status="pending_human", summary={"quick_summary": summary},
            )
            needs_deep_comfort = True
            high_risk = True
        else:
            # ── 分支 C：中/低危 → 正常 agent + 深度安抚（任务书：中/低危都送 LLM 深度安抚）──
            needs_deep_comfort = safety.risk_level in ("中危", "低危")
            high_risk = False
            if needs_deep_comfort:
                # 落库危机事件（LLM 安抚中）
                crisis_repo.create(
                    db, user.id, conv.id, safety.risk_level,
                    trigger=safety.reason, signal=safety.signal, status="comforting",
                )

        # 4. 通知前端「正在输入」
        await outbound_hub.send_typing(user.id, conv.id)

        # 5. 生成回复（真实接入 agent 图：先回复，压缩后台异步；高危也走 AI 陪伴）
        user_profile = {"nickname": user.nickname, "avatar": user.avatar}
        reply = await generate_reply(
            content,
            user_profile,
            needs_deep_comfort=needs_deep_comfort,
            high_risk=high_risk,
            user_id=user.id,
        )

        # 6. 落库日奈消息 + 更新会话最后一条
        hina_msg = message_repo.insert_one(db, conv.id, "hina", reply)
        conversation_repo.update_last_message(db, conv, reply)

        # 6.5 记忆管线回显（后台异步）：日奈的回复是 ai 角色
        echo_async(user.id, "ai", reply)

        # 7. 推送给前端
        await outbound_hub.send_message(user.id, conv.id, {
            "id": hina_msg.id,
            "role": hina_msg.role,
            "content": hina_msg.content,
            "time": hina_msg.time,
        })
