"""Phase 7 T2 — chat 编排早退（镜像 chat.service.test.ts）。

TS 参照断言：
- QA 路由走 answerAdaptive（Python: qa_agent.answer_with_context）并发出 response 事件
- 指定 agent 的同步/流式请求路径一致
Python 落点：secbot_agent/core/session.py::_maybe_handle_conversational_intent
（small_talk / meta / qa / clarify_needed 早退——不进 Planner/ReAct 编排）。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from secbot_agent.core.models import IntentDecision
from utils.event_bus import EventBus, EventType


class FakeSessionMessages:
    def __init__(self):
        self.messages = []
        self.id = "s-orch"

    def add_message(self, role, content):
        self.messages.append(SimpleNamespace(role=role, content=content))


@pytest.fixture()
def captured():
    return []


@pytest.fixture()
def bus(captured):
    bus = EventBus()

    def _subscribe(event):
        captured.append(event)

    bus.subscribe_all(_subscribe)
    return bus


def _decision(intent: str, **kw) -> IntentDecision:
    defaults = dict(confidence=0.9, needs_explore=False, needs_report=False)
    defaults.update(kw)
    return IntentDecision(intent=intent, **defaults)


async def _run_early(session_obj, decision):
    """直接调被测方法（绕过 handle_message 的 LLM 意图识别）。"""
    return await session_obj._maybe_handle_conversational_intent(
        user_input="测试输入",
        intent=decision,
        agent_type=None,
        model_name=None,
    )


def _make_session_obj(bus):
    from secbot_agent.core.session import SessionManager

    obj = SessionManager.__new__(SessionManager)
    obj.event_bus = bus
    obj.qa_agent = SimpleNamespace(
        answer=AsyncMock(return_value="live qa answer"),
        answer_with_context=AsyncMock(return_value="ctx qa answer"),
    )
    obj.current_session = FakeSessionMessages()
    obj.context_assembler = None
    obj.agents = {}
    obj.resolve_agent = None
    return obj


class TestEarlyReturnRouting:
    async def test_small_talk_direct_response(self, bus, captured):
        obj = _make_session_obj(bus)
        ans = await _run_early(obj, _decision("small_talk", direct_response="收到"))
        assert ans == "收到"
        # 早退路径也要发 CONTENT（前端总结块）并落会话
        assert any(e.type == EventType.CONTENT for e in captured)

    async def test_small_talk_fallback_text_when_no_direct(self, bus):
        obj = _make_session_obj(bus)
        ans = await _run_early(obj, _decision("small_talk"))
        assert ans  # 兜底文案非空

    async def test_qa_without_context_uses_plain_answer(self, bus):
        obj = _make_session_obj(bus)
        obj.context_assembler = None
        obj.current_session = None
        ans = await _run_early(obj, _decision("qa"))
        assert ans == "live qa answer"
        obj.qa_agent.answer.assert_awaited_once()

    async def test_qa_direct_response_short_circuits_llm(self, bus):
        obj = _make_session_obj(bus)
        # qa + direct_response → 不调 LLM（路由器已产出答案）
        ans = await _run_early(obj, _decision("qa", direct_response="直接答"))
        assert ans == "直接答"
        obj.qa_agent.answer.assert_not_awaited()
        obj.qa_agent.answer_with_context.assert_not_awaited()

    async def test_clarify_emits_clarify_event(self, bus, captured):
        obj = _make_session_obj(bus)
        ans = await _run_early(
            obj, _decision("clarify_needed", clarify_question="目标是什么？")
        )
        assert ans == "目标是什么？"
        clarify_events = [e for e in captured if e.type == EventType.CLARIFY]
        assert clarify_events and clarify_events[0].data["question"] == "目标是什么？"

    async def test_clarify_default_question(self, bus, captured):
        obj = _make_session_obj(bus)
        await _run_early(obj, _decision("clarify_needed"))
        assert any(
            e.type == EventType.CLARIFY and "授权" in e.data["question"]
            for e in captured
        )

    async def test_task_intent_returns_none_falls_through(self, bus):
        obj = _make_session_obj(bus)
        result = await _run_early(obj, _decision("task_complex"))
        assert result is None  # 不早退 → 进入 Planner/ReAct 编排
