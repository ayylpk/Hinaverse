"""
设备路由：注册极光推送 reg_id（按用户维度存储）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.repositories import user_repo
from app.schemas import RegIdRequest
from app.security import get_current_user

router = APIRouter(prefix="/api/device", tags=["device"])


@router.post("/reg_id")
def register_reg_id(
    body: RegIdRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """注册设备 reg_id 到当前用户，离线推送时按用户取出"""
    user_repo.set_reg_id(db, current_user, body.reg_id)
    return {"ok": True}
