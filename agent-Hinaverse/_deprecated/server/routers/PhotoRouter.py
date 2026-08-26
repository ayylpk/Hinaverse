import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from server.database import engine
from server.services.PhotoService import PhotoService

IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "photo"


def _resolve_safe_path(rel_path: str) -> Path | None:
    """将客户端可控路径安全解析到 IMAGES_DIR 内；非法（绝对路径/.. 穿越/盘符）返回 None"""
    try:
        raw = rel_path.replace("\\", "/").strip()
        if not raw or raw.startswith("/"):
            return None
        p = Path(raw)
        if p.is_absolute() or ".." in p.parts:
            return None
        target = (IMAGES_DIR / raw).resolve()
        if not target.is_relative_to(IMAGES_DIR.resolve()):
            return None
        return target
    except (ValueError, OSError):
        return None


# ==================== DB 依赖 ====================

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== Pydantic 模型 ====================


class PhotoCreateRequest(BaseModel):
    """新增图片"""
    path: str = Field(..., min_length=1, max_length=250, description="图片路径")


class PhotoResponse(BaseModel):
    """图片记录"""
    id: int
    path: str
    time: int


class SinglePhotoResponse(BaseModel):
    code: int
    message: str
    data: PhotoResponse | None = None


class ListPhotoResponse(BaseModel):
    code: int
    message: str
    data: list[PhotoResponse]


# ==================== 路由 ====================

router = APIRouter(prefix="/photo", tags=["图片"])


@router.post("", response_model=SinglePhotoResponse)
def add(req: PhotoCreateRequest, db: Session = Depends(get_db)):
    """新增一条图片记录"""
    service = PhotoService(db)
    result = service.add(req.path)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.post("/upload", response_model=SinglePhotoResponse)
def upload(filename: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传图片，接收客户端文件名（含月目录，如 2026_07/UUID.jpg），直接使用"""
    # 安全校验：拒绝绝对路径、.. 穿越、盘符等，目标必须落在 IMAGES_DIR 内
    safe_path = _resolve_safe_path(filename)
    if safe_path is None:
        raise HTTPException(status_code=400, detail="非法路径")
    target_path = safe_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # 写磁盘
    with open(target_path, "wb") as f:
        f.write(file.file.read())
    # 存 DB（存相对路径，便于展示）
    rel_path = str(target_path.relative_to(IMAGES_DIR))
    service = PhotoService(db)
    result = service.add(rel_path)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("/{photo_id}", response_model=SinglePhotoResponse)
def get(photo_id: int, db: Session = Depends(get_db)):
    """按 id 查询图片"""
    service = PhotoService(db)
    result = service.get(photo_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.get("", response_model=ListPhotoResponse)
def list_photos(
    cursor: Optional[int] = Query(None, description="上一页最后一条的 time"),
    limit: int = Query(50, ge=1, le=200, description="每页条数"),
    db: Session = Depends(get_db),
):
    """游标分页获取图片列表（按时间降序）"""
    service = PhotoService(db)
    result = service.list(cursor, limit)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()


@router.delete("/{photo_id}", response_model=SinglePhotoResponse)
def delete(photo_id: int, db: Session = Depends(get_db)):
    """删除图片记录 + 磁盘文件"""
    # 先查路径再删文件
    get_service = PhotoService(db)
    photo = get_service.get(photo_id)
    if photo.is_success() and photo.data:
        file_path = _resolve_safe_path(photo.data.get("path", "") or "")
        if file_path is not None and file_path.exists():
            file_path.unlink()
            print(f"  [photo] 删除文件: {file_path}")

    service = PhotoService(db)
    result = service.delete(photo_id)
    if not result.is_success():
        raise HTTPException(status_code=result.code, detail=result.message)
    return result.to_dict()
