"""Połączenie z bazą i inicjalizacja świeżego schematu OPOS."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_URL, INITIAL_ADMIN_PASSWORD


logger = logging.getLogger(__name__)
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


if DB_URL.startswith("sqlite"):

    @event.listens_for(Engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


_LEGACY_SZOP_TABLES = frozenset(
    {
        "abilities",
        "armories",
        "armory_disabled_weapons",
        "army_spells",
        "rulesets",
        "unit_abilities",
        "unit_groups",
        "unit_weapons",
        "units",
        "weapons",
    }
)

_ROSTER_MODE_COLUMNS = (
    "simple_points_enabled",
    "collapse_descriptions",
    "small_battle_enabled",
)


def assert_not_legacy_szop_database(bind: Engine) -> None:
    """Refuse an in-place SZOP-to-OPOS conversion.

    OPOS intentionally starts from a fresh database. Creating the new tables next
    to an old schema would leave a database that appears usable while mixing two
    incompatible domains.
    """
    legacy_tables = sorted(set(inspect(bind).get_table_names()) & _LEGACY_SZOP_TABLES)
    if legacy_tables:
        joined = ", ".join(legacy_tables)
        raise RuntimeError(
            "Wykryto bazę SZOP (tabele: "
            f"{joined}). OPOS wymaga świeżej bazy data/opos.db; "
            "zachowaj starą bazę jako archiwum i ustaw osobny DB_URL."
        )


def ensure_roster_mode_columns(bind: Engine) -> None:
    """Upgrade pre-mode SQLite databases without touching their OPOS data."""
    if bind.dialect.name != "sqlite":
        return
    inspector = inspect(bind)
    if "rosters" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("rosters")}
    missing = [name for name in _ROSTER_MODE_COLUMNS if name not in existing]
    if not missing:
        return
    with bind.begin() as connection:
        for name in missing:
            connection.exec_driver_sql(
                f"ALTER TABLE rosters ADD COLUMN {name} "
                "BOOLEAN NOT NULL DEFAULT 0"
            )


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create a fresh OPOS schema and a securely bootstrapped administrator."""
    from . import models
    from .security import hash_password
    from .services.opos_units import normalize_legacy_snapshot_records

    if DB_URL.startswith("sqlite"):
        raw_path = DB_URL.split("///", maxsplit=1)[-1]
        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

    assert_not_legacy_szop_database(engine)
    ensure_roster_mode_columns(engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal.begin() as session:
        normalized = normalize_legacy_snapshot_records(session)
        if normalized:
            logger.info(
                "Przeniesiono Szarżę/Przygotowanie do profili ataku w %s snapshotach.",
                normalized,
            )
        admin = session.execute(
            select(models.User).where(models.User.username == "admin")
        ).scalar_one_or_none()
        if admin is None:
            session.add(
                models.User(
                    username="admin",
                    password_hash=hash_password(INITIAL_ADMIN_PASSWORD),
                    is_admin=True,
                )
            )
            logger.warning(
                "Utworzono administratora 'admin'. Hasło bootstrap znajduje się "
                "w chronionym pliku DATA_DIR/.initial_admin_password albo w zmiennej "
                "INITIAL_ADMIN_PASSWORD. Zmień je po pierwszym logowaniu."
            )
