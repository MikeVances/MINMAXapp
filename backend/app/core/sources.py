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
        publisher="CIGR Working Group", year=2002,
        locator="в изложении Aarnink et al. 2018, ур. 11 и 13; поправка по T — отчёт CIGR, ур. 26, с. 18",
        applies_to="тепло птицы в балансе корпуса (обогрев, Qmax по теплу, влага) — напольное содержание",
        statement="Полное тепло 10.62·W^0.75 Вт при 20 °C; для птицы вне 20 °C — 1000 + 20·(20 − t) "
                  "Вт на hpu (ур. 26). Доля явного тепла на уровне КОРПУСА убывает с температурой "
                  "(часть тепла уходит на испарение влаги из подстилки).",
        how_used="Явное тепло корпуса греет воздух и снижает потребность в горелках; скрытое — "
                 "влага, которую выносит вентиляция.",
        limits="В первые недели формула переоценивает скрытую долю — для Qmin по влаге это "
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
               "калькулятор не делает. В конце цикла уставка выходит 14–17 °C — ниже, чем обычно "
               "держат на фермах: по словам технологов, так низко опускают в основном при "
               "проблемах с отоплением. Калькулятор всё равно следует производителю (решение "
               "владельца 2026-10-21): «прохладно» технологу кажется чаще, чем птице, а "
               "настоящий критерий — распределение птицы по полу, этих данных у калькулятора "
               "нет. Низкая уставка в холодную и сырую погоду поднимает минимальную вентиляцию "
               "по влаге, и обогрев может не снизиться.",
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

    # ── Индейка ────────────────────────────────────────────────────────────────
    Source(
        id="cigr_2002_turkey", kind="research",
        citation="CIGR (2002) Heat and moisture production at animal and house levels, §2.7.4 — turkeys",
        title="Heat and moisture production at animal and house levels",
        publisher="CIGR Working Group (Pedersen & Sällvik, eds.)", year=2002,
        locator="§2.7.4, ур. 19, с. 12; табл. 2.2, с. 13; ур. 26, с. 18",
        applies_to="тепло индейки в балансе корпуса (обогрев, Qmax по теплу, влага, CO₂)",
        statement="Полное тепло индейки в термонейтральной зоне Φtot = 9.86·m^0.77 Вт (m — масса, кг; "
                  "Chepete & Xin 2002, индейка 1992–1998). Поправка по температуре для птицы — "
                  "ур. 26: 1000 + 20·(20 − t) Вт на hpu.",
        how_used="Полное тепло — ур. 19 с поправкой ур. 26; доля явного тепла на уровне корпуса — "
                 "бройлерная (ур. 33 / Aarnink ур. 13, подстилка), решение владельца 2026-10-26.",
        limits="Своей доли явного тепла индейки на уровне корпуса в CIGR нет. Косвенная сверка: у "
               "индюка 8.9 кг при 18 °C в камере явное тепло 69 % (Ota & McNally 1961), бройлерная "
               "формула корпуса даёт 54 % — разница отчасти от испарения подстилки, которого в камере "
               "нет. Обзор Chepete & Xin 2001 даёт для той же группы 9.83·M^0.74, рецензируемая "
               "версия 2002 (по ней CIGR) не получена. Данных по тяжёлым индюкам мало.",
        url="https://www.cigr.org/sites/default/files/documets/CIGR_4TH_WORK_GR.pdf",
    ),
    Source(
        id="xin_1998_turkey", kind="research",
        citation="Xin H. et al. (1998) Heat and moisture production and minimum ventilation "
                 "requirements of tom turkeys during brooding-growing period",
        title="Heat and Moisture Production and Minimum Ventilation Requirements of Tom Turkeys "
              "During Brooding-growing Period",
        publisher="Transactions of the ASAE 41(5):1489–1498", year=1998, locator="ур. 6",
        applies_to="масса суточного индюшонка (день 0) во встроенных профилях индейки",
        statement="Масса индюков Nicholas на подстилке по возрасту: BM = 0.0109·D³ + 0.7124·D² + "
                  "10.057·D + 55.6 г, D — сутки; при D = 0 — 55.6 г.",
        how_used="Точка дня 0 профилей B.U.T. 6 и Converter: в таблицах производителей массы "
                 "суточной птицы нет, а край недели 1 (0.15–0.18 кг) завысил бы тепло и CO₂ "
                 "первых дней втрое.",
        limits="Другой кросс (Nicholas) и 1990-е годы; самки — то же значение.",
        url="https://doi.org/10.13031/2013.17299",
    ),
    Source(
        id="aviagen_turkey_cl23_t5", kind="manufacturer",
        citation="Aviagen Turkeys, Management Guidelines for Commercial Turkeys CL23 V4, Table 5 — "
                 "target environmental temperatures",
        title="Management Guidelines for Commercial Turkeys", publisher="Aviagen Turkeys", year=2024,
        locator="табл. 5, с. 21; RH — табл. 8, с. 26",
        applies_to="уставка температуры по дням для B.U.T. 6",
        statement="Обогрев всего корпуса (Whole House Brooding), M+F: день 1 — 36–37 °C, 2 — 35–36, "
                  "3 — 34–35, дни 4–7 — «decrease 1 °C per day», нед. 2 — 27–28, 3 — 25–26, 4 — 23–24, "
                  "5 — 21–22, 6 — 20–21, 7 — 19–20, 8 — 18–19, 9 — 17–18, с 10-й «until depletion» — "
                  "16–17. RH 50–70 % (табл. 8).",
        how_used="Уставка дня — нижняя граница диапазона ступенью на всю неделю (решение владельца "
                 "2026-10-26); дни 4–7 — 33, 32, 31, 30 °C. Поправки на RH нет. Целевая RH — 70 %, "
                 "верх диапазона: потолок влагобаланса.",
        limits="Дни 4–7 — наше прочтение «минус 1 °C в день» от 34 °C. Колонка Ambient (обогрев "
               "кольцами) для дней 1–7 в таблице пуста — брудинг кольцами не считается.",
        url="https://aviagenturkeys.com/wp-content/uploads/2025/08/"
            "CL23_V4_Management-Guidelines-for-Growing-Commercial-Turkeys_EN.pdf",
    ),
    Source(
        id="hybrid_turkey_cmg_p56", kind="manufacturer",
        citation="Hybrid Turkeys, Commercial Management Guide (2023), interior temperature guidelines",
        title="Technical guide for Hybrid Turkeys commercial products", publisher="Hybrid Turkeys",
        year=2023, locator="с. 56 (раздельно по полу), с. 57 (смешанные стада); RH — с. 46",
        applies_to="уставка температуры по дням для Converter и ConverterNOVO",
        statement="Колонка Whole room brooding without radiant heaters, самцы: 1–7 сут — 35 °C, "
                  "8–14 — 31, 15–21 — 28, 22–28 — 25, 29–35 — 23, 36–42 — 22, 43–56 — 20, 57–63 — 19, "
                  "64–70 — 18, 71–77 — 17, 78–84 — 16, 85–98 — 15, > 99 — 14; самки до 49 сут — так же, "
                  "50–56 — 19, 57–91 — 18. RH 40–60 %.",
        how_used="Уставка дня — ступенью по таблице своего пола, без поправки на RH; после конца "
                 "таблицы самок (91 сут) — 18 °C. Целевая RH — 60 %, верх диапазона.",
        limits="Брудинг кольцами и обогрев с излучателями (колонки 29 и 32 °C в первую неделю) не "
               "считаются: взята колонка обогрева всего корпуса — худшая для отопления.",
        url="https://www.hendrix-genetics.com/documents/2183/Commercial_Management_Guide_EN.pdf",
    ),
    Source(
        id="aviagen_turkey_cl23_min_vent", kind="manufacturer",
        citation="Aviagen Turkeys CL23 V4 — minimum ventilation 1 m³ per kg live weight per hour",
        title="Management Guidelines for Commercial Turkeys", publisher="Aviagen Turkeys", year=2024,
        locator="раздел Ventilation, с. 30",
        applies_to="минимальная вентиляция (Qmin) для B.U.T. 6",
        statement="«ventilate a turkey house by providing a constant minimum ratio of 1m3 of air /kg "
                  "live weight/hour. This is applicable throughout the production cycle» (CO₂ < 2500 ppm).",
        how_used="Норма = 1 м³/ч × масса профиля × живое поголовье; Qmin = max(CO₂, норма, влага), "
                 "основание guide, если правит норма.",
        limits="У тяжёлого индюка норма примерно вдвое выше расчёта по CO₂ — для Aviagen минимум "
               "на откорме почти всегда задаёт она.",
        url="https://aviagenturkeys.com/wp-content/uploads/2025/08/"
            "CL23_V4_Management-Guidelines-for-Growing-Commercial-Turkeys_EN.pdf",
    ),
    Source(
        id="hybrid_turkey_cmg_p46", kind="manufacturer",
        citation="Hybrid Turkeys, Commercial Management Guide (2023) — air renewal by week of age",
        title="Technical guide for Hybrid Turkeys commercial products", publisher="Hybrid Turkeys",
        year=2023, locator="с. 46 (таблица), с. 68",
        applies_to="минимальная вентиляция (Qmin) для Converter и ConverterNOVO",
        statement="1-я неделя: 1.7 м³/ч на м² при плотности < 10 гол/м² или 0.17 м³/ч на индейку при "
                  "> 10 гол/м²; 2-я — вдвое, 3-я — втрое, 4-я — вчетверо, «etc.». Объёмы — фактические, "
                  "с учётом потери производительности вентиляторов.",
        how_used="Норма = 0.17 м³/ч × неделя возраста × живое поголовье, при плотности < 10 гол/м² "
                 "и известной площади — 1.7 м³/ч × неделя × м² пола. Qmin = max(CO₂, норма, влага).",
        limits="Рост «etc.» после 4-й недели — наше продолжение линейного ряда. На откорме норма "
               "ниже расчёта по CO₂, и минимум задаёт CO₂.",
        url="https://www.hendrix-genetics.com/documents/2183/Commercial_Management_Guide_EN.pdf",
    ),
    Source(
        id="hybrid_turkey_cmg_p51", kind="manufacturer",
        citation="Hybrid Turkeys, Commercial Management Guide (2023) — tunnel ventilation, 2 m/s",
        title="Technical guide for Hybrid Turkeys commercial products", publisher="Hybrid Turkeys",
        year=2023, locator="с. 51",
        applies_to="проектная скорость воздуха в тоннеле для индейки",
        statement="«An air speed of 2 m/s (approximately 7 kph) reduces perceived temperature by 6 to "
                  "10°C»; мощность вентиляторов VP = S × A × 3600 (S — сечение, A — нужная скорость).",
        how_used="Цель тоннеля индейки — 2 м/с в сечении корпуса (решение владельца 2026-10-26); "
                 "пределы скорости по возрасту — бройлерные Cobb §9.7.",
        limits="Это иллюстрация, а не норма: другой цифры у источников индейки нет (Aviagen CL23 "
               "даёт только график wind chill). Пределы по возрасту перенесены с бройлера.",
        url="https://www.hendrix-genetics.com/documents/2183/Commercial_Management_Guide_EN.pdf",
    ),
    Source(
        id="hybrid_turkey_ventcalc", kind="manufacturer",
        citation="Hybrid Turkeys, Ventilation Calculator Metric v28032022 — installed minimum ventilation",
        title="Ventilation Calculator Metric", publisher="Hybrid Turkeys", year=2022,
        locator="лист расчёта, примечание к норме брудера",
        applies_to="установленная мощность вентиляторов минвентиляции для индейки",
        statement="«Hybrid recommends a minimum of 18.3 m3h/m2 for brooders»; справочно Brood 18.3, "
                  "Finish 27.5, Tunnel 36.6 м³/ч·м² (автор ссылается на Czarick, UGA).",
        how_used="Нижняя граница вентиляторов минвентиляции — 18.3 м³/ч·м² в брудере и 27.5 на "
                 "доращивании (решение владельца 2026-10-26).",
        limits="Значение Finish в файле справочное, рекомендацией названо только 18.3 для брудера.",
        url="https://www.hybridturkeys.com/documents/1191/Ventilation_Calculator_Metric_v28032022.xlsx",
    ),
    Source(
        id="aviagen_turkey_cl23_density", kind="manufacturer",
        citation="Aviagen Turkeys CL23 V4 — stocking density for brood and move",
        title="Management Guidelines for Commercial Turkeys", publisher="Aviagen Turkeys", year=2024,
        locator="с. 13; табл. 2, с. 12",
        applies_to="предупреждение о плотности посадки индейки",
        statement="В брудерном корпусе — не больше 8–10 птиц на м², на доращивании — 2.8–3.2 самца "
                  "или 5–6 самок на м².",
        how_used="Предупреждение, если живое поголовье на м² пола выше верхней границы: брудер 10, "
                 "доращивание 3.2 (самцы) или 6 (самки). Предел Cobb 42 кг/м² к индейке не применяется.",
        limits="Плотности в кг/м² руководство не даёт; для смешанного стада на доращивании предела "
               "нет — предупреждение не выдаётся.",
        url="https://aviagenturkeys.com/wp-content/uploads/2025/08/"
            "CL23_V4_Management-Guidelines-for-Growing-Commercial-Turkeys_EN.pdf",
    ),

    # ── Родительское стадо бройлеров (напольное содержание) ─────────────────────
    Source(
        id="cigr_2002_breeder", kind="standard",
        citation="CIGR Working Group (2002), §2.7.3 eq. 18 — laying hens & broiler breeders on floor "
                 "total heat Φtot = 6.8·m^0.75 + 25·Y₂; eq. 26 — temperature correction",
        title="Heat and moisture production at animal and house levels",
        publisher="CIGR Working Group (Pedersen & Sällvik, eds.)", year=2002,
        locator="§2.7.3, ур. 18, с. 11–12; табл. 2.2, с. 13; ур. 26, с. 18",
        applies_to="тепло родительского стада бройлеров в балансе корпуса (обогрев, Qmax, влага, CO₂)",
        statement="Полное тепло кур и родительского стада при 20 °C на полу: Φtot = 6.8·m^0.75 + 25·Y₂ Вт "
                  "(m — живая масса, кг; Y₂ — суточная яйцемасса, кг/сут; у ремонтного молодняка и петухов "
                  "Y₂ = 0). Поправка по температуре — ур. 26: (1000 + 20·(20 − t))/1000.",
        how_used="Полное тепло — ур. 18 с поправкой ур. 26; доля явного тепла на уровне корпуса — "
                 "бройлерная подстилочная (ур. 33 / Aarnink ур. 13), решение владельца 2026-11-03.",
        limits="В ремонте при жёстком ограничении корма ур. 18 без поправки на уровень кормления "
               "завышает теплопродукцию молодняка на ~15–35 % по сравнению с калориметрией кроссов "
               "на ограниченном кормлении (Sakomura et al. 2004, Poultry Sci. 83:1085; Teofilo et al. "
               "2022, Poultry Sci. 101:101908) — запас в сторону большего летнего воздухообмена, но "
               "возможна недооценка зимнего обогрева. Справочно РД-АПК 1.10.05.04-13 (прил. А, табл. А.2) "
               "даёт для мясных кур при 18 °C на ~7 % больше явного тепла за счёт меньшего списания на подстилку.",
        url="https://www.cigr.org/sites/default/files/documets/CIGR_4TH_WORK_GR.pdf",
    ),
    Source(
        id="ross_ps_2023_t4", kind="manufacturer",
        citation="Aviagen, Ross Parent Stock Management Handbook (2023), Table 4 — brooding temperatures",
        title="Ross Parent Stock Management Handbook", publisher="Aviagen", year=2023,
        locator="табл. 4, с. 25; Ross 308 PS PO (2021), с. 6",
        applies_to="уставка температуры и влажности по дням для Ross 308 PS",
        statement="Обогрев всего корпуса (Whole-House Brooding Temp при RH 60–70 %): суточные — 30 °C, "
                  "3 дн — 28, 6 — 27, 9 — 26, 12 — 25, 15 — 24, 18 — 23, 21 — 22, 24 — 21, 27 — 20 °C. "
                  "В продуктивном периоде целевая температура корпуса 20–21 °C (PO 2021, с. 6).",
        how_used="Ступени брудинга до 24-го дня — по табл. 4; далее нижняя граница диапазона по этапу "
                 "(решение владельца 2026-11-03): в ремонте (24–140 дн) 21 °C, в продуктивном периоде "
                 "(с 141-го дня) 20 °C. Поправки на RH нет; целевая RH — 70 % (верх диапазона табл. 4).",
        limits="Колонки локального обогрева (Spot Brooding) не используются: расчёт ведётся по "
               "температуре воздуха корпуса в зоне птицы.",
        url="https://aviagen.com/assets/Tech_Center/Ross_PS/RossPSHandBook2023.pdf",
    ),
    Source(
        id="cobb_breeder_2021_temp", kind="manufacturer",
        citation="Cobb Breeder Management Guide (2021) — floor temperature and relative humidity",
        title="Cobb Breeder Management Guide", publisher="Cobb-Vantress", year=2021,
        locator="с. 26 (брудинг), с. 55 (продуктивный период), с. 116 (RH 45–65 %)",
        applies_to="уставка температуры и влажности по дням для Cobb 500 FF и Cobb MX",
        statement="Температура пола при 60 % RH: 0–3 сут — 31 °C, 4–7 — 30, 8–15 — 29, 16–18 — 28, "
                  "19–21 — 26, 22–24 — 24, 25–27 — 22, с 28-го дня — 21–22 °C. Целевая RH — 45–65 %.",
        how_used="Уставка дня — ступенью по возрасту, с 28-го дня — нижняя граница 21 °C (решение "
                 "владельца 2026-11-03), без поправки на RH. Целевая RH — 65 % (верх диапазона).",
        limits="Поправка на плотность посадки бройлерного руководства Cobb §5.2 к родительскому "
               "стаду не применяется (плотность во много раз ниже бройлерной).",
        url="https://www.cobbgenetics.com/assets/Cobb-Files/Cobb-Breeder-Management-Guide.pdf",
    ),
    Source(
        id="ross_ps_2023_t25", kind="manufacturer",
        citation="Aviagen, Ross Parent Stock Management Handbook (2023), Table 25 — minimum ventilation "
                 "rates per bird by body weight",
        title="Ross Parent Stock Management Handbook", publisher="Aviagen", year=2023,
        locator="табл. 25, с. 113",
        applies_to="минимальная вентиляция (Qmin) производителя для Ross 308 PS",
        statement="Минимальный воздухообмен на одну птицу при температуре ниже −5 °C по живой массе "
                  "(31 строка от 0.05 кг → 0.09 м³/ч·гол до 5.00 кг → 2.89 м³/ч·гол, пропорционально m^0.75).",
        how_used="Линейная интерполяция по живой массе птицы (в совместном стаде — сумма по курам и "
                 "петухам); Qmin = max(CO₂, норма табл. 25, влага).",
        limits="Таблица дана как ориентир для холодной погоды (< −5 °C); в расчёте выступает нижней "
               "границей наряду с физическим балансом CO₂ и влаги.",
        url="https://aviagen.com/assets/Tech_Center/Ross_PS/RossPSHandBook2023.pdf",
    ),
    Source(
        id="ross_ps_2023_t18", kind="manufacturer",
        citation="Aviagen, Ross Parent Stock Management Handbook (2023), Table 18 — typical mating ratios",
        title="Ross Parent Stock Management Handbook", publisher="Aviagen", year=2023,
        locator="табл. 18, с. 66",
        applies_to="доля петухов в продуктивном корпусе Ross 308 PS при совместном содержании",
        statement="Число петухов на 100 кур по возрасту: 22–24 нед — 9.25–10.00, 24–30 нед — 8.50–9.50, "
                  "30–35 нед — 8.00–8.50, 35–40 нед — 7.50–8.00, 40–50 нед — 7.00–7.50, 50 нед до "
                  "выбраковки — 6.50–7.00.",
        how_used="В продуктивном периоде (stage = production) к поголовью кур Ross 308 PS автоматически "
                 "добавляются петухи (профиль ross308-ps-males) по верхней границе диапазона возраста "
                 "(10.0 % → 7.0 %), если вторая группа не задана явно.",
        limits="Принята верхняя граница вилки для кондиционных петухов — консервативно для тепла и вентиляции.",
        url="https://aviagen.com/assets/Tech_Center/Ross_PS/RossPSHandBook2023.pdf",
    ),
    Source(
        id="cobb_breeder_2021_males", kind="manufacturer",
        citation="Cobb Breeder Management Guide (2021) — male to female ratio in production",
        title="Cobb Breeder Management Guide", publisher="Cobb-Vantress", year=2021,
        locator="с. 51",
        applies_to="доля петухов в продуктивном корпусе Cobb 500 FF при совместном содержании",
        statement="«8 to 9 % males in slatted houses and 9 to 10 % males in deep litter houses».",
        how_used="В продуктивном периоде (stage = production) к поголовью кур Cobb 500 FF автоматически "
                 "добавляются 10 % петухов (профиль cobb-mx-males, верхняя граница вилки), если вторая "
                 "группа не задана явно.",
        limits="Постоянная доля 10 % без ступенчатого выбраковывания (spiking компенсирует отход).",
        url="https://www.cobbgenetics.com/assets/Cobb-Files/Cobb-Breeder-Management-Guide.pdf",
    ),
    Source(
        id="cobb_breeder_2021_tunnel", kind="manufacturer",
        citation="Cobb Breeder Management Guide (2021) & Ross PS Handbook (2023) — tunnel air speed",
        title="Cobb Breeder Management Guide", publisher="Cobb-Vantress", year=2021,
        locator="Cobb с. 123; Ross PS Handbook 2023 с. 172",
        applies_to="проектная скорость воздуха в тоннеле для родительского стада",
        statement="Cobb с. 123: ремонтные птичники (pullet houses) — 2.0–2.5 м/с, продуктивные корпуса "
                  "(breeder houses in production) — 2.5–3.0 м/с; Ross PS с. 172: проектная скорость "
                  "в продуктивном корпусе 3.0 м/с (600 фут/мин).",
        how_used="Цель тоннеля родительского стада — верхняя граница по этапу: 2.5 м/с в ремонте "
                 "(rearing) и 3.0 м/с в продуктивном периоде (production).",
        limits="Пределы скорости у молодой птицы до 21-го дня — общие по таблице Cobb (с. 123 / §9.7).",
        url="https://www.cobbgenetics.com/assets/Cobb-Files/Cobb-Breeder-Management-Guide.pdf",
    ),
    Source(
        id="ross_ps_2023_density", kind="manufacturer",
        citation="Aviagen, Ross Parent Stock Management Handbook (2023), Tables 7 & 14 — stocking density",
        title="Ross Parent Stock Management Handbook", publisher="Aviagen", year=2023,
        locator="табл. 7, с. 30 (ремонт); табл. 14, с. 49 (продуктивный период)",
        applies_to="предупреждение о плотности посадки родительского стада Ross 308 PS",
        statement="Ремонт (15–140 сут, табл. 7): петушки 3–4 гол/м², курочки 4–8 гол/м². "
                  "Продуктивный период (140 сут — выбраковка, табл. 14): самцы и самки совместно "
                  "4.5–5.5 гол/м².",
        how_used="Предупреждение, если живое поголовье на м² пола превышает верхнюю границу: ремонт "
                 "8.0 (курочки) или 4.0 (петушки), продуктивный период — 5.5 гол/м² (включая петухов).",
        limits="Приведены ориентиры для умеренного климата; в жарком климате руководство рекомендует "
               "нижнюю границу диапазона.",
        url="https://aviagen.com/assets/Tech_Center/Ross_PS/RossPSHandBook2023.pdf",
    ),
    Source(
        id="cobb_breeder_2021_density", kind="manufacturer",
        citation="Cobb Breeder Management Guide (2021) & Cobb MX Male Supplement (2026) — stocking density",
        title="Cobb Breeder Management Guide", publisher="Cobb-Vantress", year=2021,
        locator="Guide с. 20 (ремонт), с. 49 (продуктивный период); MX Male Supplement 2026 с. 2",
        applies_to="предупреждение о плотности посадки родительского стада Cobb 500 FF и Cobb MX",
        statement="Ремонт: курочки 7–10 гол/м² в закрытом птичнике (с. 20), петушки 3.1–3.6 гол/м² "
                  "(MX Supplement с. 2; Guide с. 20 — 3.5 гол/м²). Продуктивный период (с. 49): "
                  "5–7 гол/м².",
        how_used="Предупреждение, если живое поголовье на м² пола превышает верхнюю границу: ремонт "
                 "10.0 (курочки) или 3.6 (петушки), продуктивный период — 7.0 гол/м² (включая петухов).",
        limits="В открытых корпусах и жарком климате допустимая плотность ниже (5–7 гол/м² в ремонте, "
               "5–6 в продуктивном периоде).",
        url="https://www.cobbgenetics.com/assets/Cobb-Files/Cobb-Breeder-Management-Guide.pdf",
    ),

    # ── Ремонтный молодняк и промышленные несушки в клетках (layer) ─────────────
    Source(
        id="cigr_2002_layer_cages", kind="standard",
        citation="CIGR Working Group (2002), §2.7.2 eq. 17 & §3.3.2 eq. 34 — laying hens in cages "
                 "total heat Φtot = 6.28·m^0.75 + 25·Y₂ and house-level sensible heat",
        title="Heat and moisture production at animal and house levels",
        publisher="CIGR Working Group (Pedersen & Sällvik, eds.)", year=2002,
        locator="§2.7.2, ур. 17, с. 12; §2.10, ур. 26, с. 18; §3.3.2, ур. 34, рис. 3.7, с. 26–27",
        applies_to="полное, явное и скрытое тепло молодняка и несушек в клетках (обогрев, Qmax, влага, CO₂)",
        statement="Полное тепло кур-несушек в клетках при 20 °C: Φtot = 6.28·m^0.75 + 25·Y₂ Вт "
                  "(m — живая масса, кг; Y₂ — суточная яйцемасса, кг/сут; у ремонтного молодняка Y₂ = 0). "
                  "Поправка по температуре — ур. 26: [1000 + 20·(20 − t)]/1000. Явное тепло клеточного зала "
                  "на 1 hpu (1000 Вт при 20 °C) по измерениям в Северной Европе (Pedersen et al., 1998) — "
                  "ур. 34: Φs = 0.67·(1000 + 20·(20 − t)) − 9.8·10⁻⁸·t⁶ Вт.",
        how_used="Для вида птицы layer полное тепло считается по ур. 17 с поправкой ур. 26, а доля явного "
                 "тепла клеточного зала — напрямую по ур. 34 (зимой и летом без вилки подстилка/птица).",
        limits="Уравнение 34 получено на клеточных корпусах с помётными лентами в умеренном климате "
               "Северной Европы; при длительном хранении помёта под клетками доля скрытого тепла выше.",
        url="https://www.cigr.org/sites/default/files/documets/CIGR_4TH_WORK_GR.pdf",
    ),
    Source(
        id="lohmann_cage_2019", kind="manufacturer",
        citation="Lohmann Tierzucht — Management Guide Cage Housing (LSL-Classic & Brown-Classic), "
                 "Table 1 (temperatures & RH), Table 17 (body weight), Table 18 (egg mass)",
        title="Management Guide Cage Housing: Lohmann LSL-Classic / Lohmann Brown-Classic",
        publisher="Lohmann Tierzucht", year=2019,
        locator="табл. 1–2, с. 10; табл. 17, с. 34–35; табл. 18, с. 38–39",
        applies_to="профили роста, яйцемассы и температуры в клетках для Lohmann LSL-Classic и Brown-Classic",
        statement="Температура на уровне птицы: 1–2 сут — 35–36 °C, 3–4 — 33–34, 5–7 — 31–32, 2-я нед. — 28–29, "
                  "3-я нед. — 26–27, 4-я нед. — 22–24, с 5-й недели — 18–20 °C; относительная влажность "
                  "60–70 %; CO₂ < 0.3 % (3000 ppm), NH₃ < 20 ppm.",
        how_used="Уставка дня — середина рекомендованного диапазона температуры по возрасту и RH 65 %; "
                 "живая масса (1–72 нед.) и суточная яйцемасса Y₂ (19–72 нед.) — по таблицам 17 и 18.",
        limits="Отдельной таблицы минимального воздухообмена в м³/ч·гол руководство не задаёт — "
               "ориентиром служат пределы газов (CO₂ < 3000 ppm) и влагобаланс.",
        url="https://lohmann-breeders.com/",
    ),
    Source(
        id="hyline_cage_2025", kind="manufacturer",
        citation="Hy-Line International — Performance Standards Guide, Conventional Systems: "
                 "Hy-Line Brown (2025) & Hy-Line W-36 (2020)",
        title="Hy-Line Brown & W-36 Commercial Layers Performance Standards Guide (Conventional Systems)",
        publisher="Hy-Line International", year=2025,
        locator="с. 4 (Rearing 1–17 нед.), с. 5–6 (Production 18–100 нед.), с. 9 (Brooding Temp Cage)",
        applies_to="профили роста, яйцемассы и температуры в клетках для Hy-Line Brown и Hy-Line W-36",
        statement="Температура воздуха в клетках при брудинге: 0–3 сут — 33–36 °C (Brown) / 32–33 °C (W-36), "
                  "4–7 — 30–32, 8–14 — 28–30, 15–21 — 26–28, 22–28 — 23–26, 29–35 — 21–23, с 36-го дня — "
                  "21 °C (в продуктивном периоде 18–25 °C, оптимум ~20 °C); RH ~60 %.",
        how_used="Живая масса и яйцемасса — середина нормативной вилки Low–High по неделям 1–72; "
                 "уставка температуры — середина диапазона для клеток.",
        limits="Таблицы даны для конвенциональных и колониальных клеток при нормальном кормлении.",
        url="https://www.hyline.com/",
    ),
    Source(
        id="hyline_2018_xin_vent", kind="manufacturer",
        citation="Hy-Line Brown Commercial Layers Management Guide (2018), Air Movement Table "
                 "(Dr. Hongwei Xin, Iowa State University)",
        title="Hy-Line Brown Commercial Layers Management Guide",
        publisher="Hy-Line International", year=2018,
        locator="раздел Air Quality, с. 17",
        applies_to="минимальная вентиляция (Qmin) производителя для Hy-Line Brown и Hy-Line W-36",
        statement="Минимальный воздухообмен при наружной температуре −12…−23 °C (м³/ч на 1000 голов): "
                  "1 нед. — 75, 3 нед. — 110, 6 нед. — 210, 12 нед. — 400, 18 нед. — 600, 19+ нед. — "
                  "700–850. Общее правило подбора установленной мощности вентиляторов — 4 м³/ч на 1 кг живой массы.",
        how_used="Линейная интерполяция зимнего минимума (0.075 → 0.700 м³/ч·гол) по возрасту птицы; "
                 "Qmin = max(CO₂, норма руководства, влага).",
        limits="При стандартном коэффициенте запаса CO₂ = 1.5 расчёт по CIGR (ур. 17) лежит немного выше "
               "строки −12…−23 °C; норма руководства срабатывает как нижний порог при снижении запаса CO₂.",
        url="https://www.hyline.com/",
    ),
    Source(
        id="hendrix_cage_2018_vent", kind="manufacturer",
        citation="Hendrix Genetics — Commercial Management Guide Cage Housing, §7.9 Ventilation — "
                 "minimum air exchange rate 0.7 m³/h/kg",
        title="Commercial Management Guide Cage Housing",
        publisher="Hendrix Genetics", year=2018,
        locator="§7.3, с. 42; §7.9 Ventilation, с. 47",
        applies_to="минимальная вентиляция (Qmin) в расчёте на 1 кг живой массы для клеточных несушек",
        statement="«The minimum air exchange rate is 0.7 m³ / hour / kg live bird»; требуемая мощность "
                  "вентиляторов 4 м³/ч на 1 кг живой массы (с. 42), CO₂ ≤ 2500 ppm, NH₃ ≤ 20 ppm.",
        how_used="При выборе нормы hendrix_cage_07 нижняя граница Qmin равна 0.7 м³/ч × живая масса (кг).",
        limits="Удельный минимум 0.7 м³/ч·кг не учитывает нелинейность метаболизма (m^0.75) у суточного цыплёнка.",
        url="https://www.hendrix-genetics.com/",
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
        citation="SANHE evaporative pad curves (digitised manufacturer data)",
        title="Кривые испарительных панелей", publisher="SANHE", year=None, locator=None,
        applies_to="панели 7060, 5090 и 7090 толщиной 75 мм: КПД насыщения и сопротивление",
        statement="КПД насыщения и падение давления на панели в зависимости от скорости воздуха "
                  "и толщины.",
        how_used="Слагаемое панелей в оценке давления туннеля и рабочей точке вентилятора; "
                 "КПД — в инструменте панельного охлаждения.",
        limits="Кривые оцифрованы с графиков производителя, исходный документ в проекте не сохранён "
               "и с поставщиком не сверен. У 7090 на больших скоростях КПД почти не падал — "
               "поэтому 7090 (кроме 75 мм) заменён кривыми Munters.",
    ),
    Source(
        id="munters_celdek_7090_15", kind="manufacturer",
        citation="Munters CELdek 7090-15 — Saturation efficiency and Pressure drop vs air velocity, "
                 "D = 100/150/200/300 mm",
        title="CELdek 7090-15: КПД насыщения и сопротивление", publisher="Munters", year=None,
        locator="графики производителя (передал владелец 2026-10-28)",
        applies_to="панели 7090 толщиной 100, 150, 200 и 300 мм",
        statement="КПД насыщения падает с ростом скорости: 150 мм — 91 % при 0.5 м/с, 83 % при 2 м/с, "
                  "79 % при 3 м/с. Сопротивление 150 мм при 2 м/с ≈ 54 Па. От 3 м/с — "
                  "риск уноса капель (серая зона графика).",
        how_used="КПД — по фактической скорости через панель в инструменте панельного охлаждения; "
                 "сопротивление — в давлении туннеля и рабочей точке вентилятора.",
        limits="Оцифровано по цвету пикселей (около 0.3 % КПД и 3 % сопротивления). ΔP ниже 5 Па и "
               "выше 200 Па — за шкалой графика, продолжено степенной зависимостью. Название документа "
               "и год не известны.",
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
