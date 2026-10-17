"""
Надёжность записи данных (TODO P1, ревью 2026-10-16):
  - обрыв посреди записи не должен портить существующий файл;
  - одновременные сохранения дневника не должны терять записи.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from backend.app.core import flock_storage, json_store
from backend.app.models.flock import FlockDiaryEntry


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


def test_concurrent_diary_saves_lose_nothing(tmp_path, monkeypatch):
    """
    30 потоков одновременно сохраняют записи за разные дни одного корпуса.
    Окно гонки расширено искусственно (чтение «тормозит» на 5 мс), чтобы без
    блокировки потеря записей проявлялась всегда, а не по случайности.
    """
    monkeypatch.setattr(flock_storage, "FLOCKS_DATA_DIR", tmp_path)
    real_load = flock_storage.load_diary_entries

    def slow_load(*args, **kwargs):
        entries = real_load(*args, **kwargs)
        time.sleep(0.005)
        return entries

    monkeypatch.setattr(flock_storage, "load_diary_entries", slow_load)

    def save(day: int) -> None:
        flock_storage.save_diary_entry(
            "race", FlockDiaryEntry(house_id="race", date="2026-10-17", day_of_cycle=day)
        )

    threads = [threading.Thread(target=save, args=(d,)) for d in range(1, 31)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    days = [e.day_of_cycle for e in real_load("race")]
    assert days == list(range(1, 31))
