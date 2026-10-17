// Calibration page logic

// Экранирование для вставки в innerHTML: house_id приходит с сервера, а туда —
// от любого клиента. Без экранирования имя корпуса вида <img onerror=…>
// выполнялось бы у каждого, кто откроет страницу калибровки (stored XSS).
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const elLength      = document.getElementById('length');
const elWidth       = document.getElementById('width');
const elHeightWall  = document.getElementById('height-wall');
const elHeightRidge = document.getElementById('height-ridge');
const elVolumeDisplay = document.getElementById('volumeDisplay');
const elAreaDisplay   = document.getElementById('areaDisplay');
const elSaveBuildingBtn = document.getElementById('saveBuildingBtn');
const elBuildingStatus  = document.getElementById('buildingStatus');

const elHeaterType    = document.getElementById('heaterType');
const elHeaterPower   = document.getElementById('heaterPower');
const elGasInfo       = document.getElementById('gasInfo');
const elSaveHeaterBtn = document.getElementById('saveHeaterBtn');
const elHeaterStatus  = document.getElementById('heaterStatus');

const elTOutside    = document.getElementById('tOutside');
const elSaveCalibrationBtn = document.getElementById('saveCalibrationBtn');
const elCalibrationResult  = document.getElementById('calibrationResult');

const elTInsideTarget      = document.getElementById('tInsideTarget');
const elTOutsideAnalysis   = document.getElementById('tOutsideAnalysis');
const elQMinAnalysis       = document.getElementById('qMinAnalysis');
const elNumBirdsAnalysis   = document.getElementById('numBirdsAnalysis');
const elBirdWeightAnalysis = document.getElementById('birdWeightAnalysis');
const elAnalyzeBtn         = document.getElementById('analyzeBtn');
const elAnalysisResult     = document.getElementById('analysisResult');

const elCurrentConfig = document.getElementById('currentConfig');

// ── Тест остывания по кривой: отметка на каждом градусе ──────────────────────
// Пользователь вводит температуры, выключает обогрев и жмёт кнопку каждый раз,
// когда градусник показывает на градус меньше. По 4–6 отметкам сервер подгоняет
// модель «воздух + пол и стены» (core/cooling_fit) и находит UA без допущений
// о теплоёмкости конструкций. Многозонный режим — то же самое по градуснику каждой зоны.
const elTimerBtn     = document.getElementById('timerBtn');
const elFinishBtn    = document.getElementById('finishTestBtn');
const elTimerDisplay = document.getElementById('timerDisplay');
const elTimerStatus  = document.getElementById('timerStatus');
const elTStartInside = document.getElementById('tStartInside');
const elTapPanel     = document.getElementById('tapPanel');

const MIN_DROPS    = 4;   // меньше — параметры модели не разделяются (как на сервере)
const TARGET_DROPS = 6;   // после стольких отметок во всех зонах тест завершается сам
const MIN_DELTA_T  = 10;  // °C: меньшая разница с улицей — тест бессмыслен

// test = null | { startMs, tStart, tOut, zones: [[[сек, °C], …], …], interval }
let test = null;
let lastResult = null;    // { zones, uaTotal, points (однозонный), tOut }

function timerFormat(totalSeconds) {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60).toString().padStart(2, '0');
  const s = (totalSeconds % 60).toString().padStart(2, '0');
  return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
}

function zoneCount() {
  return Math.min(Math.max(parseInt(document.getElementById('zoneCount')?.value) || 1, 1), 8);
}

function elapsedSec() {
  return Math.floor((Date.now() - test.startMs) / 1000);
}

// Следующая ожидаемая температура зоны: на градус ниже предыдущей отметки.
// zones[i] начинается с точки старта [0, tStart], поэтому k-я отметка = tStart − k
function nextTemp(zone) {
  return Math.round((test.tStart - test.zones[zone].length) * 10) / 10;
}

