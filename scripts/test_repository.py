from app.database.session import SessionLocal
from app.services.incident import IncidentService

db = SessionLocal()

service = IncidentService(db)

incident = service.create_incident(
    title="Production API Down",
    message="Users are receiving HTTP 500 responses.",
)

print(incident.id)
print(service.list_incidents())
