# 08 — 差距清单与实施路线（Roadmap）

> 从当前 rak-runtime 代码库出发，汇总 01-07 的差距，排出分阶段实施路线。
> 每阶段独立可验证，前序通过后再进入下一阶段。

## 差距清单（汇总自 01-07）

| # | 领域 | 差距 | 详见 |
|---|------|------|------|
| G1 | Agent 内核 | 循环不可诊断（无 session 持久化/轨迹/检查点） | 01 |
| G2 | Agent 内核 | 无流式、无上下文压缩（compaction/笔记/子代理） | 01 |
| G3 | Agent 内核 | 无权限门（allow/ask/deny）、无生命周期钩子 | 01 |
| G4 | Agent 内核 | 无子代理架构 | 01 |
| G5 | 工具 | 三形态各自为政，无 ToolDef 单一事实源 | 02 |
| G6 | 工具 | 工具返回无 token 预算；无 MCP 客户端（大脑连外部工具） | 02 |
| G7 | 工具 | 动作类工具无权限门 | 02 |
| G8 | 记忆 | 记忆注入一次性灌入，无渐进披露 | 03 |
| G9 | 记忆 | 无跨会话结构化笔记 | 03 |
| G10 | 记忆 | 无记忆效用闭环（recall→usefulness） | 03 |
| G11 | 记忆 | 记忆无 scope 隔离（多用户/设备会串） | 03 |
| G12 | 技能 | 学习成果不沉淀为 SKILL.md（技能落盘缺失） | 04 |
| G13 | 技能 | 无技能渐进披露加载 | 04 |
| G14 | 协议 | 出站散落，无统一出站路由 | 05 |
| G15 | 协议 | 入站三通道未归一为 Task 抽象 | 05 |
| G16 | 协议 | 设备发现静态（无 registry） | 05 |
| G17 | 协议 | A2A tasks/get/cancel/query 未接出 | 05 |
| G18 | 具身 | 世界模型预测未进决策（不"想象后果"） | 06 |
| G19 | 具身 | 设备发现动态化缺失（MCP 客户端拉入硬件能力） | 06 |
| G20 | 具身 | 主动性规则化，无 LLM 判断"该不该打扰" | 06 |
| G21 | 具身 | 情绪未反向驱动工具选择（权限门联动） | 06 |
| G22 | 具身 | 无身体预算（能耗/频率/健康度约束） | 06 |
| G23 | 进化 | 学习无闭环度量（用了没、有效没） | 07 |
| G24 | 进化 | 技能/PolicyModel/元认知权重不落盘 | 07 |
| G25 | 进化 | 工具轨迹未进学习闭环 | 07 |
| G26 | 进化 | 无深度自省（学习整合） | 07 |
| G27 | 记忆 | 记忆写入无幂等（content-hash 去重）与全文索引（FTS5） | 03（claude-mem） |
| G28 | 记忆 | 记忆摄入无隐私护栏（敏感标签/排除清单） | 03（claude-mem） |
| G29 | 工具 | 工具无目录查询（tool list/search/preflight），agent 无法按需发现 | 02（CLI-Anything） |
| G30 | 工具 | 原子动作无能力矩阵编排（目标 × 动作序列 + preflight 检查设备） | 02（CLI-Anything） |

## 实施路线（分阶段）

### Phase A：内核硬化（G1-G4，核心价值最高）

把现有 LangGraph agent loop 升级为生产级：

1. `src/core/agent_session.py`：Session 持久化 + 工具轨迹事件（可诊断/可重放）
2. `agent_loop.py` 重构：模型缓存 + session 注入
3. `src/core/permissions.py`：权限门（cognitive=allow / device=ask / outbound=deny）
4. `src/core/hooks.py`：生命周期钩子（session/pre/post tool/llm）
5. 上下文压缩（compaction）首版

**验证**：工具轨迹可见（`get_cognitive_stats` 含轨迹）；权限门拦截动作工具；钩子驱动学习。

### Phase B：工具统一（G5-G7，G29）

6. `src/tools/registry.py`：ToolDef + 从 registry 生成 LangGraph/FastMCP/A2A 三形态
7. 工具返回封装（token 预算 + summary + 结构化错误码，对齐 CLI-Anything exit-code 语义）
8. `src/core/mcp_client.py`：大脑连接外部 MCP 服务器（硬件驱动可扩展）
9. **工具目录查询（G29）**：MCP 暴露 `tool list/search/preflight`，agent 按需发现而非全量暴露

**验证**：加一个能力只改 registry 一处；三协议自动同步；MCP 客户端拉入外部工具成功；tool preflight 报缺口。

### Phase C：记忆与技能（G8-G13，G27-G28）

10. 记忆渐进披露（L1 索引 + search_memory(full=True)）
11. 结构化笔记（`notebooks/`）+ 会话注入
12. 记忆效用闭环 + scope 隔离
13. **记忆写入幂等 + FTS5 全文索引（G27）**：sha256 content-hash 去重，narrative 挂免费全文检索
14. **记忆摄入隐私护栏（G28）**：敏感标签剥离 + 排除清单 + 校验器（对齐 claude-mem PrivacyCheckValidator）
15. `skills/` 目录 + SKILL.md + load_skill 工具 + 学习闭环自动沉淀

