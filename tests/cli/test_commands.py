"""Phase 5 — CLI 命令注册表测试（T1/T2 验收）。

验收点（plans/phase-5）：
- 帮助文本列出的每个命令都有 handler 且单测可调用；补全列表与帮助文本同源生成、永不脱节。
- 命令矩阵对齐 TS slash.ts + App.tsx（/plan /start 已删除，不得再出现）。
- parse_option_values 对齐 TS parseOptionValues 语义。
"""
from __future__ import annotations

import pytest
from rich.console import Console

from secbot_cli.commands import (
    CommandRegistry,
    SlashCommand,
    build_default_registry,
    parse_option_value,
    parse_option_values,
    split_input,
)
from secbot_cli.stream_constants import (
    EXPLORING_TOOLS,
    TERMINAL_TOOLS,
    TRANSIENT_TOOLS,
    tool_class,
)


# ----------------------------------------------------------------------
# T1 注册表
# ----------------------------------------------------------------------
class TestRegistryBasics:
    def test_register_and_lookup(self):
        reg = CommandRegistry()

        async def handler(rest):
            return None

        cmd = SlashCommand(name="/foo", description="示例", handler=handler)
        reg.register(cmd)
        assert reg.lookup("/foo") is cmd
        assert reg.lookup("/foo arg1 arg2") is cmd
        assert reg.lookup("foo") is cmd  # 无斜杠也接受
        assert reg.lookup("/bar") is None

    def test_lookup_via_alias(self):
        reg = CommandRegistry()
        cmd = SlashCommand(name="/help", description="帮助", aliases=["/h", "/?"], handler=None)
        reg.register(cmd)
        assert reg.lookup("/h") is cmd
        assert reg.lookup("/?") is cmd

    def test_completions_include_aliases_and_are_sorted_unique(self):
        reg = CommandRegistry()
        reg.register(SlashCommand(name="/b", description="", aliases=["/beta"]))
        reg.register(SlashCommand(name="/a", description=""))
        assert reg.completions() == ["/a", "/b", "/beta"]


class TestDefaultRegistryMatrix:
    """T2 命令对齐矩阵：与 TS slash.ts + App.tsx 注册表对齐。

    元数据态（无 handlers）用于离线补全；绑定态（runner 注入）用于分发。
    """

    EXPECTED = {
        "/help": ["/h", "/?"],
        "/model": [],
        "/agent": [],
        "/ask": [],
        "/task": [],
        "/new-session": [],
        "/sessions": [],
        "/list-agents": [],
        "/tools": [],
        "/skills": [],
        "/skill": [],
        "/create-skill": [],
        "/log-level": [],
        "/logs": [],
        "/accept": [],
        "/reject": [],
        "/exit": ["/quit"],
    }
    REMOVED = ["/plan", "/start"]  # 假命令清理：TS 无此命令

    @pytest.fixture()
    def registry(self):
        async def _handler(rest):
            return None

        return build_default_registry({name: _handler for name in self.EXPECTED})

    def test_command_set_matches_ts_matrix(self, registry):
        names = {c.name for c in registry.all_commands()}
        assert names == set(self.EXPECTED)

    def test_every_command_has_handler_and_description(self, registry):
        for cmd in registry.all_commands():
            assert cmd.handler is not None, f"{cmd.name} 缺 handler（宣传但无实现）"
            assert cmd.description.strip(), f"{cmd.name} 缺描述"

    def test_aliases_match(self, registry):
        by_name = {c.name: c.aliases for c in registry.all_commands()}
        for name, aliases in self.EXPECTED.items():
            assert by_name[name] == aliases, f"{name} 别名不符: {by_name[name]}"

    def test_removed_fake_commands_absent(self, registry):
        for removed in self.REMOVED:
            assert registry.lookup(removed) is None
            assert removed not in registry.completions()

    def test_completions_superset_of_help_names(self, registry):
        """补全与帮助同源：帮助里每个命令（含别名）都出现在补全列表。"""
        completions = set(registry.completions())
        for cmd in registry.all_commands():
            assert cmd.name in completions
            for alias in cmd.aliases:
                assert alias in completions


