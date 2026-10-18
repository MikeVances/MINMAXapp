"""
JS страниц — в файлах, общие помощники — в одном экземпляре (аудит 2026-10-18:
1254 строки JS внутри calculators.html, fetchJSON и экранирование в трёх копиях,
которые успели разойтись: одна выводила null как «null»).
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_calculators_page_has_no_inline_code():
    html = (STATIC / "calculators.html").read_text(encoding="utf-8")
    inline = [m for m in re.findall(r"<script>(.*?)</script>", html, re.S) if m.strip()]
    assert not inline, f"встроенных блоков: {len(inline)}"


def test_shared_helpers_are_defined_once():
    defs = {}
    for path in STATIC.glob("*.js"):
        src = path.read_text(encoding="utf-8")
        for name in ("fetchJSON", "escapeHtml", "esc"):
            if re.search(rf"(?:function\s+{name}\s*\(|(?:const|let|var)\s+{name}\s*=|window\.{name}\s*=)", src):
                defs.setdefault(name, []).append(path.name)
    assert defs.get("fetchJSON") == ["ui.js"] and defs.get("escapeHtml") == ["ui.js"], defs
    assert "esc" not in defs, defs
