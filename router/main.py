"""
Hackbot FastAPI 服务入口 — 组装所有路由、CORS、uvicorn 入口
"""

import os
import time
import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from router.chat import router as chat_router
from router.agents import router as agents_router
from router.sessions import router as sessions_router
from router.system import router as system_router
from router.defense import router as defense_router
from router.network import router as network_router
from router.database import router as database_router
from router.tools import router as tools_router
from router.memory import router as memory_router
from router.skills import router as skills_router
from router.crawler import router as crawler_router
from router.vuln_db import router as vuln_db_router
from router.dependencies import get_db_manager
from utils.error_mapper import map_exception_to_client
from utils.logger import logger
from utils.log_context import log_context


def create_app() -> FastAPI:
    """FastAPI 应用工厂"""

    application = FastAPI(
        title="Hackbot API",
        description="Hackbot AI 安全测试机器人 — REST + SSE 接口",
        version="2.0.0b1",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()
        with log_context(request_id=request_id, event="http_request", attempt=1):
            req_logger = logger.bind(event="stage_start")
            req_logger.info(f"{request.method} {request.url.path} started")
            try:
                response = await call_next(request)
                duration_ms = int((time.perf_counter() - start) * 1000)
                logger.bind(
                    event="stage_end", duration_ms=duration_ms
                ).info(f"{request.method} {request.url.path} -> {response.status_code}")
                response.headers["X-Request-Id"] = request_id
                return response
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                logger.bind(
                    event="system_error", duration_ms=duration_ms
                ).exception(f"{request.method} {request.url.path} unhandled exception")
                mapped = map_exception_to_client(exc)
                return JSONResponse(
                    status_code=mapped.status_code,
                    content={
                        "detail": mapped.message,
                        "code": mapped.code.value,
                        "request_id": request_id,
                    },
                    headers={"X-Request-Id": request_id},
                )

    # ------------------------------------------------------------------
    # 注册路由
    # ------------------------------------------------------------------
    application.include_router(chat_router)
    application.include_router(agents_router)
    application.include_router(sessions_router)
    application.include_router(system_router)
    application.include_router(defense_router)
    application.include_router(network_router)
    application.include_router(database_router)
    application.include_router(tools_router)
    application.include_router(memory_router)
    application.include_router(skills_router)
    application.include_router(crawler_router)
    application.include_router(vuln_db_router)

    # ------------------------------------------------------------------
    # 启动时初始化数据库（确保 secbot.db 与表在首次请求前就存在）
    # ------------------------------------------------------------------
    @application.on_event("startup")
    def _init_db_on_startup():
        get_db_manager()

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------
    @application.get("/health", tags=["Health"])
    async def health():
        from datetime import datetime

        return {"status": "ok", "timestamp": datetime.now().isoformat()}

    _mount_web_dist(application)

    return application


def _resolve_web_dist() -> Path:
    """dist 查找顺序：SECBOT_WEB_DIST 覆盖 → 源码仓 web/dist → wheel 内 secbot_web/dist。"""
    override = os.environ.get("SECBOT_WEB_DIST")
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [repo_root / "web" / "dist", repo_root / "secbot_web" / "dist"]
    try:
        import secbot_web  # wheel 安装时 dist 随包数据分发

        candidates.append(Path(secbot_web.__file__).parent / "dist")
    except ImportError:
        pass
    for cand in candidates:
        if (cand / "index.html").is_file():
            return cand
    return candidates[0]


def _mount_web_dist(application: FastAPI) -> None:
    """托管 web/dist 静态资源（SPA fallback 到 index.html；对齐 TS Nest ServeStatic）。

    - 路径可用 SECBOT_WEB_DIST 覆盖
    - dist 不存在时跳过并提示（开发模式由 vite dev server 代理 /api）
    """
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = _resolve_web_dist()
    if not (dist / "index.html").is_file():
        logger.info(f"web/dist 不存在（{dist}），跳过静态托管 — 前端请用 `make dev-web`（vite 代理 /api）或先 `make build-web`")
        return

    index_html = dist / "index.html"
    assets = dist / "assets"

    # SPA fallback：非 /api、非 /health、非静态文件的未知路径返回 index.html
    # （TanStack Router 深链如 /session/xxx 刷新不 404）
    @application.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_html)

    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="web-assets")
    logger.info(f"已托管 Web UI: {dist}")


# 全局 app 实例（供 uvicorn 直接引用: router.main:app）
app = create_app()


def _purge_pycache(project_root: Path) -> None:
    """启动前清理 __pycache__，减少旧字节码干扰。"""
    for p in project_root.rglob("__pycache__"):
        try:
            shutil.rmtree(p, ignore_errors=True)
        except Exception:
            # 不影响启动，仅忽略个别目录权限问题
            pass


def run_server():
    """
    脚本入口 — 可通过 `secbot server` 或 `python -m router.main` 启动。

    环境变量（可选）:
    - SECBOT_SERVER_HOST / SECBOT_SERVER_PORT: 覆盖监听地址与端口
    - SECBOT_SERVER_RELOAD=true|false: 是否启用热重载（默认关闭）
    """
    import os
    import socket
    import sys
    import uvicorn

    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent.parent
    _purge_pycache(root)

    host = os.environ.get("SECBOT_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SECBOT_SERVER_PORT", "8000"))
    reload_raw = os.environ.get("SECBOT_SERVER_RELOAD", "").lower()
    reload = reload_raw in ("1", "true", "yes")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print(
                f"端口 {port} 已被占用。请先停止占用 {port} 的进程后再启动。",
                file=sys.stderr,
            )
            print(f"  Windows: netstat -ano | findstr :{port} 查看 PID，再用 taskkill /PID <pid> /F 结束。", file=sys.stderr)
            sys.exit(1)
    uvicorn.run(
        "router.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    run_server()
