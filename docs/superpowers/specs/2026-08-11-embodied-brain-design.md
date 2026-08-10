# 具身智能大脑重构设计（rak-runtime 接线 + 升级）

- **日期**：2026-08-11
- **范围**：rak-runtime 从"决策服务"升级为"具身智能大脑"——修复全部"已实现但未接线"模块，落地 agentic 内核 + 标准 A2A 协议 + 生命感心跳。
- **用户确认的方向**：全部三阶段推进；A2A 用官方 SDK；优先使用成熟库（LangGraph/LangChain 等），不手搓基础组件。

---

## 1. 愿景定位

rak-runtime 不是纯编码工具（Claude Code/OpenCode），但**内核要像它们**：一个拥有工具调用循环的 agent 内核，LLM 能自主调用"神经元"、观察结果、迭代直到产出动作。它也不是通用个人管家（OpenClaw/Hermes），但**能力要像它们**：跨时间持久、主动、多渠道、由记忆驱动。它的核心定位是**具身智能大脑**：通过 A2A（Agent2Agent，v1.0）等协议与硬件驱动双向通信，以仿生人思维模式（心跳、情绪、需求、联想、游走）实现生命感。

一句话：**一个会呼吸、会主动、能伸手摸世界的 agent 内核。**

## 2. 现状诊断（已 grep 验证）

当前系统是"决策服务"，不是大脑：go-kernel 单向 gRPC 调 `Execute` → 返回一个动作。28 个认知模块中大量 dormant。

| 组 | 问题 | 位置 |
|---|---|---|
| A. 心跳死了 | `serve()` 用 `run_until_complete(inner_loop.start())`，loop 跑完即停，`_idle_loop` 成孤儿；`ProactiveEngine.start()` 只在从未 await 的 `start_proactive()` 里 | `runtime_server.py:381,320` |
| A. 无出站通道 | `set_speak_callback`/`set_alert_callback` 全项目无人调用，大脑无法主动说话/告警 | `inner_loop.py:101`, `proactive_engine.py:94` |
| B. 已知 bug | `StreamASR` 传 2 参调 `process_audio`（需 4 参）且不 await async 协程 | `runtime_server.py:245` |
| B. 已知 bug | `MemoryStream._get_random_recent_memory()` 读 `_working_memory`/`_ltm`（不存在），联想流永远空转 | `memory_stream.py:207` |
| B. 死测试 | `tests/test_asr_tool.py` 引用已删除的 `src.tools.asr_tool`，pytest 必挂 | `tests/test_asr_tool.py` |
| C. 完全 dormant | `policy_model.py`、`agentic_rag.py`、`sleep_consolidation.py`、`memory_postgres.py`、`memory_redis.py`、`skill_mcp_server.py`、`mqtt_publisher.py` 零引用 | 全部 |
| D. 半接线 | WorldModel 更新了但 `predict_next_state`/`detect_anomaly` 不进决策循环；`safety.update_device_state` 只在测试调用 | `world_model.py`, `safety_governance.py` |

## 3. 目标架构

```
┌────────────────────────── rak-runtime 大脑 ──────────────────────────┐
│                                                                      │
│  ┌─────────────────── Agentic Kernel（LangGraph）──────────────────┐ │
│  │  ReAct 循环：LLM 深思 ←→ 调工具(神经元) ←→ 观察 ←→ 直到产出动作    │ │
│  │  工具 = LangChain @tool（执行动作/查记忆/查设备/记反馈/反思/情绪）  │ │
│  └───────────┬─────────────────────────────┬───────────────────────┘ │
│              │                             │                          │
│  ┌───────────┴──────┐        ┌─────────────┴─────────┐               │
│  │ 认知层（28 模块） │        │ 心跳层（激活）          │               │
│  │ 记忆/元认知/用户/ │        │ InnerLoop · Proactive  │               │
│  │ 世界模型/学习/安全 │        │ SleepConsolidation     │               │
│  └───────────┬──────┘        └─────────────┬─────────┘               │
│              │                             │ speak/alert 出站         │
│  ┌───────────┴─────────────────────────────┴─────────┐               │
│  │             协议层（多传输共存）                     │               │
│  │  gRPC :50051（现有）· MCP stdio/HTTP · A2A HTTP     │               │
│  │  Agent Card · tasks/send · SSE（A2A v1.0 官方 SDK）  │               │
│  └───────────┬─────────────────────────────────────────┘               │
└──────────────┼────────────────────────────────────────────────────────┘
               │ A2A over HTTP / gRPC / MQTT
      ┌────────┴──────────────┐
      │  硬件驱动 Agent 层      │
      │ go-kernel · rak-esp ·  │
      │ 机器人 · MQTT 设备      │
      └───────────────────────┘
```

