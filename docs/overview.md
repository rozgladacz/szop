# Overview — SZOP (OPR tooling)

## Cel projektu

Aplikacja webowa do przygotowywania **list (Rozpisek)** do gry — autorski system inspirowany One Page Rules ("SZOP"). Backend FastAPI + frontend Jinja2/Vanilla JS, baza SQLite. Tests live alongside Python rule logic.

## Główne obszary

| Obszar | Co | Klucz |
|---|---|---|
| **Rozpiski** | Konkretne listy do gry, składające się z oddziałów wybranych z Armii | Endpoint: `/rosters/{id}`, kalkulacja kosztu: `/quote` |
| **Armie** | Pula oddziałów dostępna w grze; dziedziczy zbrojownie | Hierarchia: wariant trzyma tylko różnice względem bazy |
| **Zbrojownie** | Słownik dostępnych broni + abilities | Costy generowane przez silnik SSOT (`app/services/costs/`) |

## Zależności (kierunek "buduje z")

```
Rozpiski → budowane z → Armii → budowane z → Zbrojowni
```

- Rozpiska wybiera oddziały z konkretnej Armii.
- Armia wybiera bronie z konkretnej Zbrojowni (z możliwością dziedziczenia).
- Zbrojownia jest źródłem prawdy dla broni i abilities.

## Zasady gry — źródło prawdy

Pliki w `app/static/docs/` są **read-only**. Definiują zasady, których oddziały / koszty / abilities muszą przestrzegać. Jeśli kod i `app/static/docs/` są sprzeczne — **zatrzymaj się i opisz rozbieżność**, nie zgaduj znaczenia reguły.

## Użytkownicy

System ma dwa poziomy dostępu:
- **`admin`** — funkcje administracyjne (jawnie odseparowane).
- **`user`** — gracze tworzący rozpiski.

Nie rozszerzaj uprawnień usera bez wyraźnego wymagania.

## Stack technologiczny

- **Backend:** FastAPI 0.110.3, SQLAlchemy 2.0.48, Alembic 1.13.2, uvicorn
- **Frontend:** Vanilla JS (IIFE modules), Jinja2 templates
- **Baza:** SQLite (`data/szop.db`)
- **Reguły gry:** Pydantic v2 + PyYAML (deklaratywny ruleset w `app/rulesets/v1/`, A1+)
- **Testy:** pytest (Python + frontend parity + YAML/procedural parity), Node.js (JS smoke)
- **DevOps:** Docker, Tailscale, Makefile
- **Export:** ReportLab (PDF), openpyxl (Excel)

## Główna struktura katalogów

```
app/
├── config.py          — konfiguracja aplikacji (m.in. OPR_RULES_BACKEND)
├── db.py              — ORM (SQLAlchemy)
├── main.py            — FastAPI entry point
├── models.py          — modele danych (Army, Roster, Weapon, Ability)
├── routers/           — endpointy HTTP (/quote, /rosters/{id}, ...)
├── services/          — logika biznesowa
│   ├── costs/         — silnik kosztów procedural (SSOT/oracle)
│   └── rulesets/      — silnik kosztów YAML (równoległy, parity ≤ 1e-3)
├── rulesets/          — deklaratywne reguły gry
│   └── v1/            — tables.yaml + abilities.yaml + ability_costs.yaml
├── static/            — HTML/CSS/JS + dokumentacja zasad (`docs/`)
└── templates/         — szablony Jinja2

scripts/               — narzędzia (profile_quote.py --backend, reflect_and_improve.py)
seeds/                 — dane startowe
tests/                 — pytest + frontend parity + yaml_backend/ mirror suite
data/                  — SQLite DB + sekrety (.secret_key, .webhook_token)
```

Detale architektury (mapa submodułów `costs/` i `rulesets/`, feature toggle, parity gate): `docs/architecture.md`.
