# AGENTS.md — rak-runtime 开发者指南

## 项目概述

rak-runtime 是 RakTec / Xra AIoT 平台的 Python AI 运行时，作为**纯认知推理引擎**，负责 LLM 决策、记忆管理和技能执行。通过 gRPC 与 go-kernel 通信，通过外部 LLM API 做决策。

**核心原则：纯 Agent 工程，零本地推理。**
- ASR → PersonaPlex 远程 API
- LLM → Anthropic API（或兼容代理）
- 不依赖 torch/whisper/sounddevice 等本地推理库

## 快速开始

```bash
cd rak-runtime
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
python runtime_server.py       # 启动 gRPC 服务器 :50051
```

## 项目结构

```
src/
├── core/                       # 核心引擎
│   ├── decision_engine.py      # 决策引擎（三层降级：缓存→LLM→规则）
│   ├── prompt_engine.py        # 提示词引擎（动态系统提示词构建）
│   ├── semantic_cache.py       # 语义缓存（高频查询 <1ms 返回）
│   ├── learning_loop.py        # 学习闭环（执行反馈→经验沉淀）
│   ├── memory_engine.py        # 认知记忆引擎（三层记忆 + 反思学习）
│   ├── memory_persistence.py   # SQLite + JSON 文件持久化
│   ├── memory_postgres.py      # PostgreSQL 后端（pgvector）
│   ├── memory_redis.py         # Redis 后端（TTL + Pub/Sub）
│   ├── agentic_rag.py          # Agentic RAG 多跳检索
│   ├── audio_pipeline.py       # 双管线音频处理（PersonaPlex + LLM）
│   ├── sleep_consolidation.py  # 睡眠整合
│   └── world_model.py          # 世界模型（设备状态预测）
├── tools/                      # 工具类
│   ├── __init__.py             # MQTTPublisher 导出
│   └── mqtt_publisher.py       # MQTT 发布
├── mcp/                        # MCP 协议
│   └── skill_mcp_server.py     # MCP 技能服务器
└── models/                     # 数据模型
    └── action.py               # 动作模型（占位）
```

## 编码规范

### 语言与风格

- **代码注释**：中文
- **docstring**：中文
- **变量名/函数名**：英文，snake_case
- **类名**：英文，PascalCase
- **常量**：英文，UPPER_SNAKE_CASE
- **日志**：用 `logging` 模块，不用 `print`

### 延迟初始化模式

```python
_instance = None

def _get_instance():
    global _instance
    if _instance is None:
        try:
            from src.some_module import SomeClass
            _instance = SomeClass()
        except Exception as e:
            logger.warning(f"初始化失败: {e}")
            _instance = False  # 标记为不可用
    return _instance if _instance is not False else None
```

### 降级策略

所有外部依赖都支持自动降级：

- LLM 不可用 → 规则引擎
- PersonaPlex 不可用 → ASR 功能禁用
- PostgreSQL 不可用 → SQLite
- Redis 不可用 → JSON 文件

**原则**：永远不要因为一个组件不可用而导致整个服务崩溃。

## 环境变量

| 变量 | 说明 | 必需 |
|------|------|------|
| `ANTHROPIC_AUTH_TOKEN` | Anthropic API Key | LLM 功能必需 |
| `ANTHROPIC_BASE_URL` | API 代理地址 | 否（有默认值） |
| `ANTHROPIC_MODEL` | 模型名 | 否（默认 mimo-v2.5-pro） |
| `RAG_POSTGRES_DSN` | PostgreSQL 连接串 | 否（回退 SQLite） |
| `MQTT_BROKER_HOST` | MQTT Broker 地址 | 否（默认 localhost） |
| `MQTT_BROKER_PORT` | MQTT Broker 端口 | 否（默认 1883） |
| `PERSONAPLEX_SERVER` | PersonaPlex WebSocket | 否（有默认值） |

## 三层决策架构

```
请求 → ① 语义缓存（<1ms）→ 命中？→ 直接返回
                ↓ 未命中
       ② 记忆检索 + LLM 深思（~1s）→ 成功？→ 返回 + 缓存
                ↓ 失败
       ③ 规则引擎兜底 → 返回
```

## gRPC 接口

- **RuntimeService.Execute**：`ActionRequest → ActionResponse`
- **RuntimeService.StreamASR**：流式语音识别（通过 PersonaPlex）

Proto 定义在 `protos/runtime.proto`，修改后需重新生成 `generated/`。

## 测试

```bash
python test_server.py          # StreamASR 测试
python test_client.py          # Execute 文本测试
python test_e2e_full.py        # 端到端全链路测试
```

测试需要先启动服务器：`python runtime_server.py`

## 注意事项

- 不要引入 torch/whisper/sounddevice 等本地推理依赖
- `trace_id` 必须全链路透传（gRPC → MQTT → WS）
- 返回动作必须在 `available_actions` 范围内
- 任何失败都以 `status=error` 返回，不允许静默失败
- 修改 proto 后必须重新生成 `generated/` 目录
