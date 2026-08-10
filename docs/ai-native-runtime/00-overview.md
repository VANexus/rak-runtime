# AI-Native Runtime & Agent Harness — 总纲

> 面向 rak-runtime（具身智能大脑）的前沿 AI-native runtime 与 agent harness 设计文档集。
> 本目录（`docs/ai-native-runtime/`）是一整套设计文档的入口与索引。

## 定位

rak-runtime 不是纯编码工具（Claude Code / OpenCode），但**内核要像它们**——拥有生产级 agent 循环、工具系统、上下文管理与权限模型；不是通用个人管家（OpenClaw / Hermes），但**能力要像它们**——主动性、跨会话持久状态、多通道通信、可扩展技能；它的核心是**具身智能大脑**：通过 A2A / gRPC / MCP 与硬件驱动双向通信，以仿生认知（心跳、情绪、需求、联想）实现生命感。

这整套文档回答一个具体问题：**把 rak-runtime 从"决策服务 + 已激活的认知层"升级为"AI-native 前沿的 agent 运行时与工具挂具（harness）"**，每一步借鉴什么、为什么、怎么做。

## 设计原则（顶层，贯穿全套文档）

1. **上下文是有限资源，一切围绕"最小高信号 token 集"**（Context Engineering 第一原则）。
   系统提示分区、工具返回 token 高效、just-in-time 加载 vs 预检索权衡、压缩/笔记/子代理三技术。

2. **渐进式披露（Progressive Disclosure）**：启动只加载元数据，触发时加载正文，按需深入附属文件。
   适用于技能（SKILL.md 三阶段）、记忆（claude-mem 式注入）、设备能力（agent card 发现）。

3. **Agent 循环是核心，其余都是挂具**。agent loop（LLM↔工具↔观察）稳定可诊断，工具、权限、钩子、
   MCP、记忆都是可插拔的挂件。

4. **工具越少越好，接口越清晰越好**。"若人类工程师无法明确说出某场景该用哪个工具，agent 也不可能做得更好。"

5. **优雅降级是硬约束**。任何外部依赖失败 → 标记不可用 → 系统继续。LLM→agent 内核→JSON 决策→规则引擎，
   一条降级链到底。

6. **双向出站**。大脑不只是被调用的决策服务；它能主动说话、告警、派发任务（Outbound → MQTT/A2A）。

7. **仿生 ≠ 演戏**。情绪/需求/联想是真实状态机（事件驱动 + 衰减），影响行为但不伪造。

## 文档地图

| # | 文档 | 内容 | 状态 |
|---|------|------|------|
| 00 | `overview.md`（本文件） | 总纲、设计原则、文档索引 | ✅ |
| 01 | `agent-kernel.md` | Agent 主循环：LLM↔工具↔观察、状态、错误/重试、流式 | ⏳ |
| 02 | `tool-harness.md` | 工具系统：定义/注册/校验/MCP/权限/钩子/沙箱 | ⏳ |
| 03 | `context-memory.md` | 上下文工程 + 记忆体系：压缩/检索/注入/跨会话 | ⏳ |
| 04 | `capability-skills.md` | 技能与能力体系：SKILL.md、插件、渐进披露 | ⏳ |
| 05 | `protocol-communication.md` | 协议层：A2A/gRPC/MCP 双向通信、agent card、出站 | ⏳ |
| 06 | `embodied-brain.md` | 具身层：仿生认知、心跳、主动性、硬件驱动 | ⏳ |
| 07 | `evolution.md` | 学习与自进化：反思、技能沉淀、策略自适应 | ⏳ |
| 08 | `roadmap.md` | 差距清单 + 分阶段实施路线（从当前代码库出发） | ⏳ |

## 分析来源

- **竞品代码深挖**（`/mnt/shared/XRAK/ce`，4 组并行分析）：
  - 编码内核：codex（Rust）、opencode（TS）、claw-code（Rust）、CodeWhale（Rust）
  - Claude Code 生产内核：`anthropic-ai-claude-code-2.1.88`
  - 管家 agent：openclaw（TS）、hermes-agent（Python）
  - 记忆/插件：claude-mem、CLI-Anything
- **行业前沿方法论**：
  - Anthropic Context Engineering（有效上下文工程）
  - Anthropic Agent Skills（渐进式披露、SKILL.md 开放标准 agentskills.io）
  - A2A 协议 v1.0（Agent Card / tasks / SSE / 多绑定）
- **rak-runtime 现状基线**：130 单测全绿；gRPC+A2A+MCP 三协议共存；LangGraph agent 内核；三层记忆 + 活体图谱 + 联想流；心跳（InnerLoop/Proactive/Sleep）常驻。

## 当前基线（rak-runtime，2026-08）

```
gRPC :50051  Execute/StreamASR      ── go-kernel → 大脑
A2A  :8000   Agent Card + tasks/send ── 外部 agent/硬件驱动 → 大脑
MCP  stdio/HTTP 14 工具              ── Claude Code 等 → 大脑
心跳  InnerLoop · ProactiveEngine · SleepConsolidation（单一常驻 asyncio loop）
内核  LangGraph ReAct（认知工具 + finalize）→ 降级单发 JSON → 规则引擎
记忆  三层记忆 · LivingGraph 扩散激活 · MemoryStream 联想 · AgenticRAG
出站  speak/alert → MQTT（RakMessage v0）/ A2A 设备派发（RAK_OUTBOUND 门控）
```

## 阅读指引

- 想快速知道"改什么"：读 `08-roadmap.md` 的差距清单。
- 想理解"为什么这样设计"：读 `01` 与 `06`。
- 想动手实现某一块：对应章节即可，每章有现状 → 差距 → 目标设计 → 落地步骤。
