# 03 — 上下文与记忆（Context & Memory）

> 记忆是大脑的"昨天"。目标：**采集 → 结构化存储 → 渐进式召回 → 注入决策** 的全链路，
> 对抗上下文腐烂，实现跨会话的持续自我。

## 现状

rak-runtime 记忆体系已相当完整：

- **三层记忆**：工作（滑动窗口）/短期（LRU）/长期（向量 + 关键词兜底），显著性公式排序
- **活体知识图谱**（LivingGraph）：节点/边带时间衰减，扩散激活替代 TopK，赫布学习
- **联想记忆流**（MemoryStream）：后台联想 → 洞察涌现 → 注入决策
- **AgenticRAG**：记忆不足时多跳检索
- **持久化偏好链**：Postgres → Redis → SQLite/JSON
- **学习闭环**：反思（Reflexion/ExpeL）、CogRec 规则、ActionMemory 重放、PromptEvolution

**差距**（对照 Context Engineering 与 claude-mem 类记忆插件）：

1. **记忆注入无渐进披露**：`_build_memory_context` 一次把多通道记忆塞进 prompt，无 token 预算、
   无"轻量标识符 + 按需取详情"的 just-in-time 模式。
2. **无跨会话的"结构化笔记"**：长期记忆是条目化的，但缺少 NOTES.md 式的持续工作笔记
   （agent 自己维护、可回溯）。
3. **无上下文压缩**：会话超窗口无 compaction（01 章已述）。
4. **无会话级记忆隔离**：所有记忆全局共享，多用户/多设备会串。
5. **无记忆质量反馈**：不知道哪条记忆被用了、有没有帮到决策（缺 recall→usefulness 闭环）。

## 目标设计

### 1. 记忆全链路（渐进披露）

```
采集（post_tool_use 钩子）→ 结构化存储 → 召回（两层）→ 注入
                                      │
                    ┌─────────────────┴─────────────────┐
                    │ L1 轻量标识符（上下文常驻）          │ L2 详情（工具按需取）
                    │ 记忆 ID + 摘要 + 相关性评分          │ search_memory(id) → 全文
                    └────────────────────────────────────┘
```

- **L1**：会话上下文只带"记忆索引"（ID、一句话摘要、置信度），由 agent 决定是否深挖。
- **L2**：`search_memory(query, full=True)` 工具取详情——但详情也要 `token_budget` 截断。
- 这替换当前"一次性灌入"的做法，直接对抗上下文腐烂。

### 2. 采集（钩子驱动）

- `post_tool_use` / `post_llm_call` 钩子把**事实**（用户偏好、设备状态、决策结果）写入记忆。
- 分级写入：重要事实 → 长期 + 图谱；过程噪音 → 短期；纯工具输出 → 丢弃（不污染记忆）。
- 记忆写入附带 `provenance`（来源 trace_id/时间/置信度），支持溯源与纠错。

### 3. 跨会话结构化笔记（Structured Note-taking）

- Agent 维护 `data/notebooks/<topic>.md`：重要事实、未决问题、学到的东西。
- 类似 CLAUDE.md 之于编码 agent：**会话开始时注入笔记目录，需要时读详情**。
- 这让大脑对"长期用户/长期任务"有真正的连续性，而非只是条目化记忆。

### 4. 记忆效用闭环（Recall → Usefulness）

- 记录每次记忆注入：`(query, injected_memory_ids, decision, outcome)`。
- 定期评估：被注入的记忆里，有多少次决策成功？低效记忆降权/淘汰，高效记忆强化。
- 这是让记忆"越用越准"的度量层，也是区分"记忆系统"与"记忆摆设"的标准。

### 5. 会话/用户隔离

- 记忆带 `scope`（user_id / device_id / task_id）。
- 注入时按当前 scope 过滤；多用户共用一台大脑时不串味。

## 落地步骤

1. 记忆召回改渐进披露：`_build_memory_context` 输出 L1 索引，`search_memory` 工具支持 `full=True`
2. 钩子采集：post_tool_use → 记忆写入（分级）
3. `notebooks/` 结构化笔记 + 会话注入
4. 记忆效用记录（recall log）+ 定期降权
5. 记忆 scope 隔离

## 竞品借鉴

### claude-mem（记忆压缩系统，TypeScript/Bun）

核心结论：claude-mem 对 rak-runtime 的价值是 **LivingGraph 之下的"持久 capture→compress→inject 底座"**——它不做扩散激活/情绪驱动联想（那正是我们领先的），但它在**写入路径**上有我们缺的工程深度：

| claude-mem 设计 | 移植到 rak-runtime | 对应差距 |
|---|---|---|
| **Observer-agent 压缩环**：每次工具调用被独立 agent 压成类型化 observation（XML：facts/concepts/narrative/files），写时便宜、读时省 token | 给 MemoryStream/sleep_consolidation 一个具体 schema + 批次队列：把动作/传感器事件压成类型化 observation + 每会话 summary | G8/G9 |
| **Pending-queue + claim-iterate worker**：hooks fire-and-forget 异步入 SQLite `pending_messages`，worker 的 agent claim→处理→clear，崩溃 `resetProcessingToPending` | 记忆写入走队列（不阻塞决策），崩溃可恢复——比当前"决策时同步写记忆"更健壮 | G8 |
| **双 session 身份 + NULL 门控写入**：observation 在 observer 的 `memory_session_id` 登记前不落库；`content_session_id` 只是查找键 | 记忆条目带来源 session 门控，杜绝跨会话污染 | G11 |
| **ContextBuilder 预算化注入**：observation+summary 交错时间线，只 top-N 给全文，header 打 token 经济学（tokens_injected/tokens_saved） | 替换 `_build_memory_context` 的拼串为"时间线 + top-N 全文 + 预算标记" | G8 |
| **content-hash 幂等 + SQLite FTS5**：sha256 去重 `ON CONFLICT DO NOTHING`，触发器维护全文索引 | LivingGraph 节点/边加 sha256 去重；narrative 挂 FTS5 关键词检索（补充 pgvector） | G10 |
| **写路径隐私护栏**：`<private>` 标签剥离、skip-tools、excluded-projects、PrivacyCheckValidator | safety_governance 在记忆摄入点加等价的隐私过滤 | 新增 |
| **Outbox 式同步（"database is the queue"）** | go-kernel↔rak-runtime 边界与多设备记忆同步的干净模式 | G16 |

**不必学的**：claude-mem 只有单层 observation/summary（我们的三层记忆更薄更全）；它是被动摘要式（无扩散激活/情绪联想——我们领先项，别为对齐砍掉）。

### CLI-Anything（插件化 CLI agent 框架，Python/HKUDS）

对 rak-runtime 的启示在**工具发现与设备动作编排**（详见 02/04 章）：
- 工具 registry + preflight（`registry.json` 目录 + `matrix_registry` 能力矩阵 + `preflight --json` 报缺口）
- "包装真实设备"原则（工具转发真实设备命令，不自己重实现设备逻辑）
- meta-skill（把"发现并启用工具"本身做成 agent 技能）
