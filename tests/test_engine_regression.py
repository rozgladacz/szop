"""B7 — golden regression test bed: deterministyczne pełne bitwy.

Każdy GOLDEN_CASE to pełna gra (fixtura wierna regułom + predefiniowany seed +
deterministyczny matchup botów) z **zapieczętowanym** wynikiem. Bitwa jest w
100% deterministyczna: `DeterministicDice(seed)` + boty deterministyczne per
seed (ADR-0010/0012). Test pełni rolę siatki bezpieczeństwa nad silnikiem
(`app/services/engine/*`) i warstwą agentów (`app/services/agents/*`):

    Zmiana którejkolwiek wartości GOLDEN = świadoma zmiana rulesetu / silnika /
    heurystyki bota → musi być udokumentowana ADR-em (roadmap B7).

Asercje są dwupoziomowe:
  1. **Semantyczne** (winner / rounds / score / liczba eventów) — czytelne; gdy
     coś flipnie, od razu widać *co* się zmieniło.
  2. **Digest** (sha256 nad `event_to_json` całego logu) — czuły strażnik
     bit-perfect determinizmu; flipuje przy KAŻDEJ zmianie przebiegu, nawet
     gdy nagłówkowe wartości pozostają te same.

Jak zaktualizować golden po świadomej zmianie:
    python tests/test_engine_regression.py   # wypisuje świeże winner/rounds/score/digest
    # → przenieś wartości do GOLDEN_CASES + zapisz ADR z uzasadnieniem.

Skrypt jest izolowanym liściem nad publicznym API silnika/agentów (reużywa
`scripts/balance_simulate.py` jako SSOT ładowania fixtur + budowy graczy) —
testy nie dotykają DB ani kosztów.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Umożliwia uruchomienie jako skrypt (`python tests/...`) do regenu golden —
# pod pytest repo-root jest już na ścieżce.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.engine.events import event_to_json  # noqa: E402

_SCRIPT = _REPO_ROOT / "scripts" / "balance_simulate.py"
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "battles"


def _load_module():
    """Ładuje `balance_simulate.py` jako moduł (nie jest pakietem importowalnym)."""
    spec = importlib.util.spec_from_file_location("balance_simulate", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Rejestracja w sys.modules PRZED exec — `dataclass(slots=True)` rozwiązuje
    # `cls.__module__` przez `sys.modules.get(...)`, inaczej AttributeError.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bs = _load_module()


def _event_digest(events) -> str:
    """sha256 nad kanoniczną serializacją całego logu eventów (bit-perfect lock)."""
    blob = json.dumps(
        [event_to_json(e) for e in events],
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def _run(fixture_file: str, kinds: tuple[str, str], seed: int, initiative: int):
    """Rozgrywa jedną pełną deterministyczną grę (SSOT: balance_simulate)."""
    fx = bs.load_battle_fixture(_FIXTURES / fixture_file)
    players = [
        bs.make_player(kinds[0], seed),
        bs.make_player(kinds[1], seed + bs.PLAYER_SEED_OFFSET),
    ]
    return bs.simulate_from_rosters(
        fx.rosters,
        players,
        seed=seed,
        terrain=fx.terrain,
        objectives=fx.objectives,
        initiative_player=initiative,
    )


# --- GOLDEN ------------------------------------------------------------------
# Pola: id, fixtura, (P0_kind, P1_kind), seed, initiative,
#       winner, rounds, score (P0, P1), n_events, digest sha256.
# Wyniki odświeżone 2026-11-18 po ADR-0058 (kontrola celu w 2″, pkt 5.d).
GOLDEN_CASES = [
    (
        "demo_priority_mirror",
        "demo_skirmish.yaml", ("priority", "priority"), 0, 0,
        1, 4, (2, 3), 245,
        "5f0f8cf7f9bad06bf462b29ac1533272099c50249724a605748e91b02b074c4a",
    ),
    (
        "demo_priority_mirror_draw",
        "demo_skirmish.yaml", ("priority", "priority"), 11, 0,
        None, 4, (2, 2), 250,
        "4dac4a1a9c15fbec5be6d22f1391c90be95095f97dc8acb9366515812529136e",
    ),
    (
        "demo_greedy_vs_random",
        "demo_skirmish.yaml", ("greedy", "random"), 7, 1,
        1, 4, (2, 3), 212,
        "1580fd8b7f2cc3bbb99f8e3b25be2a8cc8dfb2fa207659b2ee8bc6bdcbaf8f07",
    ),
    (
        "clash_priority_vs_greedy",
        "objective_clash.yaml", ("priority", "greedy"), 0, 0,
        0, 4, (2, 1), 214,
        "e751d25b7993e6194305b8e1012963416c7307e3e8a7c8dffae74897d8ee29ad",
    ),
    (
        "clash_random_mirror",
        "objective_clash.yaml", ("random", "random"), 42, 0,
        1, 4, (0, 1), 225,
        "0b10404b945542f0ba254afceefdec730301dba31221eefe360dc743c105832b",
    ),
    (
        "profiles_v3_vs_v2",
        "unit_profiles.yaml", ("priority3", "priority2"), 0, 0,
        0, 4, (3, 2), 247,
        "ab86e47b6c83d7b5084e71ea1ab137eee71cf3e4b4b3c0d7db201028d227c707",
    ),
    (
        "profiles_v2_vs_priority",
        "unit_profiles.yaml", ("priority2", "priority"), 3, 1,
        1, 4, (2, 3), 235,
        "ec3fa31af58a1eeed931a0507540145fa6a16a805c17cade16e3df5bc951c33e",
    ),
]

_IDS = [c[0] for c in GOLDEN_CASES]


@pytest.mark.parametrize(
    "case_id,fixture_file,kinds,seed,initiative,winner,rounds,score,n_events,digest",
    GOLDEN_CASES,
    ids=_IDS,
)
def test_golden_battle(
    case_id, fixture_file, kinds, seed, initiative, winner, rounds, score, n_events, digest
):
    """Pełna gra produkuje zapieczętowany wynik (zmiana = świadoma → ADR)."""
    res = _run(fixture_file, kinds, seed, initiative)

    # Semantyczne (czytelne, pokazują CO się zmieniło)
    assert res.winner == winner, f"{case_id}: winner drift"
    assert res.rounds_played == rounds, f"{case_id}: rounds drift"
    assert tuple(res.final_state.score) == score, f"{case_id}: score drift"
    assert len(res.events) == n_events, f"{case_id}: event-count drift"

    # Bit-perfect determinizm (czuły strażnik całego przebiegu)
    assert _event_digest(res.events) == digest, (
        f"{case_id}: event-log digest drift — przebieg bitwy się zmienił. "
        f"Jeśli świadome: zaktualizuj GOLDEN + zapisz ADR (roadmap B7)."
    )


@pytest.mark.parametrize(
    "case_id,fixture_file,kinds,seed,initiative",
    [c[:5] for c in GOLDEN_CASES],
    ids=_IDS,
)
def test_golden_battle_is_reproducible(case_id, fixture_file, kinds, seed, initiative):
    """Dwa uruchomienia tego samego case'u dają identyczny przebieg (replay-safe)."""
    r1 = _run(fixture_file, kinds, seed, initiative)
    r2 = _run(fixture_file, kinds, seed, initiative)
    assert r1.winner == r2.winner
    assert r1.rounds_played == r2.rounds_played
    assert tuple(r1.final_state.score) == tuple(r2.final_state.score)
    assert _event_digest(r1.events) == _event_digest(r2.events)


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=_IDS)
def test_golden_objective_results_replay_without_recalculation(case):
    """Pkt 5.d–g: zapisane rozliczenia odtwarzają kontrolę/wynik pełnej bitwy."""
    from app.services.engine.phases import deployment_round, setup_phase
    from app.services.engine.state import apply_events

    _, fixture_file, kinds, seed, initiative = case[:5]
    result = _run(fixture_file, kinds, seed, initiative)
    fx = bs.load_battle_fixture(_FIXTURES / fixture_file)
    initial = setup_phase(fx.rosters, terrain=fx.terrain, objectives=fx.objectives,
                          initiative_player=initiative)
    initial, _ = deployment_round(initial, [])
    replayed = apply_events(initial, result.events)
    assert replayed.objectives == result.final_state.objectives
    assert replayed.score == result.final_state.score
    assert replayed.round == result.final_state.round
    assert replayed.is_game_over == result.final_state.is_game_over


