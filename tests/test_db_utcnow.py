from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, utcnow


def _memory_session():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_utcnow_is_naive_utc():
    """SSOT `utcnow()` musi zwracać NAIVE datetime (tzinfo=None).

    Kolumny `DateTime` (bez `timezone=True`) porównują naive datetimes
    (np. `AgentToken.expires_at <= now`), więc aware zerwałby te porównania
    `TypeError`. Ten test pinuje świadomą decyzję (zob. HANDOFF_utcnow-deprecation).
    """
    now = utcnow()
    assert now.tzinfo is None
    # Wartość jest bieżącym czasem UTC (a nie lokalnym) — porównaj z aware UTC.
    delta = abs((datetime.now(UTC).replace(tzinfo=None) - now).total_seconds())
    assert delta < 5


def test_timestamp_columns_persist_naive_datetimes():
    """TimestampMixin (`default=utcnow`) zapisuje naive datetimes do DB."""
    Session = _memory_session()
    with Session() as session:
        user = models.User(username="ts-naive", password_hash="x")
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.created_at.tzinfo is None
        assert user.updated_at.tzinfo is None
