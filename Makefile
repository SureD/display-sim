PYTHON ?= python3

.PHONY: install test lint format typecheck gallery docs-check build check

install:
	$(PYTHON) -m pip install -e '.[dev]'

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

typecheck:
	$(PYTHON) -m mypy

gallery:
	$(PYTHON) -m tv_sim gallery

docs-check:
	$(PYTHON) scripts/check_docs.py

build:
	$(PYTHON) -m build

check: lint typecheck test docs-check