function renderTapPanel() {
  if (!test) { elTapPanel.innerHTML = ''; return; }
  const n = test.zones.length;
  elTapPanel.innerHTML = test.zones.map((marks, i) => {
    const drops = marks.length - 1;
    const label = n > 1
      ? `<span style="min-width:80px;font-weight:600;font-size:13px;">${t('zone_lbl', { n: i + 1 })}${
          i === 0 ? ` <span class="muted" style="font-size:11px;">(${t('zone_entry')})</span>`
          : i === n - 1 ? ` <span class="muted" style="font-size:11px;">(${t('zone_far')})</span>` : ''}</span>`
      : '';
    const list = marks.slice(1).map(([sec, temp]) => `${temp} °C — ${timerFormat(sec)}`).join(' · ');
    return `
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px;background:var(--bg);border-radius:8px;margin-bottom:8px;">
        ${label}
        <button class="btn" data-zone="${i}" style="${n === 1 ? 'font-size:18px;padding:12px 22px;' : ''}">
          ${t('tap_btn', { t: nextTemp(i) })}</button>
        <span class="muted" style="font-size:12px;">${t('marks_count', { n: drops })}</span>
        <div class="muted" style="flex-basis:100%;font-size:11px;">${list}</div>
      </div>`;
  }).join('');
  elTapPanel.querySelectorAll('button[data-zone]').forEach(btn =>
    btn.addEventListener('click', () => recordMark(Number(btn.dataset.zone))));
}

function recordMark(zone) {
  if (!test) return;
  test.zones[zone].push([elapsedSec(), nextTemp(zone)]);
  const allDone = test.zones.every(m => m.length - 1 >= TARGET_DROPS);
  const enough  = test.zones.every(m => m.length - 1 >= MIN_DROPS);
  elFinishBtn.disabled = !enough;
  if (allDone) { finishTest(); return; }
  renderTapPanel();
}

function stopTimer() {
  if (test && test.interval) clearInterval(test.interval);
  elTimerBtn.textContent      = t('btn_start_test');
  elTimerBtn.style.background = '';
  elTimerBtn.style.color      = '';
  elTimerDisplay.style.color  = 'var(--accent)';
  elFinishBtn.style.display   = 'none';
}

function startTest() {
  const tOut   = parseFloat(elTOutside.value);
  const tStart = parseFloat(elTStartInside.value);
  if (isNaN(tOut) || isNaN(tStart)) {
    elTimerStatus.textContent = t('err_enter_temps_first');
    elTimerStatus.style.color = 'var(--danger)';
    return;
  }
  if (tStart - tOut < MIN_DELTA_T) {
    elTimerStatus.textContent = t('err_start_temp', { dt: MIN_DELTA_T });
    elTimerStatus.style.color = 'var(--danger)';
    return;
  }
  // Отметки — целые градусы ниже старта: стартовую температуру округляем до 0.1
  const start = Math.round(tStart * 10) / 10;
  test = {
    startMs: Date.now(), tStart: start, tOut,
    zones: Array.from({ length: zoneCount() }, () => [[0, start]]),
    interval: setInterval(() => { elTimerDisplay.textContent = timerFormat(elapsedSec()); }, 500),
  };
  lastResult = null;
  elSaveCalibrationBtn.disabled = true;
  elCalibrationResult.innerHTML = '';
  elTimerDisplay.style.color  = 'var(--accent-2)';
  elTimerStatus.style.color   = '';
  elTimerStatus.textContent   = t(zoneCount() > 1 ? 'mz_timer_running' : 'timer_running', { n: zoneCount() });
  elTimerBtn.textContent      = t('btn_cancel_test');
  elFinishBtn.style.display   = '';
  elFinishBtn.disabled        = true;
  renderTapPanel();
}

function cancelTest() {
  stopTimer();
  test = null;
  elTimerDisplay.textContent = '00:00';
  elTimerStatus.textContent  = t('timer_ready');
  renderTapPanel();
}

async function finishTest() {
  const done = test;
  stopTimer();
  test = null;
  renderTapPanel();
  elTimerStatus.style.color = 'var(--ok)';
  elTimerStatus.textContent = t('timer_done', { min: (Math.max(...done.zones.map(m => m[m.length - 1][0])) / 60).toFixed(1) });
  try {
    lastResult = await computeCurveResult(done);
    renderCurveResult(lastResult);
    elSaveCalibrationBtn.disabled = false;
  } catch (e) {
    elCalibrationResult.innerHTML = `<div class="danger">${escapeHtml(t('err_prefix') + String(e.message || e))}</div>`;
  }
}

