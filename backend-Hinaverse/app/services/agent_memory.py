"""
AgentMemory 记忆服务客户端（外部记忆管线，X-Project 租户隔离）。

接口（与 AgentMemory backend-AgentMemory/src/server.ts 对齐）：
  POST /api/echo     { userId, messages: [{role, content}] }   → L0→L1→L3 异步消化
  GET  /api/portrait?userId=                                   → 用户最终画像

调用原则：
  1. 消息回显走 echo_async()：asyncio.create_task 后台跑，绝不阻塞日奈回复
     （跟记忆压缩同一个「先回复后异步」模式）
  2. AgentMemory 背压返回 503 → 指数退避重试（1s/2s，最多 3 次）
  3. 画像查询走 get_portrait()：同步 await、3s 超时，失败返回 None——画像坏了也不许拖垮回复
"""
import asyncio
import logging

import httpx

from app.config import AGENT_MEMORY_API_KEY, AGENT_MEMORY_BASE_URL, AGENT_MEMORY_PROJECT

logger = logging.getLogger(__name__)

_TIMEOUT = 3.0        # 单请求超时（秒）：记忆服务是辅助，不值得为它等更久
_MAX_RETRY = 3        # 503 背压重试次数


def echo_async(user_id: int, role: str, content: str) -> None:
    """后台推一条消息进记忆管线（fire-and-forget，调用方不等结果）。
    role: "user"（用户说的话）| "ai"（日奈说的话）——画像必须分清谁说。"""
    asyncio.create_task(_echo_with_retry(user_id, role, content))


async def _echo_with_retry(user_id: int, role: str, content: str) -> None:
    """带退避的 echo：503 背压等 1s/2s 重试；网络异常同样退避后重试；全失败仅记日志。"""
    for attempt in range(_MAX_RETRY):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{AGENT_MEMORY_BASE_URL}/api/echo",
                    headers=_headers(),
                    json={"userId": user_id, "messages": [{"role": role, "content": content}]},
                )
            if resp.status_code == 200:
                return  # 送进去了，L0 缓冲后续消化与这里无关
            if resp.status_code == 503 and attempt < _MAX_RETRY - 1:
                await asyncio.sleep(2**attempt)  # 背压：1s → 2s
                continue
            logger.warning(
                f"[agent_memory] echo 失败 user={user_id} status={resp.status_code} body={resp.text[:200]}"
            )
            return
        except Exception as e:
            logger.warning(f"[agent_memory] echo 网络异常 user={user_id}: {e}")
            if attempt < _MAX_RETRY - 1:
                await asyncio.sleep(2**attempt)
            else:
                return


async def get_portrait(user_id: int) -> str | None:
    """查用户画像（供生成回复前拼接上下文）。失败/超时返回 None，绝不抛出。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{AGENT_MEMORY_BASE_URL}/api/portrait",
                headers=_headers(),
                params={"userId": user_id},
            )
        if resp.status_code == 200:
            data = resp.json()
            portrait = data.get("portrait")
            return portrait if isinstance(portrait, str) and portrait.strip() else None
        logger.warning(f"[agent_memory] portrait 失败 user={user_id} status={resp.status_code}")
        return None
    except Exception as e:
        logger.warning(f"[agent_memory] portrait 网络异常 user={user_id}: {e}")
        return None


def _headers() -> dict[str, str]:
    """业务鉴权头：X-Project（表前缀隔离）+ X-Api-Key（项目专属密钥）"""
    return {
        "X-Project": AGENT_MEMORY_PROJECT,
        "X-Api-Key": AGENT_MEMORY_API_KEY,
    }