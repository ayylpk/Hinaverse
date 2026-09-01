"""
Hub 层：WS 消息的收发中心（两个 Hub）。

- InboundHub  用户发送的信息（客户端 → 服务端）。
              按 type 分发到已注册的 handler。Hub 只管路由，业务留在 ws.py 里。
- OutboundHub 服务端下发的信息（服务端 → 客户端）。
              统一出口：同一条 push 命令，在线用户走 WS、离线用户走极光。
              WS 连接表（register_ws / unregister_ws / is_online）也归它管。

设计约定：
    1. InboundHub 只做「type → handler」的分发表。加新消息类型 = 注册新 handler，
       不改 Hub 本身（对应 Java 里的一个 Router）。
    2. OutboundHub 是「给用户发东西」的唯一入口，REST 路由和 WS 都通过它下发，
       不直接碰单个 websocket 连接。
    3. PushChannel 已瘦身为纯离线极光客户端，由 OutboundHub 持有作兜底。
"""
import asyncio
import logging
from typing import Any, Awaitable, Callable

from app.ws.services.push import PushChannel, push_channel

logger = logging.getLogger(__name__)

# handler 签名：收到一条客户端消息后做业务处理（业务在 ws.py，这里不写）
Handler = Callable[[Any, Any, dict[str, Any]], Awaitable[None]]


class InboundHub:
    """用户发送的信息：按 type 分发到注册的 handler。只路由，不决策。"""

    def __init__(self) -> None:
        # msg_type(str) -> handler(websocket, user, data)
        self._handlers: dict[str, Handler] = {}

    def register(self, msg_type: str, handler: Handler) -> None:
        """注册某消息类型的处理入口。未来加日记等新类型，就在这里多注册一行。"""
        self._handlers[msg_type] = handler

    async def handle(self, msg_type: str, websocket: Any, user: Any, data: dict[str, Any]) -> bool:
        """
        分发一条用户消息。
        返回是否被处理；未注册的类型返回 False（调用方忽略即可，不报错）。
        """
        handler = self._handlers.get(msg_type)
        if handler is None:
            return False
        await handler(websocket, user, data)
        return True


class OutboundHub:
    """服务端下发的信息：统一出口。在线走 WS，失败/离线降级走极光。"""

    def __init__(self, offline_push: PushChannel) -> None:
        self._offline_push = offline_push  # 纯极光客户端，离线兜底
        # user_id -> WebSocket 连接（在线表）
        self._ws_connections: dict[int, Any] = {}
        # user_id -> reg_id 查询回调（应用层启动时注入；Hub 自身不碰 DB）
        self._reg_id_lookup: Callable[[int], str] | None = None

    # ── WS 连接管理 ──

    def register_ws(self, user_id: int, websocket: Any) -> None:
        """用户上线时调用，记录 WS 连接"""
        self._ws_connections[user_id] = websocket

    def unregister_ws(self, user_id: int) -> None:
        """用户下线时调用"""
        self._ws_connections.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return user_id in self._ws_connections

    # ── reg_id 注入（修 9/1 断链：push_offline 只认 msg 里的 _reg_id）──

    def register_reg_id_lookup(self, lookup: Callable[[int], str]) -> None:
        """注册 reg_id 查询回调（user_id -> reg_id，查不到返回空串）。启动时挂，Hub 不 import DB。"""
        self._reg_id_lookup = lookup

    async def _with_reg_id(self, user_id: int, msg: dict[str, Any]) -> dict[str, Any]:
        """降级极光前把用户 reg_id 塞进 msg；查库是同步操作，丢给线程池别堵事件循环。"""
        if self._reg_id_lookup is None or msg.get("_reg_id"):
            return msg
        try:
            reg_id = await asyncio.to_thread(self._reg_id_lookup, user_id)
        except Exception as e:
            logger.warning(f"[hub] 查 reg_id 失败（跳过极光注入）: {e}")
            return msg
        if reg_id:
            msg = {**msg, "_reg_id": reg_id}  # 拷贝，不污染调用方 dict
        return msg

    # ── 核心发送：所有下发最终都走这里 ──

    async def push(self, user_id: int, msg: dict[str, Any]) -> bool:
        """
        给指定用户下发一条消息（msg 含 type 等字段）。
        在线 → 直接推 WS（视为成功）；WS 失败或离线 → 降级极光。
        返回是否送达（WS 在线即 true；极光看其返回）。
        """
        ws = self._ws_connections.get(user_id)
        if ws is not None:
            try:
                await ws.send_json(msg)
                return True
            except Exception as e:
                logger.warning(f"[hub] WS 推送失败，尝试极光: {e}")
                # WS 失败不移除连接，交给心跳机制清理；这里降级走极光
                return await self._offline_push.push_offline(user_id, await self._with_reg_id(user_id, msg))
        # 离线：走极光
        return await self._offline_push.push_offline(user_id, await self._with_reg_id(user_id, msg))

    # ── 协议便捷封装（对应用户可能收到的各类型）──

    async def send_message(self, user_id: int, conversation_id: int, msg: dict[str, Any]) -> bool:
        """下发一条对话消息（type=message，msg 含 id/role/content/time）"""
        return await self.push(user_id, {
            "type": "message",
            "conversation_id": conversation_id,
            "msg": msg,
        })

    async def send_typing(self, user_id: int, conversation_id: int) -> bool:
        """告知前端「日奈正在输入」"""
        return await self.push(user_id, {"type": "typing", "conversation_id": conversation_id})

    async def send_system(self, user_id: int, content: str) -> bool:
        """下发一条系统提示（如"这条消息无法发送"）"""
        return await self.push(user_id, {"type": "system", "content": content})

    async def send_active(self, user_id: int, conversation_id: int, msg: dict[str, Any]) -> bool:
        """主动消息（服务端主动发起，如日终总结），msg 含 id/role/content/time"""
        return await self.push(user_id, {
            "type": "active",
            "conversation_id": conversation_id,
            "msg": msg,
        })

    async def send_diary(self, user_id: int, diary: dict[str, Any]) -> bool:
        """推送日记（日终 _daily_summary_text 落库后主动下发），diary 含 id/content/time"""
        return await self.push(user_id, {"type": "diary_push", "diary": diary})


# ── 全局单例：REST 路由和 WS 共用同一个 Hub ──
inbound_hub = InboundHub()
outbound_hub = OutboundHub(push_channel)