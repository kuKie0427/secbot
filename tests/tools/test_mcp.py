"""Phase 3 MCP 测试：mcp_call 客户端往返 + secbot-mcp 服务端注册/过滤/注解。"""
import asyncio
import json
import sys
import textwrap

import pytest

from tools.mcp.mcp_call import McpCallTool
from router.mcp_server import (
    ALLOW_SENSITIVE_VALUES,
    allow_sensitive,
    build_mcp_tools,
    collect_all_tools,
    tool_is_sensitive,
)

ECHO_SERVER = textwrap.dedent("""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("echo")

    @mcp.tool()
    def echo(text: str) -> str:
        return text

    if __name__ == "__main__":
        mcp.run()
""")


@pytest.fixture
def echo_server(tmp_path):
    p = tmp_path / "echo_server.py"
    p.write_text(ECHO_SERVER)
    return p


class TestMcpCallClient:
    def test_missing_command(self):
        r = asyncio.run(McpCallTool().execute())
        assert not r.success and "command" in r.error

    def test_unsupported_action(self):
        r = asyncio.run(McpCallTool().execute(command="x", action="bogus"))
        assert not r.success and "Unsupported action" in r.error

    def test_call_tool_requires_tool_name(self):
        r = asyncio.run(McpCallTool().execute(command="x", action="call_tool"))
        assert not r.success and "tool" in r.error

    def test_list_and_call_roundtrip(self, echo_server):
        tool = McpCallTool()
        r = asyncio.run(tool.execute(
            command=sys.executable, args=[str(echo_server)], action="list_tools",
        ))
        assert r.success, r.error
        names = [t["name"] for t in r.result["tools"]]
        assert "echo" in names

        r2 = asyncio.run(tool.execute(
            command=sys.executable, args=[str(echo_server)],
            action="call_tool", tool="echo", input={"text": "hello-mcp"},
        ))
        assert r2.success, r2.error
        content = r2.result.get("content") or []
        assert any("hello-mcp" in (c.get("text") or "") for c in content)

    def test_server_crash_structured_error(self, tmp_path):
        bad = tmp_path / "bad_server.py"
        bad.write_text("import sys\nsys.stderr.write('boom-stack\\n')\nsys.exit(3)\n")
        r = asyncio.run(McpCallTool().execute(
            command=sys.executable, args=[str(bad)], action="list_tools", timeout=15,
        ))
        assert not r.success
        # stderr 捕获进错误负载（对齐 TS）
        assert "boom-stack" in r.error or (r.result or {}).get("stderr", "").find("boom-stack") >= 0

    def test_in_catalog_with_high_sensitivity(self):
        from router.tools import _CATEGORIES
        found = [t for _, _, lst in _CATEGORIES for t in lst if t.name == "mcp_call"]
        assert len(found) == 1
        assert getattr(found[0], "sensitivity", "low") == "high"


class TestMcpServerRegistration:
    def test_registry_counts_match_catalog(self):
        tools = build_mcp_tools()
        non_sensitive = [t for t in collect_all_tools() if not tool_is_sensitive(t)]
        assert len(tools) == len(non_sensitive)

    def test_sensitive_skipped_by_default(self, monkeypatch):
        monkeypatch.delenv("SECBOT_MCP_ALLOW_SENSITIVE", raising=False)
        names = {t.name for t in build_mcp_tools()}
        for s in ("attack_test", "exploit", "sniff", "credential_spray", "mcp_call"):
            assert s not in names, s

    def test_allow_sensitive_env_variants(self, monkeypatch):
        for v in ("1", "true", "yes"):
            monkeypatch.setenv("SECBOT_MCP_ALLOW_SENSITIVE", v)
            assert allow_sensitive() is True, v
        for v in ("0", "false", "", "YES "):
            monkeypatch.setenv("SECBOT_MCP_ALLOW_SENSITIVE", v if v.strip() else v)
            # "YES " trim 后小写为 yes → 放行（对齐 TS trim().toLowerCase()）
            expected = v.strip().lower() in ALLOW_SENSITIVE_VALUES
            assert allow_sensitive() is expected, repr(v)
        monkeypatch.setenv("SECBOT_MCP_ALLOW_SENSITIVE", "1")
        names = {t.name for t in build_mcp_tools()}
        assert "attack_test" in names and "mcp_call" in names

    def test_annotations_triple(self):
        tools = {t.name: t for t in build_mcp_tools()}
        ann = tools["encode_decode"].annotations

        def hint(obj, snake, camel):
            if hasattr(obj, "get"):
                return obj.get(camel)
            return getattr(obj, snake, None) if hasattr(obj, snake) else getattr(obj, camel)

        assert hint(ann, "read_only_hint", "readOnlyHint") is True
        assert hint(ann, "destructive_hint", "destructiveHint") is False
        assert hint(ann, "open_world_hint", "openWorldHint") is True

    def test_input_schema_nonempty(self):
        for t in build_mcp_tools():
            schema = getattr(t, "input_schema", None)
            if schema is None:
                schema = t.inputSchema
            assert isinstance(schema, dict) and schema.get("type") == "object", t.name
            assert isinstance(schema.get("properties"), dict), t.name

    def test_bare_properties_schema_normalized(self):
        # 旧式工具（如 port_scan）parameters 为裸 properties + 内联 required → 包装并派生 required
        tools = {t.name: t for t in build_mcp_tools()}
        schema = tools["port_scan"].inputSchema
        assert schema["type"] == "object"
        assert "host" in schema["properties"]
        assert "host" in schema.get("required", [])
        assert "required" not in schema["properties"]["host"]


class TestMcpServerCallable:
    def test_call_secbot_tool_serializes_result(self):
        from router.mcp_server import call_secbot_tool

        out = asyncio.run(call_secbot_tool("encode_decode", {"text": "aGk=", "operation": "decode"}))
        data = json.loads(out)
        assert data["success"] is True

    def test_unknown_tool_json_error(self):
        from router.mcp_server import call_secbot_tool

        out = asyncio.run(call_secbot_tool("no_such_tool", {}))
        assert json.loads(out)["success"] is False
