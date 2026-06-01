// Calibration page logic

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

const elTInitial    = document.getElementById('tInitial');
const elTFinal      = document.getElementById('tFinal');
const elTOutside    = document.getElementById('tOutside');
const elTimeMinutes = document.getElementById('timeMinutes');
const elCalculateBtn      = document.getElementById('calculateBtn');
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

// ── Таймер теста охлаждения ──────────────────────────────────────────────────
const elTimerBtn     = document.getElementById('timerBtn');
const elTimerDisplay = document.getElementById('timerDisplay');
const elTimerStatus  = document.getElementById('timerStatus');

// Фиксированные температуры — отдельно от DOM, чтобы логика была явной
const T_TEST_START = 30.0;  // °C — нагреть до этой температуры
const T_TEST_END   = 25.0;  // °C — остановить таймер при этой температуре

let timerRunning   = false;
let timerInterval  = null;
let timerStartTime = null; // timestamp Date.now()

// ── Мультизонное состояние ───────────────────────────────────────────────────
let mzActive      = false;  // идёт ли мультизонный тест
let mzStopTimes   = [];     // секунды от старта для каждой зоны (null = ещё не нажата)
let mzIntervals   = {};     // setInterval для бегущего счётчика каждой зоны
let mzAvgTime     = null;   // секунды когда контроллер показал среднее 25°C (прямое измерение)

