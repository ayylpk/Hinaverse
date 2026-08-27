"""
日奈 Agent（心理健康陪伴者）的共享 State
─────────────────────
messages:              对话历史（短期上下文），add_messages 自动拼接
short_session_memory: 短会话记忆（对话结束清空，经轻度压缩存入长记忆）
long_session_memory:  长会话记忆（满阈值后中度压缩）
need_to_save_memory:  LLM 判断本轮是否值得存入长期记忆
needs_human:          是否需要暂停等用户确认
mood:                 日奈现在的情绪
status:               日奈现在在做什么
tool_results:         本轮工具调用结果列表
needs_deep_comfort:   中/低危安全检测命中时为 True，触发深度安抚模式提示词覆写
"""
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]     # 对话历史（短期上下文），add_messages 自动拼接
    short_session_memory: list                  # 短会话记忆（对话结束清空，轻度压缩入长记忆）
    long_session_memory: list                   # 长会话记忆（满 3 条后中度压缩覆盖）
    need_to_save_memory: bool
    needs_human: bool                           # 是否需要暂停等用户确认
    mood: str                                   # 日奈现在的情绪
    status: str                                 # 日奈现在在做什么
    tool_results: list                          # 本轮工具调用结果列表
    _daily_summary_text: str                    # 日终压缩产出的「给用户的日终陪伴总结」（backend 取走落库/推送）
    needs_deep_comfort: bool                    # 中/低危命中时由 backend 传入，触发深度安抚模式
