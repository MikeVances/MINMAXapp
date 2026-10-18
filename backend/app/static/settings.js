async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw await apiError(r, opts && opts.body);   // код ошибки сервера → текст на языке интерфейса
  return r.json();
}

const elConfigSection = document.getElementById('configSection');

let cfg = {
  total_mortality_pct: 4.0, cycle_days: 42, v_tunnel_ms: 2.5, safety_factor_qmin: 1.5,
  tunnel_min_day: 14, tunnel_min_temp_c: 18.0,
};

function renderConfig() {
  elConfigSection.innerHTML = `
    <div class="card mb-16">
      <h2>${t('farm_params_h2')}</h2>
      <div class="d-grid gap-10">
        <div class="kv"><span>${t('cycle_days_lbl')}</span><span><input id="cycle_days" type="text" data-num data-int inputmode="numeric" data-min="21" data-max="56" value="${cfg.cycle_days ?? 42}"> ${t('unit_days')}</span></div>
        <div class="kv"><span>${t('mortality_lbl')}</span><span><input id="mort_total" type="text" data-num inputmode="decimal" data-min="0" data-max="100" value="${(100 - (cfg.total_mortality_pct ?? 4)).toFixed(2)}"> %</span></div>
      </div>

      <hr class="divider my-14 mx-0">
      <div class="fw-600 fs-13 c-text mb-10">${t('cigr_section_h')}</div>
      <div class="d-grid gap-10">
        <div class="kv"><span>${t('v_tunnel_lbl')}</span><span><input id="v_tunnel" type="text" data-num inputmode="decimal" data-min="0.5" data-max="5.0" value="${cfg.v_tunnel_ms ?? 2.5}"> ${t('unit_ms')}</span></div>
        <div class="kv"><span>${t('safety_factor_lbl')}</span><span><input id="safety_factor" type="text" data-num inputmode="decimal" data-min="1.0" data-max="3.0" value="${cfg.safety_factor_qmin ?? 1.5}"></span></div>
        <div class="kv"><span>${t('tunnel_min_day_lbl')}</span><span><input id="tunnel_min_day" type="text" data-num data-int inputmode="numeric" data-min="1" data-max="42" value="${cfg.tunnel_min_day ?? 14}"> ${t('unit_days')}</span></div>
        <div class="kv"><span>${t('tunnel_min_temp_lbl')}</span><span><input id="tunnel_min_temp" type="text" data-num inputmode="decimal" data-min="0" data-max="35" value="${cfg.tunnel_min_temp_c ?? 18.0}"> ${t('unit_celsius')}</span></div>
      </div>
      <div class="mt-14 d-flex gap-10 ai-center">
        <button id="saveBtn" class="btn">${t('btn_save')}</button>
        <span id="saveStatus" class="muted fs-12"></span>
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
  const NUMBER_IDS = ['cycle_days', 'mort_total', 'v_tunnel', 'safety_factor', 'tunnel_min_day', 'tunnel_min_temp'];
  bindNumber('cycle_days',      v => { cfg.cycle_days = v; });
  bindNumber('mort_total',      v => { cfg.total_mortality_pct = 100 - v; });
  bindNumber('v_tunnel',        v => { cfg.v_tunnel_ms = v; });
  bindNumber('safety_factor',   v => { cfg.safety_factor_qmin = v; });
  bindNumber('tunnel_min_day',  v => { cfg.tunnel_min_day = v; });
  bindNumber('tunnel_min_temp', v => { cfg.tunnel_min_temp_c = v; });

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
