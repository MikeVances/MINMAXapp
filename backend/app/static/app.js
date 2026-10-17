// ── UA badge: показывает результат калибровки теплопотерь для текущего корпуса ──
let _uaFetchController = null;

async function updateUaBadge(tabId) {
  const el = document.getElementById('uaBadge');
  if (!el) return;
  if (_uaFetchController) _uaFetchController.abort();
  _uaFetchController = new AbortController();
  try {
    const r = await fetch('./thermal/config', { signal: _uaFetchController.signal });
    if (!r.ok) { el.style.display = 'none'; return; }
    const cfg = await r.json();
    const ua  = cfg.calibration?.ua_coefficient;
    if (!ua || cfg.house_id !== String(tabId)) {
      el.style.display = 'none'; return;
    }
    // Корпус совпадает — показываем UA
    el.innerHTML = `🌡️ UA = <strong>${ua.toFixed(0)} ${t('cfg_ua_unit')}</strong> &nbsp;—&nbsp;
      <span class="muted">${t('ua_calibrated_lbl')}</span>
      &nbsp;<a href="./calculators.html" style="font-size:11px; opacity:.7;">${t('ua_recal_link')}</a>`;
    el.style.display = 'block';
  } catch (e) {
    if (e.name !== 'AbortError') el.style.display = 'none';
  }
}

// ── Simple in-memory + localStorage tabs for houses ──────────────────────────
const defaultTabs = [
  { id: '1', birds: 35000, age_days: 21, outside_t: 10, cap: 1000000 },
  { id: '2', birds: 32000, age_days: 21, outside_t: 25, cap: 800000 },
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
  // Хранилище может быть недоступно или переполнено — вкладки останутся в памяти страницы
  try { localStorage.setItem(storeKey, JSON.stringify(tabs)); } catch (e) { console.warn('saveTabs:', e); }
}

let tabs = loadTabs();
let active = 0;

const elTabs       = document.getElementById('tabs');
const elAddTab     = document.getElementById('addTab');
const elDelTab     = document.getElementById('delTab');
const elHouse      = document.getElementById('house');
const elBirds      = document.getElementById('birds');
const elCap        = document.getElementById('cap');
const elHeater     = document.getElementById('heater');
const elHouseLen       = document.getElementById('houseLength');
const elHouseWid       = document.getElementById('houseWidth');
const elHouseHgtWall   = document.getElementById('houseHeightWall');
const elHouseHgtRidge  = document.getElementById('houseHeightRidge');
const elNumFans        = document.getElementById('numFans');
const elFanCapM3h      = document.getElementById('fanCapM3h');
const elNumMinFans     = document.getElementById('numMinFans');
const elMinFanCapM3h   = document.getElementById('minFanCapM3h');
const elSum        = document.getElementById('sumBtn');

// modal elements
const elModal       = document.getElementById('modal');
const elModalText   = document.getElementById('modalText');
const elModalOk     = document.getElementById('modalOk');
const elModalCancel = document.getElementById('modalCancel');
let pendingDeleteIndex = null;

function renderTabs() {
  elTabs.innerHTML = '';
  tabs.forEach((tab, i) => {
    const b = document.createElement('button');
    b.className = 'tab' + (i === active ? ' active' : '');
    b.textContent = houseLabel(tab.id);
    b.onclick = () => { active = i; fillForm(); renderTabs(); };
    elTabs.appendChild(b);
  });
}

// Синхронизирует поле "cap" из num_fans × fan_cap_m3h и показывает подсказку
function syncCap() {
  const n = parseInt(elNumFans ? elNumFans.value : '', 10);
  const c = parseInt(elFanCapM3h ? elFanCapM3h.value : '', 10);
  const note = document.getElementById('capAutoNote');
  if (n > 0 && c > 0) {
    elCap.value = n * c;
    if (note) note.textContent = `= ${n} × ${c.toLocaleString(I18N.lang)} ${t('unit_m3h')}`;
  } else {
    if (note) note.textContent = '';
  }
}

if (elNumFans)   elNumFans.addEventListener('input', syncCap);
if (elFanCapM3h) elFanCapM3h.addEventListener('input', syncCap);

