"""
认证路由：注册 / 登录 / 当前用户 / 修改资料。
"""
import random

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import AuthResponse, LoginRequest, ProfileUpdateRequest, RegisterRequest, UserOut
from app.security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 注册时随机昵称的前缀池
_NICKNAME_PREFIXES = [
    "夜航者", "星尘", "拾光者", "云游", "晚风", "眠羊", "晨雾", "潮汐",
    "萤火", "木棉", "雪松", "青鸟",
]


def _random_nickname() -> str:
    """生成「前缀·四位数字」格式的随机昵称，如「夜航者·4821」"""
    prefix = random.choice(_NICKNAME_PREFIXES)
    suffix = random.randint(1000, 9999)
    return f"{prefix}·{suffix}"


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """注册：用户名唯一，密码 bcrypt 哈希，昵称随机生成，头像空串"""
    # 检查用户名是否已存在
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已被使用")

    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        nickname=_random_nickname(),
        avatar="",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return AuthResponse(token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """登录：校验用户名密码，返回 token 和 user"""
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码不正确")

    token = create_access_token(user.id)
    return AuthResponse(token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """获取当前登录用户信息"""
    return UserOut.model_validate(current_user)


@router.put("/profile", response_model=UserOut)
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """修改资料：昵称/头像可选；改密码需提供 current_password + new_password"""
    # 改密码校验
    if body.new_password is not None:
        if not body.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请输入当前密码")
        if not verify_password(body.current_password, current_user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
        current_user.hashed_password = hash_password(body.new_password)

    if body.nickname is not None:
        current_user.nickname = body.nickname
    if body.avatar is not None:
        current_user.avatar = body.avatar

    await db.commit()
    await db.refresh(current_user)
    return UserOut.model_validate(current_user)
