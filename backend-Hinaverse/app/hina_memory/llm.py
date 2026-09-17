# ============================================================
# llm.py —— 记忆压缩用的两个 LLM 出口（摘要 / 画像）
#
#   一律复用 agent 层的模型封装（agent_hina.models 是唯一的 LLM 入口，
#   不在这里另发 HTTP）。backend 通过 import agent_hina.* 共用同一套配置。
#
#   Summarizer：一批原文 → 一条摘要（L1）
#   PortraitMaker：(L2 未消费条目, 旧画像) → 新画像（整体改写，不是追加）
#
#   画像有**硬上限**（PORTRAIT_MAX_CHARS，默认 300 字）：它每轮回复都要塞进
#   系统提示词，越长越贵也越糊。超限先让模型压一次，仍超限按段落机械裁剪。
# ============================================================

import logging
import sys
from pathlib import Path
from typing import Sequence

from .scheduler import PORTRAIT_MAX_CHARS

logger = logging.getLogger(__name__)


def _agent_models():
    """拿 agent 层的模型实例；sys.path 未注入时自行注入（与 agent_service 同款兜底）。"""
    try:
        from agent_hina import models
    except ImportError:
        agent_dir = Path(__file__).resolve().parents[3] / "agent-Hinaverse"
        if str(agent_dir) not in sys.path:
            sys.path.insert(0, str(agent_dir))
        from agent_hina import models
    return models


def _invoke(model, prompt: str) -> str:
    out = model.invoke(prompt)
    return str(getattr(out, "content", out)).strip()


_SUMMARY_PROMPT = """你是陪伴产品「日奈」的记忆整理员。把下面这段对话压成**一条**记忆摘要。

【要保留】
- 发生了什么（人物、事件、时间线索）
- 用户的情绪与状态
- 没做完 / 答应过 / 说好要再提的事（这些最重要，别丢）

【规矩】
- 100~200 字，一段话，不要小标题、不要 JSON、不要 markdown
- 只写对话里出现过的事，**不许脑补**；区分清楚谁说的
- 用第三人称转述："用户提到……""日奈建议……"

【对话】
{chunk}

【输出】直接输出摘要正文，不要任何前缀。"""

# 画像骨架：四段固定不变，段内 1~2 句，全文 ≤ {limit} 字。结构稳定才好被反复改写、也才好塞进提示词。
_PORTRAIT_PROMPT = """你是陪伴产品「日奈」的画像维护员。根据新的记忆摘要，**整体改写**这位用户的画像。

【已有的画像】
{old}

【新的记忆摘要】
{pending}

【输出结构】严格用这四段，标题照抄、段序不变、每段 1~2 句话：
### 身份与生活
（身份、生活节奏、在意的人或事；无依据就写"暂无信息"）
### 性格与偏好
（怎么说话、在意什么、对什么敏感）
### 近期状态
（最近在经历什么、情绪走向、进展或反复）
### 陪伴要点
（跟他/她说话要注意什么、有什么没兑现的约定）

【硬规矩】
- 全文 ≤ {limit} 字（含标题）。宁短不长，写不下就砍细节，不许写满
- 每段一句话为主，最多两句；不要展开叙述、不要举例堆叠
- 这是**改写**：新信息并进去、被推翻的旧结论去掉，不是流水账追加
- 只写有依据的内容，不确定的宁可不写；不写建议、不做心理诊断
- 不要写"用户提到/日奈建议"这类记录腔，直接陈述

【输出】只输出画像正文（四段），不要任何额外说明。"""

# 超限时的二次压缩（极少触发，属于兜底）
_SHRINK_PROMPT = """把下面的用户画像压缩到 {limit} 字以内，保持这四段结构、标题不变：

{text}

要求：只删减、不新增内容，保留最具体的细节（身份、在意的事、近期状态、陪伴要点）；
每段压成一句话。直接输出压缩后的画像正文。"""


def summarize(entries: Sequence[str]) -> str:
    """一批原文条目 → 一条摘要。LLM 失败时退化为机械截断，保证压缩不吞数据。"""
    chunk = "\n".join(entries)
    try:
        text = _invoke(_agent_models().reduce_model, _SUMMARY_PROMPT.format(chunk=chunk))
        if text:
            return text
        logger.warning("[hina_memory] 摘要返回空，走机械兜底")
    except Exception as e:
        logger.warning(f"[hina_memory] 摘要 LLM 失败，走机械兜底：{e}")
    return chunk[:200]


def make_portrait(pending: Sequence[str], old: str | None) -> str:
    """L2 未消费条目 + 旧画像 → 新画像（整体改写，受字数硬上限约束）。"""
    summaries = "\n\n".join(f"- {s}" for s in pending)
    prompt = _PORTRAIT_PROMPT.format(
        old=old or "（还没有画像，这是第一版）", pending=summaries, limit=PORTRAIT_MAX_CHARS
    )
    try:
        text = _invoke(_agent_models().write_model, prompt)
        if text:
            return _enforce_limit(text, old)
        logger.warning("[hina_memory] 画像返回空，保留旧画像")
    except Exception as e:
        logger.warning(f"[hina_memory] 画像 LLM 失败，保留旧画像：{e}")
    if old:
        return old
    return "### 近期状态\n" + "\n".join(f"- {s}" for s in pending)


def _enforce_limit(text: str, old: str | None) -> str:
    """画像超限：先让模型压一次；仍超限就按段落机械裁剪（保完整段落，不切半句）。"""
    if len(text) <= PORTRAIT_MAX_CHARS:
        return text

    logger.info(f"[hina_memory] 画像 {len(text)} 字 > 上限 {PORTRAIT_MAX_CHARS}，要求压缩")
    try:
        shrunk = _invoke(
            _agent_models().reduce_model,
            _SHRINK_PROMPT.format(text=text, limit=PORTRAIT_MAX_CHARS),
        )
        if shrunk and len(shrunk) <= PORTRAIT_MAX_CHARS:
            return shrunk
        if shrunk:
            text = shrunk  # 压过一轮但还是长 → 走到下面的机械裁剪
    except Exception as e:
        logger.warning(f"[hina_memory] 画像压缩调用失败，直接机械裁剪：{e}")

    return _trim_sections(text)


def _trim_sections(text: str, limit: int | None = None) -> str:
    """按段落边界裁剪（宁可少一段，也不要在句子中间断掉）。"""
    limit = limit or PORTRAIT_MAX_CHARS
    lines = text.splitlines()
    kept: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + 1
        if kept and used + cost > limit:
            break
        kept.append(line)
        used += cost
    trimmed = "\n".join(kept).strip()
    # 极端情况：连第一段都超限 → 硬截断兜底
    return trimmed if trimmed else text[:limit]
