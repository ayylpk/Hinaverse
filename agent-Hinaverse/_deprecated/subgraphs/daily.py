"""
daily_compress 子图 —— 日终: 入睡 → (可能失眠) → 压缩记忆 → 设定明天

触发时机: 系统时间到达当天的「睡觉」闹钟时，由 route_at_start 路由进入
          不经过 agent_think，是系统自动执行的维护任务

内部结构:
    START → write_daily → try_sleep ─┬─ 睡着 → compress → persist_daily → set_tomorrow → END
                                     └─ 失眠 → insomnia_think → persist_insomnia → retry_sleep → END

节点职责:
    write_daily       = 日奈睡前写日记，输出到 Chroma (type: diary)
    try_sleep         = random(1,100) > 20 则睡着
    compress          = LLM 日奈第一人称轻度压缩今日记忆
    persist_daily     = 写 Chroma + 清空 long/short
    set_tomorrow      = 清除旧闹钟 + 写明天 random 起床/睡觉 + 重置 _sleepiness
    insomnia_think    = LLM 以日奈视角失眠胡思乱想，产出想法 JSON
    persist_insomnia  = 校验 + 去重 + 写入 time-line.md (主动)
    retry_sleep       = 写 20~40 分钟后「睡觉」闹钟
"""

import json
import random
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from agent_hina.state import AgentState
from agent_hina.models import reduce_model, chat_model
from agent_hina.memory_store import get_collection
from agent_hina.subgraphs.write_daily import write_daily_node
from agent_hina.prompts import (
    build_memory_daily_compress_prompt,
    build_insomnia_think_prompt,
)

TIMELINE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "time-line.md"

# 睡眠参数
SLEEP_THRESHOLD = 20            # random(1,100) > 此值 → 睡着
RETRY_SLEEP_MINUTES = 10        # 失眠后固定间隔
BED_START_HOUR = 23
BED_END_HOUR = 0
WAKE_START_HOUR = 6
WAKE_END_HOUR = 7


# ═══════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════

def _read_relationship_context() -> str:
    rel_file = Path(__file__).resolve().parent.parent.parent / "data" / "relationship-with-user.md"
    if rel_file.exists():
        return rel_file.read_text(encoding="utf-8")[:1200]
    return "暂无"


# ═══════════════════════════════════════════════════════════════════
# 0. try_sleep 节点
# ═══════════════════════════════════════════════════════════════════

def try_sleep_node(state: AgentState) -> dict:
    """每次躺下，random(1,100) > 20 就睡着（约80%概率）"""
    roll = random.randint(1, 100)
    asleep = roll > SLEEP_THRESHOLD
    print(f"  [daily:try_sleep] roll={roll} {'>'+str(SLEEP_THRESHOLD) if asleep else '<='+str(SLEEP_THRESHOLD)} → {'睡着了 zzz' if asleep else '失眠...'}")
    return {"_sleepiness": roll, "_asleep": asleep}


def route_sleep(state: AgentState) -> Literal["compress", "insomnia_think"]:  # type: ignore
    if state.get("_asleep", False):
        return "compress"
    return "insomnia_think"


# ═══════════════════════════════════════════════════════════════════
# 1. compress 节点 (不变)
# ═══════════════════════════════════════════════════════════════════

def compress_node(state: AgentState) -> dict:
    long_mem = state.get("long_session_memory", [])
    short_mem = state.get("short_session_memory", [])

    if isinstance(long_mem, list) and long_mem:
        raw_text = "\n".join(
            [f"{m.get('role', '?')}: {m.get('content', '')}" for m in long_mem]
        )
    elif isinstance(long_mem, str) and long_mem.strip():
        raw_text = long_mem
    elif short_mem:
        raw_text = "\n".join(
            [f"{m.get('role', '?')}: {m.get('content', '')}" for m in short_mem]
        )
    else:
        print("  [daily:compress] long 和 short 均为空，跳过压缩")
        return {"_daily_summary": ""}

    try:
        response = reduce_model.invoke(build_memory_daily_compress_prompt(raw_text))
        summary = response.content.strip()  # type: ignore
        print(f"  [daily:compress] {len(raw_text)} 字 → {len(summary)} 字")
        return {"_daily_summary": summary}
    except Exception as e:
        print(f"  [daily:compress] LLM 失败: {e}")
        return {"_daily_summary": raw_text[:500]}


