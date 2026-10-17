"""
Форма обратной связи → Telegram (TODO P1, ревью 2026-10-16).

Сеть не используется: подменяется urllib.request.urlopen, и тест видит ровно
то тело запроса, которое ушло бы в Telegram.
"""
from __future__ import annotations

import json

import pytest

from backend.app.routers import feedback


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Список тел запросов, «отправленных» в Telegram."""
    bodies: list[dict] = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(
        feedback.urllib.request, "urlopen",
        lambda req, timeout: bodies.append(json.loads(req.data)) or _FakeResponse(),
    )
    feedback._recent.clear()
    yield bodies
    feedback._recent.clear()


def test_message_with_markdown_characters_is_sent_as_plain_text(client, sent):
    """С parse_mode=Markdown непарные «_» и «*» давали отказ Telegram → 502."""
    msg = "snake_case и 2*3, ссылка [x](y"

    r = client.post("/feedback", json={"message": msg, "page": "calc_page"})

    assert r.status_code == 200
    assert "parse_mode" not in sent[0]
    assert msg in sent[0]["text"]


def test_too_long_message_is_rejected(client, sent):
    r = client.post("/feedback", json={"message": "x" * (feedback.MAX_MESSAGE_LEN + 1)})

    assert r.status_code == 422
    assert sent == []


def test_rate_limit_per_client(client, sent):
    for _ in range(feedback.RATE_LIMIT):
        assert client.post("/feedback", json={"message": "hi"}).status_code == 200

    r = client.post("/feedback", json={"message": "hi"})

    assert r.status_code == 429
    assert len(sent) == feedback.RATE_LIMIT
    # Другой адрес — свой лимит
    other = client.post("/feedback", json={"message": "hi"}, headers={"X-Forwarded-For": "10.0.0.9"})
    assert other.status_code == 200


def test_rate_window_expires():
    feedback._recent.clear()
    for _ in range(feedback.RATE_LIMIT):
        assert feedback._allow("k", 0.0)
    assert not feedback._allow("k", 1.0)
    assert feedback._allow("k", feedback.RATE_WINDOW_S + 1.0)
    feedback._recent.clear()
