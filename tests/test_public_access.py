from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import config, main, models
from app.db import Base, _ensure_admin, get_db
from app.security import hash_password, verify_password
from app.services import public_access

ORIGIN = "https://testserver"
PASSWORD = "haslo testowe 2026"


class FormInputs(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.values = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            attributes = dict(attrs)
            if "name" in attributes:
                self.values[attributes["name"]] = attributes.get("value", "")


@dataclass
class Clock:
    now: float


@pytest.fixture
def public_app(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'public.sqlite3'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    def override_db():
        with sessions() as db:
            yield db

    clock = Clock(1000.0)
    monkeypatch.setattr(config, "PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("REGISTRATION_OPEN", "true")
    monkeypatch.setattr(public_access, "REGISTRATION_CODE", "")
    monkeypatch.setattr(public_access, "MAX_ACCOUNTS", 100)
    monkeypatch.setattr(public_access, "REGISTER_INTERVAL", 60)
    monkeypatch.setattr(public_access, "MIN_FORM_AGE", 0)
    monkeypatch.setattr(public_access, "attempts", public_access.AttemptLimiter())
    monkeypatch.setattr(public_access, "time", SimpleNamespace(time=lambda: clock.now, monotonic=lambda: clock.now))
    monkeypatch.setitem(main.app.dependency_overrides, get_db, override_db)

    try:
        yield sessions, clock
    finally:
        engine.dispose()


def browser():
    return TestClient(main.app, base_url=ORIGIN, follow_redirects=False)


def seed_user(sessions, username, *, password=PASSWORD, is_admin=False):
    with sessions() as db:
        user = models.User(username=username, password_hash=hash_password(password), is_admin=is_admin)
        db.add(user)
        db.commit()
        return user.id


def register_data(client, username="tester", **extra):
    response = client.get("/auth/register")
    assert response.status_code == 200
    inputs = FormInputs(response.text).values
    assert inputs["form_token"]
    return {"form_token": inputs["form_token"], "username": username, "password": PASSWORD, **extra}


def post(client, path, data=None):
    return client.post(path, data=data, headers={"Origin": ORIGIN})


def login(client, username, password=PASSWORD):
    return post(client, "/auth/login", {"username": username, "password": password})


def test_public_register_creates_regular_account_without_contact_fields(public_app):
    sessions, _ = public_app
    client = browser()
    response = client.get("/auth/register")
    assert response.status_code == 200
    inputs = FormInputs(response.text).values
    assert {"username", "password", "form_token", "website"} <= inputs.keys()
    assert not {"email", "phone", "access_code"} & inputs.keys()

    response = post(client, "/auth/register", register_data(client))
    assert response.status_code == 303
    with sessions() as db:
        user = db.scalars(select(models.User)).one()
        assert user.username == "tester"
        assert not user.is_admin
        assert user.password_hash != PASSWORD
        assert verify_password(PASSWORD, user.password_hash)


def test_registration_cooldown_counts_successes_and_accepts_at_boundary(public_app):
    _, clock = public_app
    first, second = browser(), browser()
    assert post(first, "/auth/register", register_data(first)).status_code == 303

    clock.now += 59
    data = register_data(second, "other")
    response = post(second, "/auth/register", data)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"

    clock.now += 1
    response = post(second, "/auth/register", register_data(second, "other"))
    assert response.status_code == 303


@pytest.mark.parametrize("limit", ["capacity", "cooldown"])
def test_parallel_registrations_share_database_limits(public_app, monkeypatch, limit):
    sessions, clock = public_app
    if limit == "capacity":
        seed_user(sessions, "legacy")
        monkeypatch.setattr(public_access, "MAX_ACCOUNTS", 2)
        monkeypatch.setattr(public_access, "REGISTER_INTERVAL", 0)
    ready = Barrier(2, timeout=10)

    def register(username):
        client = browser()
        data = register_data(client, username)
        ready.wait()
        return post(client, "/auth/register", data).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(register, ["first", "second"]))
    assert sorted(statuses) == [303, 429]

    clock.now += 60
    client = browser()
    response = post(client, "/auth/register", register_data(client, "third"))
    assert response.status_code == (429 if limit == "capacity" else 303)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(models.User)) == 2


@pytest.mark.parametrize("invalid", [
    {"form_token": "invalid"},
    {"website": "present"},
    {"access_code": "incorrect"},
    {"password": "too short"},
    {"password": "x" * 129},
])
def test_public_registration_form_guards_reject_without_consuming_slot(public_app, monkeypatch, invalid):
    monkeypatch.setattr(public_access, "REGISTRATION_CODE", "test-only invitation")
    client = browser()
    data = register_data(client, access_code="test-only invitation")
    assert post(client, "/auth/register", {**data, **invalid}).status_code == 400
    assert post(client, "/auth/register", data).status_code == 303


def test_registration_challenge_checks_age_and_browser_cookie(public_app, monkeypatch):
    _, clock = public_app
    monkeypatch.setattr(public_access, "MIN_FORM_AGE", 2)
    client = browser()
    data = register_data(client)
    assert post(client, "/auth/register", data).status_code == 400
    clock.now += 2
    assert post(browser(), "/auth/register", data).status_code == 400
    clock.now += 15 * 60
    assert post(client, "/auth/register", data).status_code == 400
    fresh_data = register_data(client)
    clock.now += 2
    assert post(client, "/auth/register", fresh_data).status_code == 303


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://another-origin.test"}])
def test_public_rejects_mutations_without_expected_origin(public_app, headers):
    sessions, _ = public_app
    seed_user(sessions, "legacy")
    client = browser()
    response = client.post("/auth/login", headers=headers, data={"username": "legacy", "password": PASSWORD})
    assert response.status_code == 403
    assert client.get("/auth/login").status_code == 200


def test_public_allows_local_referrer_when_origin_absent(public_app):
    sessions, _ = public_app
    seed_user(sessions, "legacy")
    client = browser()
    response = client.post(
        "/auth/login",
        headers={"Referer": f"{ORIGIN}/auth/login"},
        data={"username": "legacy", "password": PASSWORD},
    )
    assert response.status_code == 303


def test_public_auth_rejects_unsupported_and_oversized_bodies(public_app):
    client = browser()
    assert client.post("/auth/login", headers={"Origin": ORIGIN}, json={}).status_code == 415
    assert login(client, "legacy", "x" * 4096).status_code == 413


def test_public_login_blocks_repeated_failures(public_app):
    sessions, _ = public_app
    seed_user(sessions, "legacy")
    client = browser()
    for _ in range(20):
        response = login(client, "legacy", "incorrect password")
        if response.status_code == 429:
            break
        assert response.status_code == 400
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert login(client, "legacy").status_code == 429


@pytest.mark.parametrize("invalidate_with", ["logout", "password_change", "id_reuse", "expiry"])
def test_public_session_is_revoked(public_app, invalidate_with):
    sessions, clock = public_app
    user_id = seed_user(sessions, "legacy")
    client = browser()
    assert login(client, "legacy").status_code == 303
    assert client.get("/auth/login").status_code == 303
    old_cookies = dict(client.cookies.items())

    if invalidate_with == "logout":
        assert client.get("/auth/logout").status_code == 405
        assert client.get("/auth/login").status_code == 303
        assert post(client, "/auth/logout").status_code == 303
    elif invalidate_with == "expiry":
        clock.now += public_access.SESSION_LIFETIME
    else:
        with sessions() as db:
            user = db.get(models.User, user_id)
            if invalidate_with == "password_change":
                user.password_hash = hash_password("inne haslo testowe")
            else:
                db.delete(user)
                db.flush()
                db.add(models.User(id=user_id, username="new-user", password_hash=hash_password(PASSWORD)))
            db.commit()

    replay = browser()
    replay.cookies.update(old_cookies)
    assert replay.get("/auth/login").status_code == 200


@pytest.mark.parametrize("existing_default", [False, True])
def test_public_admin_bootstrap_requires_safe_credentials(public_app, monkeypatch, existing_default):
    sessions, _ = public_app
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)
    if existing_default:
        seed_user(sessions, "admin", password="admin", is_admin=True)

    with sessions() as db, pytest.raises(RuntimeError, match="INITIAL_ADMIN_PASSWORD"):
        _ensure_admin(db)

    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", PASSWORD)
    with sessions() as db:
        _ensure_admin(db)
        db.commit()
        admin = db.scalars(select(models.User)).one()
        assert admin.username == "admin" and admin.is_admin
        assert verify_password(PASSWORD, admin.password_hash)
        password_hash = admin.password_hash

    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD")
    with sessions() as db:
        _ensure_admin(db)
        db.commit()
        assert db.scalars(select(models.User)).one().password_hash == password_hash


