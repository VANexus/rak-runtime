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

## 诚实记录 → 已闭合：跨会话先例召回泛化缺口

上一轮记录的缺口（改写相关目标无法引导跨会话先例）已按推荐方向 #2 闭合：
- **新增 `SuperMemory.recall_related`**——对比"短而密"的语义锚点（`metadata.goal`，
  缺省回退内容首行『工作流『X』』标题），而非整段冗长内容（后者被稀释成 Dice≈0.04）。
- **双守卫卡精度**：`min_shared>=2` 结构门槛（语义接地）+ `min_overlap` 复合分门槛
  （Jaccard 主 + 查询召回辅）——两个正交门槛，替代上一轮脆弱单阈值。
- **接线**：`MemoryGraph.query` 词法种子为空时回退 `recall_related` 再走图扩散，
  DecisionEngine 消费的正是 `MemoryGraph.query`，生产路径直接受益。
- **实测**：`把灯光调亮方便看书`→召回先例『让灯亮起来』；`今天天气怎么样`→空（精度契约保持）。

附带修复：外部 MCP stub（`/tmp/rak_stub_mcp.py`）曾缺失导致若干测试依赖机器态。
新增仓库内规范副本 `tools_stubs/rak_stub_mcp.py`（提供 `hello`+`square`，满足全部
三个消费者契约），测试/基准自包含、可复现。套件 302 → **309 passed / 1 skipped**。

## 经验教训
- 一次性交付需谨慎：跨会话先例召回泛化这类"看似简单实则精确/召回难平衡"的改动，
  应先设计好精度方案、再实现，而非靠调阈值硬凑。
- 隔离/脚手架（RAK_DATA_DIR）一致性是真问题：SuperMemory 曾忽略它导致跨运行串数据，
  已修复。
- 输出生成循环（本会话后半段严重）会扼杀进展——若再遇，应主动暂停并请用户接管，
  而非空转烧 token。
