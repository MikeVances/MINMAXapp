// i18n.js — Translation engine for MINMAXapp
// Language data is loaded from i18n/<lang>.js files BEFORE this script.
// Usage in HTML:  <tag data-i18n="key">fallback</tag>
// Usage in JS:    t('key') or t('key', { var: value })

(function () {

  // Languages loaded by <script> tags; each sets window.LOCALES.<lang>
  window.LOCALES = window.LOCALES || {};

  // Restore last choice, default to EN.
  // localStorage бросает исключение при запрете хранилища (приватный режим, политика
  // браузера) — без try/catch падал этот скрипт, а с ним переводы на ВСЕХ страницах
  let currentLang = 'en';
  try { currentLang = localStorage.getItem('lang') || 'en'; } catch (e) { /* остаётся EN */ }
  if (!window.LOCALES[currentLang]) currentLang = 'en';

  // ── t(): synchronous lookup with EN fallback ──────────────────────────────
  window.t = function (key, vars) {
    const locale   = window.LOCALES[currentLang] || {};
    const fallback = window.LOCALES['en']         || {};
    let str = locale[key] !== undefined ? locale[key] : fallback[key];
    if (str === undefined) str = key; // last resort: echo the key
    if (vars && typeof str === 'string') {
      // Число в параметре — в формате языка: «не больше 0,5», а не «0.5».
      // Параметры ошибок сервера (pydantic ctx, {code, params}) приходят числами.
      str = str.replace(/\{(\w+)\}/g, (_, k) => {
        const v = vars[k];
        if (v === undefined) return '{' + k + '}';
        return typeof v === 'number' ? window.fmtNum(v) : v;
      });
    }
    return str;
  };

  // ── Числа для человека ────────────────────────────────────────────────────
  // toFixed всегда пишет точку, а ru/de/fr/pl ставят десятичную запятую и делят
  // тысячи («34 000 м³/ч», «1.250,5» у de). Только для ТЕКСТА: координатам SVG и
  // value полей ввода нужна точка — там остаётся toFixed.
  // digits не задан — до 3 знаков без хвостовых нулей; задан — ровно столько.
  const numberFormats = {};
  window.fmtNum = function (value, digits) {
    if (value === null || value === undefined || value === '') return '—';
    let n = Number(value);
    if (!Number.isFinite(n)) return '—';
    // −0,04 с одним знаком — это «0,0», а не «-0,0»
    if (digits !== undefined && Number(n.toFixed(digits)) === 0) n = 0;
    const key = currentLang + '|' + digits;
    if (!numberFormats[key]) {
      numberFormats[key] = new Intl.NumberFormat(currentLang, digits === undefined
        ? { maximumFractionDigits: 3 }
        : { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }
    return numberFormats[key].format(n);
  };

  function hasKey(key) {
    return (window.LOCALES[currentLang] || {})[key] !== undefined
        || (window.LOCALES['en']       || {})[key] !== undefined;
  }

  // ── Ошибки API → текст на языке интерфейса ────────────────────────────────
  // Сервер текста не формирует (см. backend/app/api_errors.py): detail приходит
  // строкой-кодом ('profile_not_found'), объектом {code, params} или списком
  // pydantic для 422 ([{loc, msg, type, ctx}]). Фразы — только из словаря:
  // srv_<code> для наших ошибок, val_<type> для стандартных проверок pydantic.
  // Поле запроса → ключ подписи того же поля в форме. Раньше ошибка начиналась
  // с технического пути pydantic («outside_t: …», «points.8.body_weight_g») —
  // человек его в форме не видит (аудит 2026-10-18). Поле без подписи (служебное,
  // форма его не вводит) показываем без пути: имя переменной не помогает.
  const FIELD_LABEL_KEY = {
    birds: 'label_bird_count', num_birds: 'label_bird_count',
    age_days: 'label_tn_age', bird_age_days: 'label_tn_age',
    outside_t: 'label_outdoor_t', t_outdoor_db_c: 'label_outdoor_t',
    t_outside: 'label_outdoor_t', t_outside_c: 'label_outdoor_t',
    outside_rh: 'label_outdoor_rh', rh_outdoor_pct: 'label_outdoor_rh',
    target_rh: 'label_target_rh', user_max_m3h: 'label_sys_max',
    house_length_m: 'label_length_m', length_m: 'label_length_m',
    house_width_m: 'label_width_m', width_m: 'label_width_m',
    house_height_m: 'label_height_eff', height_m: 'label_height_eff',
    tunnel_height_m: 'label_tn_height',
    num_fans: 'label_tn_fans', fan_capacity_m3h: 'label_tn_fan_cap',
    fan_capacity_25pa_m3h: 'label_tn_fan_cap25',
    num_inlets: 'label_num_inlets', inlet_width_m: 'label_inlet_width', inlet_height_m: 'label_inlet_height',
    measured_pressure_pa: 'label_test_pa',
    total_fan_m3h: 'label_total_fans', total_fan_25pa_m3h: 'label_ev_fans25',
    pad_type: 'label_pad_type', pad_thickness_mm: 'label_pad_thick',
    pad_length_m: 'label_pad_length', pad_height_m: 'label_pad_height',
    water_supply_t_c: 'label_water_t',
    t_inside_target: 'label_t_inside', t_inside_target_c: 'label_t_inside',
    q_min_m3h: 'label_q_min_analysis', bird_weight_kg: 'label_bird_weight_analysis',
    heater_type: 'heater_type_lbl', total_power_kw: 'heating_cap_lbl', ua_coefficient: 'ua_coeff_lbl',
    day: 'col_day', body_weight_g: 'col_weight', min_temp_c: 'col_min_temp', rv_percent: 'col_rh',
    name: 'profile_name_lbl', default_growth_profile: 'growth_profile_lbl',
    cycle_days: 'cycle_days_lbl', v_tunnel_ms: 'v_tunnel_lbl', safety_factor_qmin: 'safety_factor_lbl',
    tunnel_min_day: 'tunnel_min_day_lbl', tunnel_min_temp_c: 'tunnel_min_temp_lbl',
    total_mortality_pct: 'mortality_lbl',
  };

  function fieldLabel(name) {
    const key = FIELD_LABEL_KEY[name];
    return key && hasKey(key) ? t(key).replace(/:\s*$/, '') : null;
  }

  // loc → подпись для человека: ['body', 'points', 8, 'body_weight_g'] при
  // отправленной точке дня 14 → «День 14 · Масса, г». sent — тело запроса
  // (объект или JSON-строка); без него точку называем порядковым номером.
  function locText(loc, sent) {
    const parts = (loc || []).filter(p => p !== 'body' && p !== 'query' && p !== 'path');
    const out = [];
    let node = sent;
    for (let i = 0; i < parts.length; i++) {
      const p = parts[i];
      const next = parts[i + 1];
      if (typeof next === 'number') {
        // Элемент списка: у точки профиля есть день — он понятнее индекса
        const item = node && Array.isArray(node[p]) ? node[p][next] : null;
        out.push(item && item.day != null ? `${t('col_day')} ${item.day}` : `№ ${next + 1}`);
        node = item;
        i++;
        continue;
      }
      const label = fieldLabel(p);
      if (label) out.push(label);
      node = node && typeof node === 'object' ? node[p] : null;
    }
    return out.join(' · ');
  }

  function validationItemText(item, sent) {
    // Список наших ошибок (валидация записи дневника): каждая — {code, params}
    if (item && typeof item.code === 'string') {
      return hasKey('srv_' + item.code) ? t('srv_' + item.code, item.params || {}) : item.code;
    }
    const field = locText(item.loc, sent);
    let text;
    // Наши проверки внутри моделей pydantic бросают CalcError: его код лежит в ctx.error
    const own = item.ctx && item.ctx.error && typeof item.ctx.error === 'object' ? item.ctx.error : null;
    if (own && own.code && hasKey('srv_' + own.code)) {
      text = t('srv_' + own.code, own.params || {});
    } else if (hasKey('val_' + item.type)) {
      text = t('val_' + item.type, item.ctx || {});
    } else {
      text = item.msg || item.type || '';
    }
    return field ? field + ': ' + text : text;
  }

  window.apiErrorText = function (body, status, sent) {
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body;
    if (typeof detail === 'string' && hasKey('srv_' + detail)) return t('srv_' + detail);
    if (typeof sent === 'string') { try { sent = JSON.parse(sent); } catch (e) { sent = null; } }
    if (Array.isArray(detail)) return detail.map(item => validationItemText(item, sent)).join('; ');
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
      return hasKey('srv_' + detail.code) ? t('srv_' + detail.code, detail.params || {}) : detail.code;
    }
    // 5xx: подробности только в журнале сервера, клиенту — общая фраза
    if (status >= 500) return t('srv_internal_error');
    if (typeof detail === 'string' && detail) return detail;
    return status ? 'HTTP ' + status : '';
  };

  // Неуспешный Response → Error с переведённым сообщением (e.status, e.body — для разбора)
  window.apiError = async function (resp, sent) {
    let body = null;
    try { body = await resp.json(); } catch (e) { /* тело не JSON — покажем статус */ }
    const err = new Error(window.apiErrorText(body, resp.status, sent));
    err.status = resp.status;
    err.body   = body;
    return err;
  };

  // ── Подпись корпуса ───────────────────────────────────────────────────────
  // Числовой id — «порядковый» корпус из вкладок по умолчанию, его подписываем
  // через словарь (House 1 / Птичник 1). Любое другое имя дал пользователь
  // (или оно создано как «Новое помещение 3» на его языке) — показываем как есть.
  window.houseLabel = function (id) {
    const s = String(id ?? '');
    return /^\d+$/.test(s) ? t('house_tab', { id: s }) : s;
  };

  // ── applyDOM(): translate all data-i18n* attributes in the document ───────
  function applyDOM() {
    const locale   = window.LOCALES[currentLang] || {};
    const fallback = window.LOCALES['en']         || {};

    function val(key) {
      return locale[key] !== undefined ? locale[key] : fallback[key];
    }

    document.querySelectorAll('[data-i18n]').forEach(el => {
      const v = val(el.dataset.i18n);
      if (v !== undefined) el.textContent = v;
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
      const v = val(el.dataset.i18nHtml);
      if (v !== undefined) el.innerHTML = v;
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const v = val(el.dataset.i18nPlaceholder);
      if (v !== undefined) el.placeholder = v;
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      const v = val(el.dataset.i18nTitle);
      if (v !== undefined) el.title = v;
    });

    document.documentElement.lang = currentLang;

    const tk = document.body && document.body.dataset.pageTitle;
    if (tk) { const v = val(tk); if (v) document.title = v; }
  }

  // ── setLang(): switch language in-place, no page reload ───────────────────
  function setLang(lang) {
    if (!window.LOCALES[lang]) return; // file not loaded
    currentLang = lang;
    try { localStorage.setItem('lang', lang); } catch (e) { /* выбор не запомнится */ }
    applyDOM();
    updateSwitcherUI();
    // applyDOM переводит только разметку с data-i18n. Всё, что страницы собирают
    // в JS (вкладки корпусов, результаты расчётов), они перерисовывают сами по этому событию.
    document.dispatchEvent(new CustomEvent('i18n:change', { detail: { lang } }));
  }

  // ── Language switcher UI ──────────────────────────────────────────────────
  const LANG_META = [
    { code: 'en', flag: '🇬🇧', label: 'EN' },
    { code: 'ru', flag: '🇷🇺', label: 'RU' },
    { code: 'pl', flag: '🇵🇱', label: 'PL' },
    { code: 'de', flag: '🇩🇪', label: 'DE' },
    { code: 'fr', flag: '🇫🇷', label: 'FR' },
  ];

  let switcherBar = null;

  function updateSwitcherUI() {
    if (!switcherBar) return;
    LANG_META.forEach(({ code }) => {
      const btn = switcherBar.querySelector('[data-lang="' + code + '"]');
      if (!btn) return;
      const active = code === currentLang;
      btn.classList.toggle('is-active', active);   // вид — в styles.css (.lang-btn)
    });
  }

  function injectLangSwitcher() {
    // Позиционирование — в styles.css (.lang-switcher): на десктопе fixed в углу,
    // на узком экране обычная строка над шапкой, чтобы не налезать на заголовок
    switcherBar = document.createElement('div');
    switcherBar.className = 'lang-switcher';

    LANG_META.forEach(({ code, flag, label }) => {
      const btn = document.createElement('button');
      btn.className       = 'btn btn-secondary lang-btn';
      btn.dataset.lang    = code;
      btn.textContent     = flag + ' ' + label;

      const hasData = !!(window.LOCALES[code] && Object.keys(window.LOCALES[code]).length > 0);
      if (!hasData) {
        // Stub file loaded but empty — dim and disable
        btn.disabled          = true;   // приглушение — .lang-btn:disabled
        btn.title             = 'Translation in progress';
      } else {
        btn.onclick = () => setLang(code);
      }

      switcherBar.appendChild(btn);
    });

    // В начало body: на мобильном переключатель становится статичной строкой и
    // должен стоять над содержимым, а не под футером
    document.body.prepend(switcherBar);
    updateSwitcherUI();
  }

  // ── Public API ────────────────────────────────────────────────────────────
  window.I18N = { get lang() { return currentLang; }, t: window.t, setLang, applyDOM };

  document.addEventListener('DOMContentLoaded', () => {
    applyDOM();
    injectLangSwitcher();
  });

})();
