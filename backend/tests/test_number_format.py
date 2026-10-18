"""
Числа в результатах — в формате языка интерфейса (аудит 2026-10-18).

toFixed() всегда пишет точку: русский, немецкий, французский и польский
интерфейсы показывали «2.5 °C» и «34000 м³/ч» вместо «2,5 °C» и «34 000 м³/ч».
Теперь текст для человека идёт через fmtNum (i18n.js, Intl.NumberFormat), а
числа в параметрах t() форматируются сами. toFixed остаётся там, где нужна
именно точка: координаты SVG, округление числа «+(x).toFixed(n)», value полей.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

# Где точка обязательна: разметка SVG, точки ломаной, округление числа, значение поля
_DOT_REQUIRED = re.compile(r"<(line|text|circle|polyline|polygon|path)\b|=> `\$\{tx\(|type=\"text\" data-num")
_ROUNDING = re.compile(r"\+\((?:[^()]|\([^()]*\))*\)\.toFixed\(")


def _ui_lines():
    for p in sorted(STATIC.glob("*")):
        if p.suffix in (".html", ".js") and p.name not in ("i18n.js", "numfield.js"):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                yield p.name, n, line


def test_no_tofixed_in_displayed_text():
    offenders = []
    for name, n, line in _ui_lines():
        if ".toFixed(" not in line or _DOT_REQUIRED.search(line):
            continue
        if line.count(".toFixed(") != len(_ROUNDING.findall(line)):
            offenders.append(f"{name}:{n}: {line.strip()[:100]}")
    assert not offenders, "текст для человека — через fmtNum(x, n):\n" + "\n".join(offenders)


# Поле ответа сервера прямо в шаблоне: `${d.target_v_min_ms}` — число без формата
# (так проскочили «2–2.5 м/с»). Текстовые поля перечислены явно.
_RAW_FIELD = re.compile(r"\$\{\s*(?:d|data|res|r|c|b|h|z|zq|cfg)\.([a-zA-Z_0-9]+)\s*\}")
_TEXT_FIELDS = {"day", "grade", "id", "name", "label", "status", "color", "key", "house"}


def test_no_raw_server_numbers_in_templates():
    offenders = [f"{name}:{n}: {m.group(0)}" for name, n, line in _ui_lines()
                 for m in _RAW_FIELD.finditer(line) if m.group(1) not in _TEXT_FIELDS]
    assert not offenders, "через fmtNum: " + ", ".join(offenders)


def test_no_tolocalestring_outside_i18n():
    """toLocaleString() без языка берёт язык БРАУЗЕРА, а не интерфейса."""
    offenders = [f"{name}:{n}" for name, n, line in _ui_lines() if ".toLocaleString(" in line]
    assert not offenders, "через fmtNum: " + ", ".join(offenders)


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
  window.LOCALES = { en: { p: 'max {v}' }, ru: { p: 'не больше {v}' }, de: { p: 'höchstens {v}' },
                    fr: { p: 'au plus {v}' } };
  require(process.argv[1]);
  const out = {};
  for (const lang of ['en', 'ru', 'de', 'fr']) {
    I18N.setLang(lang);
    out[lang] = [fmtNum(34000, 0), fmtNum(2.5, 1), fmtNum(1250.5, 1), fmtNum(-0.04, 1),
                 fmtNum(0.123456), fmtNum(null), fmtNum(NaN), t('p', { v: 0.5 }), t('p', { v: '0.5' })];
  }
  console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен node для запуска i18n.js")
def test_fmtnum_follows_interface_language():
    out = subprocess.run(["node", "-e", _NODE, str(STATIC / "i18n.js")],
                         capture_output=True, text=True, check=True).stdout
    got = json.loads(out)
    norm = {k: [s.replace(" ", " ").replace(" ", " ") for s in v] for k, v in got.items()}
    assert norm["en"] == ["34,000", "2.5", "1,250.5", "0.0", "0.123", "—", "—", "max 0.5", "max 0.5"]
    assert norm["ru"] == ["34 000", "2,5", "1 250,5", "0,0", "0,123", "—", "—", "не больше 0,5", "не больше 0.5"]
    assert norm["de"] == ["34.000", "2,5", "1.250,5", "0,0", "0,123", "—", "—", "höchstens 0,5", "höchstens 0.5"]
    assert norm["fr"][:3] == ["34 000", "2,5", "1 250,5"]
