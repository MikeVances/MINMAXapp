"""
Справочник источников расчёта — одна запись на каждый `source_id`, который отдаёт API.

Зачем отдельный модуль, а не строка цитаты рядом с кодом. Ответ расчёта называет
источник меткой (`cobb_2021_9_1`), и агенту без кода нечем объяснить человеку, что
за ней стоит: он пересказывал по памяти и путал, кто что утверждает. Здесь у каждой
метки — выверенный нами пересказ правила, как калькулятор его применяет и где наша
модель от источника отличается. Поиск строго по ключу, а не «похожий абзац» из
полного текста гайда: агент получает ровно тот источник, на который сослался расчёт.

Тексты на русском: справку читает агент-расчётчик и пересказывает человеку.
`citation` — прежняя короткая ссылка, её же отдают ответы расчётов в `sources`.

Правило пополнения: новый `source_id` в ядре — сразу запись здесь, иначе красный
тест test_api_v1_sources (каждый id, который отдаёт расчёт, есть в справочнике).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Optional

# Чего стоит источник — агент обязан различать норму и рассказ владельца:
#   standard     — стандарт или нормативный справочник;
#   manufacturer — руководство или паспорт производителя (кросс, панели, вентилятор);
#   research     — научная публикация;
#   extension    — методика университетской службы внедрения (UGA);
#   data         — набор данных (климат);
#   practice     — практика эксплуатации со слов владельца, без публикации;
#   unverified   — первоисточник не установлен.
SourceKind = Literal["standard", "manufacturer", "research", "extension", "data", "practice", "unverified"]


@dataclass(frozen=True)
class Source:
    id: str
    kind: SourceKind
    citation: str               # короткая ссылка — как в `sources` ответов расчёта
    title: str
    publisher: str
    year: Optional[int]
    locator: Optional[str]      # раздел, таблица, страница — где проверить
    applies_to: str             # к какой части расчёта относится
    statement: str              # что утверждает источник (наш выверенный пересказ)
    how_used: str               # как калькулятор это применяет
    limits: Optional[str] = None  # где модель отличается от источника или чего он не покрывает
    url: Optional[str] = None


ROSS_HANDBOOK_URL = "https://aviagen.com/assets/Tech_Center/Ross_Broiler/Aviagen-ROSS-Broiler-Handbook-EN.pdf"


_SOURCES: tuple[Source, ...] = (

    # ── Птица: тепло, CO₂, температура ────────────────────────────────────────
    Source(
        id="cigr_1984", kind="research",
        citation="CIGR (1984, rev. 1999) Climatization of Animal Houses, Report No. 2 — CO₂ norm",
        title="Climatization of Animal Houses, Report of Working Group No. 2",
        publisher="CIGR", year=1984, locator="ред. 1999",
        applies_to="минимальная вентиляция (Qmin) по CO₂",
        statement="Полное тепло бройлера 10.62·W^0.75 Вт (W — живая масса, кг); выделение CO₂ "
                  "пропорционально теплу. Предел CO₂ в корпусе — 3000 ppm.",
        how_used="Qmin на птицу = CO₂ птицы / (3000 − 400 ppm наружного) × коэффициент запаса 1.5 "
                 "(влага подстилки, неравномерность раздачи воздуха). Умножается на живое поголовье дня.",
        limits="Коэффициент запаса 1.5 — наше допущение, не из CIGR. Норма сверена с таблицей "
               "минимальной вентиляции Aviagen 2018 в пределах ~10 %.",
    ),
    Source(
        id="cigr_2002", kind="research",
        citation="CIGR (2002) Heat and moisture production at animal and house levels",
        title="Heat and moisture production at animal and house levels",
        publisher="CIGR Working Group", year=2002, locator="в изложении Aarnink et al. 2018, ур. 11 и 13",
        applies_to="тепло птицы в балансе корпуса (обогрев, Qmax по теплу, влага) — напольное содержание",
        statement="Полное тепло 10.62·W^0.75 Вт при 20 °C; доля явного тепла на уровне КОРПУСА "
                  "убывает с температурой (часть тепла уходит на испарение влаги из подстилки).",
        how_used="Явное тепло корпуса греет воздух и снижает потребность в горелках; скрытое — "
                 "влага, которую выносит вентиляция.",
        limits="Поправка полного тепла +2 % на градус ниже 20 °C выведена по аналогии с формулой "
               "для свиней в том же источнике — для бройлеров это вывод, а не прямая цитата. "
               "В первые недели формула переоценивает скрытую долю — для Qmin по влаге это "
               "ошибка в безопасную сторону.",
    ),
    Source(
        id="aarnink_2018", kind="research",
        citation="Aarnink et al. (2018) Heat and moisture production in growing-finishing pigs "
                 "and broilers, CIGR Journal art. 4781 — animal-level sensible share 0.67",
        title="Heat and moisture production in growing-finishing pigs and broilers",
        publisher="CIGR Journal, art. 4781", year=2018, locator=None,
        applies_to="клеточное содержание: тепло птицы летом",
        statement="На уровне ЖИВОТНОГО (без подстилки) доля явного тепла бройлера ≈ 0.67 полного.",
        how_used="В клетках помёт уходит на лентах, испарения из подстилки нет. Тепло птицы — вилка: "
                 "зимой (обогрев) берётся уровень корпуса CIGR 2002 — меньше тепла, расчёт "
                 "горелок в запас; летом (Qmax) — уровень животного 0.67 — больше тепла, Qmax в запас.",
        limits="Сталь клеток в тепловом балансе не учитывается (решение владельца).",
    ),
    Source(
        id="ross_2025_t2_5", kind="manufacturer",
        citation="Aviagen, Ross Broiler Management Handbook 2025, table 2.5 — temperature by RH",
        title="Ross Broiler Management Handbook", publisher="Aviagen", year=2025,
        locator="табл. 2.5, с. 30 (также табл. 2.4, с. 28)", url=ROSS_HANDBOOK_URL,
        applies_to="уставка температуры по дням и её сдвиг при другой влажности",
        statement="Табл. 2.5: температура сухого термометра для заданной влажности, по формуле "
                  "Mitchell (SRUC), в зависимости от массы птицы. Табл. 2.4: при 50 % RH для "
                  "массы > 1530 г — 20 °C; после 27 дней держать 20 °C или по поведению птицы. "
                  "Плотность посадки уставку не меняет — по Ross она снижает охлаждающий "
                  "эффект туннеля (с. 81).",
        how_used="Уставка дня у кроссов Aviagen (Ross 308/708, Arbor Acres) — по массе дня из "
                 "табл. 2.5 (колонка 60 % RH); при другой целевой RH уставка сдвигается по той же "
                 "таблице. Сдвиг по RH применяется и к пользовательским профилям. У Cobb 500 — "
                 "после 14-го дня, когда плотность посадки неизвестна (клетки): значения профиля.",
        limits="Методика Aviagen. Cobb и Hubbard задают уставку иначе — у них свои методики "
               "(cobb_2021_5_2, hubbard_2026_app1). Примечание Ross «RH менее критична при "
               "200–2500 г» калькулятор не учитывает: сдвиг по RH применяется при любой массе.",
    ),

    Source(
        id="cobb_2021_5_2", kind="manufacturer",
        citation="Cobb Broiler Management Guide 2021, §5.2 — temperature by RH and stocking density",
        title="Cobb Broiler Management Guide", publisher="Cobb-Vantress", year=2021,
        locator="§5.2 Temperature and Stocking Density Management, с. 40",
        url="https://www.cobbgenetics.com/assets/Cobb-Files/Broiler-Guide_English-2021-min.pdf",
        applies_to="уставка температуры по дням для Cobb 500",
        statement="Таблица по RH (30–70 %): день 0 — 34…30 °C, 7 — 32…28, 14 — 29…25, при "
                  "28 кг/м² — 25…21 °C; на каждые 10 % RH — 1 °C. Таблица по плотности: 28 кг/м² — "
                  "22–24 °C, 30 — 21–23, 32 — 20–22, 34 — 19–21, 36 — 18–20, 38 — 17–19, 40 — "
                  "16–18, 42 — 15–17, больше 42 — 14–16 °C. Плотнее 42 кг/м² держать не советует; "
                  "уставку меняют по поведению и температуре тела птицы.",
        how_used="Дни 0–14 — таблица по возрасту, колонка 60 % RH (31/29/26 °C), другая целевая "
                 "RH сдвигает на 1 °C за 10 %. После 14-го дня — по плотности посадки на этот день: "
                 "живая птица × масса профиля / площадь пола. Берётся нижняя граница диапазона: при "
                 "28 кг/м² таблица по RH даёт 22 °C именно в колонке 60 %; та же поправка по RH. "
                 "От плотности 14-го дня до 28 кг/м² — линейный переход от 26 к 22 °C "
                 "(допущение cobb_density_transition).",
        limits="Переход между 14-м днём и 28 кг/м² Cobb не задаёт — это наше допущение. Таблица "
               "по плотности — для пола с подстилкой: в клетках, где плотность на м² пола не имеет "
               "того смысла, после 14-го дня берутся значения профиля Ross (допущение "
               "cobb_density_unavailable). Колонка temp_c в getGrowthProfile для Cobb после 14-го "
               "дня — эти же значения без плотности: уставку с плотностью даёт только расчёт "
               "(target_temp_c). Поправку +1 °C на первую неделю для цыплят молодого стада "
               "калькулятор не делает.",
    ),
    Source(
        id="hubbard_2026_app1", kind="manufacturer",
        citation="Hubbard, Efficiency Plus Broiler Guide V-2026-09, appendix 1 — house temperature by age",
        title="Efficiency Plus Broiler Guide", publisher="Hubbard", year=2026,
        locator="прил. 1 «Optimal controlled house environment», с. 10",
        url="https://www.hubbardbreeders.com/medias/3262/broiler-guide-efficiency-plus-en.pdf",
        applies_to="уставка температуры по дням для Hubbard Efficiency Plus",
        statement="Обогрев всего корпуса (whole house heating): день 0 — 33 °C, 3 — 31–32, 7 — 30, "
                  "14 — 28, 21 — 25–26, 28 — 22–23, после 35 — 20 °C. RH — диапазоном (40–70 %), "
                  "без поправки температуры; поправки на плотность нет. В тексте: в первые 3 недели "
                  "каждые 0.1 м/с сверх 0.3 м/с ощущаются на 0.4–0.5 °C холоднее.",
        how_used="Уставка дня — по возрасту, линейно между точками таблицы; диапазоны — серединой "
                 "(31.5, 25.5, 22.5 °C), с 35-го дня — 20 °C. Целевая RH уставку не сдвигает: "
                 "Hubbard такой поправки не даёт (RH остаётся потолком влагобаланса).",
        limits="Середина диапазона — наш выбор. Колонка «под брудерами» (35–38 °C) — для местного "
               "обогрева, калькулятор считает обогрев всего корпуса.",
    ),

    # ── Вентиляция: нормы оборудования ─────────────────────────────────────────
    Source(
        id="cobb_2021_9_1", kind="manufacturer",
        citation="Cobb Broiler Management Guide 2021, §9.1 — installed minimum-ventilation capacity",
        title="Cobb Broiler Management Guide", publisher="Cobb-Vantress", year=2021,
        locator="§9.1 Minimum Ventilation, с. 69",
        applies_to="установленная мощность вентиляторов минимальной вентиляции",
        statement="Мощность вентиляторов по таймеру — не менее 0.3 м³/мин на м² пола (18 м³/ч·м²) "
                  "в жарком климате, где снаружи редко ниже 20–25 °C; в холодном — 0.61–0.77 "
                  "м³/мин·м² (36.6–46.2 м³/ч·м²). Цикл таймера 5 мин, не длиннее 10.",
        how_used="Вилка установленной мощности минимальной вентиляции в `equipment` — по площади пола.",
        limits="Это мощность, которую ставят, а не расход дня: расход дня — Qmin по CO₂ и влаге.",
    ),
    Source(
        id="cobb_2021_9_7", kind="manufacturer",
        citation="Cobb Broiler Management Guide 2021, §9.7 — tunnel capacity 165–200 m³/h·m², "
                 "air exchange 40–50 s",
        title="Cobb Broiler Management Guide", publisher="Cobb-Vantress", year=2021,
        locator="§9.7 Tunnel Ventilation, с. 78",
        applies_to="туннельная вентиляция напольного корпуса",
        statement="Туннельные вентиляторы для утеплённого герметичного корпуса — 165–200 м³/ч на м² "
                  "пола; воздухообмен корпуса — за 40–50 с. Пример: 3 м/с в сечении, мощности "
                  "вентиляторов при 25 Па.",
        how_used="Цель туннеля — больший из двух критериев (по площади пола и по обмену за 40–50 с); "
                 "скорость в сечении получается из расхода.",
        limits="Только напольное содержание. Для клеток — практика владельца "
               "(practice_cage_tunnel_2026).",
    ),
    Source(
        id="cobb_2021_9_7_age", kind="manufacturer",
        citation="Cobb Broiler Management Guide 2021, §9.7 — air speed limits by age "
                 "and effective temperature below 30 °C",
        title="Cobb Broiler Management Guide", publisher="Cobb-Vantress", year=2021,
        locator="§9.7, таблица Max Airspeed, с. 75",
        applies_to="допустимая скорость воздуха у птицы по возрасту",
        statement="Максимальная скорость: 0–5 дней — до 0.3 м/с; 5–14 — 0.3–0.5; 14–21 — 0.5–1.8. "
                  "Эффективная (ощущаемая) температура птицы — ниже 30 °C. В первые 25 дней "
                  "держать скорость в этих пределах, если температура не выше целевой.",
        how_used="Скорость туннеля ограничивается верхом строки возраста (в расчёте «сейчас» и в "
                 "днях проекта, если туннель разрешён раньше 21-го дня); с 21-го дня предела по "
                 "возрасту нет — действует проектная скорость туннеля. В клетках предел "
                 "относится к скорости у птицы, а не в проходе.",
        limits="Берётся верхняя граница каждой строки — максимум, а не рекомендуемое значение.",
    ),

    # ── Ограждения и герметичность ─────────────────────────────────────────────
    Source(
        id="br443_2019_s3", kind="standard",
        citation="BRE BR 443 (2019) Conventions for U-value calculations, §3 — "
                 "design values per BS EN ISO 10456 / CIBSE Guide A",
        title="Conventions for U-value calculations (BR 443)", publisher="BRE", year=2019, locator="§3",
        applies_to="теплопроводность λ материалов справочника",
        statement="Расчётные значения λ строительных материалов по BS EN ISO 10456 и CIBSE Guide A.",
        how_used="λ материала из `listConstructionMaterials`; U слоя = d/λ.",
        limits="Для утеплителя точнее λ из паспорта (декларации) конкретной панели — его можно "
               "передать в слое вместо материала.",
    ),
    Source(
        id="br443_2019_s4_3", kind="standard",
        citation="BRE BR 443 (2019) §4.3 — surface resistances per BS EN ISO 6946",
        title="Conventions for U-value calculations (BR 443)", publisher="BRE", year=2019, locator="§4.3",
        applies_to="сопротивления теплообмену у поверхностей",
        statement="По ISO 6946: Rse = 0.04; Rsi = 0.13 для стен (горизонтальный поток) и 0.10 для "
                  "кровли (поток вверх) м²·К/Вт.",
        how_used="U = 1 / (Rsi + Σ d/λ + Rse); скат круче 60° считается стеной.",
    ),
    Source(
        id="marcegaglia_dop_100p_2022", kind="manufacturer",
        citation="Marcegaglia DoP 100P 09/2022 (EN 14509), PIR core λD 0.022 W/(m·K)",
        title="Declaration of Performance 100P (EN 14509)", publisher="Marcegaglia", year=2022,
        locator="DoP 09/2022",
        applies_to="материал `pir_core` (сердечник PIR сэндвич-панели)",
        statement="Заявленная теплопроводность сердечника PIR λD = 0.022 Вт/(м·К).",
        how_used="λ материала `pir_core` в справочнике.",
        limits="Значение одного производителя — типичное, не гарантия для чужих панелей.",
    ),
    Source(
        id="uga_leakage", kind="extension",
        citation="UGA Poultry House Leakage Estimating Spreadsheet 2014; Poultry411 Tightness Calculator",
        title="Poultry House Leakage Estimating Spreadsheet", publisher="University of Georgia", year=2014,
        locator=None,
        applies_to="утечки корпуса и классы герметичности",
        statement="Эквивалентная площадь щелей ELA = относительная утечка × площадь пола / 1000; "
                  "расход через щели Q = ELA·√(2ΔP/ρ).",
        how_used="Утечка при 4 Па (ветер и тяга) — нижний предел воздухообмена при обогреве: "
                 "расход = max(Qmin, утечка), утечка к Qmin не прибавляется. Класс переводится в "
                 "утечку по верхней границе (в запас для обогрева): tight 0.48, moderate 0.65, "
                 "leaky 1.0, very_leaky 1.2 м² на 1000 м² пола. Без данных — класс moderate (допущение в ответе).",
        limits="Влияет на обогрев, только когда утечка больше Qmin (`air_exchange_basis` = `leakage`).",
    ),

    # ── Туннель: оборудование и давление ───────────────────────────────────────
    Source(
        id="uga_inlet_750cfm", kind="extension",
        citation="UGA (Czarick): 750 cfm of fan capacity per ft² of sidewall inlet opening",
        title="Правило площади приточных клапанов", publisher="University of Georgia (M. Czarick)",
        year=None, locator=None,
        applies_to="площадь приточных клапанов минимальной вентиляции",
        statement="750 cfm мощности вентиляторов на ft² открытой площади приточного клапана "
                  "(≈ 13 717 м³/ч на м²).",
        how_used="`inlet_area_m2` = верх установленной мощности минимальной вентиляции / 13 717.",
    ),
    Source(
        id="uga_pad_velocity", kind="extension",
        citation="UGA (Czarick) Evaporative cooling pad design spreadsheet — 350 fpm (1.78 m/s) "
                 "for 150 mm pads, 225 fpm (1.14 m/s) for 100 mm",
        title="Evaporative cooling pad design spreadsheet", publisher="University of Georgia (M. Czarick)",
        year=None, locator=None,
        applies_to="площадь панелей испарительного (панельного) охлаждения",
        statement="Проектная скорость воздуха через панель: 1.78 м/с для 150 мм, 1.14 м/с для 100 мм. "
                  "Та же 1.78 м/с — в Cobb 2021 для панелей 15 см.",
        how_used="`pad_area_m2` = проектный расход туннеля / проектная скорость панели.",
    ),
    Source(
        id="sanhe_pads", kind="manufacturer",
        citation="SANHE evaporative pad pressure-drop curves (digitised manufacturer data)",
        title="Кривые сопротивления испарительных панелей", publisher="SANHE", year=None, locator=None,
        applies_to="сопротивление панелей в статическом давлении туннеля",
        statement="Падение давления на панели в зависимости от скорости воздуха и толщины.",
        how_used="Слагаемое панелей в оценке давления туннеля и рабочей точке вентилятора.",
        limits="Кривые оцифрованы с графиков производителя; значение 41 Па для 150 мм при 1.78 м/с "
               "с поставщиком не сверено.",
    ),
    Source(
        id="amca_210", kind="standard",
        citation="AMCA 210 — fan ratings at standard air 1.2 kg/m³",
        title="AMCA 210 Laboratory Methods of Testing Fans", publisher="AMCA", year=None, locator=None,
        applies_to="характеристики вентиляторов и оценка давления",
        statement="Каталожные расходы вентиляторов даются при стандартном воздухе плотностью 1.2 кг/м³.",
        how_used="Давление туннеля оценивается при 1.2 кг/м³, чтобы сравнивать его с каталожной "
                 "кривой в тех же условиях; рабочая точка — пересечение с кривой из запроса.",
        limits="Потери давления по длине корпуса не считаются (0), пока нет замеров — для клеточных "
               "залов это недооценка.",
    ),

    # ── Психрометрия и климат ──────────────────────────────────────────────────
    Source(
        id="ashrae_2017_ch1", kind="standard",
        citation="ASHRAE Handbook Fundamentals 2017, ch. 1 — psychrometrics, standard atmosphere",
        title="ASHRAE Handbook — Fundamentals", publisher="ASHRAE", year=2017, locator="гл. 1",
        applies_to="влажный воздух и давление на высоте площадки",
        statement="Психрометрические соотношения и давление стандартной атмосферы по высоте.",
        how_used="Плотность и влагосодержание воздуха считаются при давлении на высоте `altitude_m`.",
    ),
    Source(
        id="era5_open_meteo", kind="data",
        citation="ERA5 via Open-Meteo (CC BY 4.0), 2015–2024",
        title="ERA5 reanalysis via Open-Meteo Historical Weather API", publisher="ECMWF / Open-Meteo",
        year=2024, locator="часовые данные 2015–2024", url="https://open-meteo.com",
        applies_to="расчётные температуры площадки (`getClimateDesign`)",
        statement="Почасовые температура и влажность реанализа ERA5 за 10 лет.",
        how_used="Зима — температура обеспеченностью 99.6 %; лето — 0.4 % по сухому термометру "
                 "с совпадающей влажностью и 0.4 % по мокрому (предел панелей).",
        limits="Реанализ сглаживает местные условия (низины, побережье) — при местных данных "
               "лучше передать свои температуры.",
    ),
    Source(
        id="effective_temp_table", kind="unverified",
        citation="Effective temperature vs air speed table (°F-based, used in the app's "
                 "tunnel tab; primary source not identified — audit 2026-10-18)",
        title="Таблица эффективной температуры от скорости воздуха", publisher="—", year=None,
        locator=None,
        applies_to="ощущаемая температура птицы в туннеле (расчёт «сейчас»)",
        statement="Ощущаемая температура в зависимости от температуры, влажности 50–70 % и скорости.",
        how_used="`effective_temp_c` в ответе «сейчас»; сравнивается с пределом 30 °C (Cobb).",
        limits="Первоисточник таблицы не установлен — значение ориентировочное, называть его "
               "нормой нельзя.",
    ),

    # ── Практика владельца ─────────────────────────────────────────────────────
    Source(
        id="practice_tunnel_rules_2026", kind="practice",
        citation="Poultry farmers' practice reported by the owner, 2026-10-19: "
                 "tunnel ventilation from day 21 at outdoor temperature ≥ 24 °C",
        title="Правила включения туннеля", publisher="практика птицеводов со слов владельца",
        year=2026, locator=None,
        applies_to="с какого дня и при какой наружной температуре включается туннель",
        statement="Туннель — с 21-го дня и при наружной температуре не ниже 24 °C.",
        how_used="Пороги по умолчанию; свои передаются в `tunnel_rules`.",
        limits="Не публикация и не норма — практика эксплуатации.",
    ),
    Source(
        id="practice_cage_tunnel_2026", kind="practice",
        citation="Owner's operating practice for cage houses, 2026-10-19: "
                 "4–5 m/s in aisles for ~2–2.5 m/s at the birds",
        title="Туннель клеточного зала", publisher="практика эксплуатации владельца", year=2026,
        locator=None,
        applies_to="цель туннеля в клеточном зале",
        statement="В проходах между батареями держат 4–5 м/с, чтобы у птицы в клетках было "
                  "~2–2.5 м/с; батареи создают сопротивление потоку.",
        how_used="Расход = 4–5 м/с × свободное сечение (сечение корпуса минус сечение батарей); "
                 "скорость у птицы — половина скорости в проходе.",
        limits="Не публикация и не норма. Потери давления по длине зала не учтены до замеров.",
    ),
)


CATALOG: dict[str, Source] = {s.id: s for s in _SOURCES}


def get_source(source_id: str) -> Optional[Source]:
    return CATALOG.get(source_id)


def citation(source_id: str) -> Optional[str]:
    s = CATALOG.get(source_id)
    return s.citation if s else None


def as_dict(s: Source) -> dict:
    """Запись для API: пустые необязательные поля не отдаются."""
    return {k: v for k, v in asdict(s).items() if v is not None}
