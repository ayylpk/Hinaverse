"""
stats_repo —— 运营台统计专用只读聚合查询（纯 SQL，无缓存、无业务写入）。

约定：
  - 时间窗一律由调用方算好传入（datetime），本层不碰"今天/7天前"这类语义；
  - 趋势类查询返回 {date: count} 字典（MySQL DATE() 分组），缺日由路由层补零；
  - "活跃/发言/消息数"口径统一 role='user'（用户说的话），hina/operator/system 不计入用户活跃。
"""
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Conversation, CrisisEvent, Message, User

# 未关闭状态：与 crisis_repo._OPEN_STATUSES 同语义（重复声明避免跨 repo import 耦合）
_OPEN_STATUSES = ("pending_human", "comforting", "handling")


def _as_date(v) -> date:
    """DATE() 结果归一化：pymysql 回 date 对象、部分驱动回 'YYYY-MM-DD' 字符串，
    统一转成 date 再当字典键——否则路由层补零时键类型对不上，趋势全零。"""
    return v if isinstance(v, date) else date.fromisoformat(str(v))


# ── 指标卡 ──


def count_total_users(db: Session) -> int:
    """总用户数（含管理员）"""
    return db.execute(select(func.count(User.id))).scalar_one()


def count_new_users_since(db: Session, since: datetime) -> int:
    """since（含）之后注册的用户数——「今日新增」传当日 0 点"""
    return db.execute(
        select(func.count(User.id)).where(User.created_at >= since)
    ).scalar_one()


def count_active_users_since(db: Session, since: datetime) -> int:
    """since 之后发过言的去重用户数（近 7 天活跃口径：说过话才算活跃）"""
    return db.execute(
        select(func.count(func.distinct(Conversation.user_id)))
        .join(Message, Message.conversation_id == Conversation.id)
        .where(Message.role == "user", Message.created_at >= since)
    ).scalar_one()


def count_messages_since(db: Session, since: datetime) -> int:
    """since 之后的消息总数（全 role，衡量大盘对话量）"""
    return db.execute(
        select(func.count(Message.id)).where(Message.created_at >= since)
    ).scalar_one()


def count_open_crises(db: Session) -> int:
    """未关闭危机事件数（pending_human/comforting/handling）"""
    return db.execute(
        select(func.count(CrisisEvent.id)).where(CrisisEvent.status.in_(_OPEN_STATUSES))
    ).scalar_one()


# ── 7 日趋势（DATE() 分组，返回 {date: count}，缺日不含） ──


def daily_new_users(db: Session, since: datetime) -> dict[date, int]:
    rows = db.execute(
        select(func.date(User.created_at), func.count(User.id))
        .where(User.created_at >= since)
        .group_by(func.date(User.created_at))
    ).all()
    return {_as_date(r[0]): r[1] for r in rows}


def daily_messages(db: Session, since: datetime) -> dict[date, int]:
    rows = db.execute(
        select(func.date(Message.created_at), func.count(Message.id))
        .where(Message.created_at >= since)
        .group_by(func.date(Message.created_at))
    ).all()
    return {_as_date(r[0]): r[1] for r in rows}


def daily_crises(db: Session, since: datetime) -> dict[date, int]:
    rows = db.execute(
        select(func.date(CrisisEvent.created_at), func.count(CrisisEvent.id))
        .where(CrisisEvent.created_at >= since)
        .group_by(func.date(CrisisEvent.created_at))
    ).all()
    return {_as_date(r[0]): r[1] for r in rows}


def crisis_distribution(db: Session) -> list[tuple[str, str, int]]:
    """全历史危机分布：(风险等级, 状态, 数量)，路由层转堆叠柱数据"""
    rows = db.execute(
        select(CrisisEvent.risk_level, CrisisEvent.status, func.count(CrisisEvent.id))
        .group_by(CrisisEvent.risk_level, CrisisEvent.status)
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


# ── 用户表（分页 + 搜索 + 批量聚合） ──


def search_users_page(
    db: Session,
    q: str | None,
    offset: int,
    limit: int,
) -> tuple[list[User], int]:
    """用户名/昵称模糊搜索 + 分页，返回 (当页 User 列表, 总数)。新注册用户排前面。"""
    stmt = select(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.username.like(like), User.nickname.like(like)))
    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()
    rows = list(db.execute(stmt.order_by(User.id.desc()).offset(offset).limit(limit)).scalars())
    return rows, total


def user_activity(
    db: Session, user_ids: list[int]
) -> tuple[dict[int, int], dict[int, datetime], dict[int, int]]:
    """
    批量取用户活跃统计（用户表三列：发言数/末次发言/危机次数），三条 GROUP BY 代替
    N+1 子查询。返回 (msg_counts, last_actives, crisis_counts)，缺项用 .get 兜 0/None。
    """
    if not user_ids:
        return {}, {}, {}
    msg_counts = {
        r[0]: r[1]
        for r in db.execute(
            select(Conversation.user_id, func.count(Message.id))
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id.in_(user_ids), Message.role == "user")
            .group_by(Conversation.user_id)
        ).all()
    }
    last_actives = {
        r[0]: r[1]
        for r in db.execute(
            select(Conversation.user_id, func.max(Message.created_at))
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id.in_(user_ids), Message.role == "user")
            .group_by(Conversation.user_id)
        ).all()
    }
    crisis_counts = {
        r[0]: r[1]
        for r in db.execute(
            select(CrisisEvent.user_id, func.count(CrisisEvent.id))
            .where(CrisisEvent.user_id.in_(user_ids))
            .group_by(CrisisEvent.user_id)
        ).all()
    }
    return msg_counts, last_actives, crisis_counts
