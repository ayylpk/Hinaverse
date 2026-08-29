"""
user_repo —— 用户表数据访问。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


def get_by_id(db: Session, user_id: int) -> User | None:
    """按主键查用户，不存在返回 None"""
    return db.get(User, user_id)


def get_by_username(db: Session, username: str) -> User | None:
    """按用户名查（登录/注册查重用）"""
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def create(
    db: Session,
    username: str,
    hashed_password: str,
    nickname: str,
    avatar: str = "",
) -> User:
    """新建用户并提交，返回带 id 的 User"""
    user = User(username=username, hashed_password=hashed_password, nickname=nickname, avatar=avatar)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_profile(db: Session, user: User, nickname: str | None = None, avatar: str | None = None) -> None:
    """修改昵称/头像（对象已由调用方持有），改完提交"""
    if nickname is not None:
        user.nickname = nickname
    if avatar is not None:
        user.avatar = avatar
    db.commit()


def update_password(db: Session, user: User, hashed_password: str) -> None:
    """改密码（bcrypt 哈希已由调用方生成）"""
    user.hashed_password = hashed_password
    db.commit()


def set_reg_id(db: Session, user: User, reg_id: str) -> None:
    """更新极光设备 reg_id（离线推送按用户取）"""
    user.reg_id = reg_id
    db.commit()


def list_all(db: Session) -> list[User]:
    """全量用户（日终压缩等定时任务遍历用）"""
    return list(db.execute(select(User).order_by(User.id)).scalars())
