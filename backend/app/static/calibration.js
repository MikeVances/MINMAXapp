// Calibration page logic

const elLength   = document.getElementById('length');
const elWidth    = document.getElementById('width');
const elHeight   = document.getElementById('height');
const elVolumeDisplay = document.getElementById('volumeDisplay');
const elAreaDisplay   = document.getElementById('areaDisplay');
const elSaveBuildingBtn = document.getElementById('saveBuildingBtn');
const elBuildingStatus  = document.getElementById('buildingStatus');

const elHeaterType    = document.getElementById('heaterType');
const elHeaterPower   = document.getElementById('heaterPower');
const elGasInfo       = document.getElementById('gasInfo');
const elSaveHeaterBtn = document.getElementById('saveHeaterBtn');
const elHeaterStatus  = document.getElementById('heaterStatus');

const elTInitial    = document.getElementById('tInitial');
const elTFinal      = document.getElementById('tFinal');
const elTOutside    = document.getElementById('tOutside');
const elTimeMinutes = document.getElementById('timeMinutes');
const elCalculateBtn      = document.getElementById('calculateBtn');
const elSaveCalibrationBtn = document.getElementById('saveCalibrationBtn');
const elCalibrationResult  = document.getElementById('calibrationResult');

const elTInsideTarget     = document.getElementById('tInsideTarget');
const elTOutsideAnalysis  = document.getElementById('tOutsideAnalysis');
const elAnalyzeBtn        = document.getElementById('analyzeBtn');
const elAnalysisResult    = document.getElementById('analysisResult');

const elCurrentConfig = document.getElementById('currentConfig');

let calculatedUA = null;

// Update volume and area display
function updateDimensionsDisplay() {
  const l = parseFloat(elLength.value) || 0;
  const w = parseFloat(elWidth.value)  || 0;
  const h = parseFloat(elHeight.value) || 0;

  if (l > 0 && w > 0 && h > 0) {
    const volume = l * w * h;
    const area   = l * w;
    elVolumeDisplay.textContent = `${volume.toFixed(1)} ${t('unit_m3')}`;
    elAreaDisplay.textContent   = `${area.toFixed(1)} ${t('unit_m2')}`;
  } else {
    elVolumeDisplay.textContent = t('vol_default');
    elAreaDisplay.textContent   = t('area_default');
  }
}

elLength.addEventListener('input', updateDimensionsDisplay);
elWidth.addEventListener('input',  updateDimensionsDisplay);
elHeight.addEventListener('input', updateDimensionsDisplay);

// Toggle gas info visibility
function updateGasInfoVisibility() {
  elGasInfo.style.display = elHeaterType.value === 'gas_open' ? 'block' : 'none';
}

elHeaterType.addEventListener('change', updateGasInfoVisibility);

// Save building dimensions
elSaveBuildingBtn.addEventListener('click', async () => {
  const l = parseFloat(elLength.value);
  const w = parseFloat(elWidth.value);
  const h = parseFloat(elHeight.value);

  if (!l || !w || !h || l <= 0 || w <= 0 || h <= 0) {
    elBuildingStatus.textContent = t('err_valid_dims');
    elBuildingStatus.style.color = 'var(--danger, #ff7a7a)';
    return;
  }

  try {
    const config = await loadConfig();
    config.building = { length_m: l, width_m: w, height_m: h };

    const r = await fetch('/thermal/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });

    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);

    elBuildingStatus.textContent = t('status_saved');
    elBuildingStatus.style.color = 'var(--ok, #7bc96f)';
    await loadAndDisplayConfig();

  } catch (e) {
    elBuildingStatus.textContent = t('err_prefix') + e.message;
    elBuildingStatus.style.color = 'var(--danger, #ff7a7a)';
  }
});

// Save heater configuration
elSaveHeaterBtn.addEventListener('click', async () => {
  const heaterType = elHeaterType.value;
  const power = parseFloat(elHeaterPower.value);

  if (!power || power < 0) {
    elHeaterStatus.textContent = t('err_valid_heater');
    elHeaterStatus.style.color = 'var(--danger, #ff7a7a)';
    return;
  }

  try {
    const config = await loadConfig();
    config.heater = { heater_type: heaterType, total_power_kw: power };

    const r = await fetch('/thermal/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });

    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);

    elHeaterStatus.textContent = t('status_saved');
    elHeaterStatus.style.color = 'var(--ok, #7bc96f)';
    await loadAndDisplayConfig();

  } catch (e) {
    elHeaterStatus.textContent = t('err_prefix') + e.message;
    elHeaterStatus.style.color = 'var(--danger, #ff7a7a)';
  }
});

