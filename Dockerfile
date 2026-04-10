# Dockerfile
FROM python:3.11-slim

# 添加调试工具
RUN apt-get update && apt-get install -y \
    procps \
    net-tools \
    iputils-ping \
    curl \
    vim-tiny \
    && rm -rf /var/lib/apt/lists/*
    
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装依赖（使用国内镜像加速）
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 50051

# 健康检查（可选）
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import grpc; import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.connect(('localhost', 50051)); s.close()" || exit 1

# 启动命令
CMD ["python", "runtime_server.py"]