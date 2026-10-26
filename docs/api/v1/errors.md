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
| 404 | <a id="source_not_found"></a>`source_not_found` | `source_id` нет в справочнике источников | `id` |
| 404 | <a id="contract_not_found"></a>`contract_not_found` | Площадка развёрнута без файла контракта `openapi.yaml` — расчёты работают, описание брать из документации | — |
| 422 | <a id="validation_failed"></a>`validation_failed` | Поле вне диапазона или не того вида; подробности — в `errors[]` по полям | — |
| 422 | <a id="profile_day_missing"></a>`profile_day_missing` | В профиле нет массы или температуры на нужный день | `id`, `day` |
| 422 | <a id="rh_out_of_table"></a>`rh_out_of_table` | Целевая RH вне таблицы Ross 2025 2.5 (40–70 %) | `rh`, `min`, `max` |
| 422 | <a id="housing_not_supported"></a>`housing_not_supported` | Способ содержания объявлен, но расчёт для него без источника не делается (сейчас таких нет; код — для будущих) | `housing` |
| 422 | <a id="cage_section_missing"></a>`cage_section_missing` | `housing: cages`, но нет `house.cage_rows` — скорость туннеля не посчитать | — |
| 422 | <a id="cage_section_implausible"></a>`cage_section_implausible` | Батареи выше стены, в сумме шире корпуса или оставляют свободным меньше 15 % сечения | `free_pct`, `min_pct` |
| 422 | <a id="fan_curve_invalid"></a>`fan_curve_invalid` | Точки характеристики не по возрастанию давления или расход не убывает | `index` |
| 422 | <a id="envelope_implausible"></a>`envelope_implausible` | U оболочки вне 0.1–8 Вт/(м²·К) — ошибка в слоях или в UA | `u`, `min`, `max` |
| 422 | <a id="turkey_stage_required"></a>`turkey_stage_required` | Профиль индейки без `flock.stage`: тип корпуса (брудер / доращивание) выбирает норму вентиляторов и предел плотности | — |
| 422 | <a id="stage_turkey_only"></a>`stage_turkey_only` | `flock.stage` у профиля бройлера — тип корпуса бывает только у индейки | `stage` |
| 422 | <a id="housing_not_for_species"></a>`housing_not_for_species` | Способ содержания не считается для вида птицы профиля (индейка в клетках) | `species`, `housing` |
| 422 | <a id="broiler_day_out_of_range"></a>`broiler_day_out_of_range` | День за пределом бройлерного цикла: проект — до 63, сценарий «сейчас» — до 70 (поля допускают 154 для индейки) | `day`, `max_day` |
| 422 | <a id="first_day_after_last"></a>`first_day_after_last` | `flock.first_day` не раньше `cycle_days` | `first_day`, `last_day` |
| 429 | <a id="rate_limited"></a>`rate_limited` | Превышен лимит частоты; заголовок `Retry-After` | `limit`, `window_s` |
| 502 | <a id="climate_unavailable"></a>`climate_unavailable` | Open-Meteo не ответил или вернул меньше года данных | — |

## Находки (`findings` / `warnings` в успешном ответе)

Находка — не ошибка: расчёт выполнен, но в нём есть риск или ограничение.

| code | severity | Смысл | params |
|---|---|---|---|
| `humidity_uncontrollable` | critical | Наружный воздух влажнее целевого — вентиляцией RH не удержать; Qmin упёрся в потолок режима | `day` |
| `condensation_risk` | warning | Внутренняя поверхность ограждений холоднее точки росы | `surface_c`, `dew_point_c` |
| `heater_insufficient` | critical | Горелок не хватает даже на 100 % | `power_kw`; сценарий 2 — `need_kw`, проект — `days` |
| `heater_load_unknown` | info | Без `envelope` загрузку горелок не найти — разбавление CO₂ взято при 100 % | — |
| `tunnel_not_allowed_age` | info | Возраст меньше допустимого для туннеля | `min_day` |
| `effective_temp_above_limit` | warning | Ощущаемая температура у вентиляторов ≥ 30 °C (Cobb 2021 §9.7) | `effective_c` |
| `effective_temp_above_profile` | info | Ощущаемая выше уставки профиля — смотреть на поведение птицы | `effective_c`, `target_c` |
| `house_geometry_missing` | warning | Без сечения корпуса потолок вентиляции только оценён | — |
| `fan_curve_extrapolated` | warning | Рабочая точка за последней точкой каталога — расход экстраполирован | `pressure_pa`, `last_pa` |
| `tunnel_pressure_high` | warning | Давление туннеля выше 50 Па — осевые вентиляторы теряют много расхода, проверить каталог и панели | `pressure_pa` |
| `stocking_density_high` | warning | Плотность посадки выше 42 кг/м² пола — предел Cobb 2021 §5.2: тепло из-под птицы вентиляцией уже не снять, уставка Cobb упирается в 14 °C. Только у методики Cobb | `days`, `density_kg_m2`, `limit_kg_m2` |
| `turkey_density_high` | warning | Индейка: поголовье на м² пола выше верхней границы Aviagen CL23 с. 13 — брудер 10, доращивание 3.2 самца или 6 самок; для смешанного стада на доращивании предела нет | `days`, `head_per_m2`, `limit_head_per_m2` |
| `leakage_exceeds_min_vent` | info | Утечка при 4 Па больше Qmin — в эти дни обогрев греет воздух щелей, а не минвентиляции; уплотнение корпуса экономит газ | `days`, `leak_4pa_m3h` |
| `min_vent_pressure_low` | warning | Даже при закрытых клапанах вентиляторы Qmin не создают разрежения, при котором клапаны бросают струю под потолок (порог — по UGA, сверить при реализации): холодный воздух через щели падает на птицу | `day`, `pressure_pa`, `min_pa` |
| `cycle_beyond_profile` | info | Цикл длиннее профиля — последние дни взяты по последней точке профиля | `last_day` |

