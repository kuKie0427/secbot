"""
Tests for tools/registry.py -- extension loading via entry_points + env vars.

验证工具扩展注册中心的三种加载路径：
1. entry point 分组发现
2. 环境变量模块加载
3. BaseTool 子类自动实例化
"""
import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from tools.base import BaseTool
from tools import registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _DummyTool(BaseTool):
    """用于测试的最小工具实现。"""

    def __init__(self, name: str = "dummy_tool"):
        super().__init__(name=name, description="A dummy tool for testing")

    async def execute(self, **kwargs):  # pragma: no cover
        return {"success": True, "result": "ok"}


class _BrokenTool(BaseTool):
    """实例化时抛异常的工具。"""

    def __init__(self):
        raise RuntimeError("intentional init failure")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEntryPointGroupDiscovery:
    """entry point 分组发现机制。"""

    @patch("tools.registry._load_from_entry_points")
    def test_basic_entry_point_discovers_tools(self, mock_ep):
        dummy = _DummyTool("ep_tool")
        mock_ep.return_value = [dummy]

        tools = registry.get_basic_tools()
        names = [t.name for t in tools]
        assert "ep_tool" in names

    @patch("tools.registry._load_from_entry_points")
    def test_advanced_entry_point_discovers_tools(self, mock_ep):
        dummy = _DummyTool("adv_tool")
        mock_ep.return_value = [dummy]

        tools = registry.get_advanced_tools()
        names = [t.name for t in tools]
        assert "adv_tool" in names

    @patch("tools.registry._load_from_entry_points")
    def test_entry_point_returns_empty_list(self, mock_ep):
        mock_ep.return_value = []
        tools = registry.get_basic_tools()
        assert tools == []


class TestEnvModuleLoading:
    """环境变量指定的模块加载。"""

    @patch.dict("os.environ", {"SECBOT_TOOL_MODULES": ""})
    def test_empty_env_returns_no_tools(self):
        tools = registry._load_from_env("SECBOT_TOOL_MODULES")
        assert tools == []

    def test_missing_module_returns_empty(self):
        tools = registry._load_from_env("SECBOT_TOOL_MODULES")
        assert tools == []

    @patch.dict("os.environ", {"SECBOT_TOOL_MODULES": "nonexistent.module.xyz"})
    def test_invalid_module_returns_empty(self):
        tools = registry._load_from_env("SECBOT_TOOL_MODULES")
        assert tools == []


class TestBaseToolSubclassAutoDiscovery:
    """BaseTool 子类自动实例化。"""

    def test_load_tools_from_module_with_TOOLS_list(self):
        mod = types.ModuleType("_test_tools_mod_TOOLS")
        mod.TOOLS = [_DummyTool("from_tools_list")]
        sys.modules["_test_tools_mod_TOOLS"] = mod
        try:
            result = registry._load_tools_from_module("_test_tools_mod_TOOLS")
            assert len(result) == 1
            assert result[0].name == "from_tools_list"
        finally:
            del sys.modules["_test_tools_mod_TOOLS"]

    def test_load_tools_from_module_with_get_tools(self):
        mod = types.ModuleType("_test_tools_mod_get")
        mod.get_tools = lambda: [_DummyTool("from_get_tools")]
        sys.modules["_test_tools_mod_get"] = mod
        try:
            result = registry._load_tools_from_module("_test_tools_mod_get")
            assert len(result) == 1
            assert result[0].name == "from_get_tools"
        finally:
            del sys.modules["_test_tools_mod_get"]

    def test_broken_tool_class_is_skipped(self):
        """BrokenTool 实例化失败不应阻塞其他工具加载。"""
        mod = types.ModuleType("_test_tools_mod_broken")
        mod.BrokenTool = _BrokenTool
        mod.GoodTool = type("GoodTool", (BaseTool,), {
            "__init__": lambda self: BaseTool.__init__(self, name="good", description="ok"),
            "execute": lambda self, **kw: None,
        })
        sys.modules["_test_tools_mod_broken"] = mod
        try:
            result = registry._load_tools_from_module("_test_tools_mod_broken")
            names = [t.name for t in result]
            assert "good" in names
            # BrokenTool should be silently skipped (or logged and skipped after Fix-9)
        finally:
            del sys.modules["_test_tools_mod_broken"]


class TestGetAllRegisteredTools:
    """get_all_registered_tools() 返回 (basic, advanced) 元组。"""

    @patch("tools.registry.get_advanced_tools")
    @patch("tools.registry.get_basic_tools")
    def test_returns_tuple(self, mock_basic, mock_advanced):
        mock_basic.return_value = [_DummyTool("b1")]
        mock_advanced.return_value = [_DummyTool("a1")]
        basic, advanced = registry.get_all_registered_tools()
        assert len(basic) == 1
        assert len(advanced) == 1

    @patch("tools.registry.get_advanced_tools")
    @patch("tools.registry.get_basic_tools")
    def test_list_registered_tool_names(self, mock_basic, mock_advanced):
        mock_basic.return_value = [_DummyTool("tool_x"), _DummyTool("tool_y")]
        mock_advanced.return_value = [_DummyTool("tool_z")]
        names = registry.list_registered_tool_names()
        assert set(names) == {"tool_x", "tool_y", "tool_z"}


class TestNoEntryPointsStillWorks:
    """清空所有 entry points 和环境变量，核心工具仍可加载（返回空列表而非异常）。"""

    @patch.dict("os.environ", {}, clear=True)
    @patch("tools.registry._load_from_entry_points", return_value=[])
    def test_graceful_empty(self, mock_ep):
        basic, advanced = registry.get_all_registered_tools()
        assert basic == []
        assert advanced == []
