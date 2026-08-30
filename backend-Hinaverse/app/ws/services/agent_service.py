"""
Agent 对接层 —— 真实接入 LangGraph 图（全链路闭环）

消息链路：
    ws.py → generate_reply → agent_hina.graph.ainvoke（先回复）
                           → run_memory_compression（异步压缩，不阻塞回复）

多用户隔离：每个会话用独立 thread_id（user_{uid}），checkpoint 按 thread 分区。
先回复后压缩：ainvoke 返回即拿到回复；记忆压缩由 asyncio.create_task 后台执行。
"""
import asyncio
import sys
from pathlib import Path
from typing import Any

# ── 复用 agent-Hinaverse 的 AI 资产（graph/models/prompts/safety）──
# 本文件位于 backend-Hinaverse/app/ws/services/ 下：parents[0]=services, [1]=ws, [2]=app, [3]=backend, [4]=项目根
_AGENT_DIR = Path(__file__).resolve().parents[4] / "agent-Hinaverse"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent_hina.graph import build_hina_graph, run_memory_compression  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from langchain_core.runnables import RunnableConfig  # noqa: E402
from langgraph.graph.state import CompiledStateGraph  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.services.agent_memory import get_portrait_cached  # noqa: E402

# ── 图实例单例：按"事件循环"缓存（每个 loop 最多 build 一次，多用户并发复用） ──
# 生产 uvicorn 单 loop ≈ 全局一份，语义与旧版完全一致；
# 测试环境每个 TestClient 有独立 loop，图内部（AsyncSqliteSaver 等）持有 loop 绑定的
# asyncio 原语——跨 loop 复用一个已建好的图会炸 "Lock is bound to a different event loop"
# （实测：test_ws 两条用例连续跑时第二个 TestClient 必崩），所以必须按 loop 隔离重建。
# 两个 dict 以 loop 对象为键（强引用，防 id 复用串台；loop 销毁后条目随引用一起回收）。
_GRAPHS: dict[asyncio.AbstractEventLoop, CompiledStateGraph] = {}
_GRAPH_LOCKS: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


async def _get_graph() -> CompiledStateGraph:
    """懒加载 + 并发安全的图单例（按当前事件循环取/建）"""
    loop = asyncio.get_running_loop()
    graph = _GRAPHS.get(loop)
    if graph is None:
        lock = _GRAPH_LOCKS.get(loop)
        if lock is None:
            lock = asyncio.Lock()  # 锁也按 loop 隔离：跨 loop 的锁本身就不能共用
            _GRAPH_LOCKS[loop] = lock
        async with lock:
            graph = _GRAPHS.get(loop)
            if graph is None:
                graph = await build_hina_graph()
                _GRAPHS[loop] = graph
    return graph


async def generate_reply(
    user_message: str,
    user_profile: dict[str, Any],
    needs_deep_comfort: bool = False,
    high_risk: bool = False,
    user_id: int | None = None,
    human_takeover: bool = False,
) -> str | None:
    """
    生成日奈的回复（真实调用 LangGraph 图）。

    - thread_id = user_id：每个用户独立上下文与记忆（多用户隔离）
    - 回复直接返回给调用方；记忆压缩在后台异步执行，不阻塞回复
    - needs_deep_comfort：中/低危时 True，触发 agent 侧深度安抚提示词覆写
    - high_risk：高危时 True，叠加高危持续深度安抚（引导热线，AI 继续陪伴）
    - human_takeover：人工接管中 True → 图在 wait_human 节点 interrupt 暂停，
      本轮无自动回复，返回 None（调用方负责给用户提示）；提交干预结果后
      handling 消失，不再传 True，自动恢复
    - 历史上下文由 LangGraph checkpoint 按 thread_id 自动累积，无需调用方传入
    """
    if user_id is None:
        # 兜底：没传 user_id 时用固定线程（仅开发/单用户场景）
        thread_id = "dev"
    else:
        thread_id = f"user_{user_id}"

    graph = await _get_graph()
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    # ── 组初始状态：用户消息 + 深度安抚/高危标记 + 用户画像 + 人工接管标记 ──
    initial: dict[str, Any] = {"messages": [HumanMessage(content=user_message)]}
    if needs_deep_comfort:
        initial["needs_deep_comfort"] = True
    if high_risk:
        initial["high_risk"] = True
    # ⚠️ 必须无条件传 human_takeover（True 或 False 都写）：
    # 该字段会持久化进 checkpoint，若上次接管为 True、这次没传，残留值会让路由误进
    # wait_human（实测踩坑：干预结束后 agent 恢复不了）。显式覆盖 checkpoint 旧值。
    initial["human_takeover"] = human_takeover

    # ── 画像回流：回复前取用户画像（TTL 缓存，绝大多数调用零网络；失败返回 None 走兜底）。
    #    人工接管中断时不需要画像，跳过省一次网络 ──
    if user_id is not None and not human_takeover:
        portrait = await get_portrait_cached(user_id)
        if portrait:
            initial["portrait"] = portrait

    # ── 0. 清理残留 pending interrupt ──
    # 上一次消息在 wait_human 节点 interrupt 后（人工接管中）图保持挂起；
    # 带 pending interrupt 的 thread 无法干净接收新输入（会把新消息叠加到
    # 挂起点上，不算新一轮），必须先 resume 收尾，下一次 invoke 才从 START 重走。
    # ⚠️ 只清理 wait_human 挂起：snap.next 也可能是执行中途的其他节点（如
    # 崩溃残留），那种情况 Resume 会把旧状态继续跑下去（还会调 LLM），不能用。
    snap = await graph.aget_state(config)
    if "wait_human" in (snap.next or ()):
        try:
            # langgraph 1.2.x 注意：resume 值不能是 None（会 UnboundLocalError）；
            # wait_human 不收 resume 值，这里传任意非 None 哨兵即可收尾
            await graph.ainvoke(Command(resume={"__type__": "cleanup"}), config=config)
        except Exception as e:
            print(f"  [agent_service] 清理 pending interrupt 失败: {e}")

    # ── 1. 先拿回复（图主链路只做回复，不含压缩）──
    # langgraph 1.2.x：ainvoke 遇到 interrupt() 不抛 GraphInterrupt（0.2.x 才抛），
    # 而是把挂起信息作为返回结果的 __interrupt__ 键带上（interrupt 值非空 → 挂起）。
    result = await graph.ainvoke(initial, config=config)
    if result.get("__interrupt__"):
        # 人工接管中：图在 wait_human 节点真正挂起（checkpoint 保留 pending，
        # next=['wait_human']）。本轮无自动回复，返回 None；下一次 invoke 前由上方清理。
        print("  [agent_service] __interrupt__: 人工接管中，本轮无自动回复")
        return None

    # 取最后一条 AI 回复
    reply = ""
    for m in reversed(result.get("messages", [])):
        content = getattr(m, "content", "")
        if content:
            reply = str(content)
            break
    if not reply:
        reply = "嗯，我在听。慢慢说，不着急。"

    # ── 2. 后台异步压缩（回复已到手，不阻塞返回）──
    asyncio.create_task(run_memory_compression(config, graph))

    return reply