// Расчёт на сервере (core/cooling_fit). Объём — из СОХРАНЁННЫХ размеров корпуса:
// по ним же сервер пересчитает UA при сохранении, и показанное совпадёт с сохранённым
async function computeCurveResult(done) {
  const config = await loadConfig();
  const b = config.building;
  if (!b) throw new Error(t('err_need_dims'));
  const volume = b.length_m * b.width_m * b.height_m;
  const n = done.zones.length;

  const zones = [];
  for (let i = 0; i < n; i++) {
    const r = await fetch('./thermal/calibrate-curve', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        t_outside_c: done.tOut,
        points: done.zones[i].map(([t_s, temp_c]) => ({ t_s, temp_c })),
        ...(n > 1 ? { volume_m3: volume / n } : {}),
      }),
    });
    if (!r.ok) throw new Error(await r.text());
    zones.push(await r.json());
  }
  return {
    zones, n, tOut: done.tOut, floorArea: b.length_m * b.width_m,
    uaTotal: zones.reduce((s, z) => s + z.ua_coefficient, 0),
    points: n === 1 ? done.zones[0] : null,
    durationMin: Math.max(...zones.map(z => z.duration_minutes)),
  };
}

function uaQuality(uaM2) {
  if (uaM2 < 0.5) return { label: t('ua_quality_excellent'), bg: '#14532d', color: '#4ade80' };
  if (uaM2 < 1.0) return { label: t('ua_quality_good'),      bg: '#713f12', color: '#fbbf24' };
  if (uaM2 < 2.0) return { label: t('ua_quality_avg'),       bg: '#7c2d12', color: '#fb923c' };
  return              { label: t('ua_quality_poor'),          bg: '#450a0a', color: '#f87171' };
}

function renderCurveResult(res) {
  const uaUnit  = t('cfg_ua_unit');
  const zoneArea = res.floorArea / res.n;
  const uaM2    = res.uaTotal / res.floorArea;
  const q       = uaQuality(uaM2);
  const cStruct = res.zones.reduce((s, z) => s + z.c_struct_j_per_k, 0);
  const cAir    = res.zones.reduce((s, z) => s + z.c_air_j_per_k, 0);
  const warnings = [...new Set(res.zones.flatMap(z => z.warnings))];

  const zoneRows = res.n > 1 ? res.zones.map((z, i) => {
    const zq = uaQuality(z.ua_coefficient / zoneArea);
    return `<div class="kv"><span>${t('zone_lbl', { n: i + 1 })}</span>
      <span style="color:${zq.color};font-weight:700;">${(z.ua_coefficient / zoneArea).toFixed(2)} ${uaUnit}/м²</span></div>`;
  }).join('') : '';

  const warnHtml = warnings.map(w =>
    `<p class="warn" style="margin:6px 0 0;font-size:12px;">⚠️ ${t('cal_warn_' + w)}</p>`).join('');

  elCalibrationResult.innerHTML = `
    <div style="padding:12px; background:var(--ok-bg,#1a3a1a); border-left:3px solid var(--ok,#7bc96f); border-radius:4px;">
      <strong>${t('cal_curve_complete')}</strong>
      <div style="margin-top:8px; display:grid; gap:6px;">
        <div class="kv"><span>${t('ua_coeff_lbl')}</span><span><strong>${res.uaTotal.toFixed(0)} ${uaUnit}</strong></span></div>
        <div class="kv"><span>${t('ua_per_m2_lbl')}</span><span>${uaM2.toFixed(2)} ${uaUnit}/м²
          <span style="padding:2px 10px;border-radius:10px;font-size:12px;background:${q.bg};color:${q.color};">${q.label}</span></span></div>
        <div class="kv"><span>${t('c_struct_lbl')}</span><span>${t('c_struct_ratio', { x: (cStruct / cAir).toFixed(1) })}</span></div>
        <div class="kv"><span>${t('duration_lbl')}</span><span>${res.durationMin.toFixed(0)} ${t('unit_min')}</span></div>
        ${zoneRows}
      </div>
      ${warnHtml}
      <p class="muted" style="margin:8px 0 0;font-size:12px;">ℹ️ ${t('cal_equilibrium_note')}</p>
      <p class="muted" style="margin:6px 0 0;font-size:13px;">${t('cal_save_hint')}</p>
    </div>`;
}

document.getElementById('zoneCount')?.addEventListener('input', () => { if (!test) renderTapPanel(); });

elTimerBtn.addEventListener('click', () => (test ? cancelTest() : startTest()));
elFinishBtn.addEventListener('click', () => { if (test) finishTest(); });

// ── Конец логики теста ───────────────────────────────────────────────────────

// Читает house_id из dataset опции текущего выбора в dimHouseSelect
function getSelectedHouseId() {
  const sel = document.getElementById('dimHouseSelect');
  if (!sel || sel.selectedIndex < 0) return null;
  return sel.options[sel.selectedIndex]?.dataset?.houseId || null;
}

