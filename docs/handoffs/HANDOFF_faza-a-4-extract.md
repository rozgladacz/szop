# HANDOFF — faza-a-4-extract

> **Wątek:** Sub-wątek `faza-a-4-drift`. A4.1 — parser `SZOP.docx` → `build/rules_extracted.yaml` (`{slug, name, type, description}` per zdolność). Spike parsera + implementacja + golden testy.
> **Status:** Done (A4.1 zamknięte, gotowy do `/handoff-archive`)
> **Utworzony:** 2026-05-26
> **Ostatnia aktualizacja:** 2026-05-26 (po A4.1.6 — 85 abilities extracted, 29 testów zielonych, pełna suita 844/844)

## Cel

Dostarczyć pierwsze ogniwo pipeline'u A4 (ADR-0006): czysty, deterministyczny extractor który czyta `app/static/docs/SZOP.docx` i emituje `build/rules_extracted.yaml` z listą zdolności w schemacie kompatybilnym z `app/rulesets/v1/abilities.yaml`. Cel jest **wąski**: schema `{slug, name, type, description}`. `cost_fn` i koszty pozostają poza extractem (ręczne w `ability_costs.yaml` — patrz ADR-0006). Sub-wątek **blokuje A4.2** (drift report nie ma wejścia bez `rules_extracted.yaml`).

Parent: [HANDOFF_faza-a-4-drift.md](HANDOFF_faza-a-4-drift.md) (Faza A4.1 z planu A4). ADR: [docs/adr/0006-pipeline-drift.md](../adr/0006-pipeline-drift.md).

## Zablokowane pliki / katalogi

- `scripts/rules_extract.py` (NEW) — główny skrypt
- `tests/test_rules_extract.py` (NEW) — golden test + sanity (≥87, <200)
- `tests/fixtures/rules_extract/` (NEW) — minimalna fixture DOCX (1-2 zdolności) dla golden testu
- `requirements-dev.txt` — `python-docx>=1.1.0`
- `.gitignore` — `build/` (jeśli brak)

**Read-only przez sub-wątek:**
- `app/static/docs/SZOP.docx` — źródło prawdy (force-tracked w git mimo `.gitignore` `app/static/docs/`)
- `app/rulesets/v1/abilities.yaml` — referencja schema/konwencji `yaml.safe_dump` (nie modyfikujemy)
- `app/data/abilities.py` — wtórne źródło 87 ability defs (do walidacji liczby w sanity check)

## Blokuje / Blokowane przez

- **Blokuje:** Faza A4.2 (drift report) w głównym wątku [HANDOFF_faza-a-4-drift](HANDOFF_faza-a-4-drift.md) — bez `build/rules_extracted.yaml` drift nie ma wejścia.
- **Blokowane przez:** nic (ADR-0006 + bootstrap A4 zrobione w sesji 2026-05-26).

## Gałąź git

- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza A4.1 — DOCX extract

#### A4.1.1 — Spike parsera DOCX ✅ (2026-05-26)

- [x] Wersja `python-docx`: **1.2.0** (latest stable)
- [x] `build/spike_paragraphs.txt` — pełen dump 225 paragrafów + 7 tabel z `SZOP.docx`. Inwentaryzacja:
  - **225 paragrafów, 7 tabel**
  - **Tylko 2 style:** `Normal` (216), `List Paragraph` (9) — **żadnych Headingów**
  - Tabele: T0 (defense), T1 (toughness), T2 (passive ability prices, 31 wpisów), T3 (range), T4 (AP), T5 (blast), T6 (weapon traits)
  - Zdolności w paragrafach 88+, format `<Name>: <description>` lub `<Name>(X): <description>`
  - Sekcje delimitowane przez paragraf końca dwukropkiem: `Pasywne:`, `Aktywne:`, `Aury:`, `Broni:` (powtórzone w `Dodatkowe zdolności:` od para 140 i `Zasady Armii:` od para 163)
  - **Start parsingu:** pierwszy `^Pasywne:$` (skip game rules 0-30)
  - **Stop parsingu:** `Koszt oddziału jest sumą kosztów modeli` (para 191) — sekcja formuł
  - Multi-paragraph descriptions: Transport span 111-114 (połączyć następne paragrafy nie pasujące do regex `Name: desc`)
