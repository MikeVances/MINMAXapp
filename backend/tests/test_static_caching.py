"""
Отдача статики (аудит 2026-10-18): не было gzip и Cache-Control, ручной ?v=
стоял у двух файлов из десятка — после деплоя браузер мог держать старый
скрипт рядом с новой страницей.

Теперь: gzip; страница no-cache + ETag (304 при совпадении); каждая её ссылка
на локальный .js/.css — ?v=<хеш содержимого>, и такой файл кэшируется навсегда.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PAGES = ["/", "/calculators.html", "/settings.html"]


def test_text_responses_are_gzipped(client):
    r = client.get("/i18n/ru.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


@pytest.mark.parametrize("page", PAGES)
def test_page_revalidates_and_answers_304(client, page):
    r = client.get(page)
    assert r.headers["cache-control"] == "no-cache" and r.headers.get("etag")
    assert client.get(page, headers={"If-None-Match": r.headers["etag"]}).status_code == 304


@pytest.mark.parametrize("page", PAGES)
def test_every_local_asset_carries_its_content_hash(client, page):
    html = client.get(page).text
    refs = re.findall(r'(?:src|href)="\./([^"?#]+\.(?:js|css))(\?v=[^"]*)?"', html)
    assert refs
    for name, query in refs:
        if not (STATIC / name).is_file():
            assert not query, f"{name}: маршрут (theme.css), а не статика — без версии"
            continue
        expected = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
        assert query == f"?v={expected}", name


def test_versioned_asset_is_immutable_unversioned_revalidates(client):
    html = client.get("/calculators.html").text
    url = re.search(r'src="\./(calibration\.js\?v=\w+)"', html).group(1)
    assert "immutable" in client.get("/" + url).headers["cache-control"]
    assert client.get("/calibration.js").headers["cache-control"] == "no-cache"


def test_no_hand_numbered_versions_left_in_sources():
    """Ручной ?v=14 забывали поднимать — теперь версию ставит сервер."""
    offenders = [f"{p.name}: {m}" for p in STATIC.glob("*.html")
                 for m in re.findall(r'\.(?:js|css)\?v=[^"]*', p.read_text(encoding="utf-8"))]
    assert not offenders, offenders
