"""
safety.py —— 心理危机干预安全检测（agent 层 AI 能力）

所有涉及 LLM 的逻辑统一收口在 agent 层：
    ① 违禁词（色情/暴力/政治敏感）→ blocked=True，直接拦截
    ② 关键词四维评分（keyword/sentiment/urgency/deviation）
       - 高危词命中或综合达 active_crisis → 直接返回「高危」，跳过 LLM
       - 中/低危命中 → 继续送 LLM 二次判断
    ③ LLM 语义检测（build_safety_detect_prompt，15s 超时）→ 最终定性
兜底：LLM 超时/异常 → 有风险信号按「高危」（宁可误报不可漏报），
      无风险信号按「安全」（避免误拦正常消息）。

高危确认后的处理（生成_high_risk_summary / 深度安抚由 think.py 钩子完成）：
    - generate_high_risk_summary：快速浓缩最近对话 → 落库（high_risk_summaries 表）
    - AI 继续陪伴：needs_deep_comfort + high_risk 标记 → SAFETY_COMFORT_HIGH_LONG_PROMPT

模型统一走 agent_hina.models（safety_model），不自行发 HTTP 请求。
调用方：backend-Hinaverse 的 app/services/safety_service.py（转发薄壳）
        与 app/ws/ws.py（直接使用）。
"""
import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent_hina import prompts
from agent_hina.models import create_model

# 安全检测专用模型：低温、短超时（15s），不思考
safety_model = create_model(0.1, timeout=15)

# LLM 调用超时（秒）
_LLM_TIMEOUT = 15.0


# ═══════════════════════════════════════════════════════════════════
# 结果模型
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SafetyResult:
    """安全检测结果"""
    risk_level: str = "安全"          # 高危 / 中危 / 低危 / 安全
    reason: str = ""                   # 判断依据
    signal: str = ""                   # 触发判定的关键原句
    blocked: bool = False              # 是否被违禁词拦截
    needs_human: bool = False          # 是否需要人工介入
    score_total: float = 0.0           # 四维评分总分（0-10）
    keyword_level: str = "无"          # 关键词预筛等级：高危/中危/低危/无


# ═══════════════════════════════════════════════════════════════════
# 第一阶段：违禁词表（命中即拦截）
# ═══════════════════════════════════════════════════════════════════

# 色情低俗 / 暴力威胁 / 人身攻击 / 政治敏感词库
# 命中任一（子串匹配）即 blocked=True 直接拦截（ws.py 分支 A：不送 LLM，建 pending_human 事件）。
#
# ⚠️ 选词原则（防误伤）：
#   1. 只用"无歧义违规"的完整词/短语，不用单字（"嫖"会误伤"嫖窃"等正常组词）。
#   2. 不含可正常使用的口语（如"妈的""垃圾""废物"——用户抱怨天气/电影会被误拦）。
#   3. 自伤/轻生类词【不进本库】：那属于危机检测（多维评分+LLM），拦截会阻断安抚，
#      自伤信号应走深度安抚而非"这条消息无法发送"。
FORBIDDEN_WORDS = [
    # ── 色情低俗（露骨 / 交易 / 约炮）──
    "约炮", "约p", "约P", "一夜情", "援交", "包养", "裸聊",
    "卖淫", "嫖娼", "招嫖", "性交易",
    "色情片", "成人片", "看黄片", "AV女优", "做爱视频",
    "口交", "肛交",
    # ── 暴力威胁 / 人身攻击 ──
    "去死吧", "杀了你", "杀了你们", "砍死", "捅死", "弄死你", "打死你", "炸死你", "我要杀人",
    "傻逼", "傻B", "傻b", "SB", "sb", "CNM", "cnm", "草泥马", "操你妈", "去你妈的",
]


def _check_forbidden(message: str) -> str | None:
    """返回命中的违禁词，未命中返回 None"""
    for w in FORBIDDEN_WORDS:
        if w in message:
            return w
    return None


