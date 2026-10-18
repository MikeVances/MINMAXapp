"""
Оформление живёт только в styles.css (+ data/theme.css): ни inline style="…",
ни прямых el.style.* в разметке и скриптах интерфейса (этап 2 выноса стилей,
2026-10-18). Иначе тема площадки снова перестаёт доходить до части элементов.

Разрешено: атрибуты рисования SVG (fill/stroke) — это данные графика, и они
всё равно берут цвет из var(--…).
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

FORBIDDEN = [
    (re.compile(r"""\sstyle\s*=\s*["']"""), "inline style= (класс в styles.css)"),
    (re.compile(r"\.style\.[a-zA-Z]"), "el.style.* (hidden или setTone/setBg/setEdge из ui.js)"),
    (re.compile(r"\.cssText\b"), "cssText (класс в styles.css)"),
]


def test_static_has_no_inline_styles():
    offenders = []
    files = [p for p in STATIC.rglob("*") if p.suffix in (".html", ".js")]
    assert files, "статика не найдена"
    for path in files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for rx, hint in FORBIDDEN:
                if rx.search(line):
                    offenders.append(f"{path.relative_to(STATIC)}:{lineno}: {hint}: {line.strip()[:90]}")

    assert not offenders, "\n".join(offenders)


def test_tone_classes_used_by_scripts_exist_in_css():
    """setTone(el, 'x') / class="c-…" должны находить правило, иначе цвет молча пропадёт."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"^\.([a-z0-9_-]+)\s*\{", css, re.M))
    used = set()
    for path in STATIC.rglob("*.js"):
        src = path.read_text(encoding="utf-8")
        used |= {"c-" + t for t in re.findall(r"setTone\([^,]+,\s*'([a-z0-9-]+)'", src)}
        used |= {"bg-" + t for t in re.findall(r"setBg\([^,]+,\s*'([a-z0-9-]+)'", src)}
        used |= {"edge-" + t for t in re.findall(r"setEdge\([^,]+,\s*'([a-z0-9-]+)'", src)}
    assert used, "вызовы setTone/setBg/setEdge не найдены"
    assert not used - defined, sorted(used - defined)
