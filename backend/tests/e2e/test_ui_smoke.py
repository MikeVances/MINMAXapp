"""
Smoke-тест интерфейса в настоящем браузере (Playwright, Chromium).

Зачем: остальные тесты читают код страниц как текст или гоняют API. Регрессию
«Рассчитать профиль падает на каждом нажатии» (rhRaw is not defined, 5541d34 →
a036f9b) они пропустили — её поймала только ручная проба в браузере. Здесь
каждая страница открывается, главные кнопки нажимаются, и любая ошибка JS
(pageerror, console.error) валит тест.

Сервер — отдельный uvicorn на свободном порту с данными во временном каталоге:
рабочий data/ не трогается, Telegram не настроен, /feedback перехвачен.

Локально без Playwright тест пропускается; в CI (env CI) — падает, чтобы
пропуск не выглядел зелёным прогоном.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover — зависит от окружения
    if os.getenv("CI"):
        raise
    pytest.skip("нужен playwright (requirements-e2e.txt)", allow_module_level=True)


HOUSE = {"id": "A", "birds": 30000, "age_days": 28, "cap": 400000,
         "length_m": 120, "width_m": 16, "height_wall_m": 2.5, "height_ridge_m": 4.5,
         "num_fans": 10, "fan_cap_m3h": 40000}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    data = Path(tempfile.mkdtemp(prefix="minmax_e2e_"))
    shutil.copytree(ROOT / "data" / "growth_profiles" / "builtin", data / "gp" / "builtin")
    env = dict(os.environ,
               GROWTH_PROFILES_DIR=str(data / "gp"), APP_CONFIG_JSON=str(data / "app_config.json"),
               THERMAL_CONFIG_JSON=str(data / "thermal.json"), THEME_CSS=str(data / "theme.css"),
               WRITE_TOKEN="", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/settings/app-config", timeout=1)
                break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError(proc.stderr.read().decode())
                time.sleep(0.1)
        else:
            raise RuntimeError("сервер не поднялся за 10 с")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    ctx = browser.new_context(base_url=base_url)
    ctx.route(re.compile(r"/feedback$"), lambda r: r.fulfill(status=200, body="{}"))
    ctx.add_init_script(f"localStorage.setItem('vent_mvp_tabs_v1', {json.dumps(json.dumps([HOUSE]))})")
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
    pg.errors = errors
    yield pg
    ctx.close()


def _open(page, path, tool=None):
    page.goto(path)
    page.wait_for_load_state("networkidle")
    if tool:
        page.click(f'.tool-tab[data-tool="{tool}"]')


def _fill(page, values: dict):
    for sel, v in values.items():
        page.fill(sel, str(v))


def _profile_calculated(page):
    """Результат, а не ошибка: блок #prof-summary показывается и с текстом ошибки
    (старый код ловил ReferenceError rhRaw в try и выводил его туда же) —
    поэтому проверяется таблица по дням: при ошибке там только div.danger."""
    page.click("#prof-calc-btn")
    page.wait_for_selector("#prof-summary table", timeout=10_000)


def test_home_page_saves_and_switches_houses(page):
    _open(page, "/")
    page.fill("#birds", "25000")
    page.click("#addTab")
    page.click("#tabs .tab >> nth=0")
    assert page.input_value("#birds") == "25000"
    assert page.errors == []


def test_profile_calculation(page):
    _open(page, "/calculators.html", "profile")
    _profile_calculated(page)
    assert page.errors == []


def test_leakage_calculation(page):
    _open(page, "/calculators.html", "leakage")
    page.click("#l-calc-btn")
    page.wait_for_selector("#l-results:not([hidden])", timeout=10_000)
    assert page.errors == []


def test_leakage_two_point_test(page):
    """Вторая точка теста: показатель n и инфильтрация при 4 Па появляются в результате."""
    _open(page, "/calculators.html", "leakage")
    page.fill("#l-fan-cap2", "68000")
    page.fill("#l-pressure2", "60")
    page.click("#l-calc-btn")
    page.wait_for_selector("#l-q4-row:not([hidden])", timeout=10_000)
    assert page.text_content("#l-n").strip() != ""
    assert page.errors == []


def test_evap_calculation(page):
    _open(page, "/calculators.html", "evap")
    _fill(page, {"#ev-length": 120, "#ev-width": 16, "#ev-tdb": 32, "#ev-rh": 45,
                 "#ev-fans": 400000, "#ev-pad-length": 24, "#ev-padh": 1.5, "#ev-birds": 30000, "#ev-eta": 75})
    page.click("#evap-btn")
    page.wait_for_selector("#ev-results:not([hidden])", timeout=10_000)
    assert page.text_content("#ev-r-eta").startswith("75 %")   # заданный КПД дошёл до расчёта
    assert page.errors == []


def test_tunnel_calculation(page):
    _open(page, "/calculators.html", "tunnel")
    _fill(page, {"#tn-width": 16, "#tn-height": 3.5, "#tn-fans": 10, "#tn-fan-cap": 40000,
                 "#tn-tdb": 32, "#tn-rh": 50, "#tn-age": 35, "#tn-birds": 30000})
    page.click("#tunnel-btn")
    page.wait_for_selector("#tn-results:not([hidden])", timeout=10_000)
    assert page.errors == []


def test_tunnel_with_pads_in_the_inlet(page):
    """Панель во впуске: толщина открывается после выбора типа, в ответе — её ΔP."""
    _open(page, "/calculators.html", "tunnel")
    _fill(page, {"#tn-width": 16, "#tn-height": 3.5, "#tn-fans": 10, "#tn-fan-cap": 40000, "#tn-fan-cap25": 36000,
                 "#tn-tdb": 32, "#tn-rh": 50, "#tn-age": 35, "#tn-birds": 30000})
    assert page.is_disabled("#tn-pad-thickness")
    page.select_option("#tn-pad-type", "7090")
    page.select_option("#tn-pad-thickness", "150")
    page.click("#tunnel-btn")
    page.wait_for_selector("#tn-r-pad-row:not([hidden])", timeout=10_000)
    assert "Pa" in page.text_content("#tn-r-pad-dp") or "Па" in page.text_content("#tn-r-pad-dp")
    assert page.errors == []


def test_cooling_test_start_mark_undo_cancel(page):
    _open(page, "/calculators.html", "calibration")
    _fill(page, {"#tStartInside": 28, "#tOutside": 5})
    page.click("#timerBtn")
    page.click('button[data-zone="0"]')
    page.click('button[data-undo="0"]')
    page.click("#timerBtn")
    assert page.evaluate("localStorage.getItem('cooling_test_v1')") is None
    assert page.errors == []


def test_every_tool_tab_shows_its_panel(page):
    """Вкладка без панели: 22bec38 искал панели до того, как они разобраны."""
    _open(page, "/calculators.html")
    for tool in page.eval_on_selector_all(".tool-tab", "els => els.map(e => e.dataset.tool)"):
        page.click(f'.tool-tab[data-tool="{tool}"]')
        assert page.is_visible(f"#panel-{tool}"), tool
    assert page.errors == []


def test_settings_page_renders(page):
    _open(page, "/settings.html")
    page.wait_for_selector("#cycle_days")
    assert page.errors == []


@pytest.mark.parametrize("path", ["/", "/calculators.html", "/settings.html"])
def test_version_line_on_every_page(page, path):
    _open(page, path)
    page.wait_for_selector("#appVersion", timeout=5_000)
    assert page.text_content("#appVersion").startswith("v")


def test_every_language_renders_without_errors(page):
    _open(page, "/calculators.html", "profile")
    for lang in ("ru", "de", "fr", "pl", "en"):
        page.click(f'.lang-btn[data-lang="{lang}"]')
    _profile_calculated(page)
    assert page.errors == []


# ── Направление производства корпуса ─────────────────────────────────────────

TURKEY_IDS = {"but6-toms", "but6-hens", "converter-toms", "converter-hens",
              "converter-novo-toms", "converter-novo-hens"}


def _house_page(browser, base_url, house: dict):
    """Своя страница: общий page кладёт корпус при КАЖДОЙ загрузке и затёр бы то,
    что сохранила главная. Здесь корпус пишется, только если хранилище пусто."""
    ctx = browser.new_context(base_url=base_url)
    ctx.route(re.compile(r"/feedback$"), lambda r: r.fulfill(status=200, body="{}"))
    ctx.add_init_script(f"if (!localStorage.getItem('vent_mvp_tabs_v1')) "
                        f"localStorage.setItem('vent_mvp_tabs_v1', {json.dumps(json.dumps([house]))})")
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(f"pageerror: {e}"))
    return ctx, pg


def _growth_options(page) -> set[str]:
    page.wait_for_function("document.querySelectorAll('#prof-growth-select option').length > 0")
    return set(page.eval_on_selector_all("#prof-growth-select option", "els => els.map(e => e.value)"))


def test_production_line_filters_growth_profiles(browser, base_url):
    ctx, page = _house_page(browser, base_url, HOUSE)
    try:
        _open(page, "/")
        page.wait_for_selector("#production option[value=turkey]", state="attached")
        # Неготовые направления видны, но выбрать их нельзя
        assert page.eval_on_selector("#production option[value=duck]", "o => o.disabled")
        assert page.input_value("#production") == "broiler_floor"
        page.select_option("#production", "turkey")
        page.click("#sumBtn")

        _open(page, "/calculators.html", "profile")
        assert _growth_options(page) == TURKEY_IDS
        assert page.input_value("#prof-growth-select") in TURKEY_IDS
        assert page.errors == []
    finally:
        ctx.close()


def test_house_saved_before_lines_keeps_its_turkey_profile(browser, base_url):
    # Корпус до 2026-10-28: направления нет, но выбран профиль индейки — это корпус
    # индейки. Иначе фильтр счёл бы профиль чужим и подставил бройлерный
    ctx, page = _house_page(browser, base_url, {**HOUSE, "growth_profile_id": "converter-toms"})
    try:
        _open(page, "/calculators.html", "profile")
        assert _growth_options(page) == TURKEY_IDS
        page.wait_for_function("document.querySelector('#prof-growth-select').value === 'converter-toms'")
        _open(page, "/")
        page.wait_for_selector("#production option[value=turkey]", state="attached")
        assert page.input_value("#production") == "turkey"
    finally:
        ctx.close()


def test_broiler_house_lists_broiler_profiles_only(browser, base_url):
    ctx, page = _house_page(browser, base_url, HOUSE)
    try:
        _open(page, "/calculators.html", "profile")
        options = _growth_options(page)
        assert "ross308" in options and not options & TURKEY_IDS
    finally:
        ctx.close()


BREEDER_IDS = {"ross308-ps-females", "ross308-ps-males", "cobb500-ff-females", "cobb-mx-males"}


def test_broiler_breeder_line_defaults_to_females_and_calculates_stages(browser, base_url):
    ctx, page = _house_page(browser, base_url, HOUSE)
    try:
        _open(page, "/")
        page.wait_for_selector("#production option[value=broiler_breeders_floor]", state="attached")
        page.select_option("#production", "broiler_breeders_floor")
        page.click("#sumBtn")

        _open(page, "/calculators.html", "profile")
        assert _growth_options(page) == BREEDER_IDS
        # По умолчанию для родительского стада выбирается женский профиль Ross 308 PS
        assert page.input_value("#prof-growth-select") == "ross308-ps-females"
        assert page.is_visible("#prof-turkey-stage")
        assert page.input_value("#prof-stage") == "rearing"
        assert page.input_value("#prof-first-day") == "1"
        assert page.input_value("#prof-last-day") == "140"
        _profile_calculated(page)

        # В продуктивном периоде меняются дни (141..448), скорость туннеля (3.0 м/с) и добавляется пометка о петухах
        page.select_option("#prof-stage", "production")
        assert page.input_value("#prof-first-day") == "141"
        assert page.input_value("#prof-last-day") == "448"
        assert page.input_value("#prof-tunnel-speed") == "3"
        _profile_calculated(page)
        assert "♂" in page.text_content("#prof-summary")
        assert page.errors == []
    finally:
        ctx.close()


def test_tunnel_calculation_modes_and_live_sync(page):
    _open(page, "/calculators.html", "profile")
    assert page.input_value("#prof-tunnel-mode") == "speed"
    assert page.is_visible("#prof-tunnel-speed-wrap")
    assert page.is_hidden("#prof-tunnel-exch-s-wrap")

    # Режим по воздухообмену: поля секунд и об/ч видны и синхронизированы (3600 / s = ach)
    page.select_option("#prof-tunnel-mode", "exchange")
    assert page.is_hidden("#prof-tunnel-speed-wrap")
    assert page.is_visible("#prof-tunnel-exch-s-wrap")
    assert page.is_visible("#prof-tunnel-ach-wrap")

    page.fill("#prof-tunnel-exch-s", "45")
    assert page.input_value("#prof-tunnel-ach") == "80"
    page.fill("#prof-tunnel-ach", "72")
    assert page.input_value("#prof-tunnel-exch-s") == "50"
    _profile_calculated(page)

    # Режим «по большему из двух»: видны все поля (скорость + с + об/ч)
    page.select_option("#prof-tunnel-mode", "max_both")
    assert page.is_visible("#prof-tunnel-speed-wrap")
    assert page.is_visible("#prof-tunnel-exch-s-wrap")
    assert page.is_visible("#prof-tunnel-ach-wrap")
    _profile_calculated(page)
    assert page.errors == []
