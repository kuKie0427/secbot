"""Skills REST 路由 — 对齐 TS skills.controller.ts 三端点。

- GET /api/skills → { skills: [...] } 信封，summary 10 字段
- GET /api/skills/{name} → 详情；未知技能 404（对齐 TS NotFoundException）
- POST /api/skills → create；重名对齐 TS plain Error → HTTP 500（有意分歧记录于 docs/SKILLS.md）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from secbot_agent.skills.service import (
    SkillAlreadyExists,
    SkillNotFound,
    get_default_skill_service,
)

router = APIRouter(prefix="/api/skills", tags=["Skills"])


class CreateSkillRequest(BaseModel):
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    author: Optional[str] = None
    tags: Optional[List[str]] = None
    triggers: Optional[List[str]] = None
    prerequisites: Optional[List[str]] = None
    body: Optional[str] = None


@router.get("")
async def list_skills():
    service = get_default_skill_service()
    return {"skills": service.list_skills()}


@router.get("/{name}")
async def get_skill(name: str):
    service = get_default_skill_service()
    try:
        return service.get_skill(name)
    except SkillNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("")
async def create_skill(body: CreateSkillRequest):
    service = get_default_skill_service()
    try:
        return service.create_skill(body.model_dump())
    except SkillAlreadyExists as e:
        # 对齐 TS：service 抛 plain Error → Nest 默认 500
        raise HTTPException(status_code=500, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
