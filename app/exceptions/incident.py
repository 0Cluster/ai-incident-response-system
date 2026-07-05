class IncidentNotFoundError(Exception):
    def __init__(self, incident_id: int):
        self.incident_id = incident_id
        super().__init__(f"Incident {incident_id} not found")
