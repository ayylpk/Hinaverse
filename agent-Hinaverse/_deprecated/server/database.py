from sqlalchemy import BigInteger, create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from pathlib import Path

Base = declarative_base()


class ChattingRecordsEnity(Base):
    """模拟现实"""
    __tablename__ = "chattingRecords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(Integer, nullable=False)  # 0=日奈，1=我
    text = Column(Text, nullable=False)
    time = Column(BigInteger, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "text": self.text,
            "time": self.time
        }

    def __repr__(self):
        return f"<Chat(role={self.role}, text={self.text[:20]}...)>"


class DiaryOfHinaEnity(Base):
    """日奈日记表"""
    __tablename__ = "diaryOfHina"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    time = Column(BigInteger, nullable=False)
    imagePath = Column(String(250), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "time": self.time,
            "image_path": self.imagePath
        }

    def __repr__(self):
        return f"<Diary(id={self.id}, title={self.title[:10]}...)>"


class DiaryOfMeEnity(Base):
    """我的日记表"""
    __tablename__ = "diaryOfMe"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    time = Column(BigInteger, nullable=False)
    imagePath = Column(String(250), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "time": self.time,
            "image_path": self.imagePath
        }

    def __repr__(self):
        return f"<Diary(id={self.id}, title={self.title[:10]}...)>"


class ImRecordsEnity(Base):
    """聊天记录表"""
    __tablename__ = "ImRecords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    time = Column(BigInteger, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "text": self.text,
            "time": self.time
        }

    def __repr__(self):
        return f"<ImRecord(id={self.id}, role={self.role}...) >"


class KaomojiEnity(Base):
    """颜文字表"""
    __tablename__ = "kaomoji"  # ✅ 改成 __tablename__

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(String(30), nullable=False)
    type = Column(String(10), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "content": self.content,
            "type": self.type
        }

    def __repr__(self):
        return f"<Kaomoji(id={self.id}, content={self.content})>"


class PhotoEnity(Base):
    """图片表"""
    __tablename__ = "photoPath"  # ✅ 改成 __tablename__

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String(250), nullable=False)
    time = Column(BigInteger, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "path": self.path,
            "time": self.time
        }

    def __repr__(self):
        return f"<Photo(id={self.id}, path={self.path})>"


# ====== 创建数据库 ======

DB_DIR = Path(__file__).resolve().parent.parent / "data" / "sqlite"
DB_DIR.mkdir(parents=True, exist_ok=True)

num = datetime.now().year - 2026
DATABASE_URL = f"sqlite:///{DB_DIR / f'hina{num}.db'}"
# echo=True 会把所有 SQL 打到控制台，生产环境噪音大，默认关闭
engine = create_engine(DATABASE_URL, echo=False)

if num == 0:
    # 第一年：创建所有表
    Base.metadata.create_all(engine)
else:
    # 后续年份：创建所有表（checkfirst 已存在则跳过）
    Base.metadata.create_all(engine, checkfirst=True)

""
