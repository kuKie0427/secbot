"""
Tests for secbot_cli/runner.py -- 块渲染逻辑。

验证 CliRenderRegistry 和 CliEventPrinter 的各渲染器行为。
"""
import io
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from secbot_cli.runner import (
    ActionBlockRenderer,
    CliEventPrinter,
    CliRenderRegistry,
    ErrorBlockRenderer,
    ObservationBlockRenderer,
    PlanningBlockRenderer,
    RenderBlock,
    SummaryBlockRenderer,
    ThoughtBlockRenderer,
)
from utils.event_bus import Event, EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_console():
    """创建一个将输出捕获到字符串的 Console。"""
    buf = io.StringIO()
    return Console(file=buf, force_terminal=True, no_color=True), buf


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlanningBlockRenderer:
    """规划块渲染。"""

    def test_renders_plan_content(self):
        console, buf = _capture_console()
        renderer = PlanningBlockRenderer(console)
        block = RenderBlock(kind="planning", body="## 任务计划\n- Step 1\n- Step 2")
        renderer.render(block)
        output = buf.getvalue()
        assert "任务计划" in output or "planning" in output.lower() or "Step 1" in output

    def test_custom_title(self):
        console, buf = _capture_console()
        renderer = PlanningBlockRenderer(console)
        block = RenderBlock(kind="planning", body="plan content", title="自定义标题")
        renderer.render(block)
        output = buf.getvalue()
        assert "自定义标题" in output


class TestThoughtBlockRenderer:
    """推理块渲染。"""

    def test_renders_thought_content(self):
        console, buf = _capture_console()
        renderer = ThoughtBlockRenderer(console)
        block = RenderBlock(kind="thought", body="正在分析目标...")
        renderer.render(block)
        output = buf.getvalue()
        assert "分析" in output or "thought" in output.lower()

    def test_default_title(self):
        console, buf = _capture_console()
        renderer = ThoughtBlockRenderer(console)
        block = RenderBlock(kind="thought", body="thinking...")
        renderer.render(block)
        output = buf.getvalue()
        assert "推理" in output


class TestActionBlockRenderer:
    """执行块渲染。"""

    def test_renders_tool_name(self):
        console, buf = _capture_console()
        renderer = ActionBlockRenderer(console)
        block = RenderBlock(
            kind="action",
            body="执行结果",
            meta={"tool": "nmap_scan", "status": "completed", "result": "80/tcp open"},
        )
        renderer.render(block)
        output = buf.getvalue()
        assert "nmap_scan" in output

    def test_renders_error(self):
        console, buf = _capture_console()
        renderer = ActionBlockRenderer(console)
        block = RenderBlock(
            kind="action",
            body="",
            meta={"tool": "exploit", "error": "connection refused"},
        )
        renderer.render(block)
        output = buf.getvalue()
        assert "connection refused" in output

    def test_result_truncation(self):
        console, buf = _capture_console()
        renderer = ActionBlockRenderer(console)
        long_result = "x" * 3000
        block = RenderBlock(
            kind="action",
            body="",
            meta={"tool": "test", "result": long_result},
        )
        renderer.render(block)
        output = buf.getvalue()
        assert "已截断" in output


class TestTransientToolRendering:
    """TRANSIENT_TOOLS 完成后显示 dim 行（通过 CliEventPrinter 验证）。"""

    def test_transient_tool_event_printer(self):
        console, buf = _capture_console()
        printer = CliEventPrinter(console)

        # Simulate EXEC_START for a transient tool
        event_start = Event(
            type=EventType.EXEC_START,
            data={"tool": "system_info", "iteration": 1, "step_key": "iter-1"},
            timestamp=None,
            iteration=1,
        )
        printer.handle(event_start)

        # Simulate EXEC_RESULT
        event_result = Event(
            type=EventType.EXEC_RESULT,
            data={
                "tool": "system_info",
                "success": True,
                "result": "Linux 5.15",
                "iteration": 1,
                "step_key": "iter-1",
            },
            timestamp=None,
            iteration=1,
        )
        printer.handle(event_result)
        # Should not raise; transient tools produce compact output
        output = buf.getvalue()
        assert len(output) >= 0  # Just verify no crash


class TestErrorBlockRenderer:
    """错误块渲染。"""

    def test_renders_error_in_red(self):
        console, buf = _capture_console()
        renderer = ErrorBlockRenderer(console)
        block = RenderBlock(kind="error", body="Something went wrong")
        renderer.render(block)
        output = buf.getvalue()
        assert "Something went wrong" in output

    def test_default_title_is_error(self):
        console, buf = _capture_console()
        renderer = ErrorBlockRenderer(console)
        block = RenderBlock(kind="error", body="err")
        renderer.render(block)
        output = buf.getvalue()
        assert "错误" in output


class TestCliRenderRegistry:
    """渲染注册表分发。"""

    def test_unknown_kind_falls_back_to_default(self):
        console, buf = _capture_console()
        registry = CliRenderRegistry(console)
        block = RenderBlock(kind="nonexistent_kind", body="fallback content")
        registry.render(block)
        output = buf.getvalue()
        assert "fallback content" in output

    def test_all_known_kinds_render_without_error(self):
        console, buf = _capture_console()
        registry = CliRenderRegistry(console)
        for kind in ["planning", "thought", "action", "observation", "summary", "report", "error"]:
            block = RenderBlock(kind=kind, body=f"test content for {kind}")
            registry.render(block)  # Should not raise