// Calculate UA coefficient
elCalculateBtn.addEventListener('click', async () => {
  const tInitial    = parseFloat(elTInitial.value);
  const tFinal      = parseFloat(elTFinal.value);
  const tOutside    = parseFloat(elTOutside.value);
  const timeMinutes = parseFloat(elTimeMinutes.value);

  if (isNaN(tInitial) || isNaN(tFinal) || isNaN(tOutside) || isNaN(timeMinutes) || timeMinutes <= 0) {
    elCalibrationResult.innerHTML = `<div class="danger">${t('err_fill_fields')}</div>`;
    return;
  }

  if (tInitial <= tOutside || tFinal <= tOutside) {
    elCalibrationResult.innerHTML = `<div class="danger">${t('err_temps_outside')}</div>`;
    return;
  }

  try {
    const r = await fetch('/thermal/calibrate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        t_initial_c:  tInitial,
        t_final_c:    tFinal,
        t_outside_c:  tOutside,
        time_minutes: timeMinutes
      })
    });

    if (!r.ok) {
      const errText = await r.text();
      throw new Error(errText);
    }

    const data = await r.json();
    calculatedUA = data.ua_coefficient;

    const coolingRate = Math.abs(data.cooling_rate_per_minute);
    const uaUnit      = t('cfg_ua_unit');
    const volUnit     = t('unit_m3');
    const rateUnit    = `°C/${t('unit_min')}`;

    elCalibrationResult.innerHTML = `
      <div style="padding:12px; background:var(--ok-bg,#1a3a1a); border-left:3px solid var(--ok,#7bc96f); border-radius:4px;">
        <strong>${t('cal_complete')}</strong>
        <div style="margin-top:8px; display:grid; gap:6px;">
          <div class="kv"><span>${t('ua_coeff_lbl')}</span><span><strong>${calculatedUA.toFixed(1)} ${uaUnit}</strong></span></div>
          <div class="kv"><span>${t('vol_label')}</span><span>${data.volume_m3.toFixed(1)} ${volUnit}</span></div>
          <div class="kv"><span>${t('cool_rate_lbl')}</span><span>${coolingRate.toFixed(3)} ${rateUnit}</span></div>
        </div>
        <p class="muted" style="margin:8px 0 0 0; font-size:13px;">
          ${t('cal_save_hint')}
        </p>
      </div>
    `;

    elSaveCalibrationBtn.disabled = false;

  } catch (e) {
    elCalibrationResult.innerHTML = `<div class="danger">${t('err_prefix')}${String(e)}</div>`;
    elSaveCalibrationBtn.disabled = true;
  }
});

// Save calibration
elSaveCalibrationBtn.addEventListener('click', async () => {
  if (!calculatedUA) {
    alert(t('err_calc_first'));
    return;
  }

  const tInitial    = parseFloat(elTInitial.value);
  const tFinal      = parseFloat(elTFinal.value);
  const tOutside    = parseFloat(elTOutside.value);
  const timeMinutes = parseFloat(elTimeMinutes.value);

  try {
    const config = await loadConfig();
    config.calibration = {
      t_initial_c:  tInitial,
      t_final_c:    tFinal,
      t_outside_c:  tOutside,
      time_minutes: timeMinutes
    };

    const r = await fetch('/thermal/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });

    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);

    alert(t('cal_saved_alert'));
    await loadAndDisplayConfig();

  } catch (e) {
    alert(t('err_save_cal') + e.message);
  }
});

