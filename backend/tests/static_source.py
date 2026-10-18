"""
Исходник страницы для структурных тестов: разметка + её локальные скрипты.

JS calculators.html вынесен в calculators.js, calibration-house.js и
growth-profiles.js. Тесты, проверявшие «что делает страница», читали один
HTML-файл; теперь они читают страницу так, как её собирает браузер: HTML и
каждый подключённый ./*.js по порядку. Словари i18n/*.js не включаются —
это данные, а не код страницы.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def page_source(page: str) -> str:
    html = (STATIC / page).read_text(encoding="utf-8")
    parts = [html]
    for src in re.findall(r'<script src="\./([^"?]+\.js)', html):
        if not src.startswith("i18n/"):
            parts.append((STATIC / src).read_text(encoding="utf-8"))
    return "\n".join(parts)
