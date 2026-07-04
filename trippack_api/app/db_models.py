import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    Text,
    Numeric,
    JSON,
    ForeignKey,
    Index,
    DateTime,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TripGoal(Base):
    __tablename__ = "trip_goals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    origin: Mapped[str] = mapped_column(String(256), default="")
    destination_preference: Mapped[str] = mapped_column(String(512), default="")
    budget_usd: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    start_date: Mapped[str] = mapped_column(String(32), default="")
    end_date: Mapped[str] = mapped_column(String(32), default="")
    needs_car: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    check_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    quotes: Mapped[list["ProviderQuote"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["PackageSnapshot"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["DealAlert"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class ProviderQuote(Base):
    __tablename__ = "provider_quotes"
    __table_args__ = (Index("ix_pq_goal", "trip_goal_id"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    trip_goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trip_goals.id", ondelete="CASCADE")
    )
    goal: Mapped["TripGoal"] = relationship(back_populates="quotes")
    category: Mapped[str] = mapped_column(String(16), default="flight")
    provider: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    price_usd: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    terms_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)


class PackageSnapshot(Base):
    __tablename__ = "package_snapshots"
    __table_args__ = (Index("ix_ps_goal", "trip_goal_id"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    trip_goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trip_goals.id", ondelete="CASCADE")
    )
    goal: Mapped["TripGoal"] = relationship(back_populates="snapshots")
    total_price_usd: Mapped[float | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    flight_quote_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    stay_quote_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    car_quote_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    passed_budget: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    constraints_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class DealAlert(Base):
    __tablename__ = "deal_alerts"
    __table_args__ = (Index("ix_da_goal", "trip_goal_id"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    trip_goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trip_goals.id", ondelete="CASCADE")
    )
    goal: Mapped["TripGoal"] = relationship(back_populates="alerts")
    snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    why_triggered: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
