# ============================================================
# store.py —— 记忆存储：内存实现（测试）+ SQLite 实现（本地/轻量部署）
# 生产 MySQL 由 Hinaverse 侧按同一 MemoryStore 协议接入。
# ============================================================

import sqlite3
from dataclasses import dataclass, field


@dataclass
class InMemoryStore:
    raw: list[str] = field(default_factory=list)            # 全部原文（含已压缩，留档）
    consumed_count: int = 0                                  # 已压缩条数
    l1: list[str] = field(default_factory=list)
    l2: list[str] = field(default_factory=list)
    portrait_text: str | None = None

    def append_raw(self, content: str) -> int:
        self.raw.append(content)
        return len(self.raw)

    def mark_consumed(self, count: int) -> None:
        self.consumed_count += count

    def take_unconsumed(self, count: int) -> list[str]:
        take = self.raw[self.consumed_count:self.consumed_count + count]
        return list(take)

    def append_l1(self, summary: str) -> None:
        self.l1.append(summary)

    def append_l2(self, summary: str) -> None:
        self.l2.append(summary)

    def l2_pending(self) -> list[str]:
        return list(self.l2)

    def clear_l2(self) -> None:
        self.l2 = []

    def get_portrait(self) -> str | None:
        return self.portrait_text

    def set_portrait(self, text: str) -> None:
        self.portrait_text = text


class SqliteStore:
    """SQLite 落盘实现（单文件即可用；表结构自动创建）。"""

    def __init__(self, db_path: str = "hina_memory.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS hm_raw (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, consumed INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS hm_l1 (seq INTEGER PRIMARY KEY AUTOINCREMENT, summary TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS hm_l2 (seq INTEGER PRIMARY KEY AUTOINCREMENT, summary TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS hm_portrait (id INTEGER PRIMARY KEY CHECK (id = 1), text TEXT);
            """
        )
        self.conn.commit()

    def append_raw(self, content: str) -> int:
        cur = self.conn.execute("INSERT INTO hm_raw(content) VALUES (?)", (content,))
        self.conn.commit()
        return cur.lastrowid

    def mark_consumed(self, count: int) -> None:
        self.conn.execute(
            "UPDATE hm_raw SET consumed = 1 WHERE seq IN "
            "(SELECT seq FROM hm_raw WHERE consumed = 0 ORDER BY seq LIMIT ?)", (count,))
        self.conn.commit()

    def take_unconsumed(self, count: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT content FROM hm_raw WHERE consumed = 0 ORDER BY seq LIMIT ?", (count,)).fetchall()
        return [r[0] for r in rows]

    def append_l1(self, summary: str) -> None:
        self.conn.execute("INSERT INTO hm_l1(summary) VALUES (?)", (summary,))
        self.conn.commit()

    def append_l2(self, summary: str) -> None:
        self.conn.execute("INSERT INTO hm_l2(summary) VALUES (?)", (summary,))
        self.conn.commit()

    def l2_pending(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT summary FROM hm_l2 ORDER BY seq").fetchall()]

    def clear_l2(self) -> None:
        self.conn.execute("DELETE FROM hm_l2")
        self.conn.commit()

    def get_portrait(self) -> str | None:
        row = self.conn.execute("SELECT text FROM hm_portrait WHERE id = 1").fetchone()
        return row[0] if row else None

    def set_portrait(self, text: str) -> None:
        self.conn.execute(
            "INSERT INTO hm_portrait(id, text) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET text = excluded.text", (text,))
        self.conn.commit()
