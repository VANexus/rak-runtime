# rak-runtime 认知推理引擎（gRPC :50051）
# 纯 Agent 工程：镜像内零 torch/本地推理依赖，LLM/ASR 走外部 API
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 依赖层（独立 COPY 利用层缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 源码 + 预生成 gRPC stub + 提示词模板
COPY src/ ./src/
COPY prompts/ ./prompts/
COPY protos/ ./protos/
COPY generated/ ./generated/
COPY runtime_server.py ./

# 非 root 运行；数据目录（记忆/画像/图谱 JSON 持久化）
RUN useradd -r -u 10001 rak \
    && mkdir -p /app/data \
    && chown -R rak:rak /app
USER rak

ENV RAK_DATA_DIR=/app/data
EXPOSE 50051

CMD ["python", "runtime_server.py"]
