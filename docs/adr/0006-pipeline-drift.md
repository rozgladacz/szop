# ADR-0006 — Pipeline drift DOCX→YAML: drift-only, nie auto-gen

- **Status:** Proposed
- **Data:** 2026-05-26
- **Kontekst:** Strumień A, Faza A4 (`docs/handoffs/HANDOFF_faza-a-4-drift.md`). Wątek startuje po zamknięciu A0–A3+A5, gdzie YAML ruleset (`app/rulesets/v1/abilities.yaml`, `tables.yaml`, `ability_costs.yaml`) został wygenerowany ze stanu `app/data/abilities.py` — **nie z DOCX**. Inwariant `docs/roadmap.md`: *„Reguły gry (`app/static/docs/`) = source of truth. Niedopuszczalna dywergencja kod ↔ DOCX."*

## Decyzja

Wprowadzamy **pipeline drift-only** — zbiór skryptów `scripts/rules_*.py` + cel `make rules-check` + workflow GHA. Pipeline **wykrywa rozbieżności** między `app/static/docs/SZOP.docx` a `app/rulesets/v1/abilities.yaml` (+ `tables.yaml`), ale **nie modyfikuje YAML automatycznie**. Aktualizację YAML wymusza świadoma decyzja człowieka (PR), opcjonalnie odnotowana w whitelist drift.

### Komponenty pipeline'u

| Skrypt | Wejście | Wyjście | Exit codes |
|---|---|---|---|
| `rules_extract.py` | `SZOP.docx` | `build/rules_extracted.yaml` (`{slug, name, type, description}` per zdolność; `cost_fn` **nieobecne** — ręczne w `ability_costs.yaml`) | 0 / 1 (parse error) |
| `rules_drift.py` | `build/rules_extracted.yaml` + `app/rulesets/v1/abilities.yaml` | `build/drift_report.md` (4 typy raportów, sekcje markdown) | 0 / 1 (ERROR) / 2 (WARN-only) |
| `rules_classify_geometry.py` | `app/rulesets/v1/abilities.yaml` | `build/geometry_classification.md` (lista exclusions dla B MVP) | 0 / 1 (parse error) |
| `rules_pdf_check.py` | `SZOP.pdf` + `SZOP.docx` + hash files | (stdout) | 0 / 1 (mismatch) |

### 4 typy raportów drift

| ID | Sytuacja | Severity | Exit code |
|---|---|---|---|
| R1 | Slug istnieje w DOCX, brak w YAML | **ERROR** | 1 |
| R2 | Slug istnieje w YAML, brak w DOCX | WARN | 2 (chyba że whitelisted → 0) |
| R3 | Ten sam slug, różny `description` (po normalizacji NFKC + `.strip()`) | WARN | 2 (chyba że whitelisted → 0) |
| R4 | Ten sam slug, różny `type` (passive/active/aura/handler) | **ERROR** | 1 |

`build/drift_report.md` formatuje każdą rozbieżność jako tabelę markdown z diff inline. Whitelist (`app/rulesets/v1/drift_allowlist.yaml`, opcjonalna) zawiera świadomie dozwolone wpisy z `reason:` + `until_date:` (review co kwartał).

### CI gate

`.github/workflows/rules_drift.yml` triggeruje się **tylko** na PR-ach modyfikujących:
- `app/static/docs/**` (zmiany DOCX/PDF)
- `app/rulesets/**` (zmiany YAML)
- `app/data/abilities.py` (wtórne źródło — póki nie zostanie zdeprecjonowane)

Pipeline nie blokuje PR-ów dotykających inny kod (zero overhead dla niepowiązanych zmian).

### Identyfikacja "zdolności" w DOCX

Heurystyka A4.1 (do walidacji w spike A4.1.1):
- Paragraph style nagłówka (np. `Heading 2`) + paragraph styl opisu (np. `Normal`) — eksperymentalnie potwierdzić w `SZOP.docx`.
- Jeśli styl nieczytelny: fallback na regex (np. `**Bold name**: opis...`) — niespecyfikowany do czasu spike'u.

`slug` w extractcie pozostaje **pusty lub generowany deterministycznie z `name`** (np. `unicodedata.normalize("NFKD", name).lower().replace(" ", "_")`). Stabilność slug-name mapping leży po stronie YAML (`abilities.yaml`), nie DOCX — przy zmianie wording w DOCX `name` się zmienia, ale `slug` w YAML pozostaje. R3 (description mismatch) wówczas trafi, ale R1/R2 nie — chyba że slug-generator z DOCX zaktualizuje slug. Drift-report eksponuje to człowiekowi do decyzji.

## Konsekwencje

**Pozytywne:**
- Inwariant SSOT (DOCX = source of truth) wymuszony automatycznie w CI.
- Pełna kontrola człowieka nad YAML — żadnych "magicznych" aktualizacji wynikających z parsera.
- Pipeline jest niskoinwazyjny: nie modyfikuje plików w repo, generuje tylko `build/*` (gitignored).
- B0 (`docs/roadmap.md`) odblokowany przez `build/geometry_classification.md` — A4.3 dostarcza listę zdolności wymagających pełnej geometrii (exclusion list dla Pareto MVP).
- DOCX↔PDF integrity check (A4.4) wykrywa silent edit jednego pliku — częsta klasa bugów (PDF jako artefakt eksportu).

