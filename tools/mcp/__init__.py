"""
MCP 工具包：mcp_call 客户端（调用外部 MCP stdio server）
"""
from tools.mcp.mcp_call import McpCallTool

MCP_TOOLS = [McpCallTool()]

__all__ = ["McpCallTool", "MCP_TOOLS"]
