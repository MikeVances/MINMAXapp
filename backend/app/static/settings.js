async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

const elTable = document.getElementById('table');
const elSave = document.getElementById('saveBtn');
const elStatus = document.getElementById('status');
const elNumPoints = document.getElementById('numPoints');
const elUpdatePoints = document.getElementById('updatePointsBtn');
const elConfigSection = document.getElementById('configSection');

let anchorPoints = []; // Only user-defined anchor points
let numAnchorPoints = 7; // Default 7 points
let cfg = { total_mortality_pct: 4.0, min_floor_0_7: 0.15, min_floor_7_14: 0.25 };

// Generate evenly spaced anchor days
function generateAnchorDays(numPoints) {
  if (numPoints < 2) return [1, 42];
  if (numPoints === 2) return [1, 42];

  const days = [1]; // Always start with day 1
  const step = (42 - 1) / (numPoints - 1);

  for (let i = 1; i < numPoints - 1; i++) {
    days.push(Math.round(1 + step * i));
  }
  days.push(42); // Always end with day 42

  return days;
}

// Initialize anchor points with default values
function initializeAnchorPoints(numPoints) {
  const days = generateAnchorDays(numPoints);
  const defaultWeights = { 1: 50, 7: 200, 14: 400, 21: 650, 28: 900, 35: 1200, 42: 2400 };
  const defaultTemps = { 1: 33, 7: 31, 14: 28, 21: 25, 28: 22, 35: 20, 42: 19 };
  const defaultRH = { 1: 60, 7: 60, 14: 60, 21: 60, 28: 60, 35: 60, 42: 60 };
  // Typical ventilation rates by age (m³/h per bird)
  const defaultQmin = { 1: 0.15, 7: 0.25, 14: 0.35, 21: 0.50, 28: 0.65, 35: 0.80, 42: 1.00 };
  const defaultQmax = { 1: 0.45, 7: 1.20, 14: 2.00, 21: 3.20, 28: 4.20, 35: 5.10, 42: 6.00 };

  return days.map(day => ({
    day,
    body_weight_g: defaultWeights[day] || Math.round(50 + (2400 - 50) * (day - 1) / 41),
    min_temp_c: defaultTemps[day] || Math.round(33 - (33 - 19) * (day - 1) / 41),
    rv_percent: defaultRH[day] || 60,
    q_min_per_bird: defaultQmin[day] || (0.15 + (1.00 - 0.15) * (day - 1) / 41),
    q_max_per_bird: defaultQmax[day] || (0.45 + (6.00 - 0.45) * (day - 1) / 41)
  }));
}

function tr(d) {
  // Use defaults if value is missing
  const qmin = d.q_min_per_bird ?? getDefaultQmin(d.day);
  const qmax = d.q_max_per_bird ?? getDefaultQmax(d.day);

  return `<tr>
      <td><strong>${d.day}</strong></td>
      <td><input type="number" step="1" min="0" value="${d.body_weight_g ?? ''}" data-key="bw" data-idx="${anchorPoints.indexOf(d)}"/></td>
      <td><input type="number" step="0.1" value="${d.min_temp_c ?? ''}" data-key="t" data-idx="${anchorPoints.indexOf(d)}"/></td>
      <td><input type="number" step="0.1" min="0" max="100" value="${d.rv_percent ?? ''}" data-key="rv" data-idx="${anchorPoints.indexOf(d)}"/></td>
      <td><input type="number" step="0.01" min="0" value="${qmin}" data-key="qmin" data-idx="${anchorPoints.indexOf(d)}"/></td>
      <td><input type="number" step="0.01" min="0" value="${qmax}" data-key="qmax" data-idx="${anchorPoints.indexOf(d)}"/></td>
    </tr>`;
}

function getDefaultQmin(day) {
  // Linear interpolation: 0.15 (day 1) → 1.00 (day 42)
  return (0.15 + (1.00 - 0.15) * (day - 1) / 41).toFixed(2);
}

function getDefaultQmax(day) {
  // Linear interpolation: 0.45 (day 1) → 6.00 (day 42)
  return (0.45 + (6.00 - 0.45) * (day - 1) / 41).toFixed(2);
}

function renderConfig() {
  const unit = cfg.ventilation_unit || 'per_bird';

  elConfigSection.innerHTML = `
    <div class="card" style="margin-bottom:16px;">
      <h2>Farm parameters</h2>
      <div style="display:grid; gap:10px;">
        <div class="kv"><span>Total mortality per cycle</span><span><input id="mort_total" type="number" step="0.01" value="${cfg.total_mortality_pct}"> %</span></div>

        <div class="kv">
          <span>Qmin/Qmax unit</span>
          <span>
            <select id="ventilation_unit" style="padding:6px 10px;">
              <option value="per_bird" ${unit === 'per_bird' ? 'selected' : ''}>m³/h per bird</option>
              <option value="per_kg" ${unit === 'per_kg' ? 'selected' : ''}>m³/h per kg live weight</option>
            </select>
          </span>
        </div>
      </div>
      <p class="muted" style="font-size:12px; margin-top:12px;">
        Ventilation rates (Qmin/Qmax) are configured per age in the table below.
      </p>
    </div>`;

  const mort = document.getElementById('mort_total');
  const ventUnit = document.getElementById('ventilation_unit');

  mort.addEventListener('change', ()=>{ cfg.total_mortality_pct = Number(mort.value || 0); });
  ventUnit.addEventListener('change', ()=>{
    cfg.ventilation_unit = ventUnit.value;
    renderTable(); // Refresh table headers
  });
}

