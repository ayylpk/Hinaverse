"""
write_daily 节点 —— 睡前写日记

触发: daily_compress 子图 START 之后第一个节点
存储: 文件 + Chroma + SQLite 三存储
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from langchain_core.messages import SystemMessage, HumanMessage

from agent_hina.state import AgentState
from agent_hina.models import write_model
from agent_hina.memory_store import get_collection
from agent_hina.prompts import build_write_daily_prompt
from agent_hina.jpush import send_diary_push

DAILY_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "daily"
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sqlite"
YEAR_OFFSET = datetime.now().year - 2026


async def write_daily_node(state: AgentState) -> dict:
    """日奈写今天的日记 → 文件 + Chroma + SQLite 三存储"""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")

    # 取今天的记忆
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
        memory_text = "暂无记录"

    # ── 读取关系档案 & 待办约定，丰富日记上下文 ──
    relationship_context = ""
    pending_agreements = ""
    rel_file = Path(__file__).resolve().parent.parent.parent / "data" / "relationship-with-user.md"
    pending_file = Path(__file__).resolve().parent.parent.parent / "data" / "pending-agreements.md"
    if rel_file.exists():
        relationship_context = rel_file.read_text(encoding="utf-8")[:1500]
    if pending_file.exists():
        pending_agreements = pending_file.read_text(encoding="utf-8")[:1000]

    # LLM 写日记
    prompt = build_write_daily_prompt(
        date_str, memory_text, relationship_context, pending_agreements
    )
    system = SystemMessage(content=f"当前时间: {now.strftime('%Y年%m月%d日 %H:%M')}")

    try:
        response = write_model.invoke([system, HumanMessage(content=prompt)])
        diary = response.content.strip()  # type: ignore
        print(f"  [daily:write] 日记完成 ({len(diary)} 字)")
    except Exception as e:
        print(f"  [daily:write] LLM 失败: {e}")
        diary = f"今天没什么特别的\n{date_str}\n\n今天太累了，没写成日记。"

    # ── 解析标题：取第一非空行作为标题，其余为正文 ──
    lines = diary.split("\n")
    title = date_str  # 兜底
    content_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            title = stripped
            content_start = i + 1
            break
    content = "\n".join(lines[content_start:]).strip() if content_start < len(lines) else ""
    if not content:
        content = diary  # 如果正文为空（只有标题），整篇当正文
    print(f"  [daily:write] 标题: {title}")

    # ── 存储 1: 文件 ──
    month_dir = DAILY_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    filepath = month_dir / f"{now.strftime('%d')}.txt"
    filepath.write_text(diary, encoding="utf-8")
    print(f"  [daily:write] 文件: {filepath}")

    # ── 存储 2: Chroma ──
    try:
        collection = get_collection()
        collection.add(
            ids=[f"diary-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4]}"],
            documents=[diary],
            metadatas=[{
                "timestamp": now.isoformat(),
                "memory_type": "diary",
                "date": date_str,
            }],
        )
        print("  [daily:write] Chroma: OK")
    except Exception as e:
        print(f"  [daily:write] Chroma: {e}")

    # ── 存储 3: SQLite ──
    try:
        db_file = DB_PATH / f"hina{YEAR_OFFSET}.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS diaryOfHina ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  title TEXT NOT NULL,"
            "  content TEXT NOT NULL,"
            "  time INTEGER NOT NULL,"
            "  imagePath TEXT NOT NULL DEFAULT ''"
            ")"
        )
        conn.execute(
            "INSERT INTO diaryOfHina (title, content, time, imagePath) VALUES (?, ?, ?, ?)",
            (title, content, int(now.timestamp() * 1000), ""),
        )
        conn.commit()
        conn.close()
        print("  [daily:write] SQLite: OK")
    except Exception as e:
        print(f"  [daily:write] SQLite: {e}")

    # ── 极光推送：通知 Android 端有新日记（reg_id 由调用方按用户传入，多用户接入前暂为空跳过）──
    try:
        await send_diary_push(title, content[:200], reg_id="")
        print("  [daily:write] 推送成功")
    except Exception as e:
        print(f"  [daily:write] 推送失败: {e}")

    return {}
