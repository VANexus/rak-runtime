# 06 — 具身智能大脑（Embodied Brain）

> 这是 rak-runtime 区别于编码 agent 与通用管家的核心：**大脑有身体**。
> 仿生认知（心跳/情绪/需求/联想）是内在状态机，硬件通信（A2A/gRPC/MCP）是外在手脚。

## 现状

- **心跳活着**：单一常驻 asyncio loop 跑 InnerLoop（事件驱动三层节奏）+ ProactiveEngine（30s 检查）+ SleepConsolidation（15min 整合）
- **情绪/需求**：六维情绪事件驱动 + 衰减；六维需求由真实信号推导；都注入决策 prompt
- **自我认知**：SelfModel（身份/能力/性格/关系/信念）
- **活体图谱 + 联想流**：扩散激活记忆，联想洞察注入决策
- **出站**：InnerLoop speak / ProactiveEngine alert → outbound → MQTT/A2A（RAK_OUTBOUND 门控）
- **硬件通信**：gRPC（go-kernel 单向入站）+ A2A（Agent Card + tasks/send 双向）+ MCP（外部可连）
- **世界模型**：设备状态地图 + 状态转移预测 + 异常检测

## 差距

1. **出站默认关**：大脑还不能主动说话/动（`RAK_OUTBOUND=1` 才真发）。主动表达没在真实链路验证。
2. **世界模型未进决策**：`predict_next_state` / `detect_anomaly` 在决策 prompt 中很少体现——
   大脑决策时不"想象后果"，异常不阻断当前动作。
3. **设备发现静态**：`RAK_DEVICE_AGENTS` 是 env 静态配置；没有运行时发现/注册。
4. **主动性规则化**：ProactiveEngine 靠时间规律预测（rule-based）；没有让 LLM 判断"该不该主动"。
5. **情绪未反向驱动工具选择**：情绪只改 prompt 措辞；压力大时应该倾向确认/保守动作（工具级），目前没有。
6. **无"身体预算"**：能耗/执行频率/设备健康度不约束决策——真机器会磨损。

## 目标设计

### 1. 感知 → 决策 → 行动的完整回路

```
硬件状态/事件（MQTT/A2A/gRPC）
   → WorldModel 更新
   → 情绪/需求更新（InnerLoop 事件）
   → 异常检测：命中高危 → 直接阻断（不进 agent 循环）
   → 决策（agent 内核，注入世界模型预测 + 身体预算）
   → 动作（execute_action → 权限门 → A2A/MQTT 派发）
   → 结果回喂 → WorldModel 转移记录 + 反射弧学习 + 记忆
```

### 2. 世界模型进决策（想象后果）

- 决策 prompt 注入：当前设备状态 + `predict_next_state(候选动作)`（"如果执行 X，预计结果 Y"）。
- 这给 LLM"反事实评估"能力（参考 SiRA）：选动作前想象结果。
- 异常检测（`detect_all_anomalies`）→ 高危异常在 agent 循环外直接触发紧急路径。

### 3. 设备发现动态化

- **MCP 客户端拉入**：硬件驱动作为 MCP 服务器注册，大脑运行时发现其工具 → 注入 agent 循环。
- **A2A 发现**：设备 agent 通过 Agent Card 广播能力，大脑缓存 + 更新 `device registry`。
- 目标：新硬件 = 跑一个 MCP/A2A 服务，大脑自动获得新能力（无需改核心代码）。

### 4. 主动性升级（LLM 判断 + 规则保底）

- 保留 rule-based 触发（时间规律/异常），但**是否真正打扰用户**由 LLM 判断：
  `should_interrupt(need, user_context, priority)` 工具 → yes/no + 措辞。
- 出站通道保持门控（`RAK_OUTBOUND=1`），但分级：critical 告警（安全）恒放行，普通打扰需确认。

### 5. 情绪 → 行为（工具级）

