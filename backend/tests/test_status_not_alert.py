"""
Сообщения — строкой статуса у кнопки, а не alert() (аудит 2026-10-18).
alert блокирует страницу и исчезает после «OK»: на телефоне его закрывают не
читая. Статус (ui.js: setStatus) остаётся на месте и пересобирается при смене языка.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _code_lines(path: Path):
    """Строки без комментариев // и <!-- -->: упоминание alert в пояснении не считается."""
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    for lineno, line in enumerate(text.splitlines(), 1):
        yield lineno, re.sub(r"(^|\s)//.*$", "", line)


def test_no_alert_anywhere_in_the_interface():
    offenders = [f"{p.name}:{n}: {line.strip()[:80]}"
                 for p in STATIC.rglob("*") if p.suffix in (".js", ".html")
                 for n, line in _code_lines(p) if re.search(r"\balert\s*\(", line)]
    assert not offenders, "\n".join(offenders)


def test_status_lines_are_announced():
    """role=status — экранный диктор зачитывает появившийся текст."""
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    calc = (STATIC / "calculators.html").read_text(encoding="utf-8")
    assert re.search(r'id="tabsStatus"[^>]*role="status"', index)
    assert re.search(r'id="saveCalibrationStatus"[^>]*role="status"', calc)


_NODE = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const listeners = {};
const ctx = { window: {}, document: { addEventListener: (n, f) => (listeners[n] = listeners[n] || []).push(f) } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(process.argv[1], 'ui.js'), 'utf8'), ctx);
const cls = new Set();
const el = { textContent: '', hidden: true, classList: { add: c => cls.add(c), remove: c => cls.delete(c) } };
let lang = 'en';
ctx.window.setStatus(el, () => lang === 'en' ? 'Saved' : 'Сохранено', 'ok');
const first = [el.textContent, el.hidden, [...cls]];
lang = 'ru'; (listeners['i18n:change'] || []).forEach(f => f());
const second = el.textContent;
ctx.window.setStatus(el, null);
lang = 'en'; (listeners['i18n:change'] || []).forEach(f => f());
console.log(JSON.stringify({ first, second, cleared: [el.textContent, el.hidden, [...cls]] }));
"""


def test_set_status_follows_language_and_clears():
    if shutil.which("node") is None:
        pytest.skip("нужен node")
    out = json.loads(subprocess.run(["node", "-e", _NODE, str(STATIC)],
                                    capture_output=True, text=True, check=True).stdout)
    assert out["first"] == ["Saved", False, ["c-ok"]]
    assert out["second"] == "Сохранено"
    assert out["cleared"] == ["", True, []]
