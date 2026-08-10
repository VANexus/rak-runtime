# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

rak-runtime 是 RakTec / Xra AIoT 平台的 **纯认知推理引擎**（Python 3.11+）。零本地推理，全部依赖外部 API。

**三项目协同：**
- **go-kernel** (Go) — 神经网络层：SkillNet 技能检索、认知路由器、PA-HPS 调度、MQTT 设备通信
- **rak-runtime** (Python) — 认知推理层：LLM 决策、记忆系统、用户理解、元认知、主动性
- **rak-esp** (C) — 神经末梢：传感器、执行器、MQTT 命令执行

**核心原则：纯 Agent 工程。**
- ASR → PersonaPlex 远程 API（不装 whisper/torch）
- LLM → Anthropic API（不跑本地模型）
- 决策 → 语义缓存 + 元认知评估 + LLM 深思 + 规则兜底（不训练 LoRA）

**三层认知架构：**
- **Execution Layer** — 语义缓存、记忆检索、LLM 决策、规则引擎
- **User Model Layer** — 用户画像、意图推断、偏好学习、纠正历史
- **Meta-Cognitive Layer** — 置信度评估、策略选择、自我反思、主动告警

## Quick Start

```bash
cd rak-runtime
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -r requirements.txt
python runtime_server.py       # 启动 gRPC 服务器 :50051
```

**测试**（需先启动服务器）：
```bash
python test_server.py          # StreamASR 测试
python test_client.py          # Execute 文本测试
python test_e2e_full.py        # 端到端全链路测试
```

## Environment Variables

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_AUTH_TOKEN` | Anthropic API Key（LLM 必需） | — |
| `ANTHROPIC_BASE_URL` | API 代理地址 | `https://token-plan-cn.xiaomimimo.com/anthropic` |
| `ANTHROPIC_MODEL` | 模型名 | `mimo-v2.5-pro` |
| `RAG_POSTGRES_DSN` | PostgreSQL 连接串 | `postgresql://rak:rak@localhost:5432/rak_memory` |
| `MQTT_BROKER_HOST` | MQTT Broker 地址 | `localhost` |
| `MQTT_BROKER_PORT` | MQTT Broker 端口 | `1883` |
| `PERSONAPLEX_SERVER` | PersonaPlex WebSocket | `ws://8.129.26.180:8998/ws` |
| `RAK_PERSONA` | LLM 系统人格 | `你是 Rak，一个具身智能助手...` |

## Architecture

### 模块总览

```
src/core/
├── decision_engine.py      # 决策引擎（四层：缓存→元认知→LLM→规则）
├── agent_loop.py           # Agentic 内核（LangGraph ReAct 工具循环，深思路径）
├── prompt_engine.py        # 提示词引擎（动态系统提示词构建）
├── semantic_cache.py       # 语义缓存（高频查询 <1ms 返回）
├── learning_loop.py        # 学习闭环（执行反馈→经验沉淀→提示词优化）
├── world_model.py          # 世界模型（设备状态预测+异常检测）
├── user_model.py           # 用户模型（画像+意图推断+偏好学习+纠正历史）
├── meta_cognition.py       # 元认知（置信度评估+策略选择+自我反思）
├── proactive_engine.py     # 主动智能（异常告警+需求预测+自我改进）
├── self_model.py           # 自我认知（身份+能力+性格+关系+信念）
├── need_engine.py          # 需求引擎（基于系统信号的内部驱动力）
├── memory_stream.py        # 联想记忆流（随机激活→语义联想→洞察涌现）
├── emotion_state.py        # 情绪动力学（六维情绪+事件驱动+衰减）
├── inner_loop.py           # 内心循环（事件驱动，线程安全桥接到事件循环）
├── conversation_state.py   # 对话状态（话题追踪+发散思考+无缝衔接）
├── living_graph.py         # 活体知识图谱（扩散激活+赫布学习+自动建图）
├── memory_engine.py        # 三层认知记忆（工作/短期/长期 + 反思）
├── memory_persistence.py   # SQLite + JSON 持久化 + PrefChainPersistence 偏好链
├── memory_postgres.py      # PostgreSQL 后端（pgvector，偏好链可选）
├── memory_redis.py         # Redis 后端（TTL + Pub/Sub，偏好链可选）
├── agentic_rag.py          # Agentic RAG 多跳检索
├── audio_pipeline.py       # 音频管线（PersonaPlex 远程 ASR + LLM）
├── sleep_consolidation.py  # 睡眠整合（记忆巩固+遗忘+反思，15min 定时）
├── cog_rec.py              # CogRec 神经符号混合（LLM 教规则引擎）
├── action_memory.py        # 动作记忆（记录-重放，<1ms 绕过 LLM）
├── prompt_evolution.py     # 双流提示词进化（战术+战略）
├── safety_governance.py    # 安全治理（LLM 驱动的运行时安全）
├── policy_model.py         # 策略模型（基底神经节，反射弧，RAK_REFLEX）
├── outbound.py             # 出站通道（speak/alert/动作派发 → MQTT/A2A）
└── _utils.py               # 共享工具（原子 JSON 写入 + LLM 客户端工厂）

src/tools/
├── __init__.py             # MQTT 发布器导出（懒加载）
└── mqtt_publisher.py       # MQTT 出站（RakMessage v0 契约，RAK_OUTBOUND 门控）

src/mcp/
├── skill_mcp_server.py     # 手写 JSON-RPC 服务器（旧，保留对照）
└── fastmcp_server.py       # 大脑 MCP 服务器（官方 fastmcp，14 工具，stdio/HTTP）

src/a2a/
├── server.py               # A2A 服务器（标准 Agent2Agent v1.0，Agent Card + tasks/send + SSE）
├── client.py               # A2A 客户端（向外部 agent 派发任务）
└── device_agent.py         # 设备驱动适配器（RAK_DEVICE_AGENTS → A2A/MQTT）

src/prompts/                # 提示词模板（Jinja2）
├── config.yaml             # 共享配置（人设、动作列表、输出格式、规则）
├── decision.yaml           # 单动作决策模板
├── decompose.yaml          # 多动作分解模板
└── rag.yaml                # RAG 推理模板
```

