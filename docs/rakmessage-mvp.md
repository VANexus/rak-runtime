# params_json 与 RakMessage 的映射（MVP）

目标：让 Go 可以把 Runtime 输出直接变成 MQTT cmd 的 RakMessage/action，不再二次设计字段。

## 映射规则

Runtime 输出：

- `action` → RakMessage.action
- `params_json`（JSON 字符串）→ `JSON.parse(params_json)` → RakMessage.params

Go 侧推荐：

- `target`：`device:{device_id}`
- `source`：`cloud:go-gateway`
- `trace_id`：原样透传

## params_json 约束

- 必须是合法 JSON 对象字符串（例如 `"{}"`、`"{\"speed\":100}"`）
- 不依赖 `device_id`（设备由 Go 决定并体现在 MQTT topic 中）

## 例子：Runtime 输出 → MQTT cmd

ActionResponse（ok）：

```json
{
  "version": "v0",
  "trace_id": "9f0e7b14-bf58-4b6a-9a2a-8f4e7f8e6001",
  "action": "shake_head",
  "params_json": "{\"speed\":100}",
  "status": "ok",
  "error_code": "",
  "error_message": ""
}
```

对应 MQTT cmd payload（RakMessage/action）：

```json
{
  "version": "v0",
  "type": "action",
  "trace_id": "9f0e7b14-bf58-4b6a-9a2a-8f4e7f8e6001",
  "source": "cloud:go-gateway",
  "target": "device:esp32-001",
  "action": "shake_head",
  "params": {
    "speed": 100
  },
  "data": {},
  "timestamp": 1710000002
}
```
