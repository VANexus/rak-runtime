# 10 — Rak Harness 架构设计（agent harness，超越 Claude Code）

> 目标：把 rak-runtime 从"决策服务 + 已激活的认知层"升级为**生产级 agent harness**——
> 一个比 Claude Code 更好的具身智能 agent 运行时。Claude Code 是 baseline，
> 本 harness 要在**超长期记忆、图结构记忆、结构化工作流、可度量质量**上超过它。

## 定位：为什么能超过 Claude Code

| 维度 | Claude Code | Rak Harness（目标） |
|------|-------------|---------------------|
| 记忆 | CLAUDE.md + 会话内上下文，跨会话靠手工 | **超长期记忆**：幂等落盘 + FTS5 全文 + 跨会话自动召回注入 |
| 记忆形态 | 无图 | **记忆即图**：篇章级关联边 + 多跳扩散召回 + 路径发现 |
| 工作流 | 单 agent 循环 + 手动 plan | **Plan→Execute→Review 结构化多 agent 工作流** |
| 质量 | 无内置度量 | **Benchmark**：任务套件 + 打分 + baseline 对比（agent 内核 vs 单发 vs 规则） |
| 生命感 | 无 | 情绪/需求/内心循环（已具备）持续影响行为 |

## 分层架构总览

```
┌─────────────────────────────────────────────────────────────┐
│ 接入层    bin/rak CLI/TUI · gRPC :50051 · A2A :8000 · MCP    │
├─────────────────────────────────────────────────────────────┤
│ Harness 层  src/harness/                                     │
│   benchmark.py   基准测试（任务套件/打分/baseline 对比）       │
│   workflow.py    Plan→Execute→Review 多 agent 工作流          │
│   （tool registry / brain facade 渐进补齐）                   │
├─────────────────────────────────────────────────────────────┤
│ 认知层    src/core/（既有 + 新增）                            │
│   agent_loop    LangGraph ReAct 内核（已有）                  │
│   memory_longterm  ★ SuperMemory 超长期记忆（新增，已接线）   │
│   memory_graph   ★ MemoryGraph 记忆即图（新增）               │
│   decision_engine 15 步决策管线（已有，超长期记忆已注入）      │
├─────────────────────────────────────────────────────────────┤
│ 协议层    A2A/MCP/MQTT（已有）                                │
└─────────────────────────────────────────────────────────────┘
```

## 超长期记忆（SuperMemory，`src/core/memory_longterm.py`）

面向"终身/跨会话"的持久记忆层，补齐四个生产级缺口：

1. **幂等写入** — `sha256(content + scope)` 作唯一键，同内容不重复落盘（G27）
2. **全文检索** — SQLite **FTS5 trigram** 分词（中文子串匹配的关键；默认 unicode61
   会把整句当一个 token，trigram 才能做 CJK 子串搜索）
3. **渐进披露** — `recall()` 返回紧凑索引（id/类型/时间/重要性/片段），`recall_full()`
   才取全文——只注入高信号 token（G8）
4. **scope 隔离** — 多用户/多设备记忆不串（G11）
5. **记忆间图链接** — 中文 n-gram Jaccard 相似度（bigram+trigram 并集）自动建边，
   `recall_by_graph()` 图扩散召回（G10）

**接线**（`decision_engine.py`）：
- `_get_super_memory()` 惰性单例
- `_build_memory_context()` 增第三通道：注入 `## 超长期记忆（跨会话）` 紧凑索引
- `_store_decision_memory()` / `_store_text_decision_memory()` 写穿
- `record_user_correction()` 纠正以 importance=0.95 永久沉淀（最强学习信号）

## 记忆即图（MemoryGraph，`src/core/memory_graph.py`）

在 SuperMemory 之上加**图查询层**，不重复存储：
- `index()` 把记忆注册为图节点（轻量实体抽取）
- `query()` 多跳召回：seed = SuperMemory.recall → 沿邻接边扩散 hops 层 → 带路径返回
- `paths()` / `shortest_path()` BFS 路径发现——"这两段记忆如何相连"
- `link()` 边同时写入 SuperMemory.memory_links（持久化委托，单一事实源）

## 工作流系统（Workflow，`src/harness/workflow.py`）

**Plan→Execute→Review** 三阶段循环，超越单 agent 循环：
1. **Plan**：LLM 把目标分解为步骤 JSON；解析失败 → 单步降级
2. **Execute**：每步经 `run_agent` 子 agent 执行（独立 session + 工具轨迹）
3. **Review**：LLM 评估是否达成目标；不达 → 带反馈重新规划，只重跑失败步骤
4. 会话经 `AgentSession`/`SessionStore` 持久化（可诊断/可重放）
5. 任何环节异常降级，绝不抛出

