// calculators.js — вкладки инструментов, профиль вентиляции, герметичность,
// испарительное и туннельное охлаждение (вынесено из calculators.html).
// Классический скрипт без defer: выполняется в том же месте разметки, что и
// прежний встроенный блок, — панели ниже него в этот момент ещё не разобраны.

// ─────── Общие помощники страницы ───────

// Класс бейджа по уровню статуса с сервера (ok | warn | danger).
// Раньше цвет угадывался по эмодзи внутри русской строки.
function badgeClass(level) {
  const cls = { ok: 'badge-tight', warn: 'badge-moderate', danger: 'badge-very_leaky' }[level] || 'badge-very_leaky';
  return 'result-badge ' + cls;
}

// Результаты инструментов собираются в JS из словаря текущего языка. Каждый
// инструмент после успешного расчёта кладёт сюда замыкание «перерисовать
// последний результат», а смена языка вызывает их все.
const rerenderOnLang = {};

// Ошибка калькулятора — над его результатом, а не alert(): alert блокировал
// страницу, а прежний результат оставался на экране рядом с ошибкой, будто он
// относится к новому вводу (аудит 2026-10-18). textFn вызывается заново при
// смене языка — текст собирается из словаря, а не хранится готовой строкой.
function showToolError(tool, resultsId, textFn) {
  const results = document.getElementById(resultsId);
  if (results) results.hidden = true;
  let box = document.getElementById(tool + '-error');
  if (!box && results) {
    box = document.createElement('p');
    box.id = tool + '-error';
    box.className = 'danger fs-12 mt-8';
    box.setAttribute('role', 'alert');
    results.parentNode.insertBefore(box, results);
  }
  const render = () => { if (box) { box.textContent = textFn(); box.hidden = false; } };
  render();
  rerenderOnLang[tool] = render;
}

function clearToolError(tool) {
  const box = document.getElementById(tool + '-error');
  if (box) box.hidden = true;
}

// Ответ сервера с ошибкой → функция текста (для showToolError); sent — тело
// запроса: по нему номер точки в ошибке превращается в день
async function apiErrorTextFn(resp, sent) {
  const err = await apiError(resp, sent);
  return () => t('err_prefix') + apiErrorText(err.body, err.status, sent);
}
document.addEventListener('i18n:change', () => {
  Object.values(rerenderOnLang).forEach(fn => { try { fn(); } catch (e) { console.warn('rerender:', e); } });
});

// ─────── Shared house selector utility ───────
// Заполняет <select> птичниками из localStorage главной страницы.
// При смене выбора вызывает onSelect(tab) — tab-объект с полями профиля.
function initHouseSelector(selId, onSelect) {
  const sel = document.getElementById(selId);
  if (!sel) return;
  let tabs = [];
  try { tabs = JSON.parse(localStorage.getItem('vent_mvp_tabs_v1') || '[]'); }
  catch(e) { console.warn('house selector:', e); }

  // Подписи опций — из словаря, поэтому при смене языка список собирается
  // заново, а текущий выбор сохраняется
  function fillOptions() {
    const chosen = sel.value;
    sel.innerHTML = `<option value="">— ${t('dims_no_houses')} —</option>`;
    tabs.forEach((tab, i) => {
      const opt = document.createElement('option');
      opt.value = i;
      const name = tab.id ? houseLabel(tab.id) : `#${i + 1}`;
      opt.textContent = name + (tab.birds ? ` — ${fmtNum(tab.birds)}` : '');
      sel.appendChild(opt);
    });
    sel.value = chosen;
  }
  fillOptions();
  sel.addEventListener('change', () => {
    const i = parseInt(sel.value, 10);
    if (!isNaN(i) && tabs[i]) onSelect(tabs[i]);
  });
  document.addEventListener('i18n:change', fillOptions);
}

function _setVal(id, v) { if (v != null && v !== '') { const el = document.getElementById(id); if (el) el.value = v; } }

// Средняя высота сечения корпуса, м — ОДНО правило для расчёта профиля и вкладки
// туннеля: стена, а при двускатной крыше (конёк выше стены) — (стена + конёк) / 2.
// Раньше туннель умножал её ещё на 0.80 «на оборудование», а профиль — нет: один
// корпус получал на соседних вкладках 1.96 и 2.47 м/с (аудит 2026-10-18). Скорость
// туннеля считают по полному сечению; поправка завышала её на 25 % при той же
// мощности — ошибка в опасную сторону. Подвесной потолок пользователь вводит сам.
function houseSectionHeight(tab) {
  const wall  = Number(tab.height_wall_m)  || null;
  const ridge = Number(tab.height_ridge_m) || null;
  if (wall && ridge && ridge > wall) return (wall + ridge) / 2;
  return wall || ridge;
}

// ─────── Tab switching ───────
const toolTabs = document.querySelector('.tool-tabs');
document.querySelectorAll('.tool-tab:not([disabled])').forEach(btn => {
  // Связка вкладка ↔ панель для экранного диктора: «вкладка, выбрана, 2 из 6»
  btn.id = 'tab-' + btn.dataset.tool;
  btn.setAttribute('aria-controls', 'panel-' + btn.dataset.tool);
  btn.addEventListener('click', () => {
    // Панель ищется в момент клика: «Теплопотери» и «Методика» стоят в разметке
    // НИЖЕ этого скрипта — найденная при загрузке, она была бы null, и вкладка
    // переключалась без панели (так и случилось в 22bec38, поймал smoke-тест)
    const panel = document.getElementById('panel-' + btn.dataset.tool);
    document.querySelectorAll('.tool-tab').forEach(tb => tb.classList.remove('active'));
    document.querySelectorAll('.tool-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    if (panel) panel.classList.add('active');
    Tabs.sync(toolTabs);
  });
});
Tabs.init(toolTabs);
// Роли панелей — когда разметка разобрана целиком (по той же причине)
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tool-panel').forEach(p => {
    p.setAttribute('role', 'tabpanel');
    p.setAttribute('aria-labelledby', 'tab-' + p.id.replace(/^panel-/, ''));
  });
});

