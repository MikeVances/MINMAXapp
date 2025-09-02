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
const elSeason = document.getElementById('season');
const elCap = document.getElementById('cap');
const elHeater = document.getElementById('heater');
const elSum = document.getElementById('sumBtn');
const elResult = document.getElementById('result');
const elSummary = document.getElementById('summary');

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
  elSeason.value = t.season || 'summer';
  elCap.value = t.cap ?? '';
  elHeater.checked = !!t.heater_on;
  (document.querySelector(`input[name="unit"][value="${t.unit || 'per_bird'}"]`)||{}).checked = true;
}

function readFormToTab() {
  const t = tabs[active];
  const idVal = (elHouse.value || '').trim();
  t.id = idVal !== '' ? idVal : t.id;
  t.birds = Number(elBirds.value || t.birds);
  t.season = elSeason.value;
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
    mode_id: t.season || 'summer',
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
  const rows = d.rows.map(r => `
    <tr>
      <td>${r.day}</td>
      <td>${r.min_temp_c ?? '—'}</td>
      <td>${r.weight_g != null ? Math.round(r.weight_g) : '—'}</td>
      <td>${Math.round(r.q_min_m3h)}</td>
      <td>${r.q_min_pct != null ? (r.q_min_pct.toFixed(1) + '%') : '—'}</td>
      <td>${Math.round(r.q_max_m3h)}</td>
      <td>${r.q_max_pct != null ? (r.q_max_pct.toFixed(1) + '%') : '—'}</td>
    </tr>`).join('');
  elSummary.innerHTML = `${head}
    <table>
      <thead><tr>
        <th>День</th><th>Min Temp, °C</th><th>Вес, г</th>
        <th>Qmin, м³/ч</th><th>Qmin, %</th>
        <th>Qmax, м³/ч</th><th>Qmax, %</th>
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
  if (tabs.length <= 1) {
    // reset to single default tab
    tabs = [{ id: '1', birds: 30000, age_days: 21, outside_t: 10, cap: null, unit: 'per_bird' }];
    active = 0;
  } else {
    tabs.splice(active, 1);
    if (active >= tabs.length) active = tabs.length - 1;
  }
  saveTabs(tabs);
  renderTabs(); fillForm();
};
elSum.onclick = summary7;

renderTabs();
fillForm();
