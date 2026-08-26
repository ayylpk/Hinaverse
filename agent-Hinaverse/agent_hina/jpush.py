"""
极光推送工具 —— 从服务器端向 Android 设备发送推送通知。

多用户版：reg_id 不再全局单例，由调用方按用户传入，用户间推送互不干扰。
（用户 reg_id 的存取由 backend-Hinaverse 的 User.reg_id 字段管理）

用法:
    from agent_hina.jpush import send_push

    await send_push(
        reg_id="用户设备的极光 registration_id",
        title="日奈的日记",
        body="2026年7月29日 日记已写好",
        extras={"type": "diary", "target_id": "20260729"}
    )
"""
import base64
import logging
import os

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

JPUSH_URL = "https://api.jpush.cn/v3/push"

# ── 极光配置（.env 由 load_dotenv 加载 / Docker 由 env_file 注入）──
JPUSH_APP_KEY = os.getenv("JPUSH_APP_KEY", "")
JPUSH_MASTER_SECRET = os.getenv("JPUSH_MASTER_SECRET", "")


def _make_auth() -> str:
    """生成 Basic Auth 头"""
    credentials = f"{JPUSH_APP_KEY}:{JPUSH_MASTER_SECRET}"
    return base64.b64encode(credentials.encode()).decode()


async def send_push(
    reg_id: str,
    title: str,
    body: str,
    extras: dict | None = None,
    channel: str = "hina_diary",
) -> bool:
    """
    通过极光推送向指定设备发送通知。

    Args:
        reg_id:  目标设备极光 registration_id（按用户传入，多用户隔离的关键）
        title:   通知标题
        body:    通知正文（大文本会自动在通知栏展开）
        extras:  附加键值对，用户点击通知时传给 app 用于页面路由
                 例: {"type": "diary", "target_id": "20260729"}
        channel: Android 通知频道 ID（diary / chat 对应不同的通知分类）

    Returns:
        True 发送成功，False 发送失败
    """
    if not reg_id:
        logger.info("[jpush] reg_id 为空，跳过推送（多用户接入后由调用方传入用户设备 ID）")
        return False
    if not JPUSH_APP_KEY or not JPUSH_MASTER_SECRET:
        logger.warning("[jpush] JPUSH_APP_KEY 或 JPUSH_MASTER_SECRET 未配置，跳过推送")
        return False

    payload = {
        "platform": "android",
        "audience": {
            "registration_id": [reg_id],
        },
        "notification": {
            "alert": body[:120],  # 简短版（通知栏预览）
            "android": {
                "title": title,
                "alert": body[:120],
                "big_text": body[:2000],  # 长文版（通知栏下拉展开，JPush 上限约 4KB）
                "channel_id": channel,
                "priority": 2,           # 高优先级，增强穿透力
                "category": "message",
                "extras": extras or {},  # ← 通知栏 extras，Android onNotifyMessageArrived 读这个
            },
        },
        "message": {
            "msg_content": body[:500],
            "content_type": "text",
            "title": title,
            "extras": extras or {},
        },
        "options": {
            "apns_production": False,
            "time_to_live": 86400,  # 离线消息保留 1 天
        },
    }

    headers = {
        "Authorization": f"Basic {_make_auth()}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(JPUSH_URL, json=payload, headers=headers)
            data = resp.json()
            if resp.status_code == 200 and data.get("msg_id"):
                logger.info(f"[jpush] 发送成功: msg_id={data['msg_id']}, title={title}")
                return True
            else:
                logger.error(f"[jpush] 发送失败: status={resp.status_code}, body={resp.text[:300]}")
                return False
    except Exception as e:
        logger.error(f"[jpush] 请求异常: {e}")
        return False


async def send_diary_push(diary_title: str, diary_preview: str, reg_id: str = "") -> bool:
    """
    推送日记通知的快捷方法。
    通知栏显示日记标题，点进去跳转到日记详情页。
    """
    return await send_push(
        reg_id=reg_id,
        title=f"📖 {diary_title}",
        body=diary_preview[:500],
        extras={
            "type": "diary",
            "target_id": diary_title,
        },
        channel="hina_diary",
    )
