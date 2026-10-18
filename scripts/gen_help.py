"""
Генератор справки «Методика» (ключ help_body_html) для пяти словарей интерфейса.

Формулы (F) общие для всех языков — переводятся только заголовки и пояснения (T),
поэтому языки не могут разойтись в формулах. Меняешь физику в backend/app/core —
правь здесь и перезапусти:

    python3 scripts/gen_help.py

Скрипт заменяет строку help_body_html в backend/app/static/i18n/{en,ru,pl,de,fr}.js.
Апостроф в тексте запрещён (сломает JS-строку) — используй ’.
"""
import re
import sys
from pathlib import Path

I18N = Path(__file__).resolve().parents[1] / "backend" / "app" / "static" / "i18n"

# Формулы — одинаковые для всех языков (порядок разделов = порядок в T[lang]["s"])
F = {
    "co2": ["H_total = 10.62 × W^0.75 × N_eff   [W]",
            "Q_CO₂ = H_total × 0.153 / 2.6 × 1.5   [m³/h]"],
    "moist": ["f_T = (1000 + 20·(20 − T_in)) / 1000",
              "Q_sens = [0.61·(1000 + 20·(20 − T_in)) − 0.228·T_in²] / 1000 × 10.62·W^0.75   [W]",
              "Q_lat = 10.62·W^0.75 × f_T − Q_sens   [W]",
              "G = Q_lat × 3600 / 2430 × N_eff  (+ V_gas × 1607)   [g/h]",
              "Q_RH = G / (ρ_in × ΔW)  ≤  Q_ceiling   [m³/h]",
              "ΔW = W_in,max − W_out   W = 621.945·Pv/(101325 − Pv)   Psat = 611.2·exp(17.67·T/(T+243.5))"],
    "final": ["Q_min = max(Q_CO₂ + Q_dilution, Q_RH)"],
    "qmax": ["Q_max = (N_eff × Q_sens − UA × ΔT) × 3600 / (ρ_in × Cp × ΔT)  ≤  Q_ceiling",
             "ΔT = T_in − T_out   ρ_in = 353.05/(T_in + 273.15)   Cp = 1006 J/(kg·K)",
             "Q_ceiling = 4 × Q_CO₂ (age < tunnel_min_day)  |  Q_tunnel (age ≥ tunnel_min_day)"],
    "duty": ["P × d = UA×ΔT + ρ_in·Cp·ΔT·Q_min(d)/3600 − N_eff × Q_sens",
             "Q_min(d) = max(Q_CO₂ + Q_dilution(d), Q_RH(d))"],
    "flame": ["V_gas = P_kW / 10 × d   [m³/h]",
              "Q_dilution = V_gas × 1000 / 2.6 × 1.5   [m³/h]   (≈ 58 m³/(h·kW))"],
    "tunnel": ["Q_max = Q_tunnel  ⇐  age ≥ tunnel_min_day  ∧  T_out ≥ tunnel_min_temp  ∧  Q_heat > 0.5 × Q_tunnel",
               "Q_tunnel = v × S × 3600   v ≤ 0.3 (age < 5) · 0.5 (age < 14) · 1.8 m/s (age < 21)",
               "ΔT_rise = N × Q_sens / (ρ × Cp × Q)   T_fan end = T_inlet + ΔT_rise",
               "Fans:  N·(q₀ − s·P) = Q   P = ρ/2·(1/S² + 1/(A_in·Cd)²)·Q² + ΔP_pad(Q/A_in)   s = (q₀ − q₂₅)/25 Pa",
               "Tunnel sufficient:  v ≥ v_target(age)  ∧  T_eff(fan end) < 30 °C (Cobb 2021 §9.7);  T_eff > T_profile(day) → watch the birds"],
    "mort": ["S(day) = (1 − m_cycle)^((day − 1)/(cycle_days − 1))",
             "N_eff = N × S(day)"],
    "pad": ["W(T_wb) = [(2501 − 2.326·T_wb)·W_s(T_wb) − 1.006·(T − T_wb)] / (2501 + 1.86·T − 4.186·T_wb)  →  T_wb",
            "T_pad = T_db − η × (T_db − T_wb)"],
    "vel": ["v = Q / (pad_length × pad_height)",
            "Q = Q₀ − s × ΔP_pad(v)   s = (Q₀ − Q₂₅)/25 Pa",
            "A_rec = Q / v_design   v_design = 1.14 m/s (100 mm) · 1.78 m/s (150 mm)"],
    "water": ["ΔW = η × (W_sat(T_wb) − W_out)   [kg/kg]",
              "Q_water = Q/3600 × ρ_da(T_pad, W_out + ΔW) × ΔW × 60   [L/min]",
              "ρ_da = p / (287.042 · T_K · (1 + 1.607858·W))   [kg dry air / m³]"],
    "wsup": ["T_water < T_dew(T_out, RH_out)  →  ⚠"],
}

