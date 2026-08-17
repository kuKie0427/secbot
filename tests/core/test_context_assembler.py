"""Phase 7 T2 — context 预算打包（镜像 context-assembler.service.test.ts）。

TS 参照断言：
- 融合会话、SQLite 与向量上下文并输出统计（session_messages/sqlite_turns/vector_hits 计数）
- 记忆落库时写入短期、情节与向量记忆
Python 落点：secbot_agent/core/context_assembler.py ContextAssembler.build。
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock


from secbot_agent.core.context_assembler import (
    AssembledContext,
    ContextAssembler,
    ContextDebugMeta,
)


class FakeContextStore:
    """最小 ContextStore 替身：pinned/focus 空、model_name 可设。"""

    def __init__(self):
        self.model_name = None

    def set_model_name(self, session_id, model_name):
        self.model_name = model_name

    def get(self, session_id):
        return SimpleNamespace(pinned=[], focus=[], unresolved=[], model_name=self.model_name)


class FakeVectorStoreManager:
    """向量检索替身：返回一条命中（带 metadata/sessionId）。"""

    def get_store(self, name, dim):
        store = MagicMock()
        store.search.return_value = [
            (
                SimpleNamespace(content="历史漏洞处置经验", id="v1", metadata={"sessionId": "s-old"}),
                0.8,
            )
        ]
        return store


class FakeDbManager:
    def __init__(self, turns):
        self._turns = turns

    def get_conversations(self, session_id, limit):
        return self._turns


class FakeSession:
    def __init__(self, messages):
        self.messages = messages


def _msg(role: str, content: str):
    return SimpleNamespace(
        role=SimpleNamespace(value=role), content=content, timestamp=datetime.now()
    )


class TestBuild:
    async def test_fuses_three_sources_with_stats(self):
        assembler = ContextAssembler.__new__(ContextAssembler)
        assembler.context_store = FakeContextStore()
        assembler.vector_store_manager = FakeVectorStoreManager()
        assembler.db_manager = FakeDbManager(
            [SimpleNamespace(user_message="u1", assistant_message="a1")]
        )

        session = FakeSession([_msg("user", "查一下端口"), _msg("assistant", "好的")])
        ctx = await assembler.build(
            query="端口", session=session, session_id="s-test"
        )

        assert isinstance(ctx, AssembledContext)
        assert ctx.context_block  # 打包产出非空
        # 统计口径（对齐 TS：session_messages/sqlite_turns/vector_hits）
        assert ctx.debug.session_messages == 2
        assert ctx.debug.sqlite_turns == 1
        assert ctx.debug.vector_hits == 1

    async def test_budget_respected(self):
        assembler = ContextAssembler.__new__(ContextAssembler)
        assembler.context_store = FakeContextStore()
        assembler.vector_store_manager = None
        assembler.db_manager = FakeDbManager([])

        session = FakeSession([_msg("user", "长" * 5000)])
        ctx = await assembler.build(
            query="q", session=session, session_id="s-budget"
        )
        # used_tokens 不超预算（模型窗口 → 预算计算的硬上限）
        assert ctx.debug.used_tokens <= ctx.debug.prompt_budget

    async def test_no_vector_manager_no_hits_no_crash(self):
        assembler = ContextAssembler.__new__(ContextAssembler)
        assembler.context_store = FakeContextStore()
        assembler.vector_store_manager = None
        assembler.db_manager = FakeDbManager([])

        ctx = await assembler.build(
            query="q", session=FakeSession([]), session_id="s-empty"
        )
        assert ctx.debug.vector_hits == 0
        assert ctx.debug.session_messages == 0


class TestDebugMetaDefaults:
    def test_defaults(self):
        meta = ContextDebugMeta()
        assert meta.prompt_budget == 0
        assert meta.focus == []
        assert meta.model_name is None
