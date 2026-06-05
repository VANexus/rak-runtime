# rak-runtime 文档索引

Owner：Runtime

## 核心文档

| 文档 | 说明 |
|------|------|
| [README.md](../README.md) | 项目总览、特性介绍、快速开始 |
| [AGENTS.md](../AGENTS.md) | Agent/开发者指南、编码规范 |
| [architecture.md](./architecture.md) | 系统架构设计、核心模块详解 |
| [TODO.md](../TODO.md) | 任务清单与进度跟踪 |

## 接口与协议

| 文档 | 说明 |
|------|------|
| [grpc-contracts.md](./grpc-contracts.md) | gRPC 冻结契约（proto 语义 + 样例 + 错误码） |
| [rakmessage-mvp.md](./rakmessage-mvp.md) | params_json 与 RakMessage 的映射规则 |
| [protos/runtime.proto](../protos/runtime.proto) | gRPC Protocol Buffers 定义 |

## 部署与运维

| 文档 | 说明 |
|------|------|
| [personaplex-deployment.md](./personaplex-deployment.md) | PersonaPlex 服务端部署指南 |

## 模块速查

| 模块 | 源文件 | 文档 |
|------|--------|------|
| 认知记忆引擎 | `src/core/memory_engine.py` | [architecture.md#4-认知记忆引擎](./architecture.md#4-认知记忆引擎) |
| Agentic RAG | `src/core/agentic_rag.py` | [architecture.md#5-agentic-rag-引擎](./architecture.md#5-agentic-rag-引擎) |
| 决策引擎 | `src/core/decision_engine.py` | [architecture.md#3-决策引擎](./architecture.md#3-决策引擎) |
| 策略模型 | `src/core/policy_model.py` | [architecture.md#6-策略模型基底神经节](./architecture.md#6-策略模型基底神经节) |
| 双管线音频处理 | `src/core/audio_pipeline.py` | [architecture.md#2-双管线音频处理器](./architecture.md#2-双管线音频处理器) |
| 睡眠整合 | `src/core/sleep_consolidation.py` | [architecture.md#8-睡眠整合](./architecture.md#8-睡眠整合) |
| LoRA 训练 | `src/core/lora_trainer.py` | [architecture.md#9-lora-微调训练](./architecture.md#9-lora-微调训练) |
| PostgreSQL 后端 | `src/core/memory_postgres.py` | [architecture.md#7-持久化存储层](./architecture.md#7-持久化存储层) |
| Redis 后端 | `src/core/memory_redis.py` | [architecture.md#7-持久化存储层](./architecture.md#7-持久化存储层) |
| 持久化管理 | `src/core/memory_persistence.py` | [architecture.md#7-持久化存储层](./architecture.md#7-持久化存储层) |
| Whisper ASR | `src/tools/asr_tool.py` | [architecture.md#1-asr-感知层](./architecture.md#1-asr-感知层) |
| PersonaPlex 客户端 | `src/tools/personaplex_client.py` | [architecture.md#1-asr-感知层](./architecture.md#1-asr-感知层) |
| MQTT 发布 | `src/tools/mqtt_publisher.py` | — |
| MCP 技能服务器 | `src/mcp/skill_mcp_server.py` | [architecture.md#10-mcp-技能服务器](./architecture.md#10-mcp-技能服务器) |

## 对齐对象

- Go 中枢：`go-kernel/`
- 全局协议权威来源：`RakTec/`
- ESP32 固件：`rak-esp/`
- 前端网关：`Xra-space/`