// ─────── Ventilation Profile ───────
(function() {
  const STORE_KEY = 'vent_mvp_tabs_v1';
  const selEl     = document.getElementById('prof-house-select');
  const profBtn   = document.getElementById('prof-calc-btn');
  const profSummary = document.getElementById('prof-summary');

  let profileTabs = [];
  let selIdx = 0;

  // Подписи корпусов — из словаря: при смене языка список собирается заново, выбор сохраняется
  function fillHouseOptions() {
    selEl.innerHTML = '';
    profBtn.disabled = !profileTabs.length;
    document.getElementById('prof-no-house').hidden = profileTabs.length > 0;
    if (!profileTabs.length) {
      const opt = document.createElement('option');
      opt.textContent = t('dims_no_houses');
      opt.value = '';
      selEl.appendChild(opt);
      return;
    }
    profileTabs.forEach((tab, idx) => {
      const opt = document.createElement('option');
      opt.value = idx;
      const name = tab.id ? houseLabel(tab.id) : `#${idx + 1}`;
      const extra = tab.birds ? ` — ${fmtNum(tab.birds)}` : '';
      opt.textContent = name + extra;
      selEl.appendChild(opt);
    });
    selEl.value = String(selIdx);
  }

  function buildSelector() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) profileTabs = JSON.parse(raw) || [];
    } catch {}

    fillHouseOptions();
    document.addEventListener('i18n:change', fillHouseOptions);
    if (!profileTabs.length) return;

    // Целевая RH — своя у каждого корпуса
    const rhEl = document.getElementById('prof-target-rh');
    const showRH = () => { const tb = profileTabs[selIdx]; rhEl.value = (tb && tb.target_rh != null) ? tb.target_rh : 60; };
    selEl.addEventListener('change', () => { selIdx = parseInt(selEl.value, 10) || 0; showRH(); });
    showRH();
  }

  async function calcProfile() {
    const tab = profileTabs[selIdx];
    if (!tab) return;

    // Неразобранный ввод — ошибка у поля, а не молчаливые 15 °C (раньше «2,5»
    // или опечатка превращались в значение по умолчанию). Пустое поле — по умолчанию,
    // 0 остаётся нулём. Целевая RH вне 40–70 % тоже ошибка: таблица ощущаемой
    // температуры там не определена; пустая — сервер возьмёт RH профиля.
    if (!NumField.validate(['prof-outside-t', 'prof-outside-rh', 'prof-target-rh'])) return;
    const outsideT  = NumField.value('prof-outside-t')  ?? 15;
    const outsideRH = NumField.value('prof-outside-rh') ?? 60;
    const targetRH  = NumField.value('prof-target-rh');
    tab.target_rh  = targetRH;
    try {
      const tabs = JSON.parse(localStorage.getItem(STORE_KEY) || '[]');
      if (tabs[selIdx]) { tabs[selIdx].target_rh = targetRH; localStorage.setItem(STORE_KEY, JSON.stringify(tabs)); }
    } catch (e) { /* не запомнится — не критично */ }
    const mode      = document.getElementById('prof-view-mode').value;

    // Сечение корпуса для туннельного расхода: ширина × средняя высота
    const hAvg = houseSectionHeight(tab);

    const payload = {
      house:        tab.id,
      birds:        tab.birds,
      house_width_m:  Number(tab.width_m) || null,
      house_height_m: hAvg || null,
      growth_profile_id: document.getElementById('prof-growth-select').value || null,
      target_rh:    targetRH,
      user_max_m3h: (tab.cap == null || tab.cap === '') ? null : Number(tab.cap),
      heater_on:    !!tab.heater_on,
      outside_t:    outsideT,
      outside_rh:   outsideRH,
    };

    profBtn.disabled = true; profBtn.textContent = t('btn_calculating');
    try {
      const r = await fetch('./calc/summary7', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw await apiError(r);
      const profData = await r.json();
      renderProfileHtml(profData, tab, mode, outsideT, outsideRH);
      rerenderOnLang.profile = () => renderProfileHtml(profData, tab, mode, outsideT, outsideRH);
    } catch (e) {
      profSummary.innerHTML = `<div class="card"><div class="danger">${escapeHtml(t('err_prefix') + (e.message || e))}</div></div>`;
      profSummary.hidden = false;
    } finally {
      profBtn.disabled = false; profBtn.textContent = t('btn_calc_profile');
    }
  }

  function renderProfileHtml(d, tab, mode, outsideT, outsideRH) {
    // Геометрия птичника
    const L = tab.length_m, W = tab.width_m;
    const S_floor = (L && W) ? L * W : null;
    const H_eff   = houseSectionHeight(tab);
    const V_house = (S_floor && H_eff) ? S_floor * H_eff : null;
    const S_cross = (W && H_eff) ? W * H_eff : null;

    const head = `
      <div class="kv"><span>${t('sum_outdoor')}</span><span>${fmtNum(outsideT, 1)} °C / ${fmtNum(outsideRH ?? 60, 0)} %</span></div>
      <div class="kv"><span>${t('sum_house_birds')}</span><span>${d.house} / ${fmtNum(d.birds)}</span></div>
      <div class="kv"><span>${t('sum_sys_max')}</span><span>${d.user_max_m3h ?? '—'} ${t('unit_m3h_plain')}</span></div>`;

    const headerByMode = {
      total:    [t('hdr_qmin_m3h'), t('hdr_qmax_m3h')],
      percent:  [t('hdr_qmin_pct'), t('hdr_qmax_pct')],
      per_bird: [t('hdr_qmin_bird'), t('hdr_qmax_bird')],
      per_kg:   [t('hdr_qmin_kg'),  t('hdr_qmax_kg')],
      per_m2:   [t('hdr_qmin_m2'),  t('hdr_qmax_m2')]
    };
    const headCols = headerByMode[mode] || headerByMode.total;

    const rows = d.rows.map(r => {
      let c1 = '—', c2 = '—';
      if (mode === 'total') {
        c1 = fmtNum(r.q_min_m3h, 0);
        c2 = fmtNum(r.q_max_m3h, 0);
      } else if (mode === 'percent') {
        c1 = r.q_min_pct != null ? (fmtNum(r.q_min_pct, 1) + '%') : '—';
        c2 = r.q_max_pct != null ? (fmtNum(r.q_max_pct, 1) + '%') : '—';
      } else if (mode === 'per_bird') {
        const be = r.birds_eff || d.birds;
        if (be > 0) { c1 = fmtNum((r.q_min_m3h / be), 4); c2 = fmtNum((r.q_max_m3h / be), 4); }
      } else if (mode === 'per_kg') {
        const be = r.birds_eff || d.birds;
        const wkg = (r.weight_g || 0) / 1000.0;
        const totalKg = be * wkg;
        if (totalKg > 0) { c1 = fmtNum((r.q_min_m3h / totalKg), 4); c2 = fmtNum((r.q_max_m3h / totalKg), 4); }
      } else if (mode === 'per_m2' && S_floor) {
        c1 = fmtNum((r.q_min_m3h / S_floor), 1);
        c2 = fmtNum((r.q_max_m3h / S_floor), 1);
      }
      // Qmin больше мощности установки — подсветить: минимум сервер не обрезает
      const c1Cell = r.capacity_insufficient ? `<span class="danger">${c1} ⚠</span>` : c1;
      return `<tr>
        <td>${r.day}</td><td>${r.min_temp_c != null ? fmtNum(Number(r.min_temp_c), 1) : '—'}</td>
        <td>${r.weight_g != null ? Math.round(r.weight_g) : '—'}</td>
        <td>${c1Cell}</td><td>${c2}</td>
      </tr>`;
    }).join('');

    const capWarn = d.rows.some(r => r.capacity_insufficient)
      ? `<p class="danger fs-12 mt-8 mb-0">⚠ ${t('cap_insufficient_note')}</p>`
      : '';
    // Влажный наружный воздух: вентиляцией RH не удержать — Qmin в таких строках равен потолку режима
    const humWarn = d.rows.some(r => r.humidity_uncontrollable)
      ? `<p class="warn fs-12 mt-8 mb-0">⚠ ${t('humidity_uncontrollable_note')}</p>`
      : '';
    // Калибровка UA не применена (чужой корпус, короткий тест, неправдоподобный U)
    const calIgnored = (d.rows.find(r => r.calibration_ignored) || {}).calibration_ignored;
    const calWarn = calIgnored && calIgnored.code !== 'calibration_other_house'
      ? `<p class="warn fs-12 mt-8 mb-0">⚠ ${t('cal_ignored_note', { reason: apiErrorText({ detail: calIgnored }, 400) })}</p>`
      : '';
    // Горелок не хватает даже на 100 % (с подогревом их же воздуха разбавления CO₂)
    const heatWarn = d.rows.some(r => r.heater_insufficient)
      ? `<p class="danger fs-12 mt-8 mb-0">⚠ ${t('heater_insufficient_note')}</p>`
      : '';
    // Горелки включены, но загрузку не найти: либо данных о горелке нет совсем (ничего
    // не добавлено), либо UA не откалиброван (разбавление CO₂ — оценка сверху при 100 %)
    const heaterNote = ['heater_data_missing', 'heater_full_duty_estimate']
      .find(code => d.rows.some(r => r.heater_note === code));
    const heaterNoteHtml = heaterNote
      ? `<p class="warn fs-12 mt-8 mb-0">⚠ ${t(heaterNote + '_note')}</p>`
      : '';
    // Туннельный Qmax считается из сечения корпуса — без размеров он равен Qmin
    const geomWarn = d.rows.some(r => r.house_geometry_missing)
      ? `<p class="warn fs-12 mt-8 mb-0">⚠ ${t('geometry_missing_note')}</p>`
      : '';

    // Физическая проверка (Cobb 2021 §9)
    let physBlock = '';
    if (S_floor) {
      const r0  = d.rows[0];
      const r42 = d.rows[d.rows.length - 1];
      const qMinM2 = r0 ? r0.q_min_m3h / S_floor : null;
      const q_sys  = d.user_max_m3h ?? (r42 ? r42.q_max_nominal_m3h : null);
      const qMaxM2 = q_sys && S_floor ? q_sys / S_floor : null;
      const T_exch = (V_house && q_sys && q_sys > 0) ? Math.round(V_house / q_sys * 3600) : null;
      const v_tun  = (S_cross && q_sys && q_sys > 0) ? q_sys / 3600 / S_cross : null;

      const hasSysCap = !!d.user_max_m3h;
      const cls_qmin  = '';
      // Цель скорости — с сервера, из той же таблицы по возрасту, что у вкладки
      // туннеля (на последний день цикла). Раньше здесь были зашиты «≥3.0 м/с»,
      // а туннель для того же корпуса и дня судил по 2.5–3.0.
      const vMin = d.tunnel_target_v_min_ms, vMax = d.tunnel_target_v_max_ms;
      const cls_qmax  = hasSysCap && qMaxM2 != null ? (qMaxM2 >= 150 ? 'ok' : qMaxM2 >= 100 ? '' : 'warn') : '';
      const cls_texch = hasSysCap && T_exch != null ? (T_exch <= 60 ? 'ok' : T_exch <= 90 ? '' : 'warn') : '';
      // Пороги — как у вердикта вкладки туннеля: ≥ v_min — норма, ≥ 0.8·v_min — мало, ниже — плохо
      const cls_vtun  = hasSysCap && v_tun != null && vMin
        ? (v_tun >= vMin ? 'ok' : v_tun >= 0.8 * vMin ? '' : 'warn') : '';
      const vTarget   = vMin ? t('phys_airspeed_target', { min: vMin, max: vMax, day: d.tunnel_target_day }) : '';

      physBlock = `
        <div class="mt-14 pt-12 bt-1">
          <div class="muted fs-12 mb-6 fw-500">${t('phys_title')}</div>
          <div class="kv"><span>${t('phys_floor_area')}</span><span>${fmtNum(S_floor, 0)} ${t('unit_m2')}</span></div>
          ${V_house ? `<div class="kv"><span>${t('phys_volume')}</span><span>${fmtNum(V_house, 0)} ${t('unit_m3')}</span></div>` : ''}
          ${S_cross  ? `<div class="kv"><span>${t('phys_cross_section')}</span><span>${fmtNum(S_cross, 1)} ${t('unit_m2')}</span></div>` : ''}
          <div class="mt-6">
            ${qMinM2 != null ? `<div class="kv"><span>${t('phys_min_vent_check')}</span><span class="${cls_qmin}">${fmtNum(qMinM2, 1)} ${t('unit_m3h_m2')} <span class="muted">[≥18]</span></span></div>` : ''}
            ${qMaxM2 != null ? `<div class="kv"><span>${t('phys_max_vent_check')}</span><span class="${cls_qmax}">${fmtNum(qMaxM2, 1)} ${t('unit_m3h_m2')} <span class="muted">[165–200]</span></span></div>` : ''}
            ${T_exch  != null ? `<div class="kv"><span>${t('phys_exchange_time')}</span><span class="${cls_texch}">${T_exch} ${t('unit_sec')} <span class="muted">[40–60]</span></span></div>` : ''}
            ${v_tun   != null ? `<div class="kv"><span>${t('phys_airspeed_tunnel')}</span><span class="${cls_vtun}">${fmtNum(v_tun, 2)} ${t('unit_ms')} ${vTarget ? `<span class="muted">[${vTarget}]</span>` : ''}</span></div>` : ''}
          </div>
          <p class="muted fs-10 mt-8 mb-0">${t('phys_cobb_source')}${hasSysCap ? '' : ' · ' + t('phys_needs_sys_cap')}</p>
        </div>`;
    } else {
      physBlock = `<p class="muted fs-11 mt-10">${t('phys_dims_needed')}</p>`;
    }

    profSummary.innerHTML = `<div class="card">${head}
      <table>
        <thead><tr>
          <th>${t('col_day')}</th><th>${t('col_min_temp')}</th><th>${t('col_weight')}</th>
          <th>${headCols[0]}</th><th>${headCols[1]}</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
      ${capWarn}
      ${humWarn}
      ${heatWarn}
      ${heaterNoteHtml}
      ${calWarn}
      ${geomWarn}
      ${physBlock}
    </div>`;
    profSummary.hidden = false;
  }

  profBtn.addEventListener('click', calcProfile);
  buildSelector();
})();

