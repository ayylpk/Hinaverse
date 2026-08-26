"""
daily_compress 节点 —— 日终压缩（定时任务触发）

职责：
    1. 把今日 long_session_memory 轻度压缩 → 明日初始上下文（覆盖 long）
    2. 根据今日内容生成一段「给用户的日终陪伴总结」（_daily_summary_text，由调用方存库/推送）

触发方式：
    backend 定时任务每天固定时间对每个用户发 "[系统状态切换] 日终压缩"，
    route_at_start 路由到本节点；压缩完成后直接 END，
    总结文本在 result["_daily_summary_text"] 中，由 backend 落库并推送给用户。

记忆闭环（含日终）：
    对话结束 → save_memory 轻度压缩入 long
    long ≥ 3 条 → reduce_memory 中度压缩覆盖 long
    每天日终 → daily_compress 把今日 long 压缩为摘要（明日自然接续）+ 生成日终总结
"""
from datetime import datetime
from pathlib import Path

from langchain_core.messages import SystemMessage, HumanMessage

from agent_hina.state import AgentState
from agent_hina.models import write_model, reduce_model
from agent_hina.prompts import (
    build_memory_daily_compress_prompt,
    build_daily_summary_prompt,
)

# 未来由用户画像系统（AgentMemory）经接口注入；当前为空
def _read_relationship_context() -> str:
    return ""


def daily_compress_node(state: AgentState) -> dict:
    """日终：轻度压缩今日记忆 + 生成给用户的日终总结"""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")

    # ── 取今日记忆 ──
    long_mem = state.get("long_session_memory", [])
    short_mem = state.get("short_session_memory", [])

    if isinstance(long_mem, list) and long_mem:
        memory_text = "\n".join(
            [f"- {m.get('content', '')}" for m in long_mem if m.get("content")]
        )
    elif isinstance(long_mem, str) and long_mem.strip():
        memory_text = long_mem
    elif short_mem:
        memory_text = "\n".join(
            [f"{m.get('role', '?')}: {m.get('content', '')}" for m in short_mem]
        )
    else:
        print("  [daily_compress] long 和 short 均为空，跳过")
        return {"_daily_summary_text": ""}

    relationship_context = _read_relationship_context()

    # ── 1. 轻度压缩今日记忆 → 明日初始上下文 ──
    daily_summary = ""
    try:
        response = reduce_model.invoke(
            build_memory_daily_compress_prompt(memory_text)
        )
        daily_summary = (response.content or "").strip()  # type: ignore
        print(f"  [daily_compress] 压缩: {len(memory_text)} 字 → {len(daily_summary)} 字")
    except Exception as e:
        print(f"  [daily_compress] 压缩失败: {e}")
        daily_summary = memory_text[:500]

    # ── 2. 生成给用户的日终陪伴总结 ──
    summary_text = ""
    if daily_summary:
        try:
            response = write_model.invoke([
                SystemMessage(content=f"当前时间: {now.strftime('%Y年%m月%d日 %H:%M')}"),
                HumanMessage(content=build_daily_summary_prompt(
                    date_str, memory_text, relationship_context
                )),
            ])
            summary_text = (response.content or "").strip()  # type: ignore
            print(f"  [daily_compress] 日终总结 ({len(summary_text)} 字)")
        except Exception as e:
            print(f"  [daily_compress] 日终总结生成失败: {e}")

    # ── 3. 覆盖 long（明日自然接续昨日摘要），清空 short ──
    return {
        "long_session_memory": (
            [{"role": "system", "content": daily_summary}] if daily_summary
            else list(long_mem)
        ),
        "short_session_memory": [],
        "_daily_summary_text": summary_text,
    }
