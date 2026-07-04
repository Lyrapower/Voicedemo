from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class QuotePayload:
    category: str  # flight | stay | car
    provider: str
    title: str
    price_usd: float | None
    currency: str
    source_url: str
    terms_notes: str | None
    is_demo: bool
    is_live: bool


class TripQuotesProvider(ABC):
    """Fetches quotes for one goal context; empty list when not connected."""

    @abstractmethod
    def fetch_quotes(self, goal_context: dict) -> list[QuotePayload]:
        pass
