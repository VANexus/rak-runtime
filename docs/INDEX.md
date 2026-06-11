# rak-runtime 文档索引

Owner：Runtime

## 核心文档

| 文档 | 说明 |
|------|------|
| [README.md](../README.md) | 项目总览、架构、快速开始 |
| [AGENTS.md](../AGENTS.md) | Agent/开发者指南、编码规范 |
| [CLAUDE.md](../CLAUDE.md) | Claude Code 指南、五层认知架构详解 |
| [architecture.md](./architecture.md) | 系统架构设计、核心模块详解 |
| [TODO.md](../TODO.md) | 任务清单与进度跟踪 |

## 接口与协议

| 文档 | 说明 |
|------|------|
| [grpc-contracts.md](./grpc-contracts.md) | gRPC 冻结契约（proto 语义 + 样例 + 错误码） |
| [rakmessage-mvp.md](./rakmessage-mvp.md) | params_json 与 RakMessage 的映射规则 |
| [protos/runtime.proto](../protos/runtime.proto) | gRPC Protocol Buffers 定义 |

## 参考文献

| 文档 | 说明 |
|------|------|
| [references.md](./references.md) | 论文引用与技术灵感来源 |

## 模块速查（28 个认知模块）

### 决策与编排

| 模块 | 源文件 | 说明 |
|------|--------|------|
| 决策引擎 | `src/core/decision_engine.py` | 15 步决策管线，中央调度器 |
| 提示词引擎 | `src/core/prompt_engine.py` | 动态系统提示词构建 |
| 语义缓存 | `src/core/semantic_cache.py` | 高频查询 <1ms 返回 |
| 学习闭环 | `src/core/learning_loop.py` | 执行反馈→经验沉淀→提示词优化 |

### 记忆系统（生物海马体模型）

| 模块 | 源文件 | 说明 |
|------|--------|------|
| 三层记忆 | `src/core/memory_engine.py` | 工作/短期/长期 + 反思学习 |
| 联想记忆流 | `src/core/memory_stream.py` | 随机激活→语义联想→洞察涌现 |
| 活体知识图谱 | `src/core/living_graph.py` | 扩散激活+赫布学习+自动建图 |
| 睡眠整合 | `src/core/sleep_consolidation.py` | 短期→长期迁移、遗忘、反思 |
| SQLite/JSON 持久化 | `src/core/memory_persistence.py` | 本地回退 |
| PostgreSQL 后端 | `src/core/memory_postgres.py` | pgvector 向量检索 |
| Redis 后端 | `src/core/memory_redis.py` | TTL + Pub/Sub |
| Agentic RAG | `src/core/agentic_rag.py` | 多跳检索推理 |

### 认知增强

| 模块 | 源文件 | 说明 |
|------|--------|------|
| 世界模型 | `src/core/world_model.py` | 设备状态预测+异常检测 |
| 用户模型 | `src/core/user_model.py` | 画像+意图推断+偏好学习 |
| 元认知 | `src/core/meta_cognition.py` | 置信度评估+策略选择+自我反思 |
| 主动智能 | `src/core/proactive_engine.py` | 异常告警+需求预测 |
| CogRec | `src/core/cog_rec.py` | LLM 教规则引擎，减少 LLM 调用 |
| 动作记忆 | `src/core/action_memory.py` | 记录-重放，<1ms 绕过 LLM |
| 提示词进化 | `src/core/prompt_evolution.py` | 战术+战略双流进化 |
| 安全治理 | `src/core/safety_governance.py` | LLM 驱动的运行时安全 |
| 策略模型 | `src/core/policy_model.py` | 基底神经节，在线学习 |

### 生命体架构

| 模块 | 源文件 | 说明 |
|------|--------|------|
| 自我认知 | `src/core/self_model.py` | 身份+能力+性格+关系+信念 |
| 情绪动力学 | `src/core/emotion_state.py` | 六维情绪+事件驱动+衰减 |
| 需求引擎 | `src/core/need_engine.py` | 基于系统信号的内部驱动力 |
| 内心循环 | `src/core/inner_loop.py` | 事件驱动心跳 |
| 对话状态 | `src/core/conversation_state.py` | 话题追踪+发散思考+无缝衔接 |

### 音频与工具

| 模块 | 源文件 | 说明 |
|------|--------|------|
| 音频管线 | `src/core/audio_pipeline.py` | PersonaPlex 远程 ASR + LLM |
| MCP 技能服务器 | `src/mcp/skill_mcp_server.py` | MCP JSON-RPC 服务器 |

## 对齐对象

- Go 中枢：`go-kernel/`
- ESP32 固件：`rak-esp/`
- 前端网关：`Xra-space/`
