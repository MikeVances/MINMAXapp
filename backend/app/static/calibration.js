// Calibration page logic

const elLength = document.getElementById('length');
const elWidth = document.getElementById('width');
const elHeight = document.getElementById('height');
const elVolumeDisplay = document.getElementById('volumeDisplay');
const elAreaDisplay = document.getElementById('areaDisplay');
const elSaveBuildingBtn = document.getElementById('saveBuildingBtn');
const elBuildingStatus = document.getElementById('buildingStatus');

const elHeaterType = document.getElementById('heaterType');
const elHeaterPower = document.getElementById('heaterPower');
const elGasInfo = document.getElementById('gasInfo');
const elSaveHeaterBtn = document.getElementById('saveHeaterBtn');
const elHeaterStatus = document.getElementById('heaterStatus');

const elTInitial = document.getElementById('tInitial');
const elTFinal = document.getElementById('tFinal');
const elTOutside = document.getElementById('tOutside');
const elTimeMinutes = document.getElementById('timeMinutes');
const elCalculateBtn = document.getElementById('calculateBtn');
const elSaveCalibrationBtn = document.getElementById('saveCalibrationBtn');
const elCalibrationResult = document.getElementById('calibrationResult');

const elTInsideTarget = document.getElementById('tInsideTarget');
const elTOutsideAnalysis = document.getElementById('tOutsideAnalysis');
const elAnalyzeBtn = document.getElementById('analyzeBtn');
const elAnalysisResult = document.getElementById('analysisResult');

const elCurrentConfig = document.getElementById('currentConfig');

let calculatedUA = null;

// Update volume and area display
function updateDimensionsDisplay() {
  const l = parseFloat(elLength.value) || 0;
  const w = parseFloat(elWidth.value) || 0;
  const h = parseFloat(elHeight.value) || 0;

  if (l > 0 && w > 0 && h > 0) {
    const volume = l * w * h;
    const area = l * w;
    elVolumeDisplay.textContent = `${volume.toFixed(1)} m³`;
    elAreaDisplay.textContent = `${area.toFixed(1)} m²`;
  } else {
    elVolumeDisplay.textContent = '— м³';
    elAreaDisplay.textContent = '— м²';
  }
}

elLength.addEventListener('input', updateDimensionsDisplay);
elWidth.addEventListener('input', updateDimensionsDisplay);
elHeight.addEventListener('input', updateDimensionsDisplay);

// Toggle gas info visibility
function updateGasInfoVisibility() {
  if (elHeaterType.value === 'gas_open') {
    elGasInfo.style.display = 'block';
  } else {
    elGasInfo.style.display = 'none';
  }
}

elHeaterType.addEventListener('change', updateGasInfoVisibility);

// Save building dimensions
elSaveBuildingBtn.addEventListener('click', async () => {
  const l = parseFloat(elLength.value);
  const w = parseFloat(elWidth.value);
  const h = parseFloat(elHeight.value);

  if (!l || !w || !h || l <= 0 || w <= 0 || h <= 0) {
    elBuildingStatus.textContent = '❌ Enter valid dimensions';
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

    elBuildingStatus.textContent = '✅ Saved';
    elBuildingStatus.style.color = 'var(--ok, #7bc96f)';
    await loadAndDisplayConfig();

  } catch (e) {
    elBuildingStatus.textContent = `❌ Ошибка: ${e.message}`;
    elBuildingStatus.style.color = 'var(--danger, #ff7a7a)';
  }
});

// Save heater configuration
elSaveHeaterBtn.addEventListener('click', async () => {
  const heaterType = elHeaterType.value;
  const power = parseFloat(elHeaterPower.value);

  if (!power || power < 0) {
    elHeaterStatus.textContent = '❌ Enter valid heating capacity';
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

    elHeaterStatus.textContent = '✅ Сохранено';
    elHeaterStatus.style.color = 'var(--ok, #7bc96f)';
    await loadAndDisplayConfig();

  } catch (e) {
    elHeaterStatus.textContent = `❌ Ошибка: ${e.message}`;
    elHeaterStatus.style.color = 'var(--danger, #ff7a7a)';
  }
});

