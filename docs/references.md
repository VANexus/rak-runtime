# rak-runtime 设计参考文献

本文档记录 rak-runtime 架构设计和实现中参考的学术论文和技术方案。

---

## 1. 流式推理优化

### StreamMA: Step-Level Streaming Multi-Agent
- **核心思想**: Agent 间通信从"全量传输"改为"步级流式传输"。每个推理 step 生成后立即转发给下游 agent，不等待整个响应完成。
- **关键发现**: 头部步骤质量高、尾部步骤容易出错。流式模式让下游 agent 先接触可靠的早期步骤，错误的晚期步骤到达时下游已有推理动量，错误影响被稀释。
- **应用**: `_llm_decide` 和 `_llm_decompose` 使用 `client.messages.stream()` 实现流式提前返回，JSON 出现即返回，不等待 stream 结束。
- **效果**: 延迟从 6-15s 降至 1.7-4.6s。

---

## 2. 学习闭环

### Reflexion: Language Agents with Verbal Reinforcement Learning
- **作者**: Shinn, Cassano, Berman, Gopinath, Narasimhan, Yao (2023)
- **链接**: https://arxiv.org/abs/2303.11366
- **核心思想**: 用语言本身作为学习媒介。失败后立即生成自然语言自我反思，分析错误原因和改进方案，存入记忆缓冲区。下次尝试时将反思注入上下文。
- **应用**: `LearningLoop._reflexion_reflect()` — 纠正/失败时立刻触发 LLM 反思，产出洞察注入 PromptEngine。

### ExpeL: LLM Agents Are Experiential Learners
- **作者**: Zhao, Huang, Xu, Lin, Liu, Huang (AAAI 2024)
- **链接**: https://arxiv.org/abs/2308.10144
- **核心思想**: 对比成功和失败的轨迹，提取可复用的规则。不是记录原始经验，而是用 LLM 抽象出因果规则。
- **应用**: `LearningLoop._expel_analyze()` — 累积足够样本后，LLM 对比成功/失败案例，提取经验规则。

### Mistake Notebook Learning (MNL)
- **链接**: https://arxiv.org/abs/2512.11485 (Dec 2025)
- **核心思想**: 批量聚类相似失败，提取共性错误模式。外部记忆只在批次性能提升时更新（稳定性保证），防止噪声污染知识。
- **应用**: `LearningLoop._batch_cluster_mistakes()` — 批量聚类失败模式，有稳定性保证才更新洞察。

### Voyager: An Open-Ended Embodied Agent with LLMs
- **作者**: Wang, Xie, Jiang, Mandlekar, Xiao, Zhu, Fan, Anandkumar (NVIDIA/Caltech, 2023)
- **核心思想**: 自动课程 + 技能库 + 迭代提示。成功完成的任务抽象为可执行代码并存储复用。技能随时间复合增长。
- **应用**: `LearningLoop._maybe_extract_skills()` — 成功模式重复 3+ 次时抽象为可复用技能。

---

## 3. 认知架构

### CoALA: Cognitive Architectures for Language Agents
- **作者**: Sumers, Yao, Narasimhan, Griffiths (Princeton, TMLR 2024)
- **链接**: https://arxiv.org/abs/2309.02427
- **核心思想**: 将 LLM agent 映射到认知科学概念。三种记忆类型（工作/情景/语义），动作分为内部（推理、检索、规划）和外部（工具使用、环境交互）。元认知是独立的内部动作。
- **应用**: rak-runtime 的三层认知架构（Execution/User Model/Meta-Cognitive Layer）直接受此框架启发。

### CogRec: Fusing LLMs and Soar
- **链接**: https://arxiv.org/abs/2512.24113 (Dec 2025)
- **核心思想**: 混合神经-符号架构。LLM 初始化 Soar 的产生式规则。当符号引擎遇到无规则匹配的 impasse 时，查询 LLM 获取解决方案，然后通过 chunking 机制转换为新规则——实现在线学习无需重训练。
- **应用**: `CogRecEngine` — 规则引擎 + LLM 教学。每次 LLM 成功处理查询，提取规则存入规则库，下次直接匹配，渐进式减少 LLM 调用。