// ─────── House selectors for tool panels ───────
// Каждый инструмент подтягивает из профиля то что хранится:
// leakage ← length, width, fan_cap_m3h (один вентилятор для теста)
// evap    ← length, width, cap (полная мощность системы)
// tunnel  ← width, height, num_fans, fan_cap_m3h, birds (наружные T и RH — только вручную)
initHouseSelector('l-house-sel', tab => {
  _setVal('l-length',  tab.length_m);
  _setVal('l-width',   tab.width_m);
  _setVal('l-fan-cap', tab.fan_cap_m3h);   // один вентилятор = типичный объём теста
});

initHouseSelector('ev-house-sel', tab => {
  _setVal('ev-length',     tab.length_m);
  _setVal('ev-width',      tab.width_m);
  // Панели занимают всю ширину торца птичника по умолчанию
  _setVal('ev-pad-length', tab.width_m);
  // Общая мощность системы = num_fans × fan_cap, или используем cap напрямую
  const totalCap = (tab.num_fans && tab.fan_cap_m3h)
    ? tab.num_fans * tab.fan_cap_m3h
    : tab.cap;
  _setVal('ev-fans', totalCap);
  _setVal('ev-birds', tab.birds);
});

// Глобальный объект конфига — обновляется IIFE профиля при загрузке настроек
var profileCfg = { cycle_days: 42 };

