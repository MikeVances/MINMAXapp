"""
Надёжность записи данных (TODO P1, ревью 2026-10-16):
обрыв посреди записи не должен портить существующий файл.
"""
from __future__ import annotations

import json

import pytest

from backend.app.core import json_store


def test_failed_write_keeps_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "cfg.json"
    path.write_text('{"total_mortality_pct": 5.0}', encoding="utf-8")

    def dump_then_crash(data, f, **kw):
        f.write('{"total_mortality')   # половина JSON — как при обрыве
        raise OSError("disk full")

    monkeypatch.setattr(json_store.json, "dump", dump_then_crash)

    with pytest.raises(OSError):
        json_store.atomic_write_json(path, {"total_mortality_pct": 7.0})

    assert json.loads(path.read_text(encoding="utf-8")) == {"total_mortality_pct": 5.0}
    assert [p.name for p in tmp_path.iterdir()] == ["cfg.json"]   # временный файл убран

