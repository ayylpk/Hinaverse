"""
save_memory 节点 —— 对话结束轻度压缩，摘要存入长期记忆

触发条件: need_to_save_memory == True（由 agent_think 判断，或规则兜底）
作用:     把 short_session_memory 用 LLM 轻度压缩成一条记忆摘要，
         追加到 long_session_memory，然后清空 short。
"""
import json
import re
from datetime import datetime

from agent_hina.state import AgentState
from agent_hina.models import save_memory_model
from agent_hina.prompts import build_memory_save_prompt


def save_memory_node(state: AgentState) -> dict:
    """
    对话收尾存记忆：
      - short 为空 → 跳过
      - 否则 LLM 轻度压缩 short → 追加到 long，清空 short
    """
    short_mem = state.get("short_session_memory", [])
    if not isinstance(short_mem, list) or not short_mem:
        print("  [save_memory] short 为空，跳过")
        return {}

    # ── 转成可读文本 ──
    memory_content = "\n".join(
        [f"{m.get('role', '?')}: {m.get('content', '')}" for m in short_mem]
    )
    now = datetime.now()

    prompt = build_memory_save_prompt(
        time=now.strftime("%Y年%m月%d日 %H:%M"),
        memory_content=memory_content,
    )

    summary = ""
    try:
        response = save_memory_model.invoke(prompt)
        raw = (response.content or "").strip()  # type: ignore
        # 解析 JSON 拿 summary
        parsed = _parse_json(raw)
        summary = parsed.get("summary", "") if isinstance(parsed, dict) else ""
        if not summary:
            summary = raw[:200]
        print(f"  [save_memory] 压缩: {len(memory_content)} 字 → {len(summary)} 字")
    except Exception as e:
        print(f"  [save_memory] 压缩失败: {e}，保留原文截断")
        summary = memory_content[:200]

    # ── 追加到 long ──
    long_mem = list(state.get("long_session_memory", []))
    if not isinstance(long_mem, list):
        long_mem = []
    long_mem.append({"role": "system", "content": summary})

    return {
        "long_session_memory": long_mem,
        "short_session_memory": [],
    }


def _parse_json(text: str) -> dict:
    """从 LLM 回复里容错提取 JSON 对象"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}
