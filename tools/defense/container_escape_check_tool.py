"""container_escape_check — 检查 Docker/K8s 容器中的逃逸向量（纯文件系统读）。

镜像 TS server/src/modules/tools/defense/container-escape-check.tool.ts
"""
import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List

from tools.base import BaseTool, ToolResult

DANGEROUS_CAPS = ["cap_sys_admin", "cap_sys_ptrace", "cap_net_admin", "cap_dac_override"]
SENSITIVE_PATHS = ["/proc/sysrq-trigger", "/proc/kcore", "/sys/kernel", "/dev/mem"]
K8S_SA_TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"


class ContainerEscapeCheckTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="container_escape_check",
            description="容器逃逸检测 — 检查 Docker/K8s 容器中的逃逸向量",
        )

    async def execute(self, **kwargs) -> ToolResult:
        findings: List[Dict[str, str]] = []
        loop = asyncio.get_event_loop()

        in_container = await loop.run_in_executor(None, _is_in_container)
        if not in_container:
            return ToolResult(success=True, result={"in_container": False, "note": "当前环境不在容器内"})

        if await loop.run_in_executor(None, _check_privileged):
            findings.append({
                "vector": "privileged_mode", "severity": "critical",
                "detail": "容器以 --privileged 运行，可直接挂载宿主机文件系统逃逸",
            })

        if Path("/var/run/docker.sock").exists():
            findings.append({
                "vector": "docker_socket", "severity": "critical",
                "detail": "Docker socket 已挂载，可通过 API 创建特权容器逃逸",
            })

        caps = await loop.run_in_executor(None, _get_capabilities)
        found_caps = [c for c in caps if c.lower() in DANGEROUS_CAPS]
        if found_caps:
            findings.append({
                "vector": "dangerous_capabilities", "severity": "high",
                "detail": f"危险 capabilities: {', '.join(found_caps)}",
            })

        for p in SENSITIVE_PATHS:
            if Path(p).exists():
                findings.append({
                    "vector": "sensitive_mount", "severity": "high",
                    "detail": f"敏感路径可访问: {p}",
                })
                break

        if await loop.run_in_executor(None, _check_cgroup_writable):
            findings.append({
                "vector": "writable_cgroup", "severity": "high",
                "detail": "cgroup 可写，可能通过 release_agent 逃逸",
            })

        if Path(K8S_SA_TOKEN).exists():
            findings.append({
                "vector": "k8s_service_account", "severity": "medium",
                "detail": "K8s ServiceAccount token 存在，检查 RBAC 权限",
            })

        if await loop.run_in_executor(None, _check_host_pid_ns):
            findings.append({
                "vector": "host_pid_namespace", "severity": "high",
                "detail": "共享宿主机 PID namespace，可访问宿主机进程",
            })

        risk_level = (
            "critical" if any(f["severity"] == "critical" for f in findings)
            else "high" if any(f["severity"] == "high" for f in findings)
            else "medium" if any(f["severity"] == "medium" for f in findings)
            else "low"
        )
        return ToolResult(
            success=True,
            result={
                "in_container": True,
                "findings_count": len(findings),
                "risk_level": risk_level,
                "findings": findings,
            },
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object", "properties": {}},
        }


def _is_in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text()
        return "docker" in cgroup or "containerd" in cgroup or "kubepods" in cgroup
    except OSError:
        return False


def _check_privileged() -> bool:
    caps = _get_capabilities()
    # 全能力集（38+ cap）通常意味着 privileged
    return len(caps) > 35


def _get_capabilities() -> List[str]:
    try:
        status = Path("/proc/self/status").read_text()
        for line in status.splitlines():
            if line.startswith("CapEff:"):
                cap_hex = int(line.split(":")[1].strip(), 16)
                return [f"cap_{i}" for i in range(cap_hex.bit_length()) if cap_hex & (1 << i)]
    except (OSError, ValueError):
        pass
    return []


def _check_cgroup_writable() -> bool:
    try:
        cgroup = Path("/sys/fs/cgroup")
        if not cgroup.exists():
            return False
        probe = cgroup / ".secbot-write-probe"
        probe.write_text("")
        probe.unlink()
        return True
    except OSError:
        return False


def _check_host_pid_ns() -> bool:
    try:
        # PID namespace inode 比较：init 与自身不同则共享宿主 PID ns
        self_ns = os.stat("/proc/self/ns/pid").st_ino
        init_ns = os.stat("/proc/1/ns/pid").st_ino
        return self_ns != init_ns
    except OSError:
        return False
