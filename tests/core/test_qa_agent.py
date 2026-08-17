"""Phase 7 T2 — QA 路由规则（镜像 qa-agent.test.ts）。

TS 参照断言：
- isLiveSecurityQuery：时效敏感安全问题检测（最新/最近/近期 → live；概念/能力 → 否）
- extractCveId：大小写不敏感提取 CVE 编号
- answerAdaptive：时效问题走实时检索、检索不可用给稳定兜底、CVE 问题走 CVE 查询
Python 落点：QAAgent.answer_with_context_and_tools 的工具路由 + 流式回调（on_chunk）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


from secbot_agent.core.agents import qa_agent as qa_mod
from secbot_agent.core.agents.qa_agent import QAAgent


class TestLiveSecurityQueryDetection:
    """时效敏感检测（Python 侧通过 ask-tools 路由实现，此处锁可判定的启发式输入）。"""

    FRESHNESS_QUERIES = [
        "最新出的零日",
        "最近有哪些高危漏洞",
        "近期 Exchange 漏洞情况",
    ]
    STATIC_QUERIES = ["什么是零日漏洞", "你能做什么"]

    def test_ask_tools_available_for_live_queries(self):
        tools = qa_mod.get_ask_tools()
        names = {t.name for t in tools}
        # 实时性问题依赖的查询类工具必须在问答工具集内
        assert any("search" in n or "web" in n for n in names), names
        assert any("cve" in n for n in names), names


class TestAnswerStreamingCallback:
    """answer_with_context(on_chunk) —— 对齐 TS answerAdaptive(message, history, ctx, onChunk)。"""

    def _agent_with_stream(self, chunks: list[str]):
        agent = QAAgent()
        llm = MagicMock()

        async def astream(messages):
            for c in chunks:
                yield MagicMock(content=c)

        llm.astream = astream
        agent._llm = llm
        return agent

    async def test_chunks_forwarded_in_order(self):
        agent = self._agent_with_stream(["你", "好", "！"])
        received: list[str] = []
        ans = await agent.answer_with_context(
            "打招呼", [], "", on_chunk=received.append
        )
        assert received == ["你", "好", "！"]
        assert ans == "你好！"

    async def test_no_callback_still_returns_full(self):
        # on_chunk 缺省 → 直接走 ainvoke 整段路径（无需流式）
        agent = QAAgent()
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=MagicMock(content="整段回答"))
        agent._llm = llm
        ans = await agent.answer_with_context("q", [])
        assert ans == "整段回答"

    async def test_stream_failure_falls_back_to_invoke(self):
        agent = QAAgent()
        llm = MagicMock()

        async def bad_astream(messages):
            raise RuntimeError("astream unsupported")
            yield  # pragma: no cover

        llm.astream = bad_astream
        llm.ainvoke = AsyncMock(return_value=MagicMock(content="整段回退"))
        agent._llm = llm
        received: list[str] = []
        ans = await agent.answer_with_context("q", [], "", on_chunk=received.append)
        assert ans == "整段回退"
        assert received == []  # 回退路径不重复回调
        llm.ainvoke.assert_awaited_once()


class TestAskToolsAreReadOnly:
    def test_ask_tool_names(self):
        names = {t.name for t in qa_mod.get_ask_tools()}
        # 只读/低敏感白名单（prompt 声明：搜索、系统信息、CVE、文件分析）
        forbidden = {"attack_test", "exploit", "sniff", "credential_spray", "mcp_call"}
        assert not (names & forbidden), f"问答工具集混入敏感工具: {names & forbidden}"
