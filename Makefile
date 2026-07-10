APP_DIR := english-reading-trainer
PYTHON := $(CURDIR)/$(APP_DIR)/.venv/bin/python

.PHONY: env-check serve test test-web test-browser coverage coverage-check schema-check ruff ruff-web verify

env-check:
	@$(PYTHON) -c "import sys; print(sys.executable)"

test: env-check
	@cd $(APP_DIR) && $(PYTHON) -m pytest tests/ -q

test-web: env-check
	@cd $(APP_DIR) && $(PYTHON) -m pytest tests/web -q

ruff-web: env-check
	@cd $(APP_DIR) && $(PYTHON) -m ruff check app/web

serve: env-check
	@cd $(APP_DIR) && $(PYTHON) -m app.web.launcher

test-browser: env-check
	@cd $(APP_DIR) && $(PYTHON) -m pytest tests/web/test_reader_toolbar_state.py -q

coverage: env-check
	@cd $(APP_DIR) && $(PYTHON) -m pytest --cov=app --cov-report=xml:coverage.xml tests/

coverage-check: coverage
	@cd $(APP_DIR) && $(PYTHON) scripts/check_coverage.py coverage.xml

schema-check: env-check
	@cd $(APP_DIR) && $(PYTHON) scripts/check_schema.py

ruff: env-check
	@cd $(APP_DIR) && $(PYTHON) -m ruff check app tests scripts

verify: ruff coverage-check schema-check test-browser
