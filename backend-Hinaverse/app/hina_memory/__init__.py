# ============================================================
# hina_memory —— Hinaverse 内建的分层记忆（L0 原文 → L1 摘要 → L2 深层摘要 → L3 画像）
#
#   纯逻辑：scheduler / engine / store(内存·SQLite)
#   落地件：models(表) / mysql_store(库实现) / llm(摘要·画像) / service(对外入口)
#
#   ⚠️ backend 业务代码只 import 本模块的 service（remember_async / portrait_cached），
#      不要直接碰 engine 与 scheduler。
# ============================================================

from .engine import MemoryEngine
from .scheduler import (
    L1_CHUNK_CUMULATIVE, PORTRAIT_EVERY, PORTRAIT_MAX_CHARS, POST_CAP_INTERVAL, RAW_WINDOW,
    MemoryCounters, plan_actions,
)
from .store import InMemoryStore, SqliteStore

__all__ = [
    "MemoryEngine", "MemoryCounters", "plan_actions",
    "L1_CHUNK_CUMULATIVE", "POST_CAP_INTERVAL", "PORTRAIT_EVERY", "RAW_WINDOW",
    "PORTRAIT_MAX_CHARS",
    "InMemoryStore", "SqliteStore",
]