- [x] **Decyzja parser:** content-based state machine (NIE style-based — niemożliwe). Stan = `(section, sub_section)`. Per linia: regex `^([\w/\(\)X\sĄĆĘŁŃÓŚŹŻąćęłńóśźż\.]+?):\s+(.+)$` → capture name + description. Type derywowany z section header.
- [x] **Decyzja schema:** Pomijamy Table 2 (ceny passive) — to dane dla `ability_costs.yaml`, nie `abilities.yaml`. A4.1 extract czyta TYLKO paragrafy.

#### A4.1.2 — Dependency ✅

- [x] `requirements-dev.txt`: dodany `python-docx>=1.1.0,<2.0`
- [x] `pip install "python-docx>=1.1.0,<2.0"` → 1.2.0 + lxml-6.1.1
- [x] Smoke: `python -c "import docx; print(docx.__version__)"` → 1.2.0

#### A4.1.3 — Implementacja `scripts/rules_extract.py` ✅

- [x] Argparse z defaults: `--input app/static/docs/SZOP.docx`, `--output build/rules_extracted.yaml`
- [x] Pydantic v2 model `ExtractedAbility` + `RulesExtract` (frozen, extra=forbid)
- [x] Type literal: `passive | active | aura | weapon | unknown` (mapowanie: `Pasywne→passive`, `Aktywne→active`, `Aury→aura`, `Broni→weapon`)
- [x] Parser: content-based state machine, start na `^Pasywne:$`, stop na `Koszt oddziału jest sumą`, ignore `Dodatkowe zdolności:`/`Zasady Armii:...`
- [x] **Fix critical bug:** paragraph text split przez `\n` przed processing — Word soft line break (Shift+Enter) łączył wiele zdolności w jednym paragrafie (Porażenie/Zguba/Dezintegracja w para 188). Bez tego brakowało 7 zdolności.
- [x] Slug generator z explicit Polish char pre-replace: `ł→l`, `Ł→L` (NFKD nie decomposuje Ł/ł — są to osobne Latin chars w Unicode). Bez tego "Łatanie" → "atanie", "Ociężałość" → "ociezaosc".
- [x] Serializer YAML zgodny z `abilities.yaml`: `safe_dump(..., allow_unicode=True, sort_keys=False, width=10000)`
- [x] `build/` auto-tworzony przez `output_path.parent.mkdir(parents=True, exist_ok=True)`
- [x] Error handling: `FileNotFoundError` + `RuntimeError` (invalid docx) → exit 1 + stderr message
- [x] Encoding: wszystkie pliki Python otwarte z `encoding='utf-8'`
- [x] Smoke: `python scripts/rules_extract.py` → **85 abilities extracted** (vs 87 w `ABILITY_DEFINITIONS` — różnica to **realny drift** który A4.2 wykryje, nie bug parsera, patrz Notatki)

#### A4.1.4 — Testy `tests/test_rules_extract.py` ✅ (29 testów)

- [x] Golden test: **programmatic-generated fixture DOCX** (przez `python-docx` w `tmp_path` fixture) — eliminuje potrzebę commitowania binary docx. 5 zdolności w fixture (passive×2, active×3 — w tym 2 split przez embedded `\n`).
- [x] CLI smoke: `main(["--input", fixture, "--output", out])` → exit 0 + valid YAML.
- [x] Sanity na realnym `SZOP.docx`:
  - `80 <= len <= 100` (relaxed z `>= 87` — DOCX ma 85, różnica vs YAML jest realnym driftem nie bugiem parsera)
  - Wszystkie slugi unikalne
  - Wszystkie pola non-empty + min 5 chars
  - Wszystkie type ∈ {passive, active, aura, weapon}
  - Core abilities present: bohater, zasadzka, zwiadowca, transport, mag, ap
  - Type distribution: passive >= 30, weapon >= 15, active >= 5, aura >= 2
- [x] `make_slug` parametrized: 16 casów (Polish chars decomposing, Łł non-decomposing, parens, slashes, special).
- [x] `validate_uniqueness` — pass on unique, raise `ValueError` on duplicate.
- [x] Edge: missing file → exit 1 + "ERROR" w stderr.
- [x] Edge: invalid DOCX (txt z `.docx` extensions) → exit 1.
- [x] Edge: DOCX bez `Pasywne:` start marker → empty list (bez raise).

