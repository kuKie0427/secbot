"""mcp_call — 调用外部 MCP stdio server 的工具（list_tools/call_tool）。sensitivity=high。

对齐 TS mcp-call.tool.ts：
- 每次调用独立 spawn + connect + close；stderr 捕获进错误负载
- 参数名是 `tool`（不是 tool_name）；action 缺省 call_tool
- 超时上限为 Python 侧安全增强（TS 依赖 SDK 默认），差异记录 docs/MCP.md
"""
import asyncio
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolResult

MCP_ACTIONS = {"list_tools", "call_tool"}
CALL_TIMEOUT_S = 120  # 安全增强：单次 MCP 调用硬上限


class McpCallTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="mcp_call",
            description="List or call tools from an external MCP stdio server.",
        )
        self.sensitivity = "high"

    async def execute(
        self,
        command: str = "",
        action: str = "call_tool",
        tool: str = "",
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        input: Optional[Dict[str, Any]] = None,
        timeout: int = CALL_TIMEOUT_S,
        **kwargs,
    ) -> ToolResult:
        command = (command or "").strip()
        action = (action or "call_tool").strip()
        tool_name = (tool or "").strip()
        args_list = [str(a) for a in (args or [])]
        arguments = input if isinstance(input, dict) else {}
        timeout_s = min(int(timeout or CALL_TIMEOUT_S), CALL_TIMEOUT_S)

        if not command:
            return ToolResult(success=False, result=None, error="Missing parameter: command")
        if action not in MCP_ACTIONS:
            return ToolResult(success=False, result=None, error=f"Unsupported action: {action}")
        if action == "call_tool" and not tool_name:
            return ToolResult(success=False, result=None, error="Missing parameter: tool")

        # SDK errlog 需要带 fileno 的真实文件对象（StringIO 会报 'fileno'）
        import tempfile

        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
            return await asyncio.wait_for(
                self._run(command=command, action=action, tool_name=tool_name,
                          args_list=args_list, arguments=arguments, cwd=cwd,
                          errlog=errlog),
                timeout=timeout_s,
            )

    async def _run(self, *, command, action, tool_name, args_list, arguments, cwd, errlog) -> ToolResult:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            return ToolResult(success=False, result=None, error="mcp SDK 未安装：uv add mcp")

        params = StdioServerParameters(command=command, args=args_list, cwd=cwd)

        try:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if action == "list_tools":
                        tools = await session.list_tools()
                        return ToolResult(
                            success=True,
                            result={"tools": [t.model_dump(exclude_none=True) for t in tools.tools]},
                        )
                    result = await session.call_tool(tool_name, arguments=arguments)
                    payload = result.model_dump(exclude_none=True)
                    return ToolResult(
                        success=not result.isError,
                        result=payload,
                        error="MCP tool returned error" if result.isError else "",
                    )
        except Exception as e:
            errlog.seek(0)
            tail = errlog.read().strip()
            return ToolResult(
                success=False,
                result={"stderr": tail} if tail else None,
                error=f"{e}\n{tail}" if tail else str(e),
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "MCP server 可执行命令"},
                    "args": {"type": "array", "items": {"type": "string"}, "description": "命令参数"},
                    "cwd": {"type": "string", "description": "工作目录（可选）"},
                    "action": {"type": "string", "enum": ["list_tools", "call_tool"], "description": "动作（默认 call_tool）"},
                    "tool": {"type": "string", "description": "目标工具名（call_tool 必填）"},
                    "input": {"type": "object", "description": "调用参数对象"},
                    "timeout": {"type": "integer", "description": f"超时秒（上限 {CALL_TIMEOUT_S}）"},
                },
                "required": ["command"],
            },
        }
