# rak-runtime 架构设计

## 一句话定位

rak-runtime 是具身 AI 系统的**边缘推理引擎**：接收语音或文本输入，通过认知记忆和 LLM 决策，输出可执行的原子动作序列。

## 系统架构总览

```
                    ┌─────────────────────────────────────────────────┐
                    │                  rak-runtime                    │
                    │                                                 │
  音频流 ──────────▶│  ┌──────────┐    ┌──────────────┐               │
                    │  │ ASR 感知 │───▶│ 双管线处理器  │               │
  gRPC ───────────▶│  │ (Whisper/ │    │ (DualPipeline)│              │
                    │  │ PersonaPlex)│  └──────┬───────┘              │
                    │  └──────────┘           │                       │
                    │                    ┌────┴────┐                  │
                    │                    ▼         ▼                  │
                    │            ┌────────┐  ┌──────────┐             │
                    │            │PersonaPlex│ │ ASR+LLM  │            │
                    │            │即时回复   │ │ 深度决策  │            │
                    │            └────────┘  └────┬─────┘             │
                    │                             │                   │
                    │                    ┌────────┴────────┐          │
                    │                    ▼                 ▼          │
                    │            ┌──────────────┐  ┌─────────────┐   │
                    │            │ 决策引擎      │  │ 策略模型     │   │
                    │            │ (LLM+规则)    │  │ (基底神经节) │   │
                    │            └──────┬───────┘  └──────┬──────┘   │
                    │                   │                 │           │
                    │            ┌──────┴─────────────────┴──────┐   │
                    │            │         认知记忆引擎           │   │
                    │            │  工作记忆│短期记忆│长期记忆    │   │
                    │            │         └──Agentic RAG──┘     │   │
                    │            └──────────────┬────────────────┘   │
                    │                           │                    │
                    │            ┌──────────────┴────────────────┐   │
                    │            │        持久化存储层            │   │
                    │            │  PostgreSQL │ Redis │ SQLite  │   │
                    │            └───────────────────────────────┘   │
                    │                                                 │
                    │            ┌───────────────────────────────┐   │
                    │            │       MCP 技能服务器          │   │
                    │            │  工具发现│调用│资源│通知      │   │
                    │            └───────────────────────────────┘   │
                    └─────────────────────┬───────────────────────────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  go-kernel   │
                                   │  (gRPC/MQTT) │
                                   └──────────────┘
```

## 核心模块详解

### 1. 音频管线

`DualPipelineProcessor` 双管线设计（纯远程 API，无本地推理）：

| 管线 | 引擎 | 特性 |
|------|------|------|
| 即时回复 | PersonaPlex | WebSocket 流式，GPU 推理，延迟 ~200ms |
| 深度决策 | ASR + LLM | 语音→文本→LLM 分解→原子动作列表 |

**音频格式**：16kHz 采样率，16-bit 整数，单声道 PCM。

### 2. 双管线音频处理器

`DualPipelineProcessor` 同时运行两条管线：

**管线 1：PersonaPlex（超低延迟）**
- 音频 → PersonaPlex → 即时语音回复
- 用途：用户立刻听到回应，保证交互流畅

**管线 2：ASR + LLM（深度思考）**
- 音频 → Whisper ASR → 文本 → LLM 分解 → 原子动作列表
- 用途：认真规划要执行什么

**提示词反哺**：LLM 生成上下文提示词传递给 PersonaPlex，让后续语音回复更智能。

### 3. 决策引擎

`DecisionEngine` 是核心决策中心，15 步决策管线：

1. 复合命令检测（多动作分解）
2. 对话状态记录
3. 语义缓存查找（<1ms）+ 元认知置信度检查
4. CogRec 规则匹配（<1ms）
5. ActionMemory 重放（<1ms）
6. 用户纠正历史检查
7. 用户画像意图推断
8. 上下文组装（SelfModel + Emotion + Needs + Memory + InnerLoop + ConversationState）
9. 双通道记忆检索（LivingGraph 扩散激活 + 传统 TopK）
10. PromptEvolution 指南注入
11. 系统提示词构建
12. LLM 深思（~1s）+ 流式提前返回
13. 元认知置信度评估 + 策略选择
14. 安全治理检查
15. 缓存 + 记忆 + 学习 + 图谱 + 规则 + 反馈全面更新

