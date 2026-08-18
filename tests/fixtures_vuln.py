"""vuln-db 离线测试桩：避免真实 NVD/CVE 在线请求。"""
from typing import Dict, List, Optional


class FakeVuln:
    def model_dump(self):
        return {
            "vuln_id": "CVE-2021-44228",
            "title": "Log4Shell RCE",
            "severity": "critical",
            "description": "JNDI lookup RCE in Apache Log4j2",
            "source": "nvd",
        }


class FakeMapping:
    def model_dump(self):
        return {
            "scan_vuln_type": "rce",
            "scan_description": "",
            "matched_vulns": [FakeVuln().model_dump()],
            "match_score": 0.9,
        }


class FakeVectorStore:
    def count(self):
        return 1

    def clear(self):
        pass


class FakeService:
    async def search_by_cve_id(self, cve_id: str) -> Optional[FakeVuln]:
        return FakeVuln() if cve_id == "CVE-2021-44228" else None

    async def search_natural_language(self, query: str, limit: int = 10) -> List[FakeVuln]:
        return [FakeVuln()][:limit]

    async def search_by_scan_result(self, scan_result: Dict, limit: int = 5) -> FakeMapping:
        return FakeMapping()

    async def sync_from_sources(self, keywords, sources=None, limit_per_source=50) -> int:
        return 2

    def get_stats(self) -> Dict:
        return {"vector_count": 1, "adapters": ["nvd", "cve"]}

    def clear(self):
        self._vector_store.clear()

    _vector_store = FakeVectorStore()


def fake_service():
    return FakeService()
