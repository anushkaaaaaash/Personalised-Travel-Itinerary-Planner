"""History means saved trip preferences, never an invented generation audit log."""
class HistoryService:
    def __init__(self, trips):
        self.trips = trips

    async def list_saved_trips(self, limit=20, offset=0):
        return await self.trips.list(limit, offset)
