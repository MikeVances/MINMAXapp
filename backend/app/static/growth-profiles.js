// growth-profiles.js — редактор профиля роста на вкладке «Профиль вентиляции»
// (вынесено из calculators.html; классический скрипт, порядок подключения — там же)

(function () {
  // ── SVG chart renderer ───────────────────────────────────────────────────
  function makeSVGChart({ series, title, yUnit }) {
    yUnit = yUnit || '';
    const W = 300, H = 180;
    const P = { t: 26, r: 10, b: 30, l: 46 };
    const CW = W - P.l - P.r, CH = H - P.t - P.b;

    const allY = series.flatMap(s => s.data.map(p => p.y).filter(v => v != null));
    if (!allY.length) return '';
    const allX = series[0].data.map(p => p.x);
    const xMin = allX[0], xMax = allX[allX.length - 1];
    let yLo = Math.min(...allY), yHi = Math.max(...allY);
    const pad = (yHi - yLo) * 0.08 || 1;
    yLo = Math.max(0, yLo - pad); yHi += pad;

    const tx = x => P.l + (x - xMin) / (xMax - xMin) * CW;
    const ty = y => P.t + (1 - (y - yLo) / (yHi - yLo)) * CH;

    const rawStep = (yHi - yLo) / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep || 1)));
    const niceStep = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= rawStep) || rawStep;
    const yTicks = [];
    for (let y = Math.ceil(yLo / niceStep) * niceStep; y <= yHi + niceStep * 0.01; y += niceStep) yTicks.push(y);

    const xTicks  = allX.filter(x => x === 1 || x % 7 === 0);
    const xLabels = allX.filter(x => x === 1 || x % 14 === 0 || x === xMax);

    // role=img + название: диктор называет график целиком, а не читает подписи осей
    // по одной; значения доступны в таблице профиля под графиками
    let o = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" class="chart-svg" role="img" aria-label="${escapeHtml(title + (yUnit ? ', ' + yUnit : ''))}">`;
    o += `<rect width="${W}" height="${H}" fill="var(--card)" rx="8"/>`;
    o += `<text x="${P.l}" y="17" fill="var(--text)" font-size="12" font-weight="600" font-family="system-ui,Arial">${title}</text>`;
    o += `<text x="${W - P.r}" y="17" fill="var(--muted)" font-size="10" text-anchor="end" font-family="system-ui,Arial">${yUnit}</text>`;

    for (const y of yTicks) {
      const cy = ty(y);
      if (cy < P.t - 2 || cy > P.t + CH + 2) continue;
      o += `<line x1="${P.l}" y1="${cy.toFixed(1)}" x2="${P.l + CW}" y2="${cy.toFixed(1)}" stroke="var(--border)"/>`;
      const lbl = y >= 1000 ? fmtNum(Math.round(y / 100) / 10) + 'k' : (y >= 10 ? Math.round(y) : fmtNum(y, 1));
      o += `<text x="${P.l - 4}" y="${(cy + 3.5).toFixed(1)}" fill="var(--muted)" font-size="9" text-anchor="end" font-family="system-ui,Arial">${lbl}</text>`;
    }

    o += `<line x1="${P.l}" y1="${P.t}" x2="${P.l}" y2="${P.t + CH}" stroke="var(--border)"/>`;
    o += `<line x1="${P.l}" y1="${P.t + CH}" x2="${P.l + CW}" y2="${P.t + CH}" stroke="var(--border)"/>`;

    for (const x of xTicks)  { const cx = tx(x); o += `<line x1="${cx.toFixed(1)}" y1="${P.t + CH}" x2="${cx.toFixed(1)}" y2="${P.t + CH + 4}" stroke="var(--muted)"/>`; }
    for (const x of xLabels) { const cx = tx(x); o += `<text x="${cx.toFixed(1)}" y="${P.t + CH + 16}" fill="var(--muted)" font-size="9" text-anchor="middle" font-family="system-ui,Arial">${x}</text>`; }

    if (series.length >= 2) {
      const top = series[0].data.filter(p => p.y != null).map(p => `${tx(p.x).toFixed(1)},${ty(p.y).toFixed(1)}`).join(' ');
      const bot = [...series[1].data].reverse().filter(p => p.y != null).map(p => `${tx(p.x).toFixed(1)},${ty(p.y).toFixed(1)}`).join(' ');
      if (top && bot) o += `<polygon points="${top} ${bot}" fill="${series[0].color}" fill-opacity="0.15"/>`;
    }

    for (const s of series) {
      const pts = s.data.filter(p => p.y != null).map(p => `${tx(p.x).toFixed(1)},${ty(p.y).toFixed(1)}`).join(' ');
      o += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>`;
    }

    // Anchor dots (editable points) — rendered on top
    for (const s of series) {
      if (!s.anchors) continue;
      for (const a of s.anchors) {
        if (a.y == null) continue;
        o += `<circle cx="${tx(a.x).toFixed(1)}" cy="${ty(a.y).toFixed(1)}" r="3.5" fill="${s.color}" stroke="var(--bg)" stroke-width="1.5"/>`;
      }
    }

    return o + '</svg>';
  }

  // fetchJSON и escapeHtml — общие, из ui.js

  // ── State ────────────────────────────────────────────────────────────────
  // profileCfg объявлен глобально (var) в основном script-блоке — здесь только обновляем
  profileCfg = { cycle_days: 42 };
  const STORE_KEY = 'vent_mvp_tabs_v1';

  let profilesList = [];     // [{id, name, breed, builtin, source, first_day, last_day}]
  let current      = null;   // полный профиль: {…, points: [...], days: [...]}
  let editedDays   = {};     // день → {body_weight_g, min_temp_c, rv_percent} — правки в таблице
  let houseSelShown = null;  // корпус, для которого показан профиль: к нему возвращает отказ от сброса правок
  let chartUnit    = 'per_bird';

  const growthSel = document.getElementById('prof-growth-select');
  const houseSel  = document.getElementById('prof-house-select');

  // Имя и источник профиля пишет пользователь — в innerHTML только через escapeHtml

  // ── Выбор профиля хранится во вкладке корпуса (localStorage главной страницы) ──
  function readTabs() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '[]') || []; } catch (e) { return []; }
  }
  function currentHouseIdx() {
    const idx = parseInt(houseSel && houseSel.value, 10);
    return isNaN(idx) ? -1 : idx;
  }
  function rememberForHouse(profileId) {
    const tabs = readTabs();
    const idx  = currentHouseIdx();
    if (!tabs[idx]) return;
    tabs[idx].growth_profile_id = profileId;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(tabs)); } catch (e) { /* выбор не запомнится — не критично */ }
  }
  function profileForHouse() {
    const tab = readTabs()[currentHouseIdx()];
    const wanted = tab && tab.growth_profile_id;
    if (wanted && profilesList.some(p => p.id === wanted)) return wanted;
    return profileCfg.default_growth_profile || (profilesList[0] && profilesList[0].id);
  }

  // ── Недельная сетка таблицы ──────────────────────────────────────────────
  // Сколько дней профиля показывать: у бройлера — цикл хозяйства из настроек, у
  // индейки — весь профиль (цикл до 22 недель, в настройках бройлерной фермы его нет)
  function shownLastDay() {
    if (current.species === 'turkey') return current.last_day;
    return Math.min(profileCfg.cycle_days || 42, current.last_day);
  }

  function weeklyDays() {
    if (!current) return [];
    const last = shownLastDay();
    const days = [Math.max(1, current.first_day)];
    for (let d = 7; d < last; d += 7) days.push(d);
    if (days[days.length - 1] !== last) days.push(last);
    return days;
  }
  function dayRow(day) {
    const base = (current.days || []).find(d => d.day === day) || { day };
    return Object.assign({}, base, editedDays[day] || {});
  }

  // ── Charts ───────────────────────────────────────────────────────────────
  function renderCharts() {
    const container = document.getElementById('profile-charts');
    if (!container || !current) return;

    const cycleDays = shownLastDay();
    const chartData = (current.days || []).filter(d => d.day >= 1 && d.day <= cycleDays);
    if (!chartData.length) { container.innerHTML = ''; return; }
    const anchors = weeklyDays().map(dayRow);

    const birdLabel = t('unit_bird');
    const kgLabel   = t('unit_kg');
    const unitLabel = chartUnit === 'per_kg' ? kgLabel : birdLabel;

    const ventVal = (p, field) => {
      const v = p[field];
      if (v == null) return null;
      if (chartUnit === 'per_kg' && p.body_weight_g > 0) return +(v / (p.body_weight_g / 1000)).toFixed(3);
      return v;
    };

    const wChart = makeSVGChart({
      series: [{
        data:    chartData.map(p => ({ x: p.day, y: p.body_weight_g })),
        color:   'var(--chart-1)',
        anchors: anchors.map(p => ({ x: p.day, y: p.body_weight_g })),
      }],
      title: t('chart_weight'), yUnit: t('unit_g'),
    });
    const tChart = makeSVGChart({
      series: [{
        data:    chartData.map(p => ({ x: p.day, y: p.min_temp_c })),
        color:   'var(--chart-2)',
        anchors: anchors.map(p => ({ x: p.day, y: p.min_temp_c })),
      }],
      title: t('chart_temp'), yUnit: '°C',
    });
    // Только Qmin: норма CO₂ из веса (сервер). Qmax — величина корпуса, не профиля
    const vChart = makeSVGChart({
      series: [{
        data:    chartData.map(p => ({ x: p.day, y: ventVal(p, 'q_min_per_bird') })),
        color:   'var(--chart-3)',
        anchors: anchors.map(p => ({ x: p.day, y: ventVal(p, 'q_min_per_bird') })),
      }],
      title: t('chart_vent'), yUnit: unitLabel,
    });

    const bB = `<button id="pu-bird" class="btn btn-secondary unit-toggle${chartUnit==='per_bird' ? '' : ' is-dim'}">${birdLabel}</button>`;
    const bK = `<button id="pu-kg"   class="btn btn-secondary unit-toggle${chartUnit==='per_kg'   ? '' : ' is-dim'}">${kgLabel}</button>`;

    container.innerHTML = `
      <div class="card">
        <div class="d-flex jc-between ai-center wrap gap-8 mb-12">
          <h2 class="m-0">${t('charts_h2')}</h2>
          <div class="d-flex gap-6">${bB}${bK}</div>
        </div>
        <div class="d-grid cols-fit-220 gap-12">
          ${wChart}${tChart}${vChart}
        </div>
      </div>`;

    document.getElementById('pu-bird').addEventListener('click', () => { chartUnit = 'per_bird'; renderCharts(); });
    document.getElementById('pu-kg').addEventListener('click',   () => { chartUnit = 'per_kg';   renderCharts(); });
  }

  // ── Editor ───────────────────────────────────────────────────────────────
  function rowHTML(d, readonly) {
    const dis = readonly ? 'disabled' : '';
    // Имя поля для экранного диктора: «Вес, г · День 14». Заголовок колонки с полем
    // в ячейке не связывается, и 21 поле звучали одинаково — «поле ввода»
    const COL = { body_weight_g: 'col_weight', min_temp_c: 'col_min_temp', rv_percent: 'col_rh' };
    const cell = (key, val, extra) =>
      `<td><input type="text" data-num ${extra || ''} value="${val ?? ''}" data-key="${key}" data-day="${d.day}" ${dis}
        aria-label="${escapeHtml(t(COL[key]) + ' · ' + t('col_day') + ' ' + d.day)}"/></td>`;
    const r = v => (v == null ? '' : +(+v).toFixed(1));
    return `<tr>
      <td><strong>${d.day}</strong></td>
      ${cell('body_weight_g', r(d.body_weight_g), 'inputmode="decimal" data-min="0"')}
      ${cell('min_temp_c', r(d.min_temp_c))}
      ${cell('rv_percent', r(d.rv_percent), 'inputmode="decimal" data-min="0" data-max="100"')}
    </tr>`;
  }

  // Источник профиля. У встроенных профилей это структура (ref/page/table/column/
  // basis/method/url), подпись к которой собирается на языке интерфейса; строка —
  // свободный текст пользователя или служебное copied_from.
  function sourceEntryHTML(key, v) {
    // Индейка: масса суточной птицы — свой источник, смешанное стадо — своя таблица
    const label = ['weight', 'climate', 'weight_day0', 'climate_mixed'].includes(key)
      ? t('gp_src_' + key) : escapeHtml(key);
    if (v && typeof v === 'object') {
      const bits = [];
      if (v.ref)    bits.push(escapeHtml(v.ref));
      if (v.table)  bits.push(t('gp_src_table',  { n: escapeHtml(v.table) }));
      if (v.page)   bits.push(t('gp_src_page',   { n: escapeHtml(v.page) }));
      if (v.column) bits.push(t('gp_src_column', { c: escapeHtml(v.column) }));
      if (v.basis)  bits.push(t('gp_src_basis_'  + v.basis));
      if (v.method) bits.push(t('gp_src_method_' + v.method));
      if (v.url)    bits.push(`<a href="${escapeHtml(v.url)}" target="_blank" rel="noopener">PDF</a>`);
      return `${label}: ${bits.join(', ')}`;
    }
    if (key === 'copied_from') return t('gp_src_copied_from', { id: escapeHtml(v) });
    return `${label}: ${escapeHtml(v)}`;
  }

  function sourceHTML(src) {
    const parts = Object.entries(src || {}).map(([k, v]) => sourceEntryHTML(k, v));
    return parts.length ? `<p class="muted fs-11 mt-0 mb-10">${t('gp_source')}: ${parts.join(' · ')}</p>` : '';
  }

  function renderTable() {
    const container = document.getElementById('profile-editor');
    if (!container || !current) return;
    const ro = current.builtin;

    const buttons = ro
      ? `<button id="gp-copy-btn" class="btn">${t('btn_copy_profile')}</button>`
      : `<button id="gp-save-btn" class="btn">${t('btn_save')}</button>
         <button id="gp-copy-btn" class="btn btn-secondary">${t('btn_copy_profile')}</button>
         <button id="gp-delete-btn" class="btn btn-secondary">${t('btn_delete_profile')}</button>`;

    container.innerHTML = `
      <div class="card">
        <div class="d-flex jc-between ai-center wrap gap-8 mb-4">
          <h2 class="m-0">${t('profile_h2')} — ${escapeHtml(current.name)}
            <span class="muted fs-12 fw-400">(${ro ? t('gp_builtin') : t('gp_custom')})</span></h2>
          <div class="d-flex gap-8 ai-center wrap">
            ${buttons}
            <span id="prof-status" class="muted fs-12" role="status"></span>
          </div>
        </div>
        ${ro ? `<p class="muted fs-11 mt-0 mb-6">${t('gp_readonly_hint')}</p>` : ''}
        ${!ro ? `<label class="mt-0 mb-10 mx-0 d-block"><span class="muted fs-12">${t('profile_name_lbl')}</span>
          <input id="gp-name" type="text" maxlength="80" value="${escapeHtml(current.name)}"/></label>` : ''}
        ${sourceHTML(current.source)}
        <p class="muted fs-11 mt-0 mb-6">${t('cigr_hint')}</p>
        <!-- Сноска к колонке температуры — над таблицей, а не в заголовке: длинный
             заголовок забирал ширину, и колонка ОВ сжималась до 31 px на телефоне -->
        <p class="muted fs-11 mt-0 mb-12">${t('col_min_temp')} ${t('gp_temp_ref')}</p>
        <div class="ox-auto">
          <table>
            <thead><tr>
              <th>${t('col_day')}</th>
              <th>${t('col_weight')}</th>
              <th>${t('col_min_temp')}</th>
              <th>${t('col_rh')}</th>
            </tr></thead>
            <tbody>${weeklyDays().map(d => rowHTML(dayRow(d), ro)).join('')}</tbody>
          </table>
        </div>
      </div>`;

    container.querySelectorAll('tbody input').forEach(inp => {
      inp.addEventListener('change', () => {
        const day = Number(inp.dataset.day);
        // Мусор не записываем: поле подсвечено (numfield.js), прежнее значение остаётся
        if (NumField.problem(inp)) return;
        const val = NumField.value(inp);
        editedDays[day] = Object.assign({}, editedDays[day] || {}, { [inp.dataset.key]: val });
        renderCharts();
      });
    });

    const on = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('click', fn); };
    on('gp-copy-btn', copyProfile);
    on('gp-save-btn', saveProfile);
    on('gp-delete-btn', deleteProfile);
  }

  function setStatus(msg, delay) {
    const el = document.getElementById('prof-status');
    if (!el) return;
    el.textContent = msg;
    if (delay) setTimeout(() => { const s = document.getElementById('prof-status'); if (s) s.textContent = ''; }, delay);
  }

  // ── Точки для сохранения ─────────────────────────────────────────────────
  // Правка недельной строки меняет только свой отрезок кривой: дневные точки между
  // соседними строками таблицы удаляются, и сервер заполнит их интерполяцией.
  // Неправленые отрезки (например, дневные данные производителя) остаются как есть.
  function pointsForSave() {
    const grid = weeklyDays();
    let points = (current.points || []).map(p => Object.assign({}, p));
    Object.keys(editedDays).map(Number).forEach(day => {
      const i    = grid.indexOf(day);
      const prev = i > 0 ? grid[i - 1] : -Infinity;
      const next = i < grid.length - 1 ? grid[i + 1] : Infinity;
      const base = points.find(p => p.day === day) || dayRow(day);
      points = points.filter(p => p.day <= prev || p.day >= next || p.day === day);
      const merged = {
        day,
        body_weight_g: base.body_weight_g ?? null,
        min_temp_c:    base.min_temp_c ?? null,
        rv_percent:    base.rv_percent ?? null,
        ...editedDays[day],
      };
      points = points.filter(p => p.day !== day).concat([merged]);
    });
    return points.sort((a, b) => a.day - b.day);
  }

  // ── API actions ──────────────────────────────────────────────────────────
  async function putProfile(id, body) {
    return fetchJSON(`./profiles/${encodeURIComponent(id)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  }

  async function copyProfile() {
    const name = window.prompt(t('prompt_profile_name'), `${current.name} (${t('gp_custom')})`);
    if (!name) return;
    // id — латиница для имени файла; имя для людей хранится отдельно и может быть любым
    const id = 'custom-' + Date.now().toString(36);
    setStatus(t('status_saving'));
    try {
      const copySource = Object.assign({}, current.source || {}, { copied_from: current.id });
      await putProfile(id, { name, breed: current.breed, source: copySource, points: pointsForSave() });
      await loadProfilesList();
      await selectProfile(id);
      setStatus(t('status_saved_ok'), 3000);
    } catch (e) {
      setStatus(t('status_err') + (e.message || e));
    }
  }

  async function saveProfile() {
    const nameEl = document.getElementById('gp-name');
    setStatus(t('status_saving'));
    try {
      current = await putProfile(current.id, {
        name:   (nameEl && nameEl.value.trim()) || current.name,
        breed:  current.breed,
        source: current.source,
        points: pointsForSave(),
      });
      editedDays = {};
      await loadProfilesList();
      renderAll();
      setStatus(t('status_saved_ok'), 3000);
    } catch (e) {
      setStatus(t('status_err') + (e.message || e));
    }
  }

  async function deleteProfile() {
    if (!window.confirm(t('confirm_delete_profile'))) return;
    try {
      await fetchJSON(`./profiles/${encodeURIComponent(current.id)}`, { method: 'DELETE' });
      await loadProfilesList();
      await selectProfile(profileCfg.default_growth_profile);
    } catch (e) {
      setStatus(t('status_err') + (e.message || e));
    }
  }

  // ── Load ─────────────────────────────────────────────────────────────────
  async function loadProfilesList() {
    profilesList = await fetchJSON('./profiles');
    renderProfilesList();
  }

  // Группы списка подписаны из словаря — вызывается и при смене языка
  function renderProfilesList() {
    growthSel.innerHTML = '';
    // Сначала профили производителей, затем свои — двумя группами
    [[true, t('gp_builtin')], [false, t('gp_custom')]].forEach(([builtin, label]) => {
      const items = profilesList.filter(p => p.builtin === builtin);
      if (!items.length) return;
      const group = document.createElement('optgroup');
      group.label = label;
      items.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name;   // textContent: имя пользователя не попадает в разметку
        group.appendChild(opt);
      });
      growthSel.appendChild(group);
    });
    // Перестройка списка сбрасывает select на первый вариант — вернуть текущий профиль,
    // иначе расчёт уйдёт по чужому кроссу
    if (current && profilesList.some(p => p.id === current.id)) growthSel.value = current.id;
  }

  async function selectProfile(id) {
    if (!id) return;
    current    = await fetchJSON(`./profiles/${encodeURIComponent(id)}`);
    editedDays = {};
    growthSel.value = id;
    if (houseSel) houseSelShown = houseSel.value;   // корпус, к которому относится показанный профиль
    rememberForHouse(id);
    renderAll();
    // Расчёт профиля показывает этапы индейки только у её профилей — сообщаем вид
    document.dispatchEvent(new CustomEvent('growthprofile:change', {
      detail: { species: current.species || 'broiler', last_day: current.last_day } }));
  }

  function renderAll() {
    renderCharts();
    renderTable();
  }

  async function loadProfile() {
    try {
      profileCfg = await fetchJSON('./settings/app-config');
      await loadProfilesList();
      await selectProfile(profileForHouse());
    } catch (e) {
      const container = document.getElementById('profile-editor');
      if (container) container.innerHTML = `<div class="card"><div class="danger">${escapeHtml(t('err_prefix') + (e.message || e))}</div></div>`;
    }
  }

  // Несохранённые правки таблицы. Раньше смена профиля или корпуса сбрасывала
  // их молча (аудит 2026-10-18). Сохранить за пользователя нельзя: это запись
  // профиля на сервер, а у встроенного профиля — только «Копировать как свой».
  function hasUnsavedEdits() { return Object.keys(editedDays).length > 0; }
  function mayDiscardEdits() { return !hasUnsavedEdits() || window.confirm(t('confirm_discard_profile_edits')); }

  growthSel.addEventListener('change', () => {
    if (!mayDiscardEdits()) { growthSel.value = current.id; return; }
    selectProfile(growthSel.value).catch(e => setStatus(t('status_err') + (e.message || e)));
  });

  // Другой корпус — свой профиль роста. Отказ возвращает прежний корпус и
  // повторно шлёт change: на тот же select подписан расчёт профиля (selIdx)
  let houseSelReverting = false;
  if (houseSel) houseSel.addEventListener('change', () => {
    if (houseSelReverting) return;
    if (!mayDiscardEdits()) {
      houseSelReverting = true;
      houseSel.value = houseSelShown;
      houseSel.dispatchEvent(new Event('change'));
      houseSelReverting = false;
      return;
    }
    houseSelShown = houseSel.value;
    selectProfile(profileForHouse()).catch(() => {});
  });

  // Уход со страницы с правками — браузер переспросит
  window.addEventListener('beforeunload', e => {
    if (!hasUnsavedEdits()) return;
    e.preventDefault();
    e.returnValue = '';
  });

  document.addEventListener('DOMContentLoaded', loadProfile);

  // Смена языка: подписи групп, таблица и графики собраны в JS из словаря.
  // Правки таблицы живут в editedDays и переживают перерисовку
  document.addEventListener('i18n:change', () => { renderProfilesList(); if (current) renderAll(); });
})();
