"""
sendMessage —— 极简消息存取接口（两个 API，需 JWT 鉴权）。

    POST /api/send-message      插入一条消息 {content}，user_id 取当前登录用户
    GET  /api/send-message/{id} 按主键读取一条消息

数据访问走 send_message_repo（DAO），不直接操作 session。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import send_message_repo
from app.schemas import SendMessageCreate, SendMessageOut
from app.security import get_current_user

router = APIRouter(prefix="/api/send-message", tags=["send-message"])


@router.post("", response_model=SendMessageOut, status_code=status.HTTP_201_CREATED)
def insert_message(
    body: SendMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SendMessageOut:
    """插入一条消息（user_id 取 token 中的当前用户，防越权），返回带 id 的记录"""
    msg = send_message_repo.create(db, user_id=current_user.id, content=body.content,
                                   scheduled_at=body.scheduled_at)
    return SendMessageOut.model_validate(msg)


@router.get("/{msg_id}", response_model=SendMessageOut)
def get_message(
    msg_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SendMessageOut:
    """按主键读取一条消息，不存在返回 404（需登录）"""
    msg = send_message_repo.get_by_id(db, msg_id)
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在")
    return SendMessageOut.model_validate(msg)
