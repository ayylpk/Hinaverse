"""
reduce_memory 节点 —— long 会话记忆压缩

触发条件: long_session_memory 条数 >= 阈值
作用:     调 LLM 把 long 里的内容压缩成 2-3 段摘要，压缩力度偏大
         压缩后的摘要直接覆盖 long（long 是内存缓冲，跨天由 daily_compress 压缩）
"""
from agent_hina.state import AgentState
from agent_hina.models import reduce_model
from agent_hina.prompts import build_memory_reduce_prompt

# 长记忆压缩阈值：long 达到该条数即触发中度压缩（对话结束 save 追加的摘要计数）
COMPRESS_THRESHOLD = 3


def reduce_memory_node(state: AgentState) -> dict:
    """
    检查 long_session_memory 是否超阈值:
      - 没到 → 什么都不做
      - 到了 → LLM 压缩 long 内容 → 覆盖 long → 返回
    """
    long_mem = state.get("long_session_memory", [])
    if not isinstance(long_mem, list):
        long_mem = []

    if len(long_mem) < COMPRESS_THRESHOLD:
        print(f"  [reduce] long 目前 {len(long_mem)} 条，未到阈值 {COMPRESS_THRESHOLD}，跳过压缩")
        return {}

    # ── 转成可读文本 ──
    raw_text = "\n".join(
        [f"- {m.get('role', '?')}: {m.get('content', '')}" for m in long_mem]
    )

    print(f"  [reduce] long 已达 {len(long_mem)} 条，开始压缩...")

    prompt = build_memory_reduce_prompt(raw_text)

    try:
        response = reduce_model.invoke(prompt)
        compressed = response.content.strip()  # type: ignore
        print(f"  [reduce] 压缩完成: {len(raw_text)} 字 → {len(compressed)} 字")
    except Exception as e:
        print(f"  [reduce] 压缩失败: {e}，保留原始 long 不压缩")
        return {}

    return {
        "long_session_memory": [{"role": "system", "content": compressed}],
    }
