from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing import Optional

from server.database import engine
from server.services.DiaryOfMeService import DiaryOfMeService


# ==================== DB 依赖 ====================

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== Pydantic 模型 ====================


class DiaryCreateRequest(BaseModel):
    """新建日记"""
    title: str = Field(..., min_length=1, max_length=20, description="标题")
    content: str = Field(..., min_length=1, description="内容")
    image_path: str = Field("", max_length=250, description="图片路径（可选）")


class DiaryUpdateRequest(BaseModel):
    """更新日记（只传要改的字段）"""
    title: Optional[str] = Field(None, min_length=1, max_length=20)
    content: Optional[str] = Field(None, min_length=1)
    image_path: Optional[str] = Field(None, max_length=250)


class DiaryResponse(BaseModel):
    """单条日记"""
    id: int
    title: str
    content: str
    time: int
    image_path: str


class SingleDiaryResponse(BaseModel):
    code: int
    message: str
    data: DiaryResponse | None = None


class ListDiaryResponse(BaseModel):
    code: int
    message: str
    data: list[DiaryResponse]


# ==================== 路由 ====================

router = APIRouter(prefix="/diary/me", tags=["我的日记"])


@router.post("", response_model=SingleDiaryResponse)
def create(req: DiaryCreateRequest, db: Session = Depends(get_db)):
    """新建一篇我的日记"""
    service = DiaryOfMeService(db)
    result = service.create(req.title, req.content, req.image_path)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("/{diary_id}", response_model=SingleDiaryResponse)
def get(diary_id: int, db: Session = Depends(get_db)):
    """按 id 查我的日记"""
    service = DiaryOfMeService(db)
    result = service.get(diary_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("", response_model=ListDiaryResponse)
def list_diaries(
    cursor: Optional[int] = Query(None, description="上一页最后一条的 time"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """游标分页获取我的日记列表（按时间降序）"""
    service = DiaryOfMeService(db)
    result = service.list(cursor, limit)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.put("/{diary_id}", response_model=SingleDiaryResponse)
def update(diary_id: int, req: DiaryUpdateRequest, db: Session = Depends(get_db)):
    """更新我的日记"""
    service = DiaryOfMeService(db)
    result = service.update(diary_id, req.title, req.content, req.image_path)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.delete("/{diary_id}", response_model=SingleDiaryResponse)
def delete(diary_id: int, db: Session = Depends(get_db)):
    """删除一篇我的日记"""
    service = DiaryOfMeService(db)
    result = service.delete(diary_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()
