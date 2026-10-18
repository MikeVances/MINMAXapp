// ── UA badge: показывает результат калибровки теплопотерь для текущего корпуса ──
let _uaFetchController = null;

async function updateUaBadge(tabId) {
  const el = document.getElementById('uaBadge');
  if (!el) return;
  if (_uaFetchController) _uaFetchController.abort();
  _uaFetchController = new AbortController();
  try {
    // Теплотехника хранится по корпусам — запрашиваем запись этого корпуса
    const r = await fetch('./thermal/config?house_id=' + encodeURIComponent(String(tabId)),
                          { signal: _uaFetchController.signal });
    if (!r.ok) { el.hidden = true; return; }
    const cfg = await r.json();
    const ua  = cfg.calibration?.ua_coefficient;
    // Неправдоподобная калибровка в расчёт не идёт — и бейдж её не показывает
    if (!ua || cfg.house_id !== String(tabId) || cfg.calibration_problem) {
      el.hidden = true; return;
    }
    // Корпус совпадает — показываем UA
    el.innerHTML = `🌡️ UA = <strong>${fmtNum(ua, 0)} ${t('cfg_ua_unit')}</strong> &nbsp;—&nbsp;
      <span class="muted">${t('ua_calibrated_lbl')}</span>
      &nbsp;<a href="./calculators.html" class="fs-11 op-70">${t('ua_recal_link')}</a>`;
    el.hidden = false;
  } catch (e) {
    if (e.name !== 'AbortError') el.hidden = true;
  }
}

// ── Simple in-memory + localStorage tabs for houses ──────────────────────────
const defaultTabs = [
  { id: '1', birds: 35000, age_days: 21, cap: 1000000 },
  { id: '2', birds: 32000, age_days: 21, cap: 800000 },
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
// Первый вход: примерные корпуса сразу сохраняются. Иначе главная показывала
// «Птичник 1», а калькуляторы (читают только сохранённое) — «нет корпусов», и
// «Рассчитать профиль» там молча ничего не делал
try { if (!localStorage.getItem(storeKey)) saveTabs(tabs); } catch (e) { /* хранилище недоступно */ }

const elTabs       = document.getElementById('tabs');
const elAddTab     = document.getElementById('addTab');
const elTabsStatus = document.getElementById('tabsStatus');
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
const elForm       = document.getElementById('calcContent');

// Числовые поля формы корпуса — их проверяет «Сохранить» и автосохранение
const NUMBER_IDS = ['birds', 'cap', 'houseLength', 'houseWidth', 'houseHeightWall',
                    'houseHeightRidge', 'numFans', 'fanCapM3h', 'numMinFans', 'minFanCapM3h'];

// Форма изменена и ещё не записана во вкладку. Раньше переключение вкладки
// молча перезаписывало ввод (20 000 голов возвращались в 35 000), а калькуляторы
// читают корпуса из localStorage — несохранённая правка там не видна (аудит 2026-10-18).
let formDirty = false;
if (elForm) {
  elForm.addEventListener('input',  () => { formDirty = true; });
  elForm.addEventListener('change', () => { formDirty = true; });
}

// Форма верна — без побочных эффектов (без фокуса и подсказок): для beforeunload
function formValid() {
  return NUMBER_IDS.every(id => { const el = document.getElementById(id); return !el || !NumField.problem(el); });
}

// Перед уходом с текущей вкладки: верные правки сохраняем сами, неверные —
// не теряем, а показываем ошибку у поля и остаёмся. true — можно уходить.
function commitBeforeLeaving() {
  if (!formDirty) return true;
  if (!NumField.validate(NUMBER_IDS)) return false;
  readFormToTab();
  return true;
}

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
    b.onclick = () => {
      if (i === active || !commitBeforeLeaving()) return;
      active = i; fillForm(); renderTabs();
    };
    elTabs.appendChild(b);
  });
  Tabs.sync(elTabs);
}
Tabs.init(elTabs);