function fillForm() {
  const tab = tabs[active];
  elHouse.value = tab.id;
  elBirds.value = tab.birds;
  elCap.value = tab.cap ?? '';
  elHeater.checked = !!tab.heater_on;
  if (elHouseLen)      elHouseLen.value      = tab.length_m      ?? '';
  if (elHouseWid)      elHouseWid.value      = tab.width_m       ?? '';
  if (elHouseHgtWall)  elHouseHgtWall.value  = tab.height_wall_m ?? '';
  if (elHouseHgtRidge) elHouseHgtRidge.value = tab.height_ridge_m ?? '';
  if (elNumFans)       elNumFans.value       = tab.num_fans        ?? '';
  if (elFanCapM3h)     elFanCapM3h.value     = tab.fan_cap_m3h    ?? '';
  if (elNumMinFans)    elNumMinFans.value    = tab.num_min_fans    ?? '';
  if (elMinFanCapM3h)  elMinFanCapM3h.value  = tab.min_fan_cap_m3h ?? '';
  // Если заданы параметры вентиляторов — авто-вычислить cap и показать подсказку
  syncCap();
  // Показать UA badge если корпус откалиброван
  updateUaBadge(tab.id);
}

function readFormToTab() {
  const tab = tabs[active];
  const idVal = (elHouse.value || '').trim();
  tab.id       = idVal !== '' ? idVal : tab.id;
  tab.birds    = Number(elBirds.value || tab.birds);
  const capVal = elCap.value === '' ? null : Number(elCap.value);
  tab.cap      = capVal;
  tab.heater_on = !!elHeater.checked;
  // Building dimensions (used by audit / heat-loss calibration)
  tab.length_m       = elHouseLen      && elHouseLen.value      !== '' ? Number(elHouseLen.value)      : (tab.length_m       ?? null);
  tab.width_m        = elHouseWid      && elHouseWid.value      !== '' ? Number(elHouseWid.value)       : (tab.width_m        ?? null);
  tab.height_wall_m  = elHouseHgtWall  && elHouseHgtWall.value  !== '' ? Number(elHouseHgtWall.value)  : (tab.height_wall_m  ?? null);
  tab.height_ridge_m = elHouseHgtRidge && elHouseHgtRidge.value !== '' ? Number(elHouseHgtRidge.value) : (tab.height_ridge_m ?? null);
  tab.num_fans        = elNumFans      && elNumFans.value      !== '' ? Number(elNumFans.value)      : (tab.num_fans        ?? null);
  tab.fan_cap_m3h     = elFanCapM3h    && elFanCapM3h.value    !== '' ? Number(elFanCapM3h.value)    : (tab.fan_cap_m3h     ?? null);
  tab.num_min_fans    = elNumMinFans   && elNumMinFans.value   !== '' ? Number(elNumMinFans.value)   : (tab.num_min_fans    ?? null);
  tab.min_fan_cap_m3h = elMinFanCapM3h && elMinFanCapM3h.value !== '' ? Number(elMinFanCapM3h.value) : (tab.min_fan_cap_m3h ?? null);
  saveTabs(tabs);
}


const MAX_HOUSES = 30; // разумный предел для одной фермы

elAddTab.onclick = () => {
  if (tabs.length >= MAX_HOUSES) {
    // Не даём накапливать сотни корпусов и ломать вёрстку
    alert(t('err_max_houses', { max: MAX_HOUSES }));
    return;
  }
  // Новый корпус получает имя на языке интерфейса («New house 3» / «Новое помещение 3»).
  // Номер подбираем так, чтобы имя не совпало с существующим: id — ключ данных корпуса
  const existing = new Set(tabs.map(x => String(x.id)));
  let n = tabs.length + 1, nextId;
  do { nextId = t('house_new_name', { n: n++ }); } while (existing.has(nextId));
  tabs.push({ id: nextId, birds: 30000, age_days: 21, outside_t: 10, cap: null });
  active = tabs.length - 1;
  saveTabs(tabs);
  renderTabs(); fillForm();
};

elDelTab.onclick = () => {
  const tab = tabs[active];
  const name = houseLabel(tab?.id ?? (active + 1));
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
    tabs = [{ id: '1', birds: 30000, age_days: 21, outside_t: 10, cap: null }];
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

// Кнопка "Сохранить данные" — записывает форму в localStorage и показывает подтверждение
elSum.onclick = () => {
  readFormToTab();
  const orig = elSum.textContent;
  elSum.textContent = t('status_saved');
  setTimeout(() => { elSum.textContent = orig; }, 1500);
};

renderTabs();
fillForm();

// Смена языка: data-i18n переводит i18n.js, а собранное здесь в JS — перерисовываем сами
document.addEventListener('i18n:change', () => {
  renderTabs();
  syncCap();
  updateUaBadge(tabs[active].id);
});