### 四层决策架构（元认知增强）

```
请求 → ① 语义缓存（<1ms）→ 高置信度命中？→ 直接返回
                ↓ 未命中或低置信度
       ② 元认知评估 → 置信度打分 + 策略选择
                ↓ 高/中置信度
       ③ 用户纠正检查 + 记忆检索 + 用户画像 + 深思（agent 内核，降级单发 JSON）
          → 返回 + 缓存 + 记录到用户模型
                ↓ 失败
       ④ 规则引擎兜底 → 返回

       置信度低 → 返回 confirm 请求（主动询问用户，不硬答）
```

### 已接线状态（2026-08 重构后）

之前大量"已实现但未接线"的模块已激活，改动时注意：

- **心跳活着**：`runtime_server.serve()` 用单一常驻 asyncio loop（`run_forever()`）
  跑 InnerLoop + ProactiveEngine + SleepConsolidation 定时器。gRPC 线程事件经
  `InnerLoop.on_event` 的线程安全桥接到事件循环线程。
- **统一单例**：所有认知模块以 `decision_engine` 模块级 `_get_*()` 单例为唯一事实源，
  `runtime_server` 从中拉取，不再自建并行实例。`_wire_cognitive_graph()` 注入依赖。
- **深思 = LangGraph agent 内核**：`decide()` 深思路径走 `agent_loop.run_agent`（RAK_AGENT=1
  默认开），工具=只读认知工具+finalize；模型不支持工具调用时降级单发 JSON。
- **出站通道**：InnerLoop speak / ProactiveEngine alert 经 `outbound.py` → MQTT/A2A，
  `RAK_OUTBOUND=1` 才真发（默认只记日志，防污染线上 broker）。
- **持久化偏好链**：`PrefChainPersistence`，`RAG_POSTGRES_DSN`/`REDIS_URL` 设置时自动升级。
- **三协议共存**：gRPC(:50051) + A2A(:8000, `python -m src.a2a.server`) + MCP(stdio/HTTP)。

**已知注意**：
- `_init_lock` 是 RLock（`_get_*` 内部有嵌套 `_get_*` 调用，如 `_get_memory_stream`→`_get_memory_engine`）。
- 反射弧（PolicyModel）需 `RAK_REFLEX=1` 且 `total_updates>=20` 且置信度≥0.85 才触发，
  数据来自 `_record_feedback` 的在线学习。
- `A2AClient` 连接需要服务器 agent card 的 `protocol_binding` 为 SDK 枚举值（`JSONRPC`/`HTTP+JSON`），
  不是 spec URI。

### 学习闭环

```
执行 → 反馈记录 → 记忆存储 → 定期反思 → 洞察注入提示词 → 下次决策优化
                                              ↓
                                        语义缓存优化
```

### 生命体认知架构

```
┌─────────────────────────────────────────────────────┐
│            Inner Loop (心跳)                          │
│   持续运行：感知→情绪→需求→联想→决策→表达（或沉默）     │
├─────────────────────────────────────────────────────┤
│            Consciousness Layer                       │
│   SelfModel · EmotionEngine · NeedEngine             │
│   我是谁 · 我感受如何 · 我需要什么                     │
├─────────────────────────────────────────────────────┤
│            Memory Layer (Living Graph)                │
│   LivingGraph · MemoryStream · MemoryEngine          │
│   扩散激活 · 联想涌现 · 传统检索                      │
├─────────────────────────────────────────────────────┤
│            Meta-Cognitive Layer                       │
│   MetaCognition · ProactiveEngine                    │
│   我有多大把握 · 我应该主动做什么                      │
├─────────────────────────────────────────────────────┤
│            User Model Layer                           │
│   UserModel · 意图推断 · 偏好学习 · 纠正历史          │
├─────────────────────────────────────────────────────┤
│            Execution Layer                            │
│   SemanticCache · PromptEngine · LLM · RuleEngine    │
└─────────────────────────────────────────────────────┘
```

