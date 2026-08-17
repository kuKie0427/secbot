# REST API 对齐清单（Python ↔ TypeScript）

以 TS 控制器（`server/src/modules/*/[name].controller.ts` @ 2ccdb5d）为唯一事实源。
路径、方法、请求/响应字段名逐字对齐；已知差异全部列于文末，无未解释差异。

- TS 端响应走 `TransformInterceptor` 信封（`data` 包裹由 HTTP 层处理，不影响业务字段名）；
  Python 端直接返回业务对象、统一错误映射中间件（`router/main.py`），业务字段名一致。
- 请求体字段：TS DTO 为 camelCase（如 `targetIp` / `localPath`）；Python 端点同时接受
  camelCase 与 snake_case（见「差异 D7」）。

## 端点总表

### sessions（7）— `sessions.controller.ts` ✅ 对齐

| 方法 | 路径 | Python 实现 |
|---|---|---|
| POST | `/api/sessions` | `router/sessions.py` |
| GET | `/api/sessions?status=` | 同上 |
| GET | `/api/sessions/{sessionId}` | 同上 |
| GET | `/api/sessions/target/{targetIp}` | 同上 |
| POST | `/api/sessions/{sessionId}/commands` | 同上（见差异 D1） |
| POST | `/api/sessions/{sessionId}/files` | 同上 |
| POST | `/api/sessions/{sessionId}/close` | 同上（见差异 D1） |

### crawler（15）— `crawler.controller.ts` ✅ 对齐

tasks 8：`POST /tasks`、`GET /tasks`、`GET /tasks/{id}`、`GET /tasks/{id}/status`、
`POST /tasks/{id}/execute`、`POST /tasks/{id}/execute-async`、`POST /tasks/{id}/cancel`、`POST /batch`；
monitors 7：`POST /monitors`、`GET /monitors`（返回 `{monitors, events}`，200 条环形缓冲）、
`POST /monitors/{id}/check`、`POST /monitors/check-all`、`POST /monitors/start`、`POST /monitors/stop`、
`POST /monitors/{id}/remove`。实现：`router/crawler.py`。

- `execute-async` 响应仅 `{success: true}`（task id 已在路径中，不额外回传，对齐 TS）。
- 任务/监控 id 为 `{url}_{timestamp}` / `{url}_{interval}` 形态（对齐 TS），但 URL 中的
  `/` 编码为 `~` 以保证 id 可作为路径参数（见差异 D2）。

### vuln-db（6）— `vuln-db.controller.ts` ✅ 对齐

`GET /cve/{cveId}`、`POST /search`、`POST /scan-match`、`POST /sync`、`POST /clear`、`GET /stats`。
实现：`router/vuln_db.py`。`sync` 入参 `keywords/sources/limit_per_source`；`clear` 无 body、无确认参数（对齐 TS）。

### network（13）— `network.controller.ts` ✅ 对齐

发现/授权 6：`POST /discover`、`GET /targets?authorized_only=`、`POST /authorize`、
`GET /authorizations`、`GET /authorized-targets`、`DELETE /authorize/{targetIp}`；
远程控制 7：`POST /connect`、`POST /execute`、`POST /upload`、`POST /download`、
`POST /disconnect`、`GET /control/sessions`。实现：`router/network.py` +
`secbot_agent/controller/remote_control.py`（SSH 走 paramiko，SFTP 对应 upload/download）。

- connect/execute/upload/download 前置校验授权台账，未授权返回
  `{success: false, error: "Target is not authorized"}`（对齐 TS gating，403 语义）。
- execute/upload/download 自动把结果登记进该 target 的最新 active 会话台账（对齐 TS）。

### memory（12）— `memory.controller.ts` ✅ 对齐（1 处 method 差异见 D5）

`POST /remember`、`GET /context`、`GET /list`、`POST /distill`、`POST /episode`、
`POST /knowledge`、`POST /clear`、`GET /stats`、`POST /vector/add`、`POST /vector/search`、
`GET /vector/stats`；recall 见 D5。实现：`router/memory.py`。

### 其余模块（既对齐项）

