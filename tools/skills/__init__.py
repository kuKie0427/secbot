"""
Skills 工具包：list_skills / get_skill / create_skill（依赖注入共享 SkillService）
"""
from tools.skills.skill_tools import ListSkillsTool, GetSkillTool, CreateSkillTool

SKILLS_TOOLS = [
    ListSkillsTool(),
    GetSkillTool(),
    CreateSkillTool(),
]

__all__ = ["ListSkillsTool", "GetSkillTool", "CreateSkillTool", "SKILLS_TOOLS"]
