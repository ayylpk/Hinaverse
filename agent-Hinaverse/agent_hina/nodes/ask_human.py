from langchain_core.messages import AIMessage
from agent_hina.state import AgentState
from agent_hina.models import ask_human_model
from agent_hina.prompts import build_ask_human_prompt


def ask_human_node(state: AgentState) -> dict:
    """
    日奈的求助节点：LLM 判定 needs_human=true（没听懂/缺关键信息）时，
    直接生成一句澄清话术作为回复返回，不再 interrupt 挂起会话。
    （WebSocket 驱动链路没有 resume 支持，interrupt 会导致会话卡死）
    """
    messages = state.get("short_session_memory", [])

    # 提取最近的对话上下文，帮助大模型理解"为什么没听懂"
    query = messages[-5:] if len(messages) > 5 else messages
    context_str = "\n".join([f"{m.get('role', 'user')}: {m.get('content', '')}" for m in query])

    try:
        system_prompt = build_ask_human_prompt(context_str)
        prompt_response = ask_human_model.invoke(system_prompt)
        prompt = prompt_response.content.strip()  # type: ignore
    except Exception as e:
        print(f"  [ask_human] 澄清话术生成失败: {e}")
        prompt = "那个……你说的我没太明白，能再说一遍吗？"

    return {
        "messages": [AIMessage(content=prompt)],
        "needs_human": False,
        "status": "在线",
    }
