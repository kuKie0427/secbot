"""Phase 4 REST 对齐测试：sessions / crawler / vuln-db / network 控制 / memory 补全。

用 httpx AsyncClient + ASGITransport 直连 app，不启动真实服务器；
网络相关（vuln-db 在线源、SSH、爬虫外网请求）全部离线化或 monkeypatch。
"""
import httpx
import pytest

from router.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# T1 sessions
# ---------------------------------------------------------------------------


class TestSessionsEndpoints:
    async def test_create_list_get_close(self, client):
        r = await client.post(
            "/api/sessions", json={"target_ip": "10.10.0.5", "connection_type": "ssh"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        session_id = body["session_id"]
        assert "10.10.0.5" in session_id and "ssh" in session_id

        r = await client.get("/api/sessions")
        assert r.json()["total"] >= 1
        assert any(s["session_id"] == session_id for s in r.json()["sessions"])

        r = await client.get(f"/api/sessions/{session_id}")
        assert r.json()["success"] is True
        assert r.json()["session"]["target_ip"] == "10.10.0.5"
        assert r.json()["session"]["status"] == "active"

        r = await client.post(f"/api/sessions/{session_id}/close")
        assert r.json()["success"] is True

        r = await client.get("/api/sessions", params={"status": "closed"})
        assert any(s["session_id"] == session_id for s in r.json()["sessions"])
        # target 索引只列 active
        r = await client.get("/api/sessions/target/10.10.0.5")
        assert r.json()["total"] == 0

    async def test_get_not_found(self, client):
        r = await client.get("/api/sessions/no_such_session")
        assert r.json()["success"] is False
        assert "not found" in r.json()["error"].lower()

    async def test_commands_with_client_result_passthrough(self, client):
        r = await client.post(
            "/api/sessions", json={"target_ip": "10.10.0.9", "connection_type": "ssh"}
        )
        session_id = r.json()["session_id"]

        r = await client.post(
            f"/api/sessions/{session_id}/commands",
            json={"command": "whoami", "result": {"output": "root"}},
        )
        assert r.json()["success"] is True

        r = await client.get(f"/api/sessions/{session_id}")
        detail = r.json()["session"]
        assert detail["commands_executed"][0]["command"] == "whoami"
        assert detail["commands_executed"][0]["result"]["output"] == "root"

    async def test_command_real_execution_via_terminal(self, client):
        """Python 有意增强：result 缺省时桥接 terminal_session 真实执行。"""
        r = await client.post(
            "/api/sessions", json={"target_ip": "", "connection_type": "chat"}
        )
        session_id = r.json()["session_id"]

        r = await client.post(
            f"/api/sessions/{session_id}/commands",
            json={"command": "echo phase4-terminal-bridge"},
        )
        assert r.json()["success"] is True

        r = await client.get(f"/api/sessions/{session_id}")
        record = r.json()["session"]["commands_executed"][0]
        assert record["result"]["success"] is True
        assert "phase4-terminal-bridge" in record["result"]["output"]

        await client.post(f"/api/sessions/{session_id}/close")

    async def test_files_and_not_found(self, client):
        r = await client.post(
            "/api/sessions", json={"target_ip": "10.10.0.7", "connection_type": "sftp"}
        )
        session_id = r.json()["session_id"]

        r = await client.post(
            f"/api/sessions/{session_id}/files",
            json={
                "transfer_type": "upload",
                "local_path": "/tmp/a",
                "remote_path": "/tmp/b",
                "result": {"ok": True},
            },
        )
        assert r.json()["success"] is True

        r = await client.get(f"/api/sessions/{session_id}")
        assert r.json()["session"]["files_transferred"][0]["type"] == "upload"

        r = await client.post("/api/sessions/ghost/files", json={})
        assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# T2 crawler
# ---------------------------------------------------------------------------


class TestCrawlerEndpoints:
    async def test_task_lifecycle_sync(self, client, monkeypatch):
        """create → execute(打桩 crawler) → status → get。"""
        from secbot_agent.crawler import scheduler as sched_mod

        async def fake_execute(self, task_id):
            task = self.tasks[task_id]
            task.status = sched_mod.TaskStatus.RUNNING
            from secbot_agent.crawler.base import CrawlResult

            task.result = CrawlResult(url=task.url, content="<h1>ok</h1>", title="OK")
            task.status = sched_mod.TaskStatus.COMPLETED
            task.completed_at = sched_mod.datetime.now()
            return task.result

        monkeypatch.setattr(sched_mod.CrawlerScheduler, "execute_task", fake_execute)

        r = await client.post(
            "/api/crawler/tasks", json={"url": "http://127.0.0.1:1/x", "crawler_type": "simple"}
        )
        task_id = r.json()["task_id"]

        r = await client.post(f"/api/crawler/tasks/{task_id}/execute")
        assert r.json()["success"] is True
        assert r.json()["result"]["title"] == "OK"

        r = await client.get(f"/api/crawler/tasks/{task_id}/status")
        assert r.json()["status"] == "completed"

        r = await client.get(f"/api/crawler/tasks/{task_id}")
        assert r.json()["task"]["status"] == "completed"

    async def test_execute_async_returns_only_success(self, client, monkeypatch):
        from secbot_agent.crawler import scheduler as sched_mod

        async def fake_execute(self, task_id):
            return None

        monkeypatch.setattr(sched_mod.CrawlerScheduler, "execute_task", fake_execute)

        r = await client.post("/api/crawler/tasks", json={"url": "http://127.0.0.1:1/y"})
        task_id = r.json()["task_id"]
        r = await client.post(f"/api/crawler/tasks/{task_id}/execute-async")
        assert r.json() == {"success": True}

    async def test_cancel_not_found(self, client):
        r = await client.post("/api/crawler/tasks/ghost/cancel")
        assert r.json()["success"] is False

    async def test_not_found_shapes(self, client):
        r = await client.get("/api/crawler/tasks/ghost")
        assert r.json()["success"] is False
        r = await client.get("/api/crawler/tasks/ghost/status")
        assert r.json()["success"] is False

    async def test_monitor_check_and_events(self, client, monkeypatch):
        """add → check(首次 False) → 内容变化 → check(变化 True + 事件入缓冲)。"""
        from router import crawler as crawler_mod

        snapshots = iter(["<html>v1</html>", "<html>v1</html>", "<html>v2-changed</html>"])

        async def fake_fetch(url):
            return next(snapshots)

        monkeypatch.setattr(crawler_mod, "_fetch_snapshot", fake_fetch)

        r = await client.post(
            "/api/crawler/monitors", json={"url": "http://127.0.0.1:1/m", "interval": 300}
        )
        monitor_id = r.json()["monitor_id"]
        assert monitor_id == "http:~~127.0.0.1:1~m_300"

        # 首次：建立基线
        r = await client.post(f"/api/crawler/monitors/{monitor_id}/check")
        assert r.json() == {"success": True, "changed": False}

        # 无变化
        r = await client.post(f"/api/crawler/monitors/{monitor_id}/check")
        assert r.json()["changed"] is False

        # 变化 → changed=True + events
        r = await client.post(f"/api/crawler/monitors/{monitor_id}/check")
        assert r.json()["changed"] is True

        listed = (await client.get("/api/crawler/monitors")).json()
        assert listed["events"], "变化事件应进入环形缓冲"
        assert listed["events"][-1]["task_id"] == monitor_id
        assert listed["events"][-1]["changed"] is True
        assert any(m["id"] == monitor_id for m in listed["monitors"])

        # 移除
        r = await client.post(f"/api/crawler/monitors/{monitor_id}/remove")
        assert r.json()["success"] is True
        r = await client.post(f"/api/crawler/monitors/{monitor_id}/remove")
        assert r.json()["success"] is False

    async def test_check_all(self, client, monkeypatch):
        from router import crawler as crawler_mod

        async def fake_fetch(url):
            return "content-a"

        monkeypatch.setattr(crawler_mod, "_fetch_snapshot", fake_fetch)

        await client.post("/api/crawler/monitors", json={"url": "http://127.0.0.1:1/a"})
        await client.post("/api/crawler/monitors", json={"url": "http://127.0.0.1:1/b"})
        r = await client.post("/api/crawler/monitors/check-all")
        assert r.json()["success"] is True
        assert set(r.json()["changed"].values()) == {False}

    async def test_monitor_start_stop(self, client):
        r = await client.post("/api/crawler/monitors/start")
        assert r.json()["success"] is True
        r = await client.post("/api/crawler/monitors/stop")
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# T3 vuln-db
# ---------------------------------------------------------------------------


class TestVulnDbEndpoints:
    async def test_cve_lookup_found_and_missing(self, client, monkeypatch):
        from router import vuln_db as vdb_mod
        from tests.fixtures_vuln import fake_service

        monkeypatch.setattr(vdb_mod, "_get_service", fake_service)

        r = await client.get("/api/vuln-db/cve/CVE-2021-44228")
        assert r.json()["success"] is True
        assert r.json()["vulnerability"]["vuln_id"] == "CVE-2021-44228"

        r = await client.get("/api/vuln-db/cve/CVE-0000-0000")
        assert r.json()["success"] is False
        assert "not found" in r.json()["message"].lower()

    async def test_search_and_scan_match(self, client, monkeypatch):
        from router import vuln_db as vdb_mod
        from tests.fixtures_vuln import fake_service

        monkeypatch.setattr(vdb_mod, "_get_service", fake_service)

        r = await client.post("/api/vuln-db/search", json={"query": "rce", "limit": 5})
        assert r.json()["vulnerabilities"][0]["vuln_id"] == "CVE-2021-44228"

        r = await client.post(
            "/api/vuln-db/scan-match",
            json={"scan_result": {"type": "rce", "severity": "critical"}, "limit": 3},
        )
        assert "matched_vulns" in r.json()

    async def test_stats_and_clear(self, client, monkeypatch):
        from router import vuln_db as vdb_mod
        from tests.fixtures_vuln import fake_service

        monkeypatch.setattr(vdb_mod, "_get_service", fake_service)

        r = await client.get("/api/vuln-db/stats")
        assert "vector_count" in r.json()

        r = await client.post("/api/vuln-db/clear")
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# T4 network 远程控制
# ---------------------------------------------------------------------------


class TestNetworkRemoteControl:
    async def test_authorized_targets_shape(self, client):
        r = await client.get("/api/network/authorized-targets")
        assert r.status_code == 200
        assert "targets" in r.json()

    async def test_connect_unauthorized_403_semantics(self, client):
        """未授权目标 connect 返回 success=False（403 语义），不抛 5xx。"""
        r = await client.post("/api/network/connect", json={"targetIp": "203.0.113.99"})
        assert r.status_code == 200
        assert r.json()["success"] is False
        assert "not authorized" in r.json()["error"].lower()

    async def test_execute_unauthorized(self, client):
        r = await client.post(
            "/api/network/execute", json={"targetIp": "203.0.113.99", "command": "id"}
        )
        assert r.json()["success"] is False

    async def test_upload_download_disconnect_unauthorized(self, client):
        for endpoint, payload in [
            (
                "/api/network/upload",
                {"targetIp": "203.0.113.99", "localPath": "a", "remotePath": "b"},
            ),
            (
                "/api/network/download",
                {"targetIp": "203.0.113.99", "remotePath": "b", "localPath": "a"},
            ),
        ]:
            r = await client.post(endpoint, json=payload)
            assert r.json()["success"] is False
            assert "not authorized" in r.json()["error"].lower()

        r = await client.post("/api/network/disconnect", json={"targetIp": "203.0.113.99"})
        assert r.json()["success"] is True

    async def test_control_sessions_shape(self, client):
        r = await client.get("/api/network/control/sessions")
        assert r.status_code == 200
        assert "active_sessions" in r.json()

    async def test_authorized_flow_via_ssh_fixture(self, client, monkeypatch):
        """connect→execute→upload→download→disconnect 打桩 RemoteController 走全链。"""
        from router.dependencies import _Singletons

        class FakeSSHClient:
            def exec_command(self, command):
                import io

                class Ch:
                    def read(self):
                        return b"uid=0(root)"

                    channel = type("C", (), {"recv_exit_status": lambda self: 0})()

                return (io.BytesIO(b""), Ch(), io.BytesIO(b""))

            def open_sftp(self):
                class SFTP:
                    def put(self, local_p, remote_p):
                        pass

                    def get(self, remote_p, local_p):
                        pass

                    def close(self):
                        pass

                return SFTP()

            def close(self):
                pass

        mc = _Singletons.main_controller()
        monkeypatch.setattr(
            mc.remote_controller,
            "connect_ssh",
            lambda *a, **k: FakeSSHClient(),
        )

        mc.authorize_target(
            target_ip="127.0.0.1",
            auth_type="full",
            credentials={"username": "root", "password": "x"},
        )
        try:
            r = await client.post(
                "/api/network/connect", json={"targetIp": "127.0.0.1", "connectionType": "ssh"}
            )
            assert r.json()["success"] is True, r.json()
            session_id = r.json()["session_id"]

            r = await client.post(
                "/api/network/execute", json={"targetIp": "127.0.0.1", "command": "id"}
            )
            body = r.json()
            assert body["success"] is True
            assert "root" in body["output"]

            # 会话台账自动记录命令（对齐 TS）
            detail = await client.get(f"/api/sessions/{session_id}")
            assert detail.json()["success"] is True
            assert detail.json()["session"]["commands_executed"][0]["command"] == "id"

            r = await client.post(
                "/api/network/upload",
                json={"targetIp": "127.0.0.1", "localPath": "/tmp/x", "remotePath": "/tmp/y"},
            )
            assert r.json()["success"] is True

            r = await client.post(
                "/api/network/download",
                json={"targetIp": "127.0.0.1", "remotePath": "/tmp/y", "localPath": "/tmp/z"},
            )
            assert r.json()["success"] is True

            r = await client.get("/api/network/control/sessions")
            assert any(s.get("target_ip") == "127.0.0.1" for s in r.json()["active_sessions"])

            r = await client.post("/api/network/disconnect", json={"targetIp": "127.0.0.1"})
            assert r.json()["success"] is True
        finally:
            mc.auth_manager.revoke_authorization("127.0.0.1")


# ---------------------------------------------------------------------------
# T5 memory 补全
# ---------------------------------------------------------------------------


class TestMemoryEndpoints:
    async def test_distill_episode_knowledge_writes_visible(self, client):
        stats0 = (await client.get("/api/memory/stats")).json()["memory"]

        r = await client.post(
            "/api/memory/distill",
            json={"conversation": [{"role": "user", "content": "hi"}], "summary": "phase4 蒸馏"},
        )
        assert r.json() == {"success": True}

        r = await client.post(
            "/api/memory/episode",
            json={"event": "扫描完成", "outcome": "发现 2 端口", "target": "10.0.0.1"},
        )
        assert r.json() == {"success": True}

        r = await client.post(
            "/api/memory/knowledge",
            json={"fact": "22 端口开放通常为 SSH", "category": "network", "importance": 0.8},
        )
        assert r.json() == {"success": True}

        stats1 = (await client.get("/api/memory/stats")).json()["memory"]
        assert stats1["episodic_count"] >= stats0["episodic_count"] + 2
        assert stats1["long_term_count"] >= stats0["long_term_count"] + 1

        listed = (
            await client.get("/api/memory/list", params={"memory_type": "long_term"})
        ).json()
        assert any("SSH" in i["content"] for i in listed["items"])
