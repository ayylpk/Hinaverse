"""
checkin —— 打卡存取接口（星历模块，需 JWT 鉴权，按用户隔离）。

    POST   /api/checkin        新建一条打卡（content 1..500，date 可选缺省当天）
    GET    /api/checkin        当前用户全部打卡（date 倒序；可选 ?date=YYYY-MM-DD 过滤）
    PATCH  /api/checkin/{id}   打卡/取消打卡标记（status: done|todo）
    DELETE /api/checkin/{id}   删除一条打卡（204）

归属规则：user_id 一律取当前登录用户（JWT），客户端传参无效；
修改/删除必须校验记录属于当前用户，否则 404（与"跨用户操作"语义一致）。
数据访问走 checkin_repo（DAO）。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import checkin_repo
from app.schemas import CheckinCreate, CheckinOut, CheckinUpdate
from app.security import get_current_user

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


def _parse_date(value: str) -> datetime.date:
    """把 ?date=YYYY-MM-DD 解析成日期；格式非法 → 422（沿用 FastAPI 校验语义）"""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date 参数格式应为 YYYY-MM-DD",
        )


@router.post("", response_model=CheckinOut, status_code=status.HTTP_201_CREATED)
def create_checkin(
    body: CheckinCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckinOut:
    """新建一条打卡（归属日缺省当天；user_id 取当前登录用户）"""
    day = body.date or datetime.now().date()
    return CheckinOut.model_validate(checkin_repo.create(db, current_user.id, body.content, day))


@router.get("", response_model=list[CheckinOut])
def list_checkins(
    date: str | None = Query(None, description="可选：只取某天（YYYY-MM-DD）的打卡"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CheckinOut]:
    """当前用户全部打卡（date 倒序，date 相同再 id 倒序）；date 参数过滤"""
    day = _parse_date(date) if date else None
    return [CheckinOut.model_validate(c) for c in checkin_repo.list_by_user(db, current_user.id, day)]


@router.patch("/{checkin_id}", response_model=CheckinOut)
def update_checkin(
    checkin_id: int,
    body: CheckinUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckinOut:
    """打卡/取消打卡标记；记录不存在或不属于当前用户 → 404"""
    checkin = checkin_repo.get_owned(db, checkin_id, current_user.id)
    if checkin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="打卡记录不存在")
    return CheckinOut.model_validate(checkin_repo.update_status(db, checkin, body.status))


@router.delete("/{checkin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_checkin(
    checkin_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """删除一条打卡（204）；记录不存在或不属于当前用户 → 404"""
    checkin = checkin_repo.get_owned(db, checkin_id, current_user.id)
    if checkin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="打卡记录不存在")
    checkin_repo.delete(db, checkin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
