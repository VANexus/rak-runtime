# 具身智能大脑实现计划（三阶段端到端）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 rak-runtime 从"决策服务"升级为"具身智能大脑"——修活全部未接线模块，落地 LangGraph agentic 内核 + 官方 MCP SDK + 标准 A2A v1.0 协议。

**Architecture:** 单一常驻 asyncio loop 承载心跳（InnerLoop/ProactiveEngine/SleepConsolidation）；决策引擎统一所有认知模块单例（消除 runtime_server 与 decision_engine 双实例）；`decide()` 的 LLM 深思步骤升级为 LangGraph ReAct agent（工具=认知模块）；对外暴露 MCP（FastMCP stdio/HTTP）与 A2A（官方 SDK）双协议。

**Tech Stack:** Python 3.14 / venv (.venv, uv 创建)；grpc 1.83 / anthropic / paho-mqtt / websockets / langgraph / langchain-core / langchain-anthropic / mcp / a2a-sdk 1.1.2 / fastapi / uvicorn / pytest 9。

## Global Constraints

- 注释/日志/UI 文案用简体中文；变量/函数 snake_case、类 PascalCase、常量 UPPER_SNAKE_CASE。
- 不引入本地推理依赖（torch/whisper/sounddevice/numpy）——框架/协议依赖不受限（用户已明确）。
- 降级原则：任何外部依赖失败 → 标记 `False` 永久不可用 → 系统继续运行，绝不崩。
- `trace_id` 全链路透传；返回动作必须在 `available_actions` 内；失败以 `status=error` 返回。
- 出站 MQTT/A2A 默认关闭（`RAK_OUTBOUND=1` 才启用），避免污染线上 broker。
- 每个任务结束必须：测试通过 + commit（中文 commit message）。

---

## Phase 0：修活大脑

### Task 0.1: 修复基线测试（11 个 stale 失败 → 全绿）

**Files:**
- Delete: `tests/test_asr_tool.py`（引用已删除的 `src.tools.asr_tool`）
- Modify: `tests/test_memory_engine.py`（`working_memory`→`working`；`MemoryEntry` 缺 id/layer）
- Modify: `src/core/decision_engine.py` `_validate_request`（空 action 且空 state → INVALID_REQUEST）

**Interfaces:**
- 无新接口。基线 `pytest tests/` 必须全绿。

- [ ] **Step 1: 删除死测试** `git rm tests/test_asr_tool.py`
- [ ] **Step 2: 修 memory_engine 测试**：`engine.working_memory` → `engine.working`；`MemoryEntry(...)` 补 `id=`, `layer=`
- [ ] **Step 3: 修 `_validate_request`**：加 `if not request.action and not request.state and not request.audio: invalid`
- [ ] **Step 4: 验证** `pytest tests/ -q` → 全绿
- [ ] **Step 5: Commit**

### Task 0.2: 修复 MemoryStream 联想空转

**Files:**
- Modify: `src/core/memory_stream.py:203-221`（`_get_random_recent_memory` 读 `_working_memory`/`_ltm`）
- Test: `tests/test_memory_stream.py`（新建）

**Interfaces:**
- Consumes: `CognitiveMemoryEngine.working.values()`、`.long_term.items`
- Produces: `_get_random_recent_memory()` 返回 str | None（真实记忆内容）

- [ ] **Step 1: 写失败测试**（注入记忆 → `_get_random_recent_memory` 非 None）
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**：读 `working.values()` 随机 + `long_term.items.values()` 按 last_accessed 排序取近 20 随机
- [ ] **Step 4: 通过 + Commit**

### Task 0.3: 修 mqtt_publisher（topic 对齐 RakMessage + 懒加载单例）

**Files:**
- Modify: `src/tools/mqtt_publisher.py`（`mqtt_publisher = MQTTPublisher()` 改为 `get_mqtt_publisher()` 懒加载；`publish_action` topic → `rak/{device_id}/cmd` + RakMessage v0 信封；新增 `publish_state`）

**Interfaces:**
- Produces: `get_mqtt_publisher() -> MQTTPublisher | None`；`MQTTPublisher.publish_action(device_id, action, params_json) -> bool`；`MQTTPublisher.publish_state(device_id, state_dict) -> bool`

- [ ] **Step 1: 写测试**（懒加载不连接；topic 格式）
- [ ] **Step 2: 实现**：`connect_async` 延迟到首次 publish；envelope `{version,type,trace_id,source,target,action,params,data,timestamp}`
- [ ] **Step 3: 验证 + Commit**

### Task 0.4: 统一认知图（消除双实例）+ 修 InnerLoop 依赖

