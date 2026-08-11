# 07 — 学习与自进化（Evolution）

> 大脑不只是响应，它会**从每次交互中变强**。目标：把现有的学习模块串成完整闭环，
> 加"度量"证明进化真的发生，加"落盘"保证进化跨会话累积。

## 现状（学习模块已相当齐全）

| 机制 | 作用 | 状态 |
|------|------|------|
| Reflexion 即时反思 | 纠正/失败 → LLM 分析 → 洞察注入 prompt | ✅ |
| ExpeL 批量对比 | 成功/失败轨迹 → 提取规则 → 入记忆 | ✅ |
| MemGPT 记忆整合 | 缓冲满 → LLM 决定保留/归档/丢弃 | ✅ |
| Voyager 技能提取 | 成功模式 3+ 次 → 抽象技能 | ⚠️ 未落盘 |
| CogRec 规则学习 | LLM 成功 → pattern→action 规则 | ✅ 落盘 |
| ActionMemory 重放 | 成功轨迹 → 相似查询重放 | ✅ 落盘 |
| PromptEvolution | 战术/战略双流指南进化 | ✅ 落盘 |
| PolicyModel 反射弧 | 在线学习（REINFORCE） | ⚠️ 未落盘 |
| 元认知策略权重 | 反思调整策略权重 | ⚠️ 未落盘 |

## 差距

1. **学习无闭环度量**：洞察/规则/技能产出了，但没有"用了没、用了是否有效"的反馈回路。
2. **部分学习成果不落盘**：技能（`_skills` 内存字典）、PolicyModel 权重（模型文件只在
   `save_model()` 时）、元认知策略权重（内存）——重启即失。
3. **学习触发是被动的**：靠事件/信号密度触发反思；没有"定期深度自省"（如每日整合）。
4. **学习与 agent 内核脱节**：agent 工具调用轨迹没喂给学习闭环（只喂了最终决策）。

## 目标设计

### 1. 学习闭环（带度量）

```
决策 + 工具轨迹
   → 反馈采集（post_tool_use 钩子：成功/失败/耗时）
   → 事件驱动反思（Reflexion 即时 / ExpeL 批量）
   → 资产产出（洞察→prompt / 规则→CogRec / 轨迹→ActionMemory / 技能→skills/）
   → 资产注入下次决策
   → 效用度量：注入的资产里，多少决策成功？
   → 强化/淘汰（低效降权，高效加强）
```

### 2. 全量落盘（进化跨会话累积）

| 资产 | 落盘位置 | 触发 |
|------|----------|------|
| 技能 | `skills/<name>/SKILL.md` | Voyager 提取 → 验证 → 入库 |
| PolicyModel 权重 | `data/models/policy.json` | 每次 `_record_feedback` 后定期 save |
| 元认知策略权重 | `data/meta_weights.json` | `reflect()` 调整后 save |
| 洞察/反思日志 | `data/reflection_log.jsonl` | 每次反思 |
| 学习度量 | `data/learning_metrics.json` | 每次资产注入评估 |

### 3. 深度自省（Sleep 整合的延伸）

- SleepConsolidation 已做记忆整合 + 反思。扩展为**学习整合**：
  - 从 `reflection_log` 提炼"本周学到什么" → 更新 SelfModel 的 `learned_skills`
  - 从工具轨迹统计高频失败动作 → 主动补技能 / 调 prompt
  - 从 PolicyModel 权重快照对比 → 确认反射弧在收敛

### 4. 工具轨迹进学习

- `post_tool_use` 钩子把工具调用轨迹（含参数/结果/耗时）喂给：
  - LearningLoop（失败工具 → 反思）
  - ActionMemory（成功轨迹 → 重放）
  - PolicyModel（状态-动作-奖励）
  - 度量层（工具使用率/成功率 → 调整 ToolDef 的 token_budget 或 description）

### 5. 学习的"自我"闭环

- 元认知 reflect() 已经调整策略权重。扩展：reflect 也评估"学习本身是否有效"
  （洞察注入后成功率是否提升）→ 决定加大/减少反思频率。
- SelfModel 增加 `learned_skills`（已学技能）与 `growth_log`（进化历史），
  `who_am_i()` 汇报"我最近学会了 X"——这是生命感的一部分。

## 落地步骤

1. 学习资产全量落盘（技能/权重/度量）
2. post_tool_use 钩子 → 学习闭环（工具轨迹进学习）
3. 学习度量 + 效用反馈（强化/淘汰）
4. Sleep 整合扩展为学习整合（深度自省）
5. SelfModel 进化汇报

## 竞品借鉴

### 结论先行

竞品分析确认：**rak-runtime 的学习模块数量已超多数竞品**（Reflexion/ExpeL/MemGPT/Voyager/CogRec/ActionMemory/PromptEvolution/反射弧全都有），缺的不是新机制，而是**闭环度量 + 全量落盘 + 护栏**。借鉴聚焦这三块。

### hermes（自我改进闭环，最相关）

- **`/learn` + `skill_manage` + curator 三件套**：`/learn` 把用户描述的任何东西生成技能创建提示；`skill_manage` 让 agent 自己写/改技能；`curator` 后台审查 agent-created 技能（pin/archive/consolidate/patch）。
- **curator 护栏**：只动 `created_by:"agent"` 的、**永不删除只归档**、pinned 豁免一切自动转换、技能使用遥测（use_count/patch_count/last_activity/state）。
- → rak-runtime 的技能自动沉淀（G12）直接抄这套：agent 创建技能 → 后台 curator 审查 → 归档不删 → 遥测驱动淘汰。

### openclaw（dreaming 巩固）

- **记忆巩固移出回复路径**："writing is the hard part"——把策展从繁忙回复路径移到后台 dreaming（light→REM→deep 三阶段）。
- **确定性门 + 有界模型**：先确定性打分门槛（relevance/频率/多样性/recency 加权），过了才让有界 LLM consolidate；写前记录 pre-image、原子 rename、失败回退 append-only。
- → rak-runtime 的 SleepConsolidation 已做记忆整合，补上"确定性门 + 有界模型 + 失败不阻塞"语义（对应 G23 度量）。

### claude-mem（写路径工程）

- observation 的幂等（content-hash）+ pending-queue + 隐私护栏（见 03 章）——学习资产的写入也适用：技能/规则/度量落盘幂等、队列化、护栏过滤。
