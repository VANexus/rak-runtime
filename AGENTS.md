# AGENTS.md — rak-runtime 开发者指南

## 项目概述

rak-runtime 是 RakTec / Xra AIoT 平台的 Python AI 运行时，作为边缘推理引擎，负责语音感知、认知决策、记忆管理和技能执行。运行在 Python 3.11+ 环境，通过 gRPC 与 go-kernel 通信，通过 MQTT 与 ESP32 设备交互。

## 快速开始

```bash
cd /home/xrak/workspace/rak-runtime
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
```

**启动 ASR 服务**：
```bash
python realtime_asr.py        # Whisper 方案（本地）
python realtime_personaplex.py # PersonaPlex 方案（远程）
```

**LoRA 训练**：
```bash
python train_lora.py collect --log data/execution_log.jsonl
python train_lora.py train --data data/training.jsonl
python train_lora.py test --input "开门"
python train_lora.py all --log data/execution_log.jsonl
```

## 项目结构

```
src/
├── core/                       # 核心引擎
│   ├── memory_engine.py        # 认知记忆引擎（三层记忆 + 反思学习）
│   ├── memory_persistence.py   # SQLite + JSON 文件持久化
│   ├── memory_postgres.py      # PostgreSQL 后端（pgvector）
│   ├── memory_redis.py         # Redis 后端（TTL + Pub/Sub）
│   ├── agentic_rag.py          # Agentic RAG 多跳检索
│   ├── decision_engine.py      # 决策引擎（LLM + 规则 + 记忆）
│   ├── policy_model.py         # 策略模型（在线学习）
│   ├── audio_pipeline.py       # 双管线音频处理
│   ├── sleep_consolidation.py  # 睡眠整合
│   └── lora_trainer.py         # LoRA 微调训练
├── tools/                      # 工具类
│   ├── asr_tool.py             # Whisper ASR
│   ├── personaplex_client.py   # PersonaPlex WebSocket 客户端
│   └── mqtt_publisher.py       # MQTT 发布
├── mcp/                        # MCP 协议
│   └── skill_mcp_server.py     # MCP 技能服务器
└── models/                     # 数据模型
    └── action.py               # 动作模型
```

## 编码规范

### 语言与风格

- **代码注释**：中文（与项目一致）
- **docstring**：中文，说明模块/类/方法的用途
- **变量名/函数名**：英文，snake_case
- **类名**：英文，PascalCase
- **常量**：英文，UPPER_SNAKE_CASE

### 命名约定

```python
# ✅ 正确
class CognitiveMemoryEngine:
    """认知记忆引擎 — 统一的记忆管理接口。"""
    
    def remember(self, content: str, memory_type: str = "episodic") -> MemoryEntry:
        """存入记忆。"""
        pass

# ❌ 错误
class memory_engine:  # 类名应 PascalCase
    def Remember(self):  # 方法名应 snake_case
        """Store memory."""  # 注释应中文
```

### 模块组织

- 每个模块顶部写模块级 docstring，说明模块用途和设计思路
- 使用 `logging` 而非 `print`
- 延迟导入重量级依赖（whisper、torch、psycopg2 等），在 `__init__` 中 try/except
- 不可用时返回 `None` 或 `False`，而非抛异常

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

所有外部依赖（PostgreSQL、Redis、LLM、ASR）都支持自动降级：

- PostgreSQL 不可用 → SQLite
- Redis 不可用 → JSON 文件
- LLM 不可用 → 规则引擎
- Whisper 不可用 → 禁用 ASR

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

## gRPC 接口

- **RuntimeService.Execute**：`ActionRequest → ActionResponse`，单动作决策
- **RuntimeService.StreamASR**：流式语音识别
- **RuntimeService.AudioDecide**：音频 → 多原子动作

Proto 定义在 `protos/runtime.proto`，修改后需重新生成 `generated/`。

## 测试

```bash
# 端到端测试
python test_e2e_full.py

# 服务器测试
python test_server.py
```

## 关键设计决策

1. **双引擎 ASR**：Whisper 本地 + PersonaPlex 远程，按环境切换
2. **三层记忆**：工作/短期/长期，模仿生物海马体
3. **Agentic RAG**：多跳迭代检索，不是单次 RAG
4. **策略模型 + LLM**：快慢双通道决策（基底神经节 + 前额叶皮层）
5. **睡眠整合**：定时记忆巩固、遗忘、反思
6. **LoRA 沉淀**：将经验转化为本地小模型能力

## 注意事项

- 不要删除 mock 实现，在真实 LLM 未就绪前用于端到端联调
- `trace_id` 必须全链路透传（gRPC → MQTT → WS）
- 返回动作必须在 `available_actions` 范围内
- 任何失败都以 `status=error` 返回，不允许静默失败
- 修改 proto 后必须重新生成 `generated/` 目录
