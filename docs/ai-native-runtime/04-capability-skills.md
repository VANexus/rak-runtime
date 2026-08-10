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

> ⏳ 待竞品分析返回后补充：openclaw 的 skills 体系、CLI-Anything 的 meta-skill 与插件发现、
> claude-code 的 Agent Skills 实现细节。
