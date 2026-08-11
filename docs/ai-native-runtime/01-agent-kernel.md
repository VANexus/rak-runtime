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

### 编码内核共性（codex/opencode/claw-code/CodeWhale）

五个编码 agent 收敛到同一循环骨架：**采样 → 工具结算 → 上下文检查 → 压缩/续接**。
差异只在采样是否流式、工具是否并行、压缩插在哪。对 rak-runtime 的具体映射：

| 竞品机制 | 移植 | 对应差距 |
|---|---|---|
| **结构化工作状态压缩模板**（opencode `SUMMARY_TEMPLATE`：Objective/Details/Work State/Next Move/Relevant Files + CodeWhale `CompactionLiveState` 重锚当前设备/动作/待审批） | 会话压缩时产出"当前任务/已完成/阻塞/下一步/关联设备"结构化摘要，压缩后注入 `CompactionLiveState`（已连接设备、正在执行的动作、待审批项）——对物理运行时是刚需 | G2 |
| **循环护栏**（CodeWhale `ToolCallBudget` + StuckGuard + 流重试预算 + claw-code `max_iterations`） | 每轮工具调用预算（耗尽→`PermissionDenied` 可见错误）、断流静默重试 N 次、空迭代守卫——防大脑对设备死循环发动作 | G1 |
| **System Context 抽象 + Context Epoch**（opencode） | 上下文源（设备状态/记忆/时间/人格）做成 typed source，变化只在 Safe Provider-Turn Boundary 作为增量系统消息注入；epoch 基线持久化复用，保 LLM 前缀缓存稳定 | G2 |
| **工具输出有界投影 + 管理输出文件**（opencode `ToolOutputStore`） | ASR 转写/传感器批数据/记忆长文的历史里只留预览（~2k 字符），完整进临时文件给路径——工具成功语义不变 | G5 |
| **Guardian LLM 评审门**（codex） | 高风险物理动作先过一次独立 LLM 评审再执行，fail-closed + 熔断 | G3/G7 |

### Claude Code 生产内核（2.1.88）

Claude Code 是最完整的生产级 agent harness，最值得移植的 5 项：

1. **主循环 = async generator 状态机，恢复路径是显式 `state=next; continue` 转移**。
   模型 fallback / 413 压缩 / max-output-tokens 升级 / token 预算续跑 / stop-hook 阻断全部建模为带 `transition.reason` 的状态转移，且有熔断（`MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES`）。→ rak-runtime 的 agent 循环该有同样的显式恢复转移表 + 遥测 reason 字段；具身映射：物理恢复（电机超时/急停复位/传感器断连）建模为同一转移表。
2. **工具是一等对象**：Zod schema + `isConcurrencySafe/isReadOnly/isDestructive/interruptBehavior/maxResultSizeChars` + 内嵌 `checkPermissions()`。编排层只读元数据就决定并发/沙箱/权限/结果预算。→ rak-runtime 的 ToolDef registry 直接继承这套元数据：`move_forward` 只读并发安全、`lock_open` 破坏性、`emergency_stop` 永不并发且需交互、传感器读数声明 `maxResultSizeChars`。
3. **流式工具执行 + 兄弟 abort**（StreamingToolExecutor）：模型还在吐字时并行执行已到达工具，只读批量并行、非只读独占；一个工具失败只杀兄弟不杀整轮。→ 电机/摄像头是慢工具，天然该与 LLM 流式重叠；"一个传感器失败不炸掉整个决策回合"。
4. **多级上下文压缩管线**：snip → microcompact（缓存级编辑）→ contextCollapse（内存投影）→ autocompact（fork 摘要代理，共享 prompt cache）→ reactive compact（413 后 strip 重试），各级有边界消息 + 保留段。→ 三层记忆（工作/短期/长期）正是同一问题的物理版：感知流压成摘要、摘要进长期、压缩不阻塞新感知。
5. **子代理 = 递归 query 循环 + 上下文 fork + prompt cache 字节一致**。多技能代理各跑一个 `query()` 实例，父只做路由，子代理独立 transcript 可 resume。→ 具身场景：导航代理/交互代理各一个实例，父路由；子代理是干净上下文做深度工作的标准手段。

另：**并行记忆/技能预取**（模型流式期间用 Haiku 侧查询记忆检索，注入或跳过，首 token 延迟不为检索买单）——世界模型/设备状态查询在感知处理时并行预取。

### openclaw / hermes（session 持久化角度）

- hermes：会话状态全进 **SQLite + FTS5**（替代每会话 JSONL），WAL 并发、CJK trigram 分词（对中文日志直接可用）、`parent_session_id` lineage 支持压缩拆分。→ rak-runtime 的会话持久化直接抄这个（而非手写 JSONL）。
- openclaw：会话/技能**在会话开始时快照**，会话内不变（保 prompt cache 稳定）。→ agent 会话的技能/工具集快照，不动摇缓存前缀。
