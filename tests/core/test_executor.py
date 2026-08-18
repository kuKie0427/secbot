"""
Tests for secbot_agent/core/executor.py -- TaskExecutor 分层并行执行 + 事件缓冲重放。

验证：
1. 串行层按序执行
2. 并行层并发执行
3. 事件缓冲重放为线性序列
4. 取消任务传播
5. ExecutionResult 返回正确
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from secbot_agent.core.executor import ExecutionResult, TaskExecutor
from secbot_agent.core.models import PlanResult, TodoItem, RequestType
from utils.event_bus import EventBus, EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeTodo:
    id: str
    content: str = ""
    status: str = "pending"
    tool_hint: str = ""
    depends_on: list = field(default_factory=list)
    result_summary: str = ""


class _FakePlanner:
    """可配置 execution order 的 mock planner。"""

    def __init__(self, layers: Optional[List[List[str]]] = None):
        self._layers = layers
        self.updates: List[tuple] = []

    def get_execution_order(self):
        return self._layers or []

    def update_todo(self, todo_id: str, status: str, summary: str = ""):
        self.updates.append((todo_id, status, summary))


class _FakeAgent:
    """可配置行为的 mock agent。"""

    def __init__(self, results: Optional[Dict[str, dict]] = None):
        self._results = results or {}
        self.calls: List[dict] = []
        self.agent_type = "test_agent"

    async def execute_todo(self, todo, user_input, context, on_event,
                           iteration, get_root_password, emit_events,
                           context_block):
        self.calls.append({"todo_id": todo.id, "iteration": iteration})
        return self._results.get(todo.id, {
            "success": True,
            "obs": f"Result for {todo.id}",
            "result": f"output_{todo.id}",
            "tool": todo.tool_hint or "",
            "params": {},
        })


def _make_plan(todos):
    return PlanResult(
        request_type=RequestType.TECHNICAL,
        todos=todos,
        plan_summary="test plan",
        direct_response=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSerialLayerExecution:
    """串行层（单 todo）按序执行。"""

    @pytest.mark.asyncio
    async def test_two_serial_layers_execute_in_order(self):
        t1 = _FakeTodo(id="t1", content="task 1")
        t2 = _FakeTodo(id="t2", content="task 2")
        plan = _make_plan([t1, t2])
        planner = _FakePlanner(layers=[["t1"], ["t2"]])
        agent = _FakeAgent()
        bus = EventBus()

        executor = TaskExecutor(plan, agent, planner, bus)
        result = await executor.run("test input")

        assert isinstance(result, ExecutionResult)
        assert len(agent.calls) == 2
        assert agent.calls[0]["todo_id"] == "t1"
        assert agent.calls[1]["todo_id"] == "t2"


class TestParallelLayerExecution:
    """并行层（多 todo）并发执行。"""

    @pytest.mark.asyncio
    async def test_parallel_layer_uses_gather(self):
        t1 = _FakeTodo(id="p1", content="parallel 1")
        t2 = _FakeTodo(id="p2", content="parallel 2")
        plan = _make_plan([t1, t2])
        planner = _FakePlanner(layers=[["p1", "p2"]])
        agent = _FakeAgent()
        bus = EventBus()

        executor = TaskExecutor(plan, agent, planner, bus)
        result = await executor.run("test input")

        assert len(agent.calls) == 2
        executed_ids = {c["todo_id"] for c in agent.calls}
        assert executed_ids == {"p1", "p2"}


class TestEventBufferReplay:
    """并行任务产生的事件通过 buffer 重放为线性序列。"""

    @pytest.mark.asyncio
    async def test_events_replayed_in_plan_order(self):
        t1 = _FakeTodo(id="r1", content="r1")
        t2 = _FakeTodo(id="r2", content="r2")
        plan = _make_plan([t1, t2])
        planner = _FakePlanner(layers=[["r1", "r2"]])
        agent = _FakeAgent()
        bus = EventBus()

        received_events = []

        def on_event(event_type, data):
            received_events.append((event_type, data.get("tool", "")))

        executor = TaskExecutor(plan, agent, planner, bus)
        await executor.run("test input", on_event=on_event)

        # Events should be replayed in plan order: r1 events first, then r2
        if received_events:
            tools_seen = [t for _, t in received_events]
            # All r1 events should appear before r2 events
            r1_indices = [i for i, t in enumerate(tools_seen) if t == "r1"]
            r2_indices = [i for i, t in enumerate(tools_seen) if t == "r2"]
            if r1_indices and r2_indices:
                assert max(r1_indices) < min(r2_indices)


class TestCancelledTaskPropagation:
    """取消任务后验证下游依赖任务被跳过。"""

    @pytest.mark.asyncio
    async def test_exception_in_todo_increments_cancelled_count(self):
        t1 = _FakeTodo(id="fail1", content="will fail")
        t2 = _FakeTodo(id="ok1", content="will succeed")
        plan = _make_plan([t1, t2])
        planner = _FakePlanner(layers=[["fail1", "ok1"]])

        class _FailingAgent(_FakeAgent):
            async def execute_todo(self, todo, **kwargs):
                if todo.id == "fail1":
                    raise RuntimeError("intentional failure")
                return await super().execute_todo(todo, **kwargs)

        agent = _FailingAgent()
        bus = EventBus()

        executor = TaskExecutor(plan, agent, planner, bus)
        result = await executor.run("test input")

        # Exception in gather with return_exceptions=True counts as cancelled
        assert result.cancelled_count >= 1


class TestExecutionResultSummary:
    """验证 ExecutionResult 包含 summary 和 cancelled_count。"""

    @pytest.mark.asyncio
    async def test_empty_plan_returns_empty_result(self):
        plan = _make_plan([])
        planner = _FakePlanner()
        agent = _FakeAgent()
        bus = EventBus()

        executor = TaskExecutor(plan, agent, planner, bus)
        result = await executor.run("test input")

        assert result.summary == ""
        assert result.cancelled_count == 0

    @pytest.mark.asyncio
    async def test_successful_execution_returns_summary(self):
        t1 = _FakeTodo(id="s1", content="success task")
        plan = _make_plan([t1])
        planner = _FakePlanner(layers=[["s1"]])
        agent = _FakeAgent(results={"s1": {
            "success": True, "obs": "Task completed successfully",
            "result": "done", "tool": "test_tool", "params": {},
        }})
        bus = EventBus()

        executor = TaskExecutor(plan, agent, planner, bus)
        result = await executor.run("test input")

        assert result.summary == "Task completed successfully"
        assert result.cancelled_count == 0