#### A4.1.5 — Gitignore ✅

- [x] `.gitignore`: dodany `build/` (sekcja "A4 pipeline output")
- [x] `git check-ignore -v build/rules_extracted.yaml` → potwierdzone ignored przez `.gitignore:21:build/`

#### A4.1.6 — Smoke + commit ✅

- [x] `python scripts/rules_extract.py` → 85 abilities → `build/rules_extracted.yaml`
- [x] Inspekcja manual: schema poprawny, opisy zachowane, slugi sensowne (z exception 9 driftów slug/name vs YAML — patrz Notatki)
- [x] `python -m pytest tests/test_rules_extract.py -v` → **29/29 passed**
- [x] `python -m pytest -q` → **844/844 passed** (815 baseline + 29 nowe)
- [ ] Commit (do zrobienia po archiwizacji wątku, razem z innymi zmianami sesji): `A4.1: rules_extract.py — DOCX → rules_extracted.yaml (parser + 29 testów + ADR-0006 Proposed)`
- [ ] `/handoff-archive faza-a-4-extract`

## Pliki dotknięte

- `scripts/rules_extract.py` (NEW, ~240 LOC) — parser DOCX + `make_slug` + `extract_abilities` + `validate_uniqueness` + `write_yaml` + CLI `main()`
- `tests/test_rules_extract.py` (NEW, 29 testów) — slug parametrized + real DOCX sanity + golden programmatic fixture + edge cases (missing/invalid/empty)
- `requirements-dev.txt` — `python-docx>=1.1.0,<2.0`
- `.gitignore` — `build/` (sekcja A4 pipeline output)
- `build/rules_extracted.yaml` (gitignored) — output, 85 abilities
- `build/spike_paragraphs.txt` (gitignored) — spike A4.1.1 dump, do referencji
- `docs/handoffs/HANDOFF_faza-a-4-extract.md` — odznaczenia + decyzje + notatki

## Hipotezy / pytania otwarte

- **H1:** `SZOP.docx` ma jednolitą strukturę "Heading + paragraf opisu" per zdolność. Spike A4.1.1 to ustali. **Jeśli nie** — parser musi mieć fallback (regex, tabela, mix).
- **H2:** `type` (passive/active/aura/handler) **nie** jest explicit w DOCX — trzeba derywować z opisu (keywords: "aura", "Akcja:", etc.) lub zostawić `"unknown"` i wymusić ręczne uzupełnienie po stronie drift report (R4). Decyzja po spike.
- **H3:** Zdolności w tabeli — `python-docx` ma `doc.tables[i].rows[j].cells[k].text`, ale traci structured info per komórka. Jeśli zdolności są w tabeli, parser musi to obsłużyć osobno.
- **H4:** Slug-from-name może kolidować dla podobnych nazw ("Atak", "Atak +1"). Jeśli kolizja — extractor raise z listą duplikatów (forc human review).

## Jak zweryfikować

```powershell
# Po A4.1.1 — spike
python -c "from docx import Document; d=Document('app/static/docs/SZOP.docx'); print(f'paragraphs: {len(d.paragraphs)}, tables: {len(d.tables)}'); from collections import Counter; print(Counter(p.style.name for p in d.paragraphs).most_common(10))"

# Po A4.1.3 — implementacja
python scripts/rules_extract.py --input app/static/docs/SZOP.docx --output build/rules_extracted.yaml
Get-Content build/rules_extracted.yaml | Select-Object -First 30

# Po A4.1.4 — testy
python -m pytest tests/test_rules_extract.py -v

# Po A4.1.6 — pełna weryfikacja
python -m pytest -q
git status --short  # build/ nie powinien się pokazać
```

## Decyzje

