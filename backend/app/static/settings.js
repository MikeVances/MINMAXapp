async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

const elConfigSection = document.getElementById('configSection');

let cfg = {
  total_mortality_pct: 4.0, min_floor_0_7: 0.15, min_floor_7_14: 0.25,
  cycle_days: 42, n_birds_initial: 30000, v_tunnel_ms: 2.5, safety_factor_qmin: 1.5,
  tunnel_min_day: 14, tunnel_min_temp_c: 18.0,
};

// Читаем поголовье из localStorage главной страницы тихо
function readBirdsFromStorage() {
  try {
    const tabs = JSON.parse(localStorage.getItem('vent_mvp_tabs_v1') || '[]');
    const first = tabs.find(tab => tab.birds > 0);
    return first ? Number(first.birds) : null;
  } catch(e) {
    return null;
  }
}

function renderConfig() {
  const birdsFromHouse = readBirdsFromStorage();
  if (birdsFromHouse) cfg.n_birds_initial = birdsFromHouse;

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

  document.getElementById('cycle_days').addEventListener('change',
    e => { cfg.cycle_days = Number(e.target.value || 42); });
  document.getElementById('mort_total').addEventListener('change',
    e => { cfg.total_mortality_pct = 100 - Number(e.target.value || 0); });
  document.getElementById('v_tunnel').addEventListener('change',
    e => { cfg.v_tunnel_ms = Number(e.target.value || 2.5); });
  document.getElementById('safety_factor').addEventListener('change',
    e => { cfg.safety_factor_qmin = Number(e.target.value || 1.5); });
  document.getElementById('tunnel_min_day').addEventListener('change',
    e => { cfg.tunnel_min_day = Number(e.target.value || 14); });
  document.getElementById('tunnel_min_temp').addEventListener('change',
    e => { cfg.tunnel_min_temp_c = Number(e.target.value || 18.0); });

  document.getElementById('saveBtn').addEventListener('click', async () => {
    const btn = document.getElementById('saveBtn');
    const st  = document.getElementById('saveStatus');
    btn.disabled = true;
    st.textContent = t('status_saving');
    try {
      await fetchJSON('/settings/app-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      });
      st.textContent = t('status_saved');
      setTimeout(() => { st.textContent = ''; }, 3000);
    } catch(e) {
      st.textContent = t('err_prefix') + String(e);
    } finally {
      btn.disabled = false;
    }
  });
}

async function loadAll() {
  try {
    cfg = await fetchJSON('/settings/app-config');
    renderConfig();
  } catch(e) {
    console.error('Settings load error:', e);
  }
}

loadAll();
