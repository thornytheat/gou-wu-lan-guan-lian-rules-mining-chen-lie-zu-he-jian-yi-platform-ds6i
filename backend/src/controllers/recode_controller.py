"""换码方案：创建 / 列表 / 详情 / 预览 / 执行（含续跑）。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.models.user import User
from src.schemas.recode import RecodePlanCreateRequest
from src.services import recode_service


def create_plan(db: Session, user: User, payload: RecodePlanCreateRequest, trace_id: str = "") -> dict:
    return recode_service.create_plan(db, user, payload.model_dump(), trace_id=trace_id)


def list_plans(db: Session) -> dict:
    return recode_service.list_plans(db)


def get_plan(db: Session, plan_id: str) -> dict:
    return recode_service.plan_detail(db, recode_service.get_plan(db, plan_id))


def preview_plan(db: Session, user: User, plan_id: str, trace_id: str = "") -> dict:
    return recode_service.preview_plan(db, user, plan_id, trace_id=trace_id)


def execute_plan(db: Session, user: User, plan_id: str, trace_id: str = "") -> dict:
    return recode_service.execute_plan(db, user, plan_id, trace_id=trace_id)
