async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

const elTable = document.getElementById('table');
const elSave = document.getElementById('saveBtn');
const elStatus = document.getElementById('status');

let rows = [];
let cfg = { total_mortality_pct: 4.0, min_floor_0_7: 0.15, min_floor_7_14: 0.25 };

function tr(d) {
  return `<tr>
      <td>${d.day}</td>
      <td><input type="number" step="1" value="${d.body_weight_g ?? ''}" data-key="bw" data-day="${d.day}"/></td>
      <td><input type="number" step="0.1" value="${d.min_temp_c ?? ''}" data-key="t" data-day="${d.day}"/></td>
      <td><input type="number" step="0.1" value="${d.rv_percent ?? ''}" data-key="rv" data-day="${d.day}"/></td>
    </tr>`;
}

function render() {
  const head = `
    <div class="kv"><span>Падёж за цикл</span><span><input id="mort_total" type="number" step="0.01" value="${cfg.total_mortality_pct}"> %</span></div>
    <div class="kv"><span>Порог Qmin 0–7 дн (м³/ч/бр)</span><span><input id="floor_0_7" type="number" step="0.001" value="${cfg.min_floor_0_7}"></span></div>
    <div class="kv"><span>Порог Qmin 7–14 дн (м³/ч/бр)</span><span><input id="floor_7_14" type="number" step="0.001" value="${cfg.min_floor_7_14}"></span></div>`;
  const table = `
    <table>
      <thead><tr><th>День</th><th>Вес, г</th><th>Min Temp, °C</th><th>RH, %</th></tr></thead>
      <tbody>
        ${rows.map(tr).join('')}
      </tbody>
    </table>`;
  elTable.innerHTML = head + table;

  elTable.querySelectorAll('tbody input').forEach(inp => {
    inp.addEventListener('change', () => {
      if (inp.id === 'mort') return; // handled separately
      const d = Number(inp.dataset.day);
      const key = inp.dataset.key;
      const val = inp.value === '' ? null : Number(inp.value);
      const row = rows.find(x => x.day === d);
      if (row) {
        if (key === 'bw') row.body_weight_g = val;
        if (key === 't') row.min_temp_c = val;
        if (key === 'rv') row.rv_percent = val;
      }
    });
  });

  const mort = document.getElementById('mort_total');
  const f1 = document.getElementById('floor_0_7');
  const f2 = document.getElementById('floor_7_14');
  mort.addEventListener('change', ()=>{ cfg.total_mortality_pct = Number(mort.value || 0); });
  f1.addEventListener('change', ()=>{ cfg.min_floor_0_7 = Number(f1.value || 0); });
  f2.addEventListener('change', ()=>{ cfg.min_floor_7_14 = Number(f2.value || 0); });
}

async function loadAll(){
  rows = await fetchJSON('/settings/day-master');
  cfg = await fetchJSON('/settings/app-config');
  render();
}

async function saveAll(){
  try {
    elSave.disabled = true; elStatus.textContent = 'Сохранение…';
    await fetchJSON('/settings/day-master', { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(rows) });
    await fetchJSON('/settings/app-config', { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(cfg) });
    elStatus.textContent = 'Сохранено';
  } catch(e) {
    elStatus.textContent = 'Ошибка: ' + String(e);
  } finally {
    elSave.disabled = false;
  }
}

elSave.addEventListener('click', saveAll);
loadAll();
