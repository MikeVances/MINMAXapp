"""
Ошибки и несохранённые правки (аудит 2026-10-18, п. 9–11).

  • ошибка сервера начиналась с пути pydantic: «outside_t: …», «points.8.body_weight_g»
    (индекс точки, а не день 14) — теперь подпись поля из формы и день;
  • калькуляторы показывали ошибку через alert() и оставляли прежний результат;
  • переключение вкладки корпуса и смена профиля молча теряли ввод;
  • пустое поле размера молча брало прежнее значение — стереть его было нельзя.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

_NODE = """
  const store = {};
  global.window = global;
  global.localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
  global.CustomEvent = class { constructor(n, o) { this.type = n; this.detail = o && o.detail; } };
  global.document = {
    readyState: 'complete', documentElement: {}, title: '',
    addEventListener() {}, dispatchEvent() {}, querySelectorAll: () => [],
    createElement: () => ({ dataset: {}, classList: { toggle() {} }, appendChild() {} }),
    body: { prepend() {}, dataset: {} },
  };
  const [dir, cases] = [process.argv[1], JSON.parse(process.argv[2])];
  require(dir + '/i18n/en.js'); require(dir + '/i18n/ru.js'); require(dir + '/i18n.js');
  const out = {};
  for (const lang of ['en', 'ru']) {
    I18N.setLang(lang);
    out[lang] = cases.map(([body, sent]) => apiErrorText(body, 422, sent));
  }
  console.log(JSON.stringify(out));
"""

LE = {"type": "less_than_equal", "msg": "Input should be less than or equal to 50", "ctx": {"le": 50}}
POINTS = [{"day": d, "body_weight_g": 100 * d} for d in (0, 1, 2, 3, 4, 5, 6, 7, 14)]
CASES = [
    # 1. Поле формы — подпись, а не имя переменной
    ({"detail": [dict(LE, loc=["body", "outside_t"])]}, None),
    # 2. Точка профиля: индекс 8 → день 14 (тело запроса — JSON-строка, как в fetch)
    ({"detail": [dict(LE, loc=["body", "points", 8, "body_weight_g"])]}, json.dumps({"points": POINTS})),
    # 3. Без тела запроса — порядковый номер, не индекс с нуля
    ({"detail": [dict(LE, loc=["body", "points", 8, "body_weight_g"])]}, None),
    # 4. Служебное поле без подписи — без пути
    ({"detail": [dict(LE, loc=["body", "calibration_problem"])]}, None),
    # 5. Несколько полей настроек
    ({"detail": [dict(LE, loc=["body", "cycle_days"]), dict(LE, loc=["body", "safety_factor_qmin"])]}, None),
]


@pytest.fixture(scope="module")
def texts():
    if shutil.which("node") is None:
        pytest.skip("нужен node")
    out = subprocess.run(["node", "-e", _NODE, str(STATIC), json.dumps(CASES)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_validation_errors_name_the_form_field_not_the_api_path(texts):
    en, ru = texts["en"], texts["ru"]
    technical = re.compile(r"outside_t|points|body_weight_g|cycle_days|safety_factor|calibration_problem|\.\d+\.")

    assert not [s for s in en + ru if technical.search(s)], en + ru
    assert en[0].startswith("Outdoor temperature")
    assert ru[0].startswith("Температура снаружи")


def test_profile_point_error_names_the_day(texts):
    assert texts["en"][1].startswith("Day 14 · Weight")
    assert texts["en"][2].startswith("№ 9 · Weight")


def test_unlabelled_field_is_shown_without_a_path(texts):
    assert not texts["en"][3].startswith(":")
    assert ":" not in texts["en"][3].split("50")[0]


# ── Калькуляторы: ошибка у результата, не alert ─────────────────────────────

def _code_lines(path: Path):
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip().startswith("//"):
            yield n, line


def test_calculators_do_not_use_alert():
    offenders = [n for n, line in _code_lines(STATIC / "calculators.html") if re.search(r"\balert\(", line)]
    assert not offenders, f"alert() в calculators.html, строки {offenders}"


def test_failed_calculation_hides_the_previous_result():
    html = (STATIC / "calculators.html").read_text(encoding="utf-8")
    fn = html[html.index("function showToolError"):html.index("function clearToolError")]
    assert "results.hidden = true" in fn
    for tool, results in (("leakage", "l-results"), ("tunnel", "tn-results"), ("evap", "ev-results")):
        assert f"showToolError('{tool}', '{results}'" in html


# ── Несохранённые правки ────────────────────────────────────────────────────

def test_house_tab_switch_commits_or_blocks_instead_of_discarding():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    click = app[app.index("b.onclick"):app.index("elTabs.appendChild")]
    assert "commitBeforeLeaving()" in click
    assert "addEventListener('beforeunload'" in app


def test_empty_dimension_field_clears_the_value():
    """Пустое поле размера = «не задано», а не прежнее значение."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    body = app[app.index("function readFormToTab"):app.index("const MAX_HOUSES")]
    assert not re.search(r"read\(el\w+,\s*tab\.(length_m|width_m|height_\w+|num_\w+|\w*fan_cap\w*)", body)


def test_bird_count_is_required():
    assert re.search(r'<input id="birds"[^>]*\brequired\b', (STATIC / "index.html").read_text(encoding="utf-8"))


def test_profile_editor_asks_before_discarding_edits():
    html = (STATIC / "calculators.html").read_text(encoding="utf-8")
    guard = html[html.index("function mayDiscardEdits"):html.index("document.addEventListener('DOMContentLoaded', loadProfile)")]
    assert guard.count("mayDiscardEdits()") >= 2          # смена профиля и смена корпуса
    assert "beforeunload" in guard
