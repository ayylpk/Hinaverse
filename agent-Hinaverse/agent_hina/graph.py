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
        spontaneous（先想一条"等会儿关心什么"，交 backend 定时发送）
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
from agent_hina.nodes.wait_human import wait_human_node
from agent_hina.nodes.daily_compress import daily_compress_node
from agent_hina.nodes.routers import should_continue, route_at_start
from agent_hina.nodes.reduce import COMPRESS_THRESHOLD

import asyncio

CHECKPOINT_DB_PATH: Path | None = None  # build_hina_graph() 内赋值

# ── 图实例单例缓存：按"事件循环"缓存，每 loop 一份（进程内不重复 build、不开多余连接） ──
# 生产 uvicorn 单 loop = 全局一份，语义不变；多用户并发共用同一图，靠 thread_id 隔离。
# 测试环境每个 TestClient 有独立 loop：AsyncSqliteSaver / aiosqlite 连接持有 loop 绑定的
# asyncio 原语，跨 loop 复用一个已建好的图必炸（实测 "Lock is bound to a different event loop"），
# 所以图、SQLite 连接、构建互斥锁全部按 loop 隔离（dict 以 loop 对象为键，防 id 复用串台）。
_GRAPH_INSTANCES: dict[asyncio.AbstractEventLoop, CompiledStateGraph] = {}
_GRAPH_BUILD_LOCKS: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


# ═══════════════════════════════════════════════════════════════════
# 构建图
# ═══════════════════════════════════════════════════════════════════

async def build_hina_graph():
    """
    构建并编译日奈 Agent 图（按事件循环缓存单例：同 loop 内只构建一次，多用户并发复用）。

    多用户用法：
        graph = await build_hina_graph()          # 全局复用一个实例
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=msg)]},
            config={"configurable": {"thread_id": f"user_{uid}"}},  # 每个用户独立 thread
        )
        # 回复返回后，异步执行记忆压缩（不阻塞回复）：
        # await run_memory_compression(config)
    """
    loop = asyncio.get_running_loop()
    graph = _GRAPH_INSTANCES.get(loop)
    if graph is not None:
        return graph

    build_lock = _GRAPH_BUILD_LOCKS.get(loop)
    if build_lock is None:
        build_lock = asyncio.Lock()
        _GRAPH_BUILD_LOCKS[loop] = build_lock
    async with build_lock:
        graph = _GRAPH_INSTANCES.get(loop)
        if graph is not None:
            return graph

        builder = StateGraph(AgentState)

        # 添加主流程节点（记忆压缩节点不在图内，见 run_memory_compression）
        builder.add_node("agent_think", agent_think_node)
        builder.add_node("execute_tool", execute_tool_node)
        builder.add_node("ask_human", ask_human_node)
        builder.add_node("daily_compress", daily_compress_node)
        builder.add_node("wait_human", wait_human_node)

        # ── START 分发：日终压缩（定时任务触发） / 人工接管中断 / 正常对话 ──
        builder.add_conditional_edges(START, route_at_start, {
            "agent_think": "agent_think",
            "daily_compress": "daily_compress",
            "wait_human": "wait_human",
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

        # 人工接管中断完 → 直接结束（本轮不产生回复；resume 收尾也走这里）
        builder.add_edge("wait_human", END)

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
        graph = builder.compile(checkpointer=checkpointer)
        _GRAPH_INSTANCES[loop] = graph
        print(f"  [graph] 图实例已构建（按 loop 缓存），checkpoint: {db_path}")
        return graph


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
        1.5 自主关心 spontaneous_thought_node（⚠️ 必须在 save 之前：
            趁 short_session_memory 还没被压缩清空才有东西可惦记）
            → 产物 _spontaneous 只随返回值交还 backend 落库，不写 checkpoint
        2. need_to_save_memory 为 True → save_memory_node（short 轻度压缩 → 追加 long）
        3. long ≥ COMPRESS_THRESHOLD → reduce_memory_node（中度压缩覆盖 long）
        4. 写回 checkpoint

    用法（backend 推送回复后，fire-and-forget）：
        config = {"configurable": {"thread_id": f"user_{uid}"}}
        asyncio.create_task(run_memory_compression(config))

    返回本次实际执行的压缩更新 dict（无更新返回 {}）；
    自主关心产物以 "_spontaneous" 键混在返回值里（一次性，不属于 state 更新）。
    """
    if graph is None:
        graph = await build_hina_graph()

    # ── 1. 读当前 state ──
    snap = await graph.aget_state(config)
    state: dict[str, Any] = dict(snap.values or {})
    if not state:
        return {}

    updates: dict[str, Any] = {}

    # ── 1.5 自主关心（先想，再压缩；失败/不关心返回 {}，绝不影响后续）──
    from agent_hina.nodes.spontaneous import spontaneous_thought_node
    sp_updates = spontaneous_thought_node(state)  # type: ignore
    if sp_updates.get("_spontaneous"):
        # ⚠️ 只放进返回值，不 aupdate_state —— _spontaneous 是一次性投递物，不是记忆
        updates["_spontaneous"] = sp_updates["_spontaneous"]

    # ── 2. 需要存记忆 → save（short → long）──
    if state.get("need_to_save_memory"):
        from agent_hina.nodes.save_memory import save_memory_node
        save_updates: dict[str, Any] = save_memory_node(state) # type: ignore
        if save_updates:
            # ⚠️ langgraph 1.x：非空 checkpoint 上 aupdate_state 必须显式 as_node
            await graph.aupdate_state(config, save_updates, as_node="agent_think")
            updates.update(save_updates)
            state.update(save_updates)
            print("  [graph:compress] save_memory 完成")

    # ── 3. long 超阈值 → reduce（覆盖 long）──
    long_mem = state.get("long_session_memory", [])
    if isinstance(long_mem, list) and len(long_mem) >= COMPRESS_THRESHOLD:
        from agent_hina.nodes.reduce import reduce_memory_node
        reduce_updates: dict[str, Any] = reduce_memory_node(state) # type: ignore
        if reduce_updates:
            await graph.aupdate_state(config, reduce_updates, as_node="agent_think")
            updates.update(reduce_updates)
            print(f"  [graph:compress] reduce_memory 完成 (long≥{COMPRESS_THRESHOLD})")

    return updates
