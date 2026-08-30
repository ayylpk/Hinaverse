"""
daily_summary —— 日终陪伴总结服务（每天 24:00 由 main.py 定时任务触发）。

流程（对每个用户，全部后台异步，不阻塞主服务）：
    1. ainvoke 图，发「[系统状态切换] 日终压缩」→ route_at_start 分发到 daily_compress 节点
    2. agent 侧完成：压缩今日记忆覆盖 long（作为明日开始的上下文）+ 清空 short + 产出 _daily_summary_text
    3. 取 _daily_summary_text → 调用 diary_repo 存为日记（用户通过 GET /api/diary 读取）
    4. 日清：把当日总结 append 进 thread 的 daily_archive（次日系统提示注入，持续上下文），
       并清空日级字段（messages 原始对话 / short / tool_results / need_to_save_memory），
       保留 long（跨日记忆）/ portrait / daily_archive / human_takeover。

为什么"先压缩落库、再清理"（顺序不可颠倒）：
    daily_compress 节点依赖 state 里的 long/short 生成总结；若先清空再触发，
    压出来就是空的，当天总结会丢。所以必须：先 ainvoke（压缩+总结）→ 落日记
    → 再把总结写进 daily_archive 并清理日级字段。

DB 用同步 Session（与 ws.py 一致），LLM 等待在 async 侧。
"""
import asyncio
import logging

from langchain_core.messages import RemoveMessage, SystemMessage

from app.database import SyncSessionLocal
from app.repositories import diary_repo, user_repo
from app.services.agent_memory import get_portrait_cached
from app.ws.services.agent_service import _get_graph

logger = logging.getLogger(__name__)

# 触发日终压缩的系统消息（route_at_start 识别前缀路由到 daily_compress 节点）
_DAILY_TRIGGER = "[系统状态切换] 日终压缩"

# daily_archive 最多保留最近 N 天的总结，防止无限膨胀
_ARCHIVE_MAX = 30


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

        # ── 日清：总结进持续上下文 + 清空日级字段（必须在落日记之后，见模块注释）──
        await _daily_cleanup(graph, config, summary_text)
    except Exception as e:
        logger.error(f"[daily_summary] 用户 {user_id} 日终压缩失败: {e}")


async def _daily_cleanup(graph, config, summary_text: str) -> None:
    """
    日清（当天收尾）：把今日总结写进 daily_archive，清掉今日原始内容。

    目标状态 = 空 messages + long + daily_archive + 画像（+ human_takeover）。
    手段用 aupdate_state（走各字段的 reducer），不动 checkpoint 表其他线程数据。
    """
    snap = await graph.aget_state(config)
    state = dict(snap.values or {})

    # 1. 当日总结 append 进 daily_archive（持续上下文，保留，日清不清它）
    archive = list(state.get("daily_archive") or [])
    archive.append(summary_text)
    archive = archive[-_ARCHIVE_MAX:]  # 只留最近 N 天，防膨胀

    # 2. 清空原始对话：RemoveMessage 是 langgraph 官方"删历史消息"的方式
    #    （messages 是 add_messages reducer，直接传 [] 不会清空，必须逐条 Remove）
    removals = []
    for m in state.get("messages", []):
        mid = getattr(m, "id", None)
        if mid:
            removals.append(RemoveMessage(id=mid))
    if not removals:
        logger.warning("[daily_summary] 消息无 id，无法用 RemoveMessage 清空（一般不会发生）")

    # 3. 覆写日级字段；long / portrait / daily_archive / human_takeover 不传即保留。
    #    ⚠️ aupdate_state 必须显式 as_node（langgraph 1.x 非空 checkpoint 推断不出
    #    来源节点会抛 Ambiguous update）；语义上这次清理属于日终节点 daily_compress。
    await graph.aupdate_state(config, {
        "messages": removals,
        "short_session_memory": [],
        "tool_results": [],
        "need_to_save_memory": False,
        "daily_archive": archive,
    }, as_node="daily_compress")
    logger.info(f"[daily_summary] 日清完成：daily_archive={len(archive)} 条，今日原始对话已清理")
