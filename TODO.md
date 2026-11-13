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

> ⚠ 2026-11-14 注：本节四条对端的 go-kernel SkillNet/设备状态/语义缓存均为 AIoT 旧架构模块；
> go-kernel 已于 2026-09 重定位为 MCP 联邦网关并把这些存根列入删除计划（见 go-kernel/TODO.md
> 「后续候选 #5」）。复活本节需先经治理裁决推翻重定位，不宜直接开工。

- [ ] rak-runtime 返回动作带置信度，go-kernel 用于更新 SkillNet Hebbian 权重
- [ ] go-kernel 设备状态通过 gRPC 传入 WorldModel
- [ ] go-kernel SkillNet 高置信度命中时跳过 rak-runtime（<1ms 直接执行）
- [ ] ProactiveEngine 告警推送到 go-kernel（WebSocket/MQTT）

### P2 — 认知增强

- [x] UserModel 持久化到 PostgreSQL（多设备同步）。验收证据：**2026-11-14 完成**——新增
      `src/core/user_model_pg.py`（`user_profiles` 表 JSONB 整包 upsert，`RAG_POSTGRES_DSN`
      门控、psycopg2 可选驱动、不可用自动降级 JSON）；`UserModel` 双源加载按 `last_seen`
      仲裁取较新者，`RAK_USER_ID` 决定多设备身份；纠正记录（学习信号最强的数据）随包持久化
      ——顺带修复存量缺陷：`record_correction` 此前只存内存、重启即丢。测试
      `tests/test_user_model_pg.py` 8 用例（坏 DSN 降级 / 双源仲裁 / 旧格式兼容 / PG 同步）。
- [x] MetaCognition 置信度校准（从实际成功率反调阈值）。验收证据：**2026-11-14 完成**——
      预测置信度分桶统计实际正确率（单桶 n≥10 生效、收缩系数限幅 0.5–1.5、样本越少越趋近
      原值），`evaluate_confidence` 出分前先校准；`reflect()` 反调 high 阈值（准确率 <80%
      收紧 +0.02 至上限 0.95，≥95% 放松 −0.01 至下限 0.80）；`record_outcome` 接入
      decision_engine 的纠正/显式反馈入口（该方法原先从未被任何代码调用）。测试
      `tests/test_meta_calibration.py` 10 用例（乐观降级 / 保守上调 / 阈值限幅 / 引擎接线）。
- [x] ProactiveEngine 需求预测精度优化（更多行为特征）。验收证据：**2026-11-14 完成**——
      预测置信度由拍板 0.7 改为证据累加：时间规律 +0.2、往日不同日子重复（≥2 天）+0.15、
      高频设备（≥10 次）+0.1，基础 0.5、封顶 0.95；低频设备不再产生候选噪音。测试
      `tests/test_proactive_prediction.py` 7 用例。
- [x] 情绪感知（从语音特征/文本语气推断用户情绪状态）。验收证据：**2026-11-14 完成
      （文本语气部分）**——新增 `src/core/emotion_perception.py`：纯词典法（<1ms 实测
      0.007ms、零外部依赖、无 torch），中英情绪词 + 否定削弱翻转 + 标点强度，经
      `apply_to` 融入六维情绪态，接入 `decide()` 步骤 3.5（`perceive_llm` 为显式复核
      通道，热路径不走）。语音特征部分不做（依赖外部 ASR 情绪 API，另行立项）。测试
      `tests/test_emotion_perception.py` 13 用例。

### P3 — 增强记忆

- [x] PostgreSQL pgvector 向量检索（当前只有 SQLite + JSON）。验收证据：**2026-11-14 完成**——
      核验发现写入侧早已实现并接线（`RAG_POSTGRES_DSN` 门控，pgvector cosine + JSONB 双形态），
      真缺口在读取侧：`PrefChainPersistence.load_embeddings` 在 PG 激活时返回空 dict，重启后
      长期记忆无向量、只能关键词兜底。本次为 `PostgresMemoryBackend` 补 `load_embeddings()`
      （兼容 vector 字符串与 JSONB 两种存储形态），链上层改为真实透传。测试
      `tests/test_pg_embeddings.py` 7 用例（含"恢复后向量检索命中"端到端断言）。
- [x] Redis 短期记忆缓存。验收证据：**2026-11-14 核验完成**——`memory_redis.py` 已实现
      （TTL + Sorted-Set 索引 + working List），经 `REDIS_URL` 门控接入 `PrefChainPersistence`
      短期记忆链路；本次仅移除模块 docstring 中从未实现的 pub/sub 宣称。
- [x] 记忆压缩优化（相似记忆合并）。验收证据：**2026-11-14 完成**——原「前 20 字符前缀分组
      + 字符 Jaccard」升级为向量贪心聚类（余弦 > 0.85；按重要度降序取前 400 条、O(N²) 有界，
      被合并条目下轮腾出名额滚动覆盖全量；指纹分桶方案经实测否决——`_simple_embed` 进程内
      哈希随机化会把近重复劈进不同桶）；无向量记忆保留原前缀兜底；合并元数据与访问计数，
      并清理向量索引陈旧项。测试 `tests/test_sleep_compression.py` 7 用例（连续 3 轮稳定）。

### P4 — 测试和部署

- [x] 端到端测试更新（适配新架构）。验收证据：**2026-11-14 完成**——① 修复 `agent_loop.py`
      / `compaction.py` 两处 py3.11 不兼容的 f-string 反斜杠语法（PEP 701），此前
      `test_agent_loop / test_compaction / test_prompt_design` 三个文件完全无法收集；
      ② 4 处写死 `/tmp/rak_stub_mcp.py` 的 stub 路径（agent_loop / mcp_client / workflow /
      external_tools_suite）改为仓内 `tools_stubs/` 绝对路径，Windows 下从挂变过；③
      `test_e2e_full.py` 按 go-kernel 2026-09 重定位口径重写：移除已废弃的
      `/api/v1/action/execute` 与 PA-HPS 调度器用例，go-kernel 侧降级为可选可达性检查
      （`/api/health`、`/metrics`），rak-runtime gRPC 两用例为必测。全量套件
      **369 过 / 1 跳过 / 0 挂**（基线 277 过 / 10 挂 / 3 文件不可收集）。
- [x] Docker 部署配置。验收证据：**2026-11-14 完成**——`Dockerfile`（python:3.11-slim、
      非 root、依赖层缓存、`RAK_DATA_DIR=/app/data`）+ `docker-compose.yml`（`--profile deps`
      可选 PG17/Redis7，不配 DSN 自动降级）+ `.dockerignore`。注：本机无 Docker/WSL，
      镜像构建未实测，发版前需在有 Docker 的环境过一次。
- [x] 性能基准测试。验收证据：**2026-11-14 完成**——新增 `tests/perf_benchmark.py`
      （无 LLM 无网络，7 项，p50/p95/p99 + 吞吐），本机实测：语义缓存精确命中 p50=0.002ms、
      记忆 recall top5 p95=3.3ms、情绪感知 p50=0.007ms、置信度评估 p50=0.003ms、
      record_interaction（含写盘）p50=3.5ms。LLM 全管线时延不在此测（需 API key，
      见 llm_life_benchmark.py）。

## 技术要点

- Proto 定义在 `protos/runtime.proto`，修改后需重新生成 `generated/`
- 纯 Agent 工程：禁止引入 torch/whisper/sounddevice 等本地推理依赖
- go-kernel SkillNet 已做技能向量检索，rak-runtime 不重复实现
- 用户数据只存本地 JSON，不上传（隐私保护）