### Sophia: Persistent Agent Framework with System 3
- **链接**: https://arxiv.org/abs/2512.18202 (Dec 2025)
- **核心思想**: 添加 "System 3" 层监督叙事身份和长期适应。四个组件：过程监督思维搜索、叙事记忆、用户/自我建模、混合奖励系统。重复操作推理步骤减少 80%。
- **应用**: `SelfModel` 和 `UserModel` 的设计参考了 Sophia 的叙事记忆和用户建模。

---

## 4. 记忆系统

### A-MEM: Agentic Memory for LLM Agents
- **链接**: https://arxiv.org/abs/2502.12110 (Feb 2025, NeurIPS 2025)
- **核心思想**: Zettelkasten 方法。每个记忆成为结构化笔记（上下文描述、关键词、标签），找到语义相关的现有记忆并创建双向链接。整合新记忆可以追溯更新旧记忆的上下文表示。
- **应用**: `LivingGraph` 的扩散激活和赫布学习受此启发。未来可加入记忆回溯更新。

### MemMachine: Ground-Truth-Preserving Memory System
- **链接**: https://arxiv.org/abs/2604.04853 (Apr 2026)
- **核心思想**: 存储完整对话 episode（非有损提取）。三层记忆：短期、长期情景、用户画像。检索代理根据查询复杂度自适应路由。
- **应用**: `PersistentMemoryManager` 的设计参考了 MemMachine 的分层存储思想。

### Hindsight: Memory that Retains, Recalls, and Reflects
- **链接**: https://arxiv.org/abs/2512.12818 (Dec 2025)
- **核心思想**: 四个逻辑网络：世界事实、代理经历、实体摘要、演化信念。三个操作：Retain、Recall、Reflect。时间感知的实体记忆层。用 20B 开源模型在 LongMemEval 上达到 83.6%，超越 GPT-4o 全上下文。
- **应用**: rak-runtime 的 WorldModel/UserModel/SelfModel 四模块架构与此高度对应。

### MemGPT: Towards LLMs as Operating Systems
- **作者**: Packer, Wooders, Lin, Fang, Patil, Stoica, Gonzalez (UC Berkeley, 2023)
- **链接**: https://arxiv.org/abs/2310.08560
- **核心思想**: 操作系统启发的分层记忆。LLM 上下文窗口 = RAM，外部存储 = 磁盘。LLM 自己管理什么在上下文中、什么归档。
- **应用**: `LearningLoop._maybe_consolidate_memory()` — 缓冲区满时 LLM 决定保留什么、归档什么。

### Decision-Theoretic Agent Memory Management (DAM)
- **链接**: https://arxiv.org/abs/2512.21567 (Dec 2025)
- **核心思想**: 将记忆管理建模为不确定性下的序贯决策问题。删除记忆前评估长期效用和风险。
- **应用**: 记忆淘汰策略参考了 DAM 的效用-风险权衡思想。

---

## 5. 规划与推理

### SPIRAL: Symbolic LLM Planning via Grounded and Reflective Search
- **链接**: https://arxiv.org/abs/2512.23167 (Dec 2025, IBM)
- **核心思想**: MCTS 中嵌入三个专用 LLM：Planner（规划）、Simulator（模拟结果）、Critic（评分反思）。将 MCTS 从暴力搜索转为引导式自纠正推理。
- **应用**: 未来可加入决策前的动作模拟（SiRA 风格），在发送 MQTT 命令前预测结果。

### SiRA: Simulative Reasoning Architecture
- **链接**: https://arxiv.org/abs/2507.23773 (Jul 2025)
- **核心思想**: LLM 世界模型维护自然语言信念状态。执行反事实评估——在选择动作前模拟各候选动作的结果。任务完成率比反应式基线高 124%。
- **应用**: `WorldModel` 的状态预测可扩展为反事实评估层。

