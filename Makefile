.PHONY: dev test test-fast lint check smoke opos-rules-check

PYTHON ?= python

dev:
	$(PYTHON) -m uvicorn app.main:app --reload

test:
	$(PYTHON) -m pytest -q

test-fast:
	$(PYTHON) -m pytest -q -x --tb=short

lint:
	$(PYTHON) -m compileall -q app scripts tests alembic

opos-rules-check:
	$(PYTHON) scripts/opos_rules_check.py

check: lint opos-rules-check test

smoke:
	@echo "Uruchom 'make dev', a następnie sprawdź: logowanie, Armie, edytor rozpiski, quote oraz karty HTML/PDF."
