// Simple in-memory + localStorage tabs for houses
const defaultTabs = [
  { id: '1', birds: 35000, age_days: 21, outside_t: 10, cap: 1000000, unit: 'per_bird' },
  { id: '2', birds: 32000, age_days: 21, outside_t: 25, cap: 800000, unit: 'per_bird' },
];

const storeKey = 'vent_mvp_tabs_v1';

function loadTabs() {
  try {
    const raw = localStorage.getItem(storeKey);
    if (!raw) return defaultTabs;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length) return parsed;
  } catch {}
  return defaultTabs;
}

function saveTabs(tabs) {
  localStorage.setItem(storeKey, JSON.stringify(tabs));
}

let tabs = loadTabs();
let active = 0;
let activeHouseTab = 'calc'; // calc, diary, analytics

const elTabs       = document.getElementById('tabs');
const elAddTab     = document.getElementById('addTab');
const elDelTab     = document.getElementById('delTab');
const elHouse      = document.getElementById('house');
const elBirds      = document.getElementById('birds');
const elOutsideTemp = document.getElementById('outsideTemp');
const elCap        = document.getElementById('cap');
const elHeater     = document.getElementById('heater');
const elSum        = document.getElementById('sumBtn');
const elResult     = document.getElementById('result');
const elSummary    = document.getElementById('summary');
const elView       = document.getElementById('viewMode');
let lastSummary = null;

// modal elements
const elModal       = document.getElementById('modal');
const elModalText   = document.getElementById('modalText');
const elModalOk     = document.getElementById('modalOk');
const elModalCancel = document.getElementById('modalCancel');
let pendingDeleteIndex = null;

// house tabs and flock info
const elHouseTabs        = document.getElementById('houseTabs');
const elFlockInfo        = document.getElementById('flockInfo');
const elFlockPlacementDate = document.getElementById('flockPlacementDate');
const elFlockCurrentDay  = document.getElementById('flockCurrentDay');
const elFlockCurrentBirds = document.getElementById('flockCurrentBirds');
const elFlockBreed       = document.getElementById('flockBreed');

function renderTabs() {
  elTabs.innerHTML = '';
  tabs.forEach((tab, i) => {
    const b = document.createElement('button');
    b.className = 'tab' + (i === active ? ' active' : '');
    b.textContent = t('house_tab', { id: tab.id });
    b.onclick = () => { active = i; fillForm(); renderTabs(); renderHouseTabs(); loadFlockInfo(); };
    elTabs.appendChild(b);
  });
}

function renderHouseTabs() {
  if (!elHouseTabs) return;
  const houseTabsData = [
    { id: 'calc',      label: t('tab_calc') },
    { id: 'diary',     label: t('tab_diary') },
    { id: 'analytics', label: t('tab_analytics') }
  ];
  elHouseTabs.innerHTML = '';
  houseTabsData.forEach(ht => {
    const b = document.createElement('button');
    b.className = 'tab' + (ht.id === activeHouseTab ? ' active' : '');
    b.textContent = ht.label;
    b.onclick = () => { activeHouseTab = ht.id; renderHouseTabs(); showActiveContent(); };
    elHouseTabs.appendChild(b);
  });
  showActiveContent();
}

function showActiveContent() {
  const calcContent     = document.getElementById('calcContent');
  const diaryContent    = document.getElementById('diaryContent');
  const analyticsContent = document.getElementById('analyticsContent');

  if (calcContent)      calcContent.style.display = 'none';
  if (diaryContent)     diaryContent.style.display = 'none';
  if (analyticsContent) analyticsContent.style.display = 'none';

  if (activeHouseTab === 'calc' && calcContent)           calcContent.style.display = 'grid';
  else if (activeHouseTab === 'diary' && diaryContent)    diaryContent.style.display = 'grid';
  else if (activeHouseTab === 'analytics' && analyticsContent) analyticsContent.style.display = 'grid';
}

