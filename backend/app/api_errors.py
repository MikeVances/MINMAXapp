"""
HTTP-ошибки с машинным кодом вместо текста.

Клиент переводит ``detail`` сам (см. apiErrorText в static/i18n.js), поэтому
роутеры отдают только код и параметры. Формы ``detail``:

* строка-код — ``"profile_not_found"`` (без параметров; так же работает
  ``write_token_required`` из write_access.py);
* объект ``{"code": …, "params": {…}}`` — когда тексту нужны значения.

Обе формы — один и тот же контракт; объектная нужна только ради параметров.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .core.errors import CalcError


def api_error(status_code: int, code: str, **params: Any) -> HTTPException:
    """``raise api_error(400, "dimensions_missing")`` / ``api_error(404, "profile_not_found", id=…)``."""
    detail: Any = {"code": code, "params": params} if params else code
    return HTTPException(status_code=status_code, detail=detail)


def from_calc_error(exc: ValueError, status_code: int = 400) -> HTTPException:
    """
    ValueError из ядра расчёта → HTTP-ответ.

    CalcError несёт код и параметры — уходят как есть. Обычный ValueError
    (pydantic, стандартная библиотека) кода не имеет: отдаём его текст, чтобы
    не потерять причину; таких мест в ядре быть не должно.
    """
    if isinstance(exc, CalcError):
        return HTTPException(status_code=status_code, detail=exc.detail)
    return HTTPException(status_code=status_code, detail=str(exc))
