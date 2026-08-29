"""
dairy —— 日记存取接口（两个 API，需 JWT 鉴权，按用户隔离）。

    POST /api/diary   插入一篇日记（user_id 取当前登录用户）
    GET  /api/diary   读取当前用户全部日记（select 全部，where user_id 匹配）

数据访问走 diary_repo（DAO）。
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import diary_repo
from app.schemas import DiaryCreate, DiaryOut
from app.security import get_current_user

router = APIRouter(prefix="/api/diary", tags=["diary"])


@router.post("", response_model=DiaryOut, status_code=status.HTTP_201_CREATED)
def insert_diary(
    body: DiaryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiaryOut:
    """插入一篇日记（user_id 取当前登录用户），返回带 id 的记录"""
    diary = diary_repo.create(db, user_id=current_user.id, content=body.content)
    return DiaryOut.model_validate(diary)


@router.get("", response_model=list[DiaryOut])
def list_diaries(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DiaryOut]:
    """读取当前用户全部日记（select 全部，where user_id 匹配当前用户，最新在前）"""
    return [DiaryOut.model_validate(d) for d in diary_repo.list_by_user(db, current_user.id)]
