"""漏洞库路由 — 对齐 TS vuln-db.controller.ts 的 6 个端点。

- 服务复用 secbot_agent.core.vuln_db.vuln_db_service.VulnDbService
- clear 经私有 _vector_store 委托 VulnVectorStore.clear()（service 无公开 clear，与 TS 相同的委托路径）
- sync/clear 无确认参数（对齐 TS）
"""

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from utils.logger import logger

router = APIRouter(prefix="/api/vuln-db", tags=["VulnDB"])

_service = None


def _get_service():
    global _service
    if _service is None:
        from secbot_agent.core.vuln_db.vuln_db_service import VulnDbService

        _service = VulnDbService()
    return _service


class SearchNaturalLanguageRequest(BaseModel):
    query: str
    limit: int = 10


class SearchByScanResultRequest(BaseModel):
    scan_result: dict
    limit: int = 5


class SyncFromSourcesRequest(BaseModel):
    keywords: List[str]
    sources: Optional[List[str]] = None
    limit_per_source: int = 50


@router.get("/cve/{cve_id}", summary="按 CVE 编号精确查询")
async def search_by_cve_id(cve_id: str):
    try:
        vuln = await _get_service().search_by_cve_id(cve_id)
    except Exception as e:
        logger.warning(f"vuln-db cve lookup failed for {cve_id}: {e}")
        vuln = None
    if not vuln:
        return {"success": False, "message": f"Vulnerability not found for {cve_id}"}
    payload = vuln.model_dump() if hasattr(vuln, "model_dump") else dict(vuln)
    return {"success": True, "vulnerability": payload}


@router.post("/search", summary="自然语言检索")
async def search_natural_language(body: SearchNaturalLanguageRequest):
    try:
        vulns = await _get_service().search_natural_language(body.query, body.limit)
    except Exception as e:
        logger.warning(f"vuln-db search failed: {e}")
        vulns = []
    out = []
    for v in vulns:
        out.append(v.model_dump() if hasattr(v, "model_dump") else dict(v))
    return {"vulnerabilities": out}


@router.post("/scan-match", summary="按扫描结果匹配")
async def search_by_scan_result(body: SearchByScanResultRequest):
    try:
        mapping = await _get_service().search_by_scan_result(body.scan_result, body.limit)
    except Exception as e:
        logger.warning(f"vuln-db scan-match failed: {e}")
        return {"matched": [], "message": str(e)}
    if hasattr(mapping, "model_dump"):
        return mapping.model_dump()
    return dict(mapping)


@router.post("/sync", summary="从数据源同步")
async def sync_from_sources(body: SyncFromSourcesRequest):
    count = await _get_service().sync_from_sources(
        body.keywords, body.sources, body.limit_per_source
    )
    return {"success": True, "indexed_count": count}


@router.post("/clear", summary="清空向量库")
async def clear_vectors():
    svc = _get_service()
    svc.clear()
    return {"success": True}


@router.get("/stats", summary="漏洞库统计")
async def stats():
    return _get_service().get_stats()
