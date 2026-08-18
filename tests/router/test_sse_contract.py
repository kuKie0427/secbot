"""Phase 7 T1 — SSE 线上事件契约快照。

锁定：线上事件名全集（`_event_to_sse` 映射 + 生成器直发）与关键字段。
改任一事件名 / 删关键字段 → 本文件必红（变更须显式更新快照并说明）。

口径：wire event 名（event: 行的值），非枚举成员比对。
参照 docs/CONTRACT_SSE.md。
"""
from __future__ import annotations


from fastapi.testclient import TestClient

from router.chat import _event_to_sse
from router.main import create_app
from utils.event_bus import Event, EventType


def _map(event_type: EventType, **data):
    return _event_to_sse(Event(type=event_type, data=data))


# ----------------------------------------------------------------------
# 线上事件名全集快照（_event_to_sse 映射产出）
# ----------------------------------------------------------------------
MAPPED_EVENT_NAMES = {
    "planning",            # PLAN_START
    "thought_start",       # THINK_START
    "thought_chunk",       # THINK_CHUNK（Python 增强）
    "thought",             # THINK_END
    "action_start",        # EXEC_START
    "action_result",       # EXEC_RESULT
    "content",             # CONTENT
    "report",              # REPORT_END
    "phase",               # TASK_PHASE
    "root_required",       # ROOT_REQUIRED（Python 增强）
    "error",               # ERROR（生成器 catch 处亦直发同构体）
    "intent_decision",     # INTENT_DECISION
    "explore_start",       # EXPLORE_START
    "explore_step",        # EXPLORE_STEP
    "explore_end",         # EXPLORE_END
    "context_patch",       # CONTEXT_PATCH
    "context_usage",       # CONTEXT_USAGE
    "context_debug",       # CONTEXT_DEBUG（Phase 7 修复）
    "clarify",             # CLARIFY
    "response_chunk",      # RESPONSE_CHUNK（Phase 7 补齐）
}

# 生成器直发（不经 _event_to_sse）
GENERATOR_EVENT_NAMES = {"connected", "response", "done"}

# 全量线上事件契约
WIRE_EVENT_NAMES = MAPPED_EVENT_NAMES | GENERATOR_EVENT_NAMES

# 双端定义未用、Python 已删除（docs/CONTRACT_SSE.md 豁免表）
REMOVED_ENUMS = {"toast_show", "command_execute"}


class TestWireEventNames:
    def test_mapped_names_snapshot(self):
        produced = set()
        for et in EventType:
            result = _map(et)
            if result:
                produced.add(result[0])
        assert produced == MAPPED_EVENT_NAMES, (
            f"线上事件集合变更：新增 {produced - MAPPED_EVENT_NAMES} / "
            f"删除 {MAPPED_EVENT_NAMES - produced}——请显式更新快照并同步 docs/CONTRACT_SSE.md"
        )

    def test_removed_unused_enums_stay_removed(self):
        values = {e.value for e in EventType}
        for gone in REMOVED_ENUMS:
            assert gone not in values, f"{gone} 应保持删除（双端定义未用）"

    def test_no_event_type_maps_to_none_silently_for_known_wire(self):
        # 所有映射事件都应有非空 data dict
        for et, name in [
            (EventType.THINK_START, "thought_start"),
            (EventType.EXEC_RESULT, "action_result"),
            (EventType.RESPONSE_CHUNK, "response_chunk"),
            (EventType.CONTEXT_DEBUG, "context_debug"),
        ]:
            _, data = _map(et)
            assert isinstance(data, dict), name


# ----------------------------------------------------------------------
# 关键字段快照
# ----------------------------------------------------------------------
class TestKeyFields:
    def test_step_key_and_iteration(self):
        _, data = _map(EventType.THINK_START, iteration=3, todo_id="t2")
        assert data["step_key"] == "todo-t2"
        assert data["iteration"] == 3

        _, data = _map(EventType.EXEC_START, iteration=1)
        assert data["step_key"] == "iter-1"  # 无 todo_id 回退

    def test_planning_scope(self):
        _, data = _map(EventType.PLAN_START, summary="s", todos=[], scope="adaptive")
        assert data["scope"] == "adaptive"
        _, data = _map(EventType.PLAN_START, summary="s", todos=[])
        assert data["scope"] == "master"  # 默认

    def test_view_type_defaults(self):
        _, data = _map(EventType.CONTENT, content="x")
        assert data["view_type"] == "summary"
        _, data = _map(EventType.EXEC_RESULT, tool="t", success=True)
        assert data["view_type"] == "raw"

    def test_response_chunk_field(self):
        _, data = _map(EventType.RESPONSE_CHUNK, chunk="段", agent="qa")
        assert data == {"chunk": "段", "agent": "qa"}

    def test_context_debug_full_fields(self):
        _, data = _map(
            EventType.CONTEXT_DEBUG,
            session_id="s1", model="m", context_window=128000,
            prompt_budget=60000, used_tokens=12000, reserved_tokens=4096,
            session_messages=8, sqlite_turns=3, vector_hits=2, pinned=1,
            focus=["web"], dropped_sections=["old"],
        )
        assert data["session_id"] == "s1"
        assert data["prompt_budget"] == 60000
        assert data["vector_hits"] == 2
        assert data["dropped_sections"] == ["old"]


# ----------------------------------------------------------------------
# 结束序列（wire 行为）
# ----------------------------------------------------------------------
class TestWireSequence:
    def test_connected_first_done_last_error_then_done(self):
        client = TestClient(create_app())
        events: list[str] = []
        with client.stream(
            "POST", "/api/chat",
            json={"message": "契约冒烟", "session_id": "snap-1", "mode": "agent"},
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
        assert events[0] == "connected"
        assert events[-1] == "done"
        if "error" in events:
            assert events[events.index("error") + 1] == "done"

    def test_error_payload_has_code_and_status(self):
        # error 帧字段契约（TS useChat.ts:434-440 读 data.code）
        _, data = _map(EventType.ERROR, error="x")
        assert "error" in data
        assert "code" in data
        assert "statusCode" in data