**Files:**
- Modify: `src/core/decision_engine.py`（新增 `_get_world_model()`、`_get_proactive_engine()`、`_wire_cognitive_graph()`；`_get_inner_loop` 补 set_dependencies；`DecisionEngine.__init__` 调 `_wire_cognitive_graph`）
- Modify: `runtime_server.py` `_init_cognitive_modules`（全部改从 decision_engine 单例拉取，不再自建并行实例）

**Interfaces:**
- Produces: `decision_engine._get_world_model()`、`._get_proactive_engine()`、`._get_inner_loop()`（均已注依赖）、`._get_sleep_consolidation()`
- 图关系：inner_loop ← (emotion, need, world, self, living_graph, conversation)；proactive ← (world, user_model, learning_loop)

- [ ] **Step 1: 写测试**（`_get_inner_loop()` 的 `_emotion_engine` 非 None；`_get_proactive_engine()` 的 `_world_model` 非 None）
- [ ] **Step 2: 实现 `_get_world_model` + `_get_proactive_engine` + `_wire_cognitive_graph`**
- [ ] **Step 3: 改 runtime_server 用单例**
- [ ] **Step 4: 验证** pytest + 无双实例断言
- [ ] **Step 5: Commit**

### Task 0.5: 出站通道（speak/alert 回调 → MQTT/日志）

**Files:**
- Create: `src/core/outbound.py`（`get_outbound()` 单例；`speak(text)`、`alert(alert)`、`publish_action(...)`；`RAK_OUTBOUND=1` 才真发）
- Modify: `runtime_server.py`（`set_speak_callback`/`set_alert_callback` 接 outbound）

**Interfaces:**
- Produces: `src.core.outbound.get_outbound() -> Outbound`；`Outbound.speak(text: str)`；`Outbound.alert(alert: ProactiveAlert)`

- [ ] **Step 1: 写测试**（RAK_OUTBOUND=0 → 只记日志不 publish；=1 → 调 publish_action）
- [ ] **Step 2: 实现 outbound.py**
- [ ] **Step 3: runtime_server 接线**
- [ ] **Step 4: 验证 + Commit**

### Task 0.6: serve() 心跳事件循环 + Sleep 定时器

**Files:**
- Modify: `runtime_server.py` `serve()`（`run_forever()` 挂 inner_loop + proactive + sleep 定时器；`call_soon_threadsafe` 桥接 gRPC 线程事件；优雅关闭顺序：停心跳→存记忆→停 gRPC）
- Modify: `src/core/inner_loop.py`（`on_event` 线程安全：非 loop 线程 → `loop.call_soon_threadsafe`）

**Interfaces:**
- Produces: `serve()` 常驻运行；InnerLoop 可在 gRPC 线程安全触发
- Consumes: `InnerLoop.start/stop`、`ProactiveEngine.start/stop`、`SleepConsolidation.consolidate()`

- [ ] **Step 1: inner_loop 线程安全桥**（`start()` 存 loop；`on_event` 判断线程）
- [ ] **Step 2: serve() 重写**
- [ ] **Step 3: 集成验证**（启动 server，发 Execute，断言 `get_cognitive_stats` 心跳指标增长）
- [ ] **Step 4: Commit**

---

## Phase 1：全面接线

### Task 1.1: FastMCP 服务器（官方 mcp SDK）

**Files:**
- Create: `src/mcp/fastmcp_server.py`（FastMCP，21 工具 + 资源，从 decision_engine 单例拉能力；`main()` stdio + `--http`）
- Modify: `pyproject.toml`/`requirements.txt`（锁定新依赖版本）

**Interfaces:**
- Produces: `run_stdio()`、`run_http(port)`；工具名与现有 SkillMCPServer 对齐（execute_action/search_memory/.../get_narrative）

- [ ] **Step 1: 写测试**（FastMCP 工具注册数量 + 一个工具调用走 decision_engine）
- [ ] **Step 2: 实现 fastmcp_server.py**
- [ ] **Step 3: 验证** stdio 启动 + `tools/list`
- [ ] **Step 4: Commit**

### Task 1.2: PolicyModel 反射弧

**Files:**
- Modify: `src/core/decision_engine.py`（`_get_policy_model()` + decide() 在 LLM 前查反射弧，env `RAK_REFLEX=1`）
- Test: `tests/test_policy_reflex.py`

**Interfaces:**
- Produces: `_get_policy_model() -> PolicyModelManager`；反射命中返回 `{"action","source":"reflex"}`
- Consumes: `PolicyModel.decide(StateVector)`、`.update(state, action_id, reward)`

