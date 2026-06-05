# rak-runtime

> RakTec / Xra AIoT 平台的 Python AI 运行时 —— 具身智能决策核心

## 定位

rak-runtime 是具身 AI 系统的**边缘推理引擎**，负责：

1. **语音感知**：ASR 语音转文字（Whisper 本地 + PersonaPlex 远程双引擎）
2. **认知决策**：LLM 驱动的自然语言 → 原子动作分解（支持多步规划）
3. **记忆系统**：三层认知记忆（工作 / 短期 / 长期）+ Agentic RAG 多跳检索
4. **策略学习**：在线策略模型（REINFORCE）+ LoRA 微调知识沉淀
5. **工具协议**：MCP 技能服务器，暴露技能网络给 LLM 发现和调用

## 核心特性

### 🎤 ASR 语音感知（双引擎）

| 方案 | 架构 | 延迟 | 运行环境 | 适用场景 |
|------|------|------|----------|----------|
| Whisper | 本地 ASR → 文本 → MQTT | ~500ms | 本地 Mac/PC | 开发调试、无 GPU 环境 |
| PersonaPlex | 端到端全双工音频流 | ~200ms | 服务器 GPU | 生产环境、低延迟要求 |

### 🧠 认知记忆系统

模仿生物海马体的三层记忆架构：

- **工作记忆**：当前上下文窗口（滑动窗口，7±2 项）
- **短期记忆**：最近对话和事件（LRU 策略，按时间衰减）
- **长期记忆**：知识库和经验（向量检索，ANN 语义查询）

三种记忆形态：
- 事实性记忆（Episodic）—— 发生了什么
- 程序性记忆（Procedural）—— 怎么做（技能/LoRA）
- 语义记忆（Semantic）—— 是什么（知识图谱）

### 🔍 Agentic RAG 多跳检索推理

不同于单次 RAG，Agentic RAG 实现迭代式深思：

1. **RETRIEVE**：粗粒度初始检索
2. **REASON**：判断证据是否充分
3. **REFINE**：不充分则精化查询
4. **SYNTHESIZE**：跨文档综合推理

支持内置规则引擎和 LLM 推理两种模式，LLM 不可用时自动降级。

### 💾 持久化存储（PostgreSQL + Redis）

| 后端 | 存储内容 | 特性 |
|------|----------|------|
| PostgreSQL | 长期记忆、向量检索、执行指标 | pgvector 扩展、全文搜索、连接池 |
| Redis | 短期记忆、工作记忆、执行日志 | TTL 自动过期、微秒级读写、Pub/Sub |
| SQLite | 本地回退 | 零依赖、单文件 |
| JSON 文件 | 最小回退 | 纯标准库 |

所有后端支持自动降级：PostgreSQL 不可用 → SQLite，Redis 不可用 → JSON 文件。

### 🏋️ LoRA 微调训练

将执行日志和程序性记忆转化为训练数据，通过 LoRA 微调本地小模型（Qwen2-0.5B）：

- 快速动作分类（<10ms，替代 LLM API 调用）
- 离线场景下的决策能力
- 个性化行为学习

训练流程：记忆收集 → JSONL 导出 → LoRA 微调 → 适配器导出 → 推理加载

### 🤖 策略模型（基底神经节）

单层线性网络（softmax 策略），模仿大脑基底神经节：

- **快思考**：<1ms 推理延迟，直接输出离散动作 ID
- **在线学习**：REINFORCE 风格策略梯度更新
- **ε-greedy 探索**：平衡利用与探索

### 🔧 MCP 技能服务器

MCP（Model Context Protocol）JSON-RPC 服务器，让 LLM 可以：

- 列出所有技能（工具发现）
- 激活技能（工具调用）
- 查询设备状态（资源访问）
- 搜索记忆（资源访问）

### 🌊 双管线音频处理

```
音频输入 → ┌─ PersonaPlex ──→ 语音回复（即时，超低延迟）
            └─ ASR → LLM ──→ 动作列表（规划）+ 提示词反哺
```

PersonaPlex 负责即时语音回复，ASR+LLM 负责深度动作决策，LLM 生成的上下文提示词反哺给 PersonaPlex 让语音回复更智能。

### 💤 睡眠整合

模仿人类睡眠中的记忆巩固：

1. 短期 → 长期记忆迁移（重要性筛选）
2. 低显著性记忆遗忘（突触修剪）
3. 反思学习批处理（经验提取）
4. 记忆压缩（相似记忆合并）

## 项目结构

