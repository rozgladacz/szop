"""Environment-backed configuration for the local SZOP MCP server."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

API_URL_ENV = "SZOP_API_URL"
BEARER_TOKEN_ENV = "SZOP_API_TOKEN"
DEFAULT_API_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class McpConfig:
    """Public API connection settings with a redacted secret representation."""

    api_url: str
    bearer_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> McpConfig:
        """Load settings without logging or embedding the bearer token in errors."""
        source = os.environ if environ is None else environ
        api_url = source.get(API_URL_ENV, DEFAULT_API_URL).strip()
        if not api_url:
            raise ValueError(f"{API_URL_ENV} must not be empty")
        raw_token = source.get(BEARER_TOKEN_ENV)
        bearer_token = raw_token.strip() if raw_token else None
        return cls(api_url=api_url, bearer_token=bearer_token or None)
