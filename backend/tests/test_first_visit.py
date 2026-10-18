"""
Первый вход (аудит 2026-10-18): главная показывала примерные корпуса, но не
сохраняла их, а калькуляторы читают только сохранённое — «Рассчитать профиль»
молча ничего не делал. Поведение подтверждено браузерной пробой; здесь — то,
что не должно уехать обратно.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_home_page_saves_the_houses_it_shows_on_first_visit():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert re.search(r"if\s*\(!localStorage\.getItem\(storeKey\)\)\s*saveTabs\(tabs\)", app)


def test_profile_button_says_why_it_is_disabled_without_a_house():
    html = (STATIC / "calculators.html").read_text(encoding="utf-8")
    body = html[html.index("function fillHouseOptions"):]
    body = body[:body.index("profileTabs.forEach")]
    assert "profBtn.disabled = !profileTabs.length" in body
    assert "prof-no-house" in body
    assert re.search(r'id="prof-no-house"[^>]*hidden', html)
    for lang in ("en", "ru", "de", "fr", "pl"):
        text = (STATIC / "i18n" / f"{lang}.js").read_text(encoding="utf-8")
        assert re.search(r"\bprof_no_house:", text) and re.search(r"\bprof_no_house_link:", text), lang
