"""
ws_handler.py —— WebSocket 消息处理、Agent 调用、闹钟管理、回复发送

chat_ws 太长了，按职责拆到这里。
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from agent_hina import prompts

TIMELINE_FILE = Path(__file__).resolve().parent.parent / "data" / "time-line.md"

# time-line.md 跨协程/线程读写的互斥锁（全局闹钟循环 + graph 节点可能并发写）
_timeline_lock = threading.Lock()


# ═══════════════════════════════════════════════════
# 1. 消息解析
# ═══════════════════════════════════════════════════

def parse_user_message(payload: str) -> dict:
    """解析用户消息 JSON → {mode, user_text, chatting_code}"""
    try:
        msg = json.loads(payload)
        raw_text = msg.get("text", payload)
        mode = int(raw_text[0]) if raw_text else 1
        user_text = raw_text[1:]
        if mode == 0:
            prompts.SYSTEM_PROMPT = prompts.HINA_IM_PROMPT
            chatting_code = 0
        else:
            prompts.SYSTEM_PROMPT = prompts.HINA_SYSTEM_PROMPT
            chatting_code = 1
    except (json.JSONDecodeError, ValueError, IndexError):
        user_text = payload
        prompts.SYSTEM_PROMPT = prompts.HINA_SYSTEM_PROMPT
        chatting_code = 1
    return {"user_text": user_text, "chatting_code": chatting_code}


# ═══════════════════════════════════════════════════
# 2. state_input 构造
# ═══════════════════════════════════════════════════

def build_state_input(msg_type: str, payload: str, user_text: str = "") -> dict:
    """根据消息类型构建 agent state 入参"""
    if msg_type == "user":
        # parse_user_message 已经设好了 SYSTEM_PROMPT，这里不覆盖
        return {"messages": [HumanMessage(content=user_text)]}

    prompts.SYSTEM_PROMPT = prompts.HINA_SYSTEM_PROMPT
    if msg_type == "state":
        return {
            "messages": [SystemMessage(content=f"[系统状态切换] {payload}")],
            "alarm_type": "状态",
            "trigger_reason": payload,
        }
    elif msg_type == "active":
        return {
            "messages": [SystemMessage(content=f"[系统主动触发] {payload}")],
            "alarm_type": "主动",
            "trigger_reason": payload,
        }
    return {}


# ═══════════════════════════════════════════════════
# 3. Agent 结果提取
# ═══════════════════════════════════════════════════

def extract_agent_reply(result: dict) -> dict:
    """从 agent 返回的 state 里取回复文字、心情、状态"""
    from langchain_core.messages import AIMessage
    messages = result.get("messages", [])
    reply_text = ""
    # 从后往前找第一个 AIMessage 有文字内容的（tool_call 可能 content 为空）
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            reply_text = msg.content
            break

    # 兜底：主动闹钟无文字时用 trigger_reason（去掉 0/1 前缀）
    if not reply_text and result.get("alarm_type") == "主动":
        reason = result.get("trigger_reason", "")
        if reason and reason[0] in "01":
            reason = reason[1:]
        if reason:
            reply_text = reason

    return {
        "reply_text": reply_text,
        "mood": result.get("mood", "") or "普通",
        "status": result.get("status", "") or "在线",
    }


def parse_wakeup(result: dict) -> tuple[datetime | None, str]:
    """取 next_wakeup_at，字符串自动转 datetime；返回 (datetime|None, reason)"""
    wakeup = result.get("next_wakeup_at")
    if isinstance(wakeup, str) and wakeup.strip():
        try:
            wakeup = datetime.strptime(wakeup.strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            wakeup = None
    if wakeup is not None and isinstance(wakeup, datetime) and wakeup > datetime.now():
        return wakeup, result.get("trigger_reason", "")
    return None, ""


# ═══════════════════════════════════════════════════
# 4. 闹钟工具
# ═══════════════════════════════════════════════════

def read_alarms_by_type(content: str, alarm_type: str) -> list[tuple[datetime, str]]:
    """从时间轴内容中筛出指定类型的闹钟，返回 [(时间, 原因), ...]"""
    from agent_hina.nodes.schedule import analysis
    alarms_map = analysis(content)
    return [(t, reason) for t, (typ, reason) in alarms_map.items() if typ == alarm_type]


def remove_alarm(target_time: datetime) -> None:
    """从时间轴文件中移除匹配时间的闹钟行（精确匹配整行，避免前缀误删）"""
    if not TIMELINE_FILE.exists():
        return
    time_str = target_time.strftime("%Y-%m-%d %H:%M")
    with _timeline_lock:
        content = TIMELINE_FILE.read_text(encoding="utf-8")
        new_lines = [
            line for line in content.splitlines()
            if not line.strip().startswith(time_str + " |")
        ]
        if len(new_lines) == len(content.splitlines()):
            return
        TIMELINE_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _write_timeline(lines: list[str]) -> None:
    """覆盖写入 timeline 文件"""
    TIMELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMELINE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resume_next_alarm(msg_type: str) -> tuple[datetime | None, str]:
    """
    当前闹钟处理完后，从 timeline 找下一个同类型闹钟。
    顺便清理过期闹钟。返回 (next_time, reason)。
    """
    if not TIMELINE_FILE.exists():
        return None, ""

    now = datetime.now()
    content = TIMELINE_FILE.read_text(encoding="utf-8")
    lines = content.splitlines()
    valid_lines: list[str] = []
    cleaned = 0

    for line in lines:
        s = line.strip()
        if s.startswith("#") or s.startswith(">") or not s:
            valid_lines.append(line)
            continue
        parts = s.split("|", maxsplit=2)
        if len(parts) < 2:
            valid_lines.append(line)
            continue
        try:
            t = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M")
            if t <= now:
                cleaned += 1
                continue
        except ValueError:
            pass
        valid_lines.append(line)

    if cleaned > 0:
        _write_timeline(valid_lines)
        print(f"  [ws] 清理了 {cleaned} 条过期闹钟")

    alarm_type = "主动" if msg_type == "active" else "状态"
    alarms = read_alarms_by_type("\n".join(valid_lines), alarm_type)
    if alarms:
        next_t, next_reason = alarms[0]
        if next_t > now:
            print(f"  [ws] 续上下一个{alarm_type}闹钟: {next_reason} @ {next_t}")
            return next_t, next_reason
    return None, ""


# ═══════════════════════════════════════════════════
# 5. 消息持久化
# ═══════════════════════════════════════════════════

async def save_user_message(chatting_code: int, user_text: str):
    """用户消息写入对应数据库（IM→ImRecords, 现实→Chat）"""
    from sqlalchemy.orm import sessionmaker
    from server.database import engine
    from server.services.ChattingRecordsService import ChatService
    from server.services.ImRecordsService import ImRecordsService
    import asyncio as _asyncio

    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _save():
        db = SessionLocal()
        try:
            if chatting_code == 0:
                ImRecordsService(db).send(1, user_text)
            else:
                ChatService(db).send_message(1, user_text)
        finally:
            db.close()
    await _asyncio.to_thread(_save)


# ═══════════════════════════════════════════════════
# 6. 回复发送 & 推送
# ═══════════════════════════════════════════════════

async def send_reply(
    reply_text: str,
    mood: str,
    status: str,
    chatting_code: int,
    msg_type: str,
    websocket,
):
    """存 DB + 推 WebSocket + 主动消息走极光推送"""
    from sqlalchemy.orm import sessionmaker
    from server.database import engine
    from server.services.ChattingRecordsService import ChatService
    from server.services.ImRecordsService import ImRecordsService
    import asyncio as _asyncio

    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    # 存 DB
    def _save():
        db = SessionLocal()
        try:
            if chatting_code == 0:
                ImRecordsService(db).send(0, reply_text)
            else:
                ChatService(db).send_message(0, reply_text)
        finally:
            db.close()
    await _asyncio.to_thread(_save)

    # 推 WebSocket
    resp = json.dumps({
        "text": str(chatting_code) + reply_text,
        "mood": mood,
        "status": status,
    }, ensure_ascii=False)
    await websocket.send_text(resp)

    # 主动触发 → 极光推送
    if msg_type in ("active", "state") and reply_text:
        try:
            from agent_hina.jpush import send_message_push
            _asyncio.create_task(send_message_push(reply_text[:500]))
            print("  [ws] 已触发主动消息推送")
        except Exception as e:
            print(f"  [ws] 推送触发失败: {e}")
