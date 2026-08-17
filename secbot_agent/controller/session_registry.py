"""会话注册表 — 进程级单例，供 /api/sessions 与 chat 交互登记共用。

对齐 TS sessions.service.ts（被动内存登记簿，SessionRecordDto 字段逐字一致），
唯一的有意分歧：POST /api/sessions/{id}/commands 在 Python 侧桥接
terminal_session 工具会话池真实执行命令（TS 仅记录客户端回填的 command+result），
差异记录在 docs/API_PARITY.md。

存储复用 MainController.session_manager（与 network connect/execute 同源），
不引入第二套会话存储。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from utils.logger import logger

# 会话注册表容量上限（LRU 语义：超过后丢弃最早的 chat 会话记录）
_MAX_REGISTRY_SIZE = 500


def get_session_registry():
    """进程级单例：复用 MainController 的 SessionManager（与远程控制同源）。"""
    from router.dependencies import get_main_controller

    return get_main_controller().session_manager


def register_interaction(session_id: str, agent_type: str = "agent", prompt: str = "") -> None:
    """chat 交互请求结束后登记会话（connection_type=chat），供 GET /api/sessions 观察。"""
    registry = get_session_registry()
    if session_id in registry.sessions:
        registry.update_session_activity(session_id)
        return
    _evict_if_full(registry)
    registry.create_session(target_ip="", connection_type="chat", auth_info={"agent": agent_type})
    # create_session 生成自己的 id；改写为交互的 request_id 以便客户端对账
    created = list(registry.sessions.values())[-1]
    registry.sessions.pop(created["session_id"], None)
    record = dict(created)
    record["session_id"] = session_id
    registry.sessions[session_id] = record
    logger.debug(f"登记交互会话: {session_id} (agent={agent_type})")


def _evict_if_full(registry) -> None:
    if len(registry.sessions) < _MAX_REGISTRY_SIZE:
        return
    # 优先淘汰 chat 会话（远程控制会话有 commands/files 台账价值更高）
    for sid, rec in registry.sessions.items():
        if rec.get("connection_type") == "chat":
            registry.sessions.pop(sid, None)
            return
    registry.sessions.pop(next(iter(registry.sessions)), None)


async def execute_via_terminal(session_id: str, command: str) -> Dict:
    """桥接 terminal_session 工具会话池真实执行命令（有意增强，非 TS 对齐）。

    懒打开终端会话；输出与耗时进 result 字段。
    """
    import time

    from tools.offense.control.terminal_tool import TerminalSessionTool

    registry = get_session_registry()
    record = registry.sessions.get(session_id)
    if record is None:
        return {"success": False, "error": "terminal unavailable"}

    tool = TerminalSessionTool()
    terminal_id = record.get("terminal_session_id")
    if not terminal_id or terminal_id not in tool._sessions:
        r = await tool.execute(action="open")
        if not r.success:
            return {"success": False, "error": f"terminal open failed: {r.error}"}
        terminal_id = (r.result or {}).get("session_id")
        record["terminal_session_id"] = terminal_id

    started = time.time()
    r = await tool.execute(action="exec", session_id=terminal_id, command=command)
    duration_ms = int((time.time() - started) * 1000)
    output = (r.result or {}).get("output", "") if isinstance(r.result, dict) else str(r.result or "")
    return {
        "success": r.success,
        "output": output,
        "error": r.error or "",
        "duration_ms": duration_ms,
    }


async def close_terminal(session_id: str) -> None:
    """关闭会话挂载的终端（若有）。"""
    from tools.offense.control.terminal_tool import TerminalSessionTool

    registry = get_session_registry()
    record = registry.sessions.get(session_id) or {}
    terminal_id = record.get("terminal_session_id")
    if terminal_id:
        await TerminalSessionTool().execute(action="close", session_id=terminal_id)


def list_sessions(status: Optional[str] = None) -> List[Dict]:
    return get_session_registry().list_sessions(status)


def get_session(session_id: str) -> Optional[Dict]:
    return get_session_registry().get_session(session_id)


def sessions_by_target(target_ip: str) -> List[Dict]:
    return get_session_registry().get_session_by_target(target_ip)
