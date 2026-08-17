# MCP 双向支持（Model Context Protocol）

对齐 TS `server/src/mcp-server.ts` + `server/src/tools/mcp-call.tool.ts`。Python 侧提供两个方向的 MCP 能力：

- **服务端（`secbot-mcp`）**：把全部 secbot 工具暴露为 MCP stdio 工具，供 Claude Desktop / Cursor / 任何 MCP 客户端调用。
- **客户端（`mcp_call` 工具）**：让 secbot Agent 在运行时连接并调用任意外部 MCP stdio server。

## 服务端：secbot-mcp

### 启动

```bash
# 控制台脚本（pyproject.toml [project.scripts]）
uv run secbot-mcp

# 或模块方式
uv run python -m router.mcp_server
```

stdio transport，无需参数。工具目录与 `GET /api/tools` 同源（复用 `router/tools.py` 的 `_CATEGORIES` 聚合，当前 77 个非敏感工具），不存在第二套目录。

### 在 Claude Desktop 中接入

```json
{
  "mcpServers": {
    "secbot": {
      "command": "/path/to/secbot-python/.venv/bin/secbot-mcp"
    }
  }
}
```

### 敏感工具开关

`sensitivity="high"` 的工具（`attack_test` / `exploit` / `sniff` / `credential_spray` / `mcp_call`）**默认跳过**，不出现在 `tools/list` 中。

放行需设置环境变量（取值对齐 TS 的 `trim().toLowerCase()` 语义）：

```json
{
  "mcpServers": {
    "secbot": {
      "command": "/path/to/secbot-python/.venv/bin/secbot-mcp",
      "env": { "SECBOT_MCP_ALLOW_SENSITIVE": "1" }
    }
  }
}
```

`"1"` / `"true"` / `"yes"`（大小写不敏感）放行，其余值（含未设置）跳过。

### 工具注解（annotations）

与 TS 逐字一致：

| 注解 | 取值 |
|------|------|
| `readOnlyHint` | `!sensitive` |
| `destructiveHint` | `sensitive` |
| `openWorldHint` | `true` |

### 返回值

`CallToolResult` 内容为 ToolResult 的 JSON 序列化：

```json
{ "success": true, "result": { ... }, "error": "" }
```

未知工具名返回 `{"success": false, ..., "error": "Unknown tool: <name>"}`，不抛协议错误。SIGINT/SIGTERM 优雅退出。

## 客户端：mcp_call 工具

`sensitivity=high`（属敏感工具集合，默认不出现在 secbot-mcp 服务端目录中）。参数对齐 TS `mcp-call.tool.ts`：

| 参数 | 说明 |
|------|------|
| `command` | MCP server 可执行命令（必填） |
| `args` | 命令参数数组（原样传给 spawn，不做 shell 元字符解析） |
| `action` | `list_tools` / `call_tool`，缺省 `call_tool` |
| `tool` | 目标工具名（**注意：是 `tool`，不是 `tool_name`**；`call_tool` 时必填） |
| `input` | 目标工具参数对象 |
| `cwd` | 工作目录 |
| `timeout` | 超时秒数，上限 120s（安全增强） |

### 用法示例（Agent 对话中）

```
用 mcp_call 连一下 npx -y @modelcontextprotocol/server-filesystem /tmp，列出它有哪些工具
用 mcp_call 调用上面的 read_text_file，读 /tmp/notes.txt
```

每次调用独立 spawn → connect → initialize → call → close；server 崩溃时 stderr 尾部会捕获进错误负载（`result.stderr` / `error` 字段）。

## 与 TS 行为差异表

| 项 | TS | Python | 说明 |
|----|----|--------|------|
| 服务端 input schema | 透传工具 schema | 裸 properties 形态统一包装为 `{"type":"object","properties":{...}}` 并派生顶层 `required` | **有意增强**：Python 旧式工具 schema 无 JSON Schema 包裹，MCP 校验更严格，不包装会拒绝注册 |
| 客户端超时 | 依赖 SDK 默认（32s 读超时） | 单次调用硬上限 120s，入参再小也取 min | **增强**：防止 Agent 卡死在无响应的 server 上 |
| 服务端工具目录 | 单独实现 | 复用 `router/tools.py` `_CATEGORIES`（与 `GET /api/tools` 同源） | 实现收敛，行为一致 |
| 敏感开关 | `SECBOT_MCP_ALLOW_SENSITIVE` ∈ {1,true,yes} | 相同 | 逐字对齐 |
| SDK 版本 | `@modelcontextprotocol/sdk` | `mcp>=1.9,<2`（pinned） | 2.0.0 移除 `mcp.server.fastmcp` 与低层装饰器 API，暂不跟进 |

## 测试

```bash
uv run pytest tests/tools/test_mcp.py -q   # 14 tests：客户端往返/校验/崩溃、服务端注册/过滤/注解/序列化
```
