# SSE 事件契约 — 双端比对表

> 事实源：TS 仓 `server/src/modules/chat/`（chat.service.ts / chat.controller.ts / sse-event-forwarder.ts）
> 与前端消费方 `web/src/hooks/useChat.ts`（事件 switch）。
> Python 端：`router/chat.py::_event_to_sse` + `_interaction_event_generator`。
> 原则：**事件名逐字对齐 TS**；Python 多出的字段为增量（前端忽略未知字段，无害）。

## 比对表（事件名 × 双端状态）

| 事件名 | TS 服务端 | Python 服务端 | 前端 useChat | 字段契约（snake_case） | 差异说明 |
|---|---|---|---|---|---|
| `connected` | ✅ chat.service:74 | ✅ 首包 | ✅ break | `message` | 一致 |
| `planning` | ✅ emitPlanningSse（scope: master\|adaptive） | ✅ | ✅ | `content, summary, scope, todos[{id,content,status}]` | Python 额外带 `agent`（增量无害） |
| `thought_start` | ✅ forwarder | ✅ | ✅ | `iteration, step_key, task?` | Python 用 `agent` 替代 TS 的 `task`（均可选，前端不读） |
| `thought_chunk` | ❌ **TS SSE 不发**（forwarder 无 THINK_CHUNK 分支；仅枚举存在） | ✅ | ✅（reasoning_chunk 别名兜底） | `chunk, iteration, step_key` | **Python 增强**：增量渲染推理；TS 端整段下发。前端两种都兼容 |
| `thought` | ✅ | ✅ | ✅ | `content, iteration, step_key` | 一致（THINK_END 映射） |
| `action_start` | ✅ | ✅ | ✅ | `tool, params, iteration, step_key` | `view_type` 双端都不发；前端默认 'raw'（豁免项） |
| `action_result` | ✅（`result` 取 `observation`） | ✅ | ✅ | `tool, success, result, iteration, step_key` | Python 额外 `view_type, error, agent`（增量） |
| `action_end` | ❌ TS 不发 | ❌ | ✅（与 action_result 同分支，防御性别名） | 同 action_result | 双端一致地不发；前端冗余分支 |
| `content` | ✅ | ✅ | ✅ | `content, view_type?, tool?` | Python `view_type` 默认 summary（TS 不带时前端也按 summary） |
| `report` | ✅ | ✅ | ✅ | `content`（report 文本） | 一致 |
| `phase` | ✅（exploring/executing/planning/summarizing） | ✅ | ✅ | `phase, detail` | 一致 |
| `context_usage` | ✅ emitContextUsage | ✅ | ✅ | `model, context_window, prompt_budget, used_tokens, reserved_tokens, ratio, focus, pinned` | 一致 |
| `explore_start` | ✅ | ✅ | ✅ | `focus` | Python 额外 `browser_session_id, userInput`（增量） |
| `explore_step` | ✅ | ✅ | ✅ | `iteration, kind, tool, observation, thought` | Python 额外 `agent` |
| `explore_end` | ✅ | ✅ | ✅ | `facts_count, unresolved, summary` | 一致 |
| `context_patch` | ✅ | ✅ | ❌ 前端不消费 | `facts_count, pinned, unresolved, summary` / 失败时 `facts_count, error` | 一致（含错误分支） |
| `intent_decision` | ✅ | ✅ | ❌ 前端不消费 | `intent, confidence, needs_explore, needs_report, focus, rationale` | 一致 |
| `clarify` | ✅ | ✅ | ❌ 前端不消费 | `question` | 一致 |
| `response_chunk` | ✅ chat.service:411（流式收尾） | ✅ Phase 7 补齐（QA 流式 on_chunk → RESPONSE_CHUNK） | ✅ | `chunk` | 一致；provider 不支持流式时 Python 静默降级整段 `response` |
| `response` | ✅ | ✅（finally 汇总） | ✅ | `content, agent` | Python 额外 `view_type` |
| `error` | ✅ `{error, code, statusCode}` | ✅ 同构（chat.py:336-345） | ✅ 读 `data.code` | `error, code, statusCode` | 一致（Phase 6 核对确认已补 code） |
| `done` | ✅ 结束序列 | ✅ 结束序列（finally 必发） | ✅ break | `{}` | 一致：**error 后必跟 done** |
| `root_required` | ✅ | ✅ | 弹窗（chat 流外监听） | `request_id, command` | 一致；客户端 POST `/api/chat/root-response` 应答 |
| `context_debug` | ✅ 仅 `SECBOT_CONTEXT_DEBUG=1` 时 | ✅ Phase 7 修复（独立 CONTEXT_DEBUG 事件，debug 字段全量） | ❌ | `session_id, model, context_window, prompt_budget, used_tokens, reserved_tokens, session_messages, sqlite_turns, vector_hits, pinned, focus, dropped_sections` | 调试事件；双端环境门控 |

## 结束序列（硬契约）

1. 每条 SSE 消息 = `event: <name>\ndata: <json>\n\n`
2. 正常流：… → `response` → `done`
3. 异常流：`error{error, code, statusCode}` → `done`（**error 不是终止帧**，done 才是）
4. `connected` 永远是首包（前端据此脱离「连接中」）

## reasoning_* 别名层（仅前端）

useChat.ts:132-134 把 `reasoning_start/reasoning_chunk` 别名为 `thought_*` 后进入 switch。
服务端（双端）均只发 `thought_*`；别名层是为兼容旧事件名保留的防御代码。

## 已声明的差异汇总

| # | 差异 | 处置 |
|---|---|---|
| D1 | Python 发 `thought_chunk`（TS SSE 不发） | 有意增强：增量渲染；前端已兼容 |
| D2 | Python 多字段 `agent`/`view_type` 等 | 增量无害，前端忽略未知字段 |
| D3 | `action_start` 无 `view_type`（双端一致） | 豁免：前端默认 'raw' |
| D4 | `response_chunk` 降级 | provider 不支持 astream 时静默回退整段 `response`（TS 行为等价） |
| D5 | `TOAST_SHOW`/`COMMAND_EXECUTE` 枚举 | 双端均定义未用；Python 已删除枚举成员（TS 侧保留未用）——不实现任何语义 |

## 快照测试

`tests/router/test_sse_contract.py` 锁定线上事件名全集与关键字段
（step_key/iteration/view_type/planning.scope/response_chunk/context_debug 字段）。
改任一事件名 → 测试必红（mutation 验证过）；变更须显式更新快照并同步本文件。
