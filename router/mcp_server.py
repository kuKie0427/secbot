"""secbot-mcp 服务端 — 把全部 secbot 工具暴露为 MCP stdio 工具。

对齐 TS server/src/mcp-server.ts + npm-bin/secbot-mcp.js：
- stdio transport；工具来源复用 router/tools.py 的 _CATEGORIES（与 GET /api/tools 同源）
- sensitive（sensitivity=high）默认跳过；SECBOT_MCP_ALLOW_SENSITIVE ∈ {1,true,yes} 放行
- 注解 readOnlyHint=!sensitive / destructiveHint=sensitive / openWorldHint=True
- ToolResult 序列化为 JSON 文本；SIGINT/SIGTERM 优雅退出
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from tools.base import BaseTool

SERVER_NAME = "secbot-mcp"
SERVER_VERSION = "1.0.0"

# 与 TS 逐字一致的解析语义
ALLOW_SENSITIVE_VALUES = {"1", "true", "yes"}


def allow_sensitive() -> bool:
    return os.environ.get("SECBOT_MCP_ALLOW_SENSITIVE", "").strip().lower() in ALLOW_SENSITIVE_VALUES


def tool_is_sensitive(tool: BaseTool) -> bool:
    return getattr(tool, "sensitivity", "low") == "high"


def collect_all_tools() -> list[BaseTool]:
    """与 GET /api/tools 同源聚合（_CATEGORIES），不出现第二套目录。"""
    from router.tools import _CATEGORIES

    seen: dict[str, BaseTool] = {}
    for _cat_id, _cat_name, tool_list in _CATEGORIES:
        for t in tool_list:
            seen.setdefault(t.name, t)
    return list(seen.values())


def normalize_input_schema(params: object) -> dict:
    """统一包装为合法 JSON Schema。

    Python 旧式工具的 parameters 是「裸 properties」形态（{参数名: {...}}，无 type/properties 包裹，
    required 内联在属性里）；MCP 校验更严格，需包装并派生顶层 required。
    """
    if not isinstance(params, dict) or not params:
        return {"type": "object", "properties": {}}
    if "properties" in params or params.get("type") == "object":
        out = dict(params)
        out["type"] = "object"
        out.setdefault("properties", {})
        return out
    props = {
        k: {ik: iv for ik, iv in v.items() if ik != "required"} if isinstance(v, dict) else v
        for k, v in params.items()
    }
    schema: dict = {"type": "object", "properties": props}
    required = [k for k, v in params.items() if isinstance(v, dict) and v.get("required") is True]
    if required:
        schema["required"] = required
    return schema


def build_mcp_tools() -> list[Tool]:
    tools: list[Tool] = []
    skip_sensitive = not allow_sensitive()
    for t in collect_all_tools():
        sensitive = tool_is_sensitive(t)
        if sensitive and skip_sensitive:
            continue
        schema = t.get_schema() or {}
        params = normalize_input_schema(schema.get("parameters"))
        tools.append(
            Tool(
                name=t.name,
                title=t.name,
                description=t.description,
                inputSchema=params,
                annotations={
                    "readOnlyHint": not sensitive,
                    "destructiveHint": sensitive,
                    "openWorldHint": True,
                },
            )
        )
    return tools


async def call_secbot_tool(name: str, arguments: dict) -> str:
    for t in collect_all_tools():
        if t.name == name:
            result = await t.execute(**(arguments or {}))
            return json.dumps(
                {"success": result.success, "result": result.result, "error": result.error},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
    return json.dumps({"success": False, "result": None, "error": f"Unknown tool: {name}"})


async def serve() -> None:
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return build_mcp_tools()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        text = await call_secbot_tool(name, arguments or {})
        return [TextContent(type="text", text=text)]

    stop = asyncio.Event()

    def _shutdown(_sig, _frame):
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
            raise_exceptions=False,
        )


def main() -> None:
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
