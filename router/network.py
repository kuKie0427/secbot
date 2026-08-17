"""
网络路由 — 内网发现、目标管理、授权管理、远程控制
对齐 TS network.controller.ts：新增 authorized-targets / connect / execute /
upload / download / disconnect / control/sessions 七个端点。
请求字段为 camelCase（对齐 TS DTO），响应为 snake_case。
"""


from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from router.dependencies import get_main_controller
from router.schemas import (
    DiscoverRequest,
    DiscoverResponse,
    HostInfo,
    TargetListResponse,
    AuthorizeRequest,
    AuthorizeResponse,
    AuthorizationInfo,
    AuthorizationListResponse,
    RevokeResponse,
)

router = APIRouter(prefix="/api/network", tags=["Network"])


class ConnectTargetRequest(BaseModel):
    target_ip: str = ""
    targetIp: str = ""  # TS DTO 字段（camelCase）
    connection_type: Optional[str] = None
    connectionType: Optional[str] = None

    def resolved_ip(self) -> str:
        return self.targetIp or self.target_ip

    def resolved_connection_type(self) -> Optional[str]:
        return self.connectionType or self.connection_type


class ExecuteTargetRequest(ConnectTargetRequest):
    command: str = ""


class UploadFileRequest(ConnectTargetRequest):
    local_path: str = ""
    localPath: str = ""
    remote_path: str = ""
    remotePath: str = ""

    def resolved_local(self) -> str:
        return self.localPath or self.local_path

    def resolved_remote(self) -> str:
        return self.remotePath or self.remote_path


class DownloadFileRequest(UploadFileRequest):
    pass


@router.post("/discover", response_model=DiscoverResponse, summary="内网发现")
async def discover(request: DiscoverRequest):
    """发现内网中所有在线主机。"""
    try:
        mc = get_main_controller()
        hosts = await mc.discover_network(request.network)

        host_list = []
        for h in (hosts or []):
            host_list.append(
                HostInfo(
                    ip=h["ip"],
                    hostname=h.get("hostname", "Unknown"),
                    mac_address=h.get("mac_address", "Unknown"),
                    open_ports=h.get("open_ports", []),
                    authorized=h.get("authorized", False),
                )
            )

        return DiscoverResponse(success=True, hosts=host_list)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"内网发现错误: {e}")


@router.get("/targets", response_model=TargetListResponse, summary="列出目标")
async def list_targets(
    authorized_only: bool = Query(False, description="仅显示已授权的目标"),
):
    """列出所有已发现的目标主机。"""
    try:
        mc = get_main_controller()
        targets = mc.get_targets(authorized_only=authorized_only)

        target_list = []
        for t in (targets or []):
            target_list.append(
                HostInfo(
                    ip=t["ip"],
                    hostname=t.get("hostname", "Unknown"),
                    mac_address=t.get("mac_address", "Unknown"),
                    open_ports=t.get("open_ports", []),
                    authorized=t.get("authorized", False),
                )
            )

        return TargetListResponse(targets=target_list)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取目标列表失败: {e}")


@router.post("/authorize", response_model=AuthorizeResponse, summary="授权目标")
async def authorize(request: AuthorizeRequest):
    """授权目标主机。"""
    try:
        mc = get_main_controller()

        credentials = {"username": request.username}
        if request.password:
            credentials["password"] = request.password
        if request.key_file:
            credentials["key_file"] = request.key_file

        success = mc.authorize_target(
            target_ip=request.target_ip,
            auth_type=request.auth_type,
            credentials=credentials,
            description=request.description,
        )

        if success:
            return AuthorizeResponse(success=True, message=f"已授权目标: {request.target_ip}")
        else:
            return AuthorizeResponse(success=False, message="授权失败")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"授权错误: {e}")


@router.get("/authorizations", response_model=AuthorizationListResponse, summary="列出所有授权")
async def list_authorizations():
    """列出所有活跃的授权记录。"""
    try:
        mc = get_main_controller()
        auths = mc.auth_manager.list_authorizations(status="active")

        auth_list = []
        for a in (auths or []):
            username = a.get("credentials", {}).get("username", "N/A")
            created = a.get("created_at", "N/A")
            if created and len(created) > 19:
                created = created[:19]

            auth_list.append(
                AuthorizationInfo(
                    target_ip=a["target_ip"],
                    auth_type=a.get("auth_type", "N/A"),
                    username=username,
                    created_at=created or "N/A",
                    description=a.get("description", "")[:50] or "N/A",
                )
            )

        return AuthorizationListResponse(authorizations=auth_list)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取授权列表失败: {e}")


