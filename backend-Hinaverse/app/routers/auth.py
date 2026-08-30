"""
认证路由：注册 / 登录 / 当前用户 / 修改资料 / 首管理员注册状态。
数据访问全部走 user_repo（DAO）。
"""
import random

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import config
from app.database import get_db
from app.models import User
from app.repositories import user_repo
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


@router.get("/admin-register-status")
def admin_register_status(db: Session = Depends(get_db)) -> dict:
    """首管理员注册通道是否开放：无 admin 用户 且 部署码已配置。
    运营台登录页据此决定是否展示「注册管理员」入口。"""
    return {"open": (not user_repo.has_admin(db)) and bool(config.ADMIN_INIT_CODE)}


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """注册：用户名唯一，密码 bcrypt 哈希，昵称随机生成，头像空串。
    is_admin=True 时按序校验部署码链（任一不过即拒绝，防止恶意抢先注册管理员）：
        ① 部署码已配置（否则通道关闭）  ② 请求码与配置码相等  ③ 全库无 admin
    is_admin 缺省/False：与历史行为完全一致（恒创建普通 user）。"""
    if user_repo.get_by_username(db, body.username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已被使用")

    role = "user"
    if body.is_admin:
        # ① 通道必须已配置（未配置 = 通道关闭）
        if not config.ADMIN_INIT_CODE:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员注册未开放")
        # ② 请求携带的部署码必须与配置码一致
        if body.init_code != config.ADMIN_INIT_CODE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邀请码错误")
        # ③ 全库只能有一个管理员（首个注册后通道永久关闭）
        if user_repo.has_admin(db):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已存在管理员，注册通道关闭")
        role = "admin"

    user = user_repo.create(
        db,
        username=body.username,
        hashed_password=hash_password(body.password),
        nickname=_random_nickname(),
        avatar="",
    )
    # role 通过 ORM 对象直接写入（create 不支持 role 参数，避免污染普通注册签名）
    if role == "admin":
        user.role = "admin"
        db.commit()
        db.refresh(user)

    token = create_access_token(user.id)
    return AuthResponse(token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """登录：校验用户名密码，返回 token 和 user"""
    user = user_repo.get_by_username(db, body.username)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码不正确")

    token = create_access_token(user.id)
    return AuthResponse(token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """获取当前登录用户信息"""
    return UserOut.model_validate(current_user)


@router.put("/profile", response_model=UserOut)
def update_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    """修改资料：昵称/头像可选；改密码需提供 current_password + new_password"""
    # 改密码校验
    if body.new_password is not None:
        if not body.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请输入当前密码")
        if not verify_password(body.current_password, current_user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
        user_repo.update_password(db, current_user, hash_password(body.new_password))

    if body.nickname is not None or body.avatar is not None:
        user_repo.update_profile(db, current_user, nickname=body.nickname, avatar=body.avatar)

    return UserOut.model_validate(current_user)
