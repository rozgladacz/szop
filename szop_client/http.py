"""HTTP client for the public B4 battle API.

The client keeps no mutable battle-state or sequence cache. Mutating one action
first reads the current checkpoint sequence, then sends it as an explicit
optimistic precondition and consumes the returned state/event delta.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import TYPE_CHECKING, Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.battle_protocol import (
    ACTIVATION_PROTOCOL_VERSION_V1,
    validate_activation_protocol_version,
)
from app.services.engine.action_codec import (
    ActionCodecError,
    action_from_json,
    action_to_json,
)
from app.services.engine.actions import Action
from app.services.engine.events import BattleEvent, json_to_event
from app.services.engine.state import BattleState
from app.services.engine.state_codec import battle_state_from_json
from szop_client.types import (
    BattleActionProposal,
    BattleInviteMetadata,
    BattleReplayResult,
    BattleStateCheckpoint,
    SimulationSummary,
)
from szop_client.wire import validate_event_delta

if TYPE_CHECKING:
    from szop_client.protocol import ContinuationFn

RULE_LOOKUP_SCHEMA = "szop.lookup_rule/v1"
ABILITY_EXPLANATION_SCHEMA = "szop.explain_ability/v1"
RULES_SEARCH_SCHEMA = "szop.search_rules/v1"
LOADOUT_VALIDATION_SCHEMA = "szop.validate_loadout/v1"
SCORE_LIST_SCHEMA = "szop.score_list/v1"
EXPLOIT_CANDIDATES_SCHEMA = "szop.find_exploit_candidates/v1"
REFERENCE_API_VERSION = 1
LOADOUT_VALIDATION_VERSION = 1
SCORE_LIST_VERSION = 1
EXPLOIT_CANDIDATES_VERSION = 1
RULES_SEARCH_STRATEGY = "hybrid_weighted_rrf"
RULE_SOURCE = "SZOP_Rozjemca.md"
ABILITY_SOURCE = "app.data.abilities"
RULE_SEARCH_SOURCES = frozenset({"SZOP_Rozjemca.md", "SZOP_Zdolnosci.md"})
MAX_RULE_QUERY_LENGTH = 200
MAX_RULE_RESULTS = 10
MAX_RULE_TEXT_LENGTH = 4000
MAX_RULE_CHILDREN = 20
MAX_ABILITY_QUERY_LENGTH = 100
MAX_RULE_SEARCH_TEXT_LENGTH = 1200
MAX_LOADOUT_COUNT = 100
RAG_SEARCH_TIMEOUT = 30.0
MAX_SCORE_GAMES_PER_OPPONENT = 10
MAX_SCORE_OPPONENTS = 10
MAX_SCORE_TOTAL_GAMES = 50
MIN_SCORE_SEED = -(2**31)
MAX_SCORE_SEED = 2**31 - 1
SCORE_LIST_TIMEOUT = 120.0
SCORE_LIST_BOTS = (
    "priority",
    "priority3",
    "claude_v3",
    "random",
    "greedy",
    "priority2",
    "claude_v1",
)
SCORE_LIST_MAPS = frozenset({"standard_a", "lustrzana_a", "symetryczna_a"})
MIN_EXPLOIT_ROSTERS = 2
MAX_EXPLOIT_ROSTERS = 7
MAX_EXPLOIT_GAMES_PER_PAIR = 3
MAX_EXPLOIT_PAIRS = 21
MAX_EXPLOIT_TOTAL_GAMES = 50


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """Transport-neutral request passed to injectable transports."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None
    timeout: float


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Transport-neutral HTTP response returned by injectable transports."""

    status_code: int
    body: bytes


@dataclass(frozen=True, slots=True)
class BattleMetadata:
    """Participant-scoped metadata returned by `GET /battles/{id}`."""

    battle_id: int
    p1_user_id: int | None
    p2_user_id: int | None
    p1_roster_id: int | None
    p2_roster_id: int | None
    winner_user_id: int | None
    current_round: int
    rng_seed: int
    status: str
    latest_sequence: int
    activation_protocol_version: int

    def __post_init__(self) -> None:
        validate_activation_protocol_version(self.activation_protocol_version)


Transport = Callable[[HttpRequest], HttpResponse]


class HttpClientError(RuntimeError):
    """HTTP API returned an error status or malformed payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HttpClientTransportError(HttpClientError):
    """HTTP transport failed before a valid API response was received."""


