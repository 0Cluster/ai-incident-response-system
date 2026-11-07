"""Seed default DB-driven automation rules (idempotent).

Run: uv run python -m scripts.seed_automation_rules
"""

from app.database.session import SessionLocal
from app.models.automation_rule import AutomationRule
from app.services.tenant import ensure_default_tenant

DEFAULT_RULES = [
    # Always log, lowest order so it runs first
    {"severity": "UNKNOWN", "action_name": "log", "enabled": True, "execution_order": 1, "config": {}},
    {"severity": "LOW", "action_name": "log", "enabled": True, "execution_order": 1, "config": {}},
    {"severity": "MEDIUM", "action_name": "log", "enabled": True, "execution_order": 1, "config": {}},
    {"severity": "HIGH", "action_name": "log", "enabled": True, "execution_order": 1, "config": {}},
    {"severity": "CRITICAL", "action_name": "log", "enabled": True, "execution_order": 1, "config": {}},
    # Example webhook disabled by default — enable via API/UI with a real URL
    {
        "severity": "CRITICAL",
        "action_name": "webhook",
        "enabled": False,
        "execution_order": 2,
        "config": {"url": "http://localhost:8000/api/v1/webhooks/custom"},
    },
]


def main() -> None:
    db = SessionLocal()
    try:
        tenant = ensure_default_tenant(db)
        created = 0
        for spec in DEFAULT_RULES:
            exists = (
                db.query(AutomationRule)
                .filter(
                    AutomationRule.tenant_id == tenant.id,
                    AutomationRule.severity == spec["severity"],
                    AutomationRule.action_name == spec["action_name"],
                )
                .first()
            )
            if exists:
                continue
            db.add(AutomationRule(tenant_id=tenant.id, **spec))
            created += 1
        db.commit()
        print(f"Seeded {created} automation rules for tenant {tenant.slug}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
