# ============================================================
# service.py —— hina_memory 对外唯一入口（backend 只 import 这里）
#
#   职责边界：
#     · 本模块管「什么时候写、写完存哪」；压缩与画像的文本生成在 llm.py；
#       触发时机判定在 scheduler.py；动作执行在 engine.py。
#     · 记忆写库是**后台异步**（fire-and-forget，跟回复同一个「先回后存」原则）：
#       绝大多数轮次只插一行；命中触发档位时才在后台线程里跑 LLM 压缩。
#     · 一个进程内用一把锁串行化写入，保证 user/ai 两条原文的顺序不被线程打乱。
# ============================================================

import logging
import threading
import time
from typing import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine import MemoryEngine
from .llm import make_portrait as _llm_make_portrait
from .llm import summarize as _llm_summarize
from .models import HinaMemoryPortrait
from .mysql_store import SqlMemoryStore
from .scheduler import L1_CHUNK_CUMULATIVE, PORTRAIT_EVERY, PORTRAIT_MAX_CHARS, RAW_WINDOW

logger = logging.getLogger(__name__)

# 写入串行化：并发线程下保证 L0 顺序（顺序错了摘要和画像都会歪）
_WRITE_LOCK = threading.Lock()

Summarizer = Callable[[Sequence[str]], str]
PortraitMaker = Callable[[Sequence[str], str | None], str]


def _session() -> Session:
    """延迟导入，避免 app.database 在模块导入期建连接（也让单测能换库）。"""
    from app.database import SessionLocal
    return SessionLocal()


def remember(
    db: Session,
    user_id: int,
    role: str,
    content: str,
    *,
    summarize: Summarizer | None = None,
    make_portrait: PortraitMaker | None = None,
) -> list[str]:
    """记一条原文，顺带执行被触发的压缩动作，返回动作列表（正常轮次是空列表）。"""
    store = SqlMemoryStore(db, user_id).speaker(role)
    engine = MemoryEngine(
        store=store,
        summarize=summarize or _llm_summarize,
        make_portrait=make_portrait or _llm_make_portrait,
        counters=store.load_counters(),
        on_event=_on_event,
    )
    actions = engine.add_entry(content)
    store.save_counters(engine.counters)
    db.commit()
    return actions


def _on_event(action: str, _detail: dict) -> None:
    logger.info(
        f"[hina_memory] 压缩动作：{action}"
        f"（L1 触发点 {L1_CHUNK_CUMULATIVE}，保护窗 {RAW_WINDOW} 条，"
        f"画像每 {PORTRAIT_EVERY} 次 L2 刷新、≤{PORTRAIT_MAX_CHARS} 字）"
    )


def remember_async(user_id: int, role: str, content: str) -> None:
    """后台写一条（fire-and-forget）：不阻塞日奈回复，失败只记日志。"""
    if not content:
        return

    def _job() -> None:
        with _WRITE_LOCK:
            db = _session()
            try:
                actions = remember(db, user_id, role, content)
                if actions:
                    logger.info(f"[hina_memory] user={user_id} 本轮触发压缩：{actions}")
            except Exception as e:  # 记忆坏了不许影响主链路
                db.rollback()
                logger.warning(f"[hina_memory] 写入失败 user={user_id}: {e}")
            finally:
                db.close()

    threading.Thread(target=_job, name=f"hina-mem-{user_id}", daemon=True).start()


# ── 画像读取（供生成回复 / 日终总结 / 运营台抽屉）──
#    画像按天级变化，但每轮回复都查一次库没必要；加 TTL 内存缓存，
#    与原先 AgentMemory 客户端的缓存策略一致（失败时保留旧值，绝不抛）。
_PORTRAIT_CACHE: dict[int, tuple[str | None, float]] = {}
_PORTRAIT_TTL = 5 * 60


def portrait_of(user_id: int) -> str | None:
    """查画像（直读库，无缓存）。"""
    db = _session()
    try:
        return db.execute(
            select(HinaMemoryPortrait.text).where(HinaMemoryPortrait.user_id == user_id)
        ).scalar_one_or_none()
    except Exception as e:
        logger.warning(f"[hina_memory] 读取画像失败 user={user_id}: {e}")
        return None
    finally:
        db.close()


def portrait_cached(user_id: int) -> str | None:
    """带 TTL 缓存的画像查询（回复链路用；失败保留旧值）。"""
    cached = _PORTRAIT_CACHE.get(user_id)
    now = time.monotonic()
    if cached and now - cached[1] < _PORTRAIT_TTL:
        return cached[0]

    fresh = portrait_of(user_id)
    if fresh:
        _PORTRAIT_CACHE[user_id] = (fresh, now)
        return fresh
    if cached:
        return cached[0]
    return None


def invalidate_portrait_cache(user_id: int) -> None:
    _PORTRAIT_CACHE.pop(user_id, None)