## Допущения (`assumptions`)

| code | Смысл |
|---|---|
| `airtightness_class_assumed` | Герметичность не задана — взят класс UGA `moderate` (0.65 м²/1000 м² пола), `params.class`, `params.relative_leakage` |
| `floor_not_included` | Пол в UA по конструкции не входит (теплообмен через грунт и массу) |
| `heating_safety_margin` | К пиковой мощности обогрева добавлен запас, `params.pct` |
| `site_pressure_from_altitude` | Давление площадки по стандартной атмосфере, `params.altitude_m` |
| `cages_heat_split_bounded` | Клетки: зима (обогрев, влажностный Qmin) — доля явного тепла корпуса CIGR 2002 (как с подстилкой); лето (Qmax) — 0.67 уровня птицы (Aarnink 2018). Каждая величина — по худшему случаю |
| `cages_bird_speed_from_aisle` | Клетки: скорость у птицы ≈ 0.5 скорости в проходах (практика эксплуатации: 4–5 м/с в проходах → 2–2.5 м/с в клетках); ощущаемая T — по ней |
| `tunnel_length_loss_not_included` | Потери давления по длине корпуса (батареи, балки, кормушки) не оценены: нет источника коэффициента — давление и падение расхода занижены; передайте `tunnel_static_pressure_pa` с замера |
| `cage_through_flow_not_included` | Клетки: расход вентиляторов = скорость в проходах × свободное сечение; воздух сквозь батареи сверху не добавлен — нижняя граница, сверять анемометром в проходе |
| `tunnel_rules_default` | `tunnel_rules` не заданы — туннель с 21-го дня и при наружной T ≥ 24 °C: практика птицеводов (владелец, 2026-10-19); `params.min_day`, `params.min_temp_c`, `source_id` |
| `cobb_density_transition` | Cobb 500: после 14-го дня уставка — по плотности посадки (живая птица × масса / пол). Между 14-м днём и 28 кг/м² Cobb значений не даёт — линейный переход 26 → 22 °C по плотности (наше допущение); `params.density_from_kg_m2`, `params.density_to_kg_m2` — плотность первого и последнего такого дня |
| `cobb_density_unavailable` | Cobb 500 в клетках: таблица Cobb по плотности — для подстилки, после 14-го дня уставка — значения профиля (Ross 2025 табл. 2.5) |
| `winter_rh_saturated` | Наружный воздух зимой — насыщенный (RH 100 %): больше влаги снаружи — больше влажностный Qmin, в безопасную сторону |
| `min_vent_climate_class` | Норма установленной мощности минвентиляции Cobb §9.1 выбрана по зиме: ниже 0 °C — холодный климат (36.6–46.2 м³/ч·м²), иначе жаркий (18). Границы у Cobb нет, `params.class`, `params.winter_design_c` |
| `min_vent_turkey_stage` | Индейка: норма установленной мощности минвентиляции — Hybrid Ventilation Calculator, 18.3 м³/ч·м² в брудере и 27.5 на доращивании (решение владельца 2026-10-26); `params.stage`, `params.m3h_per_m2` |
| `turkey_sensible_from_broiler` | Индейка: полное тепло — CIGR 2002 ур. 19 (9.86·m^0.77), доля явного тепла корпуса — бройлерная (своей у индейки в CIGR нет); у тяжёлых индюков она может быть занижена — летний Qmax тоже |
| `turkey_day0_weight` | Индейка: масса суточной птицы — Xin et al. 1998, ур. 6 (индюки Nicholas), в таблицах производителя её нет; `params.weight_g` |
| `qmin_includes_guide_norm` | Qmin = max(CO₂, норма производителя кросса, влага); `params.norm` — код нормы, основание `guide` в `qmin_basis`, когда правит она |
| `turkey_tunnel_age_limits_from_broiler` | Индейка: пределы скорости в тоннеле по возрасту — бройлерные Cobb §9.7 (до 21-го дня), у индейки своих нет |
| `effective_temp_not_for_turkey` | Индейка: ощущаемая температура в тоннеле не считается — таблица и предел бройлерные |
| `heating_without_combustion_products` | Горелки не заданы — обогрев посчитан без воздуха на разбавление CO₂ и пара открытого пламени; для газовых горелок открытого горения передайте `heaters` |
| `materials_iso_10456` | λ — BS EN ISO 10456 в изложении BRE BR 443 (2019) §3, R_si/R_se — ISO 6946 по BR 443 §4.3; панель по слоям без стыков — U из декларации точнее |
