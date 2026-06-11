# rak-runtime 任务清单

## 已完成

- [x] gRPC 服务端（Execute + StreamASR）
- [x] LLM 决策引擎（Anthropic API，15s 超时，规则兜底）
- [x] 三层认知记忆（工作/短期/长期 + 反思引擎）
- [x] Agentic RAG 多跳检索
- [x] 睡眠整合（记忆巩固+遗忘+反思）
- [x] MCP 技能服务器（13 工具 + 7 资源）
- [x] PersonaPlex 远程 ASR 双管线
- [x] PostgreSQL + Redis 持久化（自动降级）
- [x] **Phase 1: 清理本地推理依赖** — 移除 torch/whisper/sounddevice
- [x] **Phase 2: 认知增强模块**
  - [x] PromptEngine — 动态系统提示词构建（注入记忆+技能+设备状态+洞察）
  - [x] SemanticCache — 高频查询缓存（精确匹配 <1ms + 语义匹配 ~5ms）
  - [x] LearningLoop — 执行反馈→经验沉淀→提示词优化
  - [x] WorldModel — 设备状态地图+状态转移预测+异常检测
- [x] **Phase 3: 深度集成**
  - [x] 决策引擎接入 SemanticCache/PromptEngine/LearningLoop
  - [x] MCP 服务器接入 WorldModel/LearningLoop
  - [x] runtime_server.py 串联所有模块
- [x] **Phase 4: 三层认知架构**
  - [x] UserModel — 用户画像+意图推断+偏好学习+纠正历史
  - [x] MetaCognition — 置信度评估+策略选择+自我反思+不确定性处理
  - [x] ProactiveEngine — 异常告警+需求预测+主动监控
  - [x] 决策引擎接入元认知+用户模型（四层决策）
  - [x] MCP 服务器新增 5 个认知工具 + 2 个资源
- [x] **Phase 5: 生命体架构**
  - [x] SelfModel — 自我认知（身份+能力+性格+关系+信念）
  - [x] NeedEngine — 需求引擎（基于系统信号的内部驱动力）
  - [x] MemoryStream — 联想记忆流（随机激活→语义联想→洞察涌现）
  - [x] EmotionState — 情绪动力学（六维情绪+事件驱动+衰减）
  - [x] 决策引擎接入全部生命体模块（五层决策）
  - [x] MCP 服务器新增 4 个生命体工具 + 4 个资源
- [x] **Phase 6: 活体知识图谱**
  - [x] LivingGraph — 节点+边+权重+时间衰减+扩散激活
  - [x] 扩散激活算法（替代 TopK 检索）
  - [x] 自动建图（从交互中学习实体和关系）
  - [x] 赫布学习（一起激活的连接自动增强）
  - [x] 决策引擎双通道记忆（扩散激活 + 传统检索）
  - [x] MCP 服务器新增 2 个图谱工具 + 1 个资源
- [x] **Phase 7: 内心循环（Agent 的心跳）**
  - [x] InnerLoop — 持续运行的内心循环（感知→情绪→需求→联想→决策→表达）
  - [x] 自我叙事（"我最近在想什么"）
  - [x] 主动开口能力（能量>0.8 时主动说话）
  - [x] 内心独白注入 prompt（让 LLM 知道 Agent 的持续思考）
  - [x] MCP 服务器新增 2 个内心工具 + 2 个资源（共 21 工具 + 14 资源）

## 待做

### P1 — 与 go-kernel 深度联动
- [ ] rak-runtime 返回动作带置信度，go-kernel 用于更新 SkillNet Hebbian 权重
- [ ] go-kernel 设备状态通过 gRPC 传入 WorldModel
- [ ] go-kernel SkillNet 高置信度命中时跳过 rak-runtime（<1ms 直接执行）
- [ ] ProactiveEngine 告警推送到 go-kernel（WebSocket/MQTT）

### P2 — 认知增强
- [ ] UserModel 持久化到 PostgreSQL（多设备同步）
- [ ] MetaCognition 置信度校准（从实际成功率反调阈值）
- [ ] ProactiveEngine 需求预测精度优化（更多行为特征）
- [ ] 情绪感知（从语音特征/文本语气推断用户情绪状态）

### P3 — 增强记忆
- [ ] PostgreSQL pgvector 向量检索（当前只有 SQLite + JSON）
- [ ] Redis 短期记忆缓存
- [ ] 记忆压缩优化（相似记忆合并）

### P4 — 测试和部署
- [ ] 端到端测试更新（适配新架构）
- [ ] Docker 部署配置
- [ ] 性能基准测试

## 技术要点

- Proto 定义在 `protos/runtime.proto`，修改后需重新生成 `generated/`
- 纯 Agent 工程：禁止引入 torch/whisper/sounddevice 等本地推理依赖
- go-kernel SkillNet 已做技能向量检索，rak-runtime 不重复实现
- 用户数据只存本地 JSON，不上传（隐私保护）
