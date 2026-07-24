class Metrics:
    def __init__(self):
        self.event_logs = []

    def log_event(self, time: float, entity_id: str, event_type: str, details: dict):
        self.event_logs.append(
            {
                "time": time,
                "entity_id": entity_id,
                "event_type": event_type,
                "details": details,
            }
        )
