"""
schedule 节点 —— 对话结束后读取时间轴，取最近一个 [主动] 闹钟
[状态] 闹钟由 agent_graph 的定时器线程独立处理，不走这里
"""
from datetime import datetime
from pathlib import Path

from agent_hina.state import AgentState

TIMELINE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "time-line.md"


def analysis(contents: str) -> dict[datetime, tuple[str, str]]:
    """解析时间轴，返回 {时间: (类型, 事件)} 字典，按时间升序"""
    result: dict[datetime, tuple[str, str]] = {}

    for line in contents.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue

        parts = text.split("|", maxsplit=2)
        if len(parts) < 3:
            continue

        time_str = parts[0].strip()
        alarm_type = parts[1].strip()
        event_str = parts[2].strip()

        try:
            target_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        except ValueError:
            continue

        result[target_time] = (alarm_type, event_str)

    return dict(sorted(result.items()))


def schedule_node(state: AgentState) -> dict:
    """
    读时间轴 → 取最早的 [主动] 闹钟 → next_wakeup_at + trigger_reason
    [状态] 类闹钟不在这里返回——定时器线程自己处理
    """
    if not TIMELINE_FILE.exists():
        return {"next_wakeup_at": None, "trigger_reason": "", "alarm_type": ""}

    contents = TIMELINE_FILE.read_text(encoding="utf-8")
    alarms = analysis(contents)

    # 筛出 [主动] 闹钟，取最早
    active_alarms = [
        (t, r) for t, (typ, r) in alarms.items() if typ == "主动"
    ]
    if not active_alarms:
        return {"next_wakeup_at": None, "trigger_reason": "", "alarm_type": ""}

    target_time, reason = active_alarms[0]

    return {
        "next_wakeup_at": target_time,
        "trigger_reason": reason,
        "alarm_type": "主动",
    }
