"""
Нормы физической проверки профиля — по Cobb Broiler Management Guide 2021, гл. 9
(сверено с PDF 2026-10-19).

«≥18 м³/ч·м²» (§9.1: 0.3 м³/мин·м²) — норма УСТАНОВЛЕННЫХ вентиляторов
минвентиляции; раньше рядом с ней стоял биологический Qmin первого дня (~1.8),
и строка всегда выглядела как недобор в 10 раз. Туннель (§9.7): 165–200 м³/ч·м²
и смена воздуха 40–50 с — цвет «норма» теперь с тех же границ.
"""
from __future__ import annotations

import re
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "app" / "static" / "calculators.js").read_text(encoding="utf-8")


def _row(key: str) -> str:
    m = re.search(rf"t\('{key}'\).*", JS)
    assert m, key
    return m.group(0)


def test_biological_qmin_is_not_compared_with_the_fan_norm():
    assert "≥18" not in _row("phys_min_vent_check")


def test_installed_min_vent_fans_are_checked_against_cobb():
    assert "minFansCap / S_floor" in JS and "minCapM2 >= 18" in JS
    assert "phys_min_fans_norm" in _row("phys_min_fans_check")


def test_colour_thresholds_match_the_printed_ranges():
    assert re.search(r"qMaxM2 >= 165 \? 'ok'", JS)
    assert re.search(r"T_exch <= 50 \? 'ok'", JS)
    assert "[40–50]" in JS and "[40–60]" not in JS
