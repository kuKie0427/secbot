"""爬虫路由 — 对齐 TS crawler.controller.ts（tasks 8 端点 + monitors 7 端点）。

- 任务引擎复用 CrawlerScheduler；监控复用 RealtimeCrawler
- GET /monitors 返回 { monitors, events }，events 为 200 条环形缓冲（对齐 TS monitorEvents）
- execute-async 响应仅 { success: true }（task id 已在路径中，不额外回传）
"""

import asyncio
import hashlib
import re
from collections import deque
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from secbot_agent.crawler.scheduler import TaskStatus
from utils.logger import logger

router = APIRouter(prefix="/api/crawler", tags=["Crawler"])

# 进程级共享调度器与监控事件环形缓冲
_scheduler = None
_monitor_events: deque = deque(maxlen=200)


def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        from secbot_agent.crawler.scheduler import CrawlerScheduler

        _scheduler = CrawlerScheduler()
    return _scheduler


class CreateCrawlTaskRequest(BaseModel):
    url: str
    crawler_type: str = "simple"
    metadata: dict = {}


class ExecuteBatchRequest(BaseModel):
    urls: list = []
    crawler_type: str = "simple"


class AddMonitorRequest(BaseModel):
    url: str
    interval: int = 300
    extractor_config: Optional[dict] = None


def _task_to_dto(task) -> dict:
    """CrawlTask → TS CrawlerTaskDto 形态（result 摊平为 dict，时间 ISO 化）。"""
    result = None
    if task.result is not None:
        result = {
            "url": getattr(task.result, "url", ""),
            "title": getattr(task.result, "title", ""),
            "content": getattr(task.result, "content", ""),
        }
    status = task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
    return {
        "id": task.id,
        "url": task.url,
        "crawler_type": task.crawler_type,
        "status": status,
        "result": result,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "metadata": task.metadata,
    }


