# rak-runtime

Owner：YYHYCR

## 方向

rak rumtime 在 MVP 只做“最小决策服务”：接收**Go**的**gRPC Execute**请求，返回可执行的 `action + params_json`，并用稳定可复现的规则输出。

【新增】同时集成**实时语音转文字(ASR)感知模块**，提供本地低延迟的语音输入能力。

## 我负责（MVP）

- 提供 gRPC `RuntimeService.Execute`
- 保证 `trace_id` 原样透传
- 返回动作必须在 `available_actions` 范围内
- 返回错误必须用明确 `status=error + error_code + error_message`

【新增】
- 提供 gRPC `RuntimeService.StreamASR` 流式接口
- 本地Whisper模型实时语音转写，延迟<500ms
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

## MVP 最小动作集

- `shake_head`
- `wave_hand`
- `lock_open`
- `lock_close`


## 【新增】MVP 感知能力集
- `speech_to_text`：实时中文语音转文字

## 文档入口

- [docs/INDEX.md](./docs/INDEX.md)

## 权威来源（全局协调文档）

- Runtime MVP 边界：`/home/xrak/Desktop/C4/RakTec/docs/运行时/Runtime-MVP边界.md`
- 云层统一接口 v0（gRPC 部分）：`/home/xrak/Desktop/C4/RakTec/docs/接口/云层统一接口-v0.md`
- RakMessage v0：`/home/xrak/Desktop/C4/RakTec/docs/协议/RakMessage-v0.md`