initHouseSelector('tn-house-sel', tab => {
  _setVal('tn-width',  tab.width_m);
  // Для оценки готовности птичника всегда используем последний день цикла
  _setVal('tn-age',    profileCfg.cycle_days ?? 42);
  // Наружную температуру НЕ подставляем: у вкладки корпуса такого поля в
  // интерфейсе нет, а старые вкладки хранят скрытое outside_t = 10 °C — для
  // летней проверки туннеля это ложная расчётная точка (аудит 2026-10-18)
  _setVal('tn-birds',  tab.birds);

  // Высота сечения — то же правило, что в расчёте профиля (houseSectionHeight)
  const hintHeight = document.getElementById('tn-height-hint');
  if (tab.height_wall_m) {
    const hasRidge = tab.height_ridge_m && tab.height_ridge_m > tab.height_wall_m;
    const freeH = Math.round(houseSectionHeight(tab) * 100) / 100;
    _setVal('tn-height', freeH);
    if (hintHeight) {
      hintHeight.textContent = hasRidge
        ? t('hint_tn_height_gable', { wall: tab.height_wall_m, ridge: tab.height_ridge_m, result: freeH })
        : t('hint_tn_height_auto');
      setTone(hintHeight, null);
      hintHeight.hidden = false;
    }
  } else {
    if (hintHeight) {
      hintHeight.textContent = t('hint_tn_height_missing');
      setTone(hintHeight, 'warn');
      hintHeight.hidden = false;
    }
  }

  // Вентиляторы: подтягиваем из профиля если заполнены
  const fansMissing = document.getElementById('tn-fans-missing');
  const hasFans = tab.num_fans && tab.fan_cap_m3h;
  if (hasFans) {
    _setVal('tn-fans',    tab.num_fans);
    _setVal('tn-fan-cap', tab.fan_cap_m3h);
    if (fansMissing) fansMissing.hidden = true;
  } else {
    // Данных нет — показываем подсказку
    if (fansMissing) fansMissing.hidden = false;
  }
});