**InnerLoop** — 事件驱动的生命节奏（不是定时器）：
- 事件驱动（毫秒级）：有事发生 → 立刻更新情绪/需求 → 产生余韵
- 余韵（秒级）：事件后的涟漪效应 → 从 LivingGraph 联想 → 自然产生洞察
- 对话沉默中的发散思考：围绕当前话题在 LivingGraph 中扩散联想
- 无缝衔接：用户突然说话时，带着发散思考的上下文回复，保持口吻

**ConversationState** — 对话的活状态：
- 当前话题、对话风格、消息历史
- 沉默时围绕话题的发散思考
- 无缝衔接：被打断时带着思考上下文回复

**LivingGraph** — 活体知识图谱（替代 TopK 检索）：
- 节点带状态：entity/concept/event/skill/emotion
- 边带权重+时间衰减+激活计数
- 扩散激活：从一个节点开始，能量沿边传播，联想式记忆
- 自动建图：每次交互都在丰富图谱
- 赫布学习：一起激活的连接自动增强

**SelfModel** — Agent 的自我认知：
- 身份：我是 Rak，具身智能助手
- 能力：我会什么，我不会什么，我刚学会了什么
- 性格：温暖、谨慎、好奇（从交互中微调）
- 关系：我和用户的信任度（从纠正/反馈中学习）
- 信念：我信奉什么原则

**EmotionEngine** — 情绪动力学（不是演戏，是真实状态）：
- 六维连续变量：joy, fear, trust, surprise, anger, sadness
- 事件驱动：成功→喜悦↑，失败→悲伤↑，被纠正→惊讶↑
- 时间衰减：所有情绪趋向中性（约5分钟衰减一半）
- 行为影响：压力大→响应更简洁谨慎，自信→更果断

**NeedEngine** — 基于真实信号的内部驱动力：
- learning: 失败率高 → 需要学习
- stability: 纠正频率高 → 需要稳定
- exploration: 缓存命中率低 → 需要扩展知识
- rest: 连续运行时间长 → 需要整合记忆
- social: 长时间无交互 → 需要连接
- safety: 异常检测到问题 → 需要处理

**MemoryStream** — 联想记忆流：
- 后台持续运行，即使没有用户输入也在联想
- 随机激活近期记忆 → 语义联想 → 涌现洞察
- 洞察注入到决策中，让 Agent 有"灵光一现"的能力

**MetaCognition** — Agent 的自我意识：
- 置信度评估：缓存/记忆/LLM/规则多因子加权
- 策略选择：根据置信度和任务类型选择最优路径
- 不确定性处理：低置信度时主动询问，而非硬答
- 自我反思：分析决策成功率，调整策略权重

**ProactiveEngine** — 不再只是被动响应：
- 异常监控：持续检查设备状态，安全问题立即告警
- 需求预测：基于用户时间规律提前准备
- 用户可开关：不喜欢可以关闭主动性

### 与 go-kernel 的分工

| 功能 | go-kernel | rak-runtime |
|------|-----------|-------------|
| 技能检索 | SkillNet ANN + Hebbian 学习 | 不做（已由 go-kernel 处理） |
| 设备路由 | 认知路由器 ANN 匹配 | 不做 |
| 任务调度 | PA-HPS Q0/Q1/Q2 | 不做 |
| 深度推理 | 不做 | LLM + 记忆 + 提示词工程 |
| 记忆管理 | 不做 | 三层记忆 + 反思 + 睡眠整合 |
| 学习 | SkillNet 权重更新 | 经验沉淀 + 提示词优化 |
| 用户理解 | 不做 | 用户画像 + 意图推断 + 偏好学习 |
| 元认知 | 不做 | 置信度评估 + 策略选择 + 自我反思 |
| 主动性 | 不做 | 异常告警 + 需求预测 |

### gRPC Contracts

Proto：`protos/runtime.proto`，生成代码：`generated/`。修改 proto 后必须重新生成。

**语义契约**（详见 `docs/grpc-contracts.md`）：
- `version` 必须为 `"v0"`
- `trace_id` 全链路透传（gRPC → MQTT → WS）
- 返回动作必须在 `available_actions` 范围内
- `status=error` 时必须包含 `error_code` 和 `error_message`

**MVP 动作集**：`shake_head`, `wave_hand`, `lock_open`, `lock_close`, `move_forward`, `move_back`, `turn_left`, `turn_right`, `dance`, `nod`, `light_on`, `light_off`, `emergency_stop`, `idle`

## Coding Conventions

- **注释/docstring**：中文。变量/函数/类名：英文。
- **命名**：函数/变量 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`。
- **日志**：用 `logging`，不用 `print`。
- **延迟初始化**：模块级 `_get_*()` 懒加载，失败存 `False` 标记永久不可用。
- **降级原则**：所有外部依赖自动降级，永不因单组件故障崩溃。

## Important Notes

- **禁止引入** torch/whisper/sounddevice/numpy 等本地推理依赖
- `trace_id` 必须全链路透传，硬性不变量
- 返回动作必须在 `available_actions` 范围内
- 任何失败以 `status=error` 返回，不允许静默失败
- go-kernel SkillNet 已做技能路由，rak-runtime 不重复实现
- `src/models/action.py` 是空文件，动作数据全程用 plain dict
