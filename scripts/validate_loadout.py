"""C3 — `validate_loadout`: diff validator loadoutu jednostki bez zapisu loadoutu.

Uruchom:
    python scripts/validate_loadout.py --list                         # jednostki w bazie
    python scripts/validate_loadout.py 5 --loadout '{"weapons":{"3":1,"99":1}}'
    python scripts/validate_loadout.py 5 --loadout-file payload.json --count 3 --json

Deliverable Strumienia C3 (`validate_loadout(payload)` — roadmap „Narzędzia MCP")
w formie **skryptu-liścia** (ADR-0013), równolegle do `explain_ability.py` i
`simulate_engagement.py`. Od C3.1 rdzeń żyje w `app.services.loadout_validation`,
a skrypt importuje/re-eksportuje ten sam serwis co publiczne HTTP/HttpClient/MCP.

Co robi: bierze id jednostki z bazy (kontekst LEGALNYCH broni/zdolności/passive)
oraz RAW loadout payload (JSON z `--loadout`/`--loadout-file`) i pokazuje **diff**
między tym, co przysłał klient, a tym, co zaakceptuje SSOT sanityzacji
`normalize_roster_unit_loadout`:
  - selekcje ZAAKCEPTOWANE (znormalizowane),
  - selekcje ODRZUCONE (id spoza dozwolonego zbioru jednostki / niepoprawne id),
  - selekcje SKLAMPOWANE (ujemny / niepoprawny count → 0; nieznany `mode` → per_model),
plus KOSZT znormalizowanej konfiguracji przez `calculate_roster_unit_quote`
(`selected_total` + składowe). To „dry-run" endpointu quote bez zapisu do DB.

Decyzja usera 2026-06-26: validate_loadout = diff validator bez zapisu loadoutu, reuse
istniejącego quote/normalize SSOT (AGENTS [CRITICAL] #3 — bez replikacji logiki).

Skrypt-liść: zero zmian w rdzeniu silnika/costs; poza standardowym bootstrapem
schematu przez `init_db()` nie zapisuje walidowanego loadoutu ani wyników diffu.
Bez scopingu własności (jednostki = katalog armii).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Any, Sequence

# UTF-8 stdout (nazwy jednostek/broni PL na Windows cp1250 — jak simulate_engagement.py).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.db_bootstrap import initialized_session  # noqa: E402

from app.services.loadout_validation import (  # noqa: E402
    LoadoutDiff,
    SectionDiff,
    UnitNotFoundError,
    _coerce_int,
    _enumerate_raw_section,
    _id_is_parseable,
    diff_passive,
    diff_section,
    diff_to_dict,
    validate_loadout,
    validate_loadout_by_id,
)


# ---------------------------------------------------------------------------
# DB queries (no loadout writes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitInfo:
    id: int
    name: str
    army: str


def list_units(session) -> list[UnitInfo]:
    """Wszystkie jednostki w bazie (read-only), posortowane po id."""
    from app import models

    units = session.query(models.Unit).order_by(models.Unit.id).all()
    infos: list[UnitInfo] = []
    for unit in units:
        army = getattr(getattr(unit, "army", None), "name", "?") or "?"
        infos.append(UnitInfo(id=int(unit.id), name=str(unit.name or "?"), army=army))
    return infos


# ---------------------------------------------------------------------------
# Output (czyste funkcje)
# ---------------------------------------------------------------------------


def format_unit_list(infos: Sequence[UnitInfo]) -> str:
    if not infos:
        return "Brak jednostek w bazie."
    lines = [
        "Jednostki w bazie (id → nazwa / armia):",
        "=" * 60,
        f"{'id':>4}  {'nazwa':<32}  armia",
        "-" * 60,
    ]
    for info in infos:
        lines.append(f"{info.id:>4}  {info.name[:32]:<32}  {info.army}")
    return "\n".join(lines)


def _format_section(diff: SectionDiff) -> list[str]:
    label = {"weapons": "Broń", "active": "Zdolności aktywne", "aura": "Aury"}[diff.section]
    lines = [f"  {label}:"]
    if diff.accepted:
        accepted = ", ".join(f"{k}×{v}" for k, v in diff.accepted.items())
        lines.append(f"    ✓ zaakceptowane: {accepted}")
    else:
        lines.append("    ✓ zaakceptowane: (brak)")
    for id_str, reason in diff.rejected:
        lines.append(f"    ✗ ODRZUCONE {id_str} — {reason}")
    for id_str, raw_value, norm_value in diff.clamped:
        lines.append(f"    ~ SKLAMPOWANE {id_str}: {raw_value!r} → {norm_value}")
    return lines


def format_diff_report(diff: LoadoutDiff) -> str:
    """Czytelny raport tekstowy diffu + kosztu."""
    lines = [
        f"Walidacja loadoutu: jednostka [{diff.unit_id}] {diff.unit_name} (count={diff.count})",
        "=" * 60,
    ]
    mode_line = f"  Tryb: {diff.normalized_mode}"
    if diff.mode_clamped:
        mode_line += f"  (~ SKLAMPOWANE z {diff.raw_mode!r} → per_model)"
    lines.append(mode_line)
    for section in diff.sections:
        lines.extend(_format_section(section))
    lines.append("  Passive:")
    if diff.passive_accepted:
        passive = ", ".join(f"{k}={v}" for k, v in diff.passive_accepted.items())
        lines.append(f"    ✓ znormalizowane: {passive}")
    else:
        lines.append("    ✓ znormalizowane: (brak)")
    for slug in diff.passive_rejected:
        lines.append(f"    ✗ ODRZUCONE/NIEROZPOZNANE: {slug}")
    lines.append("-" * 60)
    role = diff.selected_role if diff.selected_role is not None else "—"
    lines.append(f"  Koszt (rola={role}): {diff.selected_total:.2f} pkt")
    comp = diff.components
    if comp:
        parts = ", ".join(f"{k}={float(v):.2f}" for k, v in comp.items())
        lines.append(f"    składowe: {parts}")
    lines.append("-" * 60)
    lines.append(
        "  Status: " + ("⚠ wykryto odrzucone/sklampowane selekcje" if diff.has_issues
                         else "✓ loadout czysty (bez odrzuceń/clampów)")
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="C3 validate_loadout — diff validator loadoutu bez zapisu.",
    )
    parser.add_argument("unit_id", type=int, nargs="?", help="id jednostki z bazy.")
    parser.add_argument("--loadout", type=str, default=None, help="RAW loadout jako JSON.")
    parser.add_argument(
        "--loadout-file", type=str, default=None, help="ścieżka do pliku JSON z loadoutem."
    )
    parser.add_argument("--count", type=int, default=1, help="liczba modeli/kopii (domyślnie 1).")
    parser.add_argument("--list", action="store_true", help="wypisz jednostki w bazie i zakończ.")
    parser.add_argument("--json", action="store_true", help="wypisz wynik jako JSON.")
    return parser.parse_args(argv)


def _load_raw_loadout(args: argparse.Namespace) -> dict[str, Any]:
    """Wczytaj surowy loadout z `--loadout` lub `--loadout-file`. Pusty → {}."""
    text: str | None = None
    if args.loadout_file:
        text = pathlib.Path(args.loadout_file).read_text(encoding="utf-8")
    elif args.loadout is not None:
        text = args.loadout
    if text is None or not text.strip():
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("loadout musi być obiektem JSON (dict).")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    with initialized_session() as session:
        if args.list:
            print(format_unit_list(list_units(session)))
            return 0

        if args.unit_id is None:
            print(
                "Podaj id jednostki (np. `validate_loadout.py 5 --loadout '{...}'`) lub `--list`.",
                file=sys.stderr,
            )
            return 2

        try:
            raw_loadout = _load_raw_loadout(args)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Błąd wczytania loadoutu: {exc}", file=sys.stderr)
            return 2

        try:
            diff = validate_loadout_by_id(session, args.unit_id, raw_loadout, args.count)
        except UnitNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps(diff_to_dict(diff), ensure_ascii=False, allow_nan=False))
    else:
        print(format_diff_report(diff))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
