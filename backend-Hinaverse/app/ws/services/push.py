"""
离线推送通道：只负责极光推送，不再持有 WS 连接。

WS 连接表已上移给 Hub.OutboundHub（统一出口：在线走 WS，离线调这里）。
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
    离线推送通道：纯极光客户端。

    用法：
        channel = PushChannel()
        # 用户离线时推送（msg 里带 _reg_id 才会真正发极光）
        ok = await channel.push_offline(user_id, msg)
    """

    # ── 核心推送 ──

    async def push_offline(self, user_id: int, msg: dict[str, Any]) -> bool:
        """
        用户离线时走极光推送。
        msg 是发给前端的消息对象（含 type 等字段），可带 _reg_id 指定设备；
        未带 _reg_id（用户没注册设备）时静默跳过，返回 False。
        """
        if not JPUSH_APP_KEY or not JPUSH_MASTER_SECRET:
            logger.info("[push] 极光未配置，静默降级（开发期允许）")
            return False

        reg_id = msg.get("_reg_id", "") if isinstance(msg, dict) else ""
        if not reg_id:
            logger.info(f"[push] 用户 {user_id} 未注册设备，跳过极光推送")
            return False

        # 取消息正文做通知预览
        content = ""
        if msg.get("type") in ("message", "active", "diary_push"):
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


# 全局单例，由 Hub.OutboundHub 持有（离线兜底用）
push_channel = PushChannel()