**核心数据流（双向）**：
- **入站**：硬件状态/事件（MQTT、A2A task）→ 认知层更新（WorldModel/情绪/需求）→ agent 内核决策 → 动作。
- **出站**：决策动作 / InnerLoop 主动表达 / ProactiveEngine 告警 → A2A task 派发到设备 agent，或 MQTT RakMessage，或 go-kernel 回调。

## 4. 关键技术决策

### D1. Agentic 内核 = LangGraph `create_react_agent`，不手写循环
- 模型绑定 `langchain-anthropic` 的 `ChatAnthropic(base_url=代理, model=mimo-v2.5-pro)`。
- 工具 = LangChain `@tool` 直接包认知模块方法（execute_action/search_memory/query_device/record_feedback/reflect/get_emotion/get_needs/diffuse_memory），共 8-10 个，语义与现有 MCP 21 工具对齐。
- 决策引擎 `decide()` 的"LLM 深思"步骤升级为调用 agent loop；快速通道（缓存/CogRec/ActionMemory/规则）保持不动。
- **降级链**：agent loop 失败/模型不支持工具调用 → 现有 `_llm_decide` 单发 JSON → 规则引擎。原有兜底语义不变。

### D2. MCP 层 = 官方 `mcp` SDK（FastMCP），替换手写 JSON-RPC
- 用 `FastMCP` 重写 `skill_mcp_server.py`：`@mcp.tool()` 装饰器声明 21 个工具 + 资源，获得 stdio 与 streamable HTTP 双传输（零手写帧）。streamable HTTP 默认端口 `:8001`（env `RAK_MCP_PORT`）。
- 外部 MCP 客户端（Claude Code 等）可直连大脑；LangGraph 内核在进程内直接用 LangChain 工具（不经 MCP 往返，避免自连自的开销与复杂度）。
- 现有手写 `SkillMCPServer`：Phase 1 期间保留供对照，FastMCP 版本验证通过后**删除**（它当前零引用，删除无回归风险）。

### D3. A2A = 官方 `a2a` SDK（v1.0 规范）
- 大脑作为 A2A Server：Agent Card（skills = 大脑能力清单）、`tasks/send`、`tasks/get`、`tasks/cancel`、SSE 流式任务事件、`INPUT_REQUIRED`/`AUTH_REQUIRED` 状态支持。默认监听 `:8000`（env `RAK_A2A_PORT`）。
- `DeviceDriverAgent` 适配器：把 go-kernel（gRPC）和 MQTT 设备包装成 A2A 可寻址的 agent，大脑通过 `A2AClient.tasks/send` 派发动作。
- FastAPI + uvicorn 承载（a2a SDK 官方集成）。

### D4. 出站通道 = speak/alert 回调 → MQTT（RakMessage v0）+ A2A 派发，env 开关默认关
- `set_speak_callback`（InnerLoop）与 `set_alert_callback`（ProactiveEngine）接入真实发布器。
- 修正 `mqtt_publisher.publish_action` 的 topic：`robot/{target}/control` → `rak/{device_id}/{cmd,state,audio}`（对齐 go-kernel 契约），payload 用 RakMessage v0 信封。
- `RAK_OUTBOUND=1` 才启用，避免污染线上 broker。

### D5. 单一常驻 asyncio loop
- `serve()`：`loop.run_forever()`，同一 loop 挂 InnerLoop、ProactiveEngine、SleepConsolidation 定时器、音频管线。
- gRPC 线程池事件经 `loop.call_soon_threadsafe` 桥接（修 StreamASR 同步 handler 调 async 的问题）。
- 优雅关闭：先停心跳/主动性/睡眠，再存记忆，再停 gRPC。

### D6. 持久化偏好链 Postgres → Redis → SQLite，env 启用
- `_get_memory_engine` 按 `RAG_POSTGRES_DSN` / `REDIS_URL` 升级，无配置时保持现有 SQLite/JSON。
- 复用已写好的 `HybridLongTermBackend` / `HybridMemoryBackend`，不改表结构。

### D7. 心跳层接线修复
- `memory_stream._get_random_recent_memory` 改为读 `working.values()` 与 `long_term.items.values()`。
- WorldModel 的 `detect_all_anomalies` 由 ProactiveEngine 实际调用（已接线，启动即生效）；`safety.update_device_state` 在 Execute 更新世界模型时同步调用。

## 5. 分阶段落地

