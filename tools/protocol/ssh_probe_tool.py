"""ssh_probe — SSH Banner 抓取、密钥交换算法识别、弱口令检测。

镜像 TS server/src/modules/tools/protocol/ssh-probe.tool.ts（TS 该工具 sensitive=false，Python 同样不标敏感）。
"""
import asyncio
import re
from typing import Any, Dict

from tools.base import BaseTool, ToolResult


class SshProbeTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="ssh_probe",
            description="SSH 探测 — Banner 抓取、密钥交换算法识别、弱口令检测",
        )

    async def execute(
        self,
        host: str = "",
        port: int = 22,
        username: str = "",
        password: str = "",
        timeout: int = 10,
        **kwargs,
    ) -> ToolResult:
        host = (host or "").strip()
        if not host:
            return ToolResult(success=False, result=None, error="缺少必要参数: host")

        port = int(port or 22)
        timeout_s = min(int(timeout or 10), 30)

        try:
            banner = await _grab_banner(host, port, timeout_s)
            analysis = _analyze_banner(banner)

            weak_credential = None
            if username:
                weak_credential = await _try_credential(host, port, username, password or "", timeout_s)

            result: Dict[str, Any] = {
                "host": host,
                "port": port,
                "banner": banner.strip(),
                **analysis,
            }
            if weak_credential is not None:
                result["weak_credential"] = weak_credential
            return ToolResult(success=True, result=result)
        except Exception as e:
            return ToolResult(success=False, result=None, error=f"SSH 探测失败: {e}")

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "目标主机"},
                    "port": {"type": "integer", "description": "端口（默认 22）"},
                    "username": {"type": "string", "description": "可选，提供时进行弱口令验证"},
                    "password": {"type": "string", "description": "可选，与 username 配合"},
                    "timeout": {"type": "integer", "description": "超时秒数（默认 10，上限 30）"},
                },
                "required": ["host"],
            },
        }


async def _grab_banner(host: str, port: int, timeout_s: float) -> str:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_s)
    try:
        data = await asyncio.wait_for(reader.read(512), timeout=timeout_s)
        return data.decode("utf-8", errors="ignore")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def _analyze_banner(banner: str) -> Dict[str, Any]:
    line = banner.split("\n")[0].strip()
    findings = []

    m = re.match(r"^SSH-(\d+\.\d+)-(.+)", line)
    protocol = m.group(1) if m else "unknown"
    software = m.group(2) if m else line

    if re.search(r"OpenSSH[_-]([1-6]\.|7\.[0-3])", software, re.I):
        findings.append("OpenSSH 版本较旧，可能存在已知漏洞")
    if re.search(r"dropbear", software, re.I):
        findings.append("Dropbear SSH — 嵌入式设备常见，检查版本是否有已知漏洞")
    if protocol in ("1.0", "1.99"):
        findings.append("支持 SSH v1 协议 — 存在已知密码学弱点，应禁用")
    if re.search(r"libssh[_-]0\.[0-7]\.", software, re.I):
        findings.append("libssh 旧版本 — 可能受 CVE-2018-10933 认证绕过影响")

    return {"protocol": protocol, "software": software, "findings": findings}


async def _try_credential(host: str, port: int, username: str, password: str, timeout_s: int) -> bool:
    import paramiko

    def attempt():
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(host, port=port, username=username, password=password, timeout=timeout_s,
                           allow_agent=False, look_for_keys=False)
            return True
        except paramiko.AuthenticationException:
            return False
        except Exception:
            return False
        finally:
            client.close()

    return await asyncio.get_event_loop().run_in_executor(None, attempt)
