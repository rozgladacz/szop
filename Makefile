
.PHONY: dev test test-fast test-parity lint smoke check safe-edit profile \
        rules-check rules-extract rules-extract-md rules-drift rules-classify rules-sources-check

# Force UTF-8 for every Python invocation in this Makefile.  Windows console
# defaults to cp1250 which crashes any script that prints arrows or Polish
# unit names (e.g. scripts/profile_quote.py).  See AGENTS.md "String Handling".
export PYTHONIOENCODING := utf-8

dev:
	python -m uvicorn app.main:app --reload

test:
	pytest -q

test-fast:
	pytest -q -x --tb=short

# Strumień A, Faza A3 — CI parity gate. Wymusza `both_assert` na pełnej
# suite parity (`test_ruleset_parity.py`) oraz uruchamia mirror suite
# `tests/yaml_backend/` pod yaml. Awaria = drift YAML vs procedural > 1e-3.
# Patrz `docs/handoffs/HANDOFF_faza-a.md` i `docs/adr/0004-cost-dsl.md`.
test-parity:
	OPR_RULES_BACKEND=both_assert pytest -q tests/test_ruleset_parity.py
	OPR_RULES_BACKEND=yaml pytest -q tests/yaml_backend/

lint:
	python -m ruff check app/

check:
	make lint && make test-fast

safe-edit:
	@python -c "import sys, pathlib; [open(f,'r',encoding='utf-8').read() for f in sys.argv[1:] if pathlib.Path(f).exists()]" $(FILES)

smoke:
	@echo "=== Smoke test checklist (ręczny) ==="
	@echo "1. Zbrojownia       -> czy lista broni jest widoczna?"
	@echo "2. Edytor Armii     -> czy przy oddziale widoczne sa bronie?"
	@echo "3. Rozpiski         -> czy mozna zaznaczyc oddzial i otworzyc edytor?"
	@echo "Uruchom: make dev  i sprawdz powyzsze w przegladarce."

# Performance profiling for cost engine.  Usage:
#   make profile                            # default ROSTER=10, BACKEND=procedural
#   make profile ROSTER=13                  # any roster id
#   make profile BACKEND=yaml               # profile YAML backend (A5)
#   make profile ROSTER=10 BACKEND=both_assert
# Compare results with docs/PERFORMANCE.md baseline (A5 ma sekcję per-backend).
# PYTHONPATH=. so the script can `import app.*` when run from the repo root.
ROSTER ?= 10
BACKEND ?= procedural
profile:
	PYTHONPATH=. python scripts/profile_quote.py $(ROSTER) --backend $(BACKEND)

# ---------------------------------------------------------------------------
# Strumień A, Faza A4 — pipeline drift detection (ADR-0006).
# Pełen orchestrator: `make rules-check` uruchamia wszystkie 5 skryptów
# sekwencyjnie, propaguje pierwszy non-zero exit (fail-fast).
#
# Exit codes per skrypt:
#   rules_extract.py         : 0 / 1 (parse error)
#   rules_extract_md.py      : 0 / 1 (parse error)
#   rules_drift.py           : 0 / 1 (ERROR) / 2 (WARN)
#   rules_classify_geometry  : 0 / 1
#   rules_sources_check.py   : 0 / 1 (mismatch) / 2 (missing)
#
# Targety selektywne dla debugowania pojedynczego etapu. CI gate (A4.6 GHA
# workflow `rules_drift.yml`) triggeruje `make rules-check` na PR-ach
# modyfikujących app/static/docs/**, app/rulesets/**, app/data/abilities.py.
# Kolejność: source-check (najszybszy fail), extract×2 (potrzebne do drift),
# classify (niezależny od drift), drift LAST. Powód: rules-drift może wyjść
# z exit=2 (WARN-only) co stops chain — kolejność daje pełen artifact set
# (rules_extracted.yaml, rules_md.yaml, geometry_classification.md,
# drift_report.md) NAWET gdy chain stops at drift.
rules-check: rules-sources-check rules-extract rules-extract-md rules-classify rules-drift
	@echo "==> rules-check: pipeline complete (all 5 steps passed)"

rules-extract:
	python scripts/rules_extract.py

rules-extract-md:
	python scripts/rules_extract_md.py

# rules-drift wymaga `build/rules_extracted.yaml` (z rules-extract). Make
# dispatcher zapewnia poprawną kolejność przez explicit dependency wyżej.
rules-drift:
	python scripts/rules_drift.py

rules-classify:
	python scripts/rules_classify_geometry.py

rules-sources-check:
	python scripts/rules_sources_check.py
