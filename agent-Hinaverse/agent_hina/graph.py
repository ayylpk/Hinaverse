"""
agent_graph.py —— 日奈 AI（心理健康陪伴者）LangGraph 主图

架构（先回复、压缩异步）:
    START → route_at_start
              ├─ 用户输入        → agent_think
              └─ [系统状态切换]  → daily_compress

    agent_think ─┬─ tool_calls ──→ execute_tool ──→ 回 agent_think
                 ├── needs_human ──→ ask_human ────→ END
                 └── END（直接回复）

记忆压缩（save_memory / reduce_memory）不在图主链路内：
    回复先返回给用户，压缩由 backend 在推送回复后调用
    run_memory_compression() 异步执行（读 checkpoint → 压缩 → 写回）。

记忆闭环:
    对话结束 → backend 异步 run_memory_compression：
        save_memory（轻度压缩 short → 追加 long）
        long ≥ 3 条 → reduce_memory（中度压缩覆盖 long）
    每天日终 → daily_compress（定时任务触发）

节点职责:
    agent_think  = LLM 人设 + 工具决策 (search_web/update_state) + 回复生成
    execute_tool = 执行工具调用
    ask_human    = 澄清追问（不 interrupt，直接生成话术回复）
    daily_compress = 日终记忆压缩 + 给用户的日终总结

运行时由 backend-Hinaverse 驱动（FastAPI + WebSocket）。
"""
from pathlib import Path
from dotenv import load_dotenv

# ⚠️ 必须在 import langgraph 之前加载 .env，否则 LangSmith tracing 不生效
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)

from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.runnables import RunnableConfig
from typing import Any

from agent_hina.state import AgentState
from agent_hina.nodes.think import agent_think_node
from agent_hina.nodes.execute import execute_tool_node
from agent_hina.nodes.ask_human import ask_human_node
from agent_hina.nodes.daily_compress import daily_compress_node
from agent_hina.nodes.routers import should_continue, route_at_start
from agent_hina.nodes.reduce import COMPRESS_THRESHOLD

CHECKPOINT_DB_PATH: Path | None = None  # build_hina_graph() 内赋值

# ── 图实例单例缓存：整个进程只 build 一次、只开一个 SQLite 连接 ──
# 多用户并发共用同一图实例，靠 thread_id 隔离状态（LangGraph checkpoint 机制）。
# 禁止每条消息重新 build（每次都会新建 aiosqlite 连接，高并发会耗尽连接）。
_GRAPH_INSTANCE = None


# ═══════════════════════════════════════════════════════════════════
# 构建图
# ═══════════════════════════════════════════════════════════════════

async def build_hina_graph():
    """
    构建并编译日奈 Agent 图（单例：进程内只构建一次，多用户并发复用同一实例）。

    多用户用法：
        graph = await build_hina_graph()          # 全局复用一个实例
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=msg)]},
            config={"configurable": {"thread_id": f"user_{uid}"}},  # 每个用户独立 thread
        )
        # 回复返回后，异步执行记忆压缩（不阻塞回复）：
        # await run_memory_compression(config)
    """
    global _GRAPH_INSTANCE
    if _GRAPH_INSTANCE is not None:
        return _GRAPH_INSTANCE

    builder = StateGraph(AgentState)

    # 添加主流程节点（记忆压缩节点不在图内，见 run_memory_compression）
    builder.add_node("agent_think", agent_think_node)
    builder.add_node("execute_tool", execute_tool_node)
    builder.add_node("ask_human", ask_human_node)
    builder.add_node("daily_compress", daily_compress_node)

    # ── START 分发：日终压缩（定时任务触发） / 正常对话 ──
    builder.add_conditional_edges(START, route_at_start, {
        "agent_think": "agent_think",
        "daily_compress": "daily_compress",
    })

    # agent_think → 三条路由（回复优先，压缩不在图内）
    builder.add_conditional_edges("agent_think", should_continue, {
        "execute_tool": "execute_tool",
        "ask_human": "ask_human",
        END: END,
    })

    # 工具执行完 → 回到 agent_think 继续思考
    builder.add_edge("execute_tool", "agent_think")

    # 人工澄清完 → 直接结束（澄清话术本身就是回复，不再回 agent_think 避免循环）
    builder.add_edge("ask_human", END)

    # 日终压缩完 → 结束（总结在 _daily_summary_text，由 backend 取走落库/推送）
    builder.add_edge("daily_compress", END)

    # 编译（AsyncSqliteSaver 持久化 state，断连不丢）
    global CHECKPOINT_DB_PATH
    db_path = Path(__file__).resolve().parent.parent / "data" / "sqlite" / "hina_checkpoints.db"
    CHECKPOINT_DB_PATH = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    import aiosqlite
    conn = await aiosqlite.connect(str(db_path))
    checkpointer = AsyncSqliteSaver(conn)
    _GRAPH_INSTANCE = builder.compile(checkpointer=checkpointer)
    print(f"  [graph] 图实例已构建（单例），checkpoint: {db_path}")
    return _GRAPH_INSTANCE


# ═══════════════════════════════════════════════════════════════════
# 记忆压缩（异步后台，回复返回后由 backend 调用）
# ═══════════════════════════════════════════════════════════════════

async def run_memory_compression(
    config: RunnableConfig,
    graph: CompiledStateGraph | None = None,
) -> dict[str, Any]:
    """
    回复已返回给用户后，异步执行记忆压缩（不阻塞回复）。

    流程：
        1. 读当前 thread 的 checkpoint state
        2. need_to_save_memory 为 True → save_memory_node（short 轻度压缩 → 追加 long）
        3. long ≥ COMPRESS_THRESHOLD → reduce_memory_node（中度压缩覆盖 long）
        4. 写回 checkpoint

    用法（backend 推送回复后，fire-and-forget）：
        config = {"configurable": {"thread_id": f"user_{uid}"}}
        asyncio.create_task(run_memory_compression(config))

    返回本次实际执行的压缩更新 dict（无更新返回 {}）。
    """
    if graph is None:
        graph = await build_hina_graph()

    # ── 1. 读当前 state ──
    snap = await graph.aget_state(config)
    state: dict[str, Any] = dict(snap.values or {})
    if not state:
        return {}

    updates: dict[str, Any] = {}

    # ── 2. 需要存记忆 → save（short → long）──
    if state.get("need_to_save_memory"):
        from agent_hina.nodes.save_memory import save_memory_node
        save_updates: dict[str, Any] = save_memory_node(state) # type: ignore
        if save_updates:
            await graph.aupdate_state(config, save_updates)
            updates.update(save_updates)
            state.update(save_updates)
            print("  [graph:compress] save_memory 完成")

    # ── 3. long 超阈值 → reduce（覆盖 long）──
    long_mem = state.get("long_session_memory", [])
    if isinstance(long_mem, list) and len(long_mem) >= COMPRESS_THRESHOLD:
        from agent_hina.nodes.reduce import reduce_memory_node
        reduce_updates: dict[str, Any] = reduce_memory_node(state) # type: ignore
        if reduce_updates:
            await graph.aupdate_state(config, reduce_updates)
            updates.update(reduce_updates)
            print(f"  [graph:compress] reduce_memory 完成 (long≥{COMPRESS_THRESHOLD})")

    return updates
