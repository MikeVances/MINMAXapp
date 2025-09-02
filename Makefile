PY?=python3
PIP?=$(PY) -m pip
VENV?=.venv

.PHONY: venv run-api test-smoke export-csv seed-json

venv: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt
	$(PY) -m venv $(VENV)
	. $(VENV)/bin/activate; $(PIP) install -U pip
	. $(VENV)/bin/activate; $(PIP) install -r requirements.txt

run-api: venv
	. $(VENV)/bin/activate; uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --reload

test-smoke: venv
	. $(VENV)/bin/activate; $(PY) scripts/smoke_test.py

export-csv: venv
	. $(VENV)/bin/activate; $(PY) scripts/parse_ventilation.py --xlsx "Вентиляция Минимум и максимум.xlsx" --out data/ventilation_required.csv

# Example seed-json rule with default column mapping. Adjust indices if your CSV columns differ.
seed-json: venv
	. $(VENV)/bin/activate; $(PY) scripts/csv_to_seed.py \
	  --csv data/ventilation_required.csv \
	  --out data/vent_profile_seed.json \
	  --day-col 1 --min-temp-col 2 --rv-col 3 --weight-col 5 \
	  --winter-bird-col 8 --winter-kg-col 9 \
	  --spring-bird-col 12 --spring-kg-col 13 \
	  --summer-bird-col 16 --summer-kg-col 17

