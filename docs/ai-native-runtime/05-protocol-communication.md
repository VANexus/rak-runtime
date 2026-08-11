# 05 — 协议与通信（Protocol & Communication）

> 大脑通过协议与三种"他人"说话：硬件驱动（执行）、外部 agent（协作）、工具 MCP（扩展能力）。
> 目标是**双向、可发现、标准合规**。

## 现状

| 协议 | 方向 | 现状 | 状态 |
|------|------|------|------|
| gRPC `RuntimeService` | 入站（go-kernel → 大脑） | Execute / StreamASR，:50051 | ✅ 生产 |
| A2A v1.0 | 双向 | Agent Card + tasks/send + SSE + JSON-RPC/REST，:8000 | ✅ 已实现（官方 SDK） |
| MCP（FastMCP） | 入站（外部客户端 → 大脑） | 14 工具，stdio/HTTP | ✅ 已实现 |
| MCP（客户端） | 出站（大脑 → 外部工具） | — | ⏳ 未实现 |
| A2A 出站派发 | 出站（大脑 → 设备 agent） | `RAK_DEVICE_AGENTS` → A2A/MQTT | ✅ 已实现（env 配置） |
| MQTT 出站 | 出站 | `rak/{device}/{cmd,state}` RakMessage v0 | ✅ 已实现（门控） |

## 目标设计

### 1. 统一出站抽象（Outbound Hub）

现状：出站散在 `outbound.py`（speak/alert/publish_action）。目标：统一的**出站路由**：

```
出站请求（speak / alert / execute_action）
   → 优先级路由：
     1. 目标设备有 A2A agent 且可达 → A2A tasks/send
     2. 否则 MQTT 发布（RakMessage v0）
     3. 否则记日志（不丢不崩）
   → 结果回执（成功/失败/耗时）喂给 WorldModel 转移记录 + 反射弧学习
```

### 2. 入站统一为"任务"（Task 抽象）

- gRPC Execute、A2A tasks/send、MCP execute_action、HTTP 回调 → 全部归一为**内部 Task**：
  `{task_id, text/state, available_actions, trace_id, channel}`。
- 决策结果归一为 `{action, params, answer, cognitive_state}` → 按原通道回包。
- 好处：大脑只写一份决策逻辑，四种入站共享；trace_id 全链路透传不变。

### 3. 设备发现与注册（Registry）

- `device_registry`：缓存设备 agent（A2A card / MCP server / gRPC endpoint）的能力与可达性。
- 来源：`RAK_DEVICE_AGENTS`（静态）+ MCP 客户端发现（运行时）+ A2A card 轮询（运行时）。
- 决策/出站查询 registry 找"谁能力匹配"，不再硬编码 device_id。

### 4. A2A 补齐（对齐 v1.0 规范）

- `tasks/get`、`tasks/cancel`、`tasks/query`（列表 + 过滤 + 分页）——SDK 已支持，未接出。
- push notification（webhook）——可选，`capabilities.push_notifications` 目前 false。
- 扩展 Agent Card：把 ToolDef registry 的 category 映射为 A2A skills（自动同步）。

### 5. 协议选型原则

| 场景 | 选型 | 理由 |
|------|------|------|
| 大脑 ↔ go-kernel 高频单动作 | gRPC | 低延迟、已有生态 |
| 大脑 ↔ 外部 agent / 硬件驱动（标准互操作） | A2A | 标准协议、任务生命周期、发现 |
| 大脑 ↔ 工具/能力（可插拔） | MCP | 工具发现、参数 schema、渐进披露 |
| 大脑 ↔ 设备（低带宽/离线） | MQTT | QoS、主题路由、已部署 |

原则：**gRPC 管低频高可靠、A2A 管互操作、MCP 管可扩展、MQTT 管设备**。不互相替代。

## 落地步骤

1. `src/core/outbound_hub.py`：统一出站路由 + 回执
2. 入站 Task 归一化（gRPC/A2A/MCP handler 共用决策路径）
3. `device_registry`（发现 + 缓存 + 可达性）
4. A2A 补齐 tasks/get/cancel/query
5. Agent Card 从 ToolDef registry 自动生成

## 竞品借鉴

### 关键事实：编码内核不做 A2A

codex / opencode / claw-code / CodeWhale **四个编码 agent 都没有实现 A2A**——它们全是本地单 runtime + MCP 客户端/服务端（opencode 在 `integration/connection.ts` 有 A2A 工作但未形成标准协议）。这印证了一个判断：**rak-runtime 的三协议（gRPC/A2A/MCP）比编码 agent 都超前**。协议层不需要向编码内核学互操作，要向管家学"多通道 + 节点"。

### openclaw（单一控制面 + 节点模型）

- **单一 Gateway 控制面 + 类型化 WS 协议**：一个 host 一个 Gateway，拥有所有会话/工具/事件/渠道连接；外部入口（CLI/app/automation）与 Nodes（伴侣设备）都通过它，协议是 TypeBox 定义→JSON Schema→代码生成的类型化帧。
- **设备节点模型（role:node + caps/commands + 配对审批）**：外围设备以显式能力声明接入，设备级配对审批。→ **这正是 rak-runtime ↔ go-kernel ↔ ESP/车的目标结构**：大脑作为控制面，设备以 `role:node` + 显式 caps/commands 接入，比现在 gRPC 单点对接多了"能力声明、配对审批、回连"完整模型（对应 05 章 device_registry 设计）。
- **SecretRefs + egress-time sentinels**：凭据不进配置文件明文，出网前一刻替换，未知形状哨兵 fail-closed。→ rak-runtime 的设备凭据（MQTT/A2A token）同样处理。

### hermes（gateway 多通道 + MCP 双向）

- **relay CapabilityDescriptor 握手**：`contract_version + max_message_length + supports_draft_streaming + markdown_dialect + len_unit + supported_ops`——**一个 gateway 适配器服务所有平台**，无需每通道分支。→ rak-runtime 的出站通道（MQTT/A2A/gRPC）可以同一套能力描述协商，而不是每通道写死。
- **MCP 双向**：既当 MCP client 接第三方服务器，又当 MCP server 暴露会话/工具给外部（镜像 OpenClaw 9 工具桥）。→ 印证 05 章"大脑作为 MCP 客户端拉入硬件能力"的设计。
- **cron job 字段设计**：`script` 预跑数据采集脚本（stdout 注入 prompt）、`context_from` 链式传递、`workdir` 带 AGENTS.md 加载、多平台 delivery、**3 分钟硬中断**防 runaway、catchup 窗口钳制。→ 具身定时任务（夜巡/充电检测/日志上报）直接套用这套字段。
- **后台进程通知**：`terminal(background=true, notify_on_complete=true)` → watcher 检测完成 → 触发新一轮 agent turn。→ 设备动作完成后主动触发下一轮决策（具身闭环）。

### CLI-Anything（协议侧补充）

- 不依赖 MCP 也能桥接真实软件：`subprocess + JSON 契约 + env`；只有软件本身暴露 MCP 时才走 MCP Backend Pattern。→ 印证"设备驱动优先转发命令、MCP 只是其中一种后端"的原则。
