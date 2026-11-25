import json
import os
import secrets
import stat
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_or_create_secret(env_name: str, file_name: str) -> str:
    """Return a secret resolving in this order: env var, persisted file, freshly generated.

    Generated secrets are written to ``DATA_DIR/file_name`` with 0600 permissions so
    that the application "just works" after a fresh install with no manual config.
    """

    env_value = os.getenv(env_name)
    if env_value:
        return env_value

    secret_path = DATA_DIR / file_name
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    except OSError:
        pass

    new_secret = secrets.token_urlsafe(48)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = secret_path.with_suffix(secret_path.suffix + ".tmp")
    tmp_path.write_text(new_secret, encoding="utf-8")
    try:
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp_path, secret_path)
    return new_secret


SECRET_KEY = _load_or_create_secret("SECRET_KEY", ".secret_key")
DB_URL = os.getenv("DB_URL", "sqlite:///./data/szop.db")
DEBUG = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"}
LOCAL_COST_ENGINE_ENABLED = os.getenv("LOCAL_COST_ENGINE_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}
UPDATE_REPO_URL = os.getenv("UPDATE_REPO_URL", "https://github.com/rozgladacz/szop")
UPDATE_BRANCH = os.getenv("UPDATE_BRANCH", "main")
UPDATE_REPO_PATH = os.getenv("UPDATE_REPO_PATH", ".")
UPDATE_REF = os.getenv("UPDATE_REF", "")
UPDATE_DOCKERFILE = os.getenv("UPDATE_DOCKERFILE", "Dockerfile")
UPDATE_COMPOSE_FILE = os.getenv("UPDATE_COMPOSE_FILE", "docker-compose.yml")
UPDATE_SERVICE_NAME = os.getenv("UPDATE_SERVICE_NAME", "szop-app")
UPDATE_IMAGE = os.getenv("UPDATE_IMAGE", "ghcr.io/rozgladacz/szop:latest")
UPDATE_WEBHOOK_TOKEN = _load_or_create_secret("UPDATE_WEBHOOK_TOKEN", ".webhook_token")
APP_VERSION = os.getenv("APP_VERSION", "dev")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(DATA_DIR / "backups")))
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "14"))
BACKUP_HOUR = int(os.getenv("BACKUP_HOUR", "3"))

TRUSTED_HOSTS = [
    host.strip()
    for host in os.getenv("TRUSTED_HOSTS", "*").split(",")
    if host.strip()
] or ["*"]

SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() in {"1", "true", "yes"}
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "").strip()
PUBLIC_REGISTRATION_CODE = os.getenv("PUBLIC_REGISTRATION_CODE", "")
LOCAL_PUBLIC_PREVIEW = os.getenv("LOCAL_PUBLIC_PREVIEW", "false").lower() in {"1", "true", "yes"}
LOCAL_PREVIEW_HOST = "127.0.0.1"


def validate_public_config() -> None:
    if not PUBLIC_ORIGIN and not LOCAL_PUBLIC_PREVIEW:
        return
    try:
        origin = urlsplit(PUBLIC_ORIGIN)
        port = origin.port
    except ValueError as exc:
        raise RuntimeError("Invalid PUBLIC_ORIGIN") from exc
    if (not origin.hostname or origin.username is not None
            or PUBLIC_ORIGIN != f"{origin.scheme}://{origin.netloc.lower()}"
            or any(ch.isspace() for ch in origin.netloc)):
        raise RuntimeError("PUBLIC_ORIGIN must be a canonical origin without a trailing slash")
    if LOCAL_PUBLIC_PREVIEW:
        if (origin.scheme != "http" or origin.hostname != LOCAL_PREVIEW_HOST or not port or port == 80
                or DEBUG or SESSION_HTTPS_ONLY or TRUSTED_HOSTS != [LOCAL_PREVIEW_HOST]):
            raise RuntimeError("LOCAL_PUBLIC_PREVIEW requires HTTP on 127.0.0.1 with an explicit port")
    elif origin.scheme != "https" or port == 443:
        raise RuntimeError("PUBLIC_ORIGIN requires HTTPS without the default port in the URL")
    elif DEBUG or not SESSION_HTTPS_ONLY or origin.hostname not in TRUSTED_HOSTS or "*" in TRUSTED_HOSTS:
        raise RuntimeError("PUBLIC_ORIGIN requires DEBUG off, secure cookies and the public host in TRUSTED_HOSTS")
    if not DB_URL.startswith(("sqlite://", "sqlite+")):
        raise RuntimeError("Public registration requires SQLite")


def _load_json_list(env_key: str, default: list) -> list:
    raw_value = os.getenv(env_key)
    if not raw_value:
        return default
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, list) else default


COMMAND_RUNNER_ALLOWED_COMMANDS = _load_json_list("COMMAND_RUNNER_ALLOWED_COMMANDS", [])
COMMAND_RUNNER_SEQUENCE = _load_json_list("COMMAND_RUNNER_SEQUENCE", [])
COMMAND_RUNNER_WORKDIR = Path(os.getenv("COMMAND_RUNNER_WORKDIR", "."))
