# AGENTS.md — rak-runtime 开发者指南

## 项目概述

rak-runtime 是 RakTec / Xra AIoT 平台的 **活体认知推理引擎**（Python 3.11+）。五层认知架构，28 个模块，零本地推理，全部依赖外部 API。

**核心原则：纯 Agent 工程，优雅降级。**
- ASR → PersonaPlex 远程 API
- LLM → Anthropic API（或兼容代理）
- 不依赖 torch/whisper/sounddevice 等本地推理库
- 所有模块使用 `_get_*()` 懒初始化，失败标记 `False`，系统继续运行

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
├── core/                           # 核心认知引擎（28 个模块）
│   ├── decision_engine.py          # 决策引擎（15 步决策管线，中央调度器）
│   ├── prompt_engine.py            # 提示词引擎（动态系统提示词构建）
│   ├── semantic_cache.py           # 语义缓存（<1ms 精确匹配，~5ms 语义匹配）
│   ├── learning_loop.py            # 学习闭环（执行反馈→经验沉淀→提示词优化）
│   ├── memory_engine.py            # 三层认知记忆（工作/短期/长期 + 反思）
│   ├── memory_persistence.py       # SQLite + JSON 文件持久化
│   ├── memory_postgres.py          # PostgreSQL 后端（pgvector）
│   ├── memory_redis.py             # Redis 后端（TTL + Pub/Sub）
│   ├── memory_stream.py            # 联想记忆流（随机激活→语义联想→洞察涌现）
│   ├── living_graph.py             # 活体知识图谱（扩散激活+赫布学习+自动建图）
│   ├── sleep_consolidation.py      # 睡眠整合（记忆巩固+遗忘+反思）
│   ├── agentic_rag.py              # Agentic RAG 多跳检索
│   ├── audio_pipeline.py           # 双管线音频处理（PersonaPlex + LLM）
│   ├── world_model.py              # 世界模型（设备状态预测+异常检测）
│   ├── user_model.py               # 用户模型（画像+意图推断+偏好学习+纠正历史）
│   ├── meta_cognition.py           # 元认知（置信度评估+策略选择+自我反思）
│   ├── proactive_engine.py         # 主动智能（异常告警+需求预测+自我改进）
│   ├── self_model.py               # 自我认知（身份+能力+性格+关系+信念）
│   ├── need_engine.py              # 需求引擎（基于系统信号的内部驱动力）
│   ├── emotion_state.py            # 情绪动力学（六维情绪+事件驱动+衰减）
│   ├── inner_loop.py               # 内心循环（事件驱动心跳：感知→联想→决策→表达）
│   ├── conversation_state.py       # 对话状态（话题追踪+发散思考+无缝衔接）
│   ├── cog_rec.py                  # CogRec 神经符号混合（LLM 教规则引擎）
│   ├── action_memory.py            # 动作记忆（记录-重放，<1ms 绕过 LLM）
│   ├── prompt_evolution.py         # 双流提示词进化（战术+战略）
│   ├── safety_governance.py        # 安全治理（LLM 驱动的运行时安全）
│   ├── policy_model.py             # 策略模型（基底神经节，在线学习）
│   └── _utils.py                   # 共享工具（原子 JSON 写入）
├── tools/                          # 工具类
│   └── __init__.py                 # MQTTPublisher 导出
├── mcp/                            # MCP 协议
│   └── skill_mcp_server.py         # MCP 技能服务器
└── prompts/                        # 提示词模板
    ├── config.yaml                 # 共享配置（人设、动作列表、输出格式、规则）
    ├── decision.yaml               # 单动作决策模板
    ├── decompose.yaml              # 多动作分解模板
    └── rag.yaml                    # RAG 推理模板
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

- LLM 不可用 → 规则引擎 / CogRec 规则 / ActionMemory 重放
- PersonaPlex 不可用 → ASR 功能禁用
- PostgreSQL 不可用 → SQLite
- Redis 不可用 → JSON 文件
- 任何认知模块初始化失败 → 标记 `False`，系统继续

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

## 五层认知架构

```
Inner Loop (心跳)          — 持续运行：感知→情绪→需求→联想→决策→表达（或沉默）
Consciousness Layer        — SelfModel + EmotionEngine + NeedEngine
Memory Layer (LivingGraph) — LivingGraph + MemoryStream + MemoryEngine（扩散激活 + 联想涌现）
Meta-Cognitive Layer       — MetaCognition + ProactiveEngine（置信度 + 主动性）
User Model Layer           — UserModel + 意图推断 + 偏好学习
Execution Layer            — SemanticCache + PromptEngine + LLM + RuleEngine
```

## 15 步决策流程

1. 复合命令检测（多动作分解）
2. 对话状态记录
3. 语义缓存查找（<1ms）+ 元认知置信度检查
4. CogRec 规则匹配（<1ms）
5. ActionMemory 重放（<1ms）
6. 用户纠正历史检查
7. 用户画像意图推断
8. SelfModel + Emotion + Needs + MemoryStream 洞察 + InnerLoop 叙事 + ConversationState 上下文组装
9. 双通道记忆检索（LivingGraph 扩散激活 + 传统 TopK）
10. PromptEvolution 指南注入
11. 系统提示词构建（PromptEngine）
12. LLM 深思（~1s）+ 流式提前返回优化
13. 元认知置信度评估 + 策略选择
14. 安全治理检查
15. 缓存存储 + 记忆记录 + 学习循环 + 用户模型更新 + LivingGraph 自动建图 + CogRec 学习 + ActionMemory 记录 + PromptEvolution 反馈 + InnerLoop 事件

## gRPC 接口

- **RuntimeService.Execute**：`ActionRequest → ActionResponse`
- **RuntimeService.StreamASR**：流式语音识别（通过 PersonaPlex）

Proto 定义在 `protos/runtime.proto`，修改后需重新生成 `generated/`。

## 测试

```bash
pytest tests/                        # 运行所有单元测试
pytest tests/test_meta_cognition.py  # 运行特定测试
python test_server.py                # StreamASR 集成测试
python test_client.py                # Execute 文本集成测试
python test_e2e_full.py              # 端到端全链路测试
```

单元测试不需要启动服务器，集成测试需要先启动：`python runtime_server.py`

## 注意事项

- 不要引入 torch/whisper/sounddevice 等本地推理依赖
- `trace_id` 必须全链路透传（gRPC → MQTT → WS）
- 返回动作必须在 `available_actions` 范围内
- 任何失败都以 `status=error` 返回，不允许静默失败
- 修改 proto 后必须重新生成 `generated/` 目录
- `src/models/action.py` 是空文件，动作数据全程用 plain dict
- 提示词模板在 `prompts/` 目录，使用 Jinja2 语法