## Benchmark（`src/harness/benchmark.py` + `benchmarks/`）

- **任务套件**：decision_suite（12 条中文指令→14 动作）、memory_suite（8 条跨会话
  记忆召回）、workflow_suite（8 条复合指令分解）
- **打分**：`score_suite()` 加权正确率 + 每类分项 + 平均延迟 + 工具效率
- **Baseline 对比**：`compare()` 同一任务集跑 agent 内核（RAK_AGENT=1）vs 单发 JSON
  （RAK_AGENT=0），量化 harness 增量
- **运行**：`python -m src.harness.benchmark --suite all --baseline [--json out.json]`
- 单测不碰网络（fake runner）；live 跑用 LongCat（.env 已配置）

## 质量与降级原则（延续既有约定）

- 一切外部依赖失败 → 标记不可用 → 系统继续（LLM→agent 内核→JSON→规则，一条降级链到底）
- 单测必须离线可跑（mock brain/LLM），live 测试是手动、可复现的
- 注释/文档中文，标识符英文 snake_case/PascalCase，2 空格缩进
- 新能力走注册表/模块，不硬编码进决策引擎（窄腰原则）

## 当前状态（2026-08-19）

- ✅ LLM 环境：RAK_LLM_* 覆盖全局代理，LongCat-2.0 直连（bearer），thinking 兼容
- ✅ SuperMemory：实现 + 单测 + 决策引擎接线（写穿/召回/纠正沉淀）
- ✅ MemoryGraph：实现 + 单测 + 决策引擎第四通道（多跳联想）
- ✅ Workflow：Plan→Execute→Review 引擎 + 会话持久化 + 单测
- ✅ Benchmark：任务套件（decision 13 / memory 8 / workflow 8）+ 打分 + baseline 对比
- ✅ 规则兜底增强：补全 开灯/关灯/锁上/跳舞 关键词；无匹配时安全降级 idle
- ✅ 架构去重（不要屎山）：3 处重复 `_parse_json` 统一为 `safe_json_parse`；
  统一大脑入口 `src/harness/brain.py`（CLI/A2A/benchmark 三处 run_brain 收拢）；
  工作流规划器限 1-4 步（prompt）+ `MAX_PLAN_STEPS=6` 防御性截断
- ✅ 复合指令检测强化：补 "并/以后/并且/跟/且" 连接词 + 动作动词词干计数
  （>=2 个不同动词=复合）；要求连接词两侧含动作动词，杜绝"我们以后再聊"误判
  —— workflow-suite 两个 FAIL（wf-04 挥挥手并点点头、wf-05 跳完舞以后把灯关掉）
  根因修复

**Benchmark 首跑（live，LongCat-2.0）：**
- memory-suite：8/8 PASS，平均召回 1.3ms（跨会话持久化验证通过）
- decision-suite（agent 内核）：~12 次 LLM 调用/任务，~70s/任务 —— 量化了
  "深思成本"，印证语义缓存/CogRec/ActionMemory 快速通道的必要性
- decision-suite（单发 JSON 快速路径）：4/4 正确，~2s/任务

**Benchmark 发现并修复的架构问题：**
- 🔴 **agent 内核卡死循环**：同一工具（query_device）连续调用 10 次才 finalize，
  单任务 49s、~14 次 LLM 调用 —— 成本黑洞。
  ✅ 修复：`_mk_tool` 内置**卡死护栏**（stuck-guard）：同一工具连续调用 >=3 次
  即返回"请直接 finalize"提示；`agent.invoke` 加 `recursion_limit=12` 预算帽。
- 🔴 **state 字段重载**：go-kernel 用 `state` 传设备状态 JSON，而 CLI/A2A/benchmark
  用 `state` 传用户自然语言指令。结果系统提示词渲染出"## 当前设备状态\n向前走两步"，
  模型正确地把指令读成设备状态报告 → 回 idle 不执行。
  ✅ 修复：`_looks_like_device_state()` 只对真实设备 JSON 渲染设备状态段；
  用户指令用"用户说:"措辞进 user message。
- 🔴 **学习污染链**：LLM 一次误判（动作指令回 idle）被 CogRec 学成规则持久化，
  之后 <1ms 命中错误规则，永久绕过 LLM —— 误判被固化成"正确"。
  ✅ 修复：**决策质量门** `decision_ok` —— 动作指令回 idle 视为失败决策，
  不缓存、CogRec/ActionMemory 不学、PromptEvolution 记失败、学习闭环记失败；
  并清理已污染的 4 条规则。

**修复后复跑（live）：**
- decision-suite：**13/13 PASS (1.0000)**，平均延迟 79ms（首个 991ms 走 LLM，
  其余 12 个由语义缓存/CogRec/规则 <10ms 命中）—— 快速通道价值实证。