// Calculate UA coefficient
elCalculateBtn.addEventListener('click', async () => {
  const tInitial = parseFloat(elTInitial.value);
  const tFinal = parseFloat(elTFinal.value);
  const tOutside = parseFloat(elTOutside.value);
  const timeMinutes = parseFloat(elTimeMinutes.value);

  if (isNaN(tInitial) || isNaN(tFinal) || isNaN(tOutside) || isNaN(timeMinutes) || timeMinutes <= 0) {
    elCalibrationResult.innerHTML = '<div class="danger">❌ Заполните все поля корректно</div>';
    return;
  }

  if (tInitial <= tOutside || tFinal <= tOutside) {
    elCalibrationResult.innerHTML = '<div class="danger">❌ Начальная и конечная температуры должны быть выше наружной</div>';
    return;
  }

  try {
    const r = await fetch('/thermal/calibrate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        t_initial_c: tInitial,
        t_final_c: tFinal,
        t_outside_c: tOutside,
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

    elCalibrationResult.innerHTML = `
      <div style="padding:12px; background:var(--ok-bg,#1a3a1a); border-left:3px solid var(--ok,#7bc96f); border-radius:4px;">
        <strong>✅ Calibration complete</strong>
        <div style="margin-top:8px; display:grid; gap:6px;">
          <div class="kv"><span>UA coefficient</span><span><strong>${calculatedUA.toFixed(1)} W/°C</strong></span></div>
          <div class="kv"><span>Building volume</span><span>${data.volume_m3.toFixed(1)} m³</span></div>
          <div class="kv"><span>Cooling rate</span><span>${coolingRate.toFixed(3)} °C/min</span></div>
        </div>
        <p class="muted" style="margin:8px 0 0 0; font-size:13px;">
          Click "Save calibration" to use these values in ventilation calculations.
        </p>
      </div>
    `;

    elSaveCalibrationBtn.disabled = false;

  } catch (e) {
    elCalibrationResult.innerHTML = `<div class="danger">❌ Ошибка: ${String(e)}</div>`;
    elSaveCalibrationBtn.disabled = true;
  }
});

// Save calibration
elSaveCalibrationBtn.addEventListener('click', async () => {
  if (!calculatedUA) {
    alert('Сначала выполните расчет');
    return;
  }

  const tInitial = parseFloat(elTInitial.value);
  const tFinal = parseFloat(elTFinal.value);
  const tOutside = parseFloat(elTOutside.value);
  const timeMinutes = parseFloat(elTimeMinutes.value);

  try {
    const config = await loadConfig();
    config.calibration = {
      t_initial_c: tInitial,
      t_final_c: tFinal,
      t_outside_c: tOutside,
      time_minutes: timeMinutes
    };

    const r = await fetch('/thermal/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });

    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);

    alert('✅ Калибровка сохранена! Теперь расчеты вентиляции будут автоматически учитывать воздух для обогревателей.');
    await loadAndDisplayConfig();

  } catch (e) {
    alert(`❌ Ошибка сохранения: ${e.message}`);
  }
});

// Analyze heaters
elAnalyzeBtn.addEventListener('click', async () => {
  const tInside = parseFloat(elTInsideTarget.value);
  const tOutside = parseFloat(elTOutsideAnalysis.value);

  if (isNaN(tInside) || isNaN(tOutside)) {
    elAnalysisResult.innerHTML = '<div class="danger">❌ Введите температуры</div>';
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

    const dutyCyclePercent = (data.duty_cycle_percent).toFixed(1);
    const heatLoss = data.heat_loss_kw.toFixed(1);
    const airDemand = data.air_demand_m3h.toFixed(0);

    let airInfo = '';
    if (data.air_demand_m3h > 0) {
      airInfo = `
        <div class="kv" style="background:var(--warning-bg,#3a2f1a); padding:8px; border-radius:4px; border-left:3px solid var(--warning,#f4b942);">
          <span>Additional combustion air</span>
          <span><strong>${airDemand} m³/h</strong></span>
        </div>
      `;
    } else {
      airInfo = `<p class="muted" style="margin:8px 0;">Electric heaters do not require additional combustion air.</p>`;
    }

    elAnalysisResult.innerHTML = `
      <div style="padding:12px; background:var(--card); border:1px solid var(--border); border-radius:8px; margin-top:12px;">
        <strong>📊 Analysis results:</strong>
        <div style="margin-top:8px; display:grid; gap:8px;">
          <div class="kv"><span>Heat loss</span><span>${heatLoss} kW</span></div>
          <div class="kv"><span>Heater load</span><span>${dutyCyclePercent}%</span></div>
          <div class="kv"><span>Run time</span><span>${dutyCyclePercent}% of the time</span></div>
          ${airInfo}
        </div>
        <p class="muted" style="margin:8px 0 0 0; font-size:13px;">
          ${data.air_demand_m3h > 0 ?
            'This air will be automatically added to minimum ventilation in calculations.' :
            'Ventilation calculations will not change — electric heaters do not consume combustion air.'}
        </p>
      </div>
    `;

  } catch (e) {
    elAnalysisResult.innerHTML = `<div class="danger">❌ ${String(e)}</div>`;
  }
});

// Load current configuration
async function loadConfig() {
  try {
    const r = await fetch('/thermal/config');
    if (r.ok) {
      return await r.json();
    }
  } catch (e) {
    console.error('Failed to load config:', e);
  }
  return { building: null, heater: null, calibration: null };
}

async function loadAndDisplayConfig() {
  const config = await loadConfig();

  let html = '';

  if (config.building) {
    const b = config.building;
    const volume = (b.length_m * b.width_m * b.height_m).toFixed(1);
    const area = (b.length_m * b.width_m).toFixed(1);

    html += `
      <div style="margin-bottom:12px;">
        <strong>🏢 Building dimensions:</strong>
        <div class="kv"><span>Length × Width × Height</span><span>${b.length_m} × ${b.width_m} × ${b.height_m} m</span></div>
        <div class="kv"><span>Volume</span><span>${volume} m³</span></div>
        <div class="kv"><span>Floor area</span><span>${area} m²</span></div>
      </div>
    `;

    // Fill form
    elLength.value = b.length_m;
    elWidth.value = b.width_m;
    elHeight.value = b.height_m;
    updateDimensionsDisplay();
  } else {
    html += '<div class="muted">🏢 Building dimensions not set</div>';
  }

  if (config.heater) {
    const h = config.heater;
    const typeLabel = h.heater_type === 'gas_open' ? 'Open-flame gas brooders' : 'Electric heaters';

    html += `
      <div style="margin-bottom:12px;">
        <strong>🔥 Heating equipment:</strong>
        <div class="kv"><span>Type</span><span>${typeLabel}</span></div>
        <div class="kv"><span>Capacity</span><span>${h.total_power_kw} kW</span></div>
      </div>
    `;

    // Fill form
    elHeaterType.value = h.heater_type;
    elHeaterPower.value = h.total_power_kw;
    updateGasInfoVisibility();
  } else {
    html += '<div class="muted">🔥 Heaters not configured</div>';
  }

  if (config.calibration) {
    const c = config.calibration;
    html += `
      <div>
        <strong>🔬 Calibration complete:</strong>
        <div class="kv"><span>UA coefficient</span><span>${c.ua_coefficient.toFixed(1)} W/°C</span></div>
        <div class="kv"><span>Test conditions</span><span>${c.t_initial_c}°C → ${c.t_final_c}°C in ${c.time_minutes} min (outdoor ${c.t_outside_c}°C)</span></div>
      </div>
    `;
  } else {
    html += '<div class="muted">🔬 Calibration not performed</div>';
  }

  elCurrentConfig.innerHTML = html;
}

// Initialize
updateDimensionsDisplay();
updateGasInfoVisibility();
loadAndDisplayConfig();