// ─────── Tightness class config (tips via i18n) ───────
const TIGHTNESS = {
  tight:      { css: 'badge-tight',      tipKey: 'tip_tight' },
  moderate:   { css: 'badge-moderate',   tipKey: 'tip_moderate' },
  leaky:      { css: 'badge-leaky',      tipKey: 'tip_leaky' },
  very_leaky: { css: 'badge-very_leaky', tipKey: 'tip_very_leaky' },
};

// ─────── Leakage calculation ───────
document.getElementById('l-calc-btn').addEventListener('click', async () => {
  if (!NumField.validate(document.getElementById('panel-leakage'))) return;
  const body = {
    house_length_m:       NumField.value('l-length'),
    house_width_m:        NumField.value('l-width'),
    fan_capacity_m3h:     NumField.value('l-fan-cap'),
    measured_pressure_pa: NumField.value('l-pressure'),
  };

  const btn = document.getElementById('l-calc-btn');
  btn.textContent = t('btn_leakage_busy'); btn.disabled = true;

  try {
    const resp = await fetch('./calc/tools/leakage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      showToolError('leakage', 'l-results', await apiErrorTextFn(resp, body));
      return;
    }

    const leakData = await resp.json();
    clearToolError('leakage');
    renderLeakage(leakData);
    rerenderOnLang.leakage = () => renderLeakage(leakData);

  } catch(e) {
    showToolError('leakage', 'l-results', () => t('err_conn') + e.message);
  } finally {
    btn.textContent = t('btn_leakage_active'); btn.disabled = false;
  }
});

function renderLeakage(d) {
  const tc  = TIGHTNESS[d.tightness_class] || TIGHTNESS.very_leaky;
  // Цвет — по классу с сервера: своя копия порогов здесь (0.25/0.50) разошлась
  // бы с сервером при первой же правке шкалы
  const relClass = { tight: 'ok', moderate: 'warn' }[d.tightness_class] || 'danger';
  const u = t('unit_m2');

  const badge = document.getElementById('l-badge');
  badge.textContent = t('tightness_' + d.tightness_class);
  badge.className   = 'result-badge ' + tc.css;

  document.getElementById('l-ela').innerHTML =
    `<span class="${relClass}">${fmtNum(d.ela_m2, 3)} ${u}</span>`;
  document.getElementById('l-rel').innerHTML =
    `<span class="${relClass}">${fmtNum(d.relative_leakage, 3)} ${u}/1000${u}</span>`;
  document.getElementById('l-area').textContent     = `${fmtNum(d.house_area_m2, 0)} ${u}`;
  document.getElementById('l-fan-corr').textContent = `${fmtNum(d.fan_corrected_m3h, 0)} ${t('unit_m3h')}`;
  document.getElementById('l-class-tip').textContent = t(tc.tipKey);

  document.getElementById('l-results').hidden = false;
}

// ═══════════════════════════════════════════════════
// TUNNEL SPEED
// ═══════════════════════════════════════════════════

document.getElementById('tunnel-form').addEventListener('submit', async e => {
  e.preventDefault();
  // Свой разбор числа вместо браузерного: запятая и шаг поля больше не мешают
  if (!NumField.validate(e.target)) return;
  const btn = document.getElementById('tunnel-btn');
  btn.disabled = true; btn.textContent = t('btn_tunnel_busy');

  try {
    const payload = {
      house_width_m:    NumField.value('tn-width'),
      tunnel_height_m:  NumField.value('tn-height'),
      num_fans:         NumField.value('tn-fans'),
      fan_capacity_m3h: NumField.value('tn-fan-cap'),
      t_outdoor_db_c:   NumField.value('tn-tdb'),
      rh_outdoor_pct:   NumField.value('tn-rh'),
      bird_age_days:    NumField.value('tn-age'),
      num_inlets:       NumField.value('tn-num-inlets') ?? 1,
      inlet_width_m:    NumField.value('tn-inlet-w')  ?? 0,
      inlet_height_m:   NumField.value('tn-inlet-h')  ?? 0,
      fan_capacity_25pa_m3h: NumField.value('tn-fan-cap25') ?? 0,
      // Поголовье — для нагрева воздуха вдоль корпуса (оценка у вентиляторов)
      num_birds:        NumField.value('tn-birds') ?? 0,
    };

    const resp = await fetch('./calc/tools/tunnel_speed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      showToolError('tunnel', 'tn-results', await apiErrorTextFn(resp, payload));
      return;
    }

    const tunnelData = await resp.json();
    clearToolError('tunnel');
    renderTunnel(tunnelData, payload.t_outdoor_db_c);
    rerenderOnLang.tunnel = () => renderTunnel(tunnelData, payload.t_outdoor_db_c);
  } catch (err) {
    // Сеть недоступна или ошибка отрисовки — без catch пользователь не видел ничего
    showToolError('tunnel', 'tn-results', () => t('err_prefix') + String(err));
  } finally {
    btn.disabled = false; btn.textContent = t('btn_tunnel_active');
  }
});

