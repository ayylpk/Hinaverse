from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing import Optional

from server.database import engine
from server.services.ImRecordsService import ImRecordsService


# ==================== DB 依赖 ====================

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== Pydantic 模型 ====================


class ImSendRequest(BaseModel):
    """发送 IM 消息"""
    role: int = Field(..., ge=0, le=1, description="0=日奈, 1=用户")
    text: str = Field(..., min_length=1, max_length=10000, description="消息内容")


class ImRecordResponse(BaseModel):
    """单条 IM 消息"""
    id: int
    role: int
    text: str
    time: int


class SingleImResponse(BaseModel):
    code: int
    message: str
    data: ImRecordResponse | None = None


class ListImResponse(BaseModel):
    code: int
    message: str
    data: list[ImRecordResponse]


# ==================== 路由 ====================

router = APIRouter(prefix="/im", tags=["IM聊天记录"])


@router.post("/send", response_model=SingleImResponse)
def send(req: ImSendRequest, db: Session = Depends(get_db)):
    """写入一条 IM 聊天消息"""
    service = ImRecordsService(db)
    result = service.send(req.role, req.text)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("/{record_id}", response_model=SingleImResponse)
def get(record_id: int, db: Session = Depends(get_db)):
    """按 id 查询 IM 消息"""
    service = ImRecordsService(db)
    result = service.get(record_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("/history", response_model=ListImResponse)
def list_records(
    cursor: Optional[int] = Query(None, description="上一页最后一条的 time"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """游标分页获取 IM 消息（按时间降序）"""
    service = ImRecordsService(db)
    result = service.list(cursor, limit)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.delete("/{record_id}", response_model=SingleImResponse)
def delete(record_id: int, db: Session = Depends(get_db)):
    """删除一条 IM 消息"""
    service = ImRecordsService(db)
    result = service.delete(record_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()
