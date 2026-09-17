# ============================================================
# scheduler.py —— 分层记忆压缩调度（纯函数，零 IO / 零 LLM）
#
#   层级与触发（2026-09-17 与用户对齐的方案）：
#     L0 原文条目（只追加）
#     L1 摘要层：累计 2 / 6 / 14 / 30 / 62 条时各推 1 条（块大小 2,4,8,16,32）
#     L2 深层摘要层：L1 到顶（62）后每 +32 条推 1 条
#     L3 画像：L2 接收满 4 次生成/刷新（生成时消费 L2 条目）
#   近期保护窗：最近 raw_window 条原文不参与压缩（模型干活要逐字细节）。
#
#   本模块只回答一个问题：给定当前计数，现在该做什么动作。
#   动作的执行（调 LLM 摘要、写库）在 engine.py。
# ============================================================

from dataclasses import dataclass, field

# L1 推送的累计触发点（原文条数）：块大小 2,4,8,16,32 的累加
L1_CHUNK_CUMULATIVE = (2, 6, 14, 30, 62)
# L1 到顶后，L2 的推送间隔（原文条数）
POST_CAP_INTERVAL = 32
# L2 接收满几次生成/刷新画像
PORTRAIT_EVERY = 4
# 近期保护窗：最近 N 条原文不参与压缩
RAW_WINDOW = 8

ACTION_L1 = "l1_consolidate"
ACTION_L2 = "l2_push"
ACTION_PORTRAIT = "portrait"
ACTION_DEFERRED = "deferred_window"


@dataclass
class MemoryCounters:
    """调度所需的全部状态（可从存储层重建，便于崩溃恢复）。"""
    total_entries: int = 0          # L0 原文总条数（含已压缩的）
    consumed: int = 0               # 已被压缩消费的原文条数
    l1_pushed: int = 0              # L1 已接收的推送次数
    l2_pushed: int = 0              # L2 已接收的推送次数
    l2_pending: list[str] = field(default_factory=list)  # L2 未消费条目（文本）


def plan_actions(c: MemoryCounters) -> list[str]:
    """返回当前应执行的动作序列（可能为空；调用方按顺序执行后更新计数再问）。"""
    actions: list[str] = []
    available = c.total_entries - c.consumed - RAW_WINDOW  # 窗口外的可压缩条数

    # 1) L1：还有触发档位未消费，且可压缩量足够覆盖当前块
    if c.l1_pushed < len(L1_CHUNK_CUMULATIVE):
        prev = L1_CHUNK_CUMULATIVE[c.l1_pushed - 1] if c.l1_pushed > 0 else 0
        chunk = L1_CHUNK_CUMULATIVE[c.l1_pushed] - prev
        if available >= chunk:
            actions.append(ACTION_L1)
        elif c.total_entries > c.consumed:
            actions.append(ACTION_DEFERRED)

    # 2) L1 到顶后：每满 POST_CAP_INTERVAL 条推 1 条进 L2
    #    ★ 纯函数铁律：计划阶段不修改计数器（此前 while 内自增导致计划数与执行数错位，
    #      画像的 pending 永远凑不满 4 —— s 系列同款"计划/执行错位"病）
    if c.l1_pushed >= len(L1_CHUNK_CUMULATIVE):
        since_cap = c.total_entries - L1_CHUNK_CUMULATIVE[-1]
        expected_l2 = max(0, (since_cap - RAW_WINDOW) // POST_CAP_INTERVAL)
        needed = max(0, expected_l2 - c.l2_pushed)
        actions.extend([ACTION_L2] * needed)

    # 3) 画像：L2 未消费条目攒够 PORTRAIT_EVERY 次
    if len(c.l2_pending) >= PORTRAIT_EVERY:
        actions.append(ACTION_PORTRAIT)

    return actions