function renderTunnel(d, t_real) {
  const uMs = t('unit_ms');
  const uM2 = t('unit_m2');
  const uM3h = t('unit_m3h');
  const uPa  = t('unit_pa');

  // Бейдж: сервер отдаёт код и уровень, текст — из словаря текущего языка
  const statusEl = document.getElementById('tn-status');
  statusEl.textContent = t('tn_status_' + d.status_code);
  statusEl.className = badgeClass(d.status_level);

  // Air flow
  document.getElementById('tn-r-section').textContent = fmtNum(d.cross_section_m2, 2) + ' ' + uM2;
  document.getElementById('tn-r-total').textContent   =
    fmtNum(d.total_airflow_m3h, 0) + ' ' + uM3h;

  const vOk   = d.air_velocity_ms >= d.target_v_min_ms && d.air_velocity_ms <= d.target_v_max_ms;
  const vHigh = d.air_velocity_ms > d.target_v_max_ms;
  document.getElementById('tn-r-vel').innerHTML =
    `<span class="${vOk ? 'ok' : vHigh ? 'warn' : 'danger'}">${fmtNum(d.air_velocity_ms, 2)} ${uMs}</span>`;
  // Расход по паспорту «0 Па» завышен — сказать об этом рядом со скоростью
  const velText = t('tn_vel_' + d.velocity_status, {
    v: fmtNum(d.air_velocity_ms, 1), v_min: fmtNum(d.target_v_min_ms, 1), v_max: fmtNum(d.target_v_max_ms, 1),
  });
  document.getElementById('tn-r-vel-status').textContent = velText +
    (d.velocity_basis === 'rated_0pa' ? ' · ' + t('tn_basis_rated_note') : '');

  // Wind cooling
  document.getElementById('tn-r-treal').textContent     = fmtNum(t_real, 1) + ' °C';
  // Воздух у вентиляторов теплее входного на тепло птицы — по нему ощущаемая T и THVI
  const riseRow = document.getElementById('tn-row-rise');
  riseRow.hidden = !(d.air_temp_rise_c > 0);
  if (!riseRow.hidden) {
    const riseEl = document.getElementById('tn-r-rise');
    riseEl.textContent = t('tn_rise_val', { t: fmtNum(d.t_fan_end_c, 1), rise: fmtNum(d.air_temp_rise_c, 1) });
    setTone(riseEl, d.end_to_end_rise_excessive ? 'danger' : null);
    riseEl.title = d.end_to_end_rise_excessive ? t('tn_rise_excessive') : '';
  }
  // Знак явный: при влажном воздухе и слабом потоке «охлаждение» отрицательное (ощущается жарче)
  const wc = d.wind_chill_c;
  document.getElementById('tn-r-windchill').textContent = (wc >= 0 ? '−' : '+') + fmtNum(Math.abs(wc), 1) + ' °C';
  document.getElementById('tn-r-efftemp').textContent   = fmtNum(d.effective_temp_c, 1) + ' °C';

  // THVI
  const thiEl = document.getElementById('tn-r-thi');
  thiEl.textContent = fmtNum(d.thi_value, 1);
  // Пороги THVI (Tao & Xin 2003): 35 / 38 / 40 °C → ступень шкалы 1…4
  setTone(thiEl, 'grade-' + (d.thi_value < 35 ? 1 : d.thi_value < 38 ? 2 : d.thi_value < 40 ? 3 : 4));
  document.getElementById('tn-r-thi-status').textContent = t('thvi_' + d.thi_status);

  // Inlet system
  document.getElementById('tn-r-inlet-area').textContent =
    fmtNum(d.inlet_area_m2, 1) + ' ' + uM2;
  // Скорость в приточных: 2 / 3 / 4 м/с → ступень шкалы 1…4
  const inletVelGrade = d.inlet_velocity_ms < 2.0 ? 1
                      : d.inlet_velocity_ms < 3.0 ? 2
                      : d.inlet_velocity_ms < 4.0 ? 3
                      : 4;
  document.getElementById('tn-r-inlet-vel').innerHTML =
    `<span class="c-grade-${inletVelGrade}">${fmtNum(d.inlet_velocity_ms, 2)} ${uMs}</span>`;
  document.getElementById('tn-r-inlet-sp').textContent =
    fmtNum(d.inlet_sp_pa, 1) + ' ' + uPa;
  document.getElementById('tn-r-inlet-status').textContent =
    t('tn_inlet_' + d.inlet_status, { v: fmtNum(d.inlet_velocity_ms, 2) });

  // Pressure & recommendations
  document.getElementById('tn-r-dyn-pa').textContent  = fmtNum(d.dynamic_pressure_pa, 1) + ' ' + uPa;
  document.getElementById('tn-r-tot-pa').textContent  = fmtNum(d.total_pressure_pa, 1)   + ' ' + uPa;
  document.getElementById('tn-r-target').textContent  =
    `${fmtNum(d.target_v_min_ms)}–${fmtNum(d.target_v_max_ms)} ${uMs}`;
  document.getElementById('tn-r-fans-need').textContent =
    t('fans_needed_fmt', { n: d.fans_needed_for_target, v_min: d.target_v_min_ms });

  // Decision card: tunnel vs evaporative cooling
  const decCard  = document.getElementById('tn-decision-card');
  const noteEl   = document.getElementById('tn-decision-note');
  const evapBtn  = document.getElementById('tn-to-evap-btn');
  const limitOk  = d.tunnel_sufficient;
  // Отклонение ощущаемой — тоном ТЕПЛОВОЙ проверки: при нехватке одной скорости
  // птице может быть не жарко, и красный «−2 °C» читался бы как перегрев
  const heatTone  = d.heat_sufficient ? 'ok' : 'danger';

  // Птице не жарко, не хватает только скорости — предупреждение, а не авария
  setEdge(decCard, limitOk ? 'ok' : d.tunnel_action === 'add_fans' ? 'warn' : 'danger');
  decCard.hidden = false;

  document.getElementById('tn-r-comfort-target').textContent =
    fmtNum(d.bird_comfort_target_c, 1) + ' °C';

  const marginAbs  = fmtNum(Math.abs(d.temp_margin_c), 1);
  const marginSign = d.temp_margin_c >= 0 ? '−' : '+';
  document.getElementById('tn-r-margin').innerHTML =
    `${fmtNum(d.effective_temp_c, 1)} °C &nbsp;` +
    `<span class="c-${heatTone}">(${marginSign}${marginAbs} °C)</span>`;

  const atCap = d.t_outdoor_tunnel_limit_c >= 42;
  document.getElementById('tn-r-tunnel-limit').textContent =
    atCap ? t('tunnel_limit_no_limit') : fmtNum(d.t_outdoor_tunnel_limit_c, 1) + ' °C';
  setTone(document.getElementById('tn-r-tunnel-limit'),
    atCap || d.t_outdoor_tunnel_limit_c > t_real ? 'ok' : 'danger');

  // Совет по причине провала (сервер различает): не хватает скорости — вентиляторы,
  // жарко при нормальной скорости — панели. Раньше при любом провале — панели.
  const NOTE_KEY = {
    ok: 'tn_note_ok', pads: 'tn_note_need_evap', add_fans: 'tn_note_add_fans',
    add_fans_heat: 'tn_note_add_fans_heat', add_fans_and_pads: 'tn_note_add_fans_and_pads',
  };
  const action = NOTE_KEY[d.tunnel_action] ? d.tunnel_action : (limitOk ? 'ok' : 'pads');
  noteEl.textContent = t(NOTE_KEY[action], {
    limit: fmtNum(d.t_outdoor_tunnel_limit_c, 1),
    t_eff: fmtNum(d.effective_temp_c, 1), target: fmtNum(d.bird_comfort_target_c, 1),
    t_eff_target: fmtNum(d.effective_temp_at_target_speed_c, 1),
    v: fmtNum(d.air_velocity_ms, 1), v_min: fmtNum(d.target_v_min_ms, 1), n: d.fans_needed_for_target,
  });
  evapBtn.hidden = !(action === 'pads' || action === 'add_fans_and_pads');

  document.getElementById('tn-results').hidden = false;
}