**LLM 集成**：
- 使用 Anthropic API（通过代理地址 `token-plan-cn.xiaomimimo.com`）
- 模型：`mimo-v2.5-pro`
- 5 秒超时，超时自动回退到规则引擎
- 规则引擎支持中英文关键词 → 动作映射

### 4. 认知记忆引擎

`CognitiveMemoryEngine` 实现三层记忆 + 反思学习：

**工作记忆**（`WorkingMemory`）：
- 当前对话上下文，类比前额叶皮层
- 滑动窗口，容量有限（7±2 项）
- 提供 `get_context()` 供 LLM prompt 使用

**短期记忆**（`ShortTermMemory`）：
- 最近对话和事件，类比海马体短期缓冲区
- LRU 策略，按时间衰减
- `consolidate()` 方法：筛选重要记忆提升到长期

**长期记忆**（`LongTermMemory`）：
- 持久化知识和经验，类比大脑皮层
- 向量检索（ANN）实现语义查询
- 余弦相似度 + 显著性加权排序
- `prune()` 方法：移除低显著性记忆（遗忘机制）

**反思学习引擎**（`ReflectionEngine`）：
- 从执行记录中提取经验教训
- 成功模式 → 正面强化
- 失败模式 → 负面规避
- 参考 RF-Mem 工程方法

**记忆显著性公式**：
```
salience = importance × freshness × (1 + frequency)
其中：
  freshness = max(0.1, 1.0 - age_hours × decay_rate)
  frequency = min(1.0, access_count × 0.1)
```

### 5. Agentic RAG 引擎

`AgenticRAG` 实现多跳检索推理：

```
查询 → RETRIEVE → REASON → [证据充分?] → YES → SYNTHESIZE → 答案
                               │
                               NO
                               │
                               ▼
                           REFINE → 生成精化查询 → 回到 RETRIEVE
```

**两种模式**：
- **规则引擎**（`AgenticRAG`）：基于关键词匹配和证据数量
- **LLM 推理**（`AgenticRAGWithLLM`）：使用 LLM 判断证据充分性和生成精化查询

**停止条件**：
- 置信度 ≥ 阈值（默认 0.8）
- 达到最大步数（默认 5 步）
- 无法进一步精化查询

### 6. 策略模型（基底神经节）

`PolicyModel` 实现快速反射通道：

**架构**：单层线性网络（softmax 策略）
- 输入：状态向量（特征哈希，64 维）
- 输出：动作概率分布
- 学习：在线梯度更新（REINFORCE 风格）

**与 LLM 的关系**：
- LLM = 前额叶皮层（慢思考，复杂推理）
- PolicyModel = 基底神经节（快思考，直觉反应）
- 传感器紧急事件 → PolicyModel 直接响应（不经过 LLM）

**特征哈希**：将任意特征字典映射到固定维度向量，使用 FNV-1a 哈希 + 黄金比例乘法。

### 7. 持久化存储层

**PostgreSQL 后端**（`PostgresMemoryBackend`）：
- 表：`memories`（记忆条目，支持 pgvector 向量）、`execution_metrics`（执行指标时间序列）、`skill_weights`（技能权重历史）
- 支持 pgvector 余弦距离向量检索
- 支持 ILIKE 全文搜索
- JSONB 元数据查询
- 连接池管理（psycopg2 ThreadedConnectionPool）
- 降级：PostgreSQL 不可用 → SQLite

**Redis 后端**（`RedisMemoryBackend`）：
- 键设计：`rak:memory:short:{id}`（Hash）、`rak:memory:short:index`（Sorted Set）、`rak:memory:working`（List）
- TTL 自动过期（模拟遗忘曲线）
- Sorted Set 按时间戳排序
- 降级：Redis 不可用 → JSON 文件

**混合后端**（`HybridMemoryBackend`）：
- 优先 Redis，不可用时自动降级到文件后端
- Redis 恢复后自动切换回来

### 8. 睡眠整合