@pytest.mark.parametrize(
    ("preview", "origin", "trusted_hosts", "secure", "valid"),
    [
        (True, "http://127.0.0.1:8002", ["127.0.0.1"], False, True),
        (True, "http://example.test:8002", ["example.test"], False, False),
        (True, "http://127.0.0.1:8002", ["127.0.0.1", "example.test"], False, False),
        (False, "http://127.0.0.1:8002", ["127.0.0.1"], False, False),
        (False, "https://example.test", ["example.test"], True, True),
    ],
)
def test_local_preview_config_only_accepts_explicit_loopback(monkeypatch, preview, origin, trusted_hosts, secure, valid):
    monkeypatch.setattr(config, "LOCAL_PUBLIC_PREVIEW", preview)
    monkeypatch.setattr(config, "PUBLIC_ORIGIN", origin)
    monkeypatch.setattr(config, "TRUSTED_HOSTS", trusted_hosts)
    monkeypatch.setattr(config, "SESSION_HTTPS_ONLY", secure)
    monkeypatch.setattr(config, "DEBUG", False)
    if valid:
        config.validate_public_config()
    else:
        with pytest.raises(RuntimeError):
            config.validate_public_config()


def test_local_preview_rejects_requests_from_or_to_a_nonloopback_address(public_app, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_PUBLIC_PREVIEW", True)
    origin = "http://127.0.0.1:8002"
    monkeypatch.setattr(config, "PUBLIC_ORIGIN", origin)
    loopback = TestClient(main.app, base_url=origin, client=("127.0.0.1", 50000))
    remote = TestClient(main.app, base_url=origin, client=("192.0.2.1", 50000))
    assert loopback.get("/auth/register").status_code == 200
    assert loopback.get("http://example.test:8002/auth/register").status_code == 403
    assert remote.get("/auth/register").status_code == 403
