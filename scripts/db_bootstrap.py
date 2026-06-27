"""Shared DB bootstrap for standalone scripts that read the app database."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def initialized_session() -> Iterator[object]:
    """Open a DB session after applying the same schema bootstrap as the app."""
    from app.db import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        yield session
