// ui.js — смена тона элемента из JS без захардкоженных цветов.
//
// Тон — это класс из styles.css (раздел «Тоны»): c-ok, bg-ok-bg, edge-danger…
// Скрипт говорит «это хорошо / внимание / ступень 3 шкалы», а конкретный цвет
// задаёт тема (styles.css + data/theme.css). Раньше JS сам писал цвет в стиль, и
// смена палитры не доходила до динамических статусов.
//
// Классы одной группы взаимоисключающие: перед добавлением снимаем прежний тон.
// Снимаются только тоны из списка — статичные утилиты элемента не трогаем.

(function () {
  const TONES = ['text', 'muted', 'accent', 'accent-2', 'ok', 'warn', 'danger',
                 'grade-1', 'grade-2', 'grade-3', 'grade-4',
                 'bg', 'card', 'ok-bg', 'danger-bg'];

  function swapTone(el, prefix, tone) {
    if (!el) return;
    TONES.forEach(name => el.classList.remove(prefix + name));
    if (tone) el.classList.add(prefix + tone);
  }

  // tone = null/'' — вернуть цвет, заданный классами элемента (например .muted)
  window.setTone = (el, tone) => swapTone(el, 'c-', tone);      // цвет текста
  window.setBg   = (el, tone) => swapTone(el, 'bg-', tone);     // фон
  window.setEdge = (el, tone) => swapTone(el, 'edge-', tone);   // цвет левой кромки

  // ── Общие помощники страниц ────────────────────────────────────────────────
  // Были в трёх копиях (calibration.js, settings.js, редактор профиля) — копии
  // расходились: одна выводила null как «null», другая как пустую строку.

  // Экранирование для innerHTML: имена корпусов и профилей пишет пользователь,
  // а приходят они с сервера — от любого клиента (без этого — stored XSS)
  window.escapeHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  // fetch → JSON; ошибка сервера → Error с текстом на языке интерфейса (apiError
  // из i18n.js). Тело запроса передаётся, чтобы «points.8.body_weight_g» стало
  // «День 14 · Масса, г»
  window.fetchJSON = async (url, opts) => {
    const r = await fetch(url, opts);
    if (!r.ok) throw await apiError(r, opts && opts.body);
    return r.json();
  };

  // Строка статуса вместо alert(). alert блокирует страницу и пропадает после
  // нажатия «OK» — на телефоне его закрывают не читая, и что случилось, уже не
  // узнать. Статус остаётся рядом с кнопкой, которая его вызвала.
  //
  // Текст задаётся функцией, а не строкой: при смене языка (событие i18n:change)
  // все показанные статусы пересобираются на новом языке. textFn = null — скрыть.
  const shown = new Set();
  window.setStatus = (el, textFn, tone) => {
    if (!el) return;
    el._statusText = textFn || null;
    if (textFn) shown.add(el); else shown.delete(el);
    el.textContent = textFn ? textFn() : '';
    el.hidden = !textFn;
    swapTone(el, 'c-', textFn ? tone : null);
  };
  document.addEventListener('i18n:change', () => {
    shown.forEach(el => { if (el._statusText) el.textContent = el._statusText(); });
  });

  // ── Вкладки (корпуса на главной, инструменты в калькуляторах) ──────────────
  // Вид вкладок держится на классе .active. Экранный диктор его не видит: без
  // role=tab/aria-selected вкладки звучали как ряд одинаковых кнопок, и не было
  // слышно, какая открыта. Перемещающийся tabindex: Tab заходит в ряд один раз,
  // дальше стрелки — как у вкладок операционной системы (WAI-ARIA Tabs).
  window.Tabs = {
    init(container) {
      container.setAttribute('role', 'tablist');
      container.addEventListener('keydown', e => {
        const step = { ArrowRight: 1, ArrowLeft: -1, Home: 'first', End: 'last' }[e.key];
        if (step === undefined) return;
        const tabs = [...container.querySelectorAll('[role="tab"]:not([disabled])')];
        const i = tabs.indexOf(document.activeElement);
        if (i < 0) return;
        e.preventDefault();
        const next = step === 'first' ? tabs[0]
                   : step === 'last'  ? tabs[tabs.length - 1]
                   : tabs[(i + step + tabs.length) % tabs.length];
        next.click();
        // Вкладки корпусов пересобираются по клику — фокус ставим на ту, что
        // в итоге выбрана (переход могла отклонить неверная форма)
        (container.querySelector('[aria-selected="true"]') || next).focus();
      });
      window.Tabs.sync(container);
    },
    // Атрибуты — по классу .active; звать после каждой смены вкладки
    sync(container) {
      container.querySelectorAll(':scope > button').forEach(b => {
        const on = b.classList.contains('active');
        b.setAttribute('role', 'tab');
        b.setAttribute('aria-selected', on ? 'true' : 'false');
        b.tabIndex = on ? 0 : -1;
      });
    },
  };

  // ── Модальные окна ─────────────────────────────────────────────────────────
  // Escape закрывает (как «Отмена»), Tab ходит по кругу внутри окна, а после
  // закрытия фокус возвращается на кнопку, которая окно открыла. Без этого
  // клавиатура уходила под затемнение, и окно закрывалось только мышью.
  const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

  window.Dialog = {
    open(modal, focusEl, onCancel) {
      modal._returnFocus = document.activeElement;
      modal._onCancel = onCancel;
      modal.classList.remove('hidden');
      (focusEl || modal.querySelector(FOCUSABLE))?.focus();
    },
    close(modal) {
      modal.classList.add('hidden');
      const back = modal._returnFocus;
      modal._returnFocus = null;
      if (back && document.contains(back)) back.focus();
    },
  };

  document.addEventListener('keydown', e => {
    const modal = [...document.querySelectorAll('.modal')].find(m => !m.classList.contains('hidden') && m._onCancel);
    if (!modal) return;
    if (e.key === 'Escape') { e.preventDefault(); modal._onCancel(); return; }
    if (e.key !== 'Tab') return;
    const items = [...modal.querySelectorAll(FOCUSABLE)];
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!modal.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  });
})();
