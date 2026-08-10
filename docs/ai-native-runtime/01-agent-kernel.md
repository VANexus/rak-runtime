# 01 — Agent 主循环（Agent Kernel）

> 目标：把 rak-runtime 的决策路径升级为**生产级 agent 循环**——稳定、可诊断、可降级，
> 既能像编码内核一样"拿着工具自主探索"，又保持具身场景的确定性兜底。

## 现状

rak-runtime 已有 LangGraph ReAct 内核（`src/core/agent_loop.py`）：

- 工具集：`search_memory / query_device / get_emotion / get_needs / reflect / finalize`
- 循环：LLM 调用 → 工具执行 → 结果回喂 → 直到 `finalize` 产出结构化决策
- 降级链：agent 失败 → `_llm_decide` 单发 JSON → 规则引擎

**差距**（对照前沿编码内核与 Context Engineering 方法论）：

1. **循环不可诊断**：agent 每轮调用重建一次（`create_react_agent` 每次调用新建），无状态检查点、
   无工具调用轨迹持久化、无重放调试能力。
2. **无流式**：`agent.invoke` 阻塞等全部完成；Claude Code/Codex 都是流式 token + 实时工具结果。
3. **上下文无压缩**：超过窗口长度的任务会死；没有 compaction / 结构化笔记 / 子代理三件套。
4. **工具调用无权限门**：认知工具直接执行，没有 allow/ask/deny 模型；对具身场景（物理动作）这是缺失的安全层。
5. **无钩子（hooks）**：没有 PreToolUse/PostToolUse/SessionStart 生命周期钩子。
6. **单代理**：没有子代理（subagent）架构——复杂任务无法并行/委派干净上下文。

## 目标设计

### 1. 循环核心（状态机）

```
                     ┌─────────────────────────────┐
                     │       Agent Session          │
                     │   session_id · trace_id      │
                     │   messages[] (持久化)         │
                     │   checkpoint (可恢复)        │
                     └──────────┬──────────────────┘
                                │
   ┌──────────────┐    ┌────────▼────────┐    ┌──────────────┐
   │  LLM 调用     │───▶│ 工具调用决议      │───▶│ 工具执行      │
   │  流式 token   │    │  (tool_call)    │    │  权限门→沙箱   │
   └──────────────┘    └────────┬────────┘    └──────┬───────┘
                                │                    │
                                │  ◀──── 结果回喂 ────┘
                                ▼
                        finalize / 达到上限 / 用户中断 → 结束
```

**关键决策**：

- **Session 为一等公民**：一次用户请求 = 一个 Agent Session。session 记录完整消息历史 + 工具调用轨迹
  （含参数/结果/耗时），持久化到 `data/sessions/<trace_id>.jsonl`。可重放、可审计、可断点续跑。
- **循环复用**：`create_react_agent` 改为模块级缓存（按 model 维度），每次调用注入新 session 上下文。
- **工具调用轨迹 = 可观测性核心**：每次工具调用产出结构化事件（tool/name/args/duration/status），
  流入 `get_cognitive_stats()` 与日志，供调试与学习闭环。
- **降级链保持**：agent 不可用 → JSON 单发 → 规则引擎。这是具身场景的硬约束。

### 2. 流式（Streaming）

- LLM 流式 token 实时推送给调用方（gRPC 已有 `StreamASR`，可扩展 `StreamExecute`）。
- 工具结果到达即更新会话，不必等最终答案。

### 3. 上下文管理（Context Engineering 三件套）

| 技术 | 落地 | 触发 |
|------|------|------|
| **Compaction（压缩）** | 会话接近 token 上限时，LLM 总结保留架构决策/未决问题/关键事实，开启新窗口 | 阈值触发（如 80% 上限） |
| **Structured note-taking** | Agent 定期把重要事实写进 `data/notebooks/<topic>.md`（跨会话共享） | 关键里程碑/新事实发现 |
| **Sub-agent 委派** | 复杂子任务派给干净上下文的子代理，只回收 1-2k token 浓缩摘要 | 主 agent 判断可并行/可委派 |

- **just-in-time 检索优先**：工具（memory/device/rag）按需取数，而不是预注入全部记忆。
- **渐进式披露**：会话上下文只带"轻量标识符"（记忆 ID、设备列表），需要时工具取详情。

### 4. 权限门（Permission Gate）

```
工具调用 → 权限评估（permission policy）→ allow（直接执行）/ ask（待确认）/ deny（拒绝）
```

- 具身场景分级：
  - **观察类工具**（读记忆/读情绪/查设备）：默认 allow
  - **动作类工具**（execute_action / 派发任务）：默认 ask，`emergency_stop` 永远 allow
  - **出站工具**（MQTT/A2A 派发）：默认 deny，`RAK_OUTBOUND=1` 且策略放行才执行
- 策略可配置（`config/permissions.yaml`），同一模式从 ask 升级为 allow（用户显式确认 N 次后）。

### 5. 钩子（Hooks）

仿 Claude Code 的生命周期钩子，注册为可插拔函数/脚本：

- `session_start` / `session_end`：会话生命周期
- `pre_tool_use` / `post_tool_use`：工具调用前后（可阻断、可改写）
- `pre_llm_call` / `post_llm_call`：LLM 调用前后
- `memory_update`：记忆写入时（驱动学习闭环/主动行为）

钩子是实现"大脑在决策时也在学习"的挂点：post_tool_use 钩子把动作结果喂给 PolicyModel 反射弧、
LearningLoop 反思、LivingGraph 建图。

## 落地步骤

1. `src/core/agent_session.py`：Session 数据结构 + JSONL 持久化 + 轨迹事件记录
2. `agent_loop.py` 重构：模型缓存 + session 注入 + 轨迹返回
3. `src/core/permissions.py`：权限策略（allow/ask/deny）+ 配置加载
4. `src/core/hooks.py`：钩子注册表 + 生命周期调度
5. gRPC `StreamExecute`：流式决策
6. 上下文压缩器 + 子代理工具

## 竞品借鉴

> ⏳ 待 4 组竞品分析返回后补充：codex/opencode/claw-code/CodeWhale 的循环与状态设计、
> Claude Code 的钩子/子代理/压缩机制、openclaw 的 session 持久化。