**Negatywne / koszty:**
- Każde dodanie/edycja zdolności wymaga **dwóch zmian** (DOCX + YAML) i przejścia przez drift gate. Brak auto-codegen oznacza realne tarcie.
- Pipeline jest dev-dependency-heavy: `python-docx` (~1MB), `PyYAML` (już mamy). Doliczone do `requirements-dev.txt`, **nie runtime**.
- Whitelist drift wymaga procesu review (co kwartał) żeby nie obrastał martwymi wpisami.
- False-positives ryzyko przy whitespace/Unicode mismatch — mitigation: `unicodedata.normalize("NFKC", s).strip()` w `rules_drift.py` przed porównaniem.

**Co odkładamy / czego NIE robimy:**
- Auto-codegen DOCX→YAML (alternatywa odrzucona — patrz niżej).
- Embedding-based semantic diff (alternatywa odrzucona).
- `cost_fn` w `rules_extracted.yaml` — DSL kosztu pozostaje ręczne w `ability_costs.yaml`, drift sprawdza tylko shape (slug/name/type/description).
- Text-extract PDF vs DOCX (potencjalne rozszerzenie A4.4 — start od SHA256, dorzucimy jeśli SHA nie wystarczy).

## Alternatywy rozważone

- **Auto-codegen DOCX→YAML.** Odrzucone. Generator musiałby reverse-engineerować `cost_fn` z opisu — to lossy translation. Każda zmiana wording w DOCX nadpisałaby ręcznie dostrojony YAML. Dodatkowo: spadek czytelności PR (diff hard-to-review gdy autogen).
- **Manual review w PR template** (checklist "did you update YAML?"). Odrzucone — nie skaluje się, łatwo o forget, brak weryfikacji.
- **Embedding-based semantic diff** (sentence-transformers do porównania opisów). Odrzucone — wprowadza nondeterminism w CI (model version, prog tolerancji), wymaga GPU lub długiego CPU runtime, false-positives przy synonimach kosztów ("rzut +1" vs "rzut z modyfikatorem +1") znacznie więcej niż NFKC normalize.
- **Tests-only (bez osobnych skryptów):** `tests/test_docx_yaml_parity.py`. Odrzucone — testy uruchamiane przy każdym `pytest`, koszt parsingu DOCX dorzucony do każdego runu. Pipeline jako osobne `make` target jest opt-in i CI-tylko-on-relevant-paths.

## Do rewizji przed promocją na Accepted (po zamknięciu A4)

> Sekcja edytowalna w trakcie A4. Promocja `Proposed → Accepted` w fazie A4.7 po zamknięciu A4.1–A4.6 i empirycznym przejrzeniu pierwszego drift report'u. Każdy poniższy punkt = potencjalna zmiana decyzji przed Accepted.

- [ ] **R3 severity** — czy WARN czy ERROR? Decyzja po empirycznym przejrzeniu drift dla 87 ability defs (oczekiwany duży dryf — YAML był generowany z `ABILITY_DEFINITIONS`, nie z DOCX). Jeśli >50% zdolności ma R3, severity musi zostać WARN żeby PR były przechodne.
- [ ] **R2 severity** — czy WARN ma sens dla wszystkich, czy są zdolności (np. `przygotowanie` skipowane w default) które powinny być implicit-whitelisted bez wpisu?
- [ ] **Whitelist format** — flat list, czy z metadanymi `(reason, until_date, owner)`? Decyzja po pierwszym realnym whitelist (oczekiwane >0 wpisów).
- [ ] **A4.4 PDF check** — czy SHA256 wystarczy, czy dorzucić text-extract diff? Decyzja po obserwacji jak często PDF jest podmieniany niezsynchronizowanie z DOCX.
- [ ] **Hash file location** — `app/static/docs/*.sha256` (z `!*.sha256` exception w `.gitignore`) vs `app/rulesets/v1/source_hashes.yaml` (centralizacja). Decyzja w A4.4.
- [ ] **CI failure mode** — czy ERROR (exit 1) ma blokować merge bezwarunkowo, czy `required check` w GitHub można obejść (admin override)? Polityka — do uzgodnienia.
- [ ] **Whitelist review cadence** — kwartalnie? Per release? Polityka — do uzgodnienia.
- [ ] **Slug generation strategy** — deterministic z `name` (jak wyżej) vs explicit `slug:` w DOCX (np. w komentarzu Word). Decyzja po A4.1 spike — która opcja jest realistyczna w SZOP.docx.

Jeśli któraś rewizja zmienia decyzję strukturalnie (np. embedding-diff wraca jako akceptowalna alternatywa), promocja idzie nie do `Accepted` ale do **nowego ADR z `Supersedes: 0006`** zgodnie z konwencją `docs/adr/README.md`.
