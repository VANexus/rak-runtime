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

> ⏳ 待竞品分析返回后补充：CodeWhale 的 extensions/integrations 机制、CLI-Anything 的插件发现与隔离、
> openclaw 的 skills 注册体系、Claude Code 的 MCP client 工具注入。
