async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw await apiError(r);   // код ошибки сервера → текст на языке интерфейса
  return r.json();
}

const elConfigSection = document.getElementById('configSection');

let cfg = {
  total_mortality_pct: 4.0, cycle_days: 42, v_tunnel_ms: 2.5, safety_factor_qmin: 1.5,
  tunnel_min_day: 14, tunnel_min_temp_c: 18.0,
};

function renderConfig() {
  elConfigSection.innerHTML = `
    <div class="card" style="margin-bottom:16px;">
      <h2>${t('farm_params_h2')}</h2>
      <div style="display:grid; gap:10px;">
        <div class="kv"><span>${t('cycle_days_lbl')}</span><span><input id="cycle_days" type="number" step="1" min="21" max="56" value="${cfg.cycle_days ?? 42}"> ${t('unit_days')}</span></div>
        <div class="kv"><span>${t('mortality_lbl')}</span><span><input id="mort_total" type="number" step="0.01" min="0" max="100" value="${(100 - (cfg.total_mortality_pct ?? 4)).toFixed(2)}"> %</span></div>
      </div>

      <hr style="border:none;border-top:1px solid #26272c;margin:14px 0;">
      <div style="font-weight:600;font-size:13px;color:#e6e7eb;margin-bottom:10px;">${t('cigr_section_h')}</div>
      <div style="display:grid;gap:10px;">
        <div class="kv"><span>${t('v_tunnel_lbl')}</span><span><input id="v_tunnel" type="number" step="0.1" min="0.5" max="5.0" value="${cfg.v_tunnel_ms ?? 2.5}"> ${t('unit_ms')}</span></div>
        <div class="kv"><span>${t('safety_factor_lbl')}</span><span><input id="safety_factor" type="number" step="0.1" min="1.0" max="3.0" value="${cfg.safety_factor_qmin ?? 1.5}"></span></div>
        <div class="kv"><span>${t('tunnel_min_day_lbl')}</span><span><input id="tunnel_min_day" type="number" step="1" min="1" max="42" value="${cfg.tunnel_min_day ?? 14}"> ${t('unit_days')}</span></div>
        <div class="kv"><span>${t('tunnel_min_temp_lbl')}</span><span><input id="tunnel_min_temp" type="number" step="0.5" min="0" max="35" value="${cfg.tunnel_min_temp_c ?? 18.0}"> ${t('unit_celsius')}</span></div>
      </div>
      <div style="margin-top:14px;display:flex;gap:10px;align-items:center;">
        <button id="saveBtn" class="btn">${t('btn_save')}</button>
        <span id="saveStatus" class="muted" style="font-size:12px;"></span>
      </div>
    </div>`;

  // Пустое или нечисловое поле НЕ меняет настройку. Раньше Number(v || 0) превращал
  // стёртую «сохранность» в 0 % живых — то есть 100 % падежа
  const bindNumber = (id, apply) => {
    document.getElementById(id).addEventListener('change', e => {
      const raw = e.target.value.trim();
      const val = Number(raw);
      if (raw !== '' && Number.isFinite(val)) apply(val);
    });
  };
  bindNumber('cycle_days',      v => { cfg.cycle_days = v; });
  bindNumber('mort_total',      v => { cfg.total_mortality_pct = 100 - v; });
  bindNumber('v_tunnel',        v => { cfg.v_tunnel_ms = v; });
  bindNumber('safety_factor',   v => { cfg.safety_factor_qmin = v; });
  bindNumber('tunnel_min_day',  v => { cfg.tunnel_min_day = v; });
  bindNumber('tunnel_min_temp', v => { cfg.tunnel_min_temp_c = v; });

  document.getElementById('saveBtn').addEventListener('click', async () => {
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

async function loadAll() {
  try {
    cfg = await fetchJSON('./settings/app-config');
    renderConfig();
  } catch(e) {
    console.error('Settings load error:', e);
  }
}

loadAll();
