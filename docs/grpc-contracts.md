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
