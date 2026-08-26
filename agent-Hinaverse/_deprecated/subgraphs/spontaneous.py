"""
spontaneous_thought 子图 —— 日奈自发想法生成

两种模式，子图自己检测，不靠父图传参:
    reactive   = short_session_memory 有内容 → 刚跟他说过话，基于对话产出想法
    autonomous = short_session_memory 为空   → 定时触发，基于今日摘要 + 时间判断

触发路径:
    reactive:   父图 save_memory → spontaneous_thought → schedule → END
    autonomous: 定时器 "[系统状态切换] 自主思考" → route_at_start → spontaneous_thought → schedule → END

内部结构:
    START → decide ──┬── END (不值得)
                      └── generate → persist → END

persist 每次运行后会设下一次自主思考闹钟（2-3 小时后），形成自维持循环。
"""

import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from agent_hina.state import AgentState
from agent_hina.models import chat_model
from agent_hina.prompts import (
    build_spontaneous_decide_prompt,
    build_spontaneous_generate_prompt,
    build_autonomous_decide_prompt,
    build_autonomous_generate_prompt,
)

TIMELINE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "time-line.md"

# 自主思考间隔: 2~4 小时（分钟随机），只在 7:00-23:00 之间设
AUTONOMOUS_INTERVAL_MIN = 120  # 分钟
AUTONOMOUS_INTERVAL_MAX = 240  # 最多 4 小时
AUTONOMOUS_WAKE_START = 7     # 最早 7 点
AUTONOMOUS_WAKE_END = 23      # 最晚 23 点

# 主动闹钟数量上限，超过不再生成新闹钟（防止堆积）
MAX_ACTIVE_ALARMS = 2


# ═══════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════

def _read_existing_alarms() -> str:
    """读取 time-line.md 中所有闹钟，返回格式化文本供 LLM 参考"""
    if not TIMELINE_FILE.exists():
        return "暂无已设闹钟"
    content = TIMELINE_FILE.read_text(encoding="utf-8")
    alarms = [
        l.strip()
        for l in content.splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]
    return "\n".join(alarms) if alarms else "暂无已设闹钟"


def _detect_mode(state: AgentState) -> str:
    """检测模式: 有 short_memory → reactive, 空 → autonomous
    系统主动触发(alarm_type 有值)强制 autonomous，避免后台闹钟基于虚假的 short_memory
    产出「他没回我」这类错误闹钟，导致闹钟级联循环。"""
    if state.get("alarm_type"):
        return "autonomous"
    short_mem = state.get("short_session_memory", [])
    if short_mem:
        return "reactive"
    return "autonomous"


def _read_relationship_context() -> str:
    """读取关系档案，autonomous 模式需要用"""
    rel_file = Path(__file__).resolve().parent.parent.parent / "data" / "relationship-with-user.md"
    if rel_file.exists():
        return rel_file.read_text(encoding="utf-8")[:1500]  # 取前 1500 字，不用全量
    return "暂无"


