"""
agent_think 节点 —— LLM 决策核心

日奈的人设 + 工具调用 + 状态决策 + 记忆标记

状态提取优先走 update_state 这个 tool call（DeepSeek 稳定输出）。
万一没调，用 regex 扫 ---STATE--- 块兜底。
"""
import json
import re
from datetime import datetime
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage

from agent_hina.state import AgentState
from agent_hina.tools import model_with_tools
from agent_hina import prompts

WINDOW_SIZE = 20  # 每轮送 LLM 的消息条数上限，超出用摘要


# ═══════════════════════════════════════════════════════════════════
# 状态提取（tool call 优先 → regex 兜底 → 猜）
# ═══════════════════════════════════════════════════════════════════

def extract_state(response: AIMessage) -> tuple[AIMessage, dict]:
    """
    从 LLM 回复里拿状态。优先级：
      1. update_state tool call —— 最可靠，DeepSeek 原生支持
      2. ---STATE--- 文本块  —— 旧格式兼容
    返回 (干净回复, 状态字典)
    """
    # ── 方式 1: tool call ──
    if hasattr(response, "tool_calls") and response.tool_calls:
        state_args = {}
        other_calls = []

        for tc in response.tool_calls:
            if tc.get("name") == "update_state":
                state_args = tc.get("args", {})
            else:
                other_calls.append(tc)

        if state_args:
            # 过滤空值
            state_args = {k: v for k, v in state_args.items() if v not in ("", None)}
            clean = AIMessage(
                content=response.content,
                **({"tool_calls": other_calls} if other_calls else {}), # type: ignore
            )
            print(f"  [extract_state] tool_call → {list(state_args.keys())}")
            return clean, state_args

    # ── 方式 2: regex 扫文本 ──
    content = response.content or ""
    match = re.search(r"---STATE---\s*(\{.*?\})\s*---END---", content, re.DOTALL) # type: ignore
    if not match:
        match = re.search(r"(\{[^{}]*\"need_to_save_memory\"[^{}]*\})", content, re.DOTALL) # type: ignore

    if match:
        try:
            state_args = json.loads(match.group(1))
            clean_content = content[:match.start()].strip() # type: ignore
            clean = AIMessage(
                content=clean_content,
                **({"tool_calls": response.tool_calls} if hasattr(response, "tool_calls") and response.tool_calls else {}), # type: ignore
            )
            print(f"  [extract_state] regex → {list(state_args.keys())}")
            return clean, state_args
        except json.JSONDecodeError:
            print(f"  [extract_state] JSON 坏了: {match.group(1)[:100]}")

    # ── 啥都没匹配到 ──
    print(f"  [extract_state] 没拿到状态! 回复末尾:\n{content[-300:]}")
    return response, {}


# ── 对话收尾检测，命中任一 → 需要存记忆 ──
_ENDING_PATTERNS = [
    "再见", "拜拜", "晚安", "早点回来", "路上小心", 
    "回头见", "明天见", "先忙", 
]


def _infer_need_save(user_text: str) -> bool:
    """用户说了告别语 → 对话收尾，需要存记忆"""
    for pattern in _ENDING_PATTERNS:
        if pattern in user_text:
            print(f"  [infer_need_save] 命中「{pattern}」→ need_to_save_memory = true")
            return True
    return False


# ═══════════════════════════════════════════════════════════════════
# 节点主函数
# ═══════════════════════════════════════════════════════════════════

