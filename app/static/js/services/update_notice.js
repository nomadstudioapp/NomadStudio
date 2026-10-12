'use strict';
// "Nomad Studio X is ready to install" — the one place an update asks for
// the user's attention (docs/APP_UPDATES.md §6.2). The app finds, downloads
// and prepares new versions by itself (app/services/update_check.py); this
// notice offers the restart. Not modal, never restarts on its own.
//
// Also says "Nomad Studio was updated to X" once after an update. Hidden on
// Settings (its Updates section shows the same), for viewers on another
// device (only this computer can restart the app) and after "Later" until the
// app is opened again in a new tab.
(function () {
  // A local GET: cheap. Faster while an update is downloading, so the notice
  // appears as soon as it is ready.
  var POLL_MS = 60 * 1000;
  var POLL_BUSY_MS = 10 * 1000;
  var timer = null;
  var ICON =
    '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>';

  var el = null;
  var shownKey = '';
  var restarting = false;

  function t(key, fallback, vars) {
    var text = (window.NomadI18n && window.NomadI18n.t) ? window.NomadI18n.t(key, fallback) : fallback;
    Object.keys(vars || {}).forEach(function (k) { text = text.split('{' + k + '}').join(String(vars[k])); });
    return text;
  }

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function later(key) {
    try { return window.sessionStorage.getItem('nomad-update-later') === key; } catch (_) { return false; }
  }

  function setLater(key) {
    try { window.sessionStorage.setItem('nomad-update-later', key); } catch (_) { /* private mode */ }
  }

  function onSettings() {
    return /^\/settings/.test(window.location.pathname);
  }

  function notesList(notes) {
    if (!notes) return '';
    var lang = (window.NomadI18n && window.NomadI18n.getLanguage && window.NomadI18n.getLanguage()) || 'en';
    var h = notes.highlights || {};
    var lines = h[lang] || h[notes.default_lang] || h.en || [];
    if (!lines.length) return '';
    return '<ul class="ns-update-notice-notes">' + lines.slice(0, 3).map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>';
  }

  function ensureEl() {
    if (el && document.body.contains(el)) return el;
    el = document.createElement('div');
    el.className = 'ns-update-notice';
    el.setAttribute('role', 'status');
    el.hidden = true;
    document.body.appendChild(el);
    el.addEventListener('click', onClick);
    return el;
  }

  function hide() {
    if (el) el.hidden = true;
    shownKey = '';
  }

  function show(key, html) {
    ensureEl();
    shownKey = key;
    el.innerHTML = html;
    el.hidden = false;
  }

  function render(state) {
    if (restarting) return;
    if (!state || !state.local || onSettings()) return hide();
    var r = state.lastResult;
    if (r) {
      var msg = r.ok
        ? t('settings.updates.resultOk', 'Nomad Studio was updated to {to}.', { to: r.to })
        : t('updateNotice.failed', 'Could not update to {to}. Nomad Studio went back to {from}; your data was not changed. Settings › Updates says why.', { to: r.to, from: r.from || '—' });
      return show('result:' + r.to,
        '<p class="ns-update-notice-title">' + ICON + esc(msg) + '</p>' +
        '<div class="ns-update-notice-actions">' +
          '<button type="button" class="btn settings-btn-secondary" data-un-dismiss>' + esc(t('settings.updates.dismiss', 'OK')) + '</button>' +
        '</div>');
    }
    var p = state.pending;
    var job = state.job;
    if (!p || (job && job.state === 'running')) return hide();
    var key = 'ready:' + p.to;
    if (later(key)) return hide();
    show(key,
      '<p class="ns-update-notice-title">' + ICON + esc(t('settings.updates.ready', 'Nomad Studio {to} is ready to install', { to: p.to })) + '</p>' +
      notesList(p.notes) +
      '<p class="ns-update-notice-text">' + esc(t('updateNotice.hint', 'Nomad Studio restarts with the new version in about a minute. Your data stays; a backup was made.')) + '</p>' +
      '<div class="ns-update-notice-actions">' +
        '<button type="button" class="btn settings-btn-ghost" data-un-later>' + esc(t('updateNotice.later', 'Later')) + '</button>' +
        '<button type="button" class="btn settings-btn-secondary" data-un-apply="' + esc(p.to) + '">' + esc(t('settings.updates.restart', 'Restart and update')) + '</button>' +
      '</div>');
  }

  function refresh() {
    if (restarting) return;
    clearTimeout(timer);
    fetch('/api/updates', { cache: 'no-store' })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (state) {
        render(state);
        var busy = state && state.job && state.job.state === 'running';
        timer = setTimeout(refresh, busy ? POLL_BUSY_MS : POLL_MS);
      })
      .catch(function () { timer = setTimeout(refresh, POLL_MS); /* the server may be restarting */ });
  }

  function post(url) {
    return fetch(url, { method: 'POST', cache: 'no-store' }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (json) {
        if (!res.ok || json.ok === false) throw new Error(json.error || ('HTTP ' + res.status));
        return json;
      });
    });
  }

  function waitForRestart(to, from) {
    var started = Date.now();
    function poll() {
      fetch('/api/health', { cache: 'no-store' })
        .then(function (res) { return res.json(); })
        .then(function (health) {
          // New version up, or the old one back after a rollback: reload either way.
          if (health.version === to || (Date.now() - started > 15000 && health.version === from)) {
            window.location.reload();
            return;
          }
          setTimeout(poll, 2000);
        })
        .catch(function () { setTimeout(poll, 2000); });
    }
    setTimeout(poll, 3000);
  }

  function onClick(e) {
    if (e.target.closest('[data-un-later]')) {
      setLater(shownKey);
      return hide();
    }
    if (e.target.closest('[data-un-dismiss]')) {
      post('/api/updates/dismiss-result').catch(function () {});
      return hide();
    }
    var apply = e.target.closest('[data-un-apply]');
    if (apply) {
      var to = apply.getAttribute('data-un-apply');
      var from = '';
      el.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
      fetch('/api/health', { cache: 'no-store' })
        .then(function (res) { return res.json(); })
        .then(function (health) { from = health.version || from; })
        .catch(function () {})
        .then(function () { return post('/api/updates/apply'); })
        .then(function () {
          restarting = true;
          el.innerHTML = '<p class="ns-update-notice-title">' + ICON +
            esc(t('settings.updates.restarting', 'Restarting into Nomad Studio {to}… this page reloads by itself.', { to: to })) + '</p>';
          waitForRestart(to, from);
        })
        .catch(function (error) {
          el.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
          var msg = el.querySelector('.ns-update-notice-text');
          if (msg) msg.textContent = error.message;
        });
    }
  }

  function start() {
    timer = setTimeout(refresh, 1500);
    document.addEventListener('nomad-i18n-applied', refresh);
    // shell_router.js swaps pages without a reload: re-check (Settings hides it).
    window.addEventListener('oj:shell:navigate-end', function () { setTimeout(refresh, 300); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
