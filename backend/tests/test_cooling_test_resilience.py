"""
Тест остывания на телефоне (аудит 2026-10-18): 20–60 минут с градусником,
и до сих пор его стирали перезагрузка страницы, погасший экран и случайное
двойное касание, а ошибочную отметку нельзя было снять.

Поведение подтверждено браузерной пробой (старт → отметки → отмена отметки →
перезагрузка → восстановление корпуса и таймера → завершение). Здесь — то,
что не должно уехать обратно.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
JS = (STATIC / "calibration.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = JS.index(f"function {name}(")
    depth, i = 0, JS.index("{", start)
    for j in range(i, len(JS)):
        depth += {"{": 1, "}": -1}.get(JS[j], 0)
        if depth == 0:
            return JS[i:j]
    raise AssertionError(name)


def test_every_state_change_is_persisted():
    for name in ("beginRunning", "recordMark", "undoMark", "cancelTest", "finishTest"):
        assert "persistTest()" in _function(name), name
    assert "localStorage.setItem(TEST_STORE_KEY" in _function("persistTest")


def test_unfinished_test_is_restored_on_load_unless_stale():
    body = _function("restoreTest")
    assert "TEST_MAX_AGE_MS" in body and "beginRunning(saved, true)" in body
    assert "houseId" in body, "тест возвращается к своему корпусу"
    assert re.search(r"addEventListener\('DOMContentLoaded',\s*restoreTest\)", JS)


def test_a_mark_can_be_undone():
    assert "data-undo" in _function("renderTapPanel")
    body = _function("undoMark")
    assert ".pop()" in body and "length <= 1" in body, "точка старта не снимается"


def test_double_tap_does_not_record_two_marks():
    body = _function("recordMark")
    assert "MIN_MARK_GAP_S" in body and re.search(r"<\s*MIN_MARK_GAP_S\)\s*return", body)


def test_screen_is_kept_on_while_the_test_runs():
    assert "navigator.wakeLock.request('screen')" in _function("keepScreenOn")
    assert "keepScreenOn()" in _function("beginRunning")
    assert "releaseScreen()" in _function("stopTimer")
    assert re.search(r"visibilitychange[\s\S]{0,80}keepScreenOn\(\)", JS)


def test_timer_texts_survive_apply_dom():
    """applyDOM переписывает текст по data-i18n: кнопка идущего теста показывала «Старт»."""
    assert "elTimerBtn.dataset.i18n = key" in _function("setTimerBtn")
    assert not re.search(r"elTimerBtn\.textContent\s*=\s*t\('btn_", JS.replace(_function("setTimerBtn"), ""))
    html = (STATIC / "calculators.html").read_text(encoding="utf-8")
    tag = re.search(r'<div id="timerStatus"[^>]*>', html).group(0)
    assert "data-i18n" not in tag and 'role="status"' in tag
