"""Manual DB playground: create one demo incident and list latest 5."""
from app.database.session import SessionLocal
from app.models.incident import Incident
from app.repositories.incident import IncidentRepository
from app.services.tenant import ensure_default_tenant

db = SessionLocal()
try:
    tenant = ensure_default_tenant(db)
    repo = IncidentRepository(db)
    repo.create(
        Incident(
            tenant_id=tenant.id,
            title="Database Down",
            message="Production PostgreSQL is not responding.",
        )
    )
    print(repo.get_latest(limit=5))
finally:
    db.close()
