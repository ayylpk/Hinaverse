from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing import Optional

from server.database import engine
from server.services.KaomojiService import KaomojiService


# ==================== DB 依赖 ====================

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== Pydantic 模型 ====================


class KaomojiCreateRequest(BaseModel):
    """新增颜文字"""
    content: str = Field(..., min_length=1, max_length=30, description="颜文字内容")
    type: str = Field("", max_length=10, description="分类标签")


class KaomojiResponse(BaseModel):
    """颜文字"""
    id: int
    content: str
    type: str


class SingleKaomojiResponse(BaseModel):
    code: int
    message: str
    data: KaomojiResponse | None = None


class ListKaomojiResponse(BaseModel):
    code: int
    message: str
    data: list[KaomojiResponse]


# ==================== 路由 ====================

router = APIRouter(prefix="/kaomoji", tags=["颜文字"])


@router.post("", response_model=SingleKaomojiResponse)
def add(req: KaomojiCreateRequest, db: Session = Depends(get_db)):
    """新增一个颜文字"""
    service = KaomojiService(db)
    result = service.add(req.content, req.type)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("/{kaomoji_id}", response_model=SingleKaomojiResponse)
def get(kaomoji_id: int, db: Session = Depends(get_db)):
    """按 id 查询颜文字"""
    service = KaomojiService(db)
    result = service.get(kaomoji_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("", response_model=ListKaomojiResponse)
def list_all(
    kaomoji_type: Optional[str] = Query(None, alias="type", description="按类型筛选，不传则返回全部"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """获取颜文字列表，可按 type 筛选"""
    service = KaomojiService(db)
    if kaomoji_type:
        result = service.list_by_type(kaomoji_type, limit)
    else:
        result = service.get_all(limit)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.delete("/{kaomoji_id}", response_model=SingleKaomojiResponse)
def delete(kaomoji_id: int, db: Session = Depends(get_db)):
    """删除一个颜文字"""
    service = KaomojiService(db)
    result = service.delete(kaomoji_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()
