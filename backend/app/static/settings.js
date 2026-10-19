// fetchJSON — общий, из ui.js (ошибка сервера → текст на языке интерфейса)

const elConfigSection = document.getElementById('configSection');

let cfg = {
  total_mortality_pct: 4.0, cycle_days: 42, v_tunnel_ms: 2.5, safety_factor_qmin: 1.5,
  tunnel_min_day: 14, tunnel_min_temp_c: 18.0,
};

function renderConfig() {
  elConfigSection.innerHTML = `
    <div class="card mb-16">
      <h2>${t('farm_params_h2')}</h2>
      <!-- label, а не div: подпись становится именем поля для экранного диктора и
           касание по подписи ставит курсор в поле -->
      <div class="d-grid gap-10">
        <label class="kv m-0"><span>${t('cycle_days_lbl')}</span><span><input id="cycle_days" type="text" data-num data-int inputmode="numeric" data-min="21" data-max="56" value="${cfg.cycle_days ?? 42}"> ${t('unit_days')}</span></label>
        <label class="kv m-0"><span>${t('mortality_lbl')}</span><span><input id="mort_total" type="text" data-num inputmode="decimal" data-min="0" data-max="100" value="${(100 - (cfg.total_mortality_pct ?? 4)).toFixed(2)}"> %</span></label>
        <label class="kv m-0"><span>${t('altitude_lbl')}</span><span><input id="altitude" type="text" data-num inputmode="decimal" data-min="0" data-max="4000" value="${cfg.altitude_m ?? 0}"> ${t('unit_m')}</span></label>
      </div>

      <hr class="divider my-14 mx-0">
      <div class="fw-600 fs-13 c-text mb-10">${t('cigr_section_h')}</div>
      <div class="d-grid gap-10">
        <label class="kv m-0"><span>${t('v_tunnel_lbl')}</span><span><input id="v_tunnel" type="text" data-num inputmode="decimal" data-min="0.5" data-max="5.0" value="${cfg.v_tunnel_ms ?? 2.5}"> ${t('unit_ms')}</span></label>
        <label class="kv m-0"><span>${t('safety_factor_lbl')}</span><span><input id="safety_factor" type="text" data-num inputmode="decimal" data-min="1.0" data-max="3.0" value="${cfg.safety_factor_qmin ?? 1.5}"></span></label>
        <label class="kv m-0"><span>${t('tunnel_min_day_lbl')}</span><span><input id="tunnel_min_day" type="text" data-num data-int inputmode="numeric" data-min="1" data-max="42" value="${cfg.tunnel_min_day ?? 14}"> ${t('unit_days')}</span></label>
        <label class="kv m-0"><span>${t('tunnel_min_temp_lbl')}</span><span><input id="tunnel_min_temp" type="text" data-num inputmode="decimal" data-min="0" data-max="35" value="${cfg.tunnel_min_temp_c ?? 18.0}"> ${t('unit_celsius')}</span></label>
      </div>
      <div class="mt-14 d-flex gap-10 ai-center">
        <button id="saveBtn" class="btn">${t('btn_save')}</button>
        <span id="saveStatus" class="muted fs-12" role="status"></span>
      </div>
    </div>

    <!-- Расчётные наружные условия площадки (ASHRAE гл. 14) по ERA5 / Open-Meteo -->
    <div class="card mb-16">
      <h2>${t('climate_h2')}</h2>
      <p class="hint mt-0">${t('climate_desc')}</p>
      <div class="d-grid gap-10">
        <label class="kv m-0"><span>${t('latitude_lbl')}</span><span><input id="latitude" type="text" data-num inputmode="decimal" data-min="-90" data-max="90" value="${cfg.latitude ?? ''}" placeholder="55.75"></span></label>
        <label class="kv m-0"><span>${t('longitude_lbl')}</span><span><input id="longitude" type="text" data-num inputmode="decimal" data-min="-180" data-max="180" value="${cfg.longitude ?? ''}" placeholder="37.62"></span></label>
      </div>
      <div class="mt-14 d-flex gap-10 ai-center wrap">
        <button id="climateBtn" class="btn btn-secondary">${t('climate_btn')}</button>
        <span id="climateStatus" class="muted fs-12" role="status"></span>
      </div>
      ${cfg.design_cool_db_c != null ? `
      <div class="d-grid gap-6 mt-14">
        <div class="kv"><span>${t('design_heat_lbl')}</span><span>${fmtNum(cfg.design_heat_c, 1)} °C</span></div>
        <div class="kv"><span>${t('design_cool_lbl')}</span><span>${fmtNum(cfg.design_cool_db_c, 1)} °C · ${fmtNum(cfg.design_cool_rh_pct, 0)} % · T_wb ${fmtNum(cfg.design_cool_mcwb_c, 1)} °C</span></div>
        <div class="kv"><span>${t('design_evap_lbl')}</span><span>${fmtNum(cfg.design_evap_wb_c, 1)} °C</span></div>
      </div>
      <p class="hint mt-8 mb-0">${t('climate_license', { source: escapeHtml(cfg.design_source || '') })}</p>` : ''}
    </div>

    <!-- Резервная копия: тестовая площадка теряет данные при деплое — их можно унести -->
    <div class="card mb-16">
      <h2>${t('backup_h2')}</h2>
      <p class="hint mt-0">${t('backup_desc')}</p>
      <div class="d-flex gap-10 ai-center wrap">
        <button id="backupDownload" class="btn btn-secondary">${t('backup_download')}</button>
        <label class="btn btn-secondary m-0">${t('backup_restore')}
          <input id="backupFile" type="file" accept="application/json,.json" hidden>
        </label>
        <span id="backupStatus" class="muted fs-12" role="status"></span>
      </div>
    </div>`;

  // Пустое, нечисловое или вне диапазона поле НЕ меняет настройку (оно подсвечено,
  // numfield.js). Раньше Number(v || 0) превращал стёртую «сохранность» в 0 % живых —
  // то есть 100 % падежа, а «97,5» (с запятой) не принималось вовсе
  const bindNumber = (id, apply) => {
    document.getElementById(id).addEventListener('change', e => {
      const val = NumField.value(e.target);
      if (val !== null && !NumField.problem(e.target)) apply(val);
    });
  };
  const NUMBER_IDS = ['cycle_days', 'mort_total', 'altitude', 'v_tunnel', 'safety_factor', 'tunnel_min_day', 'tunnel_min_temp'];
  bindNumber('cycle_days',      v => { cfg.cycle_days = v; });
  bindNumber('mort_total',      v => { cfg.total_mortality_pct = 100 - v; });
  // Высота площадки: на 1000 м воздух на 11 % реже — меняет влагу, тепло и UA
  bindNumber('altitude',        v => { cfg.altitude_m = v; });
  bindNumber('v_tunnel',        v => { cfg.v_tunnel_ms = v; });
  bindNumber('safety_factor',   v => { cfg.safety_factor_qmin = v; });
  bindNumber('tunnel_min_day',  v => { cfg.tunnel_min_day = v; });
  bindNumber('tunnel_min_temp', v => { cfg.tunnel_min_temp_c = v; });

  // ── Резервная копия ──
  const HOUSES_KEY = 'vent_mvp_tabs_v1';   // список корпусов главной (живёт в браузере)
  const backupSt = document.getElementById('backupStatus');
  document.getElementById('backupDownload').addEventListener('click', async () => {
    try {
      const data = await fetchJSON('./backup');
      try { data.houses = JSON.parse(localStorage.getItem(HOUSES_KEY) || 'null'); } catch (e) { data.houses = null; }
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'minmax-farm-' + new Date().toISOString().slice(0, 10) + '.json';
      a.click();
      URL.revokeObjectURL(a.href);
      setStatus(backupSt, () => t('backup_saved'), 'ok');
    } catch (e) {
      const msg = e.message || String(e);
      setStatus(backupSt, () => t('err_prefix') + msg, 'danger');
    }
  });
  document.getElementById('backupFile').addEventListener('change', async ev => {
    const file = ev.target.files[0];
    ev.target.value = '';                       // тот же файл можно выбрать ещё раз
    if (!file || !window.confirm(t('backup_confirm'))) return;
    try {
      const data = JSON.parse(await file.text());
      const res = await fetchJSON('./backup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
      });
      // Сервер принял — теперь и список корпусов этого браузера
      if (Array.isArray(data.houses) && data.houses.length) {
        try { localStorage.setItem(HOUSES_KEY, JSON.stringify(data.houses)); } catch (e) { /* хранилище недоступно */ }
      }
      cfg = await fetchJSON('./settings/app-config');
      renderConfig();
      const n = Array.isArray(data.houses) ? data.houses.length : 0;
      setStatus(document.getElementById('backupStatus'), () => t('backup_restored',
        { profiles: res.profiles, houses: n, thermal: res.thermal_houses }), 'ok');
    } catch (e) {
      const msg = e instanceof SyntaxError ? t('backup_not_json') : (e.message || String(e));
      setStatus(document.getElementById('backupStatus'), () => t('err_prefix') + msg, 'danger');
    }
  });

  // Расчётные условия: ~20 с — 10 лет часовых данных с Open-Meteo (по кнопке, не сами)
  document.getElementById('climateBtn').addEventListener('click', async () => {
    if (!NumField.validate(['latitude', 'longitude'])) return;
    const lat = NumField.value('latitude'), lon = NumField.value('longitude');
    const st = document.getElementById('climateStatus');
    if (lat === null || lon === null) { setStatus(st, () => t('climate_need_coords'), 'danger'); return; }
    const btn = document.getElementById('climateBtn');
    btn.disabled = true;
    setStatus(st, () => t('climate_loading'));
    try {
      cfg = await fetchJSON('./settings/design-climate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude: lat, longitude: lon }),
      });
      renderConfig();
    } catch (e) {
      const msg = e.message || String(e);
      setStatus(st, () => t('err_prefix') + msg, 'danger');
      btn.disabled = false;
    }
  });

  document.getElementById('saveBtn').addEventListener('click', async () => {
    if (!NumField.validate(NUMBER_IDS)) return;
    const btn = document.getElementById('saveBtn');
    const st  = document.getElementById('saveStatus');
    btn.disabled = true;
    st.textContent = t('status_saving');
    try {
      await fetchJSON('./settings/app-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      });
      st.textContent = t('status_saved');
      setTimeout(() => { st.textContent = ''; }, 3000);
    } catch(e) {
      st.textContent = t('err_prefix') + (e.message || e);
    } finally {
      btn.disabled = false;
    }
  });
}

let configLoaded = false;

async function loadAll() {
  try {
    cfg = await fetchJSON('./settings/app-config');
    configLoaded = true;
    renderConfig();
  } catch(e) {
    console.error('Settings load error:', e);
  }
}

loadAll();

// Смена языка: форма собрана в JS из словаря — перерисовать. Правки пользователя
// уже лежат в cfg (обработчики change), поэтому ничего не теряется
document.addEventListener('i18n:change', () => { if (configLoaded) renderConfig(); });