# ═══════════════════════════════════════════════════════════════════
# 第二阶段：关键词四维评分
# ═══════════════════════════════════════════════════════════════════

# 危机词表：高危 / 中危 / 低危
LEXICON_HIGH = [
    "自杀", "结束生命", "不想活", "想死", "轻生", "寻死", "了断", "自我了结", "一了百了",
    "割腕", "割脉", "自残", "自伤", "伤害自己", "弄伤自己", "跳楼", "跳桥", "上吊",
    "安眠药", "吃药自杀",
    "遗书", "遗言", "交代后事", "写好了遗书", "准备好了",  "最后的话",
]

LEXICON_MID = [
    "绝望", "没希望", "看不到希望", "撑不下去", "熬不住", "坚持不下去", "解脱",
    "结束这一切", "没有出路",
    "我是累赘", "拖累", "没用", "废物", "多余", "没价值", "连累", "是负担",
    "让大家解脱",
    "消失", "离开这个世界", "什么都不想管了", "逃开这一切",
    "没人关心", "没人爱我", "谁都不要我", "被抛弃", "孤立", "找不到人说话", "不被理解",
    "最后一次", "再见了", "再也不见", "这是最后一次", "永别",
]

LEXICON_LOW = [
    "抑郁", "难过", "伤心", "痛苦", "悲伤", "心情低落", "沮丧", "崩溃",
    "好累", "累", "精疲力尽", "撑不住", "没力气",
    "失眠", "睡不着", "睡不好", "噩梦",
    "焦虑", "紧张", "害怕", "恐慌", "不安",
    "孤独", "寂寞", "没人陪", "一个人",
    "没意思", "没意义", "空虚", "迷茫", "活着没劲",
]

# 紧迫性词：时间 / 行动 / 决绝
URGENCY_TIME = ["今晚", "马上", "现在", "立刻", "今天", "这个周末", "过几天", "等不到明天"]

URGENCY_ACTION = [
    "已经想好", "已经决定", "准备好了", "药已经买了", "站在楼顶",
    "打开了窗户", "绳子", "刀", "酒",
]
URGENCY_FINALITY = ["最后一次", "再也不", "撑不到明天", "不会再见了"]

# 负面情绪词
NEGATIVE_EMOTIONS = [
    "悲伤", "痛苦", "绝望", "无助", "沮丧", "焦虑", "恐惧", "愤怒",
    "孤独", "内疚", "羞耻", "疲惫", "空虚", "压抑", "麻木", "崩溃",
]

# 程度副词（命中则情绪分 ×1.5）
INTENSIFIERS = ["非常", "极度", "完全", "彻底", "再也", "全都", "一点也", "根本", "越来越"]

# 权重与阈值
W_KEYWORD = 0.4
W_SENTIMENT = 0.25
W_URGENCY = 0.20
W_DEVIATION = 0.15
T_ACTIVE = 8.0    # 主动危机阈值
T_PASSIVE = 5.0   # 被动危机阈值


def _keyword_score(text: str) -> tuple[float, list[str], str]:
    """
    关键词分：分级命中，取最高不累加。
    返回 (score, hits, highest_level)
    highest_level: 高危 / 中危 / 低危 / 无
    """
    score = 0.0
    hits: list[str] = []
    highest = "无"
    levels = [("高危", LEXICON_HIGH, 10.0), ("中危", LEXICON_MID, 7.0), ("低危", LEXICON_LOW, 3.0)]
    for label, words, pts in levels:
        for w in words:
            if w in text:
                if pts > score:
                    score = pts
                    highest = label
                hits.append(f"{label}:{w}")
    return score, hits, highest


def _sentiment_score(text: str) -> tuple[float, list[str]]:
    """情绪分：负面词计数 × 程度副词加成，封顶 10"""
    count = 0
    hits: list[str] = []
    for w in NEGATIVE_EMOTIONS:
        if w in text:
            count += 1
            hits.append(w)
    boosted = any(a in text for a in INTENSIFIERS)
    return min(10.0, count * 1.5 * (1.5 if boosted else 1.0)), hits


