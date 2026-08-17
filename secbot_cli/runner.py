"""
进程内交互运行器：直接调用 SessionManager，通过 EventBus + Rich 在终端实时展示。
不再经过 HTTP/SSE 网络通信，CLI 与核心逻辑在同一进程内完成。
"""

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich.align import Align
from rich.table import Table

from secbot_agent.core.session import SessionManager
from router.dependencies import (
    get_agents,
    get_context_assembler,
    get_explore_agent,
    get_intent_router,
    get_planner_agent,
    get_qa_agent,
    get_summary_agent,
    get_db_manager,
)
from utils.event_bus import EventBus, EventType, Event
from utils.logger import logger

try:
    # 可选：为 “输入 / 自动弹出命令候选” 提供交互补全
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
except Exception:  # pragma: no cover
    PromptSession = None
    WordCompleter = None


@dataclass
class RenderBlock:
    """终端渲染块：统一交给父渲染器处理 Markdown，再由子类做二次渲染。"""

    kind: str
    body: Any
    title: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class BaseMarkdownBlockRenderer:
    """父渲染器：统一做 Markdown 基础渲染。"""

    default_title = "内容"
    title_style = "bold white"
    border_style = "white"

    def __init__(self, console: Console):
        self.console = console

    def render(self, block: RenderBlock) -> None:
        title = self._build_title(block)
        markdown_text = self._build_markdown(block)
        renderable = self._to_renderable(markdown_text)
        self.console.print(
            Panel(
                renderable,
                title=Text(title, style=self.title_style),
                border_style=self.border_style,
            )
        )

    def _build_title(self, block: RenderBlock) -> str:
        return (block.title or self.default_title).strip() or self.default_title

    def _build_markdown(self, block: RenderBlock) -> str:
        value = block.body
        if isinstance(value, (dict, list)):
            body = json.dumps(value, ensure_ascii=False, indent=2)
            return f"```json\n{body}\n```"
        body = str(value or "").strip()
        return body or " "

    @staticmethod
    def _to_renderable(markdown_text: str):
        try:
            return Markdown(markdown_text)
        except Exception:
            return Text(markdown_text)


class PlanningBlockRenderer(BaseMarkdownBlockRenderer):
    default_title = "规划"
    title_style = "bold magenta"
    border_style = "magenta"


class ThoughtBlockRenderer(BaseMarkdownBlockRenderer):
    default_title = "推理"
    title_style = "bold yellow"
    border_style = "yellow"