def _monitor_to_dto(task_id: str, task) -> dict:
    return {
        "id": task_id,
        "url": task.url,
        "interval": task.interval,
        "extractor_config": task.extractor_config,
        "last_check": task.last_check.isoformat() if task.last_check else None,
        "last_content_hash": task.last_content_hash,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def _get_monitor_crawler():

    rc = _get_scheduler().get_realtime_crawler()
    # 补齐 TS 语义：list + created_at + 事件环形缓冲（RealtimeCrawler 原生没有）
    if not hasattr(rc, "created_at"):
        for t in rc.tasks.values():
            if not hasattr(t, "created_at"):
                t.created_at = datetime.now()
    return rc


@router.post("/tasks", summary="创建爬虫任务")
async def create_task(body: CreateCrawlTaskRequest):
    task_id = _get_scheduler().create_task(body.url, body.crawler_type, body.metadata or {})
    return {"success": True, "task_id": task_id}


@router.get("/tasks", summary="任务列表")
async def list_tasks():
    return {"tasks": [_task_to_dto(t) for t in _get_scheduler().tasks.values()]}


@router.get("/tasks/{task_id}", summary="任务详情")
async def get_task(task_id: str):
    task = _get_scheduler().get_task(task_id)
    if not task:
        return {"success": False, "error": f"Task not found: {task_id}"}
    return {"success": True, "task": _task_to_dto(task)}


@router.get("/tasks/{task_id}/status", summary="任务状态")
async def get_task_status(task_id: str):
    status = _get_scheduler().get_task_status(task_id)
    if status is None:
        return {"success": False, "error": f"Task not found: {task_id}"}
    value = status.value if isinstance(status, TaskStatus) else str(status)
    return {"success": True, "status": value}


@router.post("/tasks/{task_id}/execute", summary="执行任务")
async def execute_task(task_id: str):
    try:
        result = await _get_scheduler().execute_task(task_id)
        return {
            "success": True,
            "result": {
                "url": getattr(result, "url", ""),
                "title": getattr(result, "title", ""),
                "content": getattr(result, "content", ""),
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/tasks/{task_id}/execute-async", summary="异步执行任务")
async def execute_task_async(task_id: str):
    if task_id not in _get_scheduler().tasks:
        return {"success": False, "error": f"Task not found: {task_id}"}
    # 不 await 完成，立即返回（对齐 TS execute-async 语义）
    asyncio.create_task(_run_task_silently(task_id))
    return {"success": True}


async def _run_task_silently(task_id: str) -> None:
    try:
        await _get_scheduler().execute_task(task_id)
    except Exception as e:
        logger.warning(f"crawler async task {task_id} failed: {e}")


@router.post("/tasks/{task_id}/cancel", summary="取消任务")
async def cancel_task(task_id: str):
    ok = _get_scheduler().cancel_task(task_id)
    if not ok:
        return {"success": False, "error": f"Task not found: {task_id}"}
    return {"success": True}


@router.post("/batch", summary="批量执行")
async def execute_batch(body: ExecuteBatchRequest):
    results = await _get_scheduler().execute_batch(body.urls or [], body.crawler_type)
    out = {}
    for task_id, r in results.items():
        out[task_id] = {
            "url": getattr(r, "url", ""),
            "title": getattr(r, "title", ""),
            "content": getattr(r, "content", ""),
        }
    return {"success": True, "results": out}


# ---------------------------------------------------------------------------
# 监控（monitors）— 对齐 TS CrawlerService 的 monitor 语义
# ---------------------------------------------------------------------------


@router.post("/monitors", summary="添加监控")
async def add_monitor(body: AddMonitorRequest):
    rc = _get_monitor_crawler()
    monitor_id = f"{body.url.replace('/', '~')}_{body.interval}"
    rc.tasks[monitor_id] = _new_monitor_task(body.url, body.interval, body.extractor_config)
    return {"success": True, "monitor_id": monitor_id}


def _new_monitor_task(url: str, interval: int, extractor_config: Optional[dict]):
    from secbot_agent.crawler.realtime import MonitorTask

    return MonitorTask(
        url=url,
        interval=interval,
        extractor_config=extractor_config,
    )


@router.get("/monitors", summary="监控列表与事件")
async def list_monitors():
    rc = _get_monitor_crawler()
    return {
        "monitors": [_monitor_to_dto(tid, t) for tid, t in rc.tasks.items()],
        "events": list(_monitor_events),
    }


@router.post("/monitors/{monitor_id}/check", summary="立即检查")
async def check_monitor(monitor_id: str):
    rc = _get_monitor_crawler()
    if monitor_id not in rc.tasks:
        return {"success": False, "error": f"Monitor not found: {monitor_id}"}
    changed = await _check_monitor_task(rc, monitor_id, rc.tasks[monitor_id])
    return {"success": True, "changed": changed}


@router.post("/monitors/check-all", summary="检查全部")
async def check_all_monitors():
    rc = _get_monitor_crawler()
    changed_map = {}
    for monitor_id, task in list(rc.tasks.items()):
        changed_map[monitor_id] = await _check_monitor_task(rc, monitor_id, task)
    return {"success": True, "changed": changed_map}


@router.post("/monitors/start", summary="启动监控循环")
async def start_monitors():
    rc = _get_monitor_crawler()
    await rc.start()
    return {"success": True}


@router.post("/monitors/stop", summary="停止监控循环")
async def stop_monitors():
    rc = _get_monitor_crawler()
    await rc.stop()
    return {"success": True}


@router.post("/monitors/{monitor_id}/remove", summary="移除监控")
async def remove_monitor(monitor_id: str):
    rc = _get_monitor_crawler()
    if monitor_id not in rc.tasks:
        return {"success": False, "error": f"Monitor not found: {monitor_id}"}
    rc.remove_monitor(monitor_id)
    return {"success": True}


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html_to_text(html: str) -> str:
    """对齐 TS cleanHtmlToText：去 script/style、去标签、压空白。"""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


async def _fetch_snapshot(url: str) -> str:
    """对齐 TS fetchSnapshot：15s 超时，失败返回空串。"""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15.0, headers={"User-Agent": "secbot-py/2.0.0"}
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return ""
            return _clean_html_to_text(resp.text)[:20000]
    except Exception:
        return ""


async def _check_monitor_task(rc, monitor_id: str, task) -> bool:
    """对齐 TS checkMonitorTask：哈希对比 + 变化事件进环形缓冲。"""
    try:
        snapshot = await _fetch_snapshot(task.url)
        content_hash = hashlib.md5(snapshot.encode()).hexdigest()
        changed = False

        if task.last_content_hash and task.last_content_hash != content_hash:
            changed = True
            event = {
                "task_id": monitor_id,
                "url": task.url,
                "changed": True,
                "timestamp": datetime.now().isoformat(),
            }

            if task.extractor_config:
                from secbot_agent.crawler import CrawlerTool

                extracted = await CrawlerTool().execute(
                    url=task.url,
                    extract_info=True,
                    extraction_schema=(task.extractor_config or {}).get("schema", {}),
                )
                event["extracted_info"] = (
                    extracted.result if extracted.success else {"error": extracted.error}
                )

            _monitor_events.append(event)

        task.last_content_hash = content_hash
        task.last_check = datetime.now()
        return changed
    except Exception:
        task.last_check = datetime.now()
        return False
