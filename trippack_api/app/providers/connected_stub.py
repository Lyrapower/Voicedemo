from app.providers.base import TripQuotesProvider, QuotePayload


class ConnectedStubProvider(TripQuotesProvider):
    """No fake prices: returns empty until a real integration is implemented."""

    def fetch_quotes(self, goal_context: dict) -> list[QuotePayload]:
        return []