### ADaPT: As-Needed Decomposition and Planning
- **链接**: https://arxiv.org/abs/2311.05772 (Nov 2023, extended 2025)
- **核心思想**: 递归分解——只在 LLM 无法直接执行时才分解子任务。失败的子任务进一步分解。自适应分解深度。
- **应用**: `DecisionEngine.decide_from_text()` 的多动作分解可改为 ADaPT 风格的按需分解。

---

## 6. 自我进化

### MOBIMEM: Self-Evolution Without Model Retraining
- **链接**: https://arxiv.org/abs/2512.15784 (Dec 2025)
- **核心思想**: 三种专用记忆原语：Profile Memory（用户偏好对齐，23.83ms 检索，比 GraphRAG 快 280×）、Experience Memory（多级模板）、Action Memory（精细交互序列 + record-and-replay）。
- **应用**: `ActionMemory` — 记录成功的完整决策轨迹，相似查询直接重放，跳过 LLM。

### CASCADE: Cumulative Agentic Skill Creation
- **链接**: https://arxiv.org/abs/2512.23880 (Dec 2025)
- **核心思想**: 从 "LLM + 工具使用" 转向 "LLM + 技能获取"。两个元技能：持续学习（搜索、代码提取、记忆利用）和自我反思（内省、知识图谱探索）。GPT-5: 93.3% 成功率（无进化 35.4%）。
- **应用**: 技能库设计参考了 CASCADE 的累积技能创建。

### SCOPE: Prompt Evolution for Agent Effectiveness
- **链接**: https://arxiv.org/abs/2512.15374 (Dec 2025)
- **核心思想**: 双流机制——战术记忆（即时纠错，自动过期）和战略记忆（冲突解决、包含剪枝、合并）。透视驱动探索并行演化多个提示。在线优化循环从执行轨迹合成指南。
- **应用**: `PromptEvolution` — 战术/战略双流提示词进化，不同更新和过期策略。

---

## 7. 安全与治理

### VIGIL: Reflective Runtime for Self-Healing Agents
- **链接**: https://arxiv.org/abs/2512.07094 (Dec 2025)
- **核心思想**: 状态门控管道监督兄弟 agent。摄入行为日志，评估为结构化情感表示，存入 EmoBank。RBT 诊断将行为分类为优势/机会/失败。修复生成产生受保护的提示更新。
- **应用**: `SafetyGovernance` — 运行时安全监督层，在 LLM 输出和实际执行之间拦截危险模式。

### Bridging Symbolic Control and Neural Reasoning
- **链接**: https://arxiv.org/abs/2511.17673 (Nov 2025)
- **核心思想**: 结构化认知循环 + 治理层。治理层桥接符号控制（规则安全约束）和神经推理（LLM 灵活性），执行硬约束不可被神经推理覆盖。
- **应用**: 安全治理层的硬约束设计（时间窗口限制、状态验证等）。

---

## 8. 多 Agent 协作

### S-DAG: Subject-Based Directed Acyclic Graph for Multi-Agent Reasoning
- **链接**: https://arxiv.org/abs/2511.06727 (Nov 2025, AAAI 2026)
- **核心思想**: GNN 分析输入识别相关主题并推断依赖关系，生成 Subject-DAG。每个 LLM 获得主题特定的专业分数。每个主题节点选择最佳模型。
- **应用**: 未来可将安全子任务路由到安全专用模型，偏好子任务路由到偏好模型。

### ExtAgents: Scaling Knowledge via Multi-Agent Collaboration
- **链接**: https://arxiv.org/abs/2505.21471 (May 2025, ACL 2026)
- **核心思想**: 将大规模外部知识分布在多个并行运行的 LLM agent 中。绕过上下文窗口限制。高并行保持效率。
- **应用**: 长设备历史分析可分块并行处理。

---

## 9. IoT / 具身智能

### SimuHome: Temporal Smart Home Benchmark
- **链接**: https://arxiv.org/abs/2509.24282 (Sep 2025, ICLR 2026 Oral)
- **核心思想**: 基于 Matter 协议的高保真智能家居模拟器。时间加速模拟工作流调度。关键发现：工作流调度是最难的任务类别。
- **应用**: 验证了 rak-runtime 面向的场景的真实难度。

