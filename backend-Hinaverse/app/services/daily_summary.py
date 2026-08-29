"""
daily_summary —— 日终陪伴总结服务（每天 23:00 由 main.py 定时任务触发）。

流程（对每个用户，全部后台异步，不阻塞主服务）：
    1. ainvoke 图，发「[系统状态切换] 日终压缩」→ route_at_start 分发到 daily_compress 节点
    2. agent 侧完成：压缩今日记忆覆盖 long（作为明日开始的上下文）+ 清空 short + 产出 _daily_summary_text
    3. 取 _daily_summary_text → 调用 diary_repo 存为日记（用户通过 GET /api/diary 读取）

DB 用同步 Session（与 ws.py 一致），LLM 等待在 async 侧。
"""
import asyncio
import logging

from langchain_core.messages import SystemMessage

from app.database import SyncSessionLocal
from app.repositories import diary_repo, user_repo
from app.services.agent_memory import get_portrait_cached
from app.ws.services.agent_service import _get_graph

logger = logging.getLogger(__name__)

# 触发日终压缩的系统消息（route_at_start 识别前缀路由到 daily_compress 节点）
_DAILY_TRIGGER = "[系统状态切换] 日终压缩"


async def run_daily_compress_for_all() -> None:
    """
    对全部用户执行日终压缩（fire-and-forget：每个用户一个后台任务，互不阻塞）。
    单个用户失败只记日志，不影响其他用户。
    """
    logger.info("[daily_summary] 日终压缩开始")
    with SyncSessionLocal() as db:
        users = user_repo.list_all(db)
    for u in users:
        asyncio.create_task(_compress_one(u.id))
    logger.info(f"[daily_summary] 已派发 {len(users)} 个用户的日终压缩任务")


async def _compress_one(user_id: int) -> None:
    """单个用户：触发图 → 取总结 → 存为日记（走现有日记 API 体系）"""
    try:
        graph = await _get_graph()
        config = {"configurable": {"thread_id": f"user_{user_id}"}}

        # 画像回流：拉用户画像注入 state，日终总结据此写得更贴心（失败 None 走「暂无用户档案」兜底）
        initial: dict = {"messages": [SystemMessage(content=_DAILY_TRIGGER)]}
        portrait = await get_portrait_cached(user_id)
        if portrait:
            initial["portrait"] = portrait

        result = await graph.ainvoke(initial, config=config)
        summary_text = (result.get("_daily_summary_text") or "").strip()
        if not summary_text:
            logger.info(f"[daily_summary] 用户 {user_id} 无今日内容，跳过")
            return

        with SyncSessionLocal() as db:
            if user_repo.get_by_id(db, user_id) is None:
                logger.info(f"[daily_summary] 用户 {user_id} 不存在，跳过")
                return
            diary_repo.create(db, user_id, summary_text)
            logger.info(f"[daily_summary] 用户 {user_id} 日终总结已存为日记")
    except Exception as e:
        logger.error(f"[daily_summary] 用户 {user_id} 日终压缩失败: {e}")