```
rak-runtime/
├── src/
│   ├── core/
│   │   ├── memory_engine.py        # 认知记忆引擎（三层记忆 + 反思学习）
│   │   ├── memory_persistence.py   # 持久化后端（SQLite + JSON 文件）
│   │   ├── memory_postgres.py      # PostgreSQL 后端（pgvector + 连接池）
│   │   ├── memory_redis.py         # Redis 后端（TTL + Pub/Sub）
│   │   ├── agentic_rag.py          # Agentic RAG 多跳检索引擎
│   │   ├── decision_engine.py      # 决策引擎（LLM + 规则引擎 + 记忆集成）
│   │   ├── policy_model.py         # 策略模型（基底神经节，在线学习）
│   │   ├── audio_pipeline.py       # 双管线音频处理（PersonaPlex + ASR+LLM）
│   │   ├── sleep_consolidation.py  # 睡眠整合（记忆巩固 + 遗忘 + 反思）
│   │   └── lora_trainer.py         # LoRA 微调训练器
│   ├── tools/
│   │   ├── asr_tool.py             # Whisper ASR 工具类
│   │   ├── personaplex_client.py   # PersonaPlex ASR WebSocket 客户端
│   │   └── mqtt_publisher.py       # MQTT 消息发布工具
│   ├── mcp/
│   │   └── skill_mcp_server.py     # MCP 技能服务器
│   └── models/
│       └── action.py               # 动作数据模型
├── protos/
│   └── runtime.proto               # gRPC 协议定义
├── generated/                      # 生成的 gRPC 代码
├── realtime_asr.py                 # Whisper ASR 方案入口
├── realtime_personaplex.py         # PersonaPlex ASR 方案入口
├── train_lora.py                   # LoRA 训练脚本入口
├── test_e2e_full.py                # 端到端测试
├── test_server.py                  # 服务器测试
├── docs/                           # 文档目录
├── AGENTS.md                       # Agent/开发者指南
├── TODO.md                         # 任务清单
└── requirements.txt                # 依赖版本锁定
```

## 快速开始

### 环境准备

```bash
# 克隆仓库
git clone https://github.com/VANexus/rak-runtime.git
cd rak-runtime

# 创建虚拟环境并安装依赖
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 方案 1：Whisper ASR（默认，本地可运行）

```bash
python realtime_asr.py
```

### 方案 2：PersonaPlex ASR（低延迟，推荐生产）

```bash
# 前置条件：服务器端已启动 PersonaPlex 服务
python realtime_personaplex.py
```

### LoRA 训练

```bash
# 收集训练数据
python train_lora.py collect --log data/execution_log.jsonl

# 执行 LoRA 微调
python train_lora.py train --data data/training.jsonl

# 测试推理
python train_lora.py test --input "开门"

# 完整流程
python train_lora.py all --log data/execution_log.jsonl
```

## gRPC 接口

- **RuntimeService.Execute**：单动作决策（输入状态/动作，返回动作 + 参数）
- **RuntimeService.StreamASR**：流式语音识别
- **RuntimeService.AudioDecide**：音频 → ASR → LLM 分解 → 多原子动作

详见 [docs/grpc-contracts.md](./docs/grpc-contracts.md)

## 文档

- [文档索引](./docs/INDEX.md)
- [架构设计](./docs/architecture.md)
- [Agent 开发指南](./AGENTS.md)
- [gRPC 契约](./docs/grpc-contracts.md)
- [RakMessage 协议](./docs/rakmessage-mvp.md)
- [PersonaPlex 部署](./docs/personaplex-deployment.md)

## 对齐契约

- gRPC proto：[protos/runtime.proto](./protos/runtime.proto)
- gRPC 语义与样例：[docs/grpc-contracts.md](./docs/grpc-contracts.md)
- params_json 映射 RakMessage.params：[docs/rakmessage-mvp.md](./docs/rakmessage-mvp.md)

## MVP 最小动作集

`shake_head` · `wave_hand` · `lock_open` · `lock_close` · `move_forward` · `move_back` · `turn_left` · `turn_right` · `dance` · `nod` · `light_on` · `light_off` · `emergency_stop` · `idle`

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_AUTH_TOKEN` | Anthropic API Key | — |
| `ANTHROPIC_BASE_URL` | Anthropic API 代理地址 | `https://token-plan-cn.xiaomimimo.com/anthropic` |
| `ANTHROPIC_MODEL` | LLM 模型名 | `mimo-v2.5-pro` |
| `RAG_POSTGRES_DSN` | PostgreSQL 连接串 | `postgresql://rak:***@localhost:5432/rak_memory` |
| `MQTT_BROKER_HOST` | MQTT Broker 地址 | `localhost` |
| `MQTT_BROKER_PORT` | MQTT Broker 端口 | `1883` |
| `PERSONAPLEX_SERVER` | PersonaPlex WebSocket 地址 | `ws://8.129.26.180:8998/ws` |

## 依赖

- Python 3.11+
- whisper / openai-whisper（ASR）
- anthropic（LLM 客户端）
- paho-mqtt（MQTT）
- psycopg2（PostgreSQL）
- redis（Redis）
- peft / transformers / datasets（LoRA 训练）
- grpcio / grpcio-tools（gRPC）
