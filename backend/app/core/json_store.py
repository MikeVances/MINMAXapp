"""
Надёжная запись JSON-файлов данных (настройки, теплотехника, профили, дневник).

Две проблемы, которые здесь закрываются:

1. Обрыв посреди записи. open(path, "w") сначала обнуляет файл; если процесс
   упадёт или диск переполнится во время json.dump, на диске останется обрезанный
   JSON, и при следующем чтении данные потеряны целиком. Поэтому пишем во
   временный файл рядом и подменяем им старый через os.replace — это атомарно:
   читатель видит либо старую версию, либо новую.

2. Гонки «прочитать → изменить → записать». FastAPI выполняет синхронные
   обработчики в пуле потоков: два одновременных сохранения дневника читают одну
   и ту же версию, и запись второго затирает изменения первого. Поэтому на каждый
   файл заводится своя блокировка (path_lock), и весь цикл чтение-изменение-запись
   выполняется под ней.

Блокировки работают внутри одного процесса — это соответствует запуску
uvicorn с одним воркером (Procfile). Для нескольких процессов нужна БД.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


@contextmanager
def path_lock(path: str | os.PathLike) -> Iterator[None]:
    """
    Блокировка на конкретный файл. RLock: функция под блокировкой может вызвать
    другую, которая берёт ту же блокировку (update → save), без взаимоблокировки.
    """
    key = str(Path(path).resolve())
    with _locks_guard:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        yield


def atomic_write_json(path: str | os.PathLike, data: Any) -> None:
    """Записать JSON через временный файл в том же каталоге + os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Временный файл в ТОМ ЖЕ каталоге: os.replace атомарен только в пределах
    # одной файловой системы
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
