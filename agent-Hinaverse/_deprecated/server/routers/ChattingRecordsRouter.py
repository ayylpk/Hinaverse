from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing import Optional

from server.database import engine
from server.services.ChattingRecordsService import ChatService

# ==================== DB 会话依赖 ====================

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    """FastAPI 依赖：每次请求注入一个 DB 会话，请求结束后自动关闭"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== Pydantic 模型 ====================


class SendMessageRequest(BaseModel):
    """发送消息的请求体"""
    role: int = Field(..., ge=0, le=1, description="0=日奈, 1=用户")
    text: str = Field(..., min_length=1, max_length=10000, description="消息内容")


class ChatMessageResponse(BaseModel):
    """单条消息响应"""
    id: int
    role: int
    text: str
    time: int


class ListResponse(BaseModel):
    """列表响应"""
    code: int
    message: str
    data: list[ChatMessageResponse]


class SingleResponse(BaseModel):
    """单条响应"""
    code: int
    message: str
    data: ChatMessageResponse | None = None


# ==================== 路由 ====================

router = APIRouter(prefix="/chat", tags=["聊天"])


@router.post("/send", response_model=SingleResponse)
def send_message(req: SendMessageRequest, db: Session = Depends(get_db)):
    """发送一条聊天消息"""
    service = ChatService(db)
    result = service.send_message(req.role, req.text)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("/message/{msg_id}", response_model=SingleResponse)
def get_message(msg_id: int, db: Session = Depends(get_db)):
    """按 id 查询单条消息"""
    service = ChatService(db)
    result = service.get_message(msg_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("/history", response_model=ListResponse)
def get_history(
    cursor: Optional[int] = Query(None, description="上一页最后一条的 time（毫秒时间戳）"),
    limit: int = Query(50, ge=1, le=200, description="每页条数"),
    db: Session = Depends(get_db),
):
    """游标分页获取聊天历史（按时间倒序）"""
    service = ChatService(db)
    result = service.get_history(cursor, limit)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("/all", response_model=ListResponse)
def get_all(
    limit: int = Query(1000, ge=1, le=5000, description="最大条数"),
    db: Session = Depends(get_db),
):
    """获取全部聊天记录（按时间升序）"""
    service = ChatService(db)
    result = service.get_all(limit)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.delete("/message/{msg_id}", response_model=SingleResponse)
def delete_message(msg_id: int, db: Session = Depends(get_db)):
    """按 id 删除一条消息"""
    service = ChatService(db)
    result = service.delete_message(msg_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()
