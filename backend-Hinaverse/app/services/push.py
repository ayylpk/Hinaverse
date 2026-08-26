"""
推送通道：在线走 WebSocket，离线走极光推送。
极光配置缺失时静默降级（打日志不报错）。

复用 agent_hina/jpush.py 的实现思路，但按用户维度存 reg_id，
不直接 import agent-Hinaverse（本轮要求不 import 它）。
"""
import base64
import logging
from typing import Any

import httpx

from app.config import JPUSH_APP_KEY, JPUSH_MASTER_SECRET, JPUSH_URL

logger = logging.getLogger(__name__)


class PushChannel:
    """
    推送通道单例。

    用法：
        channel = PushChannel()
        # 注册 WS 连接
        channel.register_ws(user_id, websocket)
        # 推送
        await channel.push(user_id, conversation_id, msg_dict)
    """

    def __init__(self) -> None:
        # user_id -> WebSocket 连接（在线时优先走这里）
        self._ws_connections: dict[int, Any] = {}

    # ── WS 连接管理 ──

    def register_ws(self, user_id: int, websocket: Any) -> None:
        """用户上线时调用，记录 WS 连接"""
        self._ws_connections[user_id] = websocket

    def unregister_ws(self, user_id: int) -> None:
        """用户下线时调用"""
        self._ws_connections.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return user_id in self._ws_connections

    # ── 核心推送 ──

    async def push(self, user_id: int, conversation_id: int, msg: dict[str, Any]) -> bool:
        """
        推送给指定用户：在线走 WS，离线走极光。
        msg 是要发给前端的消息对象（含 type 等字段）。
        返回是否成功送达（WS 在线即视为成功；离线看极光结果）。
        """
        ws = self._ws_connections.get(user_id)
        if ws is not None:
            # 在线：直接推 WS
            try:
                await ws.send_json(msg)
                return True
            except Exception as e:
                logger.warning(f"[push] WS 推送失败，尝试极光: {e}")
                # WS 失败时不移除连接，由心跳机制处理；这里降级走极光
                return await self._push_jpush(user_id, msg)
        # 离线：走极光
        return await self._push_jpush(user_id, msg)

    # ── 极光推送 ──

    async def _push_jpush(self, user_id: int, msg: dict[str, Any]) -> bool:
        """离线推送：调极光 REST API。配置缺失时静默降级返回 False。"""
        if not JPUSH_APP_KEY or not JPUSH_MASTER_SECRET:
            logger.info("[push] 极光未配置，静默降级（开发期允许）")
            return False

        # reg_id 从数据库取，这里需要调用方传入或从 msg 带
        # 为简化，reg_id 由调用 push 的地方传入（见 device 路由存到 user.reg_id）
        reg_id = msg.pop("_reg_id", "") if isinstance(msg, dict) else ""
        if not reg_id:
            logger.info(f"[push] 用户 {user_id} 未注册设备，跳过极光推送")
            return False

        # 取消息正文做通知预览
        content = ""
        if msg.get("type") in ("message", "active"):
            inner = msg.get("msg", {})
            content = inner.get("content", "") if isinstance(inner, dict) else str(inner)
        elif msg.get("type") == "system":
            content = msg.get("content", "")

        payload = {
            "platform": "android",
            "audience": {"registration_id": [reg_id]},
            "notification": {
                "alert": content[:120],
                "android": {
                    "title": "日奈",
                    "alert": content[:120],
                    "big_text": content[:2000],
                    "channel_id": "hina_chat",
                    "priority": 2,
                    "category": "message",
                    "extras": {"type": "message", "conversation_id": str(msg.get("conversation_id", ""))},
                },
            },
            "message": {
                "msg_content": content[:500],
                "content_type": "text",
                "title": "日奈",
                "extras": {"type": "message", "conversation_id": str(msg.get("conversation_id", ""))},
            },
            "options": {"apns_production": False, "time_to_live": 86400},
        }

        credentials = f"{JPUSH_APP_KEY}:{JPUSH_MASTER_SECRET}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        headers = {"Authorization": f"Basic {auth_header}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(JPUSH_URL, json=payload, headers=headers)
                data = resp.json()
                if resp.status_code == 200 and data.get("msg_id"):
                    logger.info(f"[push] 极光发送成功: msg_id={data['msg_id']}")
                    return True
                logger.error(f"[push] 极光发送失败: status={resp.status_code}, body={resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"[push] 极光请求异常: {e}")
            return False


# 全局单例，路由和 WS 共用
push_channel = PushChannel()
