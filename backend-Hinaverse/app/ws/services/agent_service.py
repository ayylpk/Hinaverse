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

# ── 图实例单例：进程只 build 一次，多用户并发复用 ──
_GRAPH: CompiledStateGraph | None = None
_GRAPH_LOCK = asyncio.Lock()


async def _get_graph() -> CompiledStateGraph:
    """懒加载 + 并发安全的图单例"""
    global _GRAPH
    if _GRAPH is None:
        async with _GRAPH_LOCK:
            if _GRAPH is None:
                _GRAPH = await build_hina_graph()
    return _GRAPH


async def generate_reply(
    user_message: str,
    user_profile: dict[str, Any],
    history: list[dict[str, Any]],
    needs_deep_comfort: bool = False,
    user_id: int | None = None,
) -> str:
    """
    生成日奈的回复（真实调用 LangGraph 图）。

    - thread_id = user_id：每个用户独立上下文与记忆（多用户隔离）
    - 回复直接返回给调用方；记忆压缩在后台异步执行，不阻塞回复
    - needs_deep_comfort：中/低危时 True，触发 agent 侧深度安抚提示词覆写
    """
    if user_id is None:
        # 兜底：没传 user_id 时用固定线程（仅开发/单用户场景）
        thread_id = "dev"
    else:
        thread_id = f"user_{user_id}"

    graph = await _get_graph()
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    # ── 组初始状态：用户消息 + 深度安抚标记 ──
    initial: dict[str, Any] = {"messages": [HumanMessage(content=user_message)]}
    if needs_deep_comfort:
        initial["needs_deep_comfort"] = True

    # ── 1. 先拿回复（图主链路只做回复，不含压缩）──
    result = await graph.ainvoke(initial, config=config)

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
