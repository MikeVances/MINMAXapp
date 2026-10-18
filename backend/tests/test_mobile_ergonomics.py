"""
Мобильная эргономика и контраст (аудит 2026-10-18). Интерфейсом пользуются с
телефона в корпусе: касаемые меньше 44 px, рамка поля 1.2:1 и браузерно-синие
ссылки там не работают. Переключатель языка и кнопка обратной связи, прибитые
к углу экрана, закрывали навигацию и правую колонку чисел.

Тесты читают styles.css и считают контраст по токенам. Раскладку на живой
странице проверяет браузерная проба: здесь — то, что должно не уехать обратно.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
ROOT = Path(__file__).resolve().parents[2]
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")


# ─── Контраст WCAG по токенам ────────────────────────────────────────────────

def _token(css: str, name: str) -> str:
    m = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", css)
    assert m, f"токен --{name} не найден"
    return m.group(1)


def _luminance(hex_color: str) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(int(hex_color[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted([_luminance(a), _luminance(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _rule(css: str, selector: str) -> str:
    """Тело первого правила с точно таким селектором вне @media."""
    m = re.search(rf"^{re.escape(selector)}\s*\{{([^}}]*)\}}", css, re.M)
    assert m, f"правило {selector} не найдено"
    return m.group(1)


def _media_block(css: str, query: str) -> str:
    start = css.find(f"@media {query}")
    assert start >= 0, f"@media {query} не найден"
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        depth += {"{": 1, "}": -1}.get(css[j], 0)
        if depth == 0:
            return css[i + 1:j]
    raise AssertionError("незакрытый @media")


def test_field_border_is_visible_against_the_card():
    """WCAG 1.4.11: граница поля — 3:1 к фону. Старая --border давала 1.2:1."""
    border, card, surface = (_token(CSS, n) for n in ("field-border", "card", "surface"))
    assert _contrast(border, card) >= 3.0
    assert _contrast(border, surface) >= 3.0
    for sel in ('input[type="number"], input[type="text"]', "select"):
        assert "var(--field-border)" in _rule(CSS, sel), sel


def test_light_theme_example_keeps_field_border_contrast():
    """Пример светлой темы тоже задаёт рамку поля — иначе останется тёмная из styles.css."""
    light = (ROOT / "data" / "theme.example.css").read_text(encoding="utf-8")
    light = light[light.index("Светлая тема"):]
    assert _contrast(_token(light, "field-border"), _token(light, "card")) >= 3.0


def test_links_take_the_accent_colour():
    """Без правила для a ссылка браузерно-синяя: #0000ee на карточке — 1.9:1."""
    assert "var(--accent)" in _rule(CSS, "a")
    assert _contrast(_token(CSS, "accent"), _token(CSS, "card")) >= 4.5


# ─── Касаемые и раскладка ────────────────────────────────────────────────────

def test_touch_targets_are_44px_on_coarse_pointer():
    block = _media_block(CSS, "(pointer: coarse)")
    m = re.search(r"([^{}]+)\{\s*min-height:\s*44px", block)
    assert m, "min-height: 44px под pointer: coarse не найден"
    selectors = {s.strip() for s in m.group(1).split(",")}
    for need in (".btn", ".tab", ".tool-tab", 'input[type="text"]', "select"):
        assert need in selectors, need


def test_lang_switcher_is_not_pinned_to_the_corner():
    """Фиксированный угол закрывал кнопки навигации на 900–1480 px."""
    rules = re.findall(r"\.lang-switcher\s*\{([^}]*)\}", CSS)
    assert rules, "правило .lang-switcher не найдено"
    assert not any("fixed" in r for r in rules), "ни одно правило, в т. ч. под @media"


def test_feedback_button_is_pinned_only_when_the_margin_fits_it():
    """В потоке под содержимым; в угол — только если поле у контейнера 980 px
    шире кнопки (~130 px с отступом): иначе она закрывает правую колонку чисел."""
    assert "fixed" not in _rule(CSS, ".feedback-trigger")
    m = re.search(r"@media \(min-width:\s*(\d+)px\)\s*\{\s*\.feedback-trigger\s*\{[^}]*position:\s*fixed", CSS)
    assert m, "фиксированная кнопка обратной связи должна быть под min-width"
    assert int(m.group(1)) >= 980 + 2 * 130


def test_profile_table_header_has_no_long_footnote():
    """Сноска в заголовке температуры забирала ширину: колонка ОВ сжималась до 31 px."""
    html = (STATIC / "calculators.html").read_text(encoding="utf-8")
    headers = re.findall(r"<th>(.*?)</th>", html, re.S)
    assert any("col_min_temp" in h for h in headers)
    assert not any("gp_temp_ref" in h for h in headers)
    assert re.search(r"td input\[type=\"text\"\]\s*\{\s*min-width:", CSS)