// Analyze heaters
elAnalyzeBtn.addEventListener('click', async () => {
  const tInside  = parseFloat(elTInsideTarget.value);
  const tOutside = parseFloat(elTOutsideAnalysis.value);

  if (isNaN(tInside) || isNaN(tOutside)) {
    elAnalysisResult.innerHTML = `<div class="danger">${t('err_enter_temps')}</div>`;
    return;
  }

  try {
    const r = await fetch(`/thermal/analyze-heaters?t_inside_target=${tInside}&t_outside=${tOutside}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });

    if (!r.ok) {
      const errText = await r.text();
      throw new Error(errText);
    }

    const data = await r.json();

    const dutyCyclePercent = data.duty_cycle_percent.toFixed(1);
    const heatLoss  = data.heat_loss_kw.toFixed(1);
    const airDemand = data.air_demand_m3h.toFixed(0);

    let airInfo;
    if (data.air_demand_m3h > 0) {
      airInfo = `
        <div class="kv" style="background:var(--warning-bg,#3a2f1a); padding:8px; border-radius:4px; border-left:3px solid var(--warning,#f4b942);">
          <span>${t('combustion_lbl')}</span>
          <span><strong>${airDemand} ${t('unit_m3h')}</strong></span>
        </div>
      `;
    } else {
      airInfo = `<p class="muted" style="margin:8px 0;">${t('no_combustion')}</p>`;
    }

    elAnalysisResult.innerHTML = `
      <div style="padding:12px; background:var(--card); border:1px solid var(--border); border-radius:8px; margin-top:12px;">
        <strong>${t('analysis_title')}</strong>
        <div style="margin-top:8px; display:grid; gap:8px;">
          <div class="kv"><span>${t('heat_loss_lbl')}</span><span>${heatLoss} ${t('unit_kw')}</span></div>
          <div class="kv"><span>${t('heater_load_lbl')}</span><span>${dutyCyclePercent}%</span></div>
          <div class="kv"><span>${t('run_time_lbl')}</span><span>${t('run_time_val', { pct: dutyCyclePercent })}</span></div>
          ${airInfo}
        </div>
        <p class="muted" style="margin:8px 0 0 0; font-size:13px;">
          ${data.air_demand_m3h > 0 ? t('air_added_hint') : t('no_air_change')}
        </p>
      </div>
    `;

  } catch (e) {
    elAnalysisResult.innerHTML = `<div class="danger">${t('err_prefix')}${String(e)}</div>`;
  }
});

// Load current configuration
async function loadConfig() {
  try {
    const r = await fetch('/thermal/config');
    if (r.ok) return await r.json();
  } catch (e) {
    console.error('Failed to load config:', e);
  }
  return { building: null, heater: null, calibration: null };
}

async function loadAndDisplayConfig() {
  const config = await loadConfig();
  let html = '';

  if (config.building) {
    const b      = config.building;
    const volume = (b.length_m * b.width_m * b.height_m).toFixed(1);
    const area   = (b.length_m * b.width_m).toFixed(1);
    const uM  = t('unit_m');
    const uM3 = t('unit_m3');
    const uM2 = t('unit_m2');

    html += `
      <div style="margin-bottom:12px;">
        <strong>${t('cfg_bldg_h')}</strong>
        <div class="kv"><span>${t('cfg_lwh')}</span><span>${b.length_m} × ${b.width_m} × ${b.height_m} ${uM}</span></div>
        <div class="kv"><span>${t('cfg_volume')}</span><span>${volume} ${uM3}</span></div>
        <div class="kv"><span>${t('cfg_floor')}</span><span>${area} ${uM2}</span></div>
      </div>
    `;

    // Fill form
    elLength.value = b.length_m;
    elWidth.value  = b.width_m;
    elHeight.value = b.height_m;
    updateDimensionsDisplay();
  } else {
    html += `<div class="muted">${t('cfg_bldg_none')}</div>`;
  }

  if (config.heater) {
    const h         = config.heater;
    const typeLabel = h.heater_type === 'gas_open' ? t('cfg_gas_lbl') : t('cfg_elec_lbl');

    html += `
      <div style="margin-bottom:12px;">
        <strong>${t('cfg_heater_h')}</strong>
        <div class="kv"><span>${t('cfg_heater_type')}</span><span>${typeLabel}</span></div>
        <div class="kv"><span>${t('cfg_heater_cap')}</span><span>${h.total_power_kw} ${t('cfg_kw_unit')}</span></div>
      </div>
    `;

    // Fill form
    elHeaterType.value  = h.heater_type;
    elHeaterPower.value = h.total_power_kw;
    updateGasInfoVisibility();
  } else {
    html += `<div class="muted">${t('cfg_heater_none')}</div>`;
  }

  if (config.calibration) {
    const c = config.calibration;
    html += `
      <div>
        <strong>${t('cfg_cal_h')}</strong>
        <div class="kv"><span>${t('cfg_ua')}</span><span>${c.ua_coefficient.toFixed(1)} ${t('cfg_ua_unit')}</span></div>
        <div class="kv"><span>${t('cfg_test_cond')}</span><span>${t('cfg_test_val', { t0: c.t_initial_c, t1: c.t_final_c, time: c.time_minutes, tout: c.t_outside_c })}</span></div>
      </div>
    `;
  } else {
    html += `<div class="muted">${t('cfg_cal_none')}</div>`;
  }

  elCurrentConfig.innerHTML = html;
}

// Initialize
updateDimensionsDisplay();
updateGasInfoVisibility();
loadAndDisplayConfig();
