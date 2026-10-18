"""
Числовые поля интерфейса (аудит 2026-10-18, UX-ввод).

type="number" + parseFloat/Number(el.value) молча портили ввод:
  • «2,5» → value "" → +"" = 0 на сервер, или parseFloat → 2 (дробь срезана);
  • «35 000» голов → parseInt → 35;
  • step="0.5"/"100" не давал отправить 31.3 °C или 12 345 голов.
Теперь все поля — type="text" data-num, разбор и проверка в numfield.js,
неверный ввод — ошибка у поля. Эти тесты не дают вернуть старый способ.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _ui_files():
    return [p for p in STATIC.glob("*") if p.suffix in (".html", ".js")]


def test_no_native_number_inputs():
    offenders = [f"{p.name}:{n}" for p in _ui_files() if p.name != "numfield.js"
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if re.search(r"""type\s*=\s*["']number["']""", line)]
    assert not offenders, "type=number вместо data-num: " + ", ".join(offenders)


# Чтение поля «в обход» разбора. <select> с индексом (selEl.value) — не ввод числа.
_RAW_READ = [
    re.compile(r"\b(parseFloat|parseInt|Number)\([^)]*\.value\b"),
    re.compile(r"\+\s*document\.getElementById\([^)]*\)\.value"),
    re.compile(r"\+\s*el\w*\.value\b"),
]


def test_no_raw_numeric_reads_of_inputs():
    offenders = []
    for p in _ui_files():
        if p.name == "numfield.js":
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            hits = [m.group(0) for rx in _RAW_READ for m in rx.finditer(line)]
            # <select> с индексом корпуса (sel/selEl/houseSel) — не ввод числа
            if [h for h in hits if not re.search(r"sel\w*\.value", h, re.I)]:
                offenders.append(f"{p.name}:{n}: {line.strip()[:90]}")
    assert not offenders, "читать через NumField.value:\n" + "\n".join(offenders)


def _scripts_using_numfield():
    return {p.name for p in STATIC.glob("*.js") if p.name != "numfield.js"
            and "NumField." in p.read_text(encoding="utf-8")}


@pytest.mark.parametrize("page", sorted(p.name for p in STATIC.glob("*.html")))
def test_pages_using_numfield_load_it_first(page):
    """Без <script src=numfield.js> страница падает на NumField is not defined."""
    html = (STATIC / page).read_text(encoding="utf-8")
    users = _scripts_using_numfield()
    loads = [m.group(1) for m in re.finditer(r'<script src="\./([\w.-]+?)(?:\?[^"]*)?"', html)]
    needs = "NumField." in html or "data-num" in html or any(s in users for s in loads)
    if not needs:
        return
    assert "numfield.js" in loads, f"{page} использует NumField, но не подключает numfield.js"
    first_user = min((loads.index(s) for s in loads if s in users), default=len(loads))
    assert loads.index("numfield.js") < first_user, f"{page}: numfield.js подключён позже потребителя"


# Разбор числа: (ввод, язык интерфейса, ожидание; None — пусто, "nan" — ошибка)
PARSE_CASES = [
    ("2,5", "ru", 2.5), ("2.5", "ru", 2.5), ("-5,5", "ru", -5.5), ("−5", "ru", -5),
    ("25 000", "ru", 25000), ("25 000", "ru", 25000), ("35 000", "fr", 35000),
    ("20,000", "en", 20000), ("2,5", "en", 2.5), ("1.250", "de", 1250), ("1.25", "de", 1.25),
    ("2,500", "ru", 2.5), ("0", "ru", 0), (".5", "ru", 0.5),
    ("", "ru", None), ("   ", "ru", None),
    ("abc", "ru", "nan"), ("1,2,3", "ru", "nan"), ("1,234.5", "en", "nan"), ("1e3", "en", "nan"),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен node для запуска numfield.js")
def test_numfield_parse_cases():
    script = """
      global.window = global; global.document = { addEventListener() {} };
      require(process.argv[1]);
      const cases = JSON.parse(process.argv[2]);
      console.log(JSON.stringify(cases.map(([s, l]) => {
        const v = window.NumField.parse(s, l);
        return Number.isNaN(v) ? 'nan' : v;
      })));
    """
    out = subprocess.run(["node", "-e", script, str(STATIC / "numfield.js"),
                          json.dumps([[s, l] for s, l, _ in PARSE_CASES])],
                         capture_output=True, text=True, check=True).stdout
    got = json.loads(out)
    bad = [(s, l, exp, g) for (s, l, exp), g in zip(PARSE_CASES, got) if g != exp]
    assert not bad, bad
