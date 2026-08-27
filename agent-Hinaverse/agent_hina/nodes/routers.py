from typing import Literal
from langgraph.graph import END

from agent_hina.state import AgentState


# 系统状态消息中需要跳过 agent_think 的维护任务 → 对应的目标节点
_SYSTEM_MAINTENANCE = {
    "日终压缩": "daily_compress",   # 定时任务触发：日终记忆压缩 + 陪伴总结
}


def route_at_start(state: AgentState) -> Literal["agent_think", "daily_compress"]:  # type: ignore
    """
    START 分发。

    消息来源有两种，靠前缀区分：
      - 用户输入        → 无前缀，正常对话
      - [系统状态切换]   → 定时任务（目前只有日终压缩）

    [系统状态切换] 中「日终压缩」是系统维护任务，直接走 daily_compress，
    不经过 agent_think。
    """
    messages = state.get("messages", [])

    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "content") and last_msg.content:
            content = str(last_msg.content)

            # 系统状态切换 → 查维护映射表
            if content.startswith("[系统状态切换]"):
                reason = content.replace("[系统状态切换]", "").strip()
                action_word = reason.split()[0] if reason else ""
                if action_word in _SYSTEM_MAINTENANCE:
                    target = _SYSTEM_MAINTENANCE[action_word]
                    print(f"  [router:start] → {target} (系统维护: {reason})")
                    return target  # type: ignore
                print(f"  [router:start] → agent_think (状态变更: {reason})")
                return "agent_think"

    # 正常用户输入 → 直接思考
    print("  [router:start] → agent_think")
    return "agent_think"


def should_continue(state: AgentState) -> Literal["execute_tool", "ask_human", END]:  # type: ignore
    """
    agent_think 之后的路线分发，纯规则判断。

    记忆压缩（save/reduce）不在图内 —— 回复先返回用户，
    压缩由 backend 调用 graph.run_memory_compression() 异步执行。
    """
    # 1. LLM 调了工具 → 去执行
    last_msg = state["messages"][-1] if state.get("messages") else None
    if last_msg is not None and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        print(f"  [router] → execute_tool ({[tc['name'] for tc in last_msg.tool_calls]})")
        return "execute_tool"

    # 2. 需要人类确认 → 澄清追问（生成话术即回复，直接结束）
    if state.get("needs_human"):
        print("  [router] → ask_human")
        return "ask_human"

    # 3. 直接回复 → 结束本轮
    print("  [router] → END")
    return END
