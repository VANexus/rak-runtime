# gRPC 冻结契约（Runtime 视角）

proto 权威文件：[`protos/runtime.proto`](../protos/runtime.proto)

## 语义约束

- `version` 固定为 `"v0"`
- `trace_id` 必须原样透传
- `action` 必须满足：
  - status=ok：返回的 action 必须在 `available_actions` 中
  - status=error：action 可为空
- `params_json` 必须是合法 JSON 字符串
- `status=error` 时必须填：`error_code` `error_message`

## 错误码（MVP）

- `INVALID_STATE`：输入状态无效
- `ACTION_NOT_ALLOWED`：请求动作/返回动作不在允许集合中
- `PARAMS_INVALID`：params_json 无法解析或不合法
- `DECISION_FAILED`：决策失败
- `TIMEOUT`：处理超时

【新增】
- `ASR_INIT_FAILED`：ASR模型加载失败
- `ASR_STREAM_ERROR`：ASR音频流处理错误
- `ASR_DEVICE_ERROR`：麦克风设备访问失败

## 样例

### 1) 动作确认（action 非空）

ActionRequest：

```json
{
  "version": "v0",
  "trace_id": "9f0e7b14-bf58-4b6a-9a2a-8f4e7f8e6001",
  "source": "cloud:go-gateway",
  "target": "runtime:default",
  "state": "user_request",
  "available_actions": ["shake_head", "wave_hand", "lock_open", "lock_close"],
  "action": "wave_hand",
  "params_json": "{\"speed\":100,\"duration_ms\":800}"
}
```

ActionResponse（ok）：

```json
{
  "version": "v0",
  "trace_id": "9f0e7b14-bf58-4b6a-9a2a-8f4e7f8e6001",
  "action": "wave_hand",
  "params_json": "{\"speed\":100,\"duration_ms\":800}",
  "status": "ok",
  "error_code": "",
  "error_message": ""
}
```

### 2) 拒绝不允许动作

ActionResponse（error）：

```json
{
  "version": "v0",
  "trace_id": "9f0e7b14-bf58-4b6a-9a2a-8f4e7f8e6001",
  "action": "",
  "params_json": "{}",
  "status": "error",
  "error_code": "ACTION_NOT_ALLOWED",
  "error_message": "action not in available_actions"
}
```

---

## 【新增】ASR 流式接口

### 接口定义
```protobuf
rpc StreamASR(ASRRequest) returns (stream ASRResponse);
```

- **模式**：服务端流式（客户端发一次请求，服务端持续返回转写结果）
- **生命周期**：客户端建立连接后，服务端自动开始采集麦克风音频并转写
- **终止条件**：客户端断开连接，或服务端发生错误

### 消息定义
```protobuf
message ASRRequest {
  string version = 1;    // 固定为"v0"
  string trace_id = 2;   // 链路追踪ID
  string language = 3;   // 语言，默认"zh"
}

message ASRResponse {
  string text = 1;       // 转写结果文本
  string trace_id = 2;   // 原样透传请求的trace_id
  bool is_final = 3;     // 是否为最终结果（当前版本恒为true）
  float confidence = 4;  // 置信度（0.0-1.0）
}
```

### 语义约束
1. `version` 必须为 `"v0"`
2. `trace_id` 必须原样透传
3. 服务端每秒最多返回2次转写结果
4. 空结果不返回
5. 发生错误时，服务端关闭流并返回对应的错误码

### 样例
**请求**：
```json
{
  "version": "v0",
  "trace_id": "asr_123456",
  "language": "zh"
}
```

**响应流**：
```json
{"text": "你好", "trace_id": "asr_123456", "is_final": true, "confidence": 0.92}
{"text": "打开门", "trace_id": "asr_123456", "is_final": true, "confidence": 0.87}
{"text": "谢谢", "trace_id": "asr_123456", "is_final": true, "confidence": 0.95}
```