async function loadFlockInfo() {
  const tab = tabs[active];
  if (!tab || !elFlockInfo) return;

  try {
    const r = await fetch(`/flock/${tab.id}/info`);
    if (r.ok) {
      const data = await r.json();
      elFlockInfo.style.display = 'block';
      elFlockPlacementDate.textContent  = data.placement_date || '—';
      elFlockCurrentDay.textContent     = data.current_day || '—';
      elFlockCurrentBirds.textContent   = data.initial_bird_count || tab.birds || '—';
      elFlockBreed.textContent          = data.breed || '—';
    } else {
      elFlockInfo.style.display = 'none';
    }
  } catch (e) {
    console.warn('Failed to load flock info:', e);
    elFlockInfo.style.display = 'none';
  }
}

function fillForm() {
  const tab = tabs[active];
  elHouse.value = tab.id;
  elBirds.value = tab.birds;
  if (elOutsideTemp) elOutsideTemp.value = tab.outside_t ?? 15;
  elCap.value = tab.cap ?? '';
  elHeater.checked = !!tab.heater_on;
  (document.querySelector(`input[name="unit"][value="${tab.unit || 'per_bird'}"]`) || {}).checked = true;
}

function readFormToTab() {
  const tab = tabs[active];
  const idVal = (elHouse.value || '').trim();
  tab.id       = idVal !== '' ? idVal : tab.id;
  tab.birds    = Number(elBirds.value || tab.birds);
  tab.outside_t = elOutsideTemp ? Number(elOutsideTemp.value) : (tab.outside_t ?? 15);
  const capVal = elCap.value === '' ? null : Number(elCap.value);
  tab.cap      = capVal;
  tab.heater_on = !!elHeater.checked;
  tab.unit     = 'per_bird';
  saveTabs(tabs);
}

async function recalc() {
  readFormToTab();
  const tab = tabs[active];
  const payload = {
    house:        tab.id,
    birds:        tab.birds,
    age_days:     tab.age_days,
    mode_id:      'summer', // Deprecated, kept for backward compatibility
    display_unit: tab.unit,
    outside_t:    tab.outside_t ?? 15,
    heater_on:    !!tab.heater_on,
  };
  if (tab.cap !== null && tab.cap !== undefined && tab.cap !== '') payload.user_max_m3h = tab.cap;

  elSum.disabled = true; elSum.textContent = t('btn_calculating');
  try {
    const r = await fetch('/calc/minmax', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`${r.status} ${r.statusText}: ${txt}`);
    }
    const data = await r.json();
    renderResult(data, tab);
  } catch (e) {
    elResult.innerHTML = `<div class="danger">${t('err_request', { msg: String(e) })}</div>`;
  } finally {
    elSum.disabled = false; elSum.textContent = t('btn_calc_profile');
  }
}

async function summary7() {
  readFormToTab();
  const tab = tabs[active];
  const payload = {
    house:        tab.id,
    birds:        tab.birds,
    mode_id:      'summer', // Deprecated but required by API
    user_max_m3h: (tab.cap === null || tab.cap === undefined || tab.cap === '') ? null : Number(tab.cap),
    heater_on:    !!tab.heater_on,
    display_unit: tab.unit,
    outside_t:    tab.outside_t ?? 15,
  };
  elSum.disabled = true; elSum.textContent = t('btn_calculating');
  try {
    const r = await fetch('/calc/summary7', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`${r.status} ${r.statusText}: ${txt}`);
    }
    const data = await r.json();
    lastSummary = data;
    renderSummary(data);
  } catch (e) {
    elSummary.innerHTML = `<div class="danger">${t('err_request', { msg: String(e) })}</div>`;
  } finally {
    elSum.disabled = false; elSum.textContent = t('btn_calc_profile');
  }
}

