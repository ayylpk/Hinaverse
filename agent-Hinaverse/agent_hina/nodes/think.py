"""
agent_think 节点 —— LLM 决策核心

日奈的人设 + 工具调用 + 状态决策 + 记忆标记

状态提取优先走 update_state 这个 tool call（DeepSeek 稳定输出）。
万一没调，用 regex 扫 ---STATE--- 块兜底。
两个都失败就从回复文本猜心情。
"""
import json
import re
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage

from agent_hina.state import AgentState
from agent_hina.tools import model_with_tools
from agent_hina import prompts

load_dotenv()

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


# ═══════════════════════════════════════════════════════════════════
# 兜底：从回复文本猜心情
# ═══════════════════════════════════════════════════════════════════

_MOOD_PATTERNS: list[tuple[str, str]] = [
    ("累了|困了|想睡|晚安|睡觉|去睡", "困倦"),
    ("开心|太好了|嘿嘿|嗯嗯|好啊|行啊", "开心"),
    ("对不起|抱歉|我的错|怪我", "愧疚"),
    ("担心|你没事|还好吗|没事吧|小心", "担心"),
    ("谢谢|多谢|……谢|感谢", "感激"),
    ("嗯|好|知道了|明白了|去吧|路上", "平静"),
    ("烦|头疼|累|唉|叹气|难受", "关切"),
]


def _infer_mood(text: str) -> str:
    """从回复文本猜日奈心情，pattern 一个个试"""
    for pattern, mood in _MOOD_PATTERNS:
        if re.search(pattern, text):
            return mood
    return "普通"


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
# 场景推导
# ═══════════════════════════════════════════════════════════════════

def _infer_scene(status: str) -> str:
    """从 status 关键词推当前场景，关键词都匹配不到时按时间段推断"""
    s = status or ""
    if any(w in s for w in ["刚醒", "起床", "洗漱", "赖床", "醒了"]):
        return "刚醒来，准备开始一天"
    if any(w in s for w in ["做饭", "晚饭", "早饭", "厨房", "煮"]):
        return "在家，厨房"
    if any(w in s for w in ["沙发", "休息", "午休", "看书"]):
        return "在家，休息"
    if any(w in s for w in ["散步", "湖边", "公园"]):
        return "在外面散步"
    if any(w in s for w in ["咖啡", "书店"]):
        return "在咖啡店"
    if any(w in s for w in ["在家", "家里", "公寓"]):
        return "在家"

    # 关键词全没命中 → 按时间段猜
    hour = datetime.now().hour
    if 6 <= hour < 9:
        return "刚醒来，准备开始一天"
    elif 9 <= hour < 12:
        return "安静地待着，随时准备倾听"
    elif 12 <= hour < 14:
        return "在家，午休"
    elif 14 <= hour < 18:
        return "安静地待着，随时准备倾听"
    elif 18 <= hour < 20:
        return "在家，准备晚饭"
    elif 20 <= hour < 23:
        return "在家"
    else:
        return "在家，准备休息"


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

    # ── 用户档案/画像（当前为空，未来由画像系统（AgentMemory）经接口注入）──
    relationship_context = state.get("_portrait", "") or ""
    pending_agreements = ""

    # ── 选 prompt ──
    status = state.get("status", "") or "在线"
    scene = _infer_scene(status)
    print(f"  [agent_think] scene={scene}")

    system_text = prompts.SYSTEM_PROMPT.format(
        time=now.strftime("%Y年%m月%d日 %H:%M"),
        relationship_context=relationship_context or "（暂无用户档案）",
        pending_agreements=pending_agreements or "（暂无待办约定）",
        mood=state.get("mood", "思考中"),
        status=status,
        scene=scene,
    )

    # ── RAG 前置检索 —— 每次回复前强制检索，是否提起由 LLM 自行判断 ──
    remembered: list[str] = []
    query_text = (latest_text or "").strip()
    if query_text:
        try:
            from agent_hina.nodes.retriever import get_retriever
            docs, dists = get_retriever().retrieve(query_text, n=3)
            # L2 距离 < 1.0 视为相关（与 load_memory 工具同标准）
            remembered = [d for d, dist in zip(docs, dists) if dist < 1.0]
            if remembered:
                print(f"  [agent_think] 检索到 {len(remembered)} 条相关记忆")
        except Exception as e:
            print(f"  [agent_think] 记忆检索失败(降级为无记忆): {e}")

    if remembered:
        mem_block = (
            "\n\n【隐约想起的片段——是否提起由你判断】\n"
            + "\n".join(f"- {m}" for m in remembered)
            + "\n（与当前话题相关且自然就带出来；无关或生硬就忽略。"
              "禁止逐条复述、禁止刻意引用「我记得」式开场。）"
        )
        system_text += mem_block

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
    if not content_text.strip():
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

    # ── 兜底：mood / status 还是空的就猜 ──
    reply_text = clean_response.content or ""  # type: ignore
    if not state_updates.get("mood"):
        state_updates["mood"] = _infer_mood(reply_text) # type: ignore
    if not state_updates.get("status"):
        state_updates["status"] = "在线"

    # ── 兜底：LLM 没调 update_state → 规则检测是否需要存记忆 ──
    if "need_to_save_memory" not in state_updates:
        state_updates["need_to_save_memory"] = _infer_need_save(latest_text)  # type: ignore

    # ── 追加日奈回复 ──
    if clean_response.content and clean_response.content.strip():  # type: ignore
        short_mem.append({"role": "assistant", "content": clean_response.content})

    return {
        "messages": [clean_response],
        "short_session_memory": short_mem,
        "remembered_memories": remembered,
        **state_updates,
    }
