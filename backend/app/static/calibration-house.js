// calibration-house.js — выбор корпуса для шага 1 калибровки (размеры из localStorage главной)
// (вынесено из calculators.html; выполняется сразу после calibration.js)

// ── House selector for Step 1 (loads dims from main-page localStorage) ──────
(function () {
  const STORE_KEY = 'vent_mvp_tabs_v1';
  const selEl     = document.getElementById('dimHouseSelect');
  const elL       = document.getElementById('length');
  const elW       = document.getElementById('width');
  const elHW      = document.getElementById('height-wall');
  const elHR      = document.getElementById('height-ridge');

  function fireInput(el) {
    // Triggers calibration.js event listeners so volume/area update
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function fillDims(tab) {
    if (!tab) return;
    if (tab.length_m)       { elL.value  = tab.length_m;       fireInput(elL);  }
    if (tab.width_m)        { elW.value  = tab.width_m;        fireInput(elW);  }
    if (tab.height_wall_m)  { elHW.value = tab.height_wall_m;  fireInput(elHW); }
    if (tab.height_ridge_m) { elHR.value = tab.height_ridge_m; fireInput(elHR); }
  }

  function buildSelector() {
    let tabs = [];
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) tabs = JSON.parse(raw) || [];
    } catch {}

    // Only show houses that have at least length or width saved
    const withDims = tabs.filter(t => t.length_m || t.width_m);

    // Подписи — из словаря: при смене языка список собирается заново, выбор сохраняется
    function fillOptions() {
      const chosen = selEl.value;
      selEl.innerHTML = '';
      if (withDims.length === 0) {
        const opt = document.createElement('option');
        opt.textContent = t('dims_no_houses');
        opt.value = '';
        selEl.appendChild(opt);
        return;
      }
      withDims.forEach((tab, idx) => {
        const opt  = document.createElement('option');
        opt.value  = idx;
        opt.dataset.houseId = tab.id ?? '';   // для calibration.js — читает при сохранении
        const name = tab.id ? houseLabel(tab.id) : `#${idx + 1}`;
        const l = tab.length_m, w = tab.width_m;
        const hw = tab.height_wall_m, hr = tab.height_ridge_m;
        let dimStr = '';
        if (l && w) dimStr = `${fmtNum(l)}×${fmtNum(w)}`;
        if (hw && hr) dimStr += ` h${fmtNum(hw)}/${fmtNum(hr)}`;
        opt.textContent = dimStr ? `${name} (${dimStr})` : name;
        selEl.appendChild(opt);
      });
      if (chosen !== '') selEl.value = chosen;
    }
    fillOptions();
    document.addEventListener('i18n:change', fillOptions);
    if (withDims.length === 0) return;

    // Auto-fill from the first house on page load
    fillDims(withDims[0]);

    selEl.addEventListener('change', () => {
      const idx = parseInt(selEl.value, 10);
      if (!isNaN(idx)) fillDims(withDims[idx]);
    });
  }

  buildSelector();
})();
