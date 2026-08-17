"""CLI 斜杠命令注册表 — 单一事实源（补全列表 / 帮助文本 / 分发三者同源生成）。

对齐 TS terminal-ui/src/slash.ts + App.tsx 命令面板注册表：
/agent /new-session /sessions /help /list-agents /model /log-level /logs /tools
/skills /skill <name> /create-skill <name> /ask /task /accept /reject /exit

与 TS 的差异：/accept /reject /exit 为 Python CLI 进程内实现（TS terminal-ui 无此命令，
确认流在 SSE 事件里处理；exit 由 Ink keybind 处理）——记录 docs/API_PARITY.md 之外，
属 CLI 行为差异（非 REST 契约）。
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


@dataclass
class SlashCommand:
    name: str
    description: str
    aliases: List[str] = field(default_factory=list)
    args_hint: str = ""  # 参数说明，如 "<name> [--description 文本]"
    handler: Optional[Callable[..., Awaitable[None]]] = None

    @property
    def display(self) -> str:
        if self.args_hint:
            return f"{self.name} {self.args_hint}"
        return self.name


@dataclass
class CommandResult:
    """分发结果：handled=True 表示命令已消费；chat 非空则继续发送消息。"""

    handled: bool = True
    chat_message: Optional[str] = None
    chat_mode: str = "agent"
    exit_repl: bool = False


class CommandRegistry:
    """命令注册表：注册/查找/分发/渲染帮助与补全，全部同源。"""

    def __init__(self) -> None:
        self._commands: Dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        key = command.name.lstrip("/").lower()
        self._commands[key] = command

    def lookup(self, raw: str) -> Optional[SlashCommand]:
        """按首 token 查找（支持别名）。"""
        token = raw.strip().split()[0].lower() if raw.strip() else ""
        token = token.lstrip("/")
        for cmd in self._commands.values():
            if token == cmd.name.lstrip("/").lower() or token in [
                a.lstrip("/").lower() for a in cmd.aliases
            ]:
                return cmd
        return None

    def all_commands(self) -> List[SlashCommand]:
        return list(self._commands.values())

    def completions(self) -> List[str]:
        """prompt_toolkit 补全列表：含别名。"""
        out = []
        for cmd in self._commands.values():
            out.append(cmd.name)
            out.extend(cmd.aliases)
        return sorted(set(out))

    def render_help(self, console: Console) -> None:
        """帮助面板：每行 = 命令（含参数） + 描述；与补全同源，永不脱节。"""
        from rich.table import Table as _Table

        grid = _Table.grid(padding=(0, 3))
        grid.add_column(justify="left")
        grid.add_column(justify="left")
        for cmd in self.all_commands():
            names = cmd.name if not cmd.aliases else f"{cmd.name} ({'/'.join(cmd.aliases)})"
            grid.add_row(Text(names, style="bold cyan"), Text(cmd.description, style="white"))
        console.print(Panel(grid, title="命令列表", border_style="bright_blue"))


def parse_option_values(parts: List[str], flag: str) -> List[str]:
    """对齐 TS parseOptionValues：flag 后到下一个 --flag 之前的词合并为一段。"""
    values: List[str] = []
    i = 0
    while i < len(parts):
        if parts[i] != flag:
            i += 1
            continue
        segment: List[str] = []
        j = i + 1
        while j < len(parts) and not parts[j].startswith("--"):
            segment.append(parts[j])
            j += 1
        if segment:
            values.append(" ".join(segment))
        i = j
    return values


def parse_option_value(parts: List[str], flag: str) -> Optional[str]:
    values = parse_option_values(parts, flag)
    return values[0] if values else None


def build_default_registry(handlers: Optional[Dict[str, Callable[..., Awaitable]]] = None) -> CommandRegistry:
    """构建默认命令集 — 命令名/别名/描述的唯一事实源。

    handlers: 命令名 → 协程处理器的映射（由 runner 注入闭包）。
    传入后每个命令都绑定 handler（无宣传但无实现的假命令）；缺省仅含元数据，
    供离线场景（如补全提示）使用。
    """
    registry = CommandRegistry()

    def _bind(name: str, **kwargs) -> None:
        handler = (handlers or {}).get(name)
        registry.register(SlashCommand(name=name, handler=handler, **kwargs))

    _bind("/help", description="显示命令列表与集成工具概览",
          aliases=["/h", "/?"])
    _bind("/model", description="选择/配置推理后端与模型")
    _bind("/agent", description="切换智能体（super→superhackbot，default→secbot-cli）",
          args_hint="[super|default]")
    _bind("/ask", description="余文按 agent 模式发送（兼容旧命令，不切 QA）",
          args_hint="<文本>")
    _bind("/task", description="余文按 agent 模式发送（TS 遗留命令，保留对齐）",
          args_hint="<文本>")
    _bind("/new-session", description="新建空白会话")
    _bind("/sessions", description="列出并切换会话")
    _bind("/list-agents", description="列出智能体（详情）")
    _bind("/tools", description="内置工具（分类浏览）")
    _bind("/skills", description="列出 Skills")
    _bind("/skill", description="查看指定 Skill 正文", args_hint="<name>")
    _bind("/create-skill", description="创建 Skill",
          args_hint="<name> [--description 文本] [--trigger xxx] [--tag xxx] [--prerequisite xxx] [--author xxx]")
    _bind("/log-level", description="日志级别（INFO/DEBUG）")
    _bind("/logs", description="运行日志（最近 120 行）")
    _bind("/accept", description="确认敏感操作（superhackbot）")
    _bind("/reject", description="拒绝敏感操作（superhackbot）")
    _bind("/exit", description="退出（也可用 exit/quit）", aliases=["/quit"])

    return registry


def split_input(raw: str) -> List[str]:
    """把输入切成 token 列表（引号感知）。"""
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()
