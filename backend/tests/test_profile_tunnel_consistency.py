"""
Профиль и вкладка туннеля судят один корпус одинаково (аудит 2026-10-18, п. 12–13).

Для одного корпуса физическая проверка профиля давала 1.96 м/с при цели «≥3.0»,
а вкладка туннеля — 2.47 м/с при цели 2.5–3.0. Три причины:
  • сечение: туннель умножал среднюю высоту ещё на 0.80, профиль — нет;
  • цель скорости: профиль сравнивал с зашитыми 3.0 м/с, туннель — с таблицей по возрасту;
  • в туннель подставлялось скрытое outside_t = 10 °C из вкладки корпуса.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.core.app_config import load_app_config
from backend.app.core.tunnel_speed_calc import (
    TunnelSpeedInput, calculate_tunnel_speed, target_speed_range,
)

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
CALC_HTML = (STATIC / "calculators.html").read_text(encoding="utf-8")


# ── Цель скорости: одна таблица ────────────────────────────────────────────

def test_summary_reports_the_tunnel_tabs_speed_target_for_the_last_cycle_day(client):
    """Профиль получает цель с сервера — ту же, что вкладка туннеля на этот день."""
    body = client.post("/calc/summary7", json={"house": "1", "birds": 20_000}).json()

    last_day = body["rows"][-1]["day"]
    tunnel = calculate_tunnel_speed(TunnelSpeedInput(
        house_width_m=18, tunnel_height_m=3.0, num_fans=10, fan_capacity_m3h=40_000,
        t_outdoor_db_c=32, rh_outdoor_pct=60, bird_age_days=last_day))

    assert body["tunnel_target_day"] == last_day == max(load_app_config().cycle_days, 7)
    assert (body["tunnel_target_v_min_ms"], body["tunnel_target_v_max_ms"]) \
        == (tunnel.target_v_min_ms, tunnel.target_v_max_ms) == target_speed_range(last_day)


def test_profile_physics_check_has_no_hardcoded_speed_target():
    block = CALC_HTML[CALC_HTML.index("const cls_vtun"):CALC_HTML.index("physBlock = `")]
    assert "tunnel_target_v_min_ms" in CALC_HTML
    assert not re.search(r"v_tun\s*>=\s*[\d.]+\s*\?", block), "цель скорости зашита в странице"


# ── Сечение: одно правило высоты ───────────────────────────────────────────

def _tunnel_house_selector_body() -> str:
    start = CALC_HTML.index("initHouseSelector('tn-house-sel'")
    return CALC_HTML[start:CALC_HTML.index("\n});", start)]


def test_tunnel_tab_takes_the_same_section_height_as_the_profile():
    """Обе вкладки берут высоту из houseSectionHeight, без скрытого множителя."""
    selector = _tunnel_house_selector_body()
    profile = CALC_HTML[CALC_HTML.index("function renderProfileHtml"):]

    assert "houseSectionHeight(tab)" in selector
    assert "houseSectionHeight(tab)" in profile[:600]
    assert not re.search(r"\*\s*0\.8", selector), "туннель снова умножает высоту"


def _section_height_fn() -> str:
    m = re.search(r"function houseSectionHeight\(tab\) \{.*?\n\}", CALC_HTML, re.S)
    assert m, "нет общей функции высоты сечения"
    return m.group(0)


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен node")
def test_section_height_rule():
    cases = [
        ({"height_wall_m": 3.0}, 3.0),
        ({"height_wall_m": 3.0, "height_ridge_m": 5.0}, 4.0),   # двускатная
        ({"height_wall_m": 3.0, "height_ridge_m": 2.5}, 3.0),   # конёк ниже стены — опечатка, берём стену
        ({"height_wall_m": "3", "height_ridge_m": "5"}, 4.0),   # из localStorage бывают строки
        ({}, None),
    ]
    script = _section_height_fn() + f"\nconsole.log(JSON.stringify({json.dumps([c for c, _ in cases])}.map(houseSectionHeight)));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout

    assert json.loads(out) == [want for _, want in cases]


def test_tunnel_calculator_uses_the_entered_section_as_is():
    """Сервер туннеля тоже не прячет поправок: сечение = ширина × введённая высота."""
    r = calculate_tunnel_speed(TunnelSpeedInput(
        house_width_m=15, tunnel_height_m=3.4, num_fans=8, fan_capacity_m3h=36_000,
        t_outdoor_db_c=32, rh_outdoor_pct=50, bird_age_days=42))

    assert r.cross_section_m2 == pytest.approx(15 * 3.4, abs=0.01)
    assert r.air_velocity_ms == pytest.approx(8 * 36_000 / 3600 / (15 * 3.4), abs=0.01)


# ── Наружная температура: только то, что ввёл человек ─────────────────────

def test_tunnel_tab_does_not_prefill_outdoor_temperature_from_the_house():
    assert "tn-tdb" not in _tunnel_house_selector_body()


def test_house_tabs_do_not_carry_a_hidden_outdoor_temperature():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "outside_t" not in app_js