- 2026-05-26: Slug `faza-a-4-extract` (sub `faza-a-4-drift`). Powód: spike DOCX parsing = niepewny czas, izolacja od reszty pipeline'u. Wzorzec: `faza-a-2-dsl-quote` (sub `faza-a`) — archived 2026-05-23.
- 2026-05-26: Parser DOCX = `python-docx>=1.1.0` (standard, czyste API, struktura paragrafów/tabel/styli). Alternatywy odrzucone: `docx2txt` (traci tabele), unzip+XML parse (boilerplate).
- 2026-05-26: Schema extract = `{slug, name, type, description}` (BEZ `cost_fn`). Powód: ADR-0006 drift-only — `cost_fn` ręczne w `ability_costs.yaml`, drift sprawdza tylko shape.
- 2026-05-26: Slug generator deterministyczny: `unicodedata.normalize("NFKD", name).encode("ascii","ignore").decode().lower().replace(" ", "_")`. Stabilność slug w YAML nie zależy od stabilności wording DOCX (`name` może drift, slug nie — chyba że name zmieni się tak że NFKD da inny wynik, wtedy R1+R2 to wykryją).

## Notatki / odkrycia w trakcie

- 2026-05-26: HANDOFF utworzony jako sub `faza-a-4-drift`. Branch `Faza_A`. Następny krok: A4.1.1 spike — uruchomić `python -c` inspekcję `SZOP.docx` żeby zdecydować parser strategy (style-based vs regex vs tabela).
- 2026-05-26: A4.2 w głównym wątku `faza-a-4-drift` czeka na `build/rules_extracted.yaml` z tego sub-wątku. Po `/handoff-archive faza-a-4-extract` parent może wystartować A4.2.
- 2026-05-26 (po A4.1.1): **Brak Headingów w SZOP.docx** (tylko `Normal`/`List Paragraph`) → style-based parser OUT, content-based state machine IN. Sekcje delimitowane paragrafami końca dwukropkiem (`Pasywne:`/`Aktywne:`/`Aury:`/`Broni:`). Start na pierwszym `Pasywne:`, stop na `Koszt oddziału jest sumą`. Table 2 (passive prices) pominięta — to dane dla `ability_costs.yaml`, nie `abilities.yaml`.
- 2026-05-26 (po A4.1.3 v1): **Critical bug discovery #1** — paragraphy DOCX zawierają wewnętrzne `\n` (Word soft line break = Shift+Enter) które łączą wiele zdolności w jeden paragraf. 6 paragrafów z embedded `\n` = 8 utraconych zdolności (Para 188 = 3 zdolności w 1 paragrafie: Porażenie/Zguba/Dezintegracja). Fix: `paragraph.text.split("\n")` przed processing.
- 2026-05-26 (po A4.1.3 v1): **Critical bug discovery #2** — slug NFKD bug. `Ł`/`ł` nie mają NFKD decomposition (są to osobne Latin chars w Unicode, nie precomposed z combining marks). `encode("ascii", "ignore")` je dropuje. Bez fix: "Łatanie" → "atanie", "Ociężałość" → "ociezaosc". Fix: explicit pre-replace `ł→l`, `Ł→L`.
- 2026-05-26 (po A4.1.3 v2): Po obu fixach: **85 abilities extracted**. Vs 87 w `ABILITY_DEFINITIONS`/`abilities.yaml`. Różnica = **realny drift** który A4.2 wykryje:
  - YAML splituje `Szybki/Wolny` na 2 (`szybki`+`wolny`), DOCX trzyma jako 1 (`szybki_wolny`)
  - YAML splituje `Dobrze/źle strzela` na 2 (`dobrze_strzela`+`zle_strzela`), DOCX trzyma jako 1
  - YAML używa innych slugów dla Polish nazw konceptów: `burzaca`/`masywny`/`rozrywajacy`/`unik` vs DOCX `przelamanie`/`sekcje`/`podwojny`/`przewidywalny`
  - YAML ma abstract `aura` ability, DOCX nie
  - DOCX ma `AP(X)` weapon ability, YAML nie listuje
- 2026-05-26 (A4.1.4): 29 testów napisanych, wszystkie zielone. Programmatic-generated fixture DOCX w `tmp_path` eliminuje potrzebę commitowania binary fixture.
- 2026-05-26 (A4.1.6): Pełna suita `pytest -q` → **844/844 passed** (815 baseline + 29 A4.1). Wątek gotowy do archiwizacji — A4.2 w głównym `faza-a-4-drift` może wystartować z `build/rules_extracted.yaml` jako wejściem.
