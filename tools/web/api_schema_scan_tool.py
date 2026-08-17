"""api_schema_scan — 探测 OpenAPI/Swagger/GraphQL 端点。

镜像 TS server/src/modules/tools/security/api-schema-scan.tool.ts
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx

from tools.base import BaseTool, ToolResult

COMMON_PATHS = [
    "/swagger.json",
    "/swagger/v1/swagger.json",
    "/api-docs",
    "/openapi.json",
    "/openapi.yaml",
    "/v2/api-docs",
    "/v3/api-docs",
    "/docs",
    "/redoc",
    "/swagger-ui.html",
    "/swagger-ui/",
    "/graphql",
    "/graphiql",
    "/altair",
    "/playground",
    "/api/graphql",
    "/.well-known/openapi.json",
    "/api/schema",
    "/api/v1/schema",
    "/api/docs",
]

GRAPHQL_INTROSPECTION = json.dumps({
    "query": "{ __schema { types { name } queryType { name } mutationType { name } } }"
})


class ApiSchemaScanTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="api_schema_scan",
            description="API Schema 发现 — 探测 OpenAPI/Swagger/GraphQL 端点",
        )

    async def execute(
        self,
        target: str = "",
        timeout: int = 10,
        paths: Optional[List[str]] = None,
        **kwargs,
    ) -> ToolResult:
        target = (target or "").strip()
        if not target:
            return ToolResult(success=False, result=None, error="缺少必要参数: target (base URL)")

        base_url = target.rstrip("/")
        timeout_s = min(int(timeout or 10), 30)
        all_paths = COMMON_PATHS + [str(p) for p in (paths or [])]

        async with httpx.AsyncClient(
            timeout=timeout_s, follow_redirects=True, headers={"User-Agent": "secbot/1.0"}
        ) as client:
            found: List[Dict[str, Any]] = []
            probes = await asyncio.gather(
                *(_probe(client, base_url + p, timeout_s) for p in all_paths),
                return_exceptions=True,
            )
            for p, r in zip(all_paths, probes):
                if isinstance(r, Exception) or not r:
                    continue
                found.append({"path": p, "url": base_url + p, **r})

            # 对发现的 GraphQL 端点尝试 introspection
            for ep in found:
                if ep.get("type") == "graphql":
                    intro = await _graphql_introspect(client, ep["url"], timeout_s)
                    if intro:
                        ep["introspection"] = intro

        return ToolResult(
            success=True,
            result={
                "target": base_url,
                "paths_checked": len(all_paths),
                "endpoints_found": len(found),
                "endpoints": found,
            },
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标 base URL"},
                    "timeout": {"type": "integer", "description": "请求超时秒数（默认 10）"},
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "附加路径"},
                },
                "required": ["target"],
            },
        }


async def _probe(client: httpx.AsyncClient, url: str, timeout_s: int) -> Optional[Dict[str, Any]]:
    try:
        resp = await client.get(url)
    except Exception:
        return None
    if resp.status_code >= 400:
        return None

    ct = resp.headers.get("content-type", "")
    body = resp.text
    snippet = body[:500]

    if "json" in ct or body.startswith("{"):
        try:
            data = json.loads(body[:50000])
            if data.get("openapi") or data.get("swagger"):
                return {
                    "type": "openapi",
                    "version": data.get("openapi") or data.get("swagger"),
                    "title": (data.get("info") or {}).get("title"),
                    "paths_count": len(data.get("paths") or {}) or None,
                }
            if (data.get("data") or {}).get("__schema") or data.get("__schema"):
                return {"type": "graphql", "note": "GraphQL introspection 可用"}
        except json.JSONDecodeError:
            pass

    if resp.status_code == 200:
        import re
        if re.search(r"graphql|graphiql|playground", url, re.I):
            return {"type": "graphql", "content_type": ct}
        if re.search(r"swagger|redoc|api-docs", url, re.I):
            return {"type": "swagger_ui", "content_type": ct, "snippet": snippet}
    return None


async def _graphql_introspect(client: httpx.AsyncClient, url: str, timeout_s: int) -> Optional[Dict[str, Any]]:
    try:
        resp = await client.post(
            url,
            content=GRAPHQL_INTROSPECTION,
            headers={"Content-Type": "application/json", "User-Agent": "secbot/1.0"},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        schema = (data.get("data") or {}).get("__schema")
        if not schema:
            return None
        return {
            "query_type": (schema.get("queryType") or {}).get("name"),
            "mutation_type": (schema.get("mutationType") or {}).get("name"),
            "types_count": len(schema.get("types") or []),
            "types": [t.get("name") for t in (schema.get("types") or [])][:30],
        }
    except Exception:
        return None
