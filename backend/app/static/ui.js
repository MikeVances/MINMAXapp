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
})();
