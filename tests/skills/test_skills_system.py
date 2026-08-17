"""Phase 2 Skills 系统测试：Loader 递归扫描 / Service 写入 / REST 契约 / 注入开关。"""

import pytest
from fastapi.testclient import TestClient

from secbot_agent.skills.loader import SkillLoader, slugify
from secbot_agent.skills.service import (
    SkillAlreadyExists,
    SkillNotFound,
    SkillService,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SECBOT_WORKSPACE_ROOT", str(tmp_path))
    yield tmp_path


class TestLoader:
    def test_discovers_custom_nested_skill(self, workspace):
        skill_dir = workspace / "skills" / "custom" / "foo-bar"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Foo Bar\ndescription: test\n---\n\nBody here\n", encoding="utf-8"
        )
        loader = SkillLoader(workspace_root_=str(workspace))
        skills = loader.load_all()
        assert "Foo Bar" in skills
        m = skills["Foo Bar"].manifest
        assert m.slug == "foo-bar"
        assert m.scope == "custom"
        assert m.relative_dir == "skills/custom/foo-bar"

    def test_no_workspace_skills_dir_silent(self, workspace):
        loader = SkillLoader(workspace_root_=str(workspace))
        skills = loader.load_all()  # 不抛错
        # 包内 base 技能仍可见（有意分歧：Python 双源发现）
        assert len(skills) >= 5

    def test_base_scope_annotated(self, workspace):
        loader = SkillLoader(workspace_root_=str(workspace))
        skills = loader.load_all()
        base = [s for s in skills.values() if s.manifest.scope == "base"]
        assert len(base) == 5

    def test_cache_invalidated_on_create(self, workspace):
        loader = SkillLoader(workspace_root_=str(workspace))
        loader.load_all()
        skill_dir = workspace / "skills" / "custom" / "later"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: Later\n---\nB\n")
        loader.invalidate_cache()
        assert "Later" in loader.load_all()

    def test_slugify(self):
        assert slugify("My Cool Skill!") == "my-cool-skill"
        assert slugify("") == "custom-skill"


class TestService:
    def test_create_writes_and_reloadable(self, workspace):
        service = SkillService(SkillLoader(workspace_root_=str(workspace)))
        detail = service.create_skill({
            "name": "My Audit",
            "description": "审计技能",
            "tags": ["audit"],
            "triggers": ["audit"],
        })
        assert detail["slug"] == "my-audit"
        assert detail["scope"] == "custom"
        assert (workspace / "skills" / "custom" / "my-audit" / "SKILL.md").exists()

        # 再次 list 可见（T1 递归扫描验证）
        names = [s["slug"] for s in service.list_skills()]
        assert "my-audit" in names

        # get round-trip
        got = service.get_skill("my-audit")
        assert got["body"]  # 默认脚手架正文

    def test_create_duplicate_raises(self, workspace):
        service = SkillService(SkillLoader(workspace_root_=str(workspace)))
        service.create_skill({"name": "dup"})
        with pytest.raises(SkillAlreadyExists):
            service.create_skill({"name": "dup"})

    def test_get_unknown_404_semantics(self, workspace):
        service = SkillService(SkillLoader(workspace_root_=str(workspace)))
        with pytest.raises(SkillNotFound):
            service.get_skill("no-such-skill")

    def test_summary_has_10_fields(self, workspace):
        service = SkillService(SkillLoader(workspace_root_=str(workspace)))
        summary = service.list_skills()[0]
        expected = {
            "name", "description", "version", "author", "tags",
            "triggers", "prerequisites", "slug", "scope", "relativeDir",
        }
        assert expected == set(summary.keys())


class TestRestContract:
    def test_endpoints(self, workspace, tmp_path):
        from router.main import create_app

        client = TestClient(create_app())

        # GET 列表：{ skills: [...] } 信封
        r = client.get("/api/skills")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"skills"}
        assert len(body["skills"]) >= 5

        # GET 单个（包内 base 技能）
        name = body["skills"][0]["name"]
        r = client.get(f"/api/skills/{name}")
        assert r.status_code == 200
        assert "body" in r.json()

        # GET 未知 → 404
        r = client.get("/api/skills/no-such")
        assert r.status_code == 404

        # POST 创建 → 再 GET 可见
        r = client.post("/api/skills", json={"name": "Rest Skill", "description": "x"})
        assert r.status_code == 200
        assert r.json()["slug"] == "rest-skill"
        assert client.get("/api/skills/rest-skill").status_code == 200

        # POST 重名 → 500（对齐 TS plain Error 语义）
        r = client.post("/api/skills", json={"name": "Rest Skill"})
        assert r.status_code == 500


class TestInjectorDefaultOff:
    def test_default_env_no_instantiation(self, workspace, monkeypatch):
        monkeypatch.delenv("SECBOT_SKILL_AUTO_INJECT", raising=False)
        import secbot_agent.core.session as session_mod

        created = []

        class _FakeInjector:
            def __init__(self):
                created.append(self)
                self.skills = {}

            def find_relevant_skills(self, q):
                return []

        monkeypatch.setattr(
            "secbot_agent.skills.injector.SkillInjector", _FakeInjector
        )
        mgr = session_mod.SessionManager.__new__(session_mod.SessionManager)
        import asyncio

        out = asyncio.run(mgr._maybe_inject_skills("hello"))
        assert out == "hello"
        assert created == []  # 关闭时不实例化

    def test_enabled_env_injects(self, workspace, monkeypatch):
        monkeypatch.setenv("SECBOT_SKILL_AUTO_INJECT", "1")
        import secbot_agent.core.session as session_mod

        class _FakeSkill:
            class manifest:
                name = "nmap-usage"
            instructions = "Use nmap safely."

        class _FakeInjector:
            def __init__(self):
                self.skills = {}

            def find_relevant_skills(self, q):
                return [_FakeSkill()]

        monkeypatch.setattr(
            "secbot_agent.skills.injector.SkillInjector", _FakeInjector
        )
        mgr = session_mod.SessionManager.__new__(session_mod.SessionManager)
        import asyncio

        out = asyncio.run(mgr._maybe_inject_skills("nmap scan target"))
        assert out.startswith("<available-skills>")
        assert "nmap scan target" in out


class TestAgentTools:
    def test_three_tools_in_catalog(self):
        from router.tools import _CATEGORIES
        names = {t.name for _, _, lst in _CATEGORIES for t in lst}
        for n in ("list_skills", "get_skill", "create_skill"):
            assert n in names

    def test_tool_roundtrip(self, workspace):
        from tools.skills import ListSkillsTool, GetSkillTool, CreateSkillTool

        import asyncio

        r = asyncio.run(CreateSkillTool().execute(name="Tool Skill", description="d"))
        assert r.success and r.result["slug"] == "tool-skill"

        r = asyncio.run(ListSkillsTool().execute())
        assert r.success and any(s["slug"] == "tool-skill" for s in r.result["skills"])

        r = asyncio.run(GetSkillTool().execute(name="tool-skill"))
        assert r.success and r.result["slug"] == "tool-skill"

        r = asyncio.run(GetSkillTool().execute())
        assert not r.success and "name" in r.error
