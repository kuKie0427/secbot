"""流式 UI 工具分类常量 — 对齐 TS terminal-ui/src/streamConstants.ts（逐字）。

三类工具的渲染形态：
- TRANSIENT_TOOLS：完成后收起、不强调展示、不生成观察块
- EXPLORING_TOOLS：联网检索/Web Research → 「探索」样式
- TERMINAL_TOOLS：系统命令/持久终端 → 「终端」样式
"""

# 完成后收起、不强调展示的工具（也不生成观察块）
TRANSIENT_TOOLS = frozenset({
    "system_info",
    "network_analyze",
    "report_generator",
})

# 联网检索 / MCP / Web Research 能力 → 「探索」样式
EXPLORING_TOOLS = frozenset({
    "web_research",
    "web_crawler",
})

# 系统命令 / 持久终端会话 → 「终端」样式
TERMINAL_TOOLS = frozenset({
    "execute_command",
    "terminal_session",
})


def tool_class(tool_name: str) -> str:
    """返回工具渲染分类：transient / exploring / terminal / default。"""
    if tool_name in TRANSIENT_TOOLS:
        return "transient"
    if tool_name in EXPLORING_TOOLS:
        return "exploring"
    if tool_name in TERMINAL_TOOLS:
        return "terminal"
    return "default"
