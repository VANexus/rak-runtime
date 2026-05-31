# rak-runtime

Owner：YYHYCR

## 方向

rak rumtime 在 MVP 只做“最小决策服务”：接收**Go**的**gRPC Execute**请求，返回可执行的 `action + params_json`，并用稳定可复现的规则输出。

【新增】同时集成**实时语音转文字(ASR)感知模块**，提供本地低延迟的语音输入能力，支持双引擎一键切换。

## 新增文件结构说明
```structure
rak-runtime/
├── src/
│ ├── tools/
│ │ ├── asr_tool.py # Whisper ASR 工具类
│ │ ├── personaplex_client.py # PersonaPlex ASR 客户端（新增）
│ │ └── mqtt_publisher.py # MQTT 消息发布工具
├── realtime_asr.py # Whisper 方案入口
├── realtime_personaplex.py # PersonaPlex 方案入口（新增）
├── pyproject.toml # 依赖声明
└── requirements.txt # 锁定依赖版本
```

## 架构说明
项目目前支持两种ASR架构，可根据需求切换：

| 方案 | 架构 | 延迟 | 运行环境 | 适用场景 |
|------|------|------|----------|----------|
| Whisper | ASR→文本→MQTT串行 | ~500ms | 本地Mac/PC | 开发调试、无GPU环境 |
| PersonaPlex | 端到端音频流 | ~200ms | 服务器GPU | 生产环境、低延迟要求 |

## 我负责（MVP）

- 提供 gRPC `RuntimeService.Execute`
- 保证 `trace_id` 原样透传
- 返回动作必须在 `available_actions` 范围内
- 返回错误必须用明确 `status=error + error_code + error_message`

【新增】
- 提供 gRPC `RuntimeService.StreamASR` 流式接口
- 支持双ASR引擎，可根据环境一键切换：
  - 本地Whisper模型：稳定可靠，延迟<500ms，无GPU依赖
  - PersonaPlex端到端模型：低延迟优化，延迟<200ms，支持边说边转
- 支持中文语音识别，输出UTF-8纯文本
- ASR模块完全解耦，可独立启停

## 我不负责（MVP）

- MQTT 管理与设备连接
- 前端推送与云层路由
- 长期记忆、多步规划、技能市场
- OTA 作为必须能力（只允许占位）

【新增】
- 不负责语音合成(TTS)
- 不负责语义理解和意图识别
- 不负责云端ASR服务对接
- 不负责音频文件转写（仅支持实时麦克风流）

## 对齐契约（必须一致）

- gRPC proto：见 [protos/runtime.proto](./protos/runtime.proto)
- gRPC 语义与样例：见 [docs/grpc-contracts.md](./docs/grpc-contracts.md)
- params_json 映射 RakMessage.params：见 [docs/rakmessage-mvp.md](./docs/rakmessage-mvp.md)

【新增】
- ASR流式接口契约：见 [docs/grpc-contracts.md#asr-流式接口](./docs/grpc-contracts.md)
- PersonaPlex服务端部署：见 [docs/personaplex-deployment.md](./docs/personaplex-deployment.md)

## MVP 最小动作集

- `shake_head`
- `wave_hand`
- `lock_open`
- `lock_close`


## 【新增】MVP 感知能力集
- `speech_to_text`：实时中文语音转文字（支持Whisper/PersonaPlex双引擎）

## 快速开始

### 环境准备
1. 克隆仓库
```bash
git clone https://github.com/YYHYCR/rak-runtime.git
cd rak-runtime
```

2. 创建虚拟环境并安装依赖
```bash
uv venv --python 3.8
source .venv/bin/activate
uv pip install -r requirements.txt
```

3. 
方案 1：Whisper ASR（默认，稳定，本地可运行）
> 无需额外配置，直接在本地 Mac/PC 上运行，适合开发调试和 MVP 验证。
```bash
# 启动实时语音转写服务
python realtime_asr.py
```

方案 2：PersonaPlex AS（低延迟，推荐生产环境）
>基于 NVIDIA PersonaPlex 的端到端全双工语音转写，延迟比 Whisper 降低 50% 以上，支持边说边转。

> 前置条件：需要服务器端启动 **PersonaPlex** 服务才能使用
```bash
# 启动PersonaPlex客户端
python realtime_personaplex.py
```

## 文档入口

- [docs/INDEX.md](./docs/INDEX.md)
- [PersonaPlex 服务端部署指南](./docs/personaplex-deployment.md)

## 权威来源（全局协调文档）

- Runtime MVP 边界：`/home/xrak/Desktop/C4/RakTec/docs/运行时/Runtime-MVP边界.md`
- 云层统一接口 v0（gRPC 部分）：`/home/xrak/Desktop/C4/RakTec/docs/接口/云层统一接口-v0.md`
- RakMessage v0：`/home/xrak/Desktop/C4/RakTec/docs/协议/RakMessage-v0.md`