T = {
 "en": {
  "h2": "📐 Ventilation Calculation Methodology",
  "lead": "Physics-based model: Qmin = max(CO₂, moisture) including burners · Qmax = heat balance capped by the ventilation mode. SI units.",
  "s": [
   ("co2", "1 — Qmin: CO₂ balance (CIGR 1984)", "Biological minimum from live weight. Checked against the Aviagen 2018 rates within ~10 %.",
    "W = body weight [kg] · N_eff = effective flock · 0.153 = CO₂ yield · 2.6‰ = limit · 1.5 = safety"),
   ("moist", "2 — Qmin: moisture balance (CIGR 2002, house level)", "Vapour from birds and litter (and open-flame burners). Total heat is corrected for temperature (+2 % per °C below 20 °C), latent = total − house-level sensible.",
    "The more humid the outside air, the more air is needed — up to the ceiling of the mode; at the ceiling the target RH cannot be held by ventilation (heat or dehumidify)."),
   ("final", "3 — Qmin final", "Burner dilution air is added to the CO₂ branch, burner vapour to the moisture branch.", ""),
   ("qmax", "4 — Qmax: heat balance", "Air that removes the house-level sensible heat of the birds. UA is used only from a plausible calibration of this house (cooling-curve test ≥ 10 min, envelope U 0.1–8 W/(m²·K)).",
    "Cold: UA×ΔT > 0 → walls help cooling → Qmax ↓.   Hot: UA×ΔT < 0 → walls add load → Qmax ↑."),
   ("duty", "5 — Heater duty", "Solved together with the burners’ own dilution air, which must be heated too.",
    "If the equation cannot be met at d = 100 %, the heaters are reported as insufficient."),
   ("flame", "6 — Open-flame burners: CO₂ dilution", "1 m³ of gas → 1000 L of CO₂ → ~577 m³ of air to dilute it to 2.6‰ (≈ 40× the combustion air).",
    "At ΔT = 30 K heating this air takes ≈ 58 % of the burner power."),
   ("tunnel", "7 — Tunnel mode", "Tunnel only when the heat balance needs more than half of the tunnel flow — side-wall transitional ventilation covers 40–50 % (Ross 2025). Air speed limited by age (Cobb 2021). Qmin is unchanged.",
    "Tunnel tool: comfort is judged at the fan end, where the air is warmer. Wind cooling: table up to 29.4 °C, constant to 35 °C (UGA), fades to zero at 37.8 °C — bird surface temperature. Rise > 2.8 °C between ends is flagged (Cobb)."),
   ("mort", "8 — Mortality correction", "Cycle mortality spread evenly over the days.", ""),
   ("pad", "9 — Evaporative pad cooling", "The limit is the wet-bulb temperature of the outside air. Pad efficiency η and pressure drop come from the manufacturer curves (SANHE) by pad type, thickness and actual velocity — values for new pads; UGA field data: 70–75 %.",
    "T_wb is solved from the ASHRAE psychrometric equation (Fundamentals 2017, eq. 33), not Stull’s fit, which was off by up to +1 °C in hot dry air. Sufficiency is judged at the fan end: the cooled air warms over the birds."),
   ("vel", "9.1 — Air velocity through the pad", "With the 25 Pa rating the airflow is taken at the operating point including the pad resistance; otherwise the 0 Pa rating is used (overstated).",
    "Allowed range 0.6–2.5 m/s. Too high → water carried into the house · too low → mould risk."),
   ("water", "9.2 — Water consumption", "Psychrometric mass balance.", "The fans move the cooled, humidified air, so the dry-air mass is taken at the pad outlet. Check: UGA water chart, 90 °F / 60 % / 100,000 cfm, 6 in pad → 1.75 gpm; here 1.76 gpm at η = 0.75."),
   ("wsup", "9.3 — Water supply temperature", "Water colder than the dew point of the incoming air condenses vapour on the pad and lowers saturation — flagged. No correction of the pad outlet temperature is applied.", ""),
  ],
  "refs": "References: CIGR (1984, 2002) · Aarnink, CIGR Journal · Ross Broiler Handbook (2025) · Cobb Broiler Management Guide (2021) · UGA Poultry Housing Tips (Czarick) · University of Kentucky AFS ch. 9 · ASHRAE Fundamentals (2017) · SANHE pad data",
 },
 "ru": {
  "h2": "📐 Методика расчёта вентиляции",
  "lead": "Физическая модель: Qmin = max(CO₂, влага) с учётом горелок · Qmax = тепловой баланс в пределах режима вентиляции. Единицы СИ.",
  "s": [
   ("co2", "1 — Qmin: баланс CO₂ (CIGR 1984)", "Биологический минимум по живой массе. Сверен с нормами Aviagen 2018 в пределах ~10 %.",
    "W — масса птицы [кг] · N_eff — эффективное поголовье · 0.153 — выход CO₂ · 2.6‰ — предел · 1.5 — запас"),
   ("moist", "2 — Qmin: баланс влаги (CIGR 2002, уровень корпуса)", "Пар от птицы и подстилки (и горелок открытого пламени). Полное тепло с температурной поправкой (+2 % на каждый °C ниже 20 °C), скрытое = полное − явное корпуса.",
    "Чем влажнее наружный воздух, тем больше воздуха нужно — до потолка режима; на потолке целевую влажность вентиляцией не удержать (подогрев или осушение)."),
   ("final", "3 — Итоговый Qmin", "Воздух разбавления горелок прибавляется к ветке CO₂, пар горелок — к ветке влаги.", ""),
   ("qmax", "4 — Qmax: тепловой баланс", "Воздух, уносящий явное тепло птицы на уровне корпуса. UA берётся только из правдоподобной калибровки этого корпуса (тест по кривой остывания ≥ 10 мин, U оболочки 0.1–8 Вт/(м²·К)).",
    "Мороз: UA×ΔT > 0 → стены помогают охлаждению → Qmax ↓.   Жара: UA×ΔT < 0 → стены добавляют нагрузку → Qmax ↑."),
   ("duty", "5 — Загрузка горелок", "Решается вместе с собственным воздухом разбавления горелок — его тоже нужно нагреть.",
    "Если равенство недостижимо при d = 100 %, горелок не хватает — об этом выводится предупреждение."),
   ("flame", "6 — Горелки открытого пламени: разбавление CO₂", "1 м³ газа → 1000 л CO₂ → ~577 м³ воздуха для разбавления до 2.6‰ (≈ в 40 раз больше воздуха горения).",
    "При ΔT = 30 К нагрев этого воздуха забирает ≈ 58 % мощности горелки."),
   ("tunnel", "7 — Туннельный режим", "Туннель включается, только когда тепловой баланс требует больше половины туннельного расхода — переходная вентиляция через боковые клапаны покрывает 40–50 % (Ross 2025). Скорость ограничена по возрасту (Cobb 2021). Qmin не меняется.",
    "Инструмент «Туннель»: комфорт оценивается у вентиляторов, где воздух теплее. Охлаждение ветром: таблица до 29.4 °C, постоянно до 35 °C (UGA), к 37.8 °C — ноль (температура поверхности птицы). Нагрев > 2.8 °C между торцами отмечается (Cobb)."),
   ("mort", "8 — Поправка на падёж", "Падёж за цикл распределён равномерно по дням.", ""),
   ("pad", "9 — Панельное охлаждение", "Предел — температура мокрого термометра наружного воздуха. КПД панели η и сопротивление — по кривым производителя (SANHE) для типа, толщины и фактической скорости; это значения для новых панелей, по данным UGA в работе — 70–75 %.",
    "T_wb — решение психрометрического уравнения ASHRAE (Fundamentals 2017, ур. 33), а не аппроксимация Стулла: та в сухую жару ошибалась до +1 °C. Достаточность оценивается у вентиляторов: охлаждённый воздух нагревается над птицей."),
   ("vel", "9.1 — Скорость воздуха через панель", "С производительностью при 25 Па расход берётся в рабочей точке с сопротивлением панели; без неё — по паспорту при 0 Па (завышен).",
    "Допустимо 0.6–2.5 м/с. Выше → вода выносится в корпус · ниже → риск плесени."),
   ("water", "9.2 — Расход воды", "Психрометрический баланс массы.", "Вентиляторы качают уже охлаждённый увлажнённый воздух — масса сухого воздуха берётся на выходе панели. Сверка: карта расхода воды UGA, 90 °F / 60 % / 100 000 cfm, панель 15 см → 1.75 gpm; здесь 1.76 gpm при η = 0.75."),
   ("wsup", "9.3 — Температура подаваемой воды", "Вода холоднее точки росы входящего воздуха конденсирует пар на панели и снижает насыщение — это отмечается. Поправка температуры воздуха за панелью не применяется.", ""),
  ],
  "refs": "Источники: CIGR (1984, 2002) · Aarnink, CIGR Journal · Ross Broiler Handbook (2025) · Cobb Broiler Management Guide (2021) · UGA Poultry Housing Tips (Czarick) · University of Kentucky AFS гл. 9 · ASHRAE Fundamentals (2017) · данные панелей SANHE",
 },
 "pl": {
  "h2": "📐 Metodyka obliczania wentylacji",
  "lead": "Model fizyczny: Qmin = max(CO₂, wilgoć) z nagrzewnicami · Qmax = bilans cieplny w granicach trybu wentylacji. Jednostki SI.",
  "s": [
   ("co2", "1 — Qmin: bilans CO₂ (CIGR 1984)", "Minimum biologiczne z masy ciała. Zgodne z normami Aviagen 2018 w granicach ~10 %.",
    "W — masa ptaka [kg] · N_eff — efektywna obsada · 0.153 — wydzielanie CO₂ · 2.6‰ — limit · 1.5 — zapas"),
   ("moist", "2 — Qmin: bilans wilgoci (CIGR 2002, poziom kurnika)", "Para od ptaków i ściółki (oraz nagrzewnic z otwartym płomieniem). Ciepło całkowite z poprawką temperaturową (+2 % na każdy °C poniżej 20 °C), utajone = całkowite − jawne kurnika.",
    "Im wilgotniejsze powietrze zewnętrzne, tym więcej powietrza trzeba — do pułapu trybu; na pułapie wentylacją nie utrzyma się docelowej wilgotności (podgrzanie lub osuszanie)."),
   ("final", "3 — Qmin końcowe", "Powietrze rozcieńczające nagrzewnic dodaje się do gałęzi CO₂, para nagrzewnic — do gałęzi wilgoci.", ""),
   ("qmax", "4 — Qmax: bilans cieplny", "Powietrze odprowadzające ciepło jawne ptaków na poziomie kurnika. UA tylko z wiarygodnej kalibracji tego kurnika (test krzywej stygnięcia ≥ 10 min, U przegród 0.1–8 W/(m²·K)).",
    "Mróz: UA×ΔT > 0 → ściany pomagają chłodzić → Qmax ↓.   Upał: UA×ΔT < 0 → ściany dokładają obciążenia → Qmax ↑."),
   ("duty", "5 — Obciążenie nagrzewnic", "Rozwiązywane razem z powietrzem rozcieńczającym samych nagrzewnic — je też trzeba ogrzać.",
    "Jeśli równanie nie jest spełnione przy d = 100 %, nagrzewnic jest za mało — pojawia się ostrzeżenie."),
   ("flame", "6 — Nagrzewnice z otwartym płomieniem: rozcieńczanie CO₂", "1 m³ gazu → 1000 l CO₂ → ~577 m³ powietrza do rozcieńczenia do 2.6‰ (≈ 40× więcej niż powietrze spalania).",
    "Przy ΔT = 30 K ogrzanie tego powietrza zabiera ≈ 58 % mocy nagrzewnicy."),
   ("tunnel", "7 — Tryb tunelowy", "Tunel włącza się tylko, gdy bilans cieplny wymaga ponad połowy przepływu tunelowego — wentylacja przejściowa przez klapy boczne pokrywa 40–50 % (Ross 2025). Prędkość ograniczona wiekiem (Cobb 2021). Qmin bez zmian.",
    "Narzędzie „Tunel”: komfort oceniany przy wentylatorach, gdzie powietrze jest cieplejsze. Chłodzenie wiatrem: tablica do 29.4 °C, stałe do 35 °C (UGA), przy 37.8 °C zero (temperatura powierzchni ptaka). Wzrost > 2.8 °C między końcami jest oznaczany (Cobb)."),
   ("mort", "8 — Korekta na upadki", "Upadki z cyklu rozłożone równomiernie na dni.", ""),
   ("pad", "9 — Chłodzenie panelowe", "Granicą jest temperatura termometru mokrego powietrza zewnętrznego. Sprawność panelu η i opór — z krzywych producenta (SANHE) dla typu, grubości i rzeczywistej prędkości; to wartości dla nowych paneli, wg UGA w eksploatacji 70–75 %.",
    "T_wb z równania psychrometrycznego ASHRAE (Fundamentals 2017, równ. 33), nie z przybliżenia Stulla, które w suchym upale myliło się do +1 °C. Wystarczalność oceniana przy wentylatorach: schłodzone powietrze ogrzewa się nad ptakami."),
   ("vel", "9.1 — Prędkość powietrza przez panel", "Z wydajnością przy 25 Pa przepływ liczony w punkcie pracy z oporem panelu; bez niej — wg katalogu przy 0 Pa (zawyżony).",
    "Zakres 0.6–2.5 m/s. Wyżej → woda wynoszona do kurnika · niżej → ryzyko pleśni."),
   ("water", "9.2 — Zużycie wody", "Psychrometryczny bilans masy.", "Wentylatory tłoczą już schłodzone, nawilżone powietrze — masę suchego powietrza liczy się na wylocie panelu. Kontrola: wykres zużycia wody UGA, 90 °F / 60 % / 100 000 cfm, panel 15 cm → 1,75 gpm; tutaj 1,76 gpm przy η = 0,75."),
   ("wsup", "9.3 — Temperatura doprowadzanej wody", "Woda zimniejsza od punktu rosy powietrza wlotowego skrapla parę na panelu i obniża nasycenie — jest to oznaczane. Korekta temperatury za panelem nie jest stosowana.", ""),
  ],
  "refs": "Źródła: CIGR (1984, 2002) · Aarnink, CIGR Journal · Ross Broiler Handbook (2025) · Cobb Broiler Management Guide (2021) · UGA Poultry Housing Tips (Czarick) · University of Kentucky AFS rozdz. 9 · ASHRAE Fundamentals (2017) · dane paneli SANHE",
 },
 "de": {
  "h2": "📐 Methodik der Lüftungsberechnung",
  "lead": "Physikalisches Modell: Qmin = max(CO₂, Feuchte) inkl. Heizer · Qmax = Wärmebilanz innerhalb der Lüftungsart. SI-Einheiten.",
  "s": [
   ("co2", "1 — Qmin: CO₂-Bilanz (CIGR 1984)", "Biologisches Minimum aus der Lebendmasse. Mit den Aviagen-2018-Raten auf ~10 % abgeglichen.",
    "W — Lebendmasse [kg] · N_eff — effektiver Bestand · 0.153 — CO₂-Ausbeute · 2.6‰ — Grenze · 1.5 — Sicherheit"),
   ("moist", "2 — Qmin: Feuchtebilanz (CIGR 2002, Stallebene)", "Dampf von Tieren und Einstreu (und Heizern mit offener Flamme). Gesamtwärme temperaturkorrigiert (+2 % je °C unter 20 °C), latent = gesamt − sensibel auf Stallebene.",
    "Je feuchter die Außenluft, desto mehr Luft — bis zur Obergrenze der Lüftungsart; dort ist die Zielfeuchte durch Lüften nicht zu halten (heizen oder entfeuchten)."),
   ("final", "3 — Qmin gesamt", "Verdünnungsluft der Heizer zählt zum CO₂-Zweig, Heizerdampf zum Feuchtezweig.", ""),
   ("qmax", "4 — Qmax: Wärmebilanz", "Luft, die die sensible Wärme der Tiere auf Stallebene abführt. UA nur aus einer plausiblen Kalibrierung dieses Stalls (Abkühlkurventest ≥ 10 min, Hüllen-U 0.1–8 W/(m²·K)).",
    "Kälte: UA×ΔT > 0 → Wände helfen kühlen → Qmax ↓.   Hitze: UA×ΔT < 0 → Wände erhöhen die Last → Qmax ↑."),
   ("duty", "5 — Heizerauslastung", "Gemeinsam mit der eigenen Verdünnungsluft der Heizer gelöst — auch sie muss erwärmt werden.",
    "Ist die Gleichung bei d = 100 % nicht erfüllbar, reichen die Heizer nicht — es erscheint eine Warnung."),
   ("flame", "6 — Heizer mit offener Flamme: CO₂-Verdünnung", "1 m³ Gas → 1000 l CO₂ → ~577 m³ Luft zur Verdünnung auf 2.6‰ (≈ 40× Verbrennungsluft).",
    "Bei ΔT = 30 K kostet die Erwärmung dieser Luft ≈ 58 % der Heizerleistung."),
   ("tunnel", "7 — Tunnelbetrieb", "Tunnel nur, wenn die Wärmebilanz mehr als die Hälfte des Tunnelvolumenstroms verlangt — die Übergangslüftung über Seitenklappen deckt 40–50 % (Ross 2025). Luftgeschwindigkeit nach Alter begrenzt (Cobb 2021). Qmin bleibt.",
    "Werkzeug „Tunnel“: Komfort am Lüfterende, wo die Luft wärmer ist. Windkühlung: Tabelle bis 29.4 °C, konstant bis 35 °C (UGA), bei 37.8 °C null (Oberflächentemperatur der Tiere). Anstieg > 2.8 °C zwischen den Enden wird markiert (Cobb)."),
   ("mort", "8 — Verlustkorrektur", "Zyklusverluste gleichmäßig auf die Tage verteilt.", ""),
   ("pad", "9 — Pad-Kühlung", "Grenze ist die Feuchtkugeltemperatur der Außenluft. Pad-Wirkungsgrad η und Druckverlust aus Herstellerkurven (SANHE) nach Typ, Stärke und tatsächlicher Geschwindigkeit — Werte für neue Pads; UGA-Felddaten: 70–75 %.",
    "T_wb aus der psychrometrischen Gleichung nach ASHRAE (Fundamentals 2017, Gl. 33), nicht aus der Näherung nach Stull, die bei heißer, trockener Luft bis +1 °C abwich. Ausreichend wird am Lüfterende beurteilt: die gekühlte Luft erwärmt sich über den Tieren."),
   ("vel", "9.1 — Luftgeschwindigkeit durch das Pad", "Mit der Leistung bei 25 Pa wird der Volumenstrom im Betriebspunkt inkl. Pad-Widerstand berechnet; sonst nach Datenblatt bei 0 Pa (überschätzt).",
    "Bereich 0.6–2.5 m/s. Höher → Wasser wird in den Stall getragen · niedriger → Schimmelrisiko."),
   ("water", "9.2 — Wasserverbrauch", "Psychrometrische Massenbilanz.", "Die Lüfter fördern bereits gekühlte, befeuchtete Luft — die Trockenluftmasse wird am Pad-Austritt angesetzt. Kontrolle: UGA-Wasserverbrauchsdiagramm, 90 °F / 60 % / 100 000 cfm, Pad 15 cm → 1,75 gpm; hier 1,76 gpm bei η = 0,75."),
   ("wsup", "9.3 — Temperatur des Zulaufwassers", "Wasser kälter als der Taupunkt der Zuluft kondensiert Dampf am Pad und senkt die Sättigung — wird markiert. Eine Korrektur der Temperatur nach dem Pad erfolgt nicht.", ""),
  ],
  "refs": "Quellen: CIGR (1984, 2002) · Aarnink, CIGR Journal · Ross Broiler Handbook (2025) · Cobb Broiler Management Guide (2021) · UGA Poultry Housing Tips (Czarick) · University of Kentucky AFS Kap. 9 · ASHRAE Fundamentals (2017) · SANHE-Paddaten",
 },
 "fr": {
  "h2": "📐 Méthodologie de calcul de la ventilation",
  "lead": "Modèle physique : Qmin = max(CO₂, humidité) avec chauffages · Qmax = bilan thermique dans les limites du mode de ventilation. Unités SI.",
  "s": [
   ("co2", "1 — Qmin : bilan CO₂ (CIGR 1984)", "Minimum biologique selon le poids vif. Vérifié par rapport aux débits Aviagen 2018 à ~10 % près.",
    "W — poids [kg] · N_eff — effectif · 0.153 — production de CO₂ · 2.6‰ — limite · 1.5 — sécurité"),
   ("moist", "2 — Qmin : bilan d’humidité (CIGR 2002, niveau bâtiment)", "Vapeur des oiseaux et de la litière (et des chauffages à flamme nue). Chaleur totale corrigée selon la température (+2 % par °C sous 20 °C), latente = totale − sensible du bâtiment.",
    "Plus l’air extérieur est humide, plus il faut d’air — jusqu’au plafond du mode ; au plafond l’humidité cible ne peut être tenue par la ventilation (chauffer ou déshumidifier)."),
   ("final", "3 — Qmin final", "L’air de dilution des chauffages s’ajoute à la branche CO₂, leur vapeur à la branche humidité.", ""),
   ("qmax", "4 — Qmax : bilan thermique", "Air évacuant la chaleur sensible des oiseaux au niveau du bâtiment. UA seulement d’une calibration plausible de ce bâtiment (test de courbe de refroidissement ≥ 10 min, U de l’enveloppe 0.1–8 W/(m²·K)).",
    "Froid : UA×ΔT > 0 → les murs aident à refroidir → Qmax ↓.   Chaud : UA×ΔT < 0 → les murs ajoutent de la charge → Qmax ↑."),
   ("duty", "5 — Taux de charge des chauffages", "Résolu avec l’air de dilution des chauffages eux-mêmes, qu’il faut aussi chauffer.",
    "Si l’équation n’est pas satisfaite à d = 100 %, les chauffages sont insuffisants — un avertissement s’affiche."),
   ("flame", "6 — Chauffages à flamme nue : dilution du CO₂", "1 m³ de gaz → 1000 L de CO₂ → ~577 m³ d’air pour diluer à 2.6‰ (≈ 40× l’air de combustion).",
    "À ΔT = 30 K, chauffer cet air prend ≈ 58 % de la puissance du chauffage."),
   ("tunnel", "7 — Mode tunnel", "Tunnel seulement quand le bilan thermique demande plus de la moitié du débit tunnel — la ventilation de transition par les entrées latérales couvre 40–50 % (Ross 2025). Vitesse limitée selon l’âge (Cobb 2021). Qmin inchangé.",
    "Outil « Tunnel » : le confort est évalué côté ventilateurs, où l’air est plus chaud. Refroidissement par le vent : tableau jusqu’à 29.4 °C, constant jusqu’à 35 °C (UGA), nul à 37.8 °C (température de surface des oiseaux). Une hausse > 2.8 °C entre les extrémités est signalée (Cobb)."),
   ("mort", "8 — Correction de mortalité", "Mortalité du lot répartie uniformément sur les jours.", ""),
   ("pad", "9 — Refroidissement par panneaux", "La limite est la température humide de l’air extérieur. Rendement η et perte de charge selon les courbes du fabricant (SANHE) par type, épaisseur et vitesse réelle — valeurs pour panneaux neufs ; données terrain UGA : 70–75 %.",
    "T_wb est tirée de l’équation psychrométrique ASHRAE (Fundamentals 2017, éq. 33), et non de l’approximation de Stull, qui s’écartait jusqu’à +1 °C par temps chaud et sec. La suffisance est évaluée côté ventilateurs : l’air refroidi se réchauffe au-dessus des oiseaux."),
   ("vel", "9.1 — Vitesse de l’air à travers le panneau", "Avec le débit à 25 Pa, le débit est pris au point de fonctionnement avec la résistance du panneau ; sinon le débit catalogue à 0 Pa (surestimé).",
    "Plage 0.6–2.5 m/s. Plus haut → eau entraînée dans le bâtiment · plus bas → risque de moisissure."),
   ("water", "9.2 — Consommation d’eau", "Bilan massique psychrométrique.", "Les ventilateurs déplacent l’air déjà refroidi et humidifié — la masse d’air sec est prise en sortie de panneau. Contrôle : abaque UGA de consommation d’eau, 90 °F / 60 % / 100 000 cfm, panneau 15 cm → 1,75 gpm ; ici 1,76 gpm à η = 0,75."),
   ("wsup", "9.3 — Température de l’eau d’alimentation", "Une eau plus froide que le point de rosée de l’air entrant condense la vapeur sur le panneau et réduit la saturation — c’est signalé. Aucune correction de la température après panneau n’est appliquée.", ""),
  ],
  "refs": "Sources : CIGR (1984, 2002) · Aarnink, CIGR Journal · Ross Broiler Handbook (2025) · Cobb Broiler Management Guide (2021) · UGA Poultry Housing Tips (Czarick) · University of Kentucky AFS ch. 9 · ASHRAE Fundamentals (2017) · données panneaux SANHE",
 },
}


