from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.controllers import recode_controller
from src.middlewares.rbac import require_permission
from src.middlewares.rate_limit import rate_limit
from src.models.user import User
from src.schemas.recode import RecodePlanCreateRequest

router = APIRouter(tags=["recode"])


@router.get("/recode/plans")
def list_plans(
    db: Session = Depends(get_db),
    _=Depends(require_permission("recode:read")),
) -> dict:
    return recode_controller.list_plans(db)


@router.post("/recode/plans")
def create_plan(
    payload: RecodePlanCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recode:write")),
) -> dict:
    return recode_controller.create_plan(
        db, user, payload, trace_id=getattr(request.state, "trace_id", "")
    )


@router.get("/recode/plans/{plan_id}")
def get_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_permission("recode:read")),
) -> dict:
    return recode_controller.get_plan(db, plan_id)


@router.post("/recode/plans/{plan_id}/preview")
def preview_plan(
    plan_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recode:write")),
) -> dict:
    return recode_controller.preview_plan(
        db, user, plan_id, trace_id=getattr(request.state, "trace_id", "")
    )


@router.post("/recode/plans/{plan_id}/execute")
def execute_plan(
    plan_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("recode:write")),
    _=rate_limit("mining"),
) -> dict:
    return recode_controller.execute_plan(
        db, user, plan_id, trace_id=getattr(request.state, "trace_id", "")
    )