# ═══════════════════════════════════════════════════════════════════
# 2. persist_daily 节点 (不变)
# ═══════════════════════════════════════════════════════════════════

def persist_daily_node(state: AgentState) -> dict:
    summary = state.get("_daily_summary", "")
    if not summary:
        print("  [daily:persist] 摘要为空")
        return {"long_session_memory": [], "short_session_memory": [], "_new_day": False}

    try:
        collection = get_collection()
        collection.add(
            ids=[f"daily-{uuid.uuid4().hex[:8]}"],
            documents=[summary],
            metadatas=[{
                "timestamp": datetime.now().isoformat(),
                "memory_type": "daily_summary",
                "keywords": "日终总结",
            }],
        )
        print(f"  [daily:persist] Chroma 写入成功")
    except Exception as e:
        print(f"  [daily:persist] Chroma 失败: {e}")

    # 置 _new_day 标志，由 agent_think 在下一轮重建 messages（add_messages 无法直接清空）
    return {
        "long_session_memory": [],
        "short_session_memory": [],
        "_new_day": True,
        "_daily_summary": summary,
    }


# ═══════════════════════════════════════════════════════════════════
# 3. set_tomorrow 节点
# ═══════════════════════════════════════════════════════════════════

def set_tomorrow_node(state: AgentState) -> dict:
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    wake_minute = random.randint(0, 59)
    bed_minute = random.randint(0, 59)

    wake_time = f"{tomorrow} {WAKE_START_HOUR:02d}:{wake_minute:02d}"
    bed_time = f"{tomorrow} {BED_START_HOUR:02d}:{bed_minute:02d}"

    wake_line = f"{wake_time} | 状态 | 起床"
    bed_line = f"{bed_time} | 状态 | 睡觉"
    # 起床后 2~3 小时设一个自主思考，保持主动关心的循环
    auto_hour = random.randint(WAKE_START_HOUR + 2, WAKE_START_HOUR + 3)
    auto_minute = random.randint(0, 59)
    auto_line = f"{tomorrow} {auto_hour:02d}:{auto_minute:02d} | 状态 | 自主思考"

    # 保留注释行，清除旧闹钟
    header_lines: list[str] = []
    if TIMELINE_FILE.exists():
        for line in TIMELINE_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("#") or s.startswith(">"):
                header_lines.append(line)

    new_content = "\n".join(header_lines)
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"
    new_content += f"{wake_line}\n{auto_line}\n{bed_line}\n"

    TIMELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMELINE_FILE.write_text(new_content, encoding="utf-8")

    print(f"  [daily:set_tomorrow] 起床 {wake_time}  睡觉 {bed_time}")
    return {"_sleepiness": 0}


# ═══════════════════════════════════════════════════════════════════
# 4. insomnia_think 节点 (新增)
# ═══════════════════════════════════════════════════════════════════

def insomnia_think_node(state: AgentState) -> dict:
    """失眠了，LLM 以日奈视角胡思乱想，产出 1 个想法"""
    now = datetime.now()

    long_mem = state.get("long_session_memory", [])
    if isinstance(long_mem, list) and long_mem:
        long_text = "\n".join(
            [f"- {m.get('content', '')}" for m in long_mem if m.get("content")]
        )
    elif isinstance(long_mem, str):
        long_text = long_mem
    else:
        long_text = "暂无"

    prompt_text = build_insomnia_think_prompt(
        current_time=now.strftime("%Y-%m-%d %H:%M"),
        long_summary=long_text,
        relationship_context=_read_relationship_context(),
        sleepiness=state.get("_sleepiness", 0),
    )

    system_msg = SystemMessage(content=f"当前时间: {now.strftime('%Y年%m月%d日 %H:%M')}")

    try:
        response = chat_model.invoke([system_msg, HumanMessage(content=prompt_text)])
        raw = response.content.strip() if response.content else ""  # type: ignore
        print(f"  [daily:insomnia] LLM: {raw[:100]}")

        m = re.search(r"\[[\s\S]*?\]", raw)
        ideas = json.loads(m.group()) if m else json.loads(raw)
        if not isinstance(ideas, list):
            ideas = []
        print(f"  [daily:insomnia] 产出 {len(ideas)} 个失眠想法")
        return {"_generated_alarms": ideas}
    except Exception as e:
        print(f"  [daily:insomnia] 失败: {e}")
        return {"_generated_alarms": []}


