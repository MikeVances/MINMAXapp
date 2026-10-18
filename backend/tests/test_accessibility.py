"""
Доступность (аудит 2026-10-18): поля без имени, немые статусы, вкладки без
роли, модальные окна без Escape, графики без описания.

Поведение с клавиатуры (стрелки по вкладкам, Tab по кругу в окне, Escape,
возврат фокуса) подтверждено браузерной пробой. Здесь — разметка и связки,
которые не должны уехать обратно.
"""
from __future__ import annotations

import re
from pathlib import Path

from static_source import page_source

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
read = lambda name: (STATIC / name).read_text(encoding="utf-8")


def test_settings_fields_are_labelled():
    js = read("settings.js")
    assert not re.search(r'<div class="kv"><span>\$\{t\([^)]*\)\}</span><span><input', js)
    assert len(re.findall(r'<label class="kv[^"]*"><span>\$\{t\(', js)) == 6
    assert 'id="saveStatus"' in js and re.search(r'id="saveStatus"[^>]*role="status"', js)


def test_profile_table_inputs_have_names():
    html = page_source("calculators.html")
    row = html[html.index("function rowHTML"):]
    row = row[:row.index("function sourceEntryHTML")]
    assert "aria-label=" in row and "col_day" in row


def test_house_selects_point_to_their_caption():
    html = page_source("calculators.html")
    for pre in ("l", "ev", "tn"):
        assert re.search(rf'id="{pre}-house-sel" aria-labelledby="{pre}-house-lbl"', html), pre
        assert f'id="{pre}-house-lbl"' in html


def test_status_lines_are_live():
    html = page_source("calculators.html")
    for sid in ("prof-status", "buildingStatus", "heaterStatus"):
        assert re.search(rf'id="{sid}"[^>]*role="status"', html), sid
    assert re.search(r'id="feedbackStatus"[^>]*role="status"', read("feedback.js"))


def test_charts_are_images_with_a_name():
    assert re.search(r'<svg [^`]*role="img" aria-label="\$\{escapeHtml\(title', page_source("calculators.html"))


def test_tabs_use_the_shared_tablist():
    ui = read("ui.js")
    assert "setAttribute('role', 'tablist')" in ui and "aria-selected" in ui and "ArrowRight" in ui
    assert "Tabs.init(elTabs)" in read("app.js") and "Tabs.sync(elTabs)" in read("app.js")
    html = page_source("calculators.html")
    assert "Tabs.init(toolTabs)" in html and "Tabs.sync(toolTabs)" in html
    assert "setAttribute('role', 'tabpanel')" in html


def test_modals_are_dialogs_closed_by_escape():
    ui = read("ui.js")
    assert "e.key === 'Escape'" in ui and "e.key !== 'Tab'" in ui and "_returnFocus" in ui
    index, fb = read("index.html"), read("feedback.js")
    assert re.search(r'class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modalTitle"', index)
    assert re.search(r'role="dialog" aria-modal="true" aria-labelledby="feedbackTitle"', fb)
    assert "Dialog.open(elModal, elModalCancel" in read("app.js")
    assert "Dialog.open(modal, textEl" in fb
