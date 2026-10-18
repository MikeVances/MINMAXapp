// feedback.js — инжектирует кнопку и модальное окно обратной связи на любую страницу

(function () {
  document.addEventListener('DOMContentLoaded', function () {

    // ── Кнопка ───────────────────────────────────────────────────────────────
    const btn = document.createElement('button');
    btn.className     = 'btn btn-secondary feedback-trigger';   // положение — в styles.css
    btn.id            = 'feedbackTrigger';
    btn.dataset.i18n  = 'feedback_btn';
    btn.textContent   = '💬';
    document.body.appendChild(btn);

    // ── Модальное окно ────────────────────────────────────────────────────────
    const modal = document.createElement('div');
    modal.id        = 'feedbackModal';
    modal.className = 'modal hidden';
    modal.innerHTML = `
      <div class="modal-card dialog-narrow" role="dialog" aria-modal="true" aria-labelledby="feedbackTitle">
        <h3 id="feedbackTitle" class="mt-0 mb-10" data-i18n="feedback_title">Send Feedback</h3>
        <textarea id="feedbackText" class="feedback-text"
          rows="5" maxlength="2000" aria-labelledby="feedbackTitle"
          data-i18n-placeholder="feedback_placeholder"></textarea>
        <div id="feedbackStatus" class="feedback-status" role="status"></div>
        <div class="d-flex gap-8 jc-end mt-10">
          <button id="feedbackCancel" class="btn btn-secondary" data-i18n="feedback_cancel">Cancel</button>
          <button id="feedbackSend"   class="btn"               data-i18n="feedback_send">Send</button>
        </div>
      </div>`;
    document.body.appendChild(modal);

    // ── Применяем переводы если i18n уже загружен ─────────────────────────────
    if (window.I18N) window.I18N.applyDOM();

    const textEl   = modal.querySelector('#feedbackText');
    const statusEl = modal.querySelector('#feedbackStatus');
    const sendBtn  = modal.querySelector('#feedbackSend');
    const cancelBtn = modal.querySelector('#feedbackCancel');

    function openModal() {
      textEl.value    = '';
      statusEl.textContent = '';
      setTone(statusEl, null);
      Dialog.open(modal, textEl, closeModal);
    }

    function closeModal() {
      Dialog.close(modal);
    }

    btn.addEventListener('click', openModal);
    cancelBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeModal();
    });

    sendBtn.addEventListener('click', async function () {
      const text = textEl.value.trim();
      if (!text) return;

      sendBtn.disabled = true;
      statusEl.textContent = '…';
      setTone(statusEl, null);

      try {
        const resp = await fetch('./feedback', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({
            message: text,
            page:    (document.title || location.pathname).slice(0, 200),
          }),
        });

        if (resp.ok) {
          statusEl.textContent = window.t ? window.t('feedback_sent') : 'Sent!';
          setTone(statusEl, 'ok');
          setTimeout(closeModal, 1500);
        } else {
          // Сервер отвечает кодом (feedback_rate_limited, feedback_not_configured …) —
          // текст на языке интерфейса подбирает общий переводчик ошибок API
          const err = window.apiError ? await window.apiError(resp) : null;
          statusEl.textContent = (err && err.message) || (window.t ? window.t('feedback_error') : 'Error. Try again.');
          setTone(statusEl, 'danger');
        }
      } catch (_) {
        statusEl.textContent = window.t ? window.t('feedback_error') : 'Error. Try again.';
        setTone(statusEl, 'danger');
      } finally {
        sendBtn.disabled = false;
      }
    });

  });
})();