def agent_think_node(state: AgentState) -> dict:
    """每轮核心决策：组 prompt → 调 LLM → 提取状态"""
    now = datetime.now()

    # ── 追加用户消息到 short_session_memory ──
    short_mem = list(state.get("short_session_memory", []))
    all_msgs = state["messages"]
    user_msgs = [m for m in all_msgs if isinstance(m, HumanMessage)]
    latest_text = ""
    if user_msgs:
        latest = user_msgs[-1]
        latest_text = latest.content if hasattr(latest, "content") else str(latest)
        if not short_mem or short_mem[-1].get("content") != latest_text:
            short_mem.append({"role": "user", "content": latest_text})

    # ── 用户画像（AgentMemory 生成，backend 每轮注入 AgentState.portrait；
    #    缺省时提示词走「暂无用户档案」兜底）──
    relationship_context = state.get("portrait") or ""

    # ── 往日的陪伴：日终总结存档（daily_archive，每天日清时 append 当日总结，
    #    这里注入系统提示，让日奈"记得昨天聊了什么"，次日首条消息即可自然接续）──
    archive = state.get("daily_archive") or []
    archive_context = ""
    if isinstance(archive, list) and archive:
        recent_archive = archive[-7:]  # 只带最近 7 天，防上下文过长
        archive_context = "\n\n【往日的陪伴（每天的日终总结，可自然接续话题）】\n" + "\n".join(
            f"- {a}" for a in recent_archive if a
        )

    system_text = prompts.SYSTEM_PROMPT.format(
        time=now.strftime("%Y年%m月%d日 %H:%M"),
        relationship_context=relationship_context or "（暂无用户档案）",
    ) + archive_context

    # ── 深度安抚模式：中/低危命中时用 SAFETY_COMFORT_LOW_PROMPT 覆写系统提示词末尾；
    #    高危命中时用 SAFETY_COMFORT_HIGH_LONG_PROMPT（持续陪伴 + 引导热线）──
    if state.get("needs_deep_comfort"):
        # 从完整对话历史取最近 5 条（含日奈回复），让安抚模式有上下文可依
        recent_ctx = "\n".join(
            f"{'用户' if isinstance(m, HumanMessage) else '日奈'}: {getattr(m, 'content', '')}"
            for m in all_msgs[-5:]
        )
        if state.get("high_risk"):
            comfort_prompt = prompts.build_safety_comfort_high_long_prompt(
                user_message=latest_text, recent_context=recent_ctx
            )
            print("  [agent_think] 高危持续深度安抚模式已开启")
        else:
            comfort_prompt = prompts.build_safety_comfort_low_prompt(
                user_message=latest_text, recent_context=recent_ctx
            )
            print("  [agent_think] 深度安抚模式已开启")
        system_text += "\n\n" + comfort_prompt

    # ── 滑动窗口 ──
    all_msgs = state["messages"]
    if len(all_msgs) > WINDOW_SIZE:
        recent_msgs = list(all_msgs[-WINDOW_SIZE:])
        summary = state.get("long_session_memory", "")
        if summary:
            summary_text = str(summary) if isinstance(summary, str) else "\n".join(
                [f"{m.get('role','?')}: {m.get('content','')}" for m in summary] if isinstance(summary, list) else [str(summary)]
            )
            recent_msgs.insert(0, SystemMessage(
                content=f"【更早的对话摘要（已自动压缩）】\n{summary_text}\n---以下是最新---"
            ))
        print(f"  [agent_think] 窗口: {len(all_msgs)} → {len(recent_msgs)}")
    else:
        recent_msgs = list(all_msgs)

    # ── 调 LLM ──
    system_msg = SystemMessage(content=system_text)
    response = model_with_tools.invoke([system_msg] + recent_msgs)

    # ── 提取状态（tool call → regex → 猜） ──
    clean_response, state_updates = extract_state(response)

    # ── 兜底：模型只调了工具没说话（content 为空，偶发）→ 强制生成回复 ──
    content_text = clean_response.content or ""  # type: ignore
    if not content_text.strip(): # type: ignore
        if latest_text:
            # LLM 只调了工具没说话 → 补一句自然回复，避免空回复丢消息
            fallback_topic = latest_text
            print(f"  [agent_think] ⚠️ 无文字回复，补生成: {fallback_topic[:30]}")
            try:
                from agent_hina.models import chat_model
                fb = chat_model.invoke(
                    f"你是日奈。刚才你只顾着更新状态忘了说话，用户对你说：「{fallback_topic}」\n"
                    f"现在用日奈的语气补一句自然的回复（10-40字）。直接输出，不要括号、"
                    f"不要动作描写、不要提及「状态」「工具」这些词。"
                )
                fb_text = fb.content.strip() if fb.content else ""  # type: ignore
                if fb_text:
                    clean_response = AIMessage(content=fb_text)
                    reply_text = fb_text
                    print(f"  [agent_think] 空回复补生成成功: {fb_text[:50]}...")
            except Exception as e:
                print(f"  [agent_think] 补生成失败: {e}")


    # ── 兜底：LLM 没调 update_state → 规则检测是否需要存记忆 ──
    if "need_to_save_memory" not in state_updates:
        state_updates["need_to_save_memory"] = _infer_need_save(latest_text)  # type: ignore

    # ── 追加日奈回复 ──
    if clean_response.content and clean_response.content.strip():  # type: ignore
        short_mem.append({"role": "assistant", "content": clean_response.content})

    return {
        "messages": [clean_response],
        "short_session_memory": short_mem,
        **state_updates,
    }