function renderTable() {
  console.log('Rendering anchor points:', anchorPoints.length);

  const unit = cfg.ventilation_unit || 'per_bird';
  const unitLabel = unit === 'per_bird' ? 'm³/h/bird' : 'm³/h/kg';
  const unitDescription = unit === 'per_bird'
    ? 'ventilation rates for this age (m³/h per bird)'
    : 'ventilation rates for this age (m³/h per kg live weight)';

  const table = `
    <div class="card">
      <h2>Anchor-point profile</h2>
      <p class="muted" style="font-size:12px; margin-bottom:12px;">
        Enter values for the selected days. Qmin and Qmax are ${unitDescription}. After saving, the system automatically interpolates all 42 days.
      </p>
      <table>
        <thead><tr>
          <th>Day</th>
          <th>Weight, g</th>
          <th>Min Temp, °C</th>
          <th>RH, %</th>
          <th>Qmin, ${unitLabel}</th>
          <th>Qmax, ${unitLabel}</th>
        </tr></thead>
        <tbody>
          ${anchorPoints.map(tr).join('')}
        </tbody>
      </table>
    </div>`;

  elTable.innerHTML = table;

  // Add event listeners to inputs
  elTable.querySelectorAll('tbody input').forEach(inp => {
    inp.addEventListener('change', () => {
      const idx = Number(inp.dataset.idx);
      const key = inp.dataset.key;
      const val = inp.value === '' ? null : Number(inp.value);
      const point = anchorPoints[idx];
      if (point) {
        if (key === 'bw') point.body_weight_g = val;
        if (key === 't') point.min_temp_c = val;
        if (key === 'rv') point.rv_percent = val;
        if (key === 'qmin') point.q_min_per_bird = val;
        if (key === 'qmax') point.q_max_per_bird = val;
      }
    });
  });
}

function render() {
  renderConfig();
  renderTable();
}

async function loadAll(){
  try {
    // Load ONLY anchor points, not the full interpolated profile
    // mode=anchors returns only the key days
    const anchorData = await fetchJSON('/settings/day-master?mode=anchors');
    console.log('✓ Loaded anchor points:', anchorData.length, 'points');

    if (anchorData && anchorData.length >= 2) {
      anchorPoints = anchorData;
      numAnchorPoints = anchorData.length;
      elNumPoints.value = anchorData.length;
      console.log('✓ Using existing anchor points:', anchorPoints.map(p => p.day));
    } else {
      // No data saved yet — initialise with 7 default points
      anchorPoints = initializeAnchorPoints(7);
      numAnchorPoints = 7;
      elNumPoints.value = 7;
      console.log('✓ Initialized with default 7 anchor points');
    }

    cfg = await fetchJSON('/settings/app-config');
    console.log('✓ Loaded app-config:', cfg);

    render();
  } catch (e) {
    console.error('✗ Error loading data:', e);
    elStatus.textContent = 'Load error: ' + String(e);
  }
}

async function saveAll(){
  try {
    elSave.disabled = true;
    elStatus.textContent = 'Saving and interpolating…';

    // Save anchor points with auto-interpolation
    const url = '/settings/day-master?auto_interpolate=true';
    await fetchJSON(url, {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(anchorPoints)
    });

    await fetchJSON('/settings/app-config', {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(cfg)
    });

    elStatus.textContent = '✅ Saved and interpolated to 42 days';
    setTimeout(() => { elStatus.textContent = ''; }, 3000);
  } catch(e) {
    elStatus.textContent = '❌ Error: ' + String(e);
  } finally {
    elSave.disabled = false;
  }
}


function updateNumPoints() {
  const newNum = Number(elNumPoints.value);
  if (newNum < 3 || newNum > 10) {
    alert('Number of points must be between 3 and 10');
    return;
  }

  // Preserve existing data where possible
  const oldDays = anchorPoints.map(p => p.day);
  const newDays = generateAnchorDays(newNum);

  const newAnchors = newDays.map(day => {
    const existing = anchorPoints.find(p => p.day === day);
    if (existing) return existing;

    // Create new point with interpolated values
    return {
      day,
      body_weight_g: Math.round(50 + (2400 - 50) * (day - 1) / 41),
      min_temp_c: Math.round(33 - (33 - 19) * (day - 1) / 41),
      rv_percent: 60
    };
  });

  anchorPoints = newAnchors;
  numAnchorPoints = newNum;
  render();
  elStatus.textContent = `✅ Updated: ${newNum} anchor points`;
  setTimeout(() => { elStatus.textContent = ''; }, 2000);
}

elSave.addEventListener('click', saveAll);
elUpdatePoints.addEventListener('click', updateNumPoints);
loadAll();
