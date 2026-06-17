APP_DIR := english-reading-trainer
PYTHON := $(CURDIR)/$(APP_DIR)/.venv/bin/python

.PHONY: env-check test test-web ruff-web

env-check:
	@$(PYTHON) -c "import sys; print(sys.executable)"

test: env-check
	@cd $(APP_DIR) && $(PYTHON) -m pytest tests/ -q

test-web: env-check
	@cd $(APP_DIR) && $(PYTHON) -m pytest tests/web -q

ruff-web: env-check
	@cd $(APP_DIR) && $(PYTHON) -m ruff check app/web