# ═══════════════════════════════════════════════════════════════════
# 5. persist_insomnia 节点 (新增)
# ═══════════════════════════════════════════════════════════════════

def persist_insomnia_node(state: AgentState) -> dict:
    """失眠想法写入 time-line.md"""
    ideas = state.get("_generated_alarms", [])
    if not ideas:
        print("  [daily:persist_insomnia] 无想法")
        return {}

    existing_reasons: set[str] = set()
    if TIMELINE_FILE.exists():
        for line in TIMELINE_FILE.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split("|", maxsplit=2)
            if len(parts) >= 3:
                existing_reasons.add(parts[2].strip())

    written = 0
    for idea in ideas:
        time_str = idea.get("time", "")
        reason = idea.get("reason", "")
        atype = idea.get("type", "主动")
        if not time_str or not reason:
            continue
        try:
            t = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            continue
        if t <= datetime.now():
            continue
        if reason.strip() in existing_reasons:
            continue
        if atype not in ("主动", "状态"):
            atype = "主动"

        line = f"{time_str} | {atype} | {reason}"
        TIMELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TIMELINE_FILE.touch(exist_ok=True)
        content = TIMELINE_FILE.read_text(encoding="utf-8")
        if content and not content.endswith("\n"):
            content += "\n"
        TIMELINE_FILE.write_text(content + line + "\n", encoding="utf-8")
        existing_reasons.add(reason.strip())
        written += 1
        print(f"  [daily:persist_insomnia] 写入: {line[:80]}")

    print(f"  [daily:persist_insomnia] 共写入 {written} 条")
    return {}


# ═══════════════════════════════════════════════════════════════════
# 6. retry_sleep 节点 (新增)
# ═══════════════════════════════════════════════════════════════════

def retry_sleep_node(state: AgentState) -> dict:
    """设 10 分钟后再尝试睡觉"""
    next_time = datetime.now() + timedelta(minutes=RETRY_SLEEP_MINUTES)
    time_str = next_time.strftime("%Y-%m-%d %H:%M")
    line = f"{time_str} | 状态 | 睡觉"

    TIMELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMELINE_FILE.touch(exist_ok=True)
    content = TIMELINE_FILE.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        content += "\n"
    TIMELINE_FILE.write_text(content + line + "\n", encoding="utf-8")

    print(f"  [daily:retry_sleep] 下次尝试: {time_str} ({RETRY_SLEEP_MINUTES}分钟后)")
    return {}


# ═══════════════════════════════════════════════════════════════════
# 构建子图
# ═══════════════════════════════════════════════════════════════════

def build_daily_compress_subgraph():
    builder = StateGraph(AgentState)

    builder.add_node("write_daily", write_daily_node)
    builder.add_node("try_sleep", try_sleep_node)
    builder.add_node("compress", compress_node)
    builder.add_node("persist_daily", persist_daily_node)
    builder.add_node("set_tomorrow", set_tomorrow_node)
    builder.add_node("insomnia_think", insomnia_think_node)
    builder.add_node("persist_insomnia", persist_insomnia_node)
    builder.add_node("retry_sleep", retry_sleep_node)

    builder.add_edge(START, "write_daily")
    builder.add_edge("write_daily", "try_sleep")

    builder.add_conditional_edges("try_sleep", route_sleep, {
        "compress": "compress",
        "insomnia_think": "insomnia_think",
    })

    # 睡着线
    builder.add_edge("compress", "persist_daily")
    builder.add_edge("persist_daily", "set_tomorrow")
    builder.add_edge("set_tomorrow", END)

    # 失眠线
    builder.add_edge("insomnia_think", "persist_insomnia")
    builder.add_edge("persist_insomnia", "retry_sleep")
    builder.add_edge("retry_sleep", END)

    return builder.compile()
