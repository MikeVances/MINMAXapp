"""
Тема площадки: GET /theme.css отдаёт data/theme.css, а без файла — пустой CSS.
Страницы подключают его после styles.css, поэтому ответ нужен всегда и с
правильным типом; 404 от StaticFiles (как было) засорял бы консоль браузера.
"""
from __future__ import annotations

from pathlib import Path

from backend.app import main


def test_theme_css_without_file_is_empty_stylesheet(client):
    assert not main.THEME_CSS_PATH.exists()   # conftest указывает на несуществующий файл

    r = client.get("/theme.css")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert r.text.strip().startswith("/*")   # только комментарий, правил нет


def test_theme_css_serves_site_overrides(client, tmp_path, monkeypatch):
    theme = tmp_path / "theme.css"
    theme.write_text(":root { --accent: #ff8800; }\n", encoding="utf-8")
    monkeypatch.setattr(main, "THEME_CSS_PATH", theme)

    r = client.get("/theme.css")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "--accent: #ff8800" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_pages_link_theme_after_base_styles():
    """Порядок важен: переопределения действуют, только если идут после styles.css."""
    static = Path(main.__file__).parent / "static"
    for page in ("index.html", "calculators.html", "settings.html"):
        html = (static / page).read_text(encoding="utf-8")
        assert html.index('href="./styles.css"') < html.index('href="./theme.css"'), page
