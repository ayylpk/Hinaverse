"""
active_message —— 主动关心消息服务（阶段 4：「存数据库 + 统一扫描触发」）

两端职责：
    生成侧 accept_spontaneous：spontaneous 节点产出的 {content, time} 在这里做
        **发送政策校验**（时间窗口/静默时段/长度，不信 LLM 自律），过检后落
        send_messages(pending)。落库前撤销旧 pending——双保险保证"每用户至多一条"。
    发送侧 scan_once + active_message_loop：每分钟扫一遍到点的 pending，
        过三道闸门后复用 dev/active 的三段式发出（落会话 + 未读 +1 + outbound push）。

三道闸门（顺序即优先级）：
    1. 过期作废：错过送达窗（顺延/服务停摆）超 GRACE → expired——迟到的关心是骚扰
    2. 静默时段：非 QUIET_START~QUIET_END 不发（顺延，下轮再试）
    3. 危机勿扰：用户有未关闭 crisis 事件 → 跳过（人工在陪，AI 别插话；
       一直开着的话该条最终被闸门 1 作废）

撤销链路在 ws.py：用户再说话 → send_message_repo.cancel_pending（人都来了，
不用发消息关心）→ 聊完这轮自然又生成新的。
"""
import asyncio
import logging
from datetime import datetime, timedelta

from app.database import SyncSessionLocal
from app.repositories import (
    conversation_repo,
    crisis_repo,
    message_repo,
    send_message_repo,
)

logger = logging.getLogger(__name__)

# ── 调参区 ──
SCAN_INTERVAL = 60          # 每 1 分钟扫一次（用户拍板）
MIN_DELAY_MIN = 30          # 送达时间距今至少 30 分钟（刚聊完就"主动关心"很怪）
MAX_HORIZON_HOURS = 48      # 最远 48 小时（隔夜以上的惦记已经凉了）
QUIET_START, QUIET_END = 7, 23   # 只在 07:00~22:59 送达，夜里不打扰
GRACE_HOURS = 2             # 到点后 2 小时内还发不出去（顺延/停摆）→ 作废
MAX_CONTENT_LEN = 500       # 正文长度上限（对齐极光推送截断，多余没意义）


# ═══════════════════════════════════════════════════════════════════
# 生成侧：校验 + 落库（agent_service 收尾流调用，同步毫秒级）
# ═══════════════════════════════════════════════════════════════════

def accept_spontaneous(user_id: int, payload: dict) -> int | None:
    """
    接收 spontaneous 产物 {"content": str, "time": "YYYY-MM-DD HH:MM"}。
    校验通过 → 撤销旧 pending + 落新 pending，返回消息 id；不通过整条丢弃返回 None
    （不重试不补救——下一轮对话会重新想，没什么可心疼的）。
    """
    content = str(payload.get("content", "")).strip()
    try:
        scheduled = datetime.strptime(str(payload.get("time", "")).strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        logger.info(f"[active] 用户 {user_id} 关心消息时间格式非法，丢弃: {payload!r}")
        return None

    now = datetime.now()
    # 政策校验：窗口 [now+30min, now+48h] + 送达点本身必须落在 07~23（别让夜里到点的靠顺延赌运气）
    if not content or len(content) > MAX_CONTENT_LEN:
        logger.info(f"[active] 用户 {user_id} 关心消息正文长度非法({len(content)})，丢弃")
        return None
    if scheduled < now + timedelta(minutes=MIN_DELAY_MIN) or scheduled > now + timedelta(hours=MAX_HORIZON_HOURS):
        logger.info(f"[active] 用户 {user_id} 关心消息送达时间出窗({scheduled})，丢弃")
        return None
    if not (QUIET_START <= scheduled.hour < QUIET_END):
        logger.info(f"[active] 用户 {user_id} 关心消息落在静默时段({scheduled})，丢弃")
        return None

    with SyncSessionLocal() as db:
        # 至多一条不变式（ws 收消息撤销是第一道，这里是生成端双保险）
        cancelled = send_message_repo.cancel_pending(db, user_id)
        msg = send_message_repo.create_pending(db, user_id, content, scheduled)
    logger.info(f"[active] 用户 {user_id} 新关心消息 #{msg.id} 定在 {scheduled}（撤销旧 {cancelled} 条）")
    return msg.id


# ═══════════════════════════════════════════════════════════════════
# 发送侧：统一扫描
# ═══════════════════════════════════════════════════════════════════

async def active_message_loop() -> None:
    """定时循环（main.py lifespan 挂）：每 SCAN_INTERVAL 秒扫一轮。循环本身不许挂。"""
    logger.info(f"[active] 主动关心扫描已启动（每 {SCAN_INTERVAL}s）")
    while True:
        await asyncio.sleep(SCAN_INTERVAL)
        try:
            await scan_once()
        except Exception as e:
            logger.error(f"[active] 扫描异常（跳过本轮）: {e}")


async def scan_once() -> int:
    """扫一轮到点的 pending，返回本轮实际推送成功条数。"""
    from app.ws.Hub import outbound_hub  # 函数内 import：避免启动期 ws 循环依赖

    now = datetime.now()
    sent = 0
    with SyncSessionLocal() as db:
        due = send_message_repo.fetch_due(db, now)
        for msg in due:
            # 闸门 1：过期作废（放最前，积压的坏消息先清出去）
            if now - msg.scheduled_at > timedelta(hours=GRACE_HOURS):
                send_message_repo.mark_expired(db, msg)
                logger.info(f"[active] 消息 #{msg.id} 错过发送窗，作废")
                continue
            # 闸门 2：静默时段顺延（到点消息都校验过在 7~23 内，走到这说明服务在夜里停摆过）
            if not (QUIET_START <= now.hour < QUIET_END):
                continue
            # 闸门 3：危机勿扰——人工正在陪的用户，AI 的关心是噪音（挂到过期自然作废）
            if crisis_repo.find_open(db, msg.user_id) is not None:
                logger.info(f"[active] 用户 {msg.user_id} 危机事件中，关心消息 #{msg.id} 勿扰")
                continue

            # 发送三段（对齐 dev/active：落会话 + 未读 +1 + outbound push）
            conv = conversation_repo.get_latest_by_user(db, msg.user_id)
            if conv is None:
                # 没会话发不了（理论不可达：主动消息只在聊完天后生成）——按作废处理
                send_message_repo.mark_expired(db, msg)
                continue
            hina_msg = message_repo.insert_one(db, conv.id, "hina", msg.content)
            conversation_repo.update_last_message(db, conv, msg.content, unread_delta=1)

            ok = await outbound_hub.push(msg.user_id, {
                "type": "active",
                "conversation_id": conv.id,
                "msg": {
                    "id": hina_msg.id,
                    "role": hina_msg.role,
                    "content": hina_msg.content,
                    "time": hina_msg.time,
                },
                # _reg_id 不用填：OutboundHub 离线降级时经回调自动注入（8/31 链路）
            })
            if ok:
                send_message_repo.mark_sent(db, msg)
                sent += 1
                logger.info(f"[active] 关心消息 #{msg.id} → 用户 {msg.user_id} 已送达")
            else:
                send_message_repo.bump_fail(db, msg)
                logger.warning(f"[active] 关心消息 #{msg.id} 推送失败（{msg.fail_count}/{send_message_repo.MAX_FAIL}）")
    return sent