- [ ] **Step 1: 写测试**（reflex 命中路径 + 未命中走正常路径）
- [ ] **Step 2: 实现**
- [ ] **Step 3: 验证 + Commit**

### Task 1.3: AgenticRAG 进记忆上下文

**Files:**
- Modify: `src/core/decision_engine.py`（`_get_agentic_rag()`；`_build_memory_context` 在初次检索不足时多跳）

**Interfaces:**
- Produces: `_get_agentic_rag() -> AgenticRAGWithLLM`（retrieve_fn=memory.recall）
- Consumes: `AgenticRAG.query(question, top_k) -> AgenticRAGResult`

- [ ] **Step 1: 写测试**（证据不足触发多跳；结果注入 context）
- [ ] **Step 2: 实现**
- [ ] **Step 3: 验证 + Commit**

### Task 1.4: Postgres/Redis 偏好链

**Files:**
- Modify: `src/core/decision_engine.py` `_get_memory_engine`（按 `RAG_POSTGRES_DSN`/`REDIS_URL` 升级）
- Test: `tests/test_persistence_chain.py`

**Interfaces:**
- Consumes: `HybridLongTermBackend`（postgres）、`HybridMemoryBackend`（redis）
- Produces: `_get_memory_engine()` 返回 CognitiveMemoryEngine（backend 由 env 决定）

- [ ] **Step 1: 写测试**（无 env → SQLite/JSON；设 env → 尝试 Postgres，失败降级不崩）
- [ ] **Step 2: 实现**
- [ ] **Step 3: 验证 + Commit**

---

## Phase 2：agentic 内核 + A2A

### Task 2.1: LangGraph agent 内核

**Files:**
- Create: `src/core/agent_loop.py`（`create_react_agent`；工具=LangChain `@tool` 包认知模块；`run_agent(query, available_actions, context) -> dict`）
- Test: `tests/test_agent_loop.py`（mock LLM：模型不支持工具调用 → 返回 JSON 降级）

**Interfaces:**
- Produces: `run_agent(query, available_actions, memory_context, device_state) -> dict`（含 action/answer/轨迹）
- Consumes: `ChatAnthropic(base_url=ANTHROPIC_BASE_URL)`；`get_outbound()`；decision_engine 单例

- [ ] **Step 1: 写测试**（降级链 + 工具调用轨迹）
- [ ] **Step 2: 实现 agent_loop.py**
- [ ] **Step 3: decide() 深思步骤接入 + 降级链**
- [ ] **Step 4: 验证 + Commit**

### Task 2.2: A2A Server（官方 SDK）

**Files:**
- Create: `src/a2a/server.py`（Agent Card + `A2AServer`/FastAPI；`tasks/send`→decide()；SSE 流式）
- Create: `src/a2a/__init__.py`
- Test: `tests/test_a2a_server.py`（`A2AClient` send → COMPLETED + artifact）

**Interfaces:**
- Produces: `create_app() -> FastAPI`；`RAK_A2A_PORT`（默认 8000）
- Consumes: `a2a.types`（AgentCard/AgentSkill/Message/Task/Part）、`a2a.server.A2AServer`、`a2a.client.A2AClient`

- [ ] **Step 1: 写测试**（client→server 往返）
- [ ] **Step 2: 实现 server.py**
- [ ] **Step 3: 验证 + Commit**

### Task 2.3: DeviceDriverAgent 适配器 + A2A Client

**Files:**
- Create: `src/a2a/device_agent.py`（把 go-kernel gRPC/MQTT 包成 A2A 可寻址 agent；`dispatch_action`）
- Create: `src/a2a/client.py`（`A2AClient` 封装：大脑主动派发任务）
- Modify: `src/core/outbound.py`（`RAK_OUTBOUND=1` 时动作改走 A2A dispatch）

**Interfaces:**
- Produces: `dispatch_action(device_id, action, params) -> task_id`；`get_device_agents() -> [AgentCard]`
- Consumes: `a2a.client.A2AClient`；`mqtt_publisher`

- [ ] **Step 1: 写测试**（dispatch 到 mock A2A server）
- [ ] **Step 2: 实现 device_agent.py + client.py**
- [ ] **Step 3: outbound 接 A2A**
- [ ] **Step 4: 验证 + Commit**

### Task 2.4: 端到端集成验证 + 文档收尾

- [ ] **Step 1: 全量测试** `pytest tests/ -q` 全绿
- [ ] **Step 2: 冒烟**：启动 server → MCP stdio 连 → A2A client 发 task → 心跳指标
- [ ] **Step 3: 更新 CLAUDE.md/README**（新模块、新 env、新协议）
- [ ] **Step 4: Commit**
