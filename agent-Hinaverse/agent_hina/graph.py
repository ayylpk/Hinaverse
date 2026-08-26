"""
agent_graph.py —— 日奈 AI（心理健康陪伴者）LangGraph 主图

架构（全套简化版，已移除主动消息/自主思考/日终压缩/闹钟体系）:
    START → agent_think
                  │
      agent_think ─┬─ tool_calls ──→ execute_tool ──┐
                   ├── needs_human ──→ ask_human ───┤
                   ├── save+long≥3 → reduce → save ─┤
                   ├── save ──→ save ────────────────┤
                   └── END                           │
                                                     │
                   execute_tool 全部回到 agent_think 继续思考
                   ask_human 澄清完直接结束
                   save_memory 存完记忆直接结束

记忆闭环:
    对话结束 → save_memory（轻度压缩入 long_session_memory）
    long ≥ 3 条 → reduce_memory（中度压缩覆盖 long）

节点职责:
    agent_think  = LLM 人设 + 工具决策 (search_web/update_state) + 行为决策
    execute_tool = 执行工具调用
    ask_human    = interrupt() 暂停等用户确认
    reduce_memory= long 条数超 3 时压缩, 产物覆盖 long
    save_memory  = 对话结束轻度压缩, 摘要存入长期记忆

运行时由 backend-Hinaverse 驱动（FastAPI + WebSocket）。
"""
from pathlib import Path
from dotenv import load_dotenv

# ⚠️ 必须在 import langgraph 之前加载 .env，否则 LangSmith tracing 不生效
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_hina.state import AgentState
from agent_hina.nodes.think import agent_think_node
from agent_hina.nodes.execute import execute_tool_node
from agent_hina.nodes.ask_human import ask_human_node
from agent_hina.nodes.reduce import reduce_memory_node
from agent_hina.nodes.save_memory import save_memory_node
from agent_hina.nodes.daily_compress import daily_compress_node
from agent_hina.nodes.routers import should_continue, route_at_start

CHECKPOINT_DB_PATH: Path | None = None  # build_hina_graph() 内赋值


# ═══════════════════════════════════════════════════════════════════
# 构建图
# ═══════════════════════════════════════════════════════════════════

async def build_hina_graph():
    """构建并编译日奈 Agent 图"""
    builder = StateGraph(AgentState)

    # 添加主流程节点
    builder.add_node("agent_think", agent_think_node)
    builder.add_node("execute_tool", execute_tool_node)
    builder.add_node("ask_human", ask_human_node)
    builder.add_node("reduce_memory", reduce_memory_node)
    builder.add_node("save_memory", save_memory_node)
    builder.add_node("daily_compress", daily_compress_node)

    # ── START 分发：日终压缩（定时任务触发） / 正常对话 ──
    builder.add_conditional_edges(START, route_at_start, {
        "agent_think": "agent_think",
        "daily_compress": "daily_compress",
    })

    # agent_think → 五条路由（含 END）
    builder.add_conditional_edges("agent_think", should_continue, {
        "execute_tool": "execute_tool",
        "ask_human": "ask_human",
        "reduce_memory": "reduce_memory",
        "save_memory": "save_memory",
        END: END,
    })

    # 工具执行完 → 回到 agent_think 继续思考
    builder.add_edge("execute_tool", "agent_think")

    # 人工澄清完 → 直接结束（澄清话术本身就是回复，不再回 agent_think 避免循环）
    builder.add_edge("ask_human", END)

    # 记忆压缩完 → 去存记忆
    builder.add_edge("reduce_memory", "save_memory")

    # 存完记忆 → 直接结束（主动消息/闹钟体系已移除）
    builder.add_edge("save_memory", END)

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
    return builder.compile(checkpointer=checkpointer)
