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
      str = str.replace(/\{(\w+)\}/g, (_, k) => vars[k] !== undefined ? vars[k] : '{' + k + '}');
    }
    return str;
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
  function validationItemText(item) {
    // loc = ['body', 'points', 3, 'day'] → 'points.3.day'; служебные сегменты не показываем
    const field = (item.loc || []).filter(p => p !== 'body' && p !== 'query' && p !== 'path').join('.');
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

  window.apiErrorText = function (body, status) {
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body;
    if (typeof detail === 'string' && hasKey('srv_' + detail)) return t('srv_' + detail);
    if (Array.isArray(detail)) return detail.map(validationItemText).join('; ');
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
      return hasKey('srv_' + detail.code) ? t('srv_' + detail.code, detail.params || {}) : detail.code;
    }
    // 5xx: подробности только в журнале сервера, клиенту — общая фраза
    if (status >= 500) return t('srv_internal_error');
    if (typeof detail === 'string' && detail) return detail;
    return status ? 'HTTP ' + status : '';
  };

  // Неуспешный Response → Error с переведённым сообщением (e.status, e.body — для разбора)
  window.apiError = async function (resp) {
    let body = null;
    try { body = await resp.json(); } catch (e) { /* тело не JSON — покажем статус */ }
    const err = new Error(window.apiErrorText(body, resp.status));
    err.status = resp.status;
    err.body   = body;
    return err;
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
      btn.style.opacity      = active ? '1'   : '0.55';
      btn.style.borderColor  = active ? 'var(--accent)' : 'var(--border)';
      btn.style.fontWeight   = active ? '700' : '400';
    });
  }

  function injectLangSwitcher() {
    // Позиционирование — в styles.css (.lang-switcher): на десктопе fixed в углу,
    // на узком экране обычная строка над шапкой, чтобы не налезать на заголовок
    switcherBar = document.createElement('div');
    switcherBar.className = 'lang-switcher';

    LANG_META.forEach(({ code, flag, label }) => {
      const btn = document.createElement('button');
      btn.className       = 'btn btn-secondary';
      btn.dataset.lang    = code;
      btn.style.cssText   = 'font-size:11px;padding:3px 7px;transition:opacity .15s,border-color .15s;';
      btn.textContent     = flag + ' ' + label;

      const hasData = !!(window.LOCALES[code] && Object.keys(window.LOCALES[code]).length > 0);
      if (!hasData) {
        // Stub file loaded but empty — dim and disable
        btn.disabled          = true;
        btn.style.opacity     = '0.3';
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
