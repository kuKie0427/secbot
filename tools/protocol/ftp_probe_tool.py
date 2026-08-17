"""ftp_probe — FTP Banner 抓取、匿名登录检测（标准库 ftplib）。

镜像 TS server/src/modules/tools/protocol/ftp-probe.tool.ts
"""
import asyncio
import re
from typing import Any, Dict

from tools.base import BaseTool, ToolResult


class FtpProbeTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="ftp_probe",
            description="FTP 探测 — Banner 抓取、匿名登录检测",
        )

    async def execute(
        self,
        host: str = "",
        port: int = 21,
        check_anonymous: bool = True,
        timeout: int = 10,
        **kwargs,
    ) -> ToolResult:
        host = (host or "").strip()
        if not host:
            return ToolResult(success=False, result=None, error="缺少必要参数: host")

        port = int(port or 21)
        check_anon = check_anonymous is not False
        timeout_s = min(int(timeout or 10), 30)

        try:
            loop = asyncio.get_event_loop()
            banner = await loop.run_in_executor(None, _get_banner, host, port, timeout_s)
            result: Dict[str, Any] = {
                "host": host,
                "port": port,
                "banner": banner.strip(),
                **_analyze_banner(banner),
            }
            if check_anon:
                result["anonymous_login"] = await loop.run_in_executor(
                    None, _try_anonymous, host, port, timeout_s
                )
            return ToolResult(success=True, result=result)
        except Exception as e:
            return ToolResult(success=False, result=None, error=f"FTP 探测失败: {e}")

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "目标主机"},
                    "port": {"type": "integer", "description": "端口（默认 21）"},
                    "check_anonymous": {"type": "boolean", "description": "是否检测匿名登录（默认 true）"},
                    "timeout": {"type": "integer", "description": "超时秒数（默认 10，上限 30）"},
                },
                "required": ["host"],
            },
        }


def _get_banner(host: str, port: int, timeout_s: int) -> str:
    import ftplib

    ftp = ftplib.FTP()
    try:
        ftp.connect(host, port, timeout=timeout_s)
        return ftp.getwelcome()
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def _try_anonymous(host: str, port: int, timeout_s: int) -> bool:
    import ftplib

    ftp = ftplib.FTP()
    try:
        ftp.connect(host, port, timeout=timeout_s)
        ftp.login("anonymous", "anonymous@")
        return True
    except Exception:
        return False
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def _analyze_banner(banner: str) -> Dict[str, Any]:
    findings = []
    line = banner.split("\n")[0].strip()

    if re.search(r"vsftpd\s*2\.", line, re.I):
        findings.append("vsftpd 2.x — 检查是否受后门漏洞影响 (CVE-2011-2523)")
    if re.search(r"ProFTPD\s*1\.[0-2]", line, re.I):
        findings.append("ProFTPD 旧版本 — 可能存在已知 RCE")
    if re.search(r"FileZilla Server", line, re.I):
        findings.append("FileZilla Server — 检查版本是否有路径遍历漏洞")
    if re.search(r"Pure-FTPd", line, re.I):
        findings.append("Pure-FTPd 检测到")

    return {"software": re.sub(r"^220[\s-]*", "", line), "findings": findings}