// Кнопка "Перейти к испарительному охлаждению" — переключает вкладку
document.getElementById('tn-to-evap-btn').addEventListener('click', () => {
  // Тот же путь, что клик по вкладке: панель, класс и aria-selected меняются в одном месте
  document.querySelector('.tool-tab[data-tool="evap"]').click();
  document.getElementById('panel-evap')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
});

// ═══════════════════════════════════════════════════
// EVAPORATIVE COOLING
// ═══════════════════════════════════════════════════

// Доступные толщины для каждого типа панели SANHE
const SANHE_THICKNESSES = {
  '7090': [75, 100, 150, 200, 300],
  '7060': [75, 100, 150, 200, 300],
  '5090': [50, 75, 100, 150],
};

function updatePadThicknessOptions() {
  const padType  = document.getElementById('ev-pad-type').value;
  const thickSel = document.getElementById('ev-thickness');
  const prev     = +thickSel.value;
  const opts     = SANHE_THICKNESSES[padType] || [75, 100, 150];
  thickSel.innerHTML = opts.map(mm =>
    `<option value="${mm}"${mm === prev ? ' selected' : ''}>${mm} mm</option>`
  ).join('');
  // Если предыдущее значение недоступно — берём первое из списка
  if (!opts.includes(prev)) thickSel.value = opts[0];
}

// Инициализация и обработчик изменения типа панели
updatePadThicknessOptions();
document.getElementById('ev-pad-type').addEventListener('change', updatePadThicknessOptions);

document.getElementById('evap-form').addEventListener('submit', async e => {
  e.preventDefault();
  if (!NumField.validate(e.target)) return;
  const btn = document.getElementById('evap-btn');
  btn.disabled = true; btn.textContent = t('btn_evap_busy');

  try {
    const waterT = NumField.value('ev-water-t');
    const payload = {
      house_length_m:    NumField.value('ev-length'),
      t_outdoor_db_c:    NumField.value('ev-tdb'),
      rh_outdoor_pct:    NumField.value('ev-rh'),
      total_fan_m3h:     NumField.value('ev-fans'),
      pad_type:           document.getElementById('ev-pad-type').value,
      pad_thickness_mm:  NumField.value('ev-thickness'),
      pad_length_m:      NumField.value('ev-pad-length'),
      pad_height_m:      NumField.value('ev-padh'),
      t_inside_target_c: NumField.value('ev-target'),
      // Опционально: температура воды. null = стандартный адиабатический расчёт
      ...(waterT !== null ? { water_supply_t_c: waterT } : {}),
      // Нагрев воздуха над птицей до вентиляторов (0 голов — не учитывать)
      num_birds:         NumField.value('ev-birds') ?? 0,
      // Вторая точка паспорта: расход в рабочей точке с сопротивлением панели
      total_fan_25pa_m3h: NumField.value('ev-fans25') ?? 0,
      bird_age_days:     NumField.value('ev-age') ?? null,
    };

    const resp = await fetch('./calc/tools/evap_cooling', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      showToolError('evap', 'ev-results', await apiErrorTextFn(resp, payload));
      return;
    }

    const evapData = await resp.json();
    clearToolError('evap');
    renderEvap(evapData);
    rerenderOnLang.evap = () => renderEvap(evapData);
  } catch (err) {
    showToolError('evap', 'ev-results', () => t('err_prefix') + String(err));
  } finally {
    btn.disabled = false; btn.textContent = t('btn_evap_active');
  }
});

