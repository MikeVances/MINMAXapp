"""
Известные ошибки из ревью 2026-10-16 (TODO.md, раздел P0/P1).

Каждый тест описывает ПРАВИЛЬНОЕ поведение и помечен xfail(strict=True):
  - сейчас он падает → «ожидаемо», CI зелёный;
  - после исправления он пройдёт → strict превращает это в ПАДЕНИЕ с XPASS,
    и маркер нужно снять. Так тест служит проверкой «от обратного»: он
    доказуемо падал на старом коде и доказуемо проходит на новом.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.core.calc_core import CalcInput, compute

REPO_ROOT = Path(__file__).resolve().parents[2]


def _calc(profile, birds: int, age_days: int, outside_t: float, outside_rh: float = 60.0):
    ci = CalcInput(
        birds=birds, age_days=age_days, mode="summer", display_unit="per_bird",
        outside_t=outside_t, outside_rh=outside_rh,
    )
    return compute(profile, ci)


@pytest.mark.xfail(reason="TODO P0: Qmax по полному теплу 10.62 вместо явного 6.90 (+54 %)")
def test_qmax_heat_balance_uses_sensible_heat_only(profile):
    """
    День 35 (W = 2.296 кг), внутри 20 °C, снаружи 10 °C (туннель выключен), UA = 0.
    Воздух уносит только ЯВНОЕ тепло (ρ·Cp·ΔT), скрытое уходит с паром:
      H_явн = 6.90 × 2.296^0.75 × 10 000 = 128 690 Вт
      ρ     = 353.05 / 283.15 = 1.2469 кг/м³
      Qmax  = 128 690 × 3600 / (1.2469 × 1006 × 10) = 36 937 м³/ч  (3.694 м³/ч·гол)
    Сейчас код даёт 56 851 м³/ч — с полным теплом 10.62.
    """
    r = _calc(profile, birds=10_000, age_days=35, outside_t=10.0)

    assert r.q_max_m3h == pytest.approx(36_937.1, rel=1e-3)


@pytest.mark.xfail(reason="TODO P0: мощность туннеля масштабируется от введённого поголовья")
def test_tunnel_capacity_does_not_depend_on_entered_bird_count(profile):
    """
    В туннельном режиме Qmax — это установленные вентиляторы корпуса.
    Если ввести вдвое меньше птицы, вентиляторов меньше не станет.
    """
    full = _calc(profile, birds=10_000, age_days=35, outside_t=30.0)
    half = _calc(profile, birds=5_000, age_days=35, outside_t=30.0)

    assert full.tunnel_active and half.tunnel_active
    assert half.q_max_m3h == pytest.approx(full.q_max_m3h, rel=1e-9)


@pytest.mark.xfail(reason="TODO P0: Qmin молча обрезается до мощности установки")
def test_api_does_not_silently_cut_qmin_to_capacity(client):
    """
    Qmin по CO₂ = 9 460 м³/ч, установлено только 5 000 м³/ч.
    Минимум — биологическое требование: его нельзя «подогнать» под железо,
    недостаток мощности должен показываться как предупреждение.
    """
    payload = dict(
        house="1", birds=10_000, age_days=21, mode_id="summer",
        outside_t=25.0, outside_rh=60.0, user_max_m3h=5_000,
    )
    body = client.post("/calc/minmax", json=payload).json()

    assert body["q_min_m3h"] == pytest.approx(9_460.0)


@pytest.mark.xfail(reason="TODO P1: KeyError → 500 на недопустимой паре тип пэда / толщина")
def test_evap_cooling_rejects_unknown_pad_thickness_with_422(client):
    """У SANHE 5090 нет толщины 200 мм — это ошибка ввода (422), а не падение сервера (500)."""
    payload = dict(
        house_length_m=120, t_outdoor_db_c=35, rh_outdoor_pct=40, total_fan_m3h=500_000,
        pad_type="5090", pad_thickness_mm=200, pad_length_m=40, pad_height_m=1.8,
    )
    assert client.post("/calc/tools/evap_cooling", json=payload).status_code == 422


@pytest.mark.xfail(reason="TODO P0: пути к данным относительные — зависят от CWD")
@pytest.mark.parametrize(
    "module, attr",
    [
        ("backend.app.core.day_master", "DAY_MASTER_PATH"),
        ("backend.app.core.app_config", "APP_CONFIG_PATH"),
        ("backend.app.core.building_thermal", "THERMAL_CONFIG_PATH"),
        ("backend.app.core.flock_storage", "FLOCKS_DATA_DIR"),
    ],
)
def test_default_data_paths_do_not_depend_on_working_directory(module, attr, tmp_path):
    """
    Импорт в чистом процессе: без env-переменных и из чужого каталога.
    Путь по умолчанию должен быть абсолютным и вести в каталог data/ проекта.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("DAY_MASTER_JSON", "APP_CONFIG_JSON", "THERMAL_CONFIG_JSON", "FLOCKS_DATA_DIR")}
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = f"import {module} as m, os; print(os.path.abspath(str(m.{attr})) == str(m.{attr}))"

    out = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    assert out == "True"
