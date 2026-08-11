# 02 — 工具系统（Tool Harness）

> 工具是大脑的"手"：既向内摸（认知工具），又向外伸（设备动作）。目标是**最小可行工具集、
> 清晰的接口、token 高效的返回、安全的执行**。

## 现状

rak-runtime 现有三套工具表达：

| 形态 | 位置 | 数量 | 消费者 |
|------|------|------|--------|
| LangChain `@tool` | `src/core/agent_loop.py` | 6（search_memory/query_device/get_emotion/get_needs/reflect/finalize） | 进程内 LangGraph agent |
| FastMCP 工具 | `src/mcp/fastmcp_server.py` | 14 | 外部 MCP 客户端 |
| A2A 技能 | `src/a2a/server.py` | 3（decision/memory/embodiment） | 外部 A2A agent |

**问题**：三套表达各自为政，同一认知能力（如"查记忆"）在三处重复实现，接口漂移；
工具返回未做 token 预算；动作类工具没有权限门；工具定义无版本/发现/自描述统一。

## 目标设计

### 1. 单一工具源（Single Source of Truth）

**一个 `src/tools/registry.py`，定义大脑全部能力的工具清单，三种形态从中派生**：

```python
# src/tools/registry.py
TOOL_DEFS = {
  "search_memory": ToolDef(
    name="search_memory", category="cognitive", # cognitive | device | system | meta
    description="检索长期记忆与经验", 
    input_schema={...}, 
    handler="src.core.memory_engine.recall",   # 函数路径
    permission="allow",                         # allow | ask | deny
    token_budget=500,                           # 返回截断
  ),
  "execute_action": ToolDef(
    name="execute_action", category="device",
    permission="ask",  # 动作需确认
    ...
  ),
}
```

- **LangGraph agent** 从 registry 生成 `@tool`（只取 cognitive 类 + 当前权限放行的）
- **FastMCP** 从 registry 生成 `@mcp.tool()`（全量，permission 在 handler 内执行策略）
- **A2A Agent Card** 从 registry 生成 skills（按 category 分组）
- **单一事实源**：加一个能力 = 改 registry 一处；三种协议自动同步

### 2. 最小可行工具集原则

> "若人类工程师无法明确说出某场景该用哪个工具，agent 也不可能做得更好。"

- 每个工具：一个明确职责、自包含、返回 token 高效（`token_budget` 截断 + 摘要）。
- 拒绝功能重叠（现状：`get_emotion`/`get_needs`/`get_self_info` 重叠为 `get_cognitive_state` 一个即可）。
- 工具 description 精心撰写（它是渐进披露第一层，决定 agent 是否触发）。

### 3. MCP 集成（双向）

- **作为 MCP Server**（已有 FastMCP）：大脑暴露神经元给外部。
- **作为 MCP Client**（新增）：大脑能连接外部 MCP 服务器（如硬件驱动的 MCP、工具 MCP），
  把外部能力作为工具注入 agent 循环——**这是"具身可扩展"的关键**：新硬件驱动 = 一个 MCP 服务器，
  大脑自动发现其工具。

### 4. 权限与沙箱

- 权限在工具层统一执行（`permissions.py`，见 01）：cognitive=allow，device=ask，outbound=deny。
- 沙箱分级：
  - cognitive/device 工具：进程内执行（已有降级保护）
  - 外部 MCP 客户端拉入的工具：进程隔离（subprocess/容器）——恶意/不可信 MCP 服务器是攻击面
- `emergency_stop` 永远放行（具身硬约束）。

### 5. 工具返回协议（token 高效）

统一返回封装：`{ok, data, summary, truncated}` —— 长数据只给 `summary`（agent 决策用）+ `data` 截断，
需要完整数据再调一次带 `full=True` 的工具。这直接对抗上下文腐烂。

## 落地步骤

1. `src/tools/registry.py`：ToolDef + 注册表 + 从 registry 生成三形态
2. 重构 `agent_loop.py` / `fastmcp_server.py` / `a2a/server.py` 使用 registry
3. `src/core/mcp_client.py`：MCP 客户端（连接外部服务器，注入工具）
4. 工具返回封装 `tool_result()` + token 预算
5. 权限模型落地（与 01 的 permissions 共用）

## 竞品借鉴

### CLI-Anything（插件化 CLI agent 框架，HKUDS）

直接对治"三形态工具各自为政"与"动作编排"两大问题：

| CLI-Anything 设计 | 移植到 rak-runtime | 对应差距 |
|---|---|---|
| **Registry + preflight 工具目录**：`registry.json`（工具 id/描述/requires/entry_point）+ `cli-hub list/search/install` + `preflight --json`（exit 3=缺口） | ToolDef registry 之外再加**目录查询**：MCP 暴露 `tool list/search/preflight`，agent 按需发现而不是全量暴露 14 个工具 | G5 |
| **Capability 矩阵（跨工具编排）**：把"产出一条视频"建模为 capability × provider 矩阵 | 14 个原子动作建模成"目标 × 动作序列"能力矩阵，preflight 检查设备在位/动作可用 | G19/G20 |
| **JSON 输出契约 + exit-code 语义**：所有命令可 `--json` 机器消费；退出码 0/1/2/3 分级（0 成功 / 3 前置缺口） | 工具返回统一 `{ok, data, summary, truncated}` + 结构化错误码（对齐 grpc-contracts 的 error_code 语义） | G6 |
| **"包装真实设备，绝不重实现"**：CLI 只 subprocess 调真实软件，产物由真实软件产出并 E2E 验证 | rak-runtime 动作保持为对 go-kernel/设备的命令转发，不在 Python 侧重实现设备逻辑；工具测试用 E2E 验证真实产物 | G7 |
| **meta-skill（发现即能力）**：把"发现并安装 CLI"本身做成一个 SKILL.md | 把"发现并启用设备/工具"做成大脑技能（`device_discovery`），agent 任务需要时先查再启用 | G13/G19 |

**不必学的**：CLI-Anything 是纯工具编排（无记忆/无认知/无具身）；其价值是工具层工程（发现/契约/编排），不是架构。

### Claude Code（MCP client + 工具元数据）

- **MCP client 连接管理**：`connectToServer` memoize 并发去重、连接生命周期管理、运行时 `refreshTools()` 每轮把新连接 server 的工具纳入下一轮、工具命名 `mcp__<server>__<tool>`、权限走 `allowedMcpServers/deniedMcpServers`。→ rak-runtime 的 `mcp_client.py` 直接抄这套：并发去重连接 + 每轮刷新 + 命名空间 + server 级权限。
- **工具一等对象元数据**（详见 01）：`isConcurrencySafe/isReadOnly/isDestructive/maxResultSizeChars/checkPermissions`——编排层只读元数据决定并发/沙箱/权限/结果预算。→ ToolDef registry 的字段集以此为蓝本。

### CodeWhale（extensions/integrations）

- **扩展插件面而非特判 core**：能力注册到通用插件面（hooks/工具/CLI 命令），core 保持窄腰。→ rak-runtime 的 ToolDef registry 就是"窄腰"，新能力走 registry + 目录，不硬编码进决策引擎。
- **project overlay 只能收紧**：仓库内配置只能把权限/沙箱往更严方向移动，不能加凭据/放权。→ 设备 skill 自带配置只能收紧动作权限，不能放宽——物理安全不变量。
