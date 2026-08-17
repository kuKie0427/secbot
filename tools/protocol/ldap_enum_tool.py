"""ldap_enum — LDAP 匿名绑定探测 + 基础信息获取（依赖 ldap3）。

镜像 TS server/src/modules/tools/protocol/ldap-enum.tool.ts
"""
import asyncio
from typing import Any, Dict

from tools.base import BaseTool, ToolResult


class LdapEnumTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="ldap_enum",
            description="LDAP 枚举 — 匿名绑定探测 + 基础信息获取",
        )

    async def execute(
        self,
        host: str = "",
        port: int = 389,
        base_dn: str = "",
        timeout: int = 10,
        **kwargs,
    ) -> ToolResult:
        host = (host or "").strip()
        if not host:
            return ToolResult(success=False, result=None, error="缺少必要参数: host")

        port = int(port or 389)
        timeout_s = min(int(timeout or 10), 30)
        base_dn = (base_dn or "").strip()

        try:
            loop = asyncio.get_event_loop()
            anon = await loop.run_in_executor(None, _try_anonymous_bind, host, port, timeout_s)

            findings = []
            if anon.get("success"):
                if not anon.get("root_dse"):
                    findings.append("匿名绑定成功 — LDAP 允许匿名访问")
                else:
                    findings.append("匿名绑定成功且可读取 RootDSE — 信息泄露")
            else:
                findings.append("匿名绑定被拒绝")

            result: Dict[str, Any] = {
                "host": host,
                "port": port,
                "reachable": True,
                "anonymous_bind": anon.get("success", False),
                "findings": findings,
            }
            if base_dn:
                result["base_dn"] = base_dn
            if anon.get("root_dse"):
                result["root_dse"] = anon["root_dse"]
            if anon.get("naming_contexts"):
                result["naming_contexts"] = anon["naming_contexts"]
            return ToolResult(success=True, result=result)
        except Exception as e:
            return ToolResult(success=False, result=None, error=f"LDAP 枚举失败: {e}")

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "目标主机"},
                    "port": {"type": "integer", "description": "端口（默认 389）"},
                    "base_dn": {"type": "string", "description": "Base DN（可选）"},
                    "timeout": {"type": "integer", "description": "超时秒数（默认 10，上限 30）"},
                },
                "required": ["host"],
            },
        }


def _try_anonymous_bind(host: str, port: int, timeout_s: int) -> Dict[str, Any]:
    from ldap3 import Server, Connection, ALL, ANONYMOUS

    server = Server(host, port=port, get_info=ALL, connect_timeout=timeout_s)
    conn = Connection(server, authentication=ANONYMOUS, receive_timeout=timeout_s)
    try:
        if not conn.bind():
            return {"success": False}
        info: Dict[str, Any] = {"success": True}
        naming = server.info.get("naming_contexts") or []
        if naming:
            info["naming_contexts"] = [str(n) for n in naming]
        root = server.info.get("")
        if root:
            info["root_dse"] = {
                "naming_contexts": [str(n) for n in (root.get("namingContexts") or [])][:10],
                "supported_ldap_versions": [str(v) for v in (root.get("supportedLDAPVersion") or [])],
                "vendor": str(root.get("vendorName", [""])[0]) if root.get("vendorName") else None,
            }
        return info
    except Exception:
        return {"success": False}
    finally:
        try:
            conn.unbind()
        except Exception:
            pass
