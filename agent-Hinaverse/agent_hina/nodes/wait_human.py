"""
wait_human 节点 —— 人工接管中断（LangGraph 原生 interrupt）

人工接管（危机事件 handling）期间，用户消息进图后在这里暂停：
调用 interrupt() 抛出 GraphInterrupt，图进入 INTERRUPT 状态，本轮不产出任何自动回复。

恢复方式（backend ws.py 处理）：
  1. 调用方捕获 GraphInterrupt 后，立即用 Command(resume=...) 把本轮收尾，
     避免 thread 残留 pending interrupt 导致下一次 invoke 报错（WebSocket 链路
     没有"等用户回复再 resume"的交互，人工回复走独立的运营 reply 接口）。
  2. 运营提交干预结果（resolved）后 handling 消失，backend 不再传 human_takeover，
     下一条用户消息不再进入本节点，agent 自动回复自动恢复。
"""
from langgraph.types import interrupt

from agent_hina.state import AgentState


def wait_human_node(state: AgentState) -> dict:
    """人工接管中：暂停 agent 自动回复，等待人工通道接管"""
    interrupt({
        "reason": "human_takeover",
        "message": "会话已被人工接管，agent 自动回复已暂停",
    })
    # resume 收尾时会从这里继续，直接结束本轮（不产生回复）
    return {}
