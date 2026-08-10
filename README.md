# rak-runtime

> RakTec / Xra AIoT 平台的活体认知推理引擎 —— 具身智能决策核心

## 定位

rak-runtime 是具身 AI 系统的**认知推理引擎**，负责：

1. **认知决策**：LLM 驱动的自然语言 → 原子动作分解（15 步决策管线）
2. **记忆系统**：三层认知记忆 + 活体知识图谱 + 联想记忆流
3. **元认知**：置信度评估、策略选择、自我反思
4. **生命体架构**：情绪动力学、需求引擎、内心循环、自我认知
5. **学习闭环**：CogRec（LLM 教规则）、ActionMemory（记录-重放）、PromptEvolution（双流进化）

**核心原则：纯 Agent 工程，零本地推理，优雅降级。**

## 五层认知架构

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

## 核心特性

### 🧠 15 步决策管线

`DecisionEngine.decide()` 完整流程：

1. 复合命令检测（多动作分解）
2. 对话状态记录
3. 语义缓存查找（<1ms）+ 元认知置信度检查
4. CogRec 规则匹配（<1ms）
5. ActionMemory 重放（<1ms）
6. 用户纠正历史检查
7. 用户画像意图推断
8. 上下文组装（SelfModel + Emotion + Needs + Memory + InnerLoop + ConversationState）
9. 双通道记忆检索（LivingGraph 扩散激活 + 传统 TopK）
10. PromptEvolution 指南注入
11. 系统提示词构建
12. LLM 深思（~1s）+ 流式提前返回
13. 元认知置信度评估 + 策略选择
14. 安全治理检查
15. 缓存 + 记忆 + 学习 + 图谱 + 规则 + 反馈全面更新

### 🔗 CogRec 神经符号混合

LLM 成功决策自动提取为规则引擎规则。规则随时间累积，LLM 调用比例逐步降低。纠正规则获得最高置信度（0.95）。

### 📝 ActionMemory 记录-重放

记录完整决策轨迹，相似查询直接重放（<1ms）绕过 LLM。LLM 评估模糊匹配是否适合重放。

### 🔄 PromptEvolution 双流进化

- **战术流**：短期纠正，成功 N 次后自动过期
- **战略流**：长期原则，永不过期

### 🛡️ SafetyGovernance 安全治理

LLM 驱动的运行时安全判断。唯一硬约束：`emergency_stop` 始终允许。所有其他安全判断上下文感知。

### 💭 情绪动力学

六维连续变量（joy/fear/trust/surprise/anger/sadness），事件驱动更新，~5 分钟半衰期。影响行为：压力大→更简洁谨慎，自信→更果断。

### 🎯 元认知

置信度评估（缓存 0.30 + 记忆 0.15 + LLM 0.40 + 规则 0.15），策略选择（CACHE/RULE/LLM/HYBRID/ASK_USER）。低置信度时主动询问而非硬答。

### 🌊 LivingGraph 活体知识图谱

节点带状态（entity/concept/event/skill/emotion），边带权重+时间衰减。扩散激活替代 TopK 检索，赫布学习自动增强共激活连接。

### 💤 睡眠整合

短期→长期记忆迁移、低显著性遗忘、批量反思、相似记忆压缩。

## 项目结构

```
rak-runtime/
├── runtime_server.py               # gRPC 服务器入口 (:50051) + 心跳事件循环
├── src/
│   ├── core/                       # 28+ 认知模块
│   │   ├── agent_loop.py           # ★ Agentic 内核（LangGraph ReAct 工具循环）
│   │   ├── outbound.py             # ★ 出站通道（说话/告警/动作派发）
│   │   ├── decision_engine.py      # 决策引擎（中央调度器）
│   │   ├── prompt_engine.py        # 提示词引擎
│   │   ├── semantic_cache.py       # 语义缓存
│   │   ├── learning_loop.py        # 学习闭环
│   │   ├── memory_engine.py        # 三层认知记忆
│   │   ├── memory_persistence.py   # SQLite + JSON 持久化 + PrefChainPersistence
│   │   ├── memory_postgres.py      # PostgreSQL 后端（偏好链可选）
│   │   ├── memory_redis.py         # Redis 后端（偏好链可选）
│   │   ├── memory_stream.py        # 联想记忆流
│   │   ├── living_graph.py         # 活体知识图谱
│   │   ├── sleep_consolidation.py  # 睡眠整合
│   │   ├── agentic_rag.py          # Agentic RAG 多跳检索
│   │   ├── audio_pipeline.py       # 双管线音频处理
│   │   ├── world_model.py          # 世界模型
│   │   ├── user_model.py           # 用户模型
│   │   ├── meta_cognition.py       # 元认知
│   │   ├── proactive_engine.py     # 主动智能
│   │   ├── self_model.py           # 自我认知
│   │   ├── need_engine.py          # 需求引擎
│   │   ├── emotion_state.py        # 情绪动力学
│   │   ├── inner_loop.py           # 内心循环（线程安全事件桥接）
│   │   ├── conversation_state.py   # 对话状态
│   │   ├── cog_rec.py              # CogRec 神经符号混合
│   │   ├── action_memory.py        # 动作记忆
│   │   ├── prompt_evolution.py     # 双流提示词进化
│   │   ├── safety_governance.py    # 安全治理
│   │   ├── policy_model.py         # 策略模型（基底神经节，反射弧）
│   │   └── _utils.py               # 共享工具（LLM 客户端工厂）
│   ├── a2a/                        # ★ A2A 协议层（标准 Agent2Agent v1.0）
│   │   ├── server.py               #   Agent Card + tasks/send + SSE
│   │   ├── client.py               #   向外部 agent 派发任务
│   │   └── device_agent.py         #   设备驱动适配器（A2A→MQTT 兜底）
│   ├── tools/
│   │   └── mqtt_publisher.py       # MQTT 出站（RakMessage v0 契约）
│   ├── mcp/
│   │   └── fastmcp_server.py       # ★ 大脑 MCP 服务器（fastmcp，14 工具）
│   └── prompts/                    # 提示词模板（Jinja2）
├── protos/
│   └── runtime.proto               # gRPC 协议定义
├── generated/                      # 生成的 gRPC 代码
├── tests/                          # 单元测试 + 集成测试
└── docs/                           # 文档目录
```

