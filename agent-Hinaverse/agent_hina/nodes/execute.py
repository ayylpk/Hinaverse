"""
execute_tool 节点 —— 执行 LLM 请求的工具调用
"""
from langchain_core.messages import ToolMessage
from agent_hina.state import AgentState
from agent_hina.tools import tools_by_name


def execute_tool_node(state: AgentState) -> dict:
    """找最后一条消息里的 tool_calls,逐个执行"""
    last_msg = state["messages"][-1]
    results = []

    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {"tool_results": []}

    for tc in last_msg.tool_calls:
        tool = tools_by_name.get(tc["name"])
        if tool:
            try:
                observation = tool.invoke(tc["args"])
                print(f"  [execute_tool] {tc['name']}(...) → {str(observation)[:60]}...")
                results.append(ToolMessage(
                    content=str(observation),
                    tool_call_id=tc["id"],
                ))
            except Exception as e:
                print(f"  [execute_tool] {tc['name']} 失败: {e}")
                results.append(ToolMessage(
                    content=f"工具执行失败: {e}",
                    tool_call_id=tc["id"],
                ))
        else:
            results.append(ToolMessage(
                content=f"未知工具: {tc['name']}",
                tool_call_id=tc["id"],
            ))

    return {"messages": results, "tool_results": results}
