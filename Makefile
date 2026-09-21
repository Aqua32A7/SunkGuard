.PHONY: demo test compare thesis-eval verify help

PYTHON ?= python3

help:
	@echo "SunkGuard Development & Verification Commands:"
	@echo "  make demo         - Run live acceptance demo reporting measured values"
	@echo "  make test         - Run full SDK test suite"
	@echo "  make compare      - Compare baseline vs SunkGuard head-to-head (seed 8)"
	@echo "  make thesis-eval  - Run formal thesis gate evaluation across seeds 21..50"
	@echo "  make verify       - Verify bit-identical deterministic reproducibility"

demo:
	$(PYTHON) cli.py demo

test:
	$(PYTHON) -m unittest discover tests/ -v

compare:
	$(PYTHON) cli.py compare --seed 8 --ticks 150

thesis-eval:
	$(PYTHON) cli.py thesis-eval --start-seed 21 --end-seed 50

gate2-eval:
	$(PYTHON) scripts/eval_gate2.py

verify:
	$(PYTHON) cli.py verify-reproducibility --seed 42

serve:
	$(PYTHON) -m uvicorn server:app --host 0.0.0.0 --port 8000

frontend:
	npm run dev

build-frontend:
	npm run build
