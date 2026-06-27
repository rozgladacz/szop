"""C3 — `validate_loadout`: diff validator loadoutu jednostki bez zapisu loadoutu.

Uruchom:
    python scripts/validate_loadout.py --list                         # jednostki w bazie
    python scripts/validate_loadout.py 5 --loadout '{"weapons":{"3":1,"99":1}}'
    python scripts/validate_loadout.py 5 --loadout-file payload.json --count 3 --json

Deliverable Strumienia C3 (`validate_loadout(payload)` — roadmap „Narzędzia MCP")
w formie **skryptu-liścia** (ADR-0013), równolegle do `explain_ability.py` i
`simulate_engagement.py`. Pełna forma MCP-tool/HTTP czeka na serwer C1/B4.

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
from dataclasses import dataclass, field
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

from app.services.costs import calculate_roster_unit_quote  # noqa: E402
from app.services.costs.primitives import (  # noqa: E402
    ability_identifier,
    normalize_name,
)
from app.services.costs.unit_helpers import (  # noqa: E402
    normalize_roster_unit_loadout,
)

_SECTIONS = ("weapons", "active", "aura")


class UnitNotFoundError(Exception):
    """Jednostka o danym id nie istnieje w bazie."""


# ---------------------------------------------------------------------------
# Rdzeń diffu (czyste funkcje — testowalne bez DB)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionDiff:
    """Diff jednej sekcji id-owej (weapons/active/aura)."""

    section: str
    accepted: dict[str, int]  # znormalizowane id_str → count
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (id_str, powód)
    clamped: list[tuple[str, Any, int]] = field(default_factory=list)  # (id_str, raw, norm)


@dataclass(frozen=True)
class LoadoutDiff:
    """Pełny wynik walidacji: per-sekcja diff + mode + passive + koszt."""

    unit_id: int
    unit_name: str
    count: int
    raw_mode: Any
    normalized_mode: str
    mode_clamped: bool
    sections: list[SectionDiff]
    passive_accepted: dict[str, int]
    passive_rejected: list[str]
    selected_role: Any
    selected_total: float
    components: dict[str, float]

    @property
    def has_issues(self) -> bool:
        if self.mode_clamped or self.passive_rejected:
            return True
        return any(d.rejected or d.clamped for d in self.sections)


def _enumerate_raw_section(section: Any) -> list[tuple[str, Any]]:
    """Wylicz surowe `(id_str, raw_value)` z sekcji loadoutu.

    Mirror id-ekstrakcji `_normalize_loadout_section_ids` BEZ filtra dozwolonych
    (normalize celowo POMIJA odrzucone id → tu musimy je zobaczyć, by je zaraportować).
    Akceptuje dict `{id: count}` oraz listę dictów (`id`/`weapon_id`/`ability_id`/...).
    """
    if isinstance(section, dict):
        items: list[tuple[Any, Any]] = list(section.items())
    elif isinstance(section, list):
        items = []
        for entry in section:
            if not isinstance(entry, dict):
                continue
            entry_id = (
                entry.get("loadout_key")
                or entry.get("key")
                or entry.get("id")
                or entry.get("weapon_id")
                or entry.get("ability_id")
            )
            if entry_id is None:
                continue
            items.append((entry_id, entry.get("count") or entry.get("per_model") or 0))
    else:
        items = []

    pairs: list[tuple[str, Any]] = []
    for raw_id, raw_value in items:
        id_str = str(raw_id).strip()
        if not id_str:
            continue
        pairs.append((id_str, raw_value))
    return pairs


def _coerce_int(value: Any) -> int | None:
    """Parsuj count tak jak normalize: int, potem int(float(...)), inaczej None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _id_is_parseable(id_str: str) -> bool:
    """Czy id przeszłoby parse `_normalize_loadout_section_ids` (base przed ':')."""
    base = id_str.split(":", 1)[0]
    return _coerce_int(base) is not None


def diff_section(name: str, raw_section: Any, normalized_section: dict[str, int]) -> SectionDiff:
    """Porównaj surową sekcję z jej znormalizowaną wersją (klucze = oryginalne id_str)."""
    rejected: list[tuple[str, str]] = []
    clamped: list[tuple[str, Any, int]] = []
    for id_str, raw_value in _enumerate_raw_section(raw_section):
        if id_str not in normalized_section:
            reason = (
                "niedozwolone dla tej jednostki"
                if _id_is_parseable(id_str)
                else "niepoprawne id"
            )
            rejected.append((id_str, reason))
            continue
        norm_value = normalized_section[id_str]
        parsed = _coerce_int(raw_value)
        if parsed is None or parsed != norm_value:
            clamped.append((id_str, raw_value, norm_value))
    return SectionDiff(
        section=name,
        accepted=dict(normalized_section),
        rejected=rejected,
        clamped=clamped,
    )