function renderEvap(d) {
  const uM2   = t('unit_m2');
  const uMs   = t('unit_ms');
  const uLpm  = t('unit_lpm');
  const uLh   = t('unit_lh');

  // Бейдж: код и уровень с сервера, текст из словаря
  const statusEl = document.getElementById('ev-status');
  statusEl.textContent = t('ev_status_' + d.status_code);
  statusEl.className = badgeClass(d.status_level);

  // Psychrometrics
  document.getElementById('ev-r-twb').textContent     = fmtNum(d.t_wb_c, 1) + ' °C';
  document.getElementById('ev-r-tdew').textContent    = fmtNum(d.t_dew_c, 1) + ' °C';
  document.getElementById('ev-r-tpad').textContent    = fmtNum(d.t_pad_out_c, 1) + ' °C';
  // Запас и достаточность считаются у вентиляторов — показываем, откуда разница
  document.getElementById('ev-row-rise').hidden = !(d.air_temp_rise_c > 0);
  document.getElementById('ev-r-rise').textContent = t('tn_rise_val', { t: fmtNum(d.t_fan_end_c, 1), rise: fmtNum(d.air_temp_rise_c, 1) });
  document.getElementById('ev-r-cool').textContent    = fmtNum(d.cooling_achieved_c, 1) + ' °C';
  // Максимально достижимое охлаждение (предел T_wb) и % реализации потенциала
  // t_outdoor_db_c не возвращается API — восстанавливаем из cooling_achieved + t_pad_out
  const t_db_rec = d.t_pad_out_c + d.cooling_achieved_c;
  const maxCool  = +(t_db_rec - d.t_wb_c).toFixed(1);
  const potPct  = maxCool > 0 ? Math.round(d.cooling_achieved_c / maxCool * 100) : 100;
  document.getElementById('ev-r-max-cool').textContent =
    fmtNum(maxCool, 1) + ' °C  (' + potPct + '% ' + t('lbl_of_potential') + ')';
  document.getElementById('ev-r-eta').textContent     = Math.round(d.pad_efficiency * 100) + ' %';
  document.getElementById('ev-r-margin').innerHTML    = (() => {
    const cls = d.temp_margin_c >= 2 ? 'ok' : d.temp_margin_c >= 0 ? 'warn' : 'danger';
    return `<span class="${cls}">${fmtNum(d.temp_margin_c, 1)} °C</span>`;
  })();

  // Pad geometry
  document.getElementById('ev-r-area').textContent    = fmtNum(d.pad_area_m2, 2) + ' ' + uM2;
  document.getElementById('ev-r-vel').innerHTML       = (() => {
    const cls = d.velocity_ok ? 'ok' : 'danger';
    return `<span class="${cls}">${fmtNum(d.air_velocity_ms, 2)} ${uMs}</span>`;
  })();
  document.getElementById('ev-r-velstatus').textContent = t('ev_vel_' + d.velocity_status, {
    v: fmtNum(d.air_velocity_ms, 2), v_min: d.pad_v_min_ms, v_max: d.pad_v_max_ms,
    eta: Math.round(d.pad_efficiency * 100), dp: fmtNum(d.pad_pressure_drop_pa, 0),
  });
  // Откуда расход: рабочая точка с сопротивлением панели или паспорт 0 Па (завышен)
  document.getElementById('ev-r-velstatus').textContent += ' · ' + (d.airflow_basis === 'operating_point'
    ? t('ev_basis_operating', { q: fmtNum(d.airflow_m3h, 0) })
    : t('ev_basis_rated_note'));
  document.getElementById('ev-r-rec-area').textContent  = fmtNum(d.recommended_pad_area_m2, 2) + ' ' + uM2;
  if (d.pad_pressure_drop_pa != null)
    document.getElementById('ev-r-dp').textContent      = fmtNum(d.pad_pressure_drop_pa, 0) + ' ' + t('unit_pa');

  // Water consumption
  document.getElementById('ev-r-water-lpm').textContent = fmtNum(d.water_flow_lpm, 1) + ' ' + uLpm;
  document.getElementById('ev-r-water-h').textContent   = fmtNum(d.water_per_hour_l, 0) + ' ' + uLh;

  // Water supply check card
  const waterCard = document.getElementById('ev-water-card');
  if (d.water_regime !== null && d.water_regime !== undefined) {
    document.getElementById('ev-r-water-t').textContent   = fmtNum(d.water_supply_t_c, 1) + ' °C';
    document.getElementById('ev-r-water-min').textContent = fmtNum(d.t_dew_c, 1) + ' °C';

    const noteEl = document.getElementById('ev-water-note');
    const minT   = fmtNum(d.t_dew_c, 1);
    if (d.water_regime === 'safe') {
      setEdge(waterCard, 'ok');
      setBg(noteEl, 'ok-bg');
      noteEl.textContent = t('ev_water_safe', { t_water: fmtNum(d.water_supply_t_c, 1), t_dew: minT });
    } else {
      setEdge(waterCard, 'danger');
      setBg(noteEl, 'danger-bg');
      noteEl.textContent = t('ev_water_cold', { t_water: fmtNum(d.water_supply_t_c, 1), t_dew: minT });
    }

    waterCard.hidden = false;
  } else {
    waterCard.hidden = true;
  }

  document.getElementById('ev-results').hidden = false;
}
