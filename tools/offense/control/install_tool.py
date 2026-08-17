"""install_tool — 白名单安全工具安装器（自动检测包管理器）。

镜像 TS server/src/modules/tools/control/install-tool.tool.ts（白名单与 pickMethod 顺序逐字对齐）。
"""
import asyncio
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolResult

INSTALL_REGISTRY: Dict[str, Dict[str, str]] = {
    "nuclei": {"brew": "nuclei", "apt": "nuclei", "go": "github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest", "description": "模板漏洞扫描器"},
    "nikto": {"brew": "nikto", "apt": "nikto", "description": "Web 综合漏扫"},
    "nmap": {"brew": "nmap", "apt": "nmap", "description": "端口扫描与服务识别"},
    "ffuf": {"brew": "ffuf", "apt": "ffuf", "go": "github.com/ffuf/ffuf/v2@latest", "description": "目录/参数爆破"},
    "tshark": {"brew": "wireshark", "apt": "tshark", "description": "网络抓包分析"},
    "traceroute": {"brew": "traceroute", "apt": "traceroute", "description": "路由追踪"},
    "sqlmap": {"brew": "sqlmap", "apt": "sqlmap", "pip": "sqlmap", "description": "SQL 注入自动化"},
    "hydra": {"brew": "hydra", "apt": "hydra", "description": "多协议暴力破解"},
    "subfinder": {"brew": "subfinder", "go": "github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest", "description": "子域名发现"},
    "httpx": {"brew": "httpx", "go": "github.com/projectdiscovery/httpx/cmd/httpx@latest", "description": "HTTP 探测"},
    "gobuster": {"brew": "gobuster", "go": "github.com/OJ/gobuster/v3@latest", "description": "目录/DNS 爆破"},
    "amass": {"brew": "amass", "go": "github.com/owasp-amass/amass/v4/...@master", "description": "攻击面枚举"},
    "masscan": {"brew": "masscan", "apt": "masscan", "description": "高速端口扫描"},
    "whatweb": {"brew": "whatweb", "apt": "whatweb", "description": "Web 指纹识别"},
    "wpscan": {"brew": "wpscan", "description": "WordPress 漏洞扫描"},
    "testssl": {"brew": "testssl", "description": "SSL/TLS 深度检测"},
    "feroxbuster": {"brew": "feroxbuster", "description": "递归目录爆破"},
}


class InstallToolTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="install_tool",
            description="安装安全工具 — 自动检测包管理器并安装所需的安全测试工具",
        )

    async def execute(self, tool: str = "", name: str = "", **kwargs) -> ToolResult:
        tool_name = (tool or name or "").strip().lower()
        if not tool_name:
            return ToolResult(success=False, result=None, error="缺少必要参数: tool (工具名称)")

        entry = INSTALL_REGISTRY.get(tool_name)
        if not entry:
            return ToolResult(
                success=False, result=None,
                error=f"不支持自动安装: {tool_name}。支持的工具: {', '.join(INSTALL_REGISTRY)}",
            )

        loop = asyncio.get_event_loop()
        if await loop.run_in_executor(None, _is_installed, tool_name):
            return ToolResult(
                success=True,
                result={"tool": tool_name, "status": "already_installed", "message": f"{tool_name} 已安装"},
            )

        method = await self._pick_method(entry)
        if not method:
            return ToolResult(
                success=False, result=None,
                error=f"无法确定 {tool_name} 的安装方式。请手动安装。",
            )

        cmd, args = method
        result = await loop.run_in_executor(None, _exec, cmd, args, 300)
        code, stdout, stderr = result

        if code != 0:
            return ToolResult(
                success=False,
                result={"stdout": stdout[-500:], "stderr": stderr[-500:]},
                error=f"安装 {tool_name} 失败 (exit {code}): {stderr[-200:]}",
            )

        verified = await loop.run_in_executor(None, _is_installed, tool_name)
        return ToolResult(
            success=True,
            result={
                "tool": tool_name,
                "method": f"{cmd} {' '.join(args)}",
                "status": "installed" if verified else "install_completed_but_not_in_path",
                "message": (
                    f"{tool_name} 安装成功"
                    if verified
                    else f"安装命令执行完毕，但 {tool_name} 未在 PATH 中找到"
                ),
            },
        )

    async def _pick_method(self, entry: Dict[str, str]) -> Optional[tuple]:
        loop = asyncio.get_event_loop()
        os_name = sys.platform

        # 对齐 TS pickMethod：darwin 先 brew；linux 先 apt 再 brew；然后 go → pip → brew 兜底
        if os_name == "darwin" and entry.get("brew"):
            if await loop.run_in_executor(None, _is_installed, "brew"):
                return "brew", ["install", entry["brew"]]

        if os_name.startswith("linux"):
            if entry.get("apt") and await loop.run_in_executor(None, _is_installed, "apt-get"):
                return "sudo", ["apt-get", "install", "-y", entry["apt"]]
            if entry.get("brew") and await loop.run_in_executor(None, _is_installed, "brew"):
                return "brew", ["install", entry["brew"]]

        if entry.get("go") and await loop.run_in_executor(None, _is_installed, "go"):
            return "go", ["install", entry["go"]]

        if entry.get("pip") and await loop.run_in_executor(None, _is_installed, "pip3"):
            return "pip3", ["install", entry["pip"]]

        if entry.get("brew") and await loop.run_in_executor(None, _is_installed, "brew"):
            return "brew", ["install", entry["brew"]]

        return None

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": list(INSTALL_REGISTRY.keys()),
                        "description": "要安装的工具名（白名单）",
                    },
                },
                "required": ["tool"],
            },
        }


def _is_installed(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _exec(cmd: str, args: List[str], timeout_sec: int):
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1")
    try:
        r = subprocess.run(
            [cmd] + args, capture_output=True, text=True,
            timeout=timeout_sec, encoding="utf-8", errors="ignore", env=env,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "超时"
    except FileNotFoundError:
        return -1, "", f"{cmd} 不可用"
