"""
Резервная копия данных фермы (решение 2026-10-19 по эфемерному диску Render).

Тестовая площадка Render теряет data/ при каждом деплое и рестарте — владелец
принял это для теста. Чтобы данные фермы не пропадали, их можно выгрузить в
JSON и загрузить обратно:

  GET  /backup — настройки хозяйства, пользовательские профили роста, теплотехника
                 по корпусам (встроенные профили — часть приложения, не копируются)
  POST /backup — восстановление (токен записи). Каждая часть проходит те же модели
                 и проверки, что обычное сохранение; сначала проверяется ВСЁ, потом
                 пишется — битый файл не оставит данные наполовину заменёнными.

Список корпусов живёт в браузере — его добавляет и восстанавливает клиент (settings.js).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError

from ..api_errors import api_error
from ..core.app_config import load_app_config
from ..core.building_thermal import load_thermal_store
from ..core.growth_profiles import list_profiles
from ..write_access import require_write_token
from .growth_profiles import ProfileIn, put_profile
from .settings import AppCfg, put_app_cfg
from .thermal import ThermalConfigModel, update_thermal_config

router = APIRouter()

BACKUP_VERSION = 1


class Backup(BaseModel):
    version: int = Field(BACKUP_VERSION, ge=1, le=BACKUP_VERSION)
    app_config: Dict[str, Any] | None = None
    profiles: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    thermal: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # Клиентская часть (список корпусов из браузера) — сервер её не трогает
    houses: List[Dict[str, Any]] | None = None


@router.get("/backup", response_model=Backup)
def get_backup():
    profiles = {}
    for p in list_profiles():
        if p.builtin:
            continue
        profiles[p.id] = {"name": p.name, "breed": p.breed, "source": p.source,
                          "points": [asdict(pt) for pt in p.points]}
    thermal = {}
    for hid, cfg in load_thermal_store().items():
        data = {k: asdict(v) for k, v in (("building", cfg.building), ("heater", cfg.heater),
                                          ("calibration", cfg.calibration)) if v is not None}
        if data:
            thermal[hid] = data
    return Backup(app_config=asdict(load_app_config()), profiles=profiles, thermal=thermal)


@router.post("/backup", dependencies=[Depends(require_write_token)])
def restore_backup(backup: Backup):
    # 1. Проверить всё, ничего не записывая
    try:
        profiles = {pid: ProfileIn(**body) for pid, body in backup.profiles.items()}
        app_cfg = AppCfg(**backup.app_config) if backup.app_config is not None else None
        thermal = [ThermalConfigModel(house_id=hid or None, **{k: v for k, v in body.items() if k != "house_id"})
                   for hid, body in backup.thermal.items()]
    except ValidationError as e:
        raise api_error(422, "backup_invalid", detail=str(e.errors()[0].get("loc", "")))
    # 2. Записать: профили — до настроек (профиль по умолчанию должен существовать)
    for pid, body in profiles.items():
        put_profile(pid, body)
    if app_cfg is not None:
        put_app_cfg(app_cfg)
    for cfg in thermal:
        update_thermal_config(cfg)
    return {"profiles": len(profiles), "app_config": app_cfg is not None, "thermal_houses": len(thermal)}
