# rak-runtime 任务清单

> 对照：任务待办 任务8 | 云端推理层占位

---

## 当前状态

Mock gRPC 服务，单 RPC `Execute(ActionRequest) → ActionResponse`，返回硬编码响应。

---

## P2 — 真实 LLM 集成

### 1. 替换 Mock 实现
- [ ] 1.1 集成真实 LLM API（OpenAI / Anthropic / 本地模型）
- [ ] 1.2 实现自然语言 → 任务描述符(TD) 列表的分解逻辑
- [ ] 1.3 Structured Output 保证返回格式稳定

### 2. RAG 记忆系统（可选）
- [ ] 2.1 事实性记忆存储（向量数据库）
- [ ] 2.2 上下文检索增强
- [ ] 2.3 LoRA 微调流程（程序性知识沉淀）

---

## 技术要点

- Proto 定义在 `protos/runtime.proto`，修改后需重新生成 `generated/`
- 当前 mock 用于端到端联调，不要在真实 LLM 未就绪前删除
- Docker 部署：`docker-compose up --build`