- chat：`POST /api/chat`（SSE）、`POST /api/chat/root-response`（TS 另有 `sync` 端点为两端 stub，Python 未实现，见 D6）
- agents：`GET /api/agents`
- tools：`GET /api/tools`、`POST /api/tools/execute`（本阶段补齐）
- skills：`GET /api/skills`、`GET /api/skills/{name}`、`POST /api/skills`（Phase 2）
- system：`GET /api/system/config`（及其子端点）、`GET /api/system/config/providers`、`GET /api/system/config/provider/{id}`
- database / defense：Phase 0 前已对齐
- health：`GET /health`（无 `/api` 前缀，两端一致）

## 已知差异（全部有意为之）

| # | 项 | TS | Python | 说明 |
|---|---|---|---|---|
| D1 | `POST /sessions/{id}/commands` 语义 | 被动登记簿：addCommand 仅记录客户端回填的 command+result | `result` 缺省时桥接 `terminal_session` 工具会话池**真实执行**并回填输出 | **有意增强**（计划内声明）：Agent 测试过程中需要真实执行；客户端显式传 result 时行为与 TS 一致 |
| D2 | crawler 任务/监控 id 中的 `/` | `${url}_${ts}` 原样内嵌（Nest/express 对含 `/` 的路径参数同样 404） | `/` 编码为 `~` | 让 id 可作为单段路径参数；id 对客户端仍是不透明主键，`task.url` 字段保留原始 URL |
| D3 | crawler 监控循环 | service 内定时 | 进程内 asyncio 中央循环（每秒扫描，对齐 TS monitorLoop 语义，自动纳入新增监控） | 等价实现 |
| D4 | vuln-db `clear` | service 公开 clear_vectors | 经私有 `_vector_store` 委托 `VulnVectorStore.clear()` | Python service 无公开 clear 方法，委托路径一致 |
| D5 | memory recall | `GET /api/memory/recall?query=` | `POST /api/memory/recall` | **存量差异（已在计划中核实声明）**：保持 Python 现状，客户端迁移时注意 |
| D6 | chat `POST /api/chat/sync` | 存在（stub） | 未实现 | 两端均为 stub，无实际消费方；如需补齐另行登记 |
| D7 | network 请求体字段 | 仅 camelCase（`targetIp`） | camelCase 与 snake_case 均接受，响应不变 | 兼容性放宽，camelCase 优先 |
| D8 | `GET /api/system/log-level` | 无此端点 | 存在（GET/POST） | Python 独有增强，TS 无对应；保留 |
| D9 | TS `HostInfoDto` 响应字段 camelCase（`hostname` 一致；`macAddress`/`openPorts`） | camelCase | Python 返回 snake_case（`mac_address`/`open_ports`） | **存量差异**：Python web/客户端均消费 snake_case；Phase 6 Web UI 移植时以 TS 前端实际读取字段为准逐个核对 |
| D10 | MCP 服务端 input schema | 透传工具 schema | 裸 properties 包装为合法 JSON Schema（见 docs/MCP.md） | 有意增强 |
| D11 | `POST /api/system/config/provider` 请求体 | `{llm_provider}`（SetLlmProviderRequestDto） | `{llm_provider}` 与 `{provider}` 均接受（前端 ModelConfig.tsx 发 `{provider}`；TS web 与 TS 后端本身拼写不一致） | 双字段兼容，见 D7 模式 |
| D12 | `POST /api/system/config/api-key` 请求体 key 字段 | `{apiKey}`（SetApiKeyRequestDto） | `{api_key}` 与 `{apiKey}` 均接受（前端发 `api_key`） | 同 D11 |
| D13 | `POST /api/chat` 请求体 | 含 `session_id`/`client_shell`（ChatRequestDto） | Phase 6 起同构（此前缺 `session_id` 会 422） | 对齐修复 |

## 验证

```bash
uv run pytest tests/router/test_phase4_rest.py -q   # 22 tests：五组端点集成测试
uv run pytest tests/web -q                           # 11 tests：Web 托管 + 前端契约冒烟（需 make build-web）
```
