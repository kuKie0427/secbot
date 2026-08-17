"""会话路由 — 对齐 TS sessions.controller.ts 的 7 个端点。

- 登记簿语义对齐 TS（被动内存登记簿）；POST /commands 桥接 terminal_session
  池真实执行（有意增强，见 docs/API_PARITY.md）。
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from secbot_agent.controller import session_registry

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


class CreateSessionRequest(BaseModel):
    target_ip: str = ""
    connection_type: str = "ssh"
    auth_info: dict = {}


class AddCommandRequest(BaseModel):
    command: str
    result: dict = {}


class AddFileTransferRequest(BaseModel):
    transfer_type: str = "upload"
    local_path: str = ""
    remote_path: str = ""
    result: dict = {}


@router.get("", summary="列出会话")
async def list_sessions(status: Optional[str] = None):
    sessions = session_registry.list_sessions(status)
    return {"sessions": sessions, "total": len(sessions)}


@router.get("/target/{target_ip}", summary="按目标 IP 列出会话")
async def list_sessions_by_target(target_ip: str):
    sessions = session_registry.sessions_by_target(target_ip)
    return {"target_ip": target_ip, "sessions": sessions, "total": len(sessions)}


@router.get("/{session_id}", summary="获取会话详情")
async def get_session(session_id: str):
    session = session_registry.get_session(session_id)
    if not session:
        return {"success": False, "error": f"Session not found: {session_id}"}
    return {"success": True, "session": session}


@router.post("", summary="创建会话")
async def create_session(body: CreateSessionRequest):
    registry = session_registry.get_session_registry()
    session_id = registry.create_session(
        target_ip=body.target_ip,
        connection_type=body.connection_type,
        auth_info=body.auth_info or {},
    )
    return {"success": True, "session_id": session_id}


@router.post("/{session_id}/commands", summary="记录/执行命令")
async def add_command(session_id: str, body: AddCommandRequest):
    registry = session_registry.get_session_registry()
    if session_id not in registry.sessions:
        return {"success": False, "error": f"Session not found: {session_id}"}

    # 意有增强：result 为空时通过 terminal_session 池真实执行回填
    result = body.result
    if not result:
        result = await session_registry.execute_via_terminal(session_id, body.command)

    ok = registry.add_command(session_id, body.command, result)
    if not ok:
        return {"success": False, "error": f"Session not found: {session_id}"}
    return {"success": True}


@router.post("/{session_id}/files", summary="记录文件传输")
async def add_file_transfer(session_id: str, body: AddFileTransferRequest):
    registry = session_registry.get_session_registry()
    ok = registry.add_file_transfer(
        session_id,
        body.transfer_type,
        body.local_path,
        body.remote_path,
        body.result or {},
    )
    if not ok:
        return {"success": False, "error": f"Session not found: {session_id}"}
    return {"success": True}


@router.post("/{session_id}/close", summary="关闭会话")
async def close_session(session_id: str):
    registry = session_registry.get_session_registry()
    if session_id not in registry.sessions:
        return {"success": False, "error": f"Session not found: {session_id}"}
    await session_registry.close_terminal(session_id)
    registry.close_session(session_id)
    return {"success": True}