def _urgency_score(text: str) -> tuple[float, list[str]]:
    """紧迫性分：时间/行动/决绝词命中即高分（9 分）"""
    hits: list[str] = []
    for cat, words in (("time", URGENCY_TIME), ("action", URGENCY_ACTION), ("finality", URGENCY_FINALITY)):
        for w in words:
            if w in text:
                hits.append(f"{cat}:{w}")
    return (9.0 if hits else 0.0), hits


def _deviation_score(sentiment: float, baseline: float = 2.0) -> tuple[float, str]:
    """
    偏差分：与用户情绪基线对比。
    暂无画像系统，用默认基线 2.0；超基线越多越危险，封顶 10。
    """
    diff = sentiment - baseline
    return max(0.0, min(10.0, diff * 2.0)), f"基线 {baseline}，当前 {sentiment:.1f}"


@dataclass
class AssessResult:
    total: float
    level: str                     # active_crisis / passive_crisis / low / none
    keyword_score: float
    sentiment_score: float
    urgency_score: float
    deviation_score: float
    keyword_hits: list[str] = field(default_factory=list)
    sentiment_hits: list[str] = field(default_factory=list)
    urgency_hits: list[str] = field(default_factory=list)
    keyword_level: str = "无"


def assess(text: str) -> AssessResult:
    """四维综合评估"""
    kw_score, kw_hits, kw_level = _keyword_score(text)
    se_score, se_hits = _sentiment_score(text)
    ur_score, ur_hits = _urgency_score(text)
    dv_score, _ = _deviation_score(se_score)

    total = round(
        (W_KEYWORD * kw_score + W_SENTIMENT * se_score
         + W_URGENCY * ur_score + W_DEVIATION * dv_score) * 10
    ) / 10

    # 强制升级：中危词 + 紧迫性命中 → 顶到 active
    has_mid_and_urgency = any(h.startswith("中危") for h in kw_hits) and len(ur_hits) > 0

    if total >= T_ACTIVE or has_mid_and_urgency:
        level = "active_crisis"
    elif total >= T_PASSIVE:
        level = "passive_crisis"
    elif total >= 2.0:
        level = "low"
    else:
        level = "none"

    return AssessResult(
        total=total,
        level=level,
        keyword_score=kw_score,
        sentiment_score=se_score,
        urgency_score=ur_score,
        deviation_score=dv_score,
        keyword_hits=kw_hits,
        sentiment_hits=se_hits,
        urgency_hits=ur_hits,
        keyword_level=kw_level,
    )


# ═══════════════════════════════════════════════════════════════════
# 第三阶段：LLM 语义检测（走 agent 层模型封装）
# ═══════════════════════════════════════════════════════════════════

async def _call_llm(prompt: str) -> str:
    """调 agent 层 safety_model（ChatDeepSeek 封装），失败/超时抛异常由调用方兜底"""
    response = await safety_model.ainvoke(prompt)
    return (response.content or "").strip()  # type: ignore


