FROM python:3.12-slim

# 时区设为北京时间
RUN ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && echo "Asia/Shanghai" > /etc/timezone

WORKDIR /app

# 安装 uv（用阿里云镜像加速）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

# 先装依赖
COPY requirements.txt .
RUN uv pip install --system --no-cache -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 复制项目代码
COPY . .

# 数据目录
RUN mkdir -p /app/data/chroma /app/data/sqlite /app/data/daily /app/data/photo

EXPOSE 8000

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