## 快速开始

```bash
git clone https://github.com/VANexus/rak-runtime.git
cd rak-runtime
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -r requirements.txt
python runtime_server.py       # 启动 gRPC 服务器 :50051
```

### 测试

```bash
pytest tests/                        # 运行所有单元测试
pytest tests/test_meta_cognition.py  # 运行特定测试
python test_server.py                # StreamASR 集成测试
python test_client.py                # Execute 文本集成测试
python test_e2e_full.py              # 端到端全链路测试
```

## gRPC 接口

- **RuntimeService.Execute**：单动作决策（输入状态/动作，返回动作 + 参数）
- **RuntimeService.StreamASR**：流式语音识别

详见 [docs/grpc-contracts.md](./docs/grpc-contracts.md)

## 文档

- [文档索引](./docs/INDEX.md)
- [架构设计](./docs/architecture.md)
- [Agent 开发指南](./AGENTS.md)
- [Claude Code 指南](./CLAUDE.md)
- [gRPC 契约](./docs/grpc-contracts.md)
- [参考文献](./docs/references.md)

## MVP 动作集

`shake_head` · `wave_hand` · `lock_open` · `lock_close` · `move_forward` · `move_back` · `turn_left` · `turn_right` · `dance` · `nod` · `light_on` · `light_off` · `emergency_stop` · `idle`

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_AUTH_TOKEN` | Anthropic API Key | — |
| `ANTHROPIC_BASE_URL` | API 代理地址 | `https://token-plan-cn.xiaomimimo.com/anthropic` |
| `ANTHROPIC_MODEL` | 模型名 | `mimo-v2.5-pro` |
| `ANTHROPIC_AUTH_SCHEME` | 鉴权方式：`api_key`(x-api-key) / `bearer`(Authorization) | `api_key` |
| `RAK_AGENT` | 启用 LangGraph agent 内核（深思路径） | `1` |
| `RAK_REFLEX` | 启用基底神经节反射弧（需训练） | `0` |
| `RAK_AGENTIC_RAG` | 启用 Agentic RAG 多跳检索 | `0` |
| `RAK_OUTBOUND` | 启用出站通道（MQTT/A2A 派发） | `0` |
| `RAK_DEVICE_AGENTS` | 设备 agent JSON 列表（A2A 派发目标） | `[]` |
| `RAK_A2A_PORT` | A2A 服务器端口 | `8000` |
| `RAG_POSTGRES_DSN` | PostgreSQL 连接串（长期记忆偏好链） | — |
| `REDIS_URL` | Redis 连接串（短期记忆偏好链） | — |
| `MQTT_BROKER_HOST` | MQTT Broker 地址 | `localhost` |
| `MQTT_BROKER_PORT` | MQTT Broker 端口 | `1883` |
| `PERSONAPLEX_SERVER` | PersonaPlex WebSocket | `ws://8.129.26.180:8998/ws` |

## 多协议接入

大脑支持三种接入方式，可同时运行：

```bash
python runtime_server.py                    # gRPC 决策服务 + 心跳 (:50051)
python -m src.a2a.server                    # A2A 标准协议 (:8000, Agent Card)
python -m src.mcp.fastmcp_server --http 8001  # MCP 服务器（HTTP，或默认 stdio）
```

- **gRPC**：go-kernel 调 `Execute`，返回动作 + 语音回复（原有链路）
- **A2A**：任何 A2A 客户端/硬件驱动 agent 可派发任务（`tasks/send`），大脑返回动作 artifact
- **MCP**：Claude Code 等 MCP 客户端可发现并调用大脑的 14 个"神经元"工具

## 对齐契约

- gRPC proto：[protos/runtime.proto](./protos/runtime.proto)
- gRPC 语义：[docs/grpc-contracts.md](./docs/grpc-contracts.md)
- 与 go-kernel 分工：go-kernel 负责 SkillNet/认知路由/PA-HPS，rak-runtime 负责深度推理/记忆/元认知