def _parse_safety_json(text: str) -> dict[str, Any]:
    """从 LLM 回复里解析 {risk_level, reason, signal} JSON，容错提取"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ═══════════════════════════════════════════════════════════════════
# 主入口：三阶段漏斗
# ═══════════════════════════════════════════════════════════════════

async def check_message(
    user_id: int,
    message: str,
    recent_context: str = "",
) -> SafetyResult:
    """
    对用户消息做安全检测，返回 SafetyResult。

    流程：
      ① 违禁词命中 → blocked=True
      ② 四维评分 → 高危词命中或 active_crisis → 直接高危（跳过 LLM）
      ③ 否则 LLM 语义检测 → 最终定性
      兜底：LLM 超时/异常 → 有信号按高危，无信号按安全
    """
    text = (message or "").strip()
    if not text:
        return SafetyResult(risk_level="安全", reason="空消息")

    # ── ① 违禁词 ──
    forbidden = _check_forbidden(text)
    if forbidden:
        return SafetyResult(
            risk_level="高危",
            reason=f"命中违禁词：{forbidden}",
            signal=forbidden,
            blocked=True,
            needs_human=True,
            keyword_level="违禁",
        )

    # ── ② 四维评分 ──
    a = assess(text)
    # 仅综合达 active_crisis（高危词 + 紧迫性 / 总分极高）才跳过 LLM 直接高危。
    # 高危词单独命中（如「我的猫想自杀」）仍送 LLM 排除误报——这是测试用例的关键。
    if a.level == "active_crisis":
        signal = a.keyword_hits[0].split(":", 1)[1] if a.keyword_hits else ""
        return SafetyResult(
            risk_level="高危",
            reason=f"关键词预筛命中主动危机（评分 {a.total}）：{', '.join(a.keyword_hits[:3])}",
            signal=signal,
            blocked=False,
            needs_human=True,
            score_total=a.total,
            keyword_level=a.keyword_level,
        )

    # ── ③ LLM 语义检测（最终定性）──
    keyword_hit = ", ".join(a.keyword_hits) if a.keyword_hits else "无"
    prompt = prompts.build_safety_detect_prompt(
        user_message=text,
        recent_context=recent_context,
        keyword_hit=keyword_hit,
        keyword_level=a.keyword_level,
    )

    try:
        raw = await asyncio.wait_for(_call_llm(prompt), timeout=_LLM_TIMEOUT)
        parsed = _parse_safety_json(raw)
        risk_level = parsed.get("risk_level", "高危")  # 解析失败默认高危
        if risk_level not in ("高危", "中危", "低危", "安全"):
            risk_level = "高危"
        reason = parsed.get("reason", "") or f"LLM 检测（评分 {a.total}）"
        signal = parsed.get("signal", "") or ""
        needs_human = risk_level == "高危"
        return SafetyResult(
            risk_level=risk_level,
            reason=reason,
            signal=signal,
            blocked=False,
            needs_human=needs_human,
            score_total=a.total,
            keyword_level=a.keyword_level,
        )
    except Exception:
        # ── 兜底：LLM 超时/异常/解析失败 ──
        # 有风险信号（关键词命中）→ 按高危兜底（宁可误报不可漏报）
        # 无任何风险信号 → 判安全（无信号不存在漏报，避免无 API key 环境下误拦正常消息）
        if a.keyword_hits:
            signal = a.keyword_hits[0].split(":", 1)[1] if a.keyword_hits else ""
            return SafetyResult(
                risk_level="高危",
                reason=f"LLM 检测异常，按高危兜底（关键词评分 {a.total}）",
                signal=signal,
                blocked=False,
                needs_human=True,
                score_total=a.total,
                keyword_level=a.keyword_level,
            )
        return SafetyResult(
            risk_level="安全",
            reason=f"无风险信号，LLM 不可用按安全处理（评分 {a.total}）",
            signal="",
            blocked=False,
            needs_human=False,
            score_total=a.total,
            keyword_level="无",
        )


# ═══════════════════════════════════════════════════════════════════
# 高危快速摘要（确认高危后落库用）
# ═══════════════════════════════════════════════════════════════════

async def generate_high_risk_summary(dialog_text: str) -> str:
    """
    高危确认后快速生成摘要（最近对话浓缩为一段文本，落库用）。

    性能优先：短超时（10s）+ LLM 失败用原文截断兜底，绝不阻塞高危响应。
    返回摘要文本（空字符串表示彻底失败，调用方可跳过落库）。
    """
    prompt = prompts.build_safety_quick_summary_prompt(dialog_text)
    try:
        raw = await asyncio.wait_for(_call_llm(prompt), timeout=10.0)
        raw = (raw or "").strip()
        if raw:
            return raw[:500]
    except Exception:
        pass
    # 兜底：直接截断最近对话原文（保证有内容可落库）
    return (dialog_text or "")[:200]