function renderSummary(d) {
  const tab = tabs[active];
  const outsideT = tab.outside_t ?? 15;
  const head = `
    <div class="kv"><span>${t('sum_outdoor')}</span><span>${outsideT} °C</span></div>
    <div class="kv"><span>${t('sum_house_birds')}</span><span>${d.house} / ${d.birds}</span></div>
    <div class="kv"><span>${t('sum_sys_max')}</span><span>${d.user_max_m3h ?? '—'} ${t('unit_m3h_plain')}</span></div>`;

  const mode = elView ? elView.value : 'total';
  const headerByMode = {
    total:    [t('hdr_qmin_m3h'), t('hdr_qmax_m3h')],
    percent:  [t('hdr_qmin_pct'), t('hdr_qmax_pct')],
    per_bird: [t('hdr_qmin_bird'), t('hdr_qmax_bird')],
    per_kg:   [t('hdr_qmin_kg'),  t('hdr_qmax_kg')]
  };
  const headCols = headerByMode[mode] || headerByMode.total;

  const rows = d.rows.map(r => {
    let c1 = '—', c2 = '—';
    if (mode === 'total') {
      c1 = Math.round(r.q_min_m3h).toString();
      c2 = Math.round(r.q_max_m3h).toString();
    } else if (mode === 'percent') {
      c1 = r.q_min_pct != null ? (r.q_min_pct.toFixed(1) + '%') : '—';
      c2 = r.q_max_pct != null ? (r.q_max_pct.toFixed(1) + '%') : '—';
    } else if (mode === 'per_bird') {
      const be = r.birds_eff || d.birds;
      if (be > 0) { c1 = (r.q_min_m3h / be).toFixed(4); c2 = (r.q_max_m3h / be).toFixed(4); }
    } else if (mode === 'per_kg') {
      const be = r.birds_eff || d.birds;
      const wkg = (r.weight_g || 0) / 1000.0;
      const totalKg = be * wkg;
      if (totalKg > 0) { c1 = (r.q_min_m3h / totalKg).toFixed(4); c2 = (r.q_max_m3h / totalKg).toFixed(4); }
    }
    return `
      <tr>
        <td>${r.day}</td>
        <td>${r.min_temp_c ?? '—'}</td>
        <td>${r.weight_g != null ? Math.round(r.weight_g) : '—'}</td>
        <td>${c1}</td>
        <td>${c2}</td>
      </tr>`;
  }).join('');

  elSummary.innerHTML = `${head}
    <table>
      <thead><tr>
        <th>${t('col_day')}</th><th>${t('col_min_temp')}</th><th>${t('col_weight')}</th>
        <th>${headCols[0]}</th><th>${headCols[1]}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderResult(d, tab) {
  const cap = tab.cap ? Number(tab.cap) : null;
  const pct = (x) => cap && cap > 0 ? ((x / cap) * 100).toFixed(1) + '%' : '—';
  const weight = (typeof d.weight_used_g === 'number' && isFinite(d.weight_used_g))
    ? d.weight_used_g.toFixed(0) : '—';
  const dayInfo = d.day_setpoints
    ? `<div class="kv"><span>${t('res_day_setpoints')}</span><span>${d.day_setpoints.min_temp_c ?? '—'} °C, RH ${d.day_setpoints.rv_percent ?? '—'}%</span></div>`
    : '';

  elResult.innerHTML = `
    <div class="kv"><span>${t('res_age_day')}</span><span>${d.profile_day_resolved}</span></div>
    <div class="kv"><span>${t('res_weight_g')}</span><span>${weight}</span></div>
    <div class="kv big"><span>${t('res_qmin')}</span><span class="ok">${Math.round(d.q_min_m3h)} ${t('unit_m3h_plain')}</span></div>
    <div class="kv"><span>${t('res_qmin_pct')}</span><span>${pct(d.q_min_m3h)}</span></div>
    <div class="kv big"><span>${t('res_qmax')}</span><span class="warn">${Math.round(d.q_max_m3h)} ${t('unit_m3h_plain')}</span></div>
    <div class="kv"><span>${t('res_qmax_nominal')}</span><span>${Math.round(d.q_max_nominal_m3h)} ${t('unit_m3h_plain')}</span></div>
    <div class="kv"><span>${t('res_qmax_pct')}</span><span>${pct(d.q_max_m3h)}</span></div>
    <div class="kv"><span>${t('res_rates_bird')}</span><span>${d.rates.per_bird.min}…${d.rates.per_bird.max} ${t('unit_m3h_bird')}</span></div>
    <div class="kv"><span>${t('res_rates_kg')}</span><span>${d.rates.per_kg.min}…${d.rates.per_kg.max} ${t('unit_m3h_kg')}</span></div>
    ${dayInfo}
  `;
}

const MAX_HOUSES = 30; // разумный предел для одной фермы

elAddTab.onclick = () => {
  if (tabs.length >= MAX_HOUSES) {
    // Не даём накапливать сотни корпусов и ломать вёрстку
    alert(t('err_max_houses', { max: MAX_HOUSES }));
    return;
  }
  const last = tabs[tabs.length - 1]?.id || '0';
  const nextNum = parseInt(last, 10);
  const nextId = isNaN(nextNum) ? `${tabs.length + 1}` : String(nextNum + 1);
  tabs.push({ id: nextId, birds: 30000, age_days: 21, outside_t: 10, cap: null, unit: 'per_bird' });
  active = tabs.length - 1;
  saveTabs(tabs);
  renderTabs(); fillForm();
};

elDelTab.onclick = () => {
  const tab = tabs[active];
  const name = tab?.id ?? (active + 1);
  pendingDeleteIndex = active;
  if (elModal && elModalText) {
    elModalText.textContent = t('modal_remove_txt', { name });
    elModal.classList.remove('hidden');
    // Inline fallback styles (in case CSS cache)
    elModal.style.position = 'fixed';
    elModal.style.top = '0';
    elModal.style.left = '0';
    elModal.style.right = '0';
    elModal.style.bottom = '0';
    elModal.style.background = 'rgba(0,0,0,0.5)';
    elModal.style.display = 'flex';
    elModal.style.alignItems = 'center';
    elModal.style.justifyContent = 'center';
    elModal.style.zIndex = '1000';
    const card = elModal.querySelector('.modal-card');
    if (card) {
      card.style.background = getComputedStyle(document.body).getPropertyValue('--card') || '#15161a';
      card.style.border = '1px solid ' + (getComputedStyle(document.body).getPropertyValue('--border') || '#26272c');
      card.style.borderRadius = '12px';
      card.style.padding = '16px';
      card.style.width = '420px';
      card.style.maxWidth = '90vw';
      card.style.boxShadow = '0 10px 30px rgba(0,0,0,0.4)';
    }
  }
};

function applyDelete(index) {
  if (index == null) return;
  if (tabs.length <= 1) {
    tabs = [{ id: '1', birds: 30000, age_days: 21, outside_t: 10, cap: null, unit: 'per_bird' }];
    active = 0;
  } else {
    tabs.splice(index, 1);
    if (active >= tabs.length) active = tabs.length - 1;
  }
  saveTabs(tabs);
  renderTabs(); fillForm();
}

if (elModalOk) elModalOk.addEventListener('click', () => {
  applyDelete(pendingDeleteIndex);
  pendingDeleteIndex = null;
  elModal.classList.add('hidden');
  elModal.removeAttribute('style');
  const c = elModal.querySelector('.modal-card');
  if (c) c.removeAttribute('style');
});
if (elModalCancel) elModalCancel.addEventListener('click', () => {
  pendingDeleteIndex = null;
  elModal.classList.add('hidden');
  elModal.removeAttribute('style');
  const c = elModal.querySelector('.modal-card');
  if (c) c.removeAttribute('style');
});

elSum.onclick = summary7;

const elViewCtl = document.getElementById('viewMode');
if (elViewCtl) {
  elViewCtl.addEventListener('change', () => { if (lastSummary) renderSummary(lastSummary); });
}
const elOutsideTempCtl = document.getElementById('outsideTemp');
if (elOutsideTempCtl) {
  elOutsideTempCtl.addEventListener('change', () => { summary7(); });
}

renderTabs();
renderHouseTabs();
fillForm();
loadFlockInfo();
