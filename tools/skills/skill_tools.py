"""Skills 三工具 — list_skills/get_skill/create_skill。

对齐 TS tools/skills/*.tool.ts：依赖注入共享 SkillService（create 需写入能力），
惰性获取单例避免 import 时序问题。
"""
from typing import Any, Dict

from tools.base import BaseTool, ToolResult


def _service():
    from secbot_agent.skills.service import get_default_skill_service
    return get_default_skill_service()


class ListSkillsTool(BaseTool):
    def __init__(self):
        super().__init__(name="list_skills", description="List available Secbot skills.")

    async def execute(self, **kwargs) -> ToolResult:
        try:
            skills = _service().list_skills()
            return ToolResult(success=True, result={"total": len(skills), "skills": skills})
        except Exception as e:
            return ToolResult(success=False, result=None, error=str(e))

    def get_schema(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {}}}


class GetSkillTool(BaseTool):
    def __init__(self):
        super().__init__(name="get_skill", description="Read metadata and body for a Secbot skill.")

    async def execute(self, name: str = "", slug: str = "", **kwargs) -> ToolResult:
        target = (name or slug or "").strip()
        if not target:
            return ToolResult(success=False, result=None, error="Missing parameter: name")
        try:
            skill = _service().get_skill(target)
            return ToolResult(success=True, result=skill)
        except Exception as e:
            return ToolResult(success=False, result=None, error=str(e))

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "技能名或 slug"}},
                "required": ["name"],
            },
        }


class CreateSkillTool(BaseTool):
    def __init__(self):
        super().__init__(name="create_skill", description="Create a new Secbot skill in the local workspace.")

    async def execute(
        self,
        name: str = "",
        description: str = "",
        version: str = "",
        author: str = "",
        tags=None,
        triggers=None,
        prerequisites=None,
        body: str = "",
        **kwargs,
    ) -> ToolResult:
        name = (name or "").strip()
        if not name:
            return ToolResult(success=False, result=None, error="Missing parameter: name")
        payload: Dict[str, Any] = {"name": name}
        if description:
            payload["description"] = description
        if version:
            payload["version"] = version
        if author:
            payload["author"] = author
        if tags:
            payload["tags"] = [str(t) for t in tags]
        if triggers:
            payload["triggers"] = [str(t) for t in triggers]
        if prerequisites:
            payload["prerequisites"] = [str(p) for p in prerequisites]
        if body:
            payload["body"] = body
        try:
            skill = _service().create_skill(payload)
            return ToolResult(success=True, result=skill)
        except Exception as e:
            return ToolResult(success=False, result=None, error=str(e))

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能名（slug 化）"},
                    "description": {"type": "string"},
                    "version": {"type": "string"},
                    "author": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "triggers": {"type": "array", "items": {"type": "string"}},
                    "prerequisites": {"type": "array", "items": {"type": "string"}},
                    "body": {"type": "string", "description": "技能正文 Markdown（缺省生成脚手架）"},
                },
                "required": ["name"],
            },
        }
