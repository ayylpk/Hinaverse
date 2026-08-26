"""
Agent 对接层 —— 本轮的关键抽象。

真实接入时只改这一个文件：把 generate_reply 里的 mock 替换成
调用 `agent-Hinaverse/agent_hina` 的 LangGraph 图即可。
注意点（注释约定，真实接入时务必遵守）：
  1. LangGraph 图是 async 的，且 LLM 调用耗时长（几秒到几十秒），
     必须用 asyncio.create_task 或线程池隔离，不能阻塞 WS 事件循环。
  2. 多用户并发：每个会话用独立的 thread_id（configurable.thread_id），
     避免用户间记忆串线。
  3. history 只传最近 N 条（如 20 条），避免上下文超长。
"""
import random
from typing import Any

# 温和、不说教、短句的 mock 回复池，文风对齐前端 ChatWindow.vue 的 mockReplies
_MOCK_REPLIES = [
    "嗯，我在听。慢慢说，不着急。",
    "听起来你今天不太好受。要不要先深呼吸一下？",
    "我懂这种感觉。不用急着证明什么，你已经很努力了。",
    "你愿意说出来，就已经很好了。我都在。",
    "嗯……换作是我，可能也会这样想。",
    "你不需要把一切都处理得很好。累了就歇一歇，我陪着你。",
    "夜越深，星星越亮。你现在说的话，正在变成你自己的星座。",
    "谢谢你愿意告诉我这些。我会把它收进夜空里，好好记住。",
    "不用急着给答案，先让情绪待一会儿也没关系。",
    "我在这里，不会走。你想说到什么时候都可以。",
]


async def generate_reply(
    user_message: str,
    user_profile: dict[str, Any],
    history: list[dict[str, Any]],
) -> str:
    """
    生成日奈的回复。

    本轮为 mock 实现：随机返回一句温和回复。
    真实接入时替换为调用 LangGraph 图：
        from agent_hina.graph import build_hina_graph
        graph = await build_hina_graph()
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=user_message)]},
            config={"configurable": {"thread_id": str(conversation_id)}},
        )
        # 从 result 里提取回复文本
    """
    # 模拟 LLM 思考延迟，让前端 typing 动画有意义
    import asyncio
    await asyncio.sleep(0.8 + random.random() * 0.7)

    # 简单上下文感知：用户消息里有问号时，优先给共情式回复
    if "？" in user_message or "?" in user_message:
        empathetic = [r for r in _MOCK_REPLIES if "嗯" in r or "懂" in r or "听" in r]
        if empathetic:
            return random.choice(empathetic)
    return random.choice(_MOCK_REPLIES)
