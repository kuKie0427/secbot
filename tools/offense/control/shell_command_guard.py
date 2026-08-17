"""执行前校验：命令语法是否与当前真实 shell 环境一致（避免 LLM 按「猜的」终端生成命令）。

镜像 TS server/src/modules/tools/control/shell-command-guard.ts。
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Optional

ShellKind = str  # 'cmd' | 'powershell' | 'posix'


@dataclass
class ShellExecutionProfile:
    kind: ShellKind
    label: str  # 简短标签，如 cmd.exe、powershell、bash
    hint: str = ""  # 给模型/用户的语法提示


def _profile_hints(kind: ShellKind, label: str) -> str:
    if kind == "cmd":
        return (
            f"当前会话为 Windows CMD（{label}）：使用 dir、find、set/unset 风格变量引用 %VAR%、命令链接用 &；"
            "不要使用 PowerShell cmdlet（如 Get-ChildItem、$env:XXX）。"
        )
    if kind == "powershell":
        return (
            f"当前会话为 PowerShell（{label}）：可使用 Get-ChildItem、$env:XXX、cmdlet 管道；"
            '若必须跑 cmd 独占语法可嵌套 cmd /c "..." 。'
        )
    if kind == "posix":
        return (
            f"当前会话为类 Unix shell（{label}）：使用 ls、grep、find、export VAR=；"
            "不要使用 findstr、%VAR% 等典型 cmd 写法。"
        )
    return ""


def shell_profile(kind: ShellKind, label: str) -> ShellExecutionProfile:
    return ShellExecutionProfile(kind=kind, label=label, hint=_profile_hints(kind, label))


def execute_command_shell_profile() -> ShellExecutionProfile:
    """与 command_tool 的 spawn 逻辑一致：Windows 固定 cmd /d /s /c；非 Windows 为 login shell -lc。"""
    if sys.platform == "win32":
        return shell_profile("cmd", "cmd.exe (/d /s /c)")
    sh = os.environ.get("SHELL") or ("/bin/zsh" if sys.platform == "darwin" else "/bin/bash")
    base = re.split(r"[/\\]", sh)[-1] or sh
    return shell_profile("posix", f"{base} (-lc)")


def _looks_like_powershell_command(c: str) -> bool:
    if re.search(r"^\s*(powershell|pwsh)\s", c, re.IGNORECASE):
        return False
    if re.search(r"\$env:[A-Za-z_]", c, re.IGNORECASE):
        return True
    if re.search(r"\bGet-[A-Za-z][A-Za-z0-9-]*\b", c):
        return True
    if re.search(r"\b(Select-Object|Where-Object|ForEach-Object|Write-Host|Out-File|Invoke-Expression)\b", c):
        return True
    return False


def _looks_like_cmd_exclusive(c: str) -> bool:
    if re.search(r"^\s*cmd\s", c, re.IGNORECASE):
        return False
    if re.search(r"\bfindstr\b", c, re.IGNORECASE):
        return True
    if re.search(r"%[A-Za-z0-9_]+%", c):
        return True
    if re.search(r"\bwmic\b", c, re.IGNORECASE):
        return True
    return False


def _looks_like_windows_cmd_exclusive(c: str) -> bool:
    if re.search(r"^\s*(cmd|powershell|pwsh)\s", c, re.IGNORECASE):
        return False
    if re.search(r"\bfindstr\b", c, re.IGNORECASE):
        return True
    if re.search(r"\bwmic\b", c, re.IGNORECASE):
        return True
    if re.search(r"%[A-Za-z0-9_]+%", c):
        return True
    return False


def validate_command_against_shell(command: str, profile: ShellExecutionProfile) -> Optional[str]:
    """返回错误说明；None 表示未检出明显冲突（仍可能在运行时失败）。"""
    c = command.strip()
    if not c:
        return None

    if profile.kind == "cmd" and _looks_like_powershell_command(c):
        return (
            f"命令与当前执行环境不符：实际在 {profile.label} 下执行，但命令疑似 PowerShell。"
            f"请改为 CMD 兼容写法，或先执行 powershell / pwsh 再跑 cmdlet。{profile.hint}"
        )

    if profile.kind == "powershell" and _looks_like_cmd_exclusive(c):
        return (
            f"命令与当前执行环境不符：实际在 {profile.label} 下执行，但命令包含典型 cmd 语法（如 findstr、%VAR%）。"
            f'请改为 PowerShell 写法，或使用 cmd /c "..." 包裹。{profile.hint}'
        )

    if profile.kind == "posix" and _looks_like_windows_cmd_exclusive(c):
        return (
            f"命令与当前执行环境不符：实际在 {profile.label}（Unix shell）下执行，但命令含典型 Windows cmd 片段。"
            f"请改为 Unix 命令或明确说明跨平台意图。{profile.hint}"
        )

    return None
