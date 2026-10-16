// write-token.js — токен на запись для тестовой площадки (см. backend/app/write_access.py)
//
// Если на сервере задан WRITE_TOKEN, изменяющие запросы без заголовка X-Write-Token
// получают 401 "write_token_required". Скрипт оборачивает window.fetch:
//   - к запросам PUT/POST/DELETE своего сайта добавляет сохранённый токен;
//   - на 401 спрашивает токен у пользователя, запоминает и повторяет запрос один раз.
// Расчёты (POST /calc/*) сервер пропускает без токена — для них ничего не меняется.
//
// Подключать ПОСЛЕ i18n.js (нужен t()) и ДО скриптов страницы, которые вызывают fetch.

(function () {
  const STORAGE_KEY = 'write_token';
  const HEADER      = 'X-Write-Token';
  const ERROR_CODE  = 'write_token_required';

  // localStorage бывает недоступен (приватный режим, запрет cookies) — не падаем
  function readToken() {
    try { return localStorage.getItem(STORAGE_KEY) || ''; } catch (e) { return ''; }
  }
  function storeToken(value) {
    try {
      if (value) localStorage.setItem(STORAGE_KEY, value);
      else localStorage.removeItem(STORAGE_KEY);
    } catch (e) { /* токен проживёт только до перезагрузки — это допустимо */ }
  }

  let sessionToken = readToken();

  function isWriteRequest(input, init) {
    const method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    if (method === 'GET' || method === 'HEAD') return false;
    // Только свой сайт: токен не должен уходить на чужие адреса
    const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
    return url.origin === window.location.origin;
  }

  function withToken(init, token) {
    const headers = new Headers((init && init.headers) || {});
    if (token) headers.set(HEADER, token);
    return Object.assign({}, init, { headers });
  }

  async function isTokenRejection(response) {
    if (response.status !== 401) return false;
    try {
      const body = await response.clone().json();
      return body && body.detail === ERROR_CODE;
    } catch (e) {
      return false;
    }
  }

  const originalFetch = window.fetch.bind(window);

  window.fetch = async function (input, init) {
    if (!isWriteRequest(input, init)) return originalFetch(input, init);

    const response = await originalFetch(input, withToken(init, sessionToken));
    if (!(await isTokenRejection(response))) return response;

    // Сервер требует токен (или сохранённый устарел) — спросить один раз и повторить
    const prompt = (typeof t === 'function') ? t('write_token_prompt') : 'Write token';
    const entered = window.prompt(prompt, '');
    if (!entered) return response;          // отмена — вернуть исходный 401 вызывающему коду

    sessionToken = entered.trim();
    const retry = await originalFetch(input, withToken(init, sessionToken));
    // Запоминаем только принятый токен, чтобы не хранить опечатку
    if (await isTokenRejection(retry)) sessionToken = '';
    storeToken(sessionToken);
    return retry;
  };
})();
