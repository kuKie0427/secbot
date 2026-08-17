"""共享 SkillService — list/get/create 封装，router 与 agent 工具共用同一实例。

对齐 TS skills.service.ts：SkillLoader 保持只读，写入能力集中在本服务
（create 渲染 frontmatter 写 workspace skills/custom/<slug>/SKILL.md）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from secbot_agent.skills.loader import SkillLoader, slugify, workspace_root

SKILL_FILE_NAME = "SKILL.md"
DEFAULT_DESCRIPTION = "Custom Secbot skill."
DEFAULT_AUTHOR = "Secbot"
DEFAULT_VERSION = "1.0.0"


class SkillNotFound(Exception):
    """对齐 TS NotFoundException → HTTP 404。"""


class SkillAlreadyExists(Exception):
    """对齐 TS 重名 plain Error → HTTP 500（有意保持，不改为 409）。"""


def _build_default_body(name: str, description: str, triggers: List[str]) -> str:
    lines = [
        "# Overview",
        "",
        description,
        "",
        "## When to use",
        "",
        f"Use this skill when working on {name.replace('-', ' ')} tasks.",
        "",
        "## Triggers",
        "",
    ]
    lines.extend(f"- {t}" for t in triggers) if triggers else lines.append("- add-trigger-here")
    lines.extend(["", "## Notes", "", "- Replace this scaffold with task-specific guidance."])
    return "\n".join(lines)


def _normalize_list(values: Optional[List[str]]) -> List[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


class SkillService:
    def __init__(self, loader: Optional[SkillLoader] = None):
        self.loader = loader or SkillLoader()
        self._workspace_root = workspace_root()

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------
    def list_skills(self) -> List[Dict[str, Any]]:
        self.loader.load_all()
        return self.loader.list_skills()

    def get_skill(self, name_or_slug: str) -> Dict[str, Any]:
        needle = slugify(name_or_slug)
        self.loader.load_all()
        for skill in self.loader.loaded_skills.values():
            if skill.manifest.slug == needle or slugify(skill.manifest.name) == needle:
                summary = next(
                    s for s in self.loader.list_skills() if s["slug"] == skill.manifest.slug
                )
                return {**summary, "body": skill.instructions.strip()}
        raise SkillNotFound(f"Skill not found: {name_or_slug}")

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------
    def create_skill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Missing parameter: name")

        slug = slugify(name)
        relative_dir = f"skills/custom/{slug}"
        dir_path = self._workspace_root / relative_dir
        file_path = dir_path / SKILL_FILE_NAME

        dir_path.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            raise SkillAlreadyExists(f"Skill already exists: {slug}")

        description = str(payload.get("description") or DEFAULT_DESCRIPTION).strip()
        version = str(payload.get("version") or DEFAULT_VERSION).strip()
        author = str(payload.get("author") or DEFAULT_AUTHOR).strip()
        tags = _normalize_list(payload.get("tags"))
        triggers_in = _normalize_list(payload.get("triggers"))
        triggers = triggers_in or [slug]
        prerequisites = _normalize_list(payload.get("prerequisites"))
        body = str(payload.get("body") or _build_default_body(slug, description, triggers)).rstrip()

        file_path.write_text(
            _render_skill(name=slug, description=description, version=version, author=author,
                          tags=tags, triggers=triggers, prerequisites=prerequisites, body=body),
            encoding="utf-8",
        )
        logger.info(f"创建技能: {slug} → {file_path}")
        self.loader.invalidate_cache()
        return {
            "name": slug,
            "description": description,
            "version": version,
            "author": author,
            "tags": tags,
            "triggers": triggers,
            "prerequisites": prerequisites,
            "slug": slug,
            "scope": "custom",
            "relativeDir": relative_dir,
            "body": body,
        }


def _render_skill(*, name: str, description: str, version: str, author: str,
                  tags: List[str], triggers: List[str], prerequisites: List[str], body: str) -> str:
    """渲染 SKILL.md（对齐 TS renderSkill 的 frontmatter 布局）。"""
    desc_lines = "\n".join(f"  {ln}" for ln in description.splitlines()) or "  "
    def _arr(items: List[str]) -> str:
        return "[" + ", ".join(f'"{i}"' for i in items) + "]"

    return (
        "---\n"
        f"name: {name}\n"
        "description: |\n"
        f"{desc_lines}\n"
        f'version: "{version}"\n'
        f'author: "{author}"\n'
        f"tags: {_arr(tags)}\n"
        f"triggers: {_arr(triggers)}\n"
        f"prerequisites: {_arr(prerequisites)}\n"
        "---\n"
        f"\n{body}\n"
    )


_default_service: Optional[SkillService] = None


def get_default_skill_service() -> SkillService:
    """惰性单例：避免 import 时序问题（SkillInjector 等不触发加载）。"""
    global _default_service
    if _default_service is None:
        _default_service = SkillService()
    return _default_service
