# Hinaverse 后端镜像
# 构建上下文 = 仓库根。backend 通过 sys.path 引 agent-Hinaverse 图引擎
# （agent_service.py: parents[4]/"agent-Hinaverse"），所以容器内必须保持
# /app/backend-Hinaverse + /app/agent-Hinaverse 的同级布局，不能只拷 backend。
FROM python:3.12-slim

# 时区必须北京时间：日终总结（每天 24:00 循环）和离开判定都吃 datetime.now()
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# ── 依赖层（先拷 requirements 利用构建缓存）──
# ⚠️ pip 源：服务器上构建用腾讯云内网源；若哪天改本机构建，换成
#    https://mirrors.aliyun.com/pypi/simple/（内网源本机不可达）
COPY backend-Hinaverse/requirements.txt ./backend-Hinaverse/
COPY agent-Hinaverse/requirements.txt ./agent-Hinaverse/
RUN pip install --no-cache-dir -i https://mirrors.tencentyun.com/pypi/simple/ \
      -r backend-Hinaverse/requirements.txt \
      -r agent-Hinaverse/requirements.txt

# ── 源码层 ──
COPY backend-Hinaverse/ ./backend-Hinaverse/
COPY agent-Hinaverse/ ./agent-Hinaverse/

# 图引擎数据目录（checkpoint 库等）；生产由 compose 挂 ./agent-data 卷持久化
RUN mkdir -p /app/agent-Hinaverse/data/sqlite

EXPOSE 8000
WORKDIR /app/backend-Hinaverse

# 单 worker 铁律：WS 连接表 / 画像 TTL 缓存 / 定时任务都在进程内存里，
# 多 worker 会出现同一用户双连接互顶、任务重复触发——不要加 --workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
