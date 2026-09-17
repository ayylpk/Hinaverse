"""
全局配置：从环境变量读取，开发期允许缺省。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（backend-Hinaverse/）
BASE_DIR = Path(__file__).resolve().parent.parent

# 加载开发机 .env（MySQL 密码等；已在 .gitignore 不入库）。
# 系统环境变量优先级更高（load_dotenv 默认不覆盖已存在的环境变量）。
load_dotenv(BASE_DIR / ".env")

# ── 安全 ──
# 生产环境必须通过环境变量注入，开发期用固定值兜底（需 ≥32 字节，避免 PyJWT 警告）
SECRET_KEY = os.getenv("HINA_SECRET_KEY", "hinaverse-dev-secret-please-change-me-now-2026")
JWT_ALGORITHM = "HS256"
# token 有效期：7 天
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# ── 运营台首管理员注册（部署码 + 通道关闭）──
# 读环境变量 HINA_ADMIN_INIT_CODE；空字符串 = 管理员注册通道关闭（默认，安全）。
# 生产必须配置强随机码（openssl rand -hex 16 级别），否则任何人无法注册管理员；
# 本地开发在 .env 填 dev 码。注册通道在"首个管理员创建后"自动永久关闭（见 auth.py）。
ADMIN_INIT_CODE = os.getenv("HINA_ADMIN_INIT_CODE", "")

# ── 数据库（MySQL）──
# 默认连本机 MySQL，库名 hinaverse（需预先创建：CREATE DATABASE hinaverse CHARACTER SET utf8mb4）
# 连接串可整体用 HINA_DB_URL 覆盖
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "hinaverse")
DB_URL = os.getenv(
    "HINA_DB_URL",
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4",
)

# ── 极光推送（可选，缺失时静默降级）──
JPUSH_APP_KEY = os.getenv("JPUSH_APP_KEY", "")
JPUSH_MASTER_SECRET = os.getenv("JPUSH_MASTER_SECRET", "")
JPUSH_URL = "https://api.jpush.cn/v3/push"

# ── CORS ──
# 前端开发端口，生产按需调整
CORS_ORIGINS = os.getenv("HINA_CORS_ORIGINS", "*").split(",")

# ── 分层记忆（app/hina_memory，本进程内建，不再依赖外部记忆服务）──
# 阈值可经环境变量覆盖；不设则用与用户对齐过的默认值（见 hina_memory/scheduler.py）：
#   HINA_MEM_L1_CUMULATIVE   L1 触发点，默认 "2,6,14,30,62"（块 2/4/8/16/32）
#   HINA_MEM_L2_INTERVAL     L1 到顶后每 +N 条推 1 条进 L2，默认 32
#   HINA_MEM_PORTRAIT_EVERY  L2 满几次生成/刷新画像，默认 4
#   HINA_MEM_WINDOW          近期保护窗（最近 N 条不参与压缩），默认 8
