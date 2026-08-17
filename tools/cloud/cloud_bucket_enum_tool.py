"""cloud_bucket_enum — 多云存储桶枚举（AWS S3 / Azure Blob / GCP Storage / 阿里云 OSS）。

镜像 TS server/src/modules/tools/cloud/cloud-bucket-enum.tool.ts（与已有 s3_bucket 仅 AWS 的实现并存）。
"""
import asyncio
from typing import Any, Dict, List, Optional

import httpx

from tools.base import BaseTool, ToolResult

PROVIDER_URLS = {
    "aws": lambda n: f"https://{n}.s3.amazonaws.com/",
    "azure": lambda n: f"https://{n}.blob.core.windows.net/?comp=list&restype=container",
    "gcp": lambda n: f"https://storage.googleapis.com/{n}/",
    "aliyun": lambda n: f"https://{n}.oss-cn-hangzhou.aliyuncs.com/",
}

DEFAULT_SUFFIXES = [
    "", "-backup", "-bak", "-dev", "-staging", "-prod", "-assets", "-static",
    "-uploads", "-data", "-logs", "-private", "-public", "-internal", "-test",
    "-config", "-db", "-files", "-www", "-api",
]

LISTABLE_MARKS = ("<ListBucketResult", "<Contents>", "<EnumerationResults", "<Blob>")


class CloudBucketEnumTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="cloud_bucket_enum",
            description="多云存储桶枚举 — 支持 AWS S3 / Azure Blob / GCP Storage / 阿里云 OSS",
        )

    async def execute(
        self,
        keyword: str = "",
        providers: Optional[List[str]] = None,
        suffixes: Optional[List[str]] = None,
        timeout_ms: int = 5000,
        max: int = 50,
        **kwargs,
    ) -> ToolResult:
        keyword = (keyword or "").strip()
        if not keyword:
            return ToolResult(success=False, result=None, error="缺少必要参数: keyword")

        provider_list = providers or ["aws", "azure", "gcp", "aliyun"]
        suffix_list = [str(s) for s in suffixes] if suffixes else DEFAULT_SUFFIXES
        timeout_s = min(int(timeout_ms or 5000), 15000) / 1000.0
        max_per_provider = min(int(max or 50), 200)

        lower = keyword.lower()
        names = list(dict.fromkeys(f"{lower}{s}" for s in suffix_list))[:max_per_provider]

        all_results: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(
            timeout=timeout_s, follow_redirects=False, headers={"User-Agent": "secbot/1.0"}
        ) as client:
            for provider in provider_list:
                url_fn = PROVIDER_URLS.get(provider)
                if not url_fn:
                    continue
                sem = asyncio.Semaphore(10)

                async def check(name: str) -> Optional[Dict[str, Any]]:
                    async with sem:
                        return await _check_bucket(client, provider, name, url_fn(name))

                checks = await asyncio.gather(*(check(n) for n in names))
                all_results.extend(r for r in checks if r and r.get("exists"))

        return ToolResult(
            success=True,
            result={
                "keyword": keyword,
                "providers": provider_list,
                "names_tested": len(names) * len(provider_list),
                "found": len(all_results),
                "accessible": sum(1 for r in all_results if r.get("list_accessible")),
                "details": all_results[:100],
            },
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "关键字（组织/项目名）"},
                    "providers": {"type": "array", "items": {"type": "string", "enum": list(PROVIDER_URLS.keys())}},
                    "suffixes": {"type": "array", "items": {"type": "string"}, "description": "后缀列表（默认 20 个常见后缀）"},
                    "timeout_ms": {"type": "integer", "description": "单请求超时毫秒（默认 5000）"},
                    "max": {"type": "integer", "description": "每 provider 最大尝试名数（默认 50，上限 200）"},
                },
                "required": ["keyword"],
            },
        }


async def _check_bucket(client: httpx.AsyncClient, provider: str, name: str, url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "provider": provider, "bucket": name, "url": url,
        "exists": False, "list_accessible": False,
    }
    try:
        resp = await client.get(url)
        result["status"] = resp.status_code
        if resp.status_code == 200:
            result["exists"] = True
            body = resp.text
            if any(mark in body for mark in LISTABLE_MARKS):
                result["list_accessible"] = True
                result["risk"] = "high"
                result["preview"] = body[:300]
        elif resp.status_code in (301, 302, 307, 403):
            result["exists"] = True
    except Exception:
        pass
    return result