- workflow live：目标"给出三句温暖问候" → **completed，2 轮迭代**。
  第 1 轮被 reviewer 拒绝（"输出不完整，未满足三句要求"），带反馈重新规划执行后
  第 2 轮接受。评审反馈循环按设计工作，会话持久化（workflow-*）。

**Baseline 对比实证（live，LongCat-2.0，`benchmarks/baseline_suite.py` 3 臂 × 2 阶段）：**

实测表（12 任务，独立隔离 `RAK_DATA_DIR`，冷启动=新指令 / paraphrase=同义改写）：

| 决策路径 | cold 准确率 | para 准确率 | cold 延迟ms | para 延迟ms |
|---------|-----------|------------|------------|------------|
| pure_rules | 75.0% | 0.0% | 0.0 | 0.0 |
| bare_llm | 100.0% | 100.0% | 4383.9 | 3967.4 |
| harness | 100.0% | 91.7% | 18783.7 | 23286.2 |

**这次实证没有给出"harness 胜利"—— 它抓到的是一个真缺陷，价值更高：**

- 🔴 **paraphrase 语义缓存结构性失效**：`_simple_embed`（字符 bigram+trigram 哈希投影,
  dim=128）对中文改写的余弦相似度仅 **0.000~0.318**，而 `similarity_threshold=0.97`。
  → 复述/改写永远命中不了语义缓存，只有**逐字重复**（1.000）能命中。这直接击穿
  "paraphrase → <10ms 缓存命中"的可复用学习论点。此前 13/13@79ms 是因为那些任务是
  逐字重复/规则/CogRec 命中，不是真改写。
- 🔴 **save() 只持久化 `_exact_cache`（哈希），不落 `_semantic_cache`（向量）**：
  语义层重启即失，跨会话语义缓存不成立。
- 🔴 **harness cold 路径过慢**：18.8s/task（bare_llm 只要 ~4s），含 safety_governance
  的 LLM 评估（cold 曾超时一次，默认放行）——快通道没建成前，冷路径付全价。
- ✅ 诚实结论：当前 harness 在**真改写**上未赢 bare_llm（因其缓存不命中），仅大胜
  pure_rules（+91.7%）。修复方向 = 依赖自由的中文改写相似度（字符 n-gram Dice 重叠 +
  阈值校准 + 假阳性护栏）+ 语义缓存持久化 + 冷路径去冗余。已在跑多臂 workflow 修复。

**修复落地（2026-08-20，`src/core/semantic_cache.py`，多臂 workflow 实现 + 离线实证）：**
- ✅ **改写层**：`lookup()` 新增第 2b 层——字符 n-gram Dice 重叠（`_dice_overlap`），
  `para_similarity_threshold=0.40`。实测同义改写≈0.47/0.43，无关查询≈0.27，切线干净。
- ✅ **持久化修复**：`save()` 现在序列化 **精确+语义两层的并集**（按 query_hash 去重，
  v2 payload `{version:2, entries:[...]}`）；`load()` 兼容 v2 与旧平铺列表。跨进程
  `semantic_cache_size>0` 恢复证实。

**第 1 次活体复跑（`/tmp/baseline_live2.log`）暴露的下一层缺陷 + 已修：**

| 决策路径 | cold 准确率 | para 准确率 | cold 延迟ms | para 延迟ms |
|---------|-----------|------------|------------|------------|
| pure_rules | 75.0% | 0.0% | 0.0 | 0.0 |
| bare_llm | 100.0% | 100.0% | 2771.0 | 3049.9 |
| harness | 83.3% | 91.7% | 12943.2 | 10373.6 |

- ✅ **改写层真生效**：4/12 paraphrase 冷→改写在 2-3ms 命中缓存（此前 0 个能命中），
  缓存"可复用学习"机制首次实证成立。harness para 平均 23.3s → 10.4s。
- 🔴 **发现新缺陷——反义快通道误命中**：cold4「我要走了，把门关死」(lock_close) 在 1ms
  误返回 lock_open、cold8「往右偏一点」(turn_right) 1ms 误返回 turn_left。
  根因：`_ACTION_INTENT_KEYWORDS["lock_close"]` 缺「关门/关」→「把门关死」无法归类，
  原「无法归类即放行」回退 + Dice 0.47>0.40 → 反义命中；且 turn_left/turn_right 都含
  裸"转"字让 turn_left 遮蔽 turn_right。
- ✅ **已修（反义标记守卫 + 词表修正 + 边界回退）**：新增 `_has_antonym_conflict`
  （开↔关、左↔右、前↔后、进↔退、上↔下）作最强对立判别；turn 词表去掉裸"转"；
  无法归类时不再自动放行反义。离线校准：**9/12 真改写命中、7/7 反义/无关全部拦截**。