> 每阶段 = 独立 spec/plan/实现/验证。前序阶段完成并验证后才进入下一阶段。

### Phase 0「修活大脑」（~7 文件，安全小 diff）
1. `runtime_server.py`：修 `serve()` 事件循环（D5）+ 桥接线程事件 + 启动 ProactiveEngine + 挂 Sleep 定时器
2. `runtime_server.py`：修 StreamASR 签名 + async 调用（D5）
3. `memory_stream.py`：修 `_get_random_recent_memory`（D7）
4. `mqtt_publisher.py`：修 topic + 出站回调接线（D4）
5. `runtime_server.py`/`inner_loop.py`/`proactive_engine.py`：speak/alert 回调注入
6. 删 `tests/test_asr_tool.py`
7. `safety_governance`/world model 闭环（D7）

**验证**：`pytest tests/` 全绿；`life_sense_benchmark.py` 心跳/情绪/需求指标非零；gRPC 集成测试（text + audio 路径）。

### Phase 1「全面接线」（~8 文件）
1. `src/mcp/fastmcp_server.py`：FastMCP 重写（D2），修现有两处错（`semantic_cache` 未初始化、`on_execution_result`→`on_decision`）
2. PolicyModel 反射弧：`decide()` LLM 前加"基底神经节"快速通道，env `RAK_REFLEX=1`
3. AgenticRAG 进 `_build_memory_context`：记忆不足时多跳检索
4. SleepConsolidation 定时触发 + `restore_state`
5. Postgres/Redis 偏好链（D6）

**验证**：pytest；MCP 客户端连通（stdio）；反射弧延迟对比（<10ms 目标）；持久化升级路径 smoke test。

### Phase 2「agentic 内核 + A2A」（~10 文件，分两个子 spec）
**2a. Agentic 内核**
1. `src/core/agent_loop.py`：LangGraph `create_react_agent` + LangChain 工具（D1）
2. `decide()` 深思步骤接入 agent loop + 降级链
**2b. A2A 层**
3. `src/a2a/server.py`：Agent Card + `A2AServer`（FastAPI）
4. `src/a2a/device_agent.py`：DeviceDriverAgent 适配器（gRPC/MQTT → A2A）
5. `src/a2a/client.py`：大脑主动派发任务
6. 出站动作改走 A2A 或 MQTT（env 选择）

**验证**：官方 `A2AClient` 连通 + task 生命周期测试（submitted→working→completed）；agent loop 工具调用轨迹记录；模型不支持工具调用时降级回 JSON 路径。

## 6. 依赖清单（新增）

| 阶段 | 包 | 用途 | 理由 |
|---|---|---|---|
| P2 | `langgraph` + `langchain-core` + `langchain-anthropic` | agentic 内核 | 用户点名 LangGraph/LangChain；ReAct 循环现成 |
| P1/P2 | `mcp`（官方） | MCP 服务器 | FastMCP 免手写传输 |
| P2 | `a2a` + `fastapi` + `uvicorn` | A2A 协议层 | 用户选官方 SDK；标准合规 |

边界说明：项目的"禁止引入 torch/whisper/sounddevice 等本地推理依赖"约束**只指本地推理依赖**，框架/协议依赖不受此限（用户已明确）。

## 7. 风险与降级

| 风险 | 应对 |
|---|---|
| 代理不支持 Anthropic tool use（mimo 模型未知） | D1 降级链：agent loop 失败自动回退 JSON 单发决策 |
| A2A 端口/协议与现有 gRPC 冲突 | 多传输共存，A2A 独立端口（env 配置），gRPC 保持不动 |
| 出站 MQTT 污染线上 broker | D4：`RAK_OUTBOUND=1` 才启用，默认只记日志 |
| LangChain/LangGraph 与 Python 3.11 兼容性 | 锁版本于 requirements.txt，pytest 验证 |
| 心跳层改动影响现有决策路径 | Phase 0 只改生命周期不动决策逻辑；每阶段独立验证后合入 |

## 8. 验收标准（全项目）

1. `pytest tests/` 全绿（移除死测试后）
2. `life_sense_benchmark.py` 生命感评分 ≥ 0.6，心跳/情绪/需求指标持续非零
3. 大脑能主动说话/告警（InnerLoop speak + Proactive alert → 出站通道有日志/发布）
4. MCP 客户端（如 Claude Code）能连接大脑并调用工具
5. A2A `A2AClient` 能 send task 并获得 completed + artifact 动作
6. agent loop 工具调用轨迹可见，降级链可触发
7. 现有 gRPC Execute 文本/音频路径不回归