// Синхронизирует поле "cap" из num_fans × fan_cap_m3h и показывает подсказку
function syncCap() {
  // parseInt("25 000") давал 25 — суммарная производительность занижалась в тысячу раз
  const n = elNumFans   ? NumField.value(elNumFans)   : null;
  const c = elFanCapM3h ? NumField.value(elFanCapM3h) : null;
  const note = document.getElementById('capAutoNote');
  if (n > 0 && c > 0) {
    elCap.value = n * c;
    if (note) note.textContent = `= ${fmtNum(n)} × ${fmtNum(c)} ${t('unit_m3h')}`;
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
  // Подсветка ошибок прошлой вкладки к этой не относится — пересобрать по новым значениям
  NUMBER_IDS.forEach(id => { const el = document.getElementById(id); if (el) NumField.check(el); });
  formDirty = false;
}

function readFormToTab() {
  const tab = tabs[active];
  const idVal = (elHouse.value || '').trim();
  const oldId = tab.id;
  tab.id       = idVal !== '' ? idVal : tab.id;
  if (String(oldId) !== String(tab.id)) moveHouseThermal(String(oldId), String(tab.id));
  // Число из поля для хранилища; пустое поле → ifEmpty. Неразобранное сюда не
  // доходит: кнопка «Сохранить» сначала проверяет форму (NumField.validate).
  // Раньше Number("12,5") = NaN уходил в localStorage как null — размер пропадал молча.
  const read = (el, ifEmpty) => {
    const v = el ? NumField.value(el) : null;
    return v === null || Number.isNaN(v) ? ifEmpty : v;
  };
  tab.birds    = read(elBirds, tab.birds);   // поле обязательное (required) — пустым сюда не доходит
  tab.cap      = read(elCap, null);          // пусто = «не знаю максимум»
  tab.heater_on = !!elHeater.checked;
  // Размеры и вентиляторы: пустое поле = «не задано». Раньше пустое молча брало
  // прежнее значение, и ошибочно введённую длину нельзя было стереть
  tab.length_m        = read(elHouseLen,      null);
  tab.width_m         = read(elHouseWid,      null);
  tab.height_wall_m   = read(elHouseHgtWall,  null);
  tab.height_ridge_m  = read(elHouseHgtRidge, null);
  tab.num_fans        = read(elNumFans,       null);
  tab.fan_cap_m3h     = read(elFanCapM3h,     null);
  tab.num_min_fans    = read(elNumMinFans,    null);
  tab.min_fan_cap_m3h = read(elMinFanCapM3h,  null);
  saveTabs(tabs);
  formDirty = false;
}


// Корпус переименован: его калибровка и горелки лежат на сервере под старым id
// (список корпусов — здесь, в браузере). Без переноса они осиротели бы и перестали
// применяться к корпусу. Ошибку показываем, но имя в браузере не откатываем.
async function moveHouseThermal(oldId, newId) {
  try {
    const r = await fetch('./thermal/rename-house', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_house_id: oldId, new_house_id: newId }),
    });
    if (!r.ok) {
      const err = await apiError(r);
      setStatus(elTabsStatus, () => err.message, 'danger');
    }
  } catch (e) { /* сеть: запись останется под старым именем — как было до переноса */ }
}

const MAX_HOUSES = 30; // разумный предел для одной фермы

elAddTab.onclick = () => {
  if (!commitBeforeLeaving()) return;
  if (tabs.length >= MAX_HOUSES) {
    // Не даём накапливать сотни корпусов и ломать вёрстку
    setStatus(elTabsStatus, () => t('err_max_houses', { max: MAX_HOUSES }), 'danger');
    return;
  }
  setStatus(elTabsStatus, null);
  // Новый корпус получает имя на языке интерфейса («New house 3» / «Новое помещение 3»).
  // Номер подбираем так, чтобы имя не совпало с существующим: id — ключ данных корпуса
  const existing = new Set(tabs.map(x => String(x.id)));
  let n = tabs.length + 1, nextId;
  do { nextId = t('house_new_name', { n: n++ }); } while (existing.has(nextId));
  tabs.push({ id: nextId, birds: 30000, age_days: 21, cap: null });
  active = tabs.length - 1;
  saveTabs(tabs);
  renderTabs(); fillForm();
};

elDelTab.onclick = () => {
  setStatus(elTabsStatus, null);   // после удаления лимит уже не достигнут
  const tab = tabs[active];
  const name = houseLabel(tab?.id ?? (active + 1));
  pendingDeleteIndex = active;
  if (elModal && elModalText) {
    elModalText.textContent = t('modal_remove_txt', { name });
    // Фокус — на «Отмена»: удаление необратимо, случайный Enter не должен удалять
    Dialog.open(elModal, elModalCancel, cancelDelete);
  }
};

function applyDelete(index) {
  if (index == null) return;
  if (tabs.length <= 1) {
    tabs = [{ id: '1', birds: 30000, age_days: 21, cap: null }];
    active = 0;
  } else {
    tabs.splice(index, 1);
    if (active >= tabs.length) active = tabs.length - 1;
  }
  saveTabs(tabs);
  renderTabs(); fillForm();
}

function cancelDelete() {
  pendingDeleteIndex = null;
  Dialog.close(elModal);
}
if (elModalOk) elModalOk.addEventListener('click', () => {
  applyDelete(pendingDeleteIndex);
  pendingDeleteIndex = null;
  Dialog.close(elModal);
});
if (elModalCancel) elModalCancel.addEventListener('click', cancelDelete);

// Кнопка "Сохранить данные" — записывает форму в localStorage и показывает подтверждение
elSum.onclick = () => {
  // Неверное поле — фокус и подсказка у него, а не «Сохранено» с потерянным значением
  if (!NumField.validate(NUMBER_IDS)) return;
  readFormToTab();
  const orig = elSum.textContent;
  elSum.textContent = t('status_saved');
  setTimeout(() => { elSum.textContent = orig; }, 1500);
};

renderTabs();
fillForm();

// Уход со страницы (ссылка на калькуляторы, закрытие вкладки): верные правки
// сохраняем сами — запись в localStorage синхронная и успевает; неверные
// сохранить нельзя — просим браузер переспросить, а не теряем молча
window.addEventListener('beforeunload', e => {
  if (!formDirty) return;
  if (formValid()) { readFormToTab(); return; }
  e.preventDefault();
  e.returnValue = '';
});

// Смена языка: data-i18n переводит i18n.js, а собранное здесь в JS — перерисовываем сами
document.addEventListener('i18n:change', () => {
  renderTabs();
  syncCap();
  updateUaBadge(tabs[active].id);
});
