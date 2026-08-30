"""
inactive_memory —— 离开判定 + 会话记忆落盘（自动存档）。

目标：用户离线且超过阈值无对话 → 把该会话的短记忆压缩进长期记忆
（等价于"自动存个档"，下次回来日奈还记得）。

设计（为什么）：
1. 判定用「离线 + 最后活跃时间超时」双条件：
   - 在线状态取 outbound_hub.is_online（WS 断开时 ws.py 已 unregister，直接复用）
   - 最后活跃时间用 messages.created_at 的 MAX（time 是 HH:MM 展示串，不可比大小）
2. 落盘复用 agent 现成的记忆压缩链路 run_memory_compression（short→long），
   但它是 need_to_save_memory 门控的，离开落盘应无条件 → 先 aupdate_state 置位
   True 再复用；short 为空时 save_memory_node 自己跳过，天然安全。
3. 幂等：内存 dict user_id→上次处理时间。同一段空闲只触发一次（last_act 不变
   就不重复压）；服务重启允许重扫（可接受，压缩天然幂等）。
4. 失败安全：LLM 压缩失败走 save_memory 的截断兜底；每个用户 try/except 包住，
   单个失败不影响扫描循环。
5. 只动记忆，不主动发消息（主动关心消息是另一功能，本期不做）。
"""
import asyncio
import logging
from datetime import datetime, timedelta

from app.database import SyncSessionLocal
from app.repositories import message_repo, user_repo
from app.ws.Hub import outbound_hub
from app.ws.services.agent_service import _get_graph

logger = logging.getLogger(__name__)

# ── 调参区：扫描周期与离开超时阈值（秒）──
INACTIVE_SCAN_INTERVAL = 600   # 每 10 分钟扫一次（太频繁会无谓查库）
INACTIVE_TIMEOUT = 1800        # 超过 30 分钟无对话视为"离开"

# ── 幂等记忆：user_id -> 上次触发落盘的最后活跃时间 ──
_last_handled: dict[int, datetime] = {}


async def inactive_scan_loop() -> None:
    """定时循环：每 INACTIVE_SCAN_INTERVAL 秒扫一次（main.py lifespan 里 create_task）"""
    while True:
        await asyncio.sleep(INACTIVE_SCAN_INTERVAL)
        try:
            await scan_once()
        except Exception as e:
            # 扫描循环本身不能挂：单次失败记日志，下轮继续
            logger.error(f"[inactive_memory] 扫描异常: {e}")


async def scan_once() -> None:
    """扫一遍所有用户：离线 + 超时 → 派发落盘任务（fire-and-forget）"""
    cutoff = datetime.now() - timedelta(seconds=INACTIVE_TIMEOUT)
    hits: list[tuple[int, datetime]] = []

    with SyncSessionLocal() as db:
        users = user_repo.list_all(db)
        for u in users:
            # 在线用户不算离开，跳过
            if outbound_hub.is_online(u.id):
                continue
            # 最后活跃：该用户所有会话最新消息时间；从未聊过则用注册时间兜底
            last_act = message_repo.get_latest_activity(db, u.id) or u.created_at
            if last_act and last_act < cutoff:
                hits.append((u.id, last_act))

    logger.info(f"[inactive_memory] 扫描完成，命中 {len(hits)} 个离线超时用户")
    for uid, last_act in hits:
        asyncio.create_task(_persist_one(uid, last_act))


async def _persist_one(user_id: int, last_act: datetime) -> None:
    """单个用户：短记忆 → 长记忆压缩落盘（幂等 + 失败安全）"""
    # 幂等：这段空闲已处理过（last_act 未前进）就不再压
    prev = _last_handled.get(user_id)
    if prev is not None and prev >= last_act:
        return

    try:
        graph = await _get_graph()
        config = {"configurable": {"thread_id": f"user_{user_id}"}}

        # 读当前 thread 状态：没聊过（无 checkpoint）或 short 为空 → 没档可存
        snap = await graph.aget_state(config)
        state = dict(snap.values or {})
        short = state.get("short_session_memory", [])
        if not isinstance(short, list) or not short:
            logger.info(f"[inactive_memory] 用户 {user_id} 无短记忆，跳过")
            return

        # 无条件落盘：置位 need_to_save_memory 后复用现成压缩链路
        # （save_memory_node 压缩 short → 追加 long → 清空 short；long≥3 自动 reduce）
        # ⚠️ aupdate_state 必须显式 as_node：langgraph 1.x 在非空 checkpoint 上
        #    推断不出来源节点时直接抛 Ambiguous update
        await graph.aupdate_state(config, {"need_to_save_memory": True}, as_node="agent_think")
        from agent_hina.graph import run_memory_compression
        await run_memory_compression(config, graph)

        _last_handled[user_id] = last_act
        logger.info(f"[inactive_memory] 用户 {user_id} 短记忆已落盘（{len(short)} 条）")
    except Exception as e:
        logger.error(f"[inactive_memory] 用户 {user_id} 落盘失败: {e}")