class HttpClient:
    """HTTP client for checkpointed single-action play and sandbox operations."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized:
            raise ValueError("base_url must not be empty")
        self._base_url = normalized
        self._token = token
        self._timeout = timeout
        self._transport = transport or _urlopen_transport

    def create_battle(
        self,
        *,
        p1_roster_id: int,
        p2_roster_id: int,
        rng_seed: int = 0,
        initiative_player: int = 0,
        activation_protocol_version: int = ACTIVATION_PROTOCOL_VERSION_V1,
    ) -> BattleMetadata:
        """Create a sandbox battle via `POST /battles` and return its metadata."""
        protocol_version = validate_activation_protocol_version(
            activation_protocol_version
        )
        request_body = {
            "p1_roster_id": p1_roster_id,
            "p2_roster_id": p2_roster_id,
            "rng_seed": rng_seed,
            "initiative_player": initiative_player,
        }
        if protocol_version != ACTIVATION_PROTOCOL_VERSION_V1:
            request_body["activation_protocol_version"] = protocol_version
        error_label = "POST create battle"
        payload = self._request_json(
            "POST",
            "/battles",
            {},
            json_body=request_body,
            error_label=error_label,
        )
        return _metadata_from_payload(payload, error_label=error_label)

    def create_battle_invite(
        self,
        *,
        roster_id: int,
        to_user_id: int | None = None,
        scenario: str = "lustrzana_a",
        expires_in_hours: int = 24,
        activation_protocol_version: int = ACTIVATION_PROTOCOL_VERSION_V1,
    ) -> BattleInviteMetadata:
        """Create one direct or open pending invite with no follow-up request."""
        _validate_positive_id(roster_id, name="roster_id")
        if to_user_id is not None:
            _validate_positive_id(to_user_id, name="to_user_id")
        if not isinstance(scenario, str) or not scenario.strip():
            raise ValueError("scenario must be a non-empty string")
        if len(scenario) > 100:
            raise ValueError("scenario must contain at most 100 characters")
        if type(expires_in_hours) is not int or not 1 <= expires_in_hours <= 168:
            raise ValueError("expires_in_hours must be an int between 1 and 168")
        protocol_version = validate_activation_protocol_version(
            activation_protocol_version
        )
        request_body = {
            "to_user_id": to_user_id,
            "roster_id": roster_id,
            "scenario": scenario,
            "expires_in_hours": expires_in_hours,
        }
        if protocol_version != ACTIVATION_PROTOCOL_VERSION_V1:
            request_body["activation_protocol_version"] = protocol_version

        error_label = "POST create battle invite"
        payload = self._request_json(
            "POST",
            "/battles/invite",
            {},
            json_body=request_body,
            error_label=error_label,
        )
        return _battle_invite_metadata_from_payload(
            payload,
            error_label=error_label,
        )

    def accept_battle_invite(
        self,
        invite_id: int,
        *,
        roster_id: int,
    ) -> BattleMetadata:
        """Accept one invite and decode the returned existing battle contract."""
        _validate_positive_id(invite_id, name="invite_id")
        _validate_positive_id(roster_id, name="roster_id")
        error_label = "POST accept battle invite"
        payload = self._request_json(
            "POST",
            f"/battles/invite/{invite_id}/accept",
            {},
            json_body={"roster_id": roster_id},
            error_label=error_label,
        )
        return _metadata_from_payload(payload, error_label=error_label)

    def simulate_roster_ids(
        self,
        *,
        p1_roster_id: int,
        p2_roster_id: int,
        bot: str = "priority",
        n: int = 10,
        seed: int = 0,
        map_name: str = "lustrzana_a",
    ) -> SimulationSummary:
        """Run sandbox simulation via `POST /battles/simulate`."""
        if n <= 0:
            raise ValueError(f"n musi byc > 0, jest {n}")
        error_label = "POST battle simulation"
        payload = self._request_json(
            "POST",
            "/battles/simulate",
            {},
            json_body={
                "p1_roster_id": p1_roster_id,
                "p2_roster_id": p2_roster_id,
                "games": n,
                "bot": bot,
                "seed": seed,
                "map_name": map_name,
            },
            error_label=error_label,
        )
        return _simulation_summary_from_payload(payload, error_label=error_label)

    def get_battle_metadata(self, battle_id: int) -> BattleMetadata:
        """Return participant-scoped battle metadata from the B4 API."""
        error_label = "GET battle metadata"
        payload = self._get_json(
            f"/battles/{battle_id}",
            {},
            error_label=error_label,
        )
        return _metadata_from_payload(
            payload,
            error_label=error_label,
            expected_battle_id=battle_id,
        )

    def get_events(self, battle_id: int, since: int = 0) -> tuple[BattleEvent, ...]:
        """Return battle events with `sequence > since` from the B4 polling API."""
        if type(since) is not int or since < 0:
            raise ValueError("since must be an int >= 0")
        error_label = "GET battle events"
        payload = self._get_json(
            f"/battles/{battle_id}/events",
            {"since": since},
            error_label=error_label,
        )
        if not isinstance(payload, dict):
            raise HttpClientError(f"{error_label} returned malformed payload")
        _ensure_expected_battle_id(
            payload,
            battle_id,
            error_label=error_label,
        )
        events = payload.get("events")
        if not isinstance(events, list):
            raise HttpClientError("GET battle events returned malformed payload")
        try:
            return validate_event_delta(
                (_event_from_public_payload(item) for item in events),
                since=since,
            )
        except ValueError as exc:
            raise HttpClientError(
                "GET battle events returned malformed payload"
            ) from exc

    def get_state_checkpoint(self, battle_id: int) -> BattleStateCheckpoint:
        """Return state and sequence from the same versioned ``GET /state``."""
        error_label = "GET battle state"
        payload = self._get_json(
            f"/battles/{battle_id}/state",
            {},
            error_label=error_label,
        )
        if not isinstance(payload, dict):
            raise HttpClientError(f"{error_label} returned malformed payload")
        _ensure_expected_battle_id(payload, battle_id, error_label=error_label)
        try:
            sequence_at = _required_int(payload, "sequence_at")
            if sequence_at < 0:
                raise TypeError("sequence_at")
            schema = _required_str(payload, "schema")
            version = _required_int(payload, "version")
            state = battle_state_from_json(
                {
                    "schema": schema,
                    "version": version,
                    "state": payload["state"],
                }
            )
            return BattleStateCheckpoint(
                battle_id=battle_id,
                sequence_at=sequence_at,
                schema=schema,
                version=version,
                state=state,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HttpClientError(
                f"{error_label} returned malformed payload"
            ) from exc

    def get_state(self, battle_id: int) -> BattleState:
        """Return the participant-scoped current domain state of a battle."""
        return self.get_state_checkpoint(battle_id).state

    def replay_battle(self, battle_id: int) -> BattleReplayResult:
        """Reconstruct and decode one server-verified durable battle state."""
        _validate_positive_id(battle_id, name="battle_id")
        error_label = "POST battle replay"
        payload = self._request_json(
            "POST",
            f"/battles/{battle_id}/replay",
            {},
            json_body=None,
            error_label=error_label,
        )
        return _battle_replay_result_from_payload(
            payload,
            expected_battle_id=battle_id,
            error_label=error_label,
        )

    def lookup_rule(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        """Look up canonical rule points through the public read-only API."""
        normalized_query = _normalize_reference_query(
            query,
            max_length=MAX_RULE_QUERY_LENGTH,
        )
        if type(limit) is not int or not 1 <= limit <= MAX_RULE_RESULTS:
            raise ValueError(
                f"limit must be an int between 1 and {MAX_RULE_RESULTS}"
            )
        error_label = "GET rule lookup"
        payload = self._get_json(
            "/rules/lookup",
            {"query": normalized_query, "limit": limit},
            error_label=error_label,
        )
        return _rule_lookup_from_payload(
            payload,
            expected_query=normalized_query,
            requested_limit=limit,
            error_label=error_label,
        )

    def search_rules(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        """Search canonical rules semantically through the scoped hybrid API."""
        normalized_query = _normalize_reference_query(
            query,
            max_length=MAX_RULE_QUERY_LENGTH,
        )
        if type(limit) is not int or not 1 <= limit <= MAX_RULE_RESULTS:
            raise ValueError(
                f"limit must be an int between 1 and {MAX_RULE_RESULTS}"
            )
        error_label = "POST rules search"
        payload = self._request_json(
            "POST",
            "/rules/search",
            {},
            json_body={"query": normalized_query, "limit": limit},
            error_label=error_label,
            timeout=max(self._timeout, RAG_SEARCH_TIMEOUT),
        )
        return _rules_search_from_payload(
            payload,
            expected_query=normalized_query,
            requested_limit=limit,
            error_label=error_label,
        )

    def validate_loadout(
        self,
        unit_id: int,
        loadout: dict[str, Any],
        count: int = 1,
    ) -> dict[str, Any]:
        """Validate and quote one global catalog unit without persisting it."""
        if type(unit_id) is not int or unit_id < 1:
            raise ValueError("unit_id must be an int >= 1")
        if type(count) is not int or not 1 <= count <= MAX_LOADOUT_COUNT:
            raise ValueError(
                f"count must be an int between 1 and {MAX_LOADOUT_COUNT}"
            )
        canonical_loadout = _canonical_json_object(loadout, label="loadout")
        error_label = "POST loadout validation"
        payload = self._request_json(
            "POST",
            f"/units/{unit_id}/validate-loadout",
            {},
            json_body={"loadout": canonical_loadout, "count": count},
            error_label=error_label,
        )
        return _loadout_validation_from_payload(
            payload,
            expected_unit_id=unit_id,
            expected_count=count,
            error_label=error_label,
        )

    def score_list(
        self,
        roster_id: int,
        *,
        games_per_opponent: int = 3,
        bot: str = "priority",
        seed: int = 0,
        map_name: str = "lustrzana_a",
        opponent_roster_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Score one owned roster through one bounded public API request."""
        if type(roster_id) is not int or roster_id < 1:
            raise ValueError("roster_id must be an int >= 1")
        if type(games_per_opponent) is not int or not (
            1 <= games_per_opponent <= MAX_SCORE_GAMES_PER_OPPONENT
        ):
            raise ValueError(
                "games_per_opponent must be an int between 1 and "
                f"{MAX_SCORE_GAMES_PER_OPPONENT}"
            )
        if not isinstance(bot, str) or bot.lower() not in SCORE_LIST_BOTS:
            raise ValueError("bot must be an allowed lightweight simulation bot")
        normalized_bot = bot.lower()
        if type(seed) is not int or not MIN_SCORE_SEED <= seed <= MAX_SCORE_SEED:
            raise ValueError("seed must be a safe signed 32-bit int")
        if not isinstance(map_name, str) or map_name.lower() not in SCORE_LIST_MAPS:
            raise ValueError("map_name must be an allowed simulation map")
        normalized_map = map_name.lower()
        normalized_opponents: list[int] | None = None
        if opponent_roster_ids is not None:
            if type(opponent_roster_ids) is not list:
                raise ValueError("opponent_roster_ids must be a list or None")
            if (
                len(opponent_roster_ids) > MAX_SCORE_OPPONENTS
                or any(type(item) is not int or item < 1 for item in opponent_roster_ids)
                or len(set(opponent_roster_ids)) != len(opponent_roster_ids)
                or roster_id in opponent_roster_ids
                or games_per_opponent * len(opponent_roster_ids)
                > MAX_SCORE_TOTAL_GAMES
            ):
                raise ValueError("opponent_roster_ids define an invalid score workload")
            normalized_opponents = sorted(opponent_roster_ids)

        request_body: dict[str, Any] = {
            "games_per_opponent": games_per_opponent,
            "bot": normalized_bot,
            "seed": seed,
            "map_name": normalized_map,
        }
        if normalized_opponents is not None:
            request_body["opponent_roster_ids"] = normalized_opponents

        error_label = "POST roster score"
        payload = self._request_json(
            "POST",
            f"/rosters/{roster_id}/score",
            {},
            json_body=request_body,
            error_label=error_label,
            timeout=max(self._timeout, SCORE_LIST_TIMEOUT),
        )
        return _score_list_from_payload(
            payload,
            expected_roster_id=roster_id,
            expected_games_per_opponent=games_per_opponent,
            expected_bot=normalized_bot,
            expected_seed=seed,
            expected_map_name=normalized_map,
            expected_opponent_ids=normalized_opponents,
            error_label=error_label,
        )

    def find_exploit_candidates(
        self,
        army_id: int,
        *,
        games_per_pair: int = 2,
        bot: str = "priority",
        seed: int = 0,
        map_name: str = "lustrzana_a",
        roster_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Rank one bounded owner-scoped army field through one API request."""
        if type(army_id) is not int or not 1 <= army_id <= 2**63 - 1:
            raise ValueError("army_id must be a safe positive database int")
        if type(games_per_pair) is not int or not (
            1 <= games_per_pair <= MAX_EXPLOIT_GAMES_PER_PAIR
        ):
            raise ValueError(
                "games_per_pair must be an int between 1 and "
                f"{MAX_EXPLOIT_GAMES_PER_PAIR}"
            )
        if not isinstance(bot, str) or bot.lower() not in SCORE_LIST_BOTS:
            raise ValueError("bot must be an allowed lightweight simulation bot")
        normalized_bot = bot.lower()
        if type(seed) is not int or not MIN_SCORE_SEED <= seed <= MAX_SCORE_SEED:
            raise ValueError("seed must be a safe signed 32-bit int")
        if not isinstance(map_name, str) or map_name.lower() not in SCORE_LIST_MAPS:
            raise ValueError("map_name must be an allowed simulation map")
        normalized_map = map_name.lower()
        normalized_rosters: list[int] | None = None
        if roster_ids is not None:
            if type(roster_ids) is not list:
                raise ValueError("roster_ids must be a list or None")
            pair_count = len(roster_ids) * (len(roster_ids) - 1) // 2
            if (
                not MIN_EXPLOIT_ROSTERS <= len(roster_ids) <= MAX_EXPLOIT_ROSTERS
                or any(
                    type(item) is not int or not 1 <= item <= 2**63 - 1
                    for item in roster_ids
                )
                or len(set(roster_ids)) != len(roster_ids)
                or pair_count > MAX_EXPLOIT_PAIRS
                or pair_count * games_per_pair > MAX_EXPLOIT_TOTAL_GAMES
            ):
                raise ValueError("roster_ids define an invalid exploit workload")
            normalized_rosters = sorted(roster_ids)

        request_body: dict[str, Any] = {
            "games_per_pair": games_per_pair,
            "bot": normalized_bot,
            "seed": seed,
            "map_name": normalized_map,
        }
        if normalized_rosters is not None:
            request_body["roster_ids"] = normalized_rosters

        error_label = "POST exploit candidate search"
        payload = self._request_json(
            "POST",
            f"/armies/{army_id}/exploit-candidates",
            {},
            json_body=request_body,
            error_label=error_label,
            timeout=max(self._timeout, SCORE_LIST_TIMEOUT),
        )
        return _exploit_candidates_from_payload(
            payload,
            expected_army_id=army_id,
            expected_games_per_pair=games_per_pair,
            expected_bot=normalized_bot,
            expected_seed=seed,
            expected_map_name=normalized_map,
            expected_roster_ids=normalized_rosters,
            error_label=error_label,
        )

    def explain_ability(self, query: str) -> dict[str, Any]:
        """Explain one canonical ability by slug or normalized display name."""
        normalized_query = _normalize_reference_query(
            query,
            max_length=MAX_ABILITY_QUERY_LENGTH,
        )
        error_label = "GET ability explanation"
        payload = self._get_json(
            "/abilities/explain",
            {"query": normalized_query},
            error_label=error_label,
        )
        return _ability_explanation_from_payload(
            payload,
            expected_query=normalized_query,
            error_label=error_label,
        )

    def propose_battle_action(
        self,
        battle_id: int,
        *,
        expected_sequence: int,
        action: Mapping[str, Any],
        summary: str,
    ) -> BattleActionProposal:
        """Create a validated consent request without mutating the battle."""
        if type(battle_id) is not int or battle_id < 1:
            raise ValueError("battle_id must be an int >= 1")
        if type(expected_sequence) is not int or expected_sequence < 0:
            raise ValueError("expected_sequence must be an int >= 0")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string")
        try:
            canonical_action = action_to_json(action_from_json(action))
        except (ActionCodecError, TypeError, ValueError) as exc:
            raise ValueError("action must be a valid szop.action/v1 payload") from exc

        normalized_summary = summary.strip()
        error_label = "POST battle action proposal"
        payload = self._request_json(
            "POST",
            "/agent_proposals/battle-actions",
            {},
            json_body={
                "battle_id": battle_id,
                "expected_sequence": expected_sequence,
                "action": canonical_action,
                "summary": normalized_summary,
            },
            error_label=error_label,
        )
        return _battle_action_proposal_from_payload(
            payload,
            expected_battle_id=battle_id,
            expected_sequence=expected_sequence,
            expected_action=canonical_action,
            expected_summary=normalized_summary,
            error_label=error_label,
        )

    def take_action(
        self,
        battle_id: int,
        action: Action,
        *,
        continuation: "ContinuationFn | None" = None,
    ) -> tuple[BattleState, tuple[BattleEvent, ...]]:
        """Persist one action with a freshly read optimistic sequence guard.

        Callback continuations are process-local behavior and cannot cross the
        HTTP boundary in this single-action API slice.
        """
        if continuation is not None:
            raise ValueError(
                "HttpClient.take_action does not support continuation callbacks"
            )
        wire_action = action_to_json(action)
        expected_sequence = self.get_state_checkpoint(battle_id).sequence_at
        error_label = "POST battle action"
        payload = self._request_json(
            "POST",
            f"/battles/{battle_id}/actions",
            {},
            json_body={
                "expected_sequence": expected_sequence,
                "action": wire_action,
            },
            error_label=error_label,
        )
        return _action_result_from_payload(
            payload,
            expected_battle_id=battle_id,
            expected_previous_sequence=expected_sequence,
            error_label=error_label,
        )

    def _get_json(
        self,
        path: str,
        query: dict[str, Any],
        *,
        error_label: str,
    ) -> Any:
        return self._request_json(
            "GET", path, query, json_body=None, error_label=error_label
        )

    def _request_json(
        self,
        method: str,
        path: str,
        query: dict[str, Any],
        *,
        json_body: dict[str, Any] | None,
        error_label: str,
        timeout: float | None = None,
    ) -> Any:
        body = (
            None
            if json_body is None
            else json.dumps(
                json_body,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        response = self._transport(
            HttpRequest(
                method=method,
                url=self._url(path, query),
                headers=self._headers(with_json_body=json_body is not None),
                body=body,
                timeout=self._timeout if timeout is None else timeout,
            )
        )
        if not 200 <= response.status_code < 300:
            raise HttpClientError(
                f"{error_label} failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return _decode_json(response.body)

    def _headers(self, *, with_json_body: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if with_json_body:
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _url(self, path: str, query: dict[str, Any]) -> str:
        if not query:
            return f"{self._base_url}{path}"
        return f"{self._base_url}{path}?{urlencode(query)}"


def _decode_json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpClientError("HTTP response body is not valid JSON") from exc


def _normalize_reference_query(query: str, *, max_length: int) -> str:
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"query must contain at most {max_length} characters")
    return normalized


def _validate_positive_id(value: Any, *, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be an int >= 1")
    return value


def _is_strict_json_value(value: Any) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_strict_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            type(key) is str and _is_strict_json_value(item)
            for key, item in value.items()
        )
    return False


def _canonical_json_object(value: Any, *, label: str) -> dict[str, Any]:
    try:
        if type(value) is not dict or not _is_strict_json_value(value):
            raise TypeError(label)
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            )
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError(f"{label} must be a finite JSON object") from exc


def _rule_lookup_from_payload(
    payload: Any,
    *,
    expected_query: str,
    requested_limit: int,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        source = _required_str(payload, "source")
        query = _required_str(payload, "query")
        normalized_query = _bounded_required_str(
            payload,
            "normalized_query",
            max_length=MAX_RULE_QUERY_LENGTH,
        )
        mode = _required_str(payload, "mode")
        raw_matches = payload["matches"]
        if (
            schema != RULE_LOOKUP_SCHEMA
            or version != REFERENCE_API_VERSION
            or source != RULE_SOURCE
            or query != expected_query
            or mode not in {"reference", "search"}
            or not isinstance(raw_matches, list)
            or len(raw_matches) > requested_limit
        ):
            raise TypeError("rule lookup envelope")
        matches = [
            _rule_match_from_payload(item, mode=mode)
            for item in raw_matches
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "source": source,
        "query": query,
        "normalized_query": normalized_query,
        "mode": mode,
        "matches": matches,
    }


def _rules_search_from_payload(
    payload: Any,
    *,
    expected_query: str,
    requested_limit: int,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        _require_exact_keys(
            payload,
            {"schema", "version", "query", "strategy", "count", "results"},
        )
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        query = _bounded_required_str(
            payload,
            "query",
            max_length=MAX_RULE_QUERY_LENGTH,
        )
        strategy = _required_str(payload, "strategy")
        count = _required_int(payload, "count")
        raw_results = payload["results"]
        if (
            schema != RULES_SEARCH_SCHEMA
            or version != REFERENCE_API_VERSION
            or query != expected_query
            or strategy != RULES_SEARCH_STRATEGY
            or count < 0
            or count > requested_limit
            or not isinstance(raw_results, list)
            or len(raw_results) != count
        ):
            raise TypeError("rules search envelope")
        results = [
            _rules_search_result_from_payload(item, expected_rank=rank)
            for rank, item in enumerate(raw_results, start=1)
        ]
        if len({result["chunk_id"] for result in results}) != count:
            raise TypeError("rules search chunk IDs")
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "query": query,
        "strategy": strategy,
        "count": count,
        "results": results,
    }


def _loadout_validation_from_payload(
    payload: Any,
    *,
    expected_unit_id: int,
    expected_count: int,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        _require_exact_keys(
            payload,
            {
                "schema",
                "version",
                "unit_id",
                "unit_name",
                "count",
                "mode",
                "sections",
                "passive",
                "cost",
                "has_issues",
            },
        )
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        unit_id = _required_int(payload, "unit_id")
        unit_name = _bounded_required_str(payload, "unit_name", max_length=120)
        count = _required_int(payload, "count")
        mode = _loadout_mode_from_payload(payload["mode"])
        sections = _loadout_sections_from_payload(payload["sections"])
        passive = _loadout_passive_from_payload(payload["passive"])
        cost = _loadout_cost_from_payload(payload["cost"])
        has_issues = payload["has_issues"]
        expected_issues = bool(
            mode["clamped"]
            or passive["rejected"]
            or any(section["rejected"] or section["clamped"] for section in sections)
        )
        if (
            schema != LOADOUT_VALIDATION_SCHEMA
            or version != LOADOUT_VALIDATION_VERSION
            or unit_id != expected_unit_id
            or count != expected_count
            or not 1 <= count <= MAX_LOADOUT_COUNT
            or type(has_issues) is not bool
            or has_issues is not expected_issues
        ):
            raise TypeError("loadout validation envelope")
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "unit_id": unit_id,
        "unit_name": unit_name,
        "count": count,
        "mode": mode,
        "sections": sections,
        "passive": passive,
        "cost": cost,
        "has_issues": has_issues,
    }


def _score_list_from_payload(
    payload: Any,
    *,
    expected_roster_id: int,
    expected_games_per_opponent: int,
    expected_bot: str,
    expected_seed: int,
    expected_map_name: str,
    expected_opponent_ids: list[int] | None,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        _require_exact_keys(
            payload,
            {
                "schema",
                "version",
                "target",
                "parameters",
                "results",
                "aggregate",
                "cost_signals",
            },
        )
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        target = _score_roster_info_from_payload(payload["target"])
        parameters = _score_parameters_from_payload(payload["parameters"])
        raw_results = payload["results"]
        if (
            schema != SCORE_LIST_SCHEMA
            or version != SCORE_LIST_VERSION
            or target["id"] != expected_roster_id
            or parameters["games_per_opponent"] != expected_games_per_opponent
            or parameters["bot"] != expected_bot
            or parameters["seed"] != expected_seed
            or parameters["map_name"] != expected_map_name
            or not isinstance(raw_results, list)
            or len(raw_results) > MAX_SCORE_OPPONENTS
        ):
            raise TypeError("score list envelope")
        parameter_ids = parameters["opponent_roster_ids"]
        if expected_opponent_ids is not None and parameter_ids != expected_opponent_ids:
            raise TypeError("score list explicit opponent IDs")
        results = [
            _score_result_from_payload(
                item,
                expected_games=expected_games_per_opponent,
            )
            for item in raw_results
        ]
        result_ids = [result["opponent"]["id"] for result in results]
        if (
            result_ids != sorted(result_ids)
            or len(set(result_ids)) != len(result_ids)
            or expected_roster_id in result_ids
            or parameter_ids != result_ids
        ):
            raise TypeError("score result ordering")

        aggregate = _score_summary_from_payload(payload["aggregate"])
        _assert_score_summary_matches(aggregate, results)

        raw_signals = payload["cost_signals"]
        if not isinstance(raw_signals, dict):
            raise TypeError("score cost signals")
        _require_exact_keys(raw_signals, {"vs_cheaper", "vs_pricier"})
        cost_signals = {
            "vs_cheaper": _score_summary_from_payload(raw_signals["vs_cheaper"]),
            "vs_pricier": _score_summary_from_payload(raw_signals["vs_pricier"]),
        }
        _assert_score_summary_matches(
            cost_signals["vs_cheaper"],
            [
                result
                for result in results
                if result["opponent"]["points"] < target["points"]
            ],
        )
        _assert_score_summary_matches(
            cost_signals["vs_pricier"],
            [
                result
                for result in results
                if result["opponent"]["points"] > target["points"]
            ],
        )
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "target": target,
        "parameters": parameters,
        "results": results,
        "aggregate": aggregate,
        "cost_signals": cost_signals,
    }


def _exploit_candidates_from_payload(
    payload: Any,
    *,
    expected_army_id: int,
    expected_games_per_pair: int,
    expected_bot: str,
    expected_seed: int,
    expected_map_name: str,
    expected_roster_ids: list[int] | None,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        _require_exact_keys(
            payload,
            {"schema", "version", "army", "parameters", "candidates", "pairs"},
        )
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        army = _exploit_army_from_payload(payload["army"])
        parameters = _exploit_parameters_from_payload(payload["parameters"])
        roster_ids = parameters["roster_ids"]
        if (
            schema != EXPLOIT_CANDIDATES_SCHEMA
            or version != EXPLOIT_CANDIDATES_VERSION
            or army["id"] != expected_army_id
            or army["roster_count"] != len(roster_ids)
            or parameters["games_per_pair"] != expected_games_per_pair
            or parameters["bot"] != expected_bot
            or parameters["seed"] != expected_seed
            or parameters["map_name"] != expected_map_name
            or (expected_roster_ids is not None and roster_ids != expected_roster_ids)
        ):
            raise TypeError("exploit candidate envelope")

        raw_candidates = payload["candidates"]
        raw_pairs = payload["pairs"]
        if (
            not isinstance(raw_candidates, list)
            or len(raw_candidates) != len(roster_ids)
            or not isinstance(raw_pairs, list)
        ):
            raise TypeError("exploit candidate collections")
        candidate_games = (len(roster_ids) - 1) * expected_games_per_pair
        candidates = [
            _exploit_candidate_from_payload(
                item,
                expected_rank=rank,
                expected_games=candidate_games,
                expected_army_name=army["name"],
            )
            for rank, item in enumerate(raw_candidates, start=1)
        ]
        candidate_ids = [candidate["roster_id"] for candidate in candidates]
        if len(set(candidate_ids)) != len(candidate_ids) or set(candidate_ids) != set(
            roster_ids
        ):
            raise TypeError("exploit candidate roster IDs")

        expected_pair_ids = list(combinations(roster_ids, 2))
        if (
            len(expected_pair_ids) > MAX_EXPLOIT_PAIRS
            or len(expected_pair_ids) * expected_games_per_pair
            > MAX_EXPLOIT_TOTAL_GAMES
            or len(raw_pairs) != len(expected_pair_ids)
        ):
            raise TypeError("exploit candidate workload")
        pairs = [
            _exploit_pair_from_payload(
                item,
                expected_ids=pair_ids,
                expected_games=expected_games_per_pair,
            )
            for item, pair_ids in zip(raw_pairs, expected_pair_ids, strict=True)
        ]
        _assert_exploit_candidate_consistency(candidates, pairs)
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "army": army,
        "parameters": parameters,
        "candidates": candidates,
        "pairs": pairs,
    }


def _exploit_army_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("exploit army")
    _require_exact_keys(payload, {"id", "name", "roster_count"})
    army_id = _required_int(payload, "id")
    name = _bounded_required_str(payload, "name", max_length=120)
    roster_count = _required_int(payload, "roster_count")
    if army_id < 1 or not MIN_EXPLOIT_ROSTERS <= roster_count <= MAX_EXPLOIT_ROSTERS:
        raise TypeError("exploit army")
    return {"id": army_id, "name": name, "roster_count": roster_count}


def _exploit_parameters_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("exploit parameters")
    _require_exact_keys(
        payload,
        {"games_per_pair", "bot", "seed", "map_name", "roster_ids"},
    )
    games = _required_int(payload, "games_per_pair")
    bot = _required_str(payload, "bot")
    seed = _required_int(payload, "seed")
    map_name = _required_str(payload, "map_name")
    roster_ids = payload["roster_ids"]
    if (
        not 1 <= games <= MAX_EXPLOIT_GAMES_PER_PAIR
        or bot not in SCORE_LIST_BOTS
        or not MIN_SCORE_SEED <= seed <= MAX_SCORE_SEED
        or map_name not in SCORE_LIST_MAPS
        or not isinstance(roster_ids, list)
        or not MIN_EXPLOIT_ROSTERS <= len(roster_ids) <= MAX_EXPLOIT_ROSTERS
        or any(
            type(item) is not int or not 1 <= item <= 2**63 - 1
            for item in roster_ids
        )
        or roster_ids != sorted(roster_ids)
        or len(set(roster_ids)) != len(roster_ids)
    ):
        raise TypeError("exploit parameters")
    pair_count = len(roster_ids) * (len(roster_ids) - 1) // 2
    if pair_count > MAX_EXPLOIT_PAIRS or pair_count * games > MAX_EXPLOIT_TOTAL_GAMES:
        raise TypeError("exploit parameters")
    return {
        "games_per_pair": games,
        "bot": bot,
        "seed": seed,
        "map_name": map_name,
        "roster_ids": list(roster_ids),
    }


def _exploit_candidate_from_payload(
    payload: Any,
    *,
    expected_rank: int,
    expected_games: int,
    expected_army_name: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("exploit candidate")
    _require_exact_keys(
        payload,
        {
            "rank",
            "roster_id",
            "name",
            "army",
            "points",
            "composition",
            "games",
            "wins",
            "losses",
            "draws",
            "rounds",
            "win_rate",
            "loss_rate",
            "draw_rate",
            "avg_rounds",
            "exploit_score",
        },
    )
    rank = _required_int(payload, "rank")
    roster_id = _required_int(payload, "roster_id")
    name = _bounded_required_str(payload, "name", max_length=120)
    army = _bounded_required_str(payload, "army", max_length=120)
    points = _required_finite_float(payload, "points")
    composition = _required_str(payload, "composition")
    games = _required_int(payload, "games")
    wins = _required_int(payload, "wins")
    losses = _required_int(payload, "losses")
    draws = _required_int(payload, "draws")
    rounds = _required_int(payload, "rounds")
    win_rate = _required_finite_float(payload, "win_rate")
    loss_rate = _required_finite_float(payload, "loss_rate")
    draw_rate = _required_finite_float(payload, "draw_rate")
    avg_rounds = _required_finite_float(payload, "avg_rounds")
    exploit_score = _required_finite_float(payload, "exploit_score")
    expected_exploit = win_rate / points * 100.0 if points > 0.0 else 0.0
    if (
        rank != expected_rank
        or roster_id < 1
        or army != expected_army_name
        or points < 0.0
        or points > 1_000_000_000_000.0
        or len(composition) > 4000
        or games != expected_games
        or min(wins, losses, draws, rounds) < 0
        or wins + losses + draws != games
        or rounds > games * 100
        or not all(0.0 <= rate <= 1.0 for rate in (win_rate, loss_rate, draw_rate))
        or not _score_float_matches(win_rate, wins / games)
        or not _score_float_matches(loss_rate, losses / games)
        or not _score_float_matches(draw_rate, draws / games)
        or not _score_float_matches(avg_rounds, rounds / games)
        or not _score_float_matches(exploit_score, expected_exploit)
    ):
        raise TypeError("exploit candidate")
    return {
        "rank": rank,
        "roster_id": roster_id,
        "name": name,
        "army": army,
        "points": points,
        "composition": composition,
        "games": games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "rounds": rounds,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "draw_rate": draw_rate,
        "avg_rounds": avg_rounds,
        "exploit_score": exploit_score,
    }


def _exploit_pair_from_payload(
    payload: Any,
    *,
    expected_ids: tuple[int, int],
    expected_games: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("exploit pair")
    _require_exact_keys(
        payload,
        {
            "roster_a_id",
            "roster_b_id",
            "wins_a",
            "wins_b",
            "draws",
            "games",
            "rounds",
            "win_rate_a",
            "win_rate_b",
            "avg_rounds",
        },
    )
    roster_a_id = _required_int(payload, "roster_a_id")
    roster_b_id = _required_int(payload, "roster_b_id")
    wins_a = _required_int(payload, "wins_a")
    wins_b = _required_int(payload, "wins_b")
    draws = _required_int(payload, "draws")
    games = _required_int(payload, "games")
    rounds = _required_int(payload, "rounds")
    win_rate_a = _required_finite_float(payload, "win_rate_a")
    win_rate_b = _required_finite_float(payload, "win_rate_b")
    avg_rounds = _required_finite_float(payload, "avg_rounds")
    if (
        (roster_a_id, roster_b_id) != expected_ids
        or games != expected_games
        or min(wins_a, wins_b, draws, rounds) < 0
        or wins_a + wins_b + draws != games
        or rounds > games * 100
        or not 0.0 <= win_rate_a <= 1.0
        or not 0.0 <= win_rate_b <= 1.0
        or not _score_float_matches(win_rate_a, wins_a / games)
        or not _score_float_matches(win_rate_b, wins_b / games)
        or not _score_float_matches(avg_rounds, rounds / games)
    ):
        raise TypeError("exploit pair")
    return {
        "roster_a_id": roster_a_id,
        "roster_b_id": roster_b_id,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "draws": draws,
        "games": games,
        "rounds": rounds,
        "win_rate_a": win_rate_a,
        "win_rate_b": win_rate_b,
        "avg_rounds": avg_rounds,
    }


def _assert_exploit_candidate_consistency(
    candidates: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
) -> None:
    totals = {
        candidate["roster_id"]: {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "rounds": 0,
        }
        for candidate in candidates
    }
    for pair in pairs:
        left = totals[pair["roster_a_id"]]
        right = totals[pair["roster_b_id"]]
        left["games"] += pair["games"]
        left["wins"] += pair["wins_a"]
        left["losses"] += pair["wins_b"]
        left["draws"] += pair["draws"]
        left["rounds"] += pair["rounds"]
        right["games"] += pair["games"]
        right["wins"] += pair["wins_b"]
        right["losses"] += pair["wins_a"]
        right["draws"] += pair["draws"]
        right["rounds"] += pair["rounds"]

    for candidate in candidates:
        total = totals[candidate["roster_id"]]
        if any(candidate[key] != total[key] for key in total):
            raise TypeError("exploit candidate aggregate")
    expected_ranking = sorted(
        candidates,
        key=lambda candidate: (
            (
                candidate["wins"]
                / candidate["games"]
                / candidate["points"]
                * 100.0
                if candidate["points"] > 0.0
                else 0.0
            ),
            candidate["wins"] / candidate["games"],
            -candidate["points"],
            -candidate["roster_id"],
        ),
        reverse=True,
    )
    if [candidate["roster_id"] for candidate in candidates] != [
        candidate["roster_id"] for candidate in expected_ranking
    ]:
        raise TypeError("exploit candidate ranking")


def _score_roster_info_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("score roster")
    _require_exact_keys(payload, {"id", "name", "army", "points", "composition"})
    roster_id = _required_int(payload, "id")
    name = _bounded_required_str(payload, "name", max_length=120)
    army = _bounded_required_str(payload, "army", max_length=120)
    points = _required_finite_float(payload, "points")
    composition = _required_str(payload, "composition")
    if (
        roster_id < 1
        or points < 0.0
        or points > 1_000_000_000_000.0
        or len(composition) > 4000
    ):
        raise TypeError("score roster")
    return {
        "id": roster_id,
        "name": name,
        "army": army,
        "points": points,
        "composition": composition,
    }


def _score_parameters_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("score parameters")
    _require_exact_keys(
        payload,
        {
            "games_per_opponent",
            "bot",
            "seed",
            "map_name",
            "opponent_roster_ids",
        },
    )
    games = _required_int(payload, "games_per_opponent")
    bot = _required_str(payload, "bot")
    seed = _required_int(payload, "seed")
    map_name = _required_str(payload, "map_name")
    opponent_ids = payload["opponent_roster_ids"]
    if (
        not 1 <= games <= MAX_SCORE_GAMES_PER_OPPONENT
        or bot not in SCORE_LIST_BOTS
        or not MIN_SCORE_SEED <= seed <= MAX_SCORE_SEED
        or map_name not in SCORE_LIST_MAPS
        or not isinstance(opponent_ids, list)
        or len(opponent_ids) > MAX_SCORE_OPPONENTS
        or any(type(item) is not int or item < 1 for item in opponent_ids)
        or opponent_ids != sorted(opponent_ids)
        or len(set(opponent_ids)) != len(opponent_ids)
        or games * len(opponent_ids) > MAX_SCORE_TOTAL_GAMES
    ):
        raise TypeError("score parameters")
    return {
        "games_per_opponent": games,
        "bot": bot,
        "seed": seed,
        "map_name": map_name,
        "opponent_roster_ids": list(opponent_ids),
    }


def _score_result_from_payload(
    payload: Any,
    *,
    expected_games: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("score result")
    _require_exact_keys(
        payload,
        {
            "opponent",
            "n",
            "wins",
            "losses",
            "draws",
            "rounds",
            "win_rate",
            "loss_rate",
            "draw_rate",
            "avg_rounds",
        },
    )
    opponent = _score_roster_info_from_payload(payload["opponent"])
    n_games = _required_int(payload, "n")
    wins = _required_int(payload, "wins")
    losses = _required_int(payload, "losses")
    draws = _required_int(payload, "draws")
    rounds = _required_int(payload, "rounds")
    win_rate = _required_finite_float(payload, "win_rate")
    loss_rate = _required_finite_float(payload, "loss_rate")
    draw_rate = _required_finite_float(payload, "draw_rate")
    avg_rounds = _required_finite_float(payload, "avg_rounds")
    if (
        n_games != expected_games
        or min(wins, losses, draws, rounds) < 0
        or wins + losses + draws != n_games
        or rounds > n_games * 100
        or not all(
            0.0 <= rate <= 1.0
            for rate in (win_rate, loss_rate, draw_rate)
        )
        or not _score_float_matches(win_rate, wins / n_games)
        or not _score_float_matches(loss_rate, losses / n_games)
        or not _score_float_matches(draw_rate, draws / n_games)
        or not _score_float_matches(avg_rounds, rounds / n_games)
    ):
        raise TypeError("score result")
    return {
        "opponent": opponent,
        "n": n_games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "rounds": rounds,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "draw_rate": draw_rate,
        "avg_rounds": avg_rounds,
    }


def _score_summary_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("score summary")
    _require_exact_keys(
        payload,
        {
            "n_opponents",
            "n_games",
            "wins",
            "losses",
            "draws",
            "rounds",
            "win_rate",
            "loss_rate",
            "draw_rate",
            "avg_rounds",
        },
    )
    n_opponents = _required_int(payload, "n_opponents")
    n_games = _required_int(payload, "n_games")
    wins = _required_int(payload, "wins")
    losses = _required_int(payload, "losses")
    draws = _required_int(payload, "draws")
    rounds = _required_int(payload, "rounds")
    win_rate = _required_finite_float(payload, "win_rate")
    loss_rate = _required_finite_float(payload, "loss_rate")
    draw_rate = _required_finite_float(payload, "draw_rate")
    avg_rounds = _required_finite_float(payload, "avg_rounds")
    divisor = n_games or 1
    if (
        not 0 <= n_opponents <= MAX_SCORE_OPPONENTS
        or not 0 <= n_games <= MAX_SCORE_TOTAL_GAMES
        or min(wins, losses, draws, rounds) < 0
        or wins + losses + draws != n_games
        or rounds > n_games * 100
        or (n_games == 0 and (n_opponents != 0 or rounds != 0))
        or not all(
            0.0 <= rate <= 1.0
            for rate in (win_rate, loss_rate, draw_rate)
        )
        or not _score_float_matches(win_rate, wins / divisor)
        or not _score_float_matches(loss_rate, losses / divisor)
        or not _score_float_matches(draw_rate, draws / divisor)
        or not _score_float_matches(avg_rounds, rounds / divisor)
    ):
        raise TypeError("score summary")
    return {
        "n_opponents": n_opponents,
        "n_games": n_games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "rounds": rounds,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "draw_rate": draw_rate,
        "avg_rounds": avg_rounds,
    }


def _assert_score_summary_matches(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    n_games = sum(result["n"] for result in results)
    wins = sum(result["wins"] for result in results)
    losses = sum(result["losses"] for result in results)
    draws = sum(result["draws"] for result in results)
    rounds = sum(result["rounds"] for result in results)
    divisor = n_games or 1
    if (
        summary["n_opponents"] != len(results)
        or summary["n_games"] != n_games
        or summary["wins"] != wins
        or summary["losses"] != losses
        or summary["draws"] != draws
        or summary["rounds"] != rounds
        or not _score_float_matches(summary["win_rate"], wins / divisor)
        or not _score_float_matches(summary["loss_rate"], losses / divisor)
        or not _score_float_matches(summary["draw_rate"], draws / divisor)
        or not _score_float_matches(summary["avg_rounds"], rounds / divisor)
    ):
        raise TypeError("score summary consistency")


def _score_float_matches(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def _loadout_mode_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("loadout mode")
    _require_exact_keys(payload, {"raw", "normalized", "clamped"})
    raw = payload["raw"]
    normalized = _required_str(payload, "normalized")
    clamped = payload["clamped"]
    if (
        not _is_strict_json_value(raw)
        or normalized not in {"per_model", "total"}
        or type(clamped) is not bool
    ):
        raise TypeError("loadout mode")
    return {"raw": raw, "normalized": normalized, "clamped": clamped}


def _loadout_sections_from_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or len(payload) != 3:
        raise TypeError("loadout sections")
    sections = [
        _loadout_section_from_payload(section, expected_name=expected_name)
        for section, expected_name in zip(
            payload,
            ("weapons", "active", "aura"),
            strict=True,
        )
    ]
    return sections


def _loadout_section_from_payload(
    payload: Any,
    *,
    expected_name: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("loadout section")
    _require_exact_keys(payload, {"section", "accepted", "rejected", "clamped"})
    section = _required_str(payload, "section")
    if section != expected_name:
        raise TypeError("loadout section order")
    return {
        "section": section,
        "accepted": _loadout_count_mapping(payload["accepted"]),
        "rejected": _rejected_loadout_items(payload["rejected"]),
        "clamped": _clamped_loadout_items(payload["clamped"]),
    }


def _loadout_count_mapping(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        raise TypeError("loadout count mapping")
    counts: dict[str, int] = {}
    for key, value in payload.items():
        if type(key) is not str or not key or type(value) is not int or value < 0:
            raise TypeError("loadout count mapping")
        counts[key] = value
    return counts


def _rejected_loadout_items(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, list):
        raise TypeError("rejected loadout items")
    items: list[dict[str, str]] = []
    allowed_reasons = {"niedozwolone dla tej jednostki", "niepoprawne id"}
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("rejected loadout item")
        _require_exact_keys(item, {"id", "reason"})
        item_id = _required_str(item, "id")
        reason = _required_str(item, "reason")
        if not item_id or reason not in allowed_reasons:
            raise TypeError("rejected loadout item")
        items.append({"id": item_id, "reason": reason})
    return items


def _clamped_loadout_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise TypeError("clamped loadout items")
    items: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("clamped loadout item")
        _require_exact_keys(item, {"id", "raw", "normalized"})
        item_id = _required_str(item, "id")
        raw = item["raw"]
        normalized = _required_int(item, "normalized")
        if not item_id or not _is_strict_json_value(raw) or normalized < 0:
            raise TypeError("clamped loadout item")
        items.append({"id": item_id, "raw": raw, "normalized": normalized})
    return items


def _loadout_passive_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("loadout passive")
    _require_exact_keys(payload, {"accepted", "rejected"})
    rejected = payload["rejected"]
    if not isinstance(rejected, list) or any(
        type(slug) is not str or not slug for slug in rejected
    ):
        raise TypeError("loadout passive")
    return {
        "accepted": _loadout_count_mapping(payload["accepted"]),
        "rejected": list(rejected),
    }


def _loadout_cost_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("loadout cost")
    _require_exact_keys(payload, {"selected_role", "selected_total", "components"})
    selected_role = payload["selected_role"]
    selected_total = _required_finite_float(payload, "selected_total")
    components = payload["components"]
    if (
        selected_role not in {None, "wojownik", "strzelec"}
        or selected_total < 0.0
        or not isinstance(components, dict)
    ):
        raise TypeError("loadout cost")
    component_names = {"active", "aura", "base", "passive", "weapon"}
    _require_exact_keys(components, component_names)
    return {
        "selected_role": selected_role,
        "selected_total": selected_total,
        "components": {
            name: _required_finite_float(components, name)
            for name in sorted(component_names)
        },
    }


def _rules_search_result_from_payload(
    payload: Any,
    *,
    expected_rank: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("rules search result")
    _require_exact_keys(
        payload,
        {
            "rank",
            "chunk_id",
            "source",
            "headings",
            "refs",
            "text",
            "score",
            "components",
        },
    )
    rank = _required_int(payload, "rank")
    source = _required_str(payload, "source")
    if rank != expected_rank or source not in RULE_SEARCH_SOURCES:
        raise TypeError("rules search rank or source")
    components = _rules_search_components_from_payload(payload["components"])
    score = _required_finite_float(payload, "score", positive=True)
    contribution_sum = sum(
        component["contribution"]
        for component in components.values()
        if component is not None
    )
    if not math.isclose(score, contribution_sum, rel_tol=0.0, abs_tol=2e-12):
        raise TypeError("rules search score")
    return {
        "rank": rank,
        "chunk_id": _bounded_required_str(payload, "chunk_id", max_length=128),
        "source": source,
        "headings": _bounded_string_list(
            payload["headings"],
            max_items=12,
            max_length=300,
        ),
        "refs": _bounded_string_list(
            payload["refs"],
            max_items=64,
            max_length=64,
        ),
        "text": _bounded_required_str(
            payload,
            "text",
            max_length=MAX_RULE_SEARCH_TEXT_LENGTH,
        ),
        "score": score,
        "components": components,
    }


def _rules_search_components_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("rules search components")
    _require_exact_keys(payload, {"bm25", "dense"})
    bm25 = _rrf_component_from_payload(payload["bm25"], expected_weight=2.0)
    dense = _rrf_component_from_payload(payload["dense"], expected_weight=1.0)
    if bm25 is None and dense is None:
        raise TypeError("rules search components")
    return {"bm25": bm25, "dense": dense}


def _rrf_component_from_payload(
    payload: Any,
    *,
    expected_weight: float,
) -> dict[str, int | float] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise TypeError("RRF component")
    _require_exact_keys(payload, {"rank", "weight", "contribution"})
    rank = _required_int(payload, "rank")
    weight = _required_finite_float(payload, "weight", positive=True)
    contribution = _required_finite_float(
        payload,
        "contribution",
        positive=True,
    )
    if not 1 <= rank <= 5 or weight != expected_weight:
        raise TypeError("RRF component")
    return {
        "rank": rank,
        "weight": weight,
        "contribution": contribution,
    }


def _bounded_string_list(
    value: Any,
    *,
    max_items: int,
    max_length: int,
) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > max_items
        or any(
            not isinstance(item, str) or not item or len(item) > max_length
            for item in value
        )
    ):
        raise TypeError("bounded string list")
    return list(value)


def _require_exact_keys(payload: dict[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        raise TypeError("unexpected object keys")


def _required_finite_float(
    payload: dict[str, Any],
    key: str,
    *,
    positive: bool = False,
) -> float:
    value = payload[key]
    if type(value) is not float or not math.isfinite(value):
        raise TypeError(key)
    if positive and value <= 0.0:
        raise TypeError(key)
    return value


def _rule_match_from_payload(item: Any, *, mode: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TypeError("rule match")
    ref = _bounded_required_str(item, "ref", max_length=32)
    text = _bounded_required_str(
        item,
        "text",
        max_length=MAX_RULE_TEXT_LENGTH,
        allow_empty=True,
    )
    parents = _rule_context_list(item["parents"], max_items=2)
    children = _rule_context_list(
        item["children"],
        max_items=MAX_RULE_CHILDREN,
    )
    score = item["score"]
    if mode == "reference":
        if score is not None:
            raise TypeError("reference score")
    elif type(score) is not int or score < 1:
        raise TypeError("search score")
    return {
        "ref": ref,
        "text": text,
        "parents": parents,
        "children": children,
        "score": score,
    }


def _rule_context_list(value: Any, *, max_items: int) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > max_items:
        raise TypeError("rule context")
    contexts: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError("rule context")
        contexts.append(
            {
                "ref": _bounded_required_str(item, "ref", max_length=32),
                "text": _bounded_required_str(
                    item,
                    "text",
                    max_length=MAX_RULE_TEXT_LENGTH,
                    allow_empty=True,
                ),
            }
        )
    return contexts


def _ability_explanation_from_payload(
    payload: Any,
    *,
    expected_query: str,
    error_label: str,
) -> dict[str, Any]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        schema = _required_str(payload, "schema")
        version = _required_int(payload, "version")
        source = _required_str(payload, "source")
        query = _required_str(payload, "query")
        if (
            schema != ABILITY_EXPLANATION_SCHEMA
            or version != REFERENCE_API_VERSION
            or source != ABILITY_SOURCE
            or query != expected_query
        ):
            raise TypeError("ability explanation envelope")
        ability = _ability_from_payload(payload["ability"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc
    return {
        "schema": schema,
        "version": version,
        "source": source,
        "query": query,
        "ability": ability,
    }


def _ability_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("ability")
    value_label = _optional_bounded_str(payload, "value_label", max_length=100)
    value_type = _optional_bounded_str(payload, "value_type", max_length=50)
    requires_value = payload["requires_value"]
    blocked = payload["blocked"]
    raw_choices = payload["value_choices"]
    if (
        type(requires_value) is not bool
        or type(blocked) is not bool
        or not isinstance(raw_choices, list)
        or len(raw_choices) > 50
        or any(
            not isinstance(choice, str) or len(choice) > 100
            for choice in raw_choices
        )
    ):
        raise TypeError("ability fields")
    return {
        "slug": _bounded_required_str(payload, "slug", max_length=100),
        "name": _bounded_required_str(payload, "name", max_length=200),
        "display_name": _bounded_required_str(
            payload,
            "display_name",
            max_length=250,
        ),
        "type": _bounded_required_str(payload, "type", max_length=50),
        "description": _bounded_required_str(
            payload,
            "description",
            max_length=10_000,
            allow_empty=True,
        ),
        "value_label": value_label,
        "value_type": value_type,
        "requires_value": requires_value,
        "value_choices": list(raw_choices),
        "blocked": blocked,
    }


def _bounded_required_str(
    payload: dict[str, Any],
    key: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    value = _required_str(payload, key)
    if len(value) > max_length or (not allow_empty and not value):
        raise TypeError(key)
    return value


def _optional_bounded_str(
    payload: dict[str, Any],
    key: str,
    *,
    max_length: int,
) -> str | None:
    value = payload[key]
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise TypeError(key)
    return value


def _metadata_from_payload(
    payload: Any,
    *,
    error_label: str,
    expected_battle_id: int | None = None,
) -> BattleMetadata:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    if expected_battle_id is not None:
        _ensure_expected_battle_id(
            payload,
            expected_battle_id,
            error_label=error_label,
        )
    try:
        expected_keys = {
            "battle_id",
            "p1_user_id",
            "p2_user_id",
            "p1_roster_id",
            "p2_roster_id",
            "winner_user_id",
            "current_round",
            "rng_seed",
            "status",
            "latest_sequence",
            "activation_protocol_version",
        }
        if "adaptation_report" in payload:
            expected_keys.add("adaptation_report")
        _require_exact_keys(payload, expected_keys)
        return BattleMetadata(
            battle_id=_required_int(payload, "battle_id"),
            p1_user_id=_optional_int(payload, "p1_user_id"),
            p2_user_id=_optional_int(payload, "p2_user_id"),
            p1_roster_id=_optional_int(payload, "p1_roster_id"),
            p2_roster_id=_optional_int(payload, "p2_roster_id"),
            winner_user_id=_optional_int(payload, "winner_user_id"),
            current_round=_required_int(payload, "current_round"),
            rng_seed=_required_int(payload, "rng_seed"),
            status=_required_str(payload, "status"),
            latest_sequence=_required_int(payload, "latest_sequence"),
            activation_protocol_version=validate_activation_protocol_version(
                _required_int(payload, "activation_protocol_version")
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc


def _battle_invite_metadata_from_payload(
    payload: Any,
    *,
    error_label: str,
) -> BattleInviteMetadata:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        _require_exact_keys(
            payload,
            {
                "id",
                "from_user_id",
                "to_user_id",
                "roster_id",
                "scenario",
                "status",
                "activation_protocol_version",
                "expires_at",
                "created_at",
                "updated_at",
            },
        )
        return BattleInviteMetadata(
            invite_id=_required_int(payload, "id"),
            from_user_id=_required_int(payload, "from_user_id"),
            to_user_id=_optional_int(payload, "to_user_id"),
            roster_id=_required_int(payload, "roster_id"),
            scenario=_required_str(payload, "scenario"),
            status=_required_str(payload, "status"),
            activation_protocol_version=validate_activation_protocol_version(
                _required_int(payload, "activation_protocol_version")
            ),
            expires_at=_required_naive_datetime(payload, "expires_at"),
            created_at=_required_naive_datetime(payload, "created_at"),
            updated_at=_required_naive_datetime(payload, "updated_at"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc


def _simulation_summary_from_payload(
    payload: Any,
    *,
    error_label: str,
) -> SimulationSummary:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        summary = SimulationSummary(
            n_games=_required_int(payload, "n_games"),
            wins_p0=_required_int(payload, "wins_p0"),
            wins_p1=_required_int(payload, "wins_p1"),
            draws=_required_int(payload, "draws"),
            total_rounds=_required_int(payload, "total_rounds"),
        )
    except (KeyError, TypeError) as exc:
        raise HttpClientError(error_message) from exc
    if (
        summary.n_games <= 0
        or summary.wins_p0 < 0
        or summary.wins_p1 < 0
        or summary.draws < 0
        or summary.total_rounds < 0
        or summary.wins_p0 + summary.wins_p1 + summary.draws != summary.n_games
    ):
        raise HttpClientError(error_message)
    return summary


def _action_result_from_payload(
    payload: Any,
    *,
    expected_battle_id: int,
    expected_previous_sequence: int,
    error_label: str,
) -> tuple[BattleState, tuple[BattleEvent, ...]]:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    _ensure_expected_battle_id(
        payload,
        expected_battle_id,
        error_label=error_label,
    )
    try:
        previous_sequence = _required_int(payload, "previous_sequence")
        new_sequence = _required_int(payload, "new_sequence")
        if (
            previous_sequence != expected_previous_sequence
            or new_sequence < previous_sequence
        ):
            raise TypeError("action sequence")
        state_payload = payload["state"]
        if not isinstance(state_payload, dict):
            raise TypeError("state")
        state = battle_state_from_json(state_payload)
        raw_events = payload["events"]
        if not isinstance(raw_events, list):
            raise TypeError("events")
        events = tuple(_event_from_public_payload(item) for item in raw_events)
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc

    expected_sequences = tuple(range(previous_sequence + 1, new_sequence + 1))
    if tuple(event.sequence for event in events) != expected_sequences:
        raise HttpClientError(error_message)
    return state, events


def _battle_replay_result_from_payload(
    payload: Any,
    *,
    expected_battle_id: int,
    error_label: str,
) -> BattleReplayResult:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        _require_exact_keys(
            payload,
            {
                "battle_id",
                "base_sequence",
                "replayed_through_sequence",
                "event_count",
                "verified_against_checkpoint",
                "state",
            },
        )
        battle_id = _required_int(payload, "battle_id")
        if battle_id != expected_battle_id:
            raise TypeError("battle_id")
        state_payload = payload["state"]
        if not isinstance(state_payload, dict):
            raise TypeError("state")
        _require_exact_keys(state_payload, {"schema", "version", "state"})
        schema = _required_str(state_payload, "schema")
        version = _required_int(state_payload, "version")
        state = battle_state_from_json(state_payload)
        if payload["verified_against_checkpoint"] is not True:
            raise TypeError("verified_against_checkpoint")
        return BattleReplayResult(
            battle_id=battle_id,
            base_sequence=_required_int(payload, "base_sequence"),
            replayed_through_sequence=_required_int(
                payload,
                "replayed_through_sequence",
            ),
            event_count=_required_int(payload, "event_count"),
            verified_against_checkpoint=True,
            schema=schema,
            version=version,
            state=state,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc


def _battle_action_proposal_from_payload(
    payload: Any,
    *,
    expected_battle_id: int,
    expected_sequence: int,
    expected_action: dict[str, Any],
    expected_summary: str,
    error_label: str,
) -> BattleActionProposal:
    error_message = f"{error_label} returned malformed payload"
    if not isinstance(payload, dict):
        raise HttpClientError(error_message)
    try:
        if _required_str(payload, "action") != "battle:action":
            raise TypeError("action")
        if _required_str(payload, "status") != "pending":
            raise TypeError("status")
        if _required_str(payload, "summary") != expected_summary:
            raise TypeError("summary")
        proposal_payload = payload["payload"]
        if (
            not isinstance(proposal_payload, dict)
            or set(proposal_payload)
            != {"battle_id", "expected_sequence", "action"}
        ):
            raise TypeError("payload")
        battle_id = _required_int(proposal_payload, "battle_id")
        sequence = _required_int(proposal_payload, "expected_sequence")
        action = proposal_payload["action"]
        if (
            battle_id != expected_battle_id
            or sequence != expected_sequence
            or action != expected_action
        ):
            raise TypeError("proposal payload")
        return BattleActionProposal(
            proposal_id=_required_int(payload, "id"),
            owner_user_id=_required_int(payload, "owner_user_id"),
            agent_user_id=_required_int(payload, "agent_user_id"),
            token_id=_optional_int(payload, "token_id"),
            battle_id=battle_id,
            expected_sequence=sequence,
            action=action,
            summary=expected_summary,
            status="pending",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError(error_message) from exc


def _ensure_expected_battle_id(
    payload: dict[str, Any],
    expected_battle_id: int,
    *,
    error_label: str,
) -> None:
    try:
        battle_id = _required_int(payload, "battle_id")
    except (KeyError, TypeError) as exc:
        raise HttpClientError(f"{error_label} returned malformed payload") from exc
    if battle_id != expected_battle_id:
        raise HttpClientError(
            f"{error_label} returned battle_id {battle_id}, "
            f"expected {expected_battle_id}"
        )


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload[key]
    if type(value) is not int:
        raise TypeError(key)
    return value


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload[key]
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError(key)
    return value


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _required_naive_datetime(payload: dict[str, Any], key: str) -> datetime:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(key)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise TypeError(key)
    return parsed


def _event_from_public_payload(item: Any) -> BattleEvent:
    if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
        raise HttpClientError("Battle event payload is malformed")
    try:
        sequence = _required_int(item, "sequence")
        event_type = _required_str(item, "event_type")
        event = json_to_event(item["payload"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpClientError("Battle event payload cannot be decoded") from exc
    if event.sequence != sequence or type(event).__name__ != event_type:
        raise HttpClientError("Battle event envelope does not match its payload")
    return event


def _urlopen_transport(request: HttpRequest) -> HttpResponse:
    urllib_request = Request(
        request.url,
        data=request.body,
        headers=request.headers,
        method=request.method,
    )
    try:
        with urlopen(urllib_request, timeout=request.timeout) as response:
            status_code = int(getattr(response, "status", response.getcode()))
            return HttpResponse(status_code=status_code, body=response.read())
    except HTTPError as exc:
        body = exc.read()
        return HttpResponse(status_code=exc.code, body=body)
    except URLError as exc:
        raise HttpClientTransportError(f"HTTP transport failed: {exc.reason}") from exc
