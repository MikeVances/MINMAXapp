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
    const t = JSON.parse(raw);
    if (Array.isArray(t) && t.length) return t;
  } catch {}
  return defaultTabs;
}

function saveTabs(tabs) {
  localStorage.setItem(storeKey, JSON.stringify(tabs));
}

let tabs = loadTabs();
let active = 0;

const elTabs = document.getElementById('tabs');
const elAddTab = document.getElementById('addTab');
const elDelTab = document.getElementById('delTab');
const elHouse = document.getElementById('house');
const elBirds = document.getElementById('birds');
const elSeasonRes = document.getElementById('seasonResult');
const elCap = document.getElementById('cap');
const elHeater = document.getElementById('heater');
const elSum = document.getElementById('sumBtn');
const elResult = document.getElementById('result');
const elSummary = document.getElementById('summary');
const elView = document.getElementById('viewMode');
let lastSummary = null;
// modal elements
const elModal = document.getElementById('modal');
const elModalText = document.getElementById('modalText');
const elModalOk = document.getElementById('modalOk');
const elModalCancel = document.getElementById('modalCancel');
let pendingDeleteIndex = null;

function renderTabs() {
  elTabs.innerHTML = '';
  tabs.forEach((t, i) => {
    const b = document.createElement('button');
    b.className = 'tab' + (i === active ? ' active' : '');
    b.textContent = `Птичник ${t.id}`;
    b.onclick = () => { active = i; fillForm(); renderTabs(); };
    elTabs.appendChild(b);
  });
}

function fillForm() {
  const t = tabs[active];
  elHouse.value = t.id;
  elBirds.value = t.birds;
  if (elSeasonRes) elSeasonRes.value = t.season || 'summer';
  elCap.value = t.cap ?? '';
  elHeater.checked = !!t.heater_on;
  (document.querySelector(`input[name="unit"][value="${t.unit || 'per_bird'}"]`)||{}).checked = true;
}

function readFormToTab() {
  const t = tabs[active];
  const idVal = (elHouse.value || '').trim();
  t.id = idVal !== '' ? idVal : t.id;
  t.birds = Number(elBirds.value || t.birds);
  t.season = elSeasonRes ? elSeasonRes.value : (t.season || 'summer');
  const capVal = elCap.value === '' ? null : Number(elCap.value);
  t.cap = capVal;
  t.heater_on = !!elHeater.checked;
  t.unit = 'per_bird';
  saveTabs(tabs);
}

async function recalc() {
  readFormToTab();
  const t = tabs[active];
  const payload = {
    house: t.id,
    birds: t.birds,
    age_days: t.age_days,
    mode_id: t.season || 'summer',
    display_unit: t.unit,
    outside_t: (t.season === 'winter' ? -1 : (t.season === 'spring_autumn' ? 0 : 15)),
    heater_on: !!t.heater_on,
  };
  if (t.cap !== null && t.cap !== undefined && t.cap !== '') payload.user_max_m3h = t.cap;

  elCalc.disabled = true; elCalc.textContent = 'Считаем…';
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
    renderResult(data, t);
  } catch (e) {
    elResult.innerHTML = `<div class="danger">Ошибка запроса: ${String(e)}</div>`;
  } finally {
    elCalc.disabled = false; elCalc.textContent = 'Пересчитать';
  }
}

async function summary7() {
  readFormToTab();
  const t = tabs[active];
  const payload = {
    house: t.id,
    birds: t.birds,
    mode_id: (elSeasonRes ? elSeasonRes.value : (t.season || 'summer')),
    user_max_m3h: (t.cap === null || t.cap === undefined || t.cap === '') ? null : Number(t.cap),
    heater_on: !!t.heater_on,
    display_unit: t.unit,
  };
  elSum.disabled = true; elSum.textContent = 'Считаем…';
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
    elSummary.innerHTML = `<div class="danger">Ошибка запроса: ${String(e)}</div>`;
  } finally {
    elSum.disabled = false; elSum.textContent = 'Сводка 7 точек';
  }
}

