# Rak Harness 会话 Capstone（2026-08-20）

本文件整合 rak-runtime agent harness 本轮大规模会话的全部交付与决策，
作为可持续维护的归档（主架构看 `10-harness-architecture.md`）。

## 最终状态
- 提交：~24 个（`e8c0019` → `bebb2cd`）
- 离线：**302 passed / 1 skipped**（后续 generalization 尝试回滚后保持）
- 活体（LongCat-2.0，隔离 RAK_DATA_DIR，诚实记录）：
  - decision-suite **13/13 (1.0000)**（avg 15.3s/task，fast-path 5-7s）
  - workflow **completed 1 轮 + 跨会话召回先例**
  - 3-arm baseline：harness cold 100% / para 100%
- 工作树干净，变更全部提交

## 本轮交付（按主题）
| 主题 | 交付 | 要点 |
|------|------|------|
| TODO #4 断学习链 | 复合路径顶层 action 契约 + 缓存落库 | cold `?` 0/12，paraphrase 命中 9/12 |
| G5 工具单一事实源 | `COGNITIVE_TOOLS` 5→10 | agent 内核自动物化 + 提示词单一来源 |
| G12/G13 技能落盘 | SKILL.md 持久化 + 强化 | Voyager 技能跨会话恢复 + digest 注入 |
| G6/G19 MCP 客户端 | 外部 MCP 工具（stdio+进程内） | 物化进 agent 内核，benchmark 固化 |
| 工作流→超长期记忆 | 工作流成果入 SuperMemory | 跨会话召回先例，活体 completed |
| agent 预算配置 | RAK_AGENT_MAX_TOKENS/RECURSION | LongCat thinking 可运行时收敛 |
| CoreMemory（Letta 前沿） | labeled 有界 core 块 + scratch | 补齐记忆三层架构的 core 层 |
| 图→决策集成测试 | 锁定 MemoryGraph 注入决策上下文 | 图结构记忆到决策的真实贡献 |
| SuperMemory RAK_DATA_DIR 隔离 | 默认路径经 _data_dir() 派生 | 修复基准/测试跨运行串数据 |

## 诚实记录：跨会话先例召回泛化缺口（未解决，需正确设计）
调试确认：SuperMemory 词法召回（FTS/LIKE/bigram）对近逐字目标可召回，但**改写相关目标
返回空**（`让灯亮起来` vs `把灯光调亮`）。尝试 naive 字符重叠（Dice）泛化失败：
- 冗长内容 + bigram/trigram → Dice ≈ 0.04（稀释严重）
- 简洁目标 + unigram → 目标对 Dice ≈ 0.14，但需阈值降到 0.10 才命中
- 阈值 0.10 破坏 unsatisfied `unrelated-query-returns-empty` 精度契约（全量回归）

**结论**：需更严谨方案，而非调阈值。推荐方向：
1. **`recall_by_graph` 图扩散召回**——工作流记忆已建图索引（scope='workflow'），
   相关目标经相似边扩散浮出先例，天然带路径与权重，比字符 Dice 更有语义。
2. 或：工作流记忆存**结构化 goal 字段**（metadata），检索时对 goal 字段做
   embedding/关键词匹配，而非对整段内容做 Dice。
3. 或：复用 semantic_cache 的 Dice 层实现作为**独立召回通道**并配反义/类别守卫
   （但需先解决"短查询 vs 长记忆内容"的尺度不匹配）。

`tests/test_workflow.py::test_related_goal_recall_generalization_gap` 已如实锁定
当前近逐字行为，防止误以为已支持。

## 经验教训
- 一次性交付需谨慎：跨会话先例召回泛化这类"看似简单实则精确/召回难平衡"的改动，
  应先设计好精度方案、再实现，而非靠调阈值硬凑。
- 隔离/脚手架（RAK_DATA_DIR）一致性是真问题：SuperMemory 曾忽略它导致跨运行串数据，
  已修复。
- 输出生成循环（本会话后半段严重）会扼杀进展——若再遇，应主动暂停并请用户接管，
  而非空转烧 token。