function timerFormat(totalSeconds) {
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const s = (totalSeconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function mzZoneCount() {
  return Math.min(Math.max(parseInt(document.getElementById('zoneCount')?.value) || 1, 1), 8);
}

// Перестраивает кнопки зон под текущее количество (вызывается при смене счётчика и старте)
function mzBuildUI(disabled) {
  const n         = mzZoneCount();
  const container = document.getElementById('zoneTimers');
  if (!container) return;
  if (n <= 1) { container.style.display = 'none'; container.innerHTML = ''; return; }

  container.innerHTML = '';
  container.style.display = 'block';

  // ── Блок "среднее по птичнику" — прямое измерение с дисплея контроллера ──
  const avgRow = document.createElement('div');
  avgRow.style.cssText = 'display:flex;align-items:center;gap:10px;padding:10px 12px;background:#0f1f2a;border:1px solid #1e4060;border-radius:8px;margin-bottom:12px;';
  avgRow.innerHTML = `
    <span style="flex:1;font-size:13px;line-height:1.4;">
      🌡️ <strong>${t('mz_avg_label')}</strong><br>
      <span class="muted" style="font-size:11px;">${t('mz_avg_hint')}</span>
    </span>
    <span id="mz-avg-elapsed" style="font-family:monospace;font-size:18px;min-width:70px;text-align:right;color:var(--muted);">—</span>
    <button id="mz-avg-btn" class="btn" style="padding:7px 14px;font-size:13px;background:#1e4060;color:#7dd3fc;"
      ${disabled ? 'disabled' : ''}>${t('mz_avg_mark')}</button>
    <span id="mz-avg-done" style="color:var(--ok);display:none;font-size:18px;">✓</span>`;
  container.appendChild(avgRow);
  document.getElementById('mz-avg-btn')?.addEventListener('click', () => {
    if (mzAvgTime !== null) return; // нажать можно только один раз
    mzAvgTime = Math.floor((Date.now() - timerStartTime) / 1000);
    const btn  = document.getElementById('mz-avg-btn');
    const disp = document.getElementById('mz-avg-elapsed');
    const done = document.getElementById('mz-avg-done');
    if (btn)  btn.disabled = true;
    if (disp) { disp.textContent = timerFormat(mzAvgTime); disp.style.color = 'var(--ok)'; }
    if (done) done.style.display = '';
  });

  // ── Кнопки отдельных зон ──────────────────────────────────────────────────
  for (let i = 0; i < n; i++) {
    const isFirst = i === 0, isLast = i === n - 1;
    const suffix  = isFirst ? ` <span class="muted" style="font-size:11px;">(${t('zone_entry')})</span>`
                  : isLast  ? ` <span class="muted" style="font-size:11px;">(${t('zone_far')})</span>`
                  : '';
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 10px;background:var(--bg);border-radius:6px;margin-bottom:6px;';
    row.innerHTML = `
      <span style="min-width:90px;font-weight:600;font-size:13px;">${t('zone_lbl', { n: i + 1 })}${suffix}</span>
      <span id="mz-elapsed-${i}" style="font-family:monospace;font-size:18px;min-width:70px;color:var(--muted);">—</span>
      <button id="mz-stop-${i}" class="btn" style="padding:6px 12px;font-size:13px;"
        ${disabled ? 'disabled' : ''} data-zone="${i}">${t('zone_stop_btn')}</button>
      <span id="mz-done-${i}" style="color:var(--ok);display:none;font-size:18px;">✓</span>`;
    container.appendChild(row);
    document.getElementById(`mz-stop-${i}`).addEventListener('click', () => mzStopZone(i));
  }
}

function mzStopZone(i) {
  const elapsed = Math.floor((Date.now() - timerStartTime) / 1000);
  mzStopTimes[i] = elapsed;
  clearInterval(mzIntervals[i]);

  const btn  = document.getElementById(`mz-stop-${i}`);
  const disp = document.getElementById(`mz-elapsed-${i}`);
  const done = document.getElementById(`mz-done-${i}`);
  if (btn)  btn.disabled = true;
  if (disp) { disp.textContent = timerFormat(elapsed); disp.style.color = 'var(--ok)'; }
  if (done) done.style.display = '';

  // Все зоны зафиксированы — завершаем тест автоматически
  if (mzStopTimes.every(s => s !== null)) mzFinish();
}

function mzFinish() {
  clearInterval(timerInterval);
  timerRunning = false;
  mzActive     = false;

  elTimerBtn.textContent      = t('btn_start_test');
  elTimerBtn.style.background = '';
  elTimerBtn.style.color      = '';
  elTimerDisplay.style.color  = 'var(--accent)';
  elTimerStatus.style.color   = 'var(--ok)';
  elTimerStatus.textContent   = t('mz_all_done');

  mzRenderProfile();
}

function mzCancel() {
  clearInterval(timerInterval);
  Object.values(mzIntervals).forEach(id => clearInterval(id));
  timerRunning = false;
  mzActive     = false;
  mzAvgTime    = null;

  elTimerBtn.textContent      = t('btn_start_test');
  elTimerBtn.style.background = '';
  elTimerBtn.style.color      = '';
  elTimerDisplay.textContent  = '00:00';
  elTimerDisplay.style.color  = 'var(--accent)';
  elTimerStatus.textContent   = '';

  mzBuildUI(true); // сброс кнопок зон в disabled
}

function mzRenderProfile() {
  const n      = mzZoneCount();
  const tOut   = parseFloat(elTOutside.value);
  const l      = parseFloat(elLength.value) || 0;
  const w      = parseFloat(elWidth.value)  || 0;
  const hEff   = effectiveHeight();
  const zoneL  = l > 0 ? l / n : 0;
  const zoneVol  = zoneL * w * hEff;
  const zoneArea = zoneL * w;

  const dtAvg = ((T_TEST_START - tOut) + (T_TEST_END - tOut)) / 2;
  const C_zone = zoneVol * 1.2 * 1005; // тепловая ёмкость воздуха одной зоны, Дж/°C
  const uaUnit = t('cfg_ua_unit');

  const results = mzStopTimes.map((sec, i) => {
    const coolRate = (T_TEST_START - T_TEST_END) / sec; // °C/с
    const ua       = (C_zone * coolRate) / dtAvg;       // Вт/°C
    const uaM2     = zoneArea > 0 ? ua / zoneArea : 0;
    return { zone: i + 1, sec, ua, uaM2, coolRate };
  });

  const maxUaM2 = Math.max(...results.map(r => r.uaM2));
  const avgUaM2 = results.reduce((s, r) => s + r.uaM2, 0) / n;
  const sumUA   = results.reduce((s, r) => s + r.ua,   0); // суммарный UA здания

  // Эквивалентное время для сохранения в калибровку:
  //   - прямое измерение (контроллер показал 25°C) — предпочтительно, точнее
  //   - гармоническое среднее зональных времён     — фолбэк
  const harmonicMean   = n / mzStopTimes.reduce((s, sec) => s + 1 / sec, 0);
  const buildingEquivSec = mzAvgTime ?? harmonicMean;
  const buildingEquivSrc = mzAvgTime != null ? t('mz_ua_src_direct') : t('mz_ua_src_harmonic');

  elTInitial.value    = T_TEST_START;
  elTFinal.value      = T_TEST_END;
  elTimeMinutes.value = (buildingEquivSec / 60).toFixed(3);

  // Позволяем кнопке «Сохранить калибровку» работать через стандартный обработчик
  calculatedUA   = sumUA;
  calculatedArea = l * w;

  function quality(uaM2) {
    if (uaM2 < 0.5) return { label: t('ua_quality_excellent'), bg: '#14532d', color: '#4ade80' };
    if (uaM2 < 1.0) return { label: t('ua_quality_good'),      bg: '#713f12', color: '#fbbf24' };
    if (uaM2 < 2.0) return { label: t('ua_quality_avg'),       bg: '#7c2d12', color: '#fb923c' };
    return              { label: t('ua_quality_poor'),          bg: '#450a0a', color: '#f87171' };
  }

  const rows = results.map(r => {
    const q   = quality(r.uaM2);
    const pct = maxUaM2 > 0 ? Math.round((r.uaM2 / maxUaM2) * 100) : 0;
    const isFirst = r.zone === 1, isLast = r.zone === n;
    const sfx = isFirst ? ` <span class="muted" style="font-size:11px;">(${t('zone_entry')})</span>`
               : isLast ? ` <span class="muted" style="font-size:11px;">(${t('zone_far')})</span>` : '';
    return `
      <div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px;">
          <span><strong>${t('zone_lbl', { n: r.zone })}</strong>${sfx}</span>
          <span style="color:${q.color};font-weight:700;">${r.uaM2.toFixed(2)} ${uaUnit}/м²</span>
        </div>
        <div style="background:#1a1b20;border-radius:6px;height:14px;overflow:hidden;">
          <div style="width:${pct}%;height:14px;background:${q.color};border-radius:6px;transition:width .4s;"></div>
        </div>
        <div style="font-size:11px;color:var(--muted);margin-top:3px;">
          ${t('zone_elapsed')}: ${timerFormat(r.sec)}
          &nbsp;|&nbsp; ${t('zone_cool_rate')}: ${(r.coolRate * 60).toFixed(3)} °C/${t('unit_min')}
        </div>
      </div>`;
  }).join('');

  const avgQ = quality(avgUaM2);

  document.getElementById('calibrationResult').innerHTML = `
    <div style="padding:14px;background:var(--ok-bg,#1a3a1a);border-left:3px solid var(--ok,#7bc96f);border-radius:4px;">
      <strong>📊 ${t('zone_profile_h')}</strong>
      <div style="margin-top:14px;">${rows}</div>
      <hr style="border:0;border-top:1px solid var(--border);margin:12px 0;">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span class="muted">${t('zone_avg_lbl')}</span>
        <strong>${avgUaM2.toFixed(2)} ${uaUnit}/м²</strong>
        <span style="padding:2px 10px;border-radius:10px;font-size:12px;background:${avgQ.bg};color:${avgQ.color};">${avgQ.label}</span>
      </div>
      <div style="margin-top:8px;font-size:12px;color:var(--muted);">
        ${t('mz_ua_source')}: <strong>${buildingEquivSrc}</strong>
        (${timerFormat(buildingEquivSec)})
      </div>
      <p class="muted" style="margin:10px 0 0;font-size:12px;">⚠️ ${t('zone_note')}</p>
      <p class="muted" style="margin:6px 0 0;font-size:12px;">${t('cal_save_hint')}</p>
    </div>`;

  elSaveCalibrationBtn.disabled = false;
}

// Перестраиваем UI при изменении количества зон (только если тест не идёт)
document.getElementById('zoneCount')?.addEventListener('input', () => {
  if (!timerRunning) mzBuildUI(true);
});

elTimerBtn.addEventListener('click', () => {
  // ── СТАРТ ──────────────────────────────────────────────────────────────────
  if (!timerRunning) {
    const tOut = parseFloat(elTOutside.value);
    if (isNaN(tOut)) {
      elTimerStatus.textContent = t('err_enter_outside_first');
      elTimerStatus.style.color = 'var(--danger)';
      return;
    }
    if (tOut >= T_TEST_END) {
      elTimerStatus.textContent = t('err_outside_too_warm', { t_end: T_TEST_END });
      elTimerStatus.style.color = 'var(--danger)';
      return;
    }

    timerRunning   = true;
    timerStartTime = Date.now();
    elTimerDisplay.style.color = 'var(--accent-2)';
    elTimerStatus.style.color  = '';

    // Глобальный счётчик
    timerInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - timerStartTime) / 1000);
      elTimerDisplay.textContent = timerFormat(elapsed);
    }, 500);

    if (mzZoneCount() > 1) {
      // ── МУЛЬТИЗОННЫЙ РЕЖИМ ───────────────────────────────────
      mzActive    = true;
      mzAvgTime   = null;
      mzStopTimes = new Array(mzZoneCount()).fill(null);
      mzIntervals = {};
      mzBuildUI(false); // строим кнопки зон (активные)

      elTimerStatus.textContent   = t('mz_timer_running', { n: mzZoneCount() });
      elTimerBtn.textContent      = t('mz_cancel');
      elTimerBtn.style.background = '';
      elTimerBtn.style.color      = '';

      // Запускаем живые счётчики для каждой зоны
      for (let i = 0; i < mzZoneCount(); i++) {
        mzIntervals[i] = setInterval(() => {
          const el = document.getElementById(`mz-elapsed-${i}`);
          if (el) {
            const elapsed = Math.floor((Date.now() - timerStartTime) / 1000);
            el.style.color  = 'var(--text)';
            el.textContent  = timerFormat(elapsed);
          }
        }, 500);
      }

    } else {
      // ── ОДНОЗОННЫЙ РЕЖИМ ─────────────────────────────────────
      elTimerStatus.textContent   = t('timer_running', { t_end: T_TEST_END });
      elTimerBtn.textContent      = t('btn_stop_test', { t_end: T_TEST_END });
      elTimerBtn.style.background = 'var(--danger, #ff7a7a)';
      elTimerBtn.style.color      = '#1b0b0b';
    }

  // ── СТОП / ОТМЕНА ──────────────────────────────────────────────────────────
  } else {
    if (mzActive) {
      // В мультизонном режиме кнопка = Отмена
      mzCancel();
    } else {
      // Однозонный стоп
      clearInterval(timerInterval);
      timerRunning = false;

      const elapsedSeconds = Math.floor((Date.now() - timerStartTime) / 1000);

      elTimerBtn.textContent      = t('btn_start_test');
      elTimerBtn.style.background = '';
      elTimerBtn.style.color      = '';
      elTimerDisplay.style.color  = 'var(--accent)';

      if (elapsedSeconds < 30) {
        elTimerStatus.textContent = t('err_test_too_short');
        elTimerStatus.style.color = 'var(--warn, #ffcf6b)';
        return;
      }

      elTInitial.value    = T_TEST_START;
      elTFinal.value      = T_TEST_END;
      elTimeMinutes.value = (elapsedSeconds / 60).toFixed(3);

      elTimerStatus.style.color = 'var(--ok)';
      elTimerStatus.textContent = t('timer_done', { min: (elapsedSeconds / 60).toFixed(1) });

      elCalculateBtn.click();
    }
  }
});

