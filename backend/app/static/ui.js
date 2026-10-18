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
})();