| 情绪状态 | 行为倾向 |
|----------|----------|
| 压力高（stress>0.6） | 动作类工具权限升级为 ask；回复更简洁 |
| 自信高（confidence>0.7） | 允许直接执行已知安全动作 |
| 恐惧高（fear>0.6） | 所有动作 ask，倾向 emergency_stop 兜底 |

- 实现：权限门读 `EmotionEngine` 派生状态，动态调整 device 类工具的 ask/allow 阈值。

### 6. 身体预算（Body Budget）

- `WorldModel` 增加 `body_budget`：能耗率、执行频率上限、设备健康度。
- 决策前检查：动作是否超出预算 → 拒绝或降频。
- 这是真机器（电机/舵机会磨损）的硬约束，也是"具身"区别于纯软件的标志。

## 落地步骤

1. 决策注入世界模型预测 + 异常阻断路径
2. 设备 registry（MCP 客户端发现 + A2A card 缓存）
3. 主动性的 LLM 判断层（`should_interrupt` 工具）
4. 情绪 → 权限门联动
5. `body_budget` 进世界模型 + 决策约束

## 竞品借鉴

### openclaw（具身最相关的管家）

| openclaw 设计 | 移植到 rak-runtime | 对应差距 |
|---|---|---|
| **记忆五层 tier + provenance 门控 + dreaming 后台巩固**：Instructions/MEMORY.md 常驻、daily notes 可搜索、provenance 类（untrusted/system）结构性禁止进常驻提示、确定性门+有界模型 consolidate | 设备传感器/LLM 输出/外部内容标为 `untrusted`，禁止进入常驻提示；记忆巩固移出回复路径（写入路径是安全边界）——具身设备 24h 跑，记忆污染是实害 | G8/G10 |
| **Standing intents（前瞻记忆编译成触发器）**：事件型意图（"设备状态满足条件时主动动作"）编译为带 trigger 字段的确定性 prefilter，匹配路径零模型调用 | "设备状态满足 X → 主动动作"建模为 standing intent，入站设备事件先跑确定性 prefilter，命中即触发（不每次问 LLM） | G20 |
| **Heartbeat + 隔离 cron 会话 + watchdog**：周期主会话 turn + `HEARTBEAT_OK` 静默 token；isolated 会话 60 分钟 watchdog、3 分钟脚本中断、10 连败自动禁用 | 具身巡检（夜巡/电量/日志）用隔离会话 + watchdog，无人值守防失控 | G20 |
| **技能 markdown + 加载期门控 + 会话快照**：设备操作流程（校准/安全规程/故障排查）写成 SKILL.md，`requires.bins` 门控 | 校准/安全规程 SKILL.md 按"依赖的设备/CLI 是否在位"门控，会话开始快照保缓存稳定 | G12/G13 |

### hermes（自进化 + 服务门控）

| hermes 设计 | 移植 | 对应差距 |
|---|---|---|
| **Footprint Ladder + `check_fn` 服务门控工具**：工具未配置时 `check_fn` 返回 False → schema 从模型可见集消失，零 footprint | 具身动作集（移动/摇头/锁）按"该设备是否在线/配置"门控：设备离线时工具从 schema 消失，绝不常驻 | G19/G20 |
| **curator 式技能生命周期**：只动 agent 创建的技能、永不删除只归档、pinned 豁免、技能使用遥测（use_count/patch_count） | 大脑自主沉淀技能时的安全护栏：只归档不删、pinned 豁免、遥测驱动淘汰 | G23 |
| **SQLite+FTS5 会话 + CJK trigram** | 中文设备日志/指令的记忆检索直接可用 | G27 |
| **cron script 预跑注入**：脚本 stdout 注入 prompt、`no_agent=True` 纯脚本 | 定时设备数据采集（读传感器）预跑注入，不占 agent turn | G20 |

### 具身特有（无竞品可抄，原创）

世界模型"想象后果"、身体预算（能耗/频率/健康度）、异常阻断、情绪→权限门联动——管家 agent 没有身体，这些是 rak-runtime 的原创设计，也是它区别于"通用管家"的本质。
