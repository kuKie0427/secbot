"""Phase 6 — Web 托管与前端契约冒烟（@pytest.mark.web，CI 可选跑）。

前置：`make build-web`（web/dist → secbot_web/dist）或 SECBOT_WEB_DIST 指向任意 dist。
dist 缺失时整模块跳过（不失败——纯 Python 贡献者无需 Node）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from router.main import _resolve_web_dist, create_app

pytestmark = pytest.mark.web

_DIST = _resolve_web_dist()
_HAS_DIST = (_DIST / "index.html").is_file()
pytestmark = [
    pytest.mark.web,
    pytest.mark.skipif(not _HAS_DIST, reason=f"web/dist 未构建（{_DIST}）— 先 make build-web"),
]


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


class TestStaticHosting:
    def test_root_serves_index(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert '<div id="root">' in r.text
        assert "<script" in r.text

    def test_spa_deep_link_no_404(self, client):
        # TanStack Router 深链刷新回 index.html
        for path in ("/session/n01J8abc", "/session/xyz/settings"):
            r = client.get(path)
            assert r.status_code == 200, path
            assert '<div id="root">' in r.text

    def test_assets_served(self, client):
        html = client.get("/").text
        import re

        m = re.search(r'src="(/assets/[^"]+\.js)"', html)
        assert m, "index.html 应引用 assets bundle"
        r = client.get(m.group(1))
        assert r.status_code == 200
        assert len(r.content) > 100_000  # ~460KB 主包

    def test_api_takes_precedence_over_spa(self, client):
        # /api 与 /health 不能被 SPA fallback 吞掉
        assert client.get("/api/tools").status_code == 200
        assert client.get("/health").status_code == 200


class TestFrontendApiContract:
    """前端源码实际调用的端点全集（grep web/src 校准）必须 2xx。"""

    def test_system_config(self, client):
        assert client.get("/api/system/config").status_code == 200

    def test_system_providers(self, client):
        assert client.get("/api/system/config/providers").status_code == 200

    def test_system_provider_settings(self, client):
        assert client.get("/api/system/config/provider-settings").status_code == 200

    def test_tools_catalog(self, client):
        assert client.get("/api/tools").status_code == 200

    def test_set_provider_frontend_spelling(self, client):
        # ModelConfig.tsx:40-44 发送 {provider}
        r = client.post("/api/system/config/provider", json={"provider": "deepseek"})
        assert r.status_code == 200

    def test_set_api_key_frontend_spelling(self, client):
        # ModelConfig.tsx:54-58 发送 {provider, api_key}（空 key = 删除，不动真实配置）
        r = client.post("/api/system/config/api-key", json={"provider": "deepseek", "api_key": ""})
        assert r.status_code == 200

    def test_chat_sse_frontend_payload(self, client):
        """useChat.ts:129 精确 payload：connected 首包、done 终止、error 后必跟 done。"""
        payload = {"message": "冒烟", "session_id": "smoke-1", "mode": "agent", "agent": "secbot-cli"}
        events: list[str] = []
        with client.stream("POST", "/api/chat", json=payload) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
        assert events[0] == "connected"
        assert events[-1] == "done"
        if "error" in events:
            assert events[events.index("error") + 1] == "done"