### REFLEX: Metacognitive Reasoning for Robotic Planning
- **链接**: https://arxiv.org/abs/2505.14899 (May 2025)
- **核心思想**: 两部分元认知循环：技能分解（从已完成任务中识别可复用模块化技能）和自我反思（面对未见场景时分析失败并合成新方案）。
- **应用**: 技能分解和元认知反思直接应用于 IoT 设备协调。

### LLM-Empowered Agentic AI for Industrial IoT
- **链接**: https://arxiv.org/abs/2512.20997 (Dec 2025)
- **核心思想**: RAG 语义意图推断 + DRL 编排 + 增量记忆持续学习。切片可用率提升 19%。
- **应用**: 增量记忆机制用于持续学习设备交互模式。

---

## 10. 评估基准

### TAU-bench: Tool-Agent-User Interaction Benchmark
- **链接**: https://arxiv.org/abs/2406.12045 (2024)
- **核心思想**: 三方评估：Tool、Agent、User。评估多轮对话中的工具使用和策略遵循。

### ETOM: Tool Orchestration Benchmark in MCP Ecosystem
- **链接**: https://arxiv.org/abs/2510.19423 (Oct 2025, EACL 2026)
- **核心思想**: 五级课程从单工具到复杂跨服务器规划。关键发现：刚性层级 MCP 结构会损害性能。
- **应用**: MCP 工具编排设计参考。

### ProtocolBench + ProtocolRouter
- **链接**: https://arxiv.org/abs/2510.17149 (Oct 2025, ICML 2026)
- **核心思想**: 比较 A2A/ACP/ANP/Agora 等协议。完成时间跨协议差异达 36.5%。可学习路由器选择场景协议。
- **应用**: gRPC vs MQTT 协议选择参考。

---

## 设计决策追溯

| rak-runtime 组件 | 主要参考论文 | 设计决策 |
|-----------------|-------------|----------|
| `decision_engine.py` 四层决策 | CoALA | 认知架构的内部/外部动作分离 |
| `decision_engine.py` 流式 LLM | StreamMA | 流式提前返回，JSON 出现即返回 |
| `learning_loop.py` 事件驱动反思 | Reflexion + ExpeL | 纠正即时反思，样本累积批量分析 |
| `learning_loop.py` 技能提取 | Voyager + CASCADE | 成功模式抽象为可复用技能 |
| `learning_loop.py` 记忆整合 | MemGPT | LLM 决定保留/归档/丢弃 |
| `memory_engine.py` 三层记忆 | CoALA + Hindsight | 工作/短期/长期 + 关键词兜底 |
| `memory_persistence.py` | MemMachine | 完整 episode 存储，非有损提取 |
| `living_graph.py` 扩散激活 | A-MEM | 语义链接 + 赫布学习 |
| `self_model.py` 自我认知 | Sophia | 叙事身份 + 能力/限制/信念 |
| `user_model.py` 用户画像 | Sophia + MOBIMEM | 偏好学习 + 纠正历史 |
| `meta_cognition.py` 置信度评估 | CoALA | 元认知作为独立内部动作 |
| `prompt_engine.py` YAML 模板 | SCOPE | 模板外置，支持动态渲染 |
| `world_model.py` 状态预测 | SiRA | 设备状态跟踪 + 异常检测 |
| `proactive_engine.py` 主动智能 | VIGIL | 运行时监控 + 主动告警 |
| `inner_loop.py` 事件驱动心跳 | CoALA | 感知→联想→决策→表达循环 |
| `emotion_state.py` 情绪动力学 | VIGIL (EmoBank) | 六维情绪 + 事件驱动 + 时间衰减 |
| `CogRecEngine` 规则学习 | CogRec | LLM 教规则引擎，渐进减少 LLM 调用 |
| `ActionMemory` 动作重放 | MOBIMEM | record-and-replay，已知模式跳过 LLM |
| `PromptEvolution` 提示词进化 | SCOPE | 战术/战略双流，不同过期策略 |
| `SafetyGovernance` 安全治理 | VIGIL + 符号-神经桥接 | 硬约束不可被 LLM 覆盖 |
