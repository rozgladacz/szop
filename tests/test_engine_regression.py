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
# Wyniki odświeżone po P6. Porównanie pełnych logów w ADR-0059.
GOLDEN_CASES = [
    (
        "demo_priority_mirror",
        "demo_skirmish.yaml", ("priority", "priority"), 0, 0,
        1, 4, (2, 3), 243,
        "80e9813e2c1d47e0911fb3254f1ca0c33759d1281fd51f056f1c484a5e91bca4",
    ),
    (
        "demo_priority_mirror_draw",
        "demo_skirmish.yaml", ("priority", "priority"), 11, 0,
        None, 4, (2, 2), 247,
        "853a3a39bbc6a2c4d2b2751c312ef1220b353f8913bbd498f854e09d9952214a",
    ),
    (
        "demo_greedy_vs_random",
        "demo_skirmish.yaml", ("greedy", "random"), 7, 1,
        1, 4, (2, 3), 203,
        "72c24382e2beb5dc54269c1517128c2d950e7eb90192d41218ca3d846b91f0b1",
    ),
    (
        "clash_priority_vs_greedy",
        "objective_clash.yaml", ("priority", "greedy"), 0, 0,
        0, 4, (3, 0), 203,
        "9d1a34b20f49c3e08804fc451543070d1f7dd62e16112426796126c1cc2767c5",
    ),
    (
        "clash_random_mirror",
        "objective_clash.yaml", ("random", "random"), 42, 0,
        1, 4, (0, 1), 234,
        "cc1f827ed4574727d04e71397c713226cd97cd5ea24f3832c107e00ef9800110",
    ),
    (
        "profiles_v3_vs_v2",
        "unit_profiles.yaml", ("priority3", "priority2"), 0, 0,
        0, 4, (3, 2), 256,
        "a4402b8b3214927f1c6dafedbb41c3dc57b280eeeb261c17adf08f40884953bb",
    ),
    (
        "profiles_v2_vs_priority",
        "unit_profiles.yaml", ("priority2", "priority"), 3, 1,
        None, 4, (2, 2), 234,
        "2ab9ad29cbd4a13c7bff144839ebdae728bfb932af1c9b14b5f03fd0790b5924",
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