// Эффективная высота для двускатной крыши: среднее стены и конька
// V = L × W × (H_стена + H_конёк) / 2
function effectiveHeight() {
  const hw = parseFloat(elHeightWall.value)  || 0;
  const hr = parseFloat(elHeightRidge.value) || 0;
  if (hw > 0 && hr > 0) return (hw + hr) / 2;
  return hw || hr; // если задана только одна — используем её
}

// Update volume and area display
function updateDimensionsDisplay() {
  const l    = parseFloat(elLength.value) || 0;
  const w    = parseFloat(elWidth.value)  || 0;
  const hEff = effectiveHeight();

  if (l > 0 && w > 0 && hEff > 0) {
    const volume = l * w * hEff;
    const area   = l * w;
    elVolumeDisplay.textContent = `${volume.toFixed(1)} ${t('unit_m3')}`;
    elAreaDisplay.textContent   = `${area.toFixed(1)} ${t('unit_m2')}`;
  } else {
    elVolumeDisplay.textContent = t('vol_default');
    elAreaDisplay.textContent   = t('area_default');
  }
}

elLength.addEventListener('input',      updateDimensionsDisplay);
elWidth.addEventListener('input',       updateDimensionsDisplay);
elHeightWall.addEventListener('input',  updateDimensionsDisplay);
elHeightRidge.addEventListener('input', updateDimensionsDisplay);

// Toggle gas info visibility
function updateGasInfoVisibility() {
  elGasInfo.style.display = elHeaterType.value === 'gas_open' ? 'block' : 'none';
}

elHeaterType.addEventListener('change', updateGasInfoVisibility);