@router.delete("/authorize/{target_ip}", response_model=RevokeResponse, summary="撤销授权")
async def revoke_authorization(target_ip: str):
    """撤销指定目标的授权。"""
    try:
        mc = get_main_controller()
        success = mc.auth_manager.revoke_authorization(target_ip)

        if success:
            return RevokeResponse(success=True, message=f"已撤销授权: {target_ip}")
        else:
            return RevokeResponse(success=False, message=f"授权不存在或撤销失败: {target_ip}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"撤销授权错误: {e}")


# ---------------------------------------------------------------------------
# 远程控制（对齐 TS network.controller.ts）
# ---------------------------------------------------------------------------


@router.get("/authorized-targets", summary="已授权目标列表")
async def get_authorized_targets():
    """获取所有已授权目标（含授权信息）。"""
    mc = get_main_controller()
    return {"targets": mc.get_authorized_targets()}


@router.post("/connect", summary="连接目标")
async def connect_target(body: ConnectTargetRequest):
    """连接到已授权目标；成功返回 session_id。"""
    target_ip = body.resolved_ip()
    connection_type = body.resolved_connection_type()
    if not target_ip:
        return {"success": False, "error": "Missing parameter: targetIp"}

    mc = get_main_controller()
    if not mc.auth_manager.is_authorized(target_ip):
        return {"success": False, "error": "Target is not authorized"}

    session_id = mc.connect_target(target_ip, connection_type)
    if not session_id:
        return {"success": False, "error": "Connection failed"}
    resolved = connection_type or "ssh"
    return {"success": True, "session_id": session_id, "connection_type": resolved}


@router.post("/execute", summary="在目标上执行命令")
async def execute_on_target(body: ExecuteTargetRequest):
    target_ip = body.resolved_ip()
    if not target_ip or not body.command:
        return {"success": False, "error": "Missing parameter: targetIp / command"}

    mc = get_main_controller()
    if not mc.auth_manager.is_authorized(target_ip):
        return {"success": False, "error": "Target is not authorized"}

    result = mc.execute_on_target(target_ip, body.command)
    if isinstance(result, dict) and "connection_type" not in result:
        result.setdefault("connection_type", body.resolved_connection_type() or "ssh")
    return result


@router.post("/upload", summary="上传文件到目标")
async def upload_to_target(body: UploadFileRequest):
    target_ip = body.resolved_ip()
    local_path = body.resolved_local()
    remote_path = body.resolved_remote()
    if not target_ip or not local_path or not remote_path:
        return {"success": False, "error": "Missing parameter: targetIp / localPath / remotePath"}

    mc = get_main_controller()
    if not mc.auth_manager.is_authorized(target_ip):
        return {"success": False, "error": "Target is not authorized"}

    return mc.upload_to_target(target_ip, local_path, remote_path)


@router.post("/download", summary="从目标下载文件")
async def download_from_target(body: DownloadFileRequest):
    target_ip = body.resolved_ip()
    local_path = body.resolved_local()
    remote_path = body.resolved_remote()
    if not target_ip or not local_path or not remote_path:
        return {"success": False, "error": "Missing parameter: targetIp / remotePath / localPath"}

    mc = get_main_controller()
    if not mc.auth_manager.is_authorized(target_ip):
        return {"success": False, "error": "Target is not authorized"}

    return mc.download_from_target(target_ip, remote_path, local_path)


@router.post("/disconnect", summary="断开目标连接")
async def disconnect_target(body: ConnectTargetRequest):
    target_ip = body.resolved_ip()
    connection_type = body.resolved_connection_type() or "ssh"
    if not target_ip:
        return {"success": False, "error": "Missing parameter: targetIp"}

    mc = get_main_controller()
    mc.disconnect_target(target_ip)
    return {"success": True, "message": f"Disconnected {target_ip} ({connection_type})"}


@router.get("/control/sessions", summary="活动控制会话")
async def list_control_sessions():
    mc = get_main_controller()
    return {"active_sessions": mc.remote_controller.get_active_sessions()}