def _write_alarm_line(line: str):
    """追加一行到 time-line.md"""
    TIMELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMELINE_FILE.touch(exist_ok=True)
    current = TIMELINE_FILE.read_text(encoding="utf-8")
    if current and not current.endswith("\n"):
        current += "\n"
    TIMELINE_FILE.write_text(current + line + "\n", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════
# 1. decide 节点
# ═══════════════════════════════════════════════════════════════════

def decide_node(state: AgentState) -> dict:
    """
    自检 mode → 选 prompt → LLM 判断是否值得产出想法。
    reactive:   看刚才的对话有没有后续跟进点
    autonomous: 看时间 + 今日摘要 + 关系档案，有没有需要关心的事
    """
    mode = _detect_mode(state)
    now = datetime.now()

    # ── reactive 模式 ──
    if mode == "reactive":
        short_mem = state.get("short_session_memory", [])
        conversation_text = "\n".join(
            [f"{m.get('role', '?')}: {m.get('content', '')}" for m in short_mem]
        )

        long_mem = state.get("long_session_memory", [])
        if isinstance(long_mem, list) and long_mem:
            long_text = "\n".join(
                [f"- {m.get('content', '')}" for m in long_mem if m.get("content")]
            )
        elif isinstance(long_mem, str):
            long_text = long_mem
        else:
            long_text = "暂无"

        prompt_text = build_spontaneous_decide_prompt(
            conversation_text=conversation_text,
            long_summary=long_text,
            existing_alarms=_read_existing_alarms(),
        )
        print("  [spontaneous:decide] 模式: reactive")

    # ── autonomous 模式 ──
    else:
        long_mem = state.get("long_session_memory", [])
        if isinstance(long_mem, list) and long_mem:
            long_text = "\n".join(
                [f"- {m.get('content', '')}" for m in long_mem if m.get("content")]
            )
        elif isinstance(long_mem, str):
            long_text = long_mem
        else:
            long_text = "暂无今日摘要"

        prompt_text = build_autonomous_decide_prompt(
            current_time=now.strftime("%Y-%m-%d %H:%M"),
            long_summary=long_text,
            existing_alarms=_read_existing_alarms(),
            relationship_context=_read_relationship_context(),
        )
        print("  [spontaneous:decide] 模式: autonomous")

    system_msg = SystemMessage(content=f"当前时间: {now.strftime('%Y年%m月%d日 %H:%M')}")

    try:
        response = chat_model.invoke([system_msg, HumanMessage(content=prompt_text)])
        raw = response.content.strip() if response.content else ""  # type: ignore
        print(f"  [spontaneous:decide] LLM 输出: {raw[:80]}")

        raw_lower = raw.strip().lower()
        # 只认明确的肯定词，防止 "not true" / 带解释的输出误判
        should_think = (
            raw_lower in ("true", "yes", "y", "1")
            or raw_lower.startswith("true")
            or raw_lower.startswith("yes")
        )

        label = "值得" if should_think else "不值得"
        print(f"  [spontaneous:decide] → {label}产出想法")

        # 不管值不值得，都要续上下一次自主思考闹钟
        if not should_think:
            _set_next_autonomous()

    except Exception as e:
        print(f"  [spontaneous:decide] LLM 调用失败: {e}")
        should_think = False

    return {"_should_think": should_think, "_think_mode": mode}


# ═══════════════════════════════════════════════════════════════════
# 2. generate 节点
# ═══════════════════════════════════════════════════════════════════

def generate_node(state: AgentState) -> dict:
    """
    自检 mode → 选 prompt → LLM 产出 1-2 个想法。
    """
    mode = state.get("_think_mode", "reactive")
    now = datetime.now()

    if mode == "reactive":
        short_mem = state.get("short_session_memory", [])
        conversation_text = "\n".join(
            [f"{m.get('role', '?')}: {m.get('content', '')}" for m in short_mem]
        )
        prompt_text = build_spontaneous_generate_prompt(
            conversation_text=conversation_text,
            existing_alarms=_read_existing_alarms(),
            current_time=now.strftime("%Y-%m-%d %H:%M"),
        )
    else:
        long_mem = state.get("long_session_memory", [])
        if isinstance(long_mem, list) and long_mem:
            long_text = "\n".join(
                [f"- {m.get('content', '')}" for m in long_mem if m.get("content")]
            )
        elif isinstance(long_mem, str):
            long_text = long_mem
        else:
            long_text = "暂无今日摘要"

        prompt_text = build_autonomous_generate_prompt(
            current_time=now.strftime("%Y-%m-%d %H:%M"),
            long_summary=long_text,
            existing_alarms=_read_existing_alarms(),
            relationship_context=_read_relationship_context(),
        )

    print(f"  [spontaneous:generate] 模式: {mode}")
    system_msg = SystemMessage(content=f"当前时间: {now.strftime('%Y年%m月%d日 %H:%M')}")

    try:
        response = chat_model.invoke([system_msg, HumanMessage(content=prompt_text)])
        raw = response.content.strip() if response.content else ""  # type: ignore
        print(f"  [spontaneous:generate] LLM 原始: {raw[:120]}")

        json_match = re.search(r"\[[\s\S]*?\]", raw)
        if json_match:
            ideas = json.loads(json_match.group())
        else:
            ideas = json.loads(raw)

        if not isinstance(ideas, list):
            print("  [spontaneous:generate] 输出非数组，丢弃")
            return {"_generated_alarms": []}

        print(
            f"  [spontaneous:generate] 产出 {len(ideas)} 个想法: "
            f"{[i.get('reason', '')[:30] for i in ideas]}"
        )
        return {"_generated_alarms": ideas}

    except json.JSONDecodeError as e:
        print(f"  [spontaneous:generate] JSON 解析失败: {e}")
        return {"_generated_alarms": []}
    except Exception as e:
        print(f"  [spontaneous:generate] LLM 调用失败: {e}")
        return {"_generated_alarms": []}


# ═══════════════════════════════════════════════════════════════════
# 3. persist 节点
# ═══════════════════════════════════════════════════════════════════

def persist_node(state: AgentState) -> dict:
    """
    1. 校验 generate 产出的想法 → 去重 → 追加 time-line.md
    2. 设定下一次自主思考闹钟（自维持循环）
    """
    ideas = state.get("_generated_alarms", [])

    # ── 读已有闹钟（去重用 + 数量限制）──
    existing_reasons: set[str] = set()
    active_count = 0  # 未触发的「主动」闹钟数
    if TIMELINE_FILE.exists():
        for line in TIMELINE_FILE.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split("|", maxsplit=2)
            if len(parts) >= 3:
                existing_reasons.add(parts[2].strip())
                if parts[1].strip() == "主动":
                    active_count += 1

    # #1 修复：已有 2 个以上主动闹钟 → 不写新的，防止堆积级联
    if active_count >= MAX_ACTIVE_ALARMS:
        print(f"  [spontaneous:persist] 已有 {active_count} 个主动闹钟 (上限 {MAX_ACTIVE_ALARMS})，跳过新闹钟")
        _set_next_autonomous()
        return {}

    # ── 校验 + 去重 + 写入 ──
    new_lines: list[str] = []
    for idea in ideas:
        time_str = idea.get("time", "")
        alarm_type = idea.get("type", "主动")
        reason = idea.get("reason", "")

        if not time_str or not reason:
            continue
        try:
            target_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            continue
        if target_time <= datetime.now():
            continue
        if reason.strip() in existing_reasons:
            continue
        if alarm_type not in ("主动", "状态"):
            alarm_type = "主动"

        line = f"{time_str} | {alarm_type} | {reason}"
        new_lines.append(line)
        existing_reasons.add(reason.strip())
        print(f"  [spontaneous:persist] 写入: {line}")

    for line in new_lines:
        _write_alarm_line(line)
    if new_lines:
        print(f"  [spontaneous:persist] 已追加 {len(new_lines)} 条")

    # ── 设下一次自主思考闹钟 ──
    _set_next_autonomous()

    return {}


def _set_next_autonomous():
    """
    在 time-line.md 写入下一次自主思考闹钟。
    间隔 2~3 小时随机，只在 7:00-23:00 之间设。
    如果下次时间超过 23:00，推到明天 7:00 之后。
    """
    now = datetime.now()
    interval = random.randint(AUTONOMOUS_INTERVAL_MIN, AUTONOMOUS_INTERVAL_MAX)
    next_time = now + timedelta(minutes=interval)

    # 如果超过晚上 22 点，推到明天早上 8-9 点
    if next_time.hour >= AUTONOMOUS_WAKE_END:
        tomorrow = next_time + timedelta(days=1)
        morning_minute = random.randint(0, 59)
        next_time = tomorrow.replace(
            hour=AUTONOMOUS_WAKE_START, minute=morning_minute, second=0, microsecond=0
        )

    # 如果早于早上 8 点，也推到 8 点后
    if next_time.hour < AUTONOMOUS_WAKE_START:
        morning_minute = random.randint(0, 59)
        next_time = next_time.replace(
            hour=AUTONOMOUS_WAKE_START, minute=morning_minute, second=0, microsecond=0
        )

    time_str = next_time.strftime("%Y-%m-%d %H:%M")
    line = f"{time_str} | 状态 | 自主思考"

    # 检查是否已有「未来」的自主思考闹钟，避免重复；过期残留行不拦截
    if TIMELINE_FILE.exists():
        now_check = datetime.now()
        for existing in TIMELINE_FILE.read_text(encoding="utf-8").splitlines():
            if "自主思考" not in existing:
                continue
            parts = existing.strip().split("|", maxsplit=2)
            try:
                t = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M")
                if t > now_check:
                    print(f"  [spontaneous:persist] 已有未来自主思考闹钟，跳过: {existing.strip()}")
                    return
            except (ValueError, IndexError):
                continue
        print("  [spontaneous:persist] 已有自主思考闹钟均已过期，允许重设")

    _write_alarm_line(line)
    print(f"  [spontaneous:persist] 下次自主思考: {line}")


# ═══════════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════════

def should_think(state: AgentState) -> Literal["generate", END]:  # type: ignore
    if state.get("_should_think", False):
        return "generate"
    return END


# ═══════════════════════════════════════════════════════════════════
# 构建子图入口
# ═══════════════════════════════════════════════════════════════════

def build_spontaneous_thought_subgraph():
    builder = StateGraph(AgentState)

    builder.add_node("decide", decide_node)
    builder.add_node("generate", generate_node)
    builder.add_node("persist", persist_node)

    builder.add_edge(START, "decide")
    builder.add_conditional_edges("decide", should_think, {
        "generate": "generate",
        END: END,
    })
    builder.add_edge("generate", "persist")
    builder.add_edge("persist", END)

    return builder.compile()
