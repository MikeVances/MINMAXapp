PY?=python3
PIP?=$(PY) -m pip
VENV?=.venv

.PHONY: venv run-api test test-e2e test-smoke

venv: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt
	$(PY) -m venv $(VENV)
	. $(VENV)/bin/activate; $(PIP) install -U pip
	. $(VENV)/bin/activate; $(PIP) install -r requirements.txt

run-api: venv
	. $(VENV)/bin/activate; uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --reload

# Эталоны физики и известные баги (xfail strict) — сервер не нужен
test: venv
	. $(VENV)/bin/activate; $(PIP) install -q -r requirements-dev.txt
	. $(VENV)/bin/activate; $(PY) -m pytest

# Браузерный smoke-тест страниц (Playwright + Chromium; сервер поднимает сам)
test-e2e: venv
	. $(VENV)/bin/activate; $(PIP) install -q -r requirements-dev.txt -r requirements-e2e.txt
	. $(VENV)/bin/activate; $(PY) -m playwright install chromium
	. $(VENV)/bin/activate; $(PY) -m pytest backend/tests/e2e

# Проверка ЖИВОГО сервера (сначала make run-api)
test-smoke: venv
	. $(VENV)/bin/activate; $(PY) scripts/smoke_test.py
