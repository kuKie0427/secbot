"""email_enum — SMTP 用户枚举（VRFY/RCPT TO 验证邮箱存在性，标准库 smtplib）。

镜像 TS server/src/modules/tools/protocol/email-enum.tool.ts
"""
import asyncio
import smtplib
from typing import Any, Dict, List, Optional

import dns.resolver

from tools.base import BaseTool, ToolResult

DEFAULT_USERS = [
    "admin", "root", "info", "support", "contact",
    "webmaster", "postmaster", "sales", "test", "user", "mail", "office",
]


class EmailEnumTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="email_enum",
            description="SMTP 用户枚举 — 通过 VRFY/RCPT TO 验证邮箱地址是否存在",
        )

    async def execute(
        self,
        domain: str = "",
        users: Optional[List[str]] = None,
        method: str = "rcpt",
        timeout: int = 15,
        **kwargs,
    ) -> ToolResult:
        domain = (domain or "").strip()
        if not domain:
            return ToolResult(success=False, result=None, error="缺少必要参数: domain")

        target_users = [str(u) for u in users] if users else DEFAULT_USERS
        method = (method or "rcpt").strip().lower()
        if method not in ("vrfy", "rcpt"):
            method = "rcpt"
        timeout_s = min(int(timeout or 15), 60)

        try:
            loop = asyncio.get_event_loop()
            mx_host = await loop.run_in_executor(None, _resolve_mx, domain, timeout_s)
            if not mx_host:
                return ToolResult(success=False, result=None, error=f"无法解析 {domain} 的 MX 记录")

            results = await loop.run_in_executor(
                None, _enumerate, mx_host, domain, target_users, method, timeout_s
            )
            valid = [r for r in results if r["valid"]]
            invalid = [r for r in results if not r["valid"]]
            return ToolResult(
                success=True,
                result={
                    "domain": domain,
                    "mx_host": mx_host,
                    "method": method,
                    "users_checked": len(target_users),
                    "valid": valid,
                    "invalid": invalid,
                },
            )
        except Exception as e:
            return ToolResult(success=False, result=None, error=f"SMTP 枚举失败: {e}")

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "目标域名"},
                    "users": {"type": "array", "items": {"type": "string"}, "description": "待验证用户名列表（默认常见角色账户）"},
                    "method": {"type": "string", "enum": ["vrfy", "rcpt"], "description": "验证方式（默认 rcpt）"},
                    "timeout": {"type": "integer", "description": "超时秒数（默认 15，上限 60）"},
                },
                "required": ["domain"],
            },
        }


def _resolve_mx(domain: str, timeout_s: int) -> Optional[str]:
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout_s
        records = sorted(resolver.resolve(domain, "MX"), key=lambda r: r.preference)
        return str(records[0].exchange).rstrip(".") if records else None
    except Exception:
        return None


def _enumerate(mx_host: str, domain: str, users: List[str], method: str, timeout_s: int):
    results = []
    with smtplib.SMTP(mx_host, 25, timeout=timeout_s) as smtp:
        smtp.ehlo()
        for user in users:
            addr = f"{user}@{domain}"
            code = _verify(smtp, addr, method)
            results.append({"user": user, "email": addr, "valid": 200 <= code < 300, "code": code})
    return results


def _verify(smtp: smtplib.SMTP, addr: str, method: str) -> int:
    try:
        if method == "vrfy":
            return smtp.verify(addr)[0]
        smtp.mail("test@example.com")
        code = smtp.rcpt(addr)[0]
        smtp.rset()
        return code
    except smtplib.SMTPServerDisconnected:
        return 0
    except Exception:
        return 0