def esc(x: str) -> str:
    return x.replace("&", "&amp;").replace("&amp;nbsp;", "&nbsp;").replace("<", "&lt;").replace(">", "&gt;")


def render(lang: str) -> str:
    d = T[lang]
    out = [f'<h2 class="mt-0">{d["h2"]}</h2><p class="muted">{esc(d["lead"])}</p>']
    for key, title, para, note in d["s"]:
        lines = "<br>".join(esc(l) for l in F[key])
        note_html = f'<br><span class="muted">{esc(note)}</span>' if note else ""
        out.append(f'<h3>{esc(title)}</h3><p>{esc(para)}</p><div class="info-block formula">{lines}{note_html}</div>')
    out.append(f'<hr class="section-divider"><p class="muted fs-12">{esc(d["refs"])}</p>')
    html = "".join(out)
    assert "'" not in html, f"{lang}: апостроф сломает строку JS"
    return html


for lang in T:
    assert [k for k, *_ in T[lang]["s"]] == list(F), lang
    p = I18N / f"{lang}.js"
    src = p.read_text(encoding="utf-8")
    pat = re.compile(r"^(\s*help_body_html:\s*)'.*?',\s*$", re.M)
    assert len(pat.findall(src)) == 1, lang
    src = pat.sub(lambda m: m.group(1) + "'" + render(lang) + "',", src)
    p.write_text(src, encoding="utf-8")
    print("ok", lang, len(render(lang)))