class ActionBlockRenderer(BaseMarkdownBlockRenderer):
    default_title = "执行"
    title_style = "bold cyan"
    border_style = "cyan"
    _MAX_RESULT_CHARS = 2000

    def _build_markdown(self, block: RenderBlock) -> str:
        meta = block.meta or {}
        lines: list[str] = []
        tool = meta.get("tool", "")
        status = meta.get("status", "")
        script = meta.get("script", "")
        params = meta.get("params", {})
        error = meta.get("error")
        result = meta.get("result")

        if tool:
            lines.append(f"**工具**: `{tool}`")
        if status:
            lines.append(f"**状态**: {status}")

        if script:
            lines.append("**命令**:")
            lines.append(f"```bash\n{script}\n```")
        elif params:
            try:
                params_text = json.dumps(params, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                params_text = str(params)
            lines.append("**参数**:")
            lines.append(f"```json\n{params_text}\n```")

        if error:
            lines.append(f"**错误**: {error}")

        if result not in (None, ""):
            result_text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
            if len(result_text) > self._MAX_RESULT_CHARS:
                result_text = result_text[: self._MAX_RESULT_CHARS] + "\n... (已截断)"
            lines.append("**输出**:")
            lines.append(f"```text\n{result_text}\n```")

        if not lines:
            return super()._build_markdown(block)
        return "\n\n".join(lines)


class ObservationBlockRenderer(BaseMarkdownBlockRenderer):
    default_title = "观察"
    title_style = "bold blue"
    border_style = "blue"


class SummaryBlockRenderer(BaseMarkdownBlockRenderer):
    default_title = "总结"
    title_style = "bold green"
    border_style = "green"


class ErrorBlockRenderer(BaseMarkdownBlockRenderer):
    default_title = "错误"
    title_style = "bold red"
    border_style = "red"


class CliRenderRegistry:
    """渲染注册表：按块类型分发到子渲染器。"""

    def __init__(self, console: Console):
        base = BaseMarkdownBlockRenderer(console)
        self._renderers = {
            "default": base,
            "planning": PlanningBlockRenderer(console),
            "thought": ThoughtBlockRenderer(console),
            "action": ActionBlockRenderer(console),
            "observation": ObservationBlockRenderer(console),
            "summary": SummaryBlockRenderer(console),
            "report": SummaryBlockRenderer(console),
            "error": ErrorBlockRenderer(console),
        }

    def render(self, block: RenderBlock) -> None:
        renderer = self._renderers.get(block.kind, self._renderers["default"])
        renderer.render(block)


class CliEventPrinter:
    """订阅 EventBus 事件，用 Rich 在终端打印各阶段信息。"""

    def __init__(self, console: Console):
        self.console = console
        self._current_thought: list[str] = []
        self._current_phase: str = ""
        self._registry = CliRenderRegistry(console)

    @staticmethod
    def _strip_rich_markup(text: str) -> str:
        """去掉 rich markup，避免标题里出现 [bold ...] 语法。"""
        return re.sub(r"\[[^\]]+\]", "", text or "").strip()

    def handle(self, event: Event) -> None:
        t = event.type
        d = event.data

        if t == EventType.PLAN_START:
            summary = d.get("summary", "")
            todos = d.get("todos", [])
            lines = []
            if summary:
                lines.append(summary)
            if todos:
                lines.append("")
                for todo in todos:
                    content = todo.get("content", "")
                    status = todo.get("status", "pending")
                    mark = {"pending": "○", "in_progress": "◉", "completed": "✓"}.get(
                        status, "○"
                    )
                    lines.append(f"  {mark} {content}")
            self._registry.render(
                RenderBlock(
                    kind="planning",
                    title="规划",
                    body="\n".join(lines) if lines else "规划中...",
                )
            )

        elif t == EventType.THINK_START:
            self._current_thought = []

        elif t == EventType.THINK_CHUNK:
            chunk = d.get("chunk", "")
            if chunk:
                self._current_thought.append(chunk)

        elif t == EventType.THINK_END:
            thought = d.get("thought", "") or "".join(self._current_thought)
            if thought:
                self._registry.render(
                    RenderBlock(kind="thought", title="推理", body=thought)
                )
            self._current_thought = []

        elif t == EventType.EXEC_START:
            tool = d.get("tool", "")
            params = d.get("params", {})
            script = d.get("script", "")
            from secbot_cli.stream_constants import tool_class

            cls = tool_class(tool)
            title = {"exploring": "探索", "terminal": "终端"}.get(cls, "工具执行")
            self._registry.render(
                RenderBlock(
                    kind="action",
                    title=title,
                    body="",
                    meta={
                        "tool": tool,
                        "status": "执行中",
                        "params": params,
                        "script": script,
                    },
                )
            )

        elif t == EventType.EXEC_RESULT:
            tool = d.get("tool", "")
            success = d.get("success", True)
            from secbot_cli.stream_constants import tool_class

            # TRANSIENT 工具：完成后收起、不强调展示（对齐 TS TRANSIENT_TOOLS）
            if tool_class(tool) == "transient":
                self.console.print(f"[dim]✓ {tool} 完成（输出已收起）[/dim]")
                return
            self._registry.render(
                RenderBlock(
                    kind="action",
                    title="工具执行结果",
                    body="",
                    meta={
                        "tool": tool,
                        "status": "完成" if success else "失败",
                        "result": d.get("result", "") if success else None,
                        "error": d.get("error", "未知错误") if not success else None,
                    },
                )
            )

        elif t == EventType.CONTENT:
            content = d.get("content", "")
            if content:
                view_type = d.get("view_type", "summary")
                tool = d.get("tool", "")
                raw_title = self._strip_rich_markup(str(d.get("title", "")))
                if tool or "观察" in raw_title:
                    title = f"观察 · {tool}" if tool else (raw_title or "观察")
                    kind = "observation"
                elif view_type == "summary":
                    title = raw_title or "总结"
                    kind = "summary"
                else:
                    title = raw_title or "内容"
                    kind = "default"
                self._registry.render(
                    RenderBlock(kind=kind, title=title, body=content)
                )

        elif t == EventType.REPORT_END:
            report = d.get("report", "")
            if report:
                self._registry.render(
                    RenderBlock(kind="report", title="报告", body=report)
                )

        elif t == EventType.TASK_PHASE:
            phase = d.get("phase", "")
            detail = d.get("detail", "")
            if phase and phase != "done":
                label = {
                    "planning": "规划中",
                    "thinking": "推理中",
                    "exec": "执行中",
                    "report": "报告生成中",
                }.get(phase, phase)
                if detail:
                    label = f"{label}: {detail}"
                if label != self._current_phase:
                    self._current_phase = label
                    self.console.print(f"[dim]⟫ {label}[/dim]")

        elif t == EventType.PLAN_TODO:
            todo_id = d.get("todo_id", "")
            status = d.get("status", "")
            result_summary = d.get("result_summary", "")
            mark = {"pending": "○", "in_progress": "◉", "completed": "✓"}.get(status, "○")
            msg = f"[dim]  {mark} [{todo_id}] {status}[/dim]"
            if result_summary:
                msg += f" — {result_summary}"
            self.console.print(msg)

        elif t == EventType.ROOT_REQUIRED:
            pass

        elif t == EventType.ERROR:
            error = d.get("error", "")
            self._registry.render(
                RenderBlock(kind="error", title="错误", body=str(error))
            )


async def _get_root_password_interactive(
    command: str, console: Console
) -> Optional[Dict[str, Any]]:
    """终端内交互式 root 权限请求。"""
    console.print(
        Panel(
            f"以下命令需要 root/管理员权限:\n[bold]{command}[/bold]",
            title="[bold yellow]权限请求[/bold yellow]",
            border_style="yellow",
        )
    )
    console.print("[1] 执行一次  [2] 总是允许  [3] 拒绝")
    choice = Prompt.ask("选择", choices=["1", "2", "3"], default="3", console=console)
    if choice == "3":
        return {"action": "deny"}
    if choice == "2":
        from utils.root_policy import save_root_policy
        save_root_policy(root_policy="always_allow")

    password = Prompt.ask("请输入密码", password=True, console=console)
    action = "run_once" if choice == "1" else "always_allow"
    return {"action": action, "password": password}


def _create_session_manager(console: Console) -> SessionManager:
    """实例化 SessionManager 及其依赖，与 router 中的初始化逻辑对齐。"""
    get_db_manager()

    event_bus = EventBus()
    printer = CliEventPrinter(console)
    event_bus.subscribe_all(printer.handle)

    async def root_callback(command: str) -> Optional[Dict[str, Any]]:
        return await _get_root_password_interactive(command, console)

    session_manager = SessionManager(
        event_bus=event_bus,
        console=console,
        agents=get_agents(),
        planner=get_planner_agent(),
        qa_agent=get_qa_agent(),
        summary_agent=get_summary_agent(),
        context_assembler=get_context_assembler(),
        intent_router=get_intent_router(),
        explore_agent=get_explore_agent(),
        get_root_password=root_callback,
    )
    return session_manager


async def _run_single_message(
    session_manager: SessionManager,
    message: str,
    agent_type: Optional[str] = None,
    mode: str = "agent",
) -> str:
    """处理单条消息并返回响应。"""
    force_qa = mode == "ask"
    force_agent_flow = mode == "agent"
    return await session_manager.handle_message(
        message,
        agent_type=agent_type,
        force_qa=force_qa,
        force_agent_flow=force_agent_flow,
    )


def _render_startup_screen(
    console: Console, session_manager: SessionManager, agent_type: Optional[str]
) -> None:
    """启动欢迎页（对齐 `assets/show_picture.png` 风格）。"""
    banner = r"""
███████╗███████╗ ██████╗██████╗  ██████╗ ████████╗
██╔════╝██╔════╝██╔════╝██╔══██╗██╔═══██╗╚══██╔══╝
███████╗█████╗  ██║     ██████╔╝██║   ██║   ██║
╚════██║██╔══╝  ██║     ██╔══██╗██║   ██║   ██║
███████║███████╗╚██████╗██████╔╝╚██████╔╝   ██║
╚══════╝╚══════╝ ╚═════╝╚═════╝  ╚═════╝    ╚═╝
""".strip("\n")

    console.print()
    console.print(Align.center(Text(banner, style="bold cyan")))
    console.print(Align.center(Text("Security Testing Agent", style="cyan")))
    console.print()

    # 顶部徽标行：hackbot/default/auto + 工具数 + 模型提示（不触发 LLM 初始化）
    tools_count = 0
    try:
        agents = getattr(session_manager, "agents", None) or {}
        # CLI 进程内 agents 结构：{'secbot-cli': CoordinatorAgent, 'superhackbot': SuperHackbotAgent}
        # 优先使用当前 agent_type 对应实例，回退到 secbot-cli。
        coordinator = agents.get(agent_type or "secbot-cli") or agents.get("secbot-cli")
        default_agent = getattr(coordinator, "_default_agent", None) if coordinator else None
        tools = getattr(default_agent, "security_tools", None) if default_agent else None
        tools_count = len(tools) if isinstance(tools, list) else 0
    except Exception:
        tools_count = 0

    # 为了对齐启动引导与截图效果：启动页固定提示用户用 /model 选择。
    model_tip = "未选择（/model 选择）"

    _ = agent_type  # 预留：后续若要在徽标行展示可按 agent_type 显示
    console.print(
        Text.assemble(
            (" secbot ", "bold white on blue"),
            (" ", ""),
            (" default ", "bold white on green"),
            (" ", ""),
            (" auto ", "bold white on grey37"),
            ("  ", ""),
            (f"{tools_count} tools", "dim"),
            ("  ", ""),
            (model_tip, "dim"),
        )
    )
    console.print()

    # Quick Start（两列）
    left = [
        "• 扫描当前主机所在内网环境",
        "• 你好 / 你能做什么",
        "• Scan localhost for open ports",
        "• /plan 编写测试计划，/start 执行计划",
    ]
    right = [
        "推荐首条，发现内网主机与端口",
        "问候或了解能力（走问答）",
        "扫描本机开放端口",
        "命令一览：规划/执行",
    ]

    grid = Table.grid(padding=(0, 3))
    grid.add_column(justify="left", ratio=2)
    grid.add_column(justify="left", ratio=3)
    for left_item, right_item in zip(left, right):
        grid.add_row(Text(left_item, style="cyan"), Text(right_item, style="white"))

    body = Table.grid(padding=(0, 0))
    body.add_column(ratio=1)
    body.add_row(Text("不知道做什么？试试这些：", style="bold cyan"))
    body.add_row(Text(" ", style="white"))
    body.add_row(grid)

    console.print(
        Panel(
            body,
            title="Quick Start",
            title_align="center",
            border_style="bright_blue",
        )
    )
    console.print(
        Text.assemble(
            ("模式 ", "white"),
            ("default", "bold"),
            ("（自动） | ", "white"),
            ("super", "bold"),
            ("（专家）；当前：", "white"),
            ("default", "bold green"),
            ("。输入 ", "white"),
            ("/agent", "bold cyan"),
            (" 切换；启动时 ", "white"),
            ("-a secbot-cli", "bold cyan"),
            (" | ", "white"),
            ("-a superhackbot", "bold cyan"),
            ("。", "white"),
        )
    )
    console.print(Text("输入 / 后回车可列出所有命令（或输入 / 后自动弹出）。exit 退出", style="dim"))
    console.print()
    console.print(Text.assemble(("— 模式：", "dim"), (" 默认", "bold blue")))
    console.print()


def _build_registry(console: Console, state: "_ReplState"):
    """注册表 + 全部命令 handler（单一事实源：补全/帮助/分发同源）。

    命令名/别名/描述元数据来自 build_default_registry；此处仅注入 handler 闭包。
    先构建一个临时注册表供 /help 引用，再以 handlers 重建并复用同一 render_help。
    """
    from secbot_cli.commands import (
        CommandResult,
        build_default_registry,
        parse_option_value,
        parse_option_values,
        split_input,
    )

    registry = build_default_registry({})

    async def _help(rest: List[str]) -> "CommandResult":
        registry.render_help(console)
        _render_tools_overview(console)
        return CommandResult()

    async def _model(rest: List[str]) -> "CommandResult":
        _run_model_selector_inline(console)
        return CommandResult()

    async def _agent(rest: List[str]) -> "CommandResult":
        arg = (rest[0] if rest else "").lower()
        if arg in ("super", "superhackbot"):
            state.agent_type = "superhackbot"
        elif arg in ("default", "secbot-cli", ""):
            state.agent_type = "secbot-cli"
        else:
            console.print(f"[yellow]未知 agent: {arg}（可用 super / default）[/yellow]")
            return CommandResult()
        console.print(f"[green]已切换智能体: {state.agent_type}[/green]")
        return CommandResult()

    async def _ask_task(rest: List[str]) -> "CommandResult":
        # 对齐 TS slash.ts:76-95：/ask /task 均按 agent 模式发送余文，不切 QA
        message = " ".join(rest)
        if not message:
            console.print("[yellow]用法: /ask <文本>（余文按 agent 模式发送）[/yellow]")
            return CommandResult()
        return CommandResult(chat_message=message, chat_mode="agent")

    async def _new_session(rest: List[str]) -> "CommandResult":
        state.session_manager = _create_session_manager(console)
        console.print("[green]已新建空白会话（上下文已隔离）[/green]")
        return CommandResult()

    async def _sessions(rest: List[str]) -> "CommandResult":
        from secbot_agent.controller.session_registry import list_sessions

        sessions = list_sessions()
        if not sessions:
            console.print("[yellow]当前无登记会话（chat 交互结束后自动登记）[/yellow]")
            return CommandResult()
        from rich.table import Table

        table = Table(title="Sessions", border_style="bright_blue")
        table.add_column("#", justify="right")
        table.add_column("session_id")
        table.add_column("conn")
        table.add_column("target")
        table.add_column("status")
        for i, s in enumerate(sessions, 1):
            table.add_row(str(i), s.get("session_id", ""), s.get("connection_type", ""),
                          s.get("target_ip", "") or "-", s.get("status", ""))
        console.print(table)
        choice = console.input("[dim]切换到 #（回车跳过）: [/dim]").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(sessions):
            console.print(f"[green]会话 {sessions[int(choice)-1]['session_id']} 的历史见 /api/sessions；"
                          f"CLI 当前对话上下文不变[/green]")
        return CommandResult()

    async def _list_agents(rest: List[str]) -> "CommandResult":
        agents = state.session_manager.agents or get_agents()
        lines = []
        for type_, inst in agents.items():
            name = getattr(inst, "name", type_)
            desc = (getattr(inst, "description", "") or "").strip().splitlines()
            lines.append(f"{type_}: {name} — {desc[0] if desc else ''}")
        console.print(Panel("\n".join(lines) or "(无)", title="智能体列表", border_style="bright_blue"))
        return CommandResult()

    async def _tools(rest: List[str]) -> "CommandResult":
        _render_tools_browser(console)
        return CommandResult()

    async def _skills(rest: List[str]) -> "CommandResult":
        from secbot_agent.skills.service import SkillService

        skills = SkillService().list_skills()
        if not skills:
            console.print("[yellow]未发现 Skills（workspace/skills/ 下可放置）[/yellow]")
            return CommandResult()
        lines = []
        for s in skills:
            lines.append(f"{s.get('slug', '')} [{s.get('scope', '')}] — {s.get('description', '')}")
        console.print(Panel("\n".join(lines), title="Skills", border_style="bright_blue"))
        return CommandResult()

    async def _skill(rest: List[str]) -> "CommandResult":
        from secbot_agent.skills.service import SkillService, SkillNotFound

        name = rest[0] if rest else ""
        if not name:
            console.print("用法: /skill <name>")
            return CommandResult()
        try:
            skill = SkillService().get_skill(name)
        except SkillNotFound:
            console.print(f"[yellow]Skill 不存在: {name}[/yellow]")
            return CommandResult()
        text = "\n".join([
            f"# {skill.get('slug', name)}", "",
            skill.get("description", ""), "",
            f"triggers: {', '.join(skill.get('triggers', []) or [])}",
            f"tags: {', '.join(skill.get('tags', []) or [])}", "",
            skill.get("body", ""),
        ])
        console.print(Panel(text, title=f"Skill · {name}", border_style="bright_blue"))
        return CommandResult()

    async def _create_skill(rest: List[str]) -> "CommandResult":
        from secbot_agent.skills.service import SkillService, SkillAlreadyExists

        parts = split_input(f"/create-skill {' '.join(rest)}")
        if not rest or not rest[0]:
            console.print("用法: /create-skill <name> [--description 文本] [--trigger xxx] [--tag xxx] [--prerequisite xxx] [--author xxx]")
            return CommandResult()
        name = rest[0]
        payload = {
            "name": name,
            "description": parse_option_value(parts, "--description"),
            "author": parse_option_value(parts, "--author"),
            "tags": parse_option_values(parts, "--tag"),
            "triggers": parse_option_values(parts, "--trigger"),
            "prerequisites": parse_option_values(parts, "--prerequisite"),
        }
        try:
            svc = SkillService()
            created = svc.create_skill({k: v for k, v in payload.items() if v})
        except SkillAlreadyExists:
            console.print(f"[yellow]Skill 已存在: {name}[/yellow]")
            return CommandResult()
        except Exception as e:
            console.print(f"[red]创建失败: {e}[/red]")
            return CommandResult()
        console.print(f"[green]已创建 skill {created['slug']}[/green]\n"
                      f"路径: {created['relativeDir']}\n描述: {created['description']}")
        return CommandResult()

    async def _log_level(rest: List[str]) -> "CommandResult":
        from utils.logger import set_log_level

        arg = (rest[0] if rest else "").upper()
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if arg in levels:
            set_log_level(arg)
            console.print(f"[green]日志级别: {arg}[/green]")
            return CommandResult()
        console.print("选择日志级别: " + " ".join(f"[{i+1}]{lv}" for i, lv in enumerate(levels)))
        choice = console.input("[dim]选择: [/dim]").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(levels):
            set_log_level(levels[int(choice) - 1])
            console.print(f"[green]日志级别: {levels[int(choice)-1]}[/green]")
        return CommandResult()

    async def _logs(rest: List[str]) -> "CommandResult":
        import os

        cwd = os.getcwd()
        targets = [
            ("BACKEND-RUNTIME", os.path.join(cwd, "logs", "backend-runtime.log")),
            ("CLI-RUNTIME", os.path.join(cwd, "logs", "cli-runtime.log")),
        ]
        sections = []
        for title, path in targets:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    lines = [ln for ln in f.read().splitlines() if ln.strip()]
                tail = lines[-120:] if len(lines) > 120 else lines
                sections.append(f"## {title}\n" + ("\n".join(tail) or "(empty)"))
            except OSError:
                sections.append(f"## {title}\n(log file not found — 运行产生日志后生成)")
        console.print(Panel("\n\n".join(sections), title="运行日志（最近 120 行）", border_style="bright_blue"))
        return CommandResult()

    async def _accept(rest: List[str]) -> "CommandResult":
        await _route_confirmation(state, True, console)
        return CommandResult()

    async def _reject(rest: List[str]) -> "CommandResult":
        await _route_confirmation(state, False, console)
        return CommandResult()

    async def _exit(rest: List[str]) -> "CommandResult":
        return CommandResult(exit_repl=True)

    handlers = {
        "/help": _help,
        "/model": _model,
        "/agent": _agent,
        "/ask": _ask_task,
        "/task": _ask_task,
        "/new-session": _new_session,
        "/sessions": _sessions,
        "/list-agents": _list_agents,
        "/tools": _tools,
        "/skills": _skills,
        "/skill": _skill,
        "/create-skill": _create_skill,
        "/log-level": _log_level,
        "/logs": _logs,
        "/accept": _accept,
        "/reject": _reject,
        "/exit": _exit,
    }
    return build_default_registry(handlers)


async def _route_confirmation(state: "_ReplState", accepted: bool, console: Console) -> None:
    """/accept /reject → SecurityReActAgent.handle_accept（superhackbot 确认流闭环）。"""
    agents = state.session_manager.agents or {}
    agent = agents.get("superhackbot") or agents.get(state.agent_type)
    handler = getattr(agent, "handle_accept", None)
    inner = getattr(agent, "_default_agent", None)
    if handler is None and inner is not None:
        handler = getattr(inner, "handle_accept", None)
        agent = inner
    if handler is None:
        console.print("[yellow]当前智能体不支持确认流（需 superhackbot）[/yellow]")
        return
    try:
        # handle_accept(choice: int)：1=接受首个方案；拒绝走 confirmation.reject
        if accepted:
            result = await handler(1)
        else:
            confirmation = getattr(agent, "confirmation", None)
            if confirmation is None or not confirmation.is_pending():
                result = "当前没有待确认的操作。"
            else:
                confirmation.reject()
                result = "已拒绝待确认操作。"
        label = "已确认" if accepted else "已拒绝"
        console.print(f"[green]{label}: {result if result else 'ok'}[/green]")
    except Exception as e:
        console.print(f"[red]确认流调用失败: {e}[/red]")


def _render_tools_overview(console: Console) -> None:
    """/help 附带工具概览——进程内聚合（离线可用，不经 HTTP）。"""
    try:
        from router.tools import _CATEGORIES

        lines = ["", "SECBOT 集成的安全工具"]
        total = 0
        for cat_id, cat_name, tool_list in _CATEGORIES:
            names = [t.name for t in tool_list]
            total += len(names)
            preview = ", ".join(names[:6]) + ("…" if len(names) > 6 else "")
            lines.append(f"【{cat_name}】{len(names)} 个 — {preview}")
        lines.insert(1, f"总计 {total} 个")
        console.print(Text("\n".join(lines), style="dim"))
    except Exception:
        pass


def _render_tools_browser(console: Console) -> None:
    """分类工具浏览（对齐 TS /tools 输出形态）。"""
    try:
        from router.tools import _CATEGORIES
    except Exception as e:
        console.print(f"[red]工具目录不可用: {e}[/red]")
        return
    lines = ["SECBOT 内置工具"]
    total = 0
    for cat_id, cat_name, tool_list in _CATEGORIES:
        total += len(tool_list)
        lines += ["", f"【{cat_name}】{len(tool_list)} 个"]
        for t in tool_list:
            lines.append(f"  {t.name:<24} — {t.description}")
    lines.insert(1, f"总计: {total} 个")
    console.print(Panel("\n".join(lines), title="工具目录", border_style="bright_blue"))


class _ReplState:
    """REPL 可变状态（agent 切换 / 会话重建）。"""

    def __init__(self, session_manager: SessionManager, agent_type: Optional[str]):
        self.session_manager = session_manager
        self.agent_type = agent_type


def _build_prompt_session(history_path) -> Optional["PromptSession"]:
    """创建支持补全 + 跨会话历史持久化的 PromptSession；不可用则返回 None。"""
    if PromptSession is None or WordCompleter is None:
        return None
    try:
        if not sys.stdin.isatty():
            return None
    except Exception:
        return None

    commands = _active_registry.completions() if _active_registry else ["/help"]
    completer = WordCompleter(commands, ignore_case=True, match_middle=True)
    kwargs = {}
    try:
        from prompt_toolkit.history import FileHistory

        kwargs["history"] = FileHistory(str(history_path))
    except Exception:
        pass
    return PromptSession(completer=completer, complete_while_typing=True, **kwargs)


# 当前 REPL 绑定的注册表（补全列表生成时可见）
_active_registry = None


async def run_interactive(
    console: Console,
    agent_type: Optional[str] = None,
    mode: str = "agent",
) -> None:
    """交互式 REPL：命令注册表分发 + prompt_toolkit 补全/历史。"""
    global _active_registry

    state = _ReplState(_create_session_manager(console), agent_type)
    _render_startup_screen(console, state.session_manager, agent_type)

    registry = _build_registry(console, state)
    _active_registry = registry

    import os
    history_path = os.path.expanduser("~/.secbot-cli/history")
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    pt_session = _build_prompt_session(history_path)

    while True:
        try:
            if pt_session is not None:
                try:
                    if hasattr(pt_session, "prompt_async"):
                        user_input = (await pt_session.prompt_async(">>> ") or "").strip()
                    else:
                        user_input = console.input("[bold green]>>> [/bold green]").strip()
                        pt_session = None
                except Exception:
                    user_input = console.input("[bold green]>>> [/bold green]").strip()
                    pt_session = None
            else:
                user_input = console.input("[bold green]>>> [/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见！[/dim]")
            break

        if not user_input:
            continue

        low = user_input.lower()
        if low in ("exit", "quit"):
            console.print("[dim]再见！[/dim]")
            break

        if user_input.startswith("/"):
            command = registry.lookup(user_input)
            if command is None:
                if user_input == "/":
                    registry.render_help(console)
                    continue
                console.print(f"[yellow]未知命令: {user_input.split()[0]}（/help 查看命令表）[/yellow]")
                continue
            if command.handler is None:
                console.print(f"[yellow]命令未实现: {command.name}[/yellow]")
                continue
            from secbot_cli.commands import split_input

            parts = split_input(user_input)
            result = await command.handler(parts[1:])
            if result.exit_repl:
                console.print("[dim]再见！[/dim]")
                break
            if result.chat_message:
                try:
                    await _run_single_message(
                        state.session_manager,
                        result.chat_message,
                        agent_type=state.agent_type,
                        mode=result.chat_mode,
                    )
                except KeyboardInterrupt:
                    console.print("\n[yellow]已中断当前任务[/yellow]")
                except Exception as e:
                    console.print(f"[bold red]处理出错: {e}[/bold red]")
                    logger.exception("CLI 交互错误")
            console.print()
            continue

        try:
            await _run_single_message(
                state.session_manager, user_input, agent_type=state.agent_type, mode=mode
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]已中断当前任务[/yellow]")
        except Exception as e:
            console.print(f"[bold red]处理出错: {e}[/bold red]")
            logger.exception("CLI 交互错误")

        console.print()


async def run_once(
    console: Console,
    message: str,
    agent_type: Optional[str] = None,
    mode: str = "agent",
) -> None:
    """单条消息模式：处理一条消息后退出。"""
    session_manager = _create_session_manager(console)
    try:
        await _run_single_message(
            session_manager, message, agent_type=agent_type, mode=mode
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/yellow]")
    except Exception as e:
        console.print(f"[bold red]处理出错: {e}[/bold red]")
        logger.exception("CLI 单次执行错误")


def _run_model_selector_inline(console: Console) -> None:
    """在交互式 REPL 中执行模型切换。"""
    try:
        from hackbot_config import get_llm_provider, save_llm_provider
        from utils.model_selector import run_model_selector, get_provider_model

        current = get_llm_provider()
        current_model = get_provider_model(current)
        provider, model = run_model_selector(
            console, current_provider=current, current_model=current_model
        )
        if provider is not None:
            save_llm_provider(provider)
            model_info = model or "(默认模型)"
            console.print(
                f"[green]已切换推理后端: {provider}，模型: {model_info}[/green]"
            )
            console.print("[dim]新配置将在下次创建 Agent 时生效。[/dim]")
    except Exception as e:
        console.print(f"[red]模型切换失败: {e}[/red]")
