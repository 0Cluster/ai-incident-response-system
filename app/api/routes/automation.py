from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.automation.registry import registry
from app.core.auth import Principal, require_role
from app.core.dependencies import get_db
from app.models.enums import UserRole
from app.schemas.automation import (
    AutomationRuleCreate,
    AutomationRuleResponse,
    AutomationRuleUpdate,
)
from app.services.automation_rule import AutomationRuleService

router = APIRouter(prefix="/automation-rules", tags=["Automation"])


def get_automation_service(
    db: Session = Depends(get_db),
) -> AutomationRuleService:
    return AutomationRuleService(db)


@router.get("/actions")
def list_actions(_: Principal = Depends(require_role(UserRole.VIEWER))):
    return {"actions": registry.list()}


@router.get("/", response_model=list[AutomationRuleResponse])
def list_rules(
    service: AutomationRuleService = Depends(get_automation_service),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
):
    return service.list_rules(principal.tenant_id)


@router.post("/", response_model=AutomationRuleResponse, status_code=201)
def create_rule(
    data: AutomationRuleCreate,
    service: AutomationRuleService = Depends(get_automation_service),
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
):
    if registry.get(data.action_name) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{data.action_name}'",
        )
    try:
        return service.create_rule(
            tenant_id=principal.tenant_id,
            severity=data.severity,
            action_name=data.action_name,
            enabled=data.enabled,
            execution_order=data.execution_order,
            config=data.config,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{rule_id}", response_model=AutomationRuleResponse)
def update_rule(
    rule_id: int,
    data: AutomationRuleUpdate,
    service: AutomationRuleService = Depends(get_automation_service),
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
):
    if data.action_name is not None and registry.get(data.action_name) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{data.action_name}'",
        )
    try:
        rule = service.update_rule(
            rule_id,
            tenant_id=principal.tenant_id,
            severity=data.severity,
            action_name=data.action_name,
            enabled=data.enabled,
            execution_order=data.execution_order,
            config=data.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if rule is None:
        raise HTTPException(status_code=404, detail="Automation rule not found")
    return rule


@router.delete("/{rule_id}", status_code=204)
def delete_rule(
    rule_id: int,
    service: AutomationRuleService = Depends(get_automation_service),
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
):
    ok = service.delete_rule(rule_id, principal.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Automation rule not found")
    return Response(status_code=204)