`SleepConsolidation` 模仿人类睡眠中的记忆巩固：

1. **短期 → 长期迁移**：筛选显著性 ≥ 阈值的记忆
2. **遗忘**：移除低显著性的旧记忆（突触修剪）
3. **反思**：分析执行记录，提取经验（支持 LLM 深度反思）
4. **压缩**：合并内容高度相似（>0.8）的记忆
5. **持久化**：保存当前记忆状态到持久化存储

**触发方式**：定时触发 / 阈值触发 / 手动触发

### 9. CogRec 神经符号混合

`CogRec` 实现 LLM 教规则引擎的混合架构（灵感来自 arXiv:2512.24113）：

- LLM 成功决策自动提取为规则引擎规则
- 规则随时间累积，LLM 调用比例逐步降低
- 纠正规则获得最高置信度（0.95）
- 子串匹配 + 动作可用性过滤

### 10. ActionMemory 记录-重放

`ActionMemory` 记录完整决策轨迹（灵感来自 MOBIMEM, arXiv:2512.15784）：

- 相似查询直接重放（<1ms）绕过 LLM
- LLM 评估模糊匹配是否适合重放
- 完整轨迹记录：输入→决策→结果

### 11. PromptEvolution 双流进化

`PromptEvolution` 实现提示词的自进化（灵感来自 SCOPE, arXiv:2512.15374）：

- **战术流**：短期纠正，成功 N 次后自动过期
- **战略流**：长期原则，永不过期
- 相关性匹配注入到决策提示词

### 12. SafetyGovernance 安全治理

`SafetyGovernance` 实现 LLM 驱动的运行时安全（灵感来自 VIGIL, arXiv:2512.07094）：

- 唯一硬约束：`emergency_stop` 始终允许
- 所有其他安全判断上下文感知（通过 LLM）
- 违规记录 + 设备状态更新

### 13. MCP 技能服务器

`SkillMCPServer` 实现 MCP（Model Context Protocol）JSON-RPC 服务器：

**内置工具**：
- `activate_skill`：自然语言 → 技能匹配
- `execute_action`：直接执行原子动作
- `query_device`：查询设备状态
- `search_memory`：搜索记忆系统
- `register_skill`：注册新技能

**内置资源**：
- `rak://devices`：设备列表
- `rak://skills`：技能列表
- `rak://memory/stats`：记忆统计

## 决策模式

### 模式 1：动作确认（Action Confirmation）

- 条件：输入 `action` 非空
- 规则：校验 action 是否在 `available_actions`，必要时补齐/修正 `params_json`

### 模式 2：状态转动作（State-to-Action）

- 条件：输入 `action` 为空
- 规则：基于 `state` + 记忆上下文，从 `available_actions` 中选择动作

### 模式 3：音频决策（Audio Decision）

- 输入：PCM 音频流
- 流程：ASR → 记忆检索 → LLM 多步分解 → 原子动作列表

### 模式 4：策略模型快速决策

- 输入：状态向量
- 流程：特征哈希 → 线性网络 → softmax → 动作 ID
- 用途：紧急事件的快速反射（不经过 LLM）

## 不变式（必须保证）

- `trace_id` 原样返回，跨 gRPC → MQTT → WS 全链路透传
- 绝不返回 `available_actions` 之外的动作
- 任何失败都以 `status=error` 返回（不允许静默失败）
- LLM 不可用时自动降级到规则引擎（用户无感知）

## 四个认知闭环

1. **记忆闭环**：感知 → 工作记忆 → 短期 → 长期 → 检索 → 决策
2. **知识闭环**：执行 → 反思 → 知识提取 → 长期记忆 → 检索
3. **学习闭环**：成功/失败 → 权重调整 → 行为优化
4. **执行闭环**：决策 → 执行 → 反馈 → 记忆 → 下次决策

## 参考论文

- arXiv:2603.07379：Agentic RAG 形式化框架
- arXiv:2603.09192：双树架构（方法即节点）
- MemGPT：可插拔记忆管理
- EverMemOS：终身记忆设计哲学
- lightMem：轻量化外挂记忆（睡眠整合 + 反思）
- RF-Mem：反思学习记忆