// ── Конец логики таймера ─────────────────────────────────────────────────────

let calculatedUA    = null;
let calculatedArea  = null;   // м² — для UA/м² качественной оценки

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
    config.house_id  = getSelectedHouseId();
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
    const r = await fetch('./thermal/calibrate', {
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

    // Считаем площадь пола из DOM — не нужно менять API
    const l = parseFloat(elLength.value);
    const w = parseFloat(elWidth.value);
    calculatedArea = (l > 0 && w > 0) ? l * w : null;

    const coolingRate = Math.abs(data.cooling_rate_per_minute);
    const uaUnit      = t('cfg_ua_unit');
    const volUnit     = t('unit_m3');
    const rateUnit    = `°C/${t('unit_min')}`;

    // Качественная оценка изоляции по UA/м²
    let qualityHtml = '';
    if (calculatedArea && calculatedArea > 0) {
      const uaPerM2 = calculatedUA / calculatedArea;
      let qLabel, qBg, qColor;
      if      (uaPerM2 < 0.5) { qLabel = t('ua_quality_excellent'); qBg = '#14532d'; qColor = '#4ade80'; }
      else if (uaPerM2 < 1.0) { qLabel = t('ua_quality_good');      qBg = '#713f12'; qColor = '#fbbf24'; }
      else if (uaPerM2 < 2.0) { qLabel = t('ua_quality_avg');       qBg = '#7c2d12'; qColor = '#fb923c'; }
      else                    { qLabel = t('ua_quality_poor');       qBg = '#450a0a'; qColor = '#f87171'; }
      qualityHtml = `
        <div style="margin-top:10px; padding:10px; background:var(--bg); border-radius:6px; display:grid; gap:6px;">
          <div class="kv"><span>${t('ua_per_m2_lbl')}</span><span>${uaPerM2.toFixed(2)} ${uaUnit}/м²</span></div>
          <div style="display:inline-block; padding:5px 14px; border-radius:20px; font-weight:700; font-size:14px; background:${qBg}; color:${qColor};">${qLabel}</div>
        </div>`;
    }

    elCalibrationResult.innerHTML = `
      <div style="padding:12px; background:var(--ok-bg,#1a3a1a); border-left:3px solid var(--ok,#7bc96f); border-radius:4px;">
        <strong>${t('cal_complete')}</strong>
        <div style="margin-top:8px; display:grid; gap:6px;">
          <div class="kv"><span>${t('ua_coeff_lbl')}</span><span><strong>${calculatedUA.toFixed(1)} ${uaUnit}</strong></span></div>
          <div class="kv"><span>${t('vol_label')}</span><span>${data.volume_m3.toFixed(1)} ${volUnit}</span></div>
          <div class="kv"><span>${t('cool_rate_lbl')}</span><span>${coolingRate.toFixed(3)} ${rateUnit}</span></div>
        </div>
        ${qualityHtml}
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
    config.house_id  = getSelectedHouseId();
    config.calibration = {
      t_initial_c:  tInitial,
      t_final_c:    tFinal,
      t_outside_c:  tOutside,
      time_minutes: timeMinutes
    };

    const r = await fetch('./thermal/config', {
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
            ${data.status_label}
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
      🏠 ${t('cfg_house_lbl')}: <strong>${t('house_tab', { id: config.house_id })}</strong>
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
        <div class="kv"><span>${t('cfg_test_cond')}</span><span>${t('cfg_test_val', { t0: c.t_initial_c, t1: c.t_final_c, time: c.time_minutes, tout: c.t_outside_c })}</span></div>
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
  if (config.building) {
    elLength.value     = config.building.length_m;
    elWidth.value      = config.building.width_m;
    // height_m — эффективная высота (среднее стены и конька), ставим в поле стены как
    // начальное приближение; пользователь при необходимости скорректирует и введёт конёк
    elHeightWall.value  = config.building.height_m;
    elHeightRidge.value = '';
    updateDimensionsDisplay();
  }
  if (config.heater) {
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