function renderSummary(d) {
  const head = `<div class="kv"><span>Сезон</span><span>${d.mode_id}</span></div>
                <div class="kv"><span>Птичник/Птица</span><span>${d.house} / ${d.birds}</span></div>
                <div class="kv"><span>Макс. производительность</span><span>${d.user_max_m3h ?? '—'} м³/ч</span></div>`;
  if (elSeasonRes) elSeasonRes.value = d.mode_id;
  const mode = elView ? elView.value : 'total';
  const headerByMode = {
    total: ['Qmin, м³/ч', 'Qmax, м³/ч'],
    percent: ['Qmin, %', 'Qmax, %'],
    per_bird: ['Qmin, м³/ч/бр', 'Qmax, м³/ч/бр'],
    per_kg: ['Qmin, м³/ч/кг', 'Qmax, м³/ч/кг']
  };
  const headCols = headerByMode[mode] || headerByMode.total;
  const rows = d.rows.map(r => {
    let c1 = '—', c2 = '—';
    if (mode === 'total') {
      c1 = Math.round(r.q_min_m3h).toString();
      c2 = Math.round(r.q_max_m3h).toString();
    } else if (mode === 'percent') {
      c1 = (r.q_min_pct != null) ? (r.q_min_pct.toFixed(1) + '%') : '—';
      c2 = (r.q_max_pct != null) ? (r.q_max_pct.toFixed(1) + '%') : '—';
    } else if (mode === 'per_bird') {
      const be = r.birds_eff || d.birds; if (be > 0) { c1 = (r.q_min_m3h / be).toFixed(4); c2 = (r.q_max_m3h / be).toFixed(4); }
    } else if (mode === 'per_kg') {
      const be = r.birds_eff || d.birds; const wkg = (r.weight_g || 0)/1000.0; const totalKg = be*wkg; if (totalKg > 0) { c1 = (r.q_min_m3h/totalKg).toFixed(4); c2 = (r.q_max_m3h/totalKg).toFixed(4); }
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
        <th>День</th><th>Min Temp, °C</th><th>Вес, г</th>
        <th>${headCols[0]}</th><th>${headCols[1]}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderResult(d, t) {
  const cap = t.cap ? Number(t.cap) : null;
  const pct = (x) => cap && cap > 0 ? ((x / cap) * 100).toFixed(1) + '%' : '—';
  const weight = (typeof d.weight_used_g === 'number' && isFinite(d.weight_used_g)) ? d.weight_used_g.toFixed(0) : '—';
  const dayInfo = d.day_setpoints ? `<div class="kv"><span>Уставки дня</span><span>${d.day_setpoints.min_temp_c ?? '—'} °C, RH ${d.day_setpoints.rv_percent ?? '—'}%</span></div>` : '';

  elResult.innerHTML = `
    <div class="kv"><span>Возраст, день</span><span>${d.profile_day_resolved}</span></div>
    <div class="kv"><span>Вес, г</span><span>${weight}</span></div>
    <div class="kv big"><span>Qmin</span><span class="ok">${Math.round(d.q_min_m3h)} м³/ч</span></div>
    <div class="kv"><span>Qmin от мощности</span><span>${pct(d.q_min_m3h)}</span></div>
    <div class="kv big"><span>Qmax</span><span class="warn">${Math.round(d.q_max_m3h)} м³/ч</span></div>
    <div class="kv"><span>Qmax (номинал)</span><span>${Math.round(d.q_max_nominal_m3h)} м³/ч</span></div>
    <div class="kv"><span>Qmax от мощности</span><span>${pct(d.q_max_m3h)}</span></div>
    <div class="kv"><span>Ставки (на голову)</span><span>${d.rates.per_bird.min}…${d.rates.per_bird.max} м³/ч/бр</span></div>
    <div class="kv"><span>Ставки (на кг)</span><span>${d.rates.per_kg.min}…${d.rates.per_kg.max} м³/ч/кг</span></div>
    ${dayInfo}
  `;
}

elAddTab.onclick = () => {
  const last = tabs[tabs.length - 1]?.id || '0';
  const nextNum = parseInt(last, 10);
  const nextId = isNaN(nextNum) ? `${tabs.length + 1}` : String(nextNum + 1);
  tabs.push({ id: nextId, birds: 30000, age_days: 21, outside_t: 10, cap: null, unit: 'per_bird' });
  active = tabs.length - 1;
  saveTabs(tabs);
  renderTabs(); fillForm();
};
elDelTab.onclick = () => {
  const t = tabs[active];
  const name = t?.id ?? (active + 1);
  pendingDeleteIndex = active;
  if (elModal && elModalText) {
    elModalText.textContent = `Удалить птичник «${name}»? Это действие удалит локально сохранённые данные этой вкладки и не может быть отменено.`;
    elModal.classList.remove('hidden');
    // inline fallback styles (на случай кеша CSS)
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

function applyDelete(index){
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

if (elModalOk) elModalOk.addEventListener('click', ()=>{ applyDelete(pendingDeleteIndex); pendingDeleteIndex = null; elModal.classList.add('hidden'); elModal.removeAttribute('style'); const c = elModal.querySelector('.modal-card'); if (c){ c.removeAttribute('style'); } });
if (elModalCancel) elModalCancel.addEventListener('click', ()=>{ pendingDeleteIndex = null; elModal.classList.add('hidden'); elModal.removeAttribute('style'); const c = elModal.querySelector('.modal-card'); if (c){ c.removeAttribute('style'); } });
elSum.onclick = summary7;
const elViewCtl = document.getElementById('viewMode');
if (elViewCtl) {
  elViewCtl.addEventListener('change', ()=>{ if (lastSummary) renderSummary(lastSummary); });
}
const elSeasonCtl = document.getElementById('seasonResult');
if (elSeasonCtl) {
  elSeasonCtl.addEventListener('change', ()=>{ summary7(); });
}

renderTabs();
fillForm();
