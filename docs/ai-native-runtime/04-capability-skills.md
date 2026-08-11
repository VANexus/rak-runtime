# 04 — 技能与能力体系（Capability & Skills）

> 技能是大脑的"肌肉记忆"：把反复成功的能力打包成可复用、可发现、渐进加载的资产。
> 采用 Agent Skills 开放标准（agentskills.io）的三层渐进披露。

## 现状

- 工具三形态（registry 缺失，见 02）各自为政
- 学习闭环会产出"洞察/规则/轨迹"，但**没有沉淀为可复用的技能文件**：
  - CogRec 规则（pattern→action）✓ 已有
  - ActionMemory 轨迹重放 ✓ 已有
  - LearningLoop 技能提取（Voyager 风格）→ `_skills` 字典，**未落盘、未结构化、agent 用不上**
- 无 SKILL.md 式的能力包（指令 + 脚本 + 参考资源，渐进加载）

## 目标设计

### 1. 技能 = 目录 + SKILL.md（渐进披露三阶段）

```
skills/
├── lock-open/                # 示例：门锁技能
│   ├── SKILL.md              # frontmatter(name, description) + 正文指令
│   ├── reference.md          # 附属参考（按需读）
│   └── open_lock.py          # 确定性脚本（agent 直接执行，不读进上下文）
├── battery-optimize/
│   └── SKILL.md
└── ...
```

- **L1 启动**：会话上下文只注入所有技能的 `name + description`（决定是否触发）。
- **L2 触发**：agent 认定相关后读 `SKILL.md` 正文。
- **L3 按需**：正文引用的附属文件/脚本，需要时才读/执行。

### 2. 技能来源（两条流）

- **人工编写**（运维/开发者）：设备操作规范、安全流程。
- **自动沉淀**（学习闭环）：把反复成功的轨迹抽象为技能——
  - 触发：同一 action+context 成功 N 次（已有 `_maybe_extract_skills` 雏形）
  - 生成：LLM 从轨迹提炼 `SKILL.md`（指令）+ 脚本
  - 验证：新技能跑一轮基准，成功率达标才入库
  - 复用：下次相似场景 agent 触发该技能 → 行为更稳、token 更省

### 3. 能力注册与三形态同步（衔接 02）

- `ToolDef registry` 是能力的单一事实源。
- 技能（SKILL.md 包）是**更重的多步工作流**，工具是**轻量单步能力**。两者互补：
  - 工具：单步、schema、MCP/A2A 暴露
  - 技能：多步、指令+脚本、agent 触发
- 技能目录也纳入 MCP/A2A 暴露（作为"procedural knowledge"资源）。

### 4. 安全

- 技能含指令与脚本 = 执行任意代码 = 攻击面。从不可信来源安装前**通读全部捆绑文件**。
- 技能执行遵循权限门：脚本执行前评估（是否连接外部网络、是否触碰物理设备）。
- `emergency_stop` 相关技能永远放行，其他设备技能需确认。

## 落地步骤

1. `skills/` 目录 + SKILL.md 规范（frontmatter + 渐进披露）
2. 会话启动注入技能索引（L1）
3. `load_skill(name)` 工具（L2/L3 读取 + 执行脚本）
4. 学习闭环 → 技能自动沉淀（提炼/验证/入库）
5. 技能纳入权限门 + 安全审查

## 竞品借鉴

### claude-mem（20 个 SKILL.md 技能集）

- 每个能力一个 SKILL.md（frontmatter name+description + 正文），`plugin/skills/` 组织。
- 技能与工具互补：claude-mem 的 MCP 工具（search/timeline/get_observations）+ 20 个技能（learn-codebase/smart-explore/standup…）。
- **skills 是"程序性记忆"**：工具给单步能力，技能给多步工作流（含指令 + 脚本 + 参考资源）。
- 印证本章结论：技能目录是活资产，可随 agent 自主发现、按需加载。

### CLI-Anything（meta-skill 模式）

- `cli-hub-meta-skill` = **一个让 agent 自主发现并安装 CLI 的 SKILL.md**："文档是市场入口"，
  agent 任务需要时先 `cli-hub search/list` 再按需 `install`（明确禁止 bulk-install）。
- `cli-hub-matrix/*/SKILL.md`：每个能力矩阵（3d-cad/video-creation…）自带技能，preflight 报缺口再精装。
- 对 rak-runtime 的直接映射：
  1. **`device_discovery` 技能**：大脑需要控制新设备时，先查 registry 再启用其 MCP/A2A 能力
  2. **技能 = 能力目录的入口**：`skills/` 不仅存流程，还存"如何发现更多能力"
  3. **preflight 式技能检查**：技能加载前先检查前置（设备在位、工具可用、权限放行）

**不必学的**：CLI-Anything 的技能是纯 CLI 编排（无认知/记忆维度）；开源的 skills 标准（agentskills.io）已吸收其渐进披露思想，直接采用标准即可。

### openclaw（最完整的技能体系）

| openclaw 设计 | 移植到 rak-runtime |
|---|---|
| **技能 = markdown 指令 + 环境门控，不是代码插件**：SKILL.md 编译成紧凑 XML 块注入系统提示（每技能 ~97 字符 ≈ 24 token），`requires.bins/env/config` 在加载期决定可用性 | 设备操作技能（校准/安全规程）按 `requires.bins`（依赖的 CLI/设备）门控，成本可预测 |
| **6 级优先级 + 每 agent allowlist**：workspace > 项目 .agents/skills > 个人 > managed > bundled > extraDirs；allowlist 控制可见性 | `skills/` 分级目录 + 大脑能力 allowlist（哪些技能对当前任务可见） |
| **会话开始快照，会话内不变**：技能集合在会话开始时定格，保 prompt cache 稳定 | agent 会话技能集快照，不动摇缓存前缀（与 01 章一致） |
| **`$skill` 引用 + 成本预算**：`maxSkillsPromptChars` 预算、描述截断 | 技能索引注入有 token 预算上限 |

**结论**：openclaw 证明"技能是程序性记忆的最轻形态"——markdown + 门控 + 快照，成本可预测。rak-runtime 直接采用 agentskills.io 标准（SKILL.md frontmatter + 渐进披露），补上门控与快照即可。