def _passive_kept(raw_slug: str, normalized_keys: set[str]) -> bool:
    """Czy surowy slug passive przetrwał sanityzację (kanoniczny match z normalize)?

    Reużywa tych samych helperów kanonikalizacji, których używa
    `normalize_roster_unit_loadout` przy budowie `allowed_passive_lookup`
    (`casefold` / `normalize_name` / `ability_identifier`), więc match jest spójny
    z SSOT, nie replikuje logiki dozwolonych slugów.
    """
    candidates = {
        raw_slug,
        raw_slug.casefold(),
        normalize_name(raw_slug),
        ability_identifier(raw_slug),
    }
    return bool(candidates & normalized_keys)


def diff_passive(raw_loadout: dict[str, Any], normalized_passive: dict[str, int]) -> list[str]:
    """Surowe slugi passive (z dodatnią intencją), które NIE przetrwały sanityzacji."""
    raw_passive = raw_loadout.get("passive")
    if not isinstance(raw_passive, dict):
        return []
    normalized_keys = set(normalized_passive.keys())
    rejected: list[str] = []
    for slug, value in raw_passive.items():
        slug_text = str(slug).strip()
        if not slug_text:
            continue
        if (_coerce_int(value) or 0) <= 0:
            continue  # 0/wyłączone — nie jest „odrzuceniem", to świadome off
        if not _passive_kept(slug_text, normalized_keys):
            rejected.append(slug_text)
    return rejected


def validate_loadout(unit, raw_loadout: dict[str, Any], count: int = 1) -> LoadoutDiff:
    """Zbuduj `LoadoutDiff` dla jednostki ORM + surowego loadoutu.

    Reuse SSOT: `normalize_roster_unit_loadout` (sanityzacja) + `calculate_roster_unit_quote`
    (koszt liczony WEWNĘTRZNIE na znormalizowanym loadoucie — quote.py:116).
    """
    raw = raw_loadout if isinstance(raw_loadout, dict) else {}
    normalized = normalize_roster_unit_loadout(unit, raw)

    sections = [diff_section(name, raw.get(name), normalized.get(name, {})) for name in _SECTIONS]

    raw_mode = raw.get("mode")
    raw_mode_str = str(raw_mode).strip().lower() if raw_mode is not None else ""
    normalized_mode = normalized["mode"]
    # Clamp = klient podał mode, którego SSOT nie rozpoznał jako „total"/„per_model"
    # i sprowadził do per_model (normalize: cokolwiek != "total" → "per_model").
    mode_clamped = bool(raw_mode_str) and raw_mode_str not in ("total", "per_model")

    passive_rejected = diff_passive(raw, normalized.get("passive", {}))

    quote = calculate_roster_unit_quote(unit, raw, count)

    return LoadoutDiff(
        unit_id=int(getattr(unit, "id", 0) or 0),
        unit_name=str(getattr(unit, "name", "?") or "?"),
        count=count,
        raw_mode=raw_mode,
        normalized_mode=normalized_mode,
        mode_clamped=mode_clamped,
        sections=sections,
        passive_accepted=dict(normalized.get("passive", {})),
        passive_rejected=passive_rejected,
        selected_role=quote.get("selected_role"),
        selected_total=float(quote.get("selected_total") or 0.0),
        components=dict(quote.get("components") or {}),
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


def validate_loadout_by_id(
    session, unit_id: int, raw_loadout: dict[str, Any], count: int = 1
) -> LoadoutDiff:
    """Wczytaj jednostkę po id (read-only) i zbuduj diff. Raises `UnitNotFoundError`."""
    from app import models

    unit = session.get(models.Unit, unit_id)
    if unit is None:
        raise UnitNotFoundError(f"Jednostka id={unit_id} nie istnieje")
    return validate_loadout(unit, raw_loadout, count)


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


def diff_to_dict(diff: LoadoutDiff) -> dict[str, Any]:
    """Maszynowa serializacja (jsonl-kompatybilny rekord, schema `szop.validate_loadout/v1`)."""
    return {
        "schema": "szop.validate_loadout/v1",
        "unit_id": diff.unit_id,
        "unit_name": diff.unit_name,
        "count": diff.count,
        "mode": {
            "raw": diff.raw_mode,
            "normalized": diff.normalized_mode,
            "clamped": diff.mode_clamped,
        },
        "sections": [
            {
                "section": s.section,
                "accepted": s.accepted,
                "rejected": [{"id": i, "reason": r} for i, r in s.rejected],
                "clamped": [
                    {"id": i, "raw": raw, "normalized": norm} for i, raw, norm in s.clamped
                ],
            }
            for s in diff.sections
        ],
        "passive": {
            "accepted": diff.passive_accepted,
            "rejected": diff.passive_rejected,
        },
        "cost": {
            "selected_role": diff.selected_role,
            "selected_total": diff.selected_total,
            "components": diff.components,
        },
        "has_issues": diff.has_issues,
    }


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
        print(json.dumps(diff_to_dict(diff), ensure_ascii=False))
    else:
        print(format_diff_report(diff))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
