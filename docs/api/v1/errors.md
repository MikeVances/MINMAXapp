# MINMAX API v1 — коды ошибок и находок

Ошибки приходят в формате RFC 7807 (`application/problem+json`). Поле `type` —
ссылка на раздел этого файла, `code` — стабильный машинный код, `params` — значения
для подстановки в текст. Текст для пользователя клиент берёт из своего словаря
по `code`, а не из `title`/`detail` (те — на английском, для журналов).

Коды не переименовываются внутри v1: новый код — добавление, удаление или смена
смысла — только в v2.

## Ошибки (HTTP 4xx/5xx)

| HTTP | code | Когда | params |
|---|---|---|---|
| 400 | <a id="bad_request"></a>`bad_request` | Тело не JSON или не того типа | — |
| 401 | <a id="api_key_required"></a>`api_key_required` | На площадке заданы ключи, а `X-API-Key` нет или он неверный | — |
| 404 | <a id="profile_not_found"></a>`profile_not_found` | `growth_profile_id` нет в справочнике | `id` |
| 404 | <a id="material_not_found"></a>`material_not_found` | `material_id` нет в справочнике конструкций | `id` |
| 422 | <a id="validation_failed"></a>`validation_failed` | Поле вне диапазона или не того вида; подробности — в `errors[]` по полям | — |
| 422 | <a id="profile_day_missing"></a>`profile_day_missing` | В профиле нет массы или температуры на нужный день | `id`, `day` |
| 422 | <a id="rh_out_of_table"></a>`rh_out_of_table` | Целевая RH вне таблицы Ross 2025 2.5 (40–70 %) | `rh`, `min`, `max` |
| 422 | <a id="housing_not_supported"></a>`housing_not_supported` | Способ содержания объявлен, но расчёт для него без источника не делается (сейчас таких нет; код — для будущих) | `housing` |
| 422 | <a id="cage_section_missing"></a>`cage_section_missing` | `housing: cages`, но нет `house.cage_rows` — скорость туннеля не посчитать | — |
| 422 | <a id="cage_section_implausible"></a>`cage_section_implausible` | Батареи выше стены или оставляют свободным меньше 15 % сечения | `free_pct`, `min_pct` |
| 422 | <a id="envelope_implausible"></a>`envelope_implausible` | U оболочки вне 0.1–8 Вт/(м²·К) — ошибка в слоях или в UA | `u`, `min`, `max` |
| 429 | <a id="rate_limited"></a>`rate_limited` | Превышен лимит частоты; заголовок `Retry-After` | `limit`, `window_s` |
| 502 | <a id="climate_unavailable"></a>`climate_unavailable` | Open-Meteo не ответил или вернул меньше года данных | — |

## Находки (`findings` / `warnings` в успешном ответе)

Находка — не ошибка: расчёт выполнен, но в нём есть риск или ограничение.

| code | severity | Смысл | params |
|---|---|---|---|
| `humidity_uncontrollable` | critical | Наружный воздух влажнее целевого — вентиляцией RH не удержать; Qmin упёрся в потолок режима | `day` |
| `condensation_risk` | warning | Внутренняя поверхность ограждений холоднее точки росы | `surface_c`, `dew_point_c` |
| `heater_insufficient` | critical | Горелок не хватает даже на 100 % | `need_kw`, `power_kw` |
| `heater_load_unknown` | info | Без `envelope` загрузку горелок не найти — разбавление CO₂ взято при 100 % | — |
| `tunnel_not_allowed_age` | info | Возраст меньше допустимого для туннеля | `min_day` |
| `effective_temp_above_limit` | warning | Ощущаемая температура у вентиляторов ≥ 30 °C (Cobb 2021 §9.7) | `effective_c` |
| `effective_temp_above_profile` | info | Ощущаемая выше уставки профиля — смотреть на поведение птицы | `effective_c`, `target_c` |
| `house_geometry_missing` | warning | Без сечения корпуса потолок вентиляции только оценён | — |
| `cycle_beyond_profile` | info | Цикл длиннее профиля — последние дни взяты по последней точке профиля | `last_day` |

## Допущения (`assumptions`)

| code | Смысл |
|---|---|
| `infiltration_not_included` | Инфильтрация через щели не учтена (нет `infiltration_m3h`) — тепло занижено |
| `floor_not_included` | Пол в UA по конструкции не входит (теплообмен через грунт и массу) |
| `heating_safety_margin` | К пиковой мощности обогрева добавлен запас, `params.pct` |
| `site_pressure_from_altitude` | Давление площадки по стандартной атмосфере, `params.altitude_m` |
| `cages_heat_split_bounded` | Клетки: зима (обогрев, влажностный Qmin) — доля явного тепла корпуса CIGR 2002 (как с подстилкой); лето (Qmax) — 0.67 уровня птицы (Aarnink 2018). Каждая величина — по худшему случаю |
| `cages_bird_speed_from_aisle` | Клетки: скорость у птицы ≈ 0.5 скорости в проходах (практика эксплуатации: 4–5 м/с в проходах → 2–2.5 м/с в клетках); ощущаемая T — по ней |
| `cage_through_flow_not_included` | Клетки: расход вентиляторов = скорость в проходах × свободное сечение; воздух сквозь батареи сверху не добавлен — нижняя граница, сверять анемометром в проходе |
| `materials_iso_10456` | λ материалов — расчётные значения ISO 10456; сэндвич-панель — U из паспорта, если передан |