- ✅ **离线全绿**：258 passed / 1 skipped（新增改写命中/无关拒绝/持久化往返/逐字命中/
  反义拦截×3）。3 个未能命中（向前走↔往前挪 dice .20、跳个舞↔来一段舞蹈 .22、
  点个头↔颔首一下 .00）是不重叠用词的真难改写——字符重叠法在无 embedding 模型时
  的诚实上限，回退 LLM 仍正确但付延迟。
- ⏳ ~~第 2 次活体复跑中~~ → **已完成，第 3 次复跑坐实精确度胜利：**

**第 2/3 次活体复跑（`/tmp/baseline_live3.log`）—— harness 精确度胜出：**

| 决策路径 | cold 准确率 | para 准确率 | cold 延迟ms | para 延迟ms |
|---------|-----------|------------|------------|------------|
| pure_rules | 75.0% | 0.0% | 0.0 | 0.0 |
| bare_llm | 100.0% | 83.3% | 2518.7 | 4971.5 |
| harness | 100.0% | **100.0%** | 15980.2 | 12609.5 |

- ✅ **harness 是唯一双 100% 臂**：cold 12/12 + para 12/12；对 bare_llm para 增量 **+16.7%**
  （bare_llm 本轮 10/12，改写了 2 个复述出错），对 pure_rules +100%。「复用学习让 harness
  比单发 LLM 更准」论点成立——不是只快，是更正确。
- ✅ **反义误命中已消除**：cold4 现在 lock_close（曾误 lock_open）、cold8 turn_right（曾误
  turn_left），均恢复正确。改写命中也拉起：para 命中列表 1/2/4/7/8/10 在 **1-3ms**。
- 📊 **para 命中/未命中拆解（决定性）**：6 个改写命中 @1-3ms（1/2/4/7/8/10）；
  6 个回退 LLM——其中 3 个是零重叠难改写（往前挪.20/来一段舞蹈.22/颔首一下.00，合规上限），
  另 3 个（3/6/9）根因是 **cold 决策返回 `?`（无动作可抽取）→ 无缓存可复用**。
- 🔴 **新目标——cold 决策 `->?` 断学习链**：cold 3/6/9/11 返回 `_extract_action` 抽不到动作
  （confirm/低置信/空 action 路径），这些 task 的 paraphrase 全回退 LLM。修复 cold 决策
  可靠性是下一个延迟瓶颈。

⬜ Tool registry（G5 三形态工具统一）—— 下阶段
⬜ MCP 客户端（G6/G19 大脑连外部工具）—— 下阶段
⬜ 技能 SKILL.md 落盘（G12/G13）—— 下阶段
⬜ agent 内核思考 token 预算收敛（LongCat thinking 延迟）—— 下阶段
✅ **cold 决策 `->?` 断学习链修复** —— 已修（TODO #4）

**TODO #4 修复（2026-08-20，`src/core/decision_engine.py`）：**

根因不是"无动作可抽取"，而是**复合路径的返回契约 + 缓存盲区**：
- 冷任务 3/6/9/11（"把门打开让我进来"等）被 `_is_compound_command` 路由到
  `decide_from_text`（多动作分解），该路径历史上**只返回 actions 列表、无顶层
  action** → baseline `res.get("action")` 为空（日志 '?'）；且 `decide_from_text`
  **只 lookup 不 store** → 复合 cold 决策永不落缓存 → paraphrase 无法复用。

修复：
1. **顶层 action 契约**：`decide_from_text` 两个返回点都注入
   `"action": _primary_action(actions, available_actions)`（首个合法动作，
   无合法时安全降级 idle）。多动作路径与单动作路径返回契约一致。
2. **复合路径缓存**：新增 `_store_text_cache`，复用 decide() 的防污染守门
   （动作指令回 idle 不缓存），把多动作决策的顶层 action 落入语义缓存。

**离线实证（`run_brain` 全链路，规则兜底路径）：**
- 4 个问题冷任务顶层 action 全部非空且等于期望（lock_open/move_back/wave_hand/dance）。
- **3/4 个问题任务的 paraphrase 现在经 Dice 改写层 2-3ms 命中缓存**
  （之前全断链回退 LLM）：「把门打开让我进来」→「让我进屋，把门开开」、
  「往后退一点」→「退后一些」、「跟我打个招呼，挥挥手」→「招个手问个好」。
- 第 4 个（跳个舞吧→来一段舞蹈）是零重叠硬改写（dice .22 < .40），字符重叠法
  诚实上限，回退 LLM 仍正确。
- 全量 **261 passed / 1 skipped**（新增 3 条回归：顶层 action 非空、
  单意图冗余动词不空 action、_primary_action 降级 idle）。



