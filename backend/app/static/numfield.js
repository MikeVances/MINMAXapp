/*
 * Числовые поля: свой разбор вместо <input type="number">.
 *
 * Почему не type="number" (аудит 2026-10-18):
 *   • запятая (ru/de/fr/pl): браузер либо отдаёт value === "" (и +"" = 0 уходит
 *     на сервер как ноль), либо parseFloat("2,5") = 2 — молча теряется дробь;
 *   • step="0.5"/"100" запрещал реальные значения: 31.3 °C, 12 345 голов;
 *   • iOS при inputmode=decimal показывает клавиатуру с запятой — без своего
 *     разбора type=number на ней в принципе не набрать дробь.
 *
 * Разметка поля: type="text" data-num [data-int] [data-min] [data-max] [required].
 * Неверное поле подсвечивается и получает текст ошибки через setCustomValidity —
 * браузер сам покажет его у поля и не даст отправить <form>.
 */
(function () {
  'use strict';

  // Пробелы всех видов — разделители тысяч: «25 000», toLocaleString('ru')
  // ставит U+00A0, fr — узкий U+202F
  const SPACES = /[\s  ']/g;

  // Разделитель тысяч языка интерфейса: ',' у en, '.' у de, пробел у остальных
  function groupSeparator(lang) {
    try {
      const part = new Intl.NumberFormat(lang).formatToParts(12345).find(p => p.type === 'group');
      return part ? part.value : '';
    } catch (e) { return ''; }
  }

  /**
   * Разобрать то, что набрал человек.
   * Возвращает null для пустой строки и NaN для мусора — молча не подставляем ничего.
   *
   * Одиночная запятая или точка — десятичный разделитель, КРОМЕ записи вида
   * «25,000» / «1.250» на языке, где этот знак — разделитель тысяч: англичанин,
   * набравший «20,000» голов, имеет в виду двадцать тысяч, а не двадцать.
   */
  function parse(raw, lang) {
    let s = String(raw ?? '').replace(SPACES, '').replace(/−/g, '-');   // «−» из копипасты
    if (s === '') return null;

    const group = groupSeparator(lang || (window.I18N && I18N.lang) || 'en');
    if ((group === ',' || group === '.') && new RegExp('^[+-]?\\d{1,3}(\\' + group + '\\d{3})+$').test(s)) {
      s = s.split(group).join('');
    }

    // Обе разновидности разделителя сразу («1,234.5») — неоднозначно, лучше спросить
    if (s.includes(',') && s.includes('.')) return NaN;
    s = s.replace(',', '.');
    return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(s) ? Number(s) : NaN;
  }

  function attrNum(el, name) {
    const v = el.dataset[name];
    return v === undefined || v === '' ? null : Number(v);
  }

  // Код ошибки поля или null: bad | required | int | min | max
  function problem(el) {
    if (el.disabled) return null;
    const v = parse(el.value);
    if (v === null) return el.required ? 'required' : null;
    if (Number.isNaN(v)) return 'bad';
    if (el.hasAttribute('data-int') && !Number.isInteger(v)) return 'int';
    const min = attrNum(el, 'min'), max = attrNum(el, 'max');
    if (min !== null && v < min) return 'min';
    if (max !== null && v > max) return 'max';
    return null;
  }

  function fmt(n) {
    try { return Number(n).toLocaleString(window.I18N ? I18N.lang : undefined); } catch (e) { return String(n); }
  }

  // Отметить поле: рамка + текст, который браузер покажет у поля
  function mark(el) {
    const code = problem(el);
    const msg = code === null ? '' : t('num_err_' + code, { min: fmt(attrNum(el, 'min')), max: fmt(attrNum(el, 'max')) });
    el.setCustomValidity(msg);
    el.classList.toggle('is-invalid', code !== null);
    el.setAttribute('aria-invalid', code !== null ? 'true' : 'false');
    return code;
  }

  /**
   * Проверить числовые поля: контейнер (все data-num внутри) или список id —
   * список нужен там, где на одной панели несколько независимых действий
   * (калибровка): мусор в поле здания не должен блокировать анализ горелок.
   * Первое неверное поле получает фокус и подсказку браузера.
   * Возвращает true, если всё в порядке.
   */
  function validate(rootOrIds) {
    const fields = Array.isArray(rootOrIds)
      ? rootOrIds.map(id => document.getElementById(id)).filter(Boolean)
      : (rootOrIds || document).querySelectorAll('input[data-num]');
    let first = null;
    fields.forEach(el => { if (mark(el) !== null && !first) first = el; });
    if (first) { first.focus(); first.reportValidity(); }
    return first === null;
  }

  /** Число из поля (id или элемент): null — пусто, NaN — не число. */
  function value(elOrId) {
    const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
    return el ? parse(el.value) : null;
  }

  // Подсветка на лету — только для уже тронутого поля, чтобы пустая форма
  // не вспыхивала красным при открытии; при смене языка пересобираем тексты
  document.addEventListener('input', e => {
    if (e.target.matches && e.target.matches('input[data-num]')) mark(e.target);
  });
  document.addEventListener('focusout', e => {
    if (e.target.matches && e.target.matches('input[data-num]')) mark(e.target);
  });
  document.addEventListener('i18n:change', () => {
    document.querySelectorAll('input[data-num].is-invalid').forEach(mark);
  });

  // check — пересобрать подсветку поля после программной записи value
  // (значение из хранилища не порождает input/focusout)
  window.NumField = { parse, problem, validate, value, check: mark };
})();
