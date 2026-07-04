from app.database.session import SessionLocal
from app.models.incident import Incident
from app.repositories.incident import IncidentRepository

db = SessionLocal()

repo = IncidentRepository(db)

incident = Incident(
    title="Database Down",
    message="Production PostgreSQL is not responding.",
)

repo.create(incident)

print(repo.get_all())
