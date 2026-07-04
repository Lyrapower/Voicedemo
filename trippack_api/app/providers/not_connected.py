from app.providers.base import TripQuotesProvider, QuotePayload


class NotConnectedProvider(TripQuotesProvider):
    def fetch_quotes(self, goal_context: dict) -> list[QuotePayload]:
        return []