def test_golden_cases_cover_all_fixtures():
    """Sanity: każda commitowana fixtura ma ≥1 golden case."""
    committed = {p.name for p in _FIXTURES.glob("*.yaml")}
    covered = {c[1] for c in GOLDEN_CASES}
    assert committed <= covered, f"Fixtury bez golden case: {committed - covered}"


def test_golden_cases_cover_decisive_and_draw():
    """Sanity: golden pokrywa zarówno rozstrzygnięcia (oba kierunki) jak i remis."""
    winners = {c[5] for c in GOLDEN_CASES}
    assert {0, 1, None} <= winners, f"Brak pokrycia wyników: {winners}"


if __name__ == "__main__":
    # Regen golden: wypisuje świeże wartości dla każdego case'u (po świadomej
    # zmianie silnika/bota przenieś do GOLDEN_CASES + zapisz ADR — roadmap B7).
    for _c in GOLDEN_CASES:
        _id, _fix, _kinds, _seed, _init = _c[0], _c[1], _c[2], _c[3], _c[4]
        _r = _run(_fix, _kinds, _seed, _init)
        print(
            f"{_id}: winner={_r.winner!r} rounds={_r.rounds_played} "
            f"score={tuple(_r.final_state.score)} n_events={len(_r.events)}\n"
            f"    digest={_event_digest(_r.events)}"
        )