// Save building dimensions
elSaveBuildingBtn.addEventListener('click', async () => {
  const l    = parseFloat(elLength.value);
  const w    = parseFloat(elWidth.value);
  const hEff = effectiveHeight();

  if (!l || !w || !hEff || l <= 0 || w <= 0 || hEff <= 0) {
    elBuildingStatus.textContent = t('err_valid_dims');
    elBuildingStatus.style.color = 'var(--danger, #ff7a7a)';
    return;
  }

  try {
    const config = await loadConfig();
    const houseId = getSelectedHouseId();
    if (config.house_id != null && houseId != null && config.house_id !== houseId) {
      // Другой корпус: калибровка и горелки прежнего корпуса к нему не относятся
      config.calibration = null;
      config.heater      = null;
    } else if (config.calibration) {
      if (config.calibration.points || config.calibration.method !== 'cooling_curve') {
        // Тот же корпус, но размеры могли измениться: UA пересчитает сервер
        // по сохранённым отметкам (или старому тесту) и новому объёму
        delete config.calibration.ua_coefficient;
      } else {
        // Многозонная калибровка хранит только итог — пересчитать нельзя, нужен новый тест
        config.calibration = null;
      }
    }
    config.house_id  = houseId;
    // Backend принимает height_m — передаём эффективную высоту (среднее стены и конька)
    config.building = { length_m: l, width_m: w, height_m: hEff };

    const r = await fetch('./thermal/config', {
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

    const r = await fetch('./thermal/config', {
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

// Save calibration
elSaveCalibrationBtn.addEventListener('click', async () => {
  if (!lastResult) { alert(t('err_calc_first')); return; }
  try {
    const config = await loadConfig();
    config.house_id = getSelectedHouseId();
    const r = lastResult;
    const first = r.points ? r.points[0] : null;
    const last  = r.points ? r.points[r.points.length - 1] : null;
    config.calibration = r.points
      // Однозонный: отправляем отметки, UA посчитает сервер по объёму корпуса
      // (и пересчитает сам, если размеры потом поменяются)
      ? { t_initial_c: first[1], t_final_c: last[1], t_outside_c: r.tOut,
          time_minutes: last[0] / 60, method: 'cooling_curve',
          points: r.points.map(([t_s, temp_c]) => ({ t_s, temp_c })) }
      // Многозонный: UA здания = сумма зон; отметки по зонам разные, сохраняем итог
      : { t_initial_c: 0, t_final_c: 0, t_outside_c: r.tOut, time_minutes: r.durationMin,
          ua_coefficient: r.uaTotal, method: 'cooling_curve' };

    const resp = await fetch('./thermal/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(config),
    });
    if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
    alert(t('cal_saved_alert'));
    await loadAndDisplayConfig();
  } catch (e) {
    alert(t('err_save_cal') + e.message);
  }
});

// Analyze heaters — Step 4: full heat balance
elAnalyzeBtn.addEventListener('click', async () => {
  const tInside    = parseFloat(elTInsideTarget.value);
  const tOutside   = parseFloat(elTOutsideAnalysis.value);
  const qMin       = parseFloat(elQMinAnalysis?.value);
  const numBirds   = parseInt(elNumBirdsAnalysis?.value, 10);
  const birdWeight = parseFloat(elBirdWeightAnalysis?.value);

  if (isNaN(tInside) || isNaN(tOutside) || isNaN(qMin) || isNaN(numBirds) || isNaN(birdWeight)) {
    elAnalysisResult.innerHTML = `<div class="danger">${t('err_enter_all_fields')}</div>`;
    return;
  }

  try {
    const r = await fetch('./thermal/analyze-heaters', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        t_inside_target: tInside,
        t_outside:       tOutside,
        q_min_m3h:       qMin,
        num_birds:       numBirds,
        bird_weight_kg:  birdWeight,
      })
    });

    if (!r.ok) {
      const errText = await r.text();
      throw new Error(errText);
    }

    const data = await r.json();

    const dutyCyclePct = data.duty_cycle_percent.toFixed(1);
    const qWalls       = data.q_walls_kw.toFixed(1);
    const qVent        = data.q_ventilation_kw.toFixed(1);
    const qBirds       = data.q_birds_kw.toFixed(1);
    const qHeater      = data.q_heater_required_kw.toFixed(1);
    const birdFrac     = (data.bird_heat_fraction * 100).toFixed(0);
    const combAir      = data.combustion_air_m3h.toFixed(0);

    // Цвет duty cycle: зелёный → жёлтый → красный
    const dutyColor = data.duty_cycle >= 0.95 ? 'var(--danger,#e05252)'
                    : data.duty_cycle >= 0.75 ? 'var(--warning,#f4b942)'
                    : 'var(--success,#4caf50)';

    const overloadBanner = !data.heater_covers_need
      ? `<div class="danger" style="padding:6px 8px; border-radius:4px; margin-top:4px;">${t('heater_overload_warn')}</div>`
      : '';

    const airSection = data.combustion_air_m3h > 0
      ? `<div class="kv" style="background:var(--warning-bg,#3a2f1a); padding:8px; border-radius:4px; border-left:3px solid var(--warning,#f4b942);">
           <span>${t('combustion_lbl')}</span>
           <span><strong>${combAir} ${t('unit_m3h')}</strong></span>
         </div>
         <p class="muted" style="margin:4px 0 0 0; font-size:12px;">${t('air_added_hint')}</p>`
      : `<p class="muted" style="margin:8px 0 0 0;">${t('no_combustion')}</p>`;

    elAnalysisResult.innerHTML = `
      <div style="padding:12px; background:var(--card); border:1px solid var(--border); border-radius:8px; margin-top:12px;">
        <strong>${t('analysis_title')}</strong>
        <div style="margin-top:10px; display:grid; gap:6px;">

          <div style="font-size:11px; color:var(--muted); font-weight:600; text-transform:uppercase; letter-spacing:.5px;">
            ${t('heat_balance_title')}
          </div>
          <div class="kv"><span>${t('q_walls_lbl')}</span><span>${qWalls} ${t('unit_kw')}</span></div>
          <div class="kv"><span>${t('q_ventilation_lbl')}</span><span>${qVent} ${t('unit_kw')}</span></div>
          <div class="kv">
            <span>${t('q_birds_lbl')}</span>
            <span>−${qBirds} ${t('unit_kw')} <span class="muted" style="font-size:12px;">(${birdFrac}% ${t('bird_heat_pct_lbl')})</span></span>
          </div>

          <div class="kv" style="border-top:1px solid var(--border); padding-top:8px; font-weight:600;">
            <span>${t('q_heater_lbl')}</span>
            <span style="color:${dutyColor}">${qHeater} ${t('unit_kw')} &nbsp;·&nbsp; ${dutyCyclePct}%</span>
          </div>
          ${overloadBanner}

          <div style="font-size:11px; color:var(--muted); font-weight:600; text-transform:uppercase; letter-spacing:.5px; margin-top:8px;">
            ${t('status_lbl')}
          </div>
          <div style="padding:6px 8px; background:var(--bg); border-radius:4px; font-size:13px;">
            ${t('ht_status_' + data.status_code, {
              birds_kw: qBirds, deficit_kw: data.heater_deficit_kw.toFixed(1), duty_pct: data.duty_cycle_percent.toFixed(0),
            })}
          </div>

          ${airSection}
        </div>
      </div>
    `;

  } catch (e) {
    elAnalysisResult.innerHTML = `<div class="danger">${t('err_prefix')}${String(e)}</div>`;
  }
});

// Load current configuration
async function loadConfig() {
  try {
    const r = await fetch('./thermal/config');
    if (r.ok) return await r.json();
  } catch (e) {
    console.error('Failed to load config:', e);
  }
  return { house_id: null, building: null, heater: null, calibration: null };
}

async function loadAndDisplayConfig() {
  const config = await loadConfig();
  let html = '';

  if (config.house_id) {
    html += `<div style="margin-bottom:10px; padding:6px 12px; background:var(--bg); border-radius:6px; font-size:13px;">
      🏠 ${t('cfg_house_lbl')}: <strong>${escapeHtml(t('house_tab', { id: config.house_id }))}</strong>
    </div>`;
  }

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
        <div class="kv"><span>${t('cfg_lwh')}</span><span>${b.length_m} × ${b.width_m} ${uM}</span></div>
        <div class="kv"><span>${t('label_height_eff')}</span><span>${b.height_m} ${uM}</span></div>
        <div class="kv"><span>${t('cfg_volume')}</span><span>${volume} ${uM3}</span></div>
        <div class="kv"><span>${t('cfg_floor')}</span><span>${area} ${uM2}</span></div>
      </div>
    `;
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
  } else {
    html += `<div class="muted">${t('cfg_heater_none')}</div>`;
  }

  if (config.calibration) {
    const c = config.calibration;
    const uaStr = c.ua_coefficient != null
      ? `${c.ua_coefficient.toFixed(1)} ${t('cfg_ua_unit')}`
      : '—';
    html += `
      <div>
        <strong>${t('cfg_cal_h')}</strong>
        <div class="kv"><span>${t('cfg_ua')}</span><span>${uaStr}</span></div>
        <div class="kv"><span>${t('cfg_method')}</span><span>${t(c.method === 'cooling_curve' ? 'cfg_method_curve' : 'cfg_method_air_only')}</span></div>
        ${c.method === 'cooling_curve' && c.points
          ? `<div class="kv"><span>${t('cfg_test_cond')}</span><span>${t('cfg_curve_val', { n: c.points.length - 1, time: Math.round(c.time_minutes), tout: c.t_outside_c })}</span></div>`
          : c.method === 'cooling_curve' ? ''
          : `<div class="kv"><span>${t('cfg_test_cond')}</span><span>${t('cfg_test_val', { t0: c.t_initial_c, t1: c.t_final_c, time: c.time_minutes, tout: c.t_outside_c })}</span></div>
             <p class="warn" style="margin:6px 0 0;font-size:12px;">⚠️ ${t('cfg_air_only_recalibrate')}</p>`}
      </div>
    `;
  } else {
    html += `<div class="muted">${t('cfg_cal_none')}</div>`;
  }

  elCurrentConfig.innerHTML = html;
}

// Заполняет поля форм из сохранённого конфига — только при инициализации страницы.
// После сохранений форму не трогаем: пользователь только что сам ввёл значения.
async function fillFormFromConfig() {
  const config = await loadConfig();
  // Ответ сервера приходит ПОСЛЕ того, как селектор корпусов уже заполнил форму
  // размерами выбранного корпуса (стена + конёк). Серверный конфиг хранит один корпус
  // и только эффективную высоту — перезапись затирала бы размеры другого корпуса
  // и терялся конёк. Поэтому: корпус выбран → размеры из его вкладки, не с сервера.
  const selectedHouse = getSelectedHouseId();
  const sameHouse = selectedHouse == null || config.house_id == null || config.house_id === selectedHouse;
  if (config.building && selectedHouse == null) {
    elLength.value     = config.building.length_m;
    elWidth.value      = config.building.width_m;
    // height_m — эффективная высота (среднее стены и конька), ставим в поле стены как
    // начальное приближение; пользователь при необходимости скорректирует и введёт конёк
    elHeightWall.value  = config.building.height_m;
    elHeightRidge.value = '';
    updateDimensionsDisplay();
  }
  // Горелки — свойство корпуса: подставляем только для того же корпуса
  if (config.heater && sameHouse) {
    elHeaterType.value  = config.heater.heater_type;
    elHeaterPower.value = config.heater.total_power_kw;
    updateGasInfoVisibility();
  }
}

// Initialize
updateDimensionsDisplay();
updateGasInfoVisibility();
fillFormFromConfig();
loadAndDisplayConfig();
