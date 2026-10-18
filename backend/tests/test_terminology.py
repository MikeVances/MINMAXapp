"""
Русская терминология: pad cooling — «панельное охлаждение», панель — «панель»,
никогда не калька «пэд» (решение владельца проекта). Касается и комментариев,
и описаний API (OpenAPI видят интеграторы), и словарей интерфейса.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_ped_calque_anywhere():
    offenders = []
    for path in list((ROOT / "backend").rglob("*")) + [ROOT / "README.md"]:
        if path.suffix not in {".py", ".js", ".html", ".css", ".md"} or ".venv" in path.parts:
            continue
        if path.name == Path(__file__).name:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"пэд", line, re.I):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert not offenders, "\n".join(offenders)
