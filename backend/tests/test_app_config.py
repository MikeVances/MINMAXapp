"""
Загрузка настроек хозяйства из файла, сохранённого старой версией приложения.

После удаления сезонного режима в старых data/app_config.json остались ключи
max_per_kg_*, use_temp_blend, min_floor_* и т.п. Раньше AppConfig(**raw) падал на
незнакомом ключе, и ВЕСЬ конфиг молча откатывался на умолчания — терялись падёж
и длина цикла.
"""
from __future__ import annotations

import json

from backend.app.core.app_config import load_app_config

LEGACY_CONFIG = {
    "total_mortality_pct": 5.0,
    "cycle_days": 49,
    "min_floor_unit": "per_bird",
    "min_floor_0_7": 0.18,
    "max_per_kg_winter": 2.5,
    "use_temp_blend": True,
    "temp_winter_c": -10.0,
    "n_birds_initial": 30000,
}


def test_legacy_keys_are_dropped_and_known_values_kept(tmp_path):
    path = tmp_path / "app_config.json"
    path.write_text(json.dumps(LEGACY_CONFIG), encoding="utf-8")

    cfg = load_app_config(str(path))

    # Значения пользователя, а не умолчания (4.0 % и 42 дня)
    assert cfg.total_mortality_pct == 5.0
    assert cfg.cycle_days == 49
    assert not hasattr(cfg, "max_per_kg_winter")