# ----------------------------------------------------------------------
# T3 分类常量
# ----------------------------------------------------------------------
class TestStreamConstants:
    def test_tool_class_transient(self):
        for tool in TRANSIENT_TOOLS:
            assert tool_class(tool) == "transient"

    def test_tool_class_exploring(self):
        for tool in EXPLORING_TOOLS:
            assert tool_class(tool) == "exploring"

    def test_tool_class_terminal(self):
        for tool in TERMINAL_TOOLS:
            assert tool_class(tool) == "terminal"

    def test_tool_class_default(self):
        assert tool_class("nmap_scan") == "default"
        assert tool_class("") == "default"

    def test_sets_match_ts_stream_constants(self):
        """对齐 TS terminal-ui streamConstants.ts 的分类集合（逐字）。"""
        assert TRANSIENT_TOOLS == {"system_info", "network_analyze", "report_generator"}
        assert EXPLORING_TOOLS == {"web_research", "web_crawler"}
        assert TERMINAL_TOOLS == {"execute_command", "terminal_session"}


# ----------------------------------------------------------------------
# TS 对齐的 flag 解析
# ----------------------------------------------------------------------
class TestParseOptionValues:
    def test_single_flag_single_value(self):
        assert parse_option_values(["--tag", "a"], "--tag") == ["a"]

    def test_multi_word_segment_joined(self):
        parts = split_input("/create-skill my-skill --description 扫描 内网 主机")
        assert parse_option_values(parts, "--description") == ["扫描 内网 主机"]

    def test_repeated_flag_collects_all(self):
        parts = split_input("/create-skill x --trigger t1 --trigger t2 --tag g")
        assert parse_option_values(parts, "--trigger") == ["t1", "t2"]
        assert parse_option_values(parts, "--tag") == ["g"]

    def test_segment_stops_at_next_flag(self):
        parts = split_input("/create-skill x --trigger t1 --tag g")
        assert parse_option_values(parts, "--trigger") == ["t1"]

    def test_missing_flag_returns_empty(self):
        assert parse_option_values(["/create-skill", "x"], "--tag") == []

    def test_parse_option_value_takes_first(self):
        parts = split_input("/create-skill x --author alice --author bob")
        assert parse_option_value(parts, "--author") == "alice"

    def test_quoted_input(self):
        parts = split_input('/create-skill x --description "端口 扫描"')
        assert parse_option_values(parts, "--description") == ["端口 扫描"]


# ----------------------------------------------------------------------
# runner 集成：注册表构建 + /help 渲染冒烟
# ----------------------------------------------------------------------
class TestRunnerRegistryIntegration:
    @pytest.fixture()
    def built(self):
        from types import SimpleNamespace

        from secbot_cli import runner as runner_mod

        console = Console(record=True, width=100)
        state = runner_mod._ReplState(SimpleNamespace(), "default")

        registry = runner_mod._build_registry(console, state)
        return registry, console, state

    def test_build_registry_yields_full_matrix(self, built):
        registry, _, _ = built
        names = {c.name for c in registry.all_commands()}
        assert names == set(TestDefaultRegistryMatrix.EXPECTED)

    def test_help_renders_every_command(self, built):
        registry, console, _ = built
        registry.render_help(console)
        output = console.export_text()
        for cmd in registry.all_commands():
            base = cmd.name.lstrip("/")
            assert base in output, f"/help 输出缺少 {cmd.name}"

    async def test_exit_command_sets_exit_repl(self, built):
        registry, _, _ = built
        cmd = registry.lookup("/exit")
        result = await cmd.handler([])
        assert result.exit_repl is True

    async def test_ask_task_return_chat_message_agent_mode(self, built):
        registry, _, _ = built
        for name in ("/ask", "/task"):
            cmd = registry.lookup(name)
            result = await cmd.handler(["今天", "有什么", "工具"])
            assert result.chat_message == "今天 有什么 工具"
            assert result.chat_mode == "agent"

    async def test_ask_without_args_is_handled_silently(self, built):
        registry, _, _ = built
        cmd = registry.lookup("/ask")
        result = await cmd.handler([])
        assert result.handled is True
        assert result.chat_message is None