**验证**：记忆注入 token 大幅下降；跨会话笔记生效；重复写入不产生重复条目；隐私内容被过滤；技能自动沉淀可复用。

### Phase D：协议与具身（G14-G22，G30）

16. 统一出站路由（outbound_hub）+ 回执喂 WorldModel/反射弧
17. 入站 Task 归一化（gRPC/A2A/MCP 共用决策路径）
18. device_registry（动态发现 + 缓存）
19. A2A 补齐 tasks/get/cancel/query
20. 世界模型预测注入决策 + 异常阻断
21. 主动性 LLM 判断层 + 情绪→权限门联动
22. body_budget（能耗/频率/健康度）
23. **设备动作能力矩阵（G30）**：14 个原子动作建模为"目标 × 动作序列"矩阵，preflight 检查设备在位

**验证**：出站回执闭环；异常阻断真实触发；情绪高压力时动作 ask；动作矩阵 preflight 报缺口。

### Phase E：进化闭环（G23-G26）

24. 学习资产全量落盘（技能/权重/度量）
25. post_tool_use → 学习闭环（工具轨迹进学习）
26. 学习效用度量 + 强化/淘汰
27. Sleep 整合扩展为学习整合（深度自省）

**验证**：学习度量指标上升；技能跨重启累积；自省更新 SelfModel。

## 优先级建议

- **先做 A 与 C**：内核硬化 + 记忆渐进披露是"AI-native 质量"的最大杠杆，且独立于竞品结论。
- **B 与 D 依赖工具统一**：B 先行，D 建立在 registry 之上。
- **E 贯穿**：钩子（A 的产物）驱动学习（E），可并行推进。

## 竞品借鉴（借谁、借什么）

| 阶段 | 借 | 具体机制 | 来源 |
|---|---|---|---|
| A 内核硬化 | Claude Code | 显式恢复转移表 + 熔断；工具一等对象元数据（并发/破坏性/结果预算）；流式工具执行 + 兄弟 abort；多级压缩管线 | claude-code 2.1.88 |
| A 内核硬化 | CodeWhale/opencode | 循环护栏（ToolCallBudget/StuckGuard/空迭代守卫）；System Context 抽象 + Context Epoch；结构化工作状态压缩模板 | 编码内核四件套 |
| B 工具统一 | CLI-Anything | tool registry + preflight 目录查询；JSON 契约 + exit-code 语义；"包装真实设备"原则；meta-skill | CLI-Anything |
| B 工具统一 | opencode | 工具输出有界投影（ToolOutputStore） | 编码内核 |
| C 记忆技能 | claude-mem | observer 压缩环 + pending-queue worker；预算化注入（token 经济学）；content-hash 幂等 + FTS5；双 session 门控；隐私护栏 | claude-mem |
| C 记忆技能 | hermes | curator 技能生命周期（归档不删/pinned 豁免/遥测）；CJK trigram 检索 | hermes |
| D 协议具身 | openclaw | 设备节点模型（role:node + caps + 配对审批）；SecretRefs + 出网哨兵；standing intents 确定性 prefilter | openclaw |
| D 协议具身 | hermes | relay CapabilityDescriptor 握手；cron script 预跑注入；后台进程通知；MCP 双向 | hermes |
| E 进化闭环 | hermes | 技能使用遥测驱动淘汰 | hermes |
| E 进化闭环 | openclaw | provenance 门控 + dreaming 巩固 | openclaw |

## 优先级调整（竞品结论驱动）

1. **A 与 C 保持最高优先级**（不变）：内核硬化 + 记忆渐进披露是最大杠杆，竞品结论（Claude Code 的恢复转移表、claude-mem 的预算化注入）强烈印证。
2. **B 的工具目录查询（G29）提前**：CLI-Anything 证明"按需发现工具"是 agent 可扩展性的前提，值得在 B 阶段头一个做。
3. **D 的设备节点模型（openclaw）补强 device_registry**：不只是缓存能力，还要"配对审批 + caps 声明"，这直接复用 openclaw 的成熟模型，比自创 registry 更稳。
4. **E 不新增机制**：竞品分析确认 rak-runtime 学习模块已领先（反射/规则/轨迹/双流进化全有），E 只做闭环度量 + 落盘 + 护栏（curator 模式），不发明新算法。

## 编码场景特有、不必学的

- **文件/编辑工具族**（apply_patch/read/grep/glob/Edit 语义/TurnDiffTracker）——具身大脑不需要代码编辑工具面
- **Workspace 沙箱/文件系统边界**——设备的"边界"是动作白名单与设备权限，不是路径
- **AGENTS.md 项目指令发现**——除非要读多仓库指令
- **Prompt cache 指纹/本地 completion 缓存（claw-code）**——代理环境成本优化，语义缓存已存在
- **CodeWhale/TUI 模式 UI 状态机、终端渲染**——终端交互问题
- **40+ 聊天渠道适配 + 多平台消息投递矩阵（openclaw）**——具身大脑留一个可替换通道抽象即可
- **ClawHub/agentskills.io 市场分发 + 技能信任信封**——除非未来做第三方技能市场
- **Kanban 多 agent 工作队列（hermes）**——除非做多机器人协作，PA-HPS 调度已覆盖
