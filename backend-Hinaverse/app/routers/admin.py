"""
运营台统计路由（/api/admin，仅管理员）：大盘指标 / 7日趋势 / 危机分布 / 用户表 / 用户详情 / 画像。

原则（9/7 拍板）：
  - 统计全部确定性逻辑 → 纯 SQL 聚合走 stats_repo，不做缓存、不碰 LLM；
  - 「当前在线」直读 OutboundHub 连接表（内存即事实源，查库反而失真）；
  - 画像零新业务逻辑 → 转发 ws 链路同款 agent_memory.get_portrait_cached，
    项目 Key 留在服务端，浏览器永远拿不到；
  - 抽屉拆两个接口：detail（本地 SQL，秒开）+ portrait（跨服务，懒加载），
    AgentMemory 挂了只空一个画像栏，不拖垮整页。
"""
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import crisis_repo, message_repo, stats_repo, user_repo
from app.schemas import (
    AdminCrisisDist,
    AdminPortraitOut,
    AdminStatsCards,
    AdminStatsOut,
    AdminTrendPoint,
    AdminUserDetailOut,
    AdminUserOut,
    AdminUserPageOut,
    CrisisEventOut,
    MessageOut,
)
from app.security import require_admin
from app.services import agent_memory
from app.ws.Hub import outbound_hub

router = APIRouter(prefix="/api/admin", tags=["admin"])

_TREND_DAYS = 7  # 趋势回看天数（含今天）


def _user_row(
    user: User,
    msg_counts: dict[int, int],
    last_actives: dict[int, datetime],
    crisis_counts: dict[int, int],
) -> AdminUserOut:
    """User + 三张聚合字典 → 用户表行（列表/详情共用）"""
    return AdminUserOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        created_at=user.created_at,
        last_active=last_actives.get(user.id),
        msg_count=msg_counts.get(user.id, 0),
        crisis_count=crisis_counts.get(user.id, 0),
    )


@router.get("/stats", response_model=AdminStatsOut)
def get_stats(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminStatsOut:
    """统计页主数据：指标卡 + 7 日趋势（缺日补零）+ 危机分布（全历史）"""
    now = datetime.now()
    today_0 = datetime.combine(now.date(), time.min)
    trend_from = today_0 - timedelta(days=_TREND_DAYS - 1)   # 含今天共 7 天
    rolling_7d = now - timedelta(days=7)

    cards = AdminStatsCards(
        total_users=stats_repo.count_total_users(db),
        new_users_today=stats_repo.count_new_users_since(db, today_0),
        active_users_7d=stats_repo.count_active_users_since(db, rolling_7d),
        messages_7d=stats_repo.count_messages_since(db, rolling_7d),
        open_crises=stats_repo.count_open_crises(db),
        online_users=outbound_hub.online_count(),
    )

    users_map = stats_repo.daily_new_users(db, trend_from)
    msgs_map = stats_repo.daily_messages(db, trend_from)
    crises_map = stats_repo.daily_crises(db, trend_from)
    # 逐日补零：repo 的 GROUP BY 只回有数据的日期，图表要连续 7 天
    trend = []
    for i in range(_TREND_DAYS - 1, -1, -1):
        d = (now - timedelta(days=i)).date()
        trend.append(AdminTrendPoint(
            date=d.isoformat(),
            new_users=users_map.get(d, 0),
            messages=msgs_map.get(d, 0),
            crises=crises_map.get(d, 0),
        ))

    crisis_dist = [
        AdminCrisisDist(risk_level=r, status=s, count=c)
        for r, s, c in stats_repo.crisis_distribution(db)
    ]
    return AdminStatsOut(cards=cards, trend=trend, crisis_dist=crisis_dist)


@router.get("/users", response_model=AdminUserPageOut)
def list_users(
    q: str | None = Query(None, max_length=64, description="用户名/昵称模糊搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserPageOut:
    """用户表：分页 + 搜索，行内带发言数/末次活跃/危机数（三条批量 GROUP BY）"""
    users, total = stats_repo.search_users_page(db, q, (page - 1) * size, size)
    msg_counts, last_actives, crisis_counts = stats_repo.user_activity(
        db, [u.id for u in users]
    )
    items = [
        _user_row(u, msg_counts, last_actives, crisis_counts) for u in users
    ]
    return AdminUserPageOut(total=total, page=page, size=size, items=items)


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = user_repo.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


@router.get("/users/{user_id}/detail", response_model=AdminUserDetailOut)
def get_user_detail(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserDetailOut:
    """用户详情抽屉（秒开部分）：资料 + 跨会话最近 20 条 + 危机史（画像走 /portrait 懒加载）"""
    user = _get_user_or_404(db, user_id)
    msg_counts, last_actives, crisis_counts = stats_repo.user_activity(db, [user.id])
    recent = message_repo.get_recent_for_user(db, user.id, limit=20)
    events = crisis_repo.list_by_user(db, user.id)
    return AdminUserDetailOut(
        user=_user_row(user, msg_counts, last_actives, crisis_counts),
        messages=[MessageOut.model_validate(m) for m in recent],
        crises=[CrisisEventOut.model_validate(e) for e in events],
    )


@router.get("/users/{user_id}/portrait", response_model=AdminPortraitOut)
async def get_user_portrait(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPortraitOut:
    """画像转发：复用 ws 链路同款 TTL 缓存客户端，失败/无画像返回 None 走前端空态。
    async 定义——httpx 3s 超时在事件循环里等，不吃线程池工位。"""
    _get_user_or_404(db, user_id)
    portrait = await agent_memory.get_portrait_cached(user_id)
    return AdminPortraitOut(user_id=user_id, portrait=portrait)
