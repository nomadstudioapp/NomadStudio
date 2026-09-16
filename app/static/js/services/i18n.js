/* ─── Nomad Studio i18n ───────────────────────────────────────────────────
   Generic data-i18n substitution engine + the shared Language panel
   (opens like the History panel — same fixed/slide-in pattern, see
   parts/lang_panel.css). Zero dependencies, self-contained.

   Markup contract:
   - `data-i18n="hub.subtitle"`            → replaces textContent
   - `data-i18n-attr="placeholder:key"`     → replaces one or more attributes
     (comma-separated pairs: "placeholder:key,title:key2")
   - `data-i18n-lang-toggle="cs-lang-panel"` on the trigger button → id of
     the panel wrapper to toggle `.is-open` on
   - `data-i18n-lang-overlay="cs-lang-overlay"` on the same trigger → id of
     the backdrop overlay to wire up
   - `data-i18n-lang-list` on the container that should receive one button
     per language (built automatically, ZH/KO render disabled until their
     JSON exists — see LANGUAGES below)
   - `data-i18n-lang-close` on the panel's close button
   - `data-i18n-lang-current` on any element that should show the active
     language code (e.g. the toggle button label, since it's icon-less)

   - `data-i18n-n="20"` alongside data-i18n → fills {n} in the string
   - `data-i18n-literal="English text"`     → data-driven text (flow card
     names/descs/tags); looked up by its English in flow.flowLabels

   All four languages ship: en.json, es.json, zh.json, ko.json. */
(function () {
  'use strict';

  var LANG_KEY = 'oj-lang-v1';
  var LANGUAGES = [
    { id: 'en', label: 'English', ready: true },
    { id: 'es', label: 'Español', ready: true },
    { id: 'zh', label: '中文', ready: true },
    { id: 'ko', label: '한국어', ready: true }
  ];
  var cache = {};
  var packTexts = {};  // lang → text the installed packages carry (see mergePackageTexts)

  function getLanguage() {
    try { return localStorage.getItem(LANG_KEY) || 'en'; } catch (_) { return 'en'; }
  }

  function resolveKey(dict, key) {
    var parts = key.split('.');
    var node = dict;
    for (var i = 0; i < parts.length; i++) {
      if (node == null) return null;
      node = node[parts[i]];
    }
    return typeof node === 'string' ? node : null;
  }

  function literalTable(dict) {
    return (dict && dict.flow && dict.flow.flowLabels) || null;
  }

  function applyStrings(dict) {
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var value = resolveKey(dict, el.getAttribute('data-i18n'));
      if (value == null) return;
      // data-i18n-n="20" fills a {n} placeholder ("{n} looks").
      var n = el.getAttribute('data-i18n-n');
      el.textContent = n != null ? value.replace(/\{n\}/g, n) : value;
    });
    // Server-rendered text that comes from data rather than from a key —
    // flow card names, descriptions and tags out of the flow JSONs. The
    // attribute holds the English original; it is looked up in the same
    // flat flowLabels table tField() uses, and falls back to English.
    var table = literalTable(dict);
    document.querySelectorAll('[data-i18n-literal]').forEach(function (el) {
      var src = el.getAttribute('data-i18n-literal');
      var value = table && Object.prototype.hasOwnProperty.call(table, src) ? table[src] : null;
      el.textContent = value != null ? value : src;
    });
    document.querySelectorAll('[data-i18n-attr]').forEach(function (el) {
      el.getAttribute('data-i18n-attr').split(',').forEach(function (pair) {
        var parts = pair.split(':');
        var attr = parts[0] && parts[0].trim();
        var key = parts[1] && parts[1].trim();
        if (!attr || !key) return;
        var value = resolveKey(dict, key);
        if (value != null) el.setAttribute(attr, value);
      });
    });
  }

  function loadDict(id) {
    if (cache[id]) return Promise.resolve(cache[id]);
    return fetch('/static/i18n/' + id + '.json')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (json) { cache[id] = json; return json; })
      .catch(function () { return {}; });
  }

  function syncPanelState(activeId) {
    document.querySelectorAll('[data-i18n-lang-option]').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute('data-i18n-lang-option') === activeId);
    });
    document.querySelectorAll('[data-i18n-lang-current]').forEach(function (el) {
      el.textContent = activeId.toUpperCase();
    });
  }

  // Packages carry their own text (PACKAGE_FORMAT.md §7): the flows they
  // bring are not in the app dictionary. Their translations are keyed by the
  // original text, like flowLabels, so they merge straight into it. Merged
  // once per language; a failure just leaves the flow in its own language.
  function mergePackageTexts(dict, id) {
    if (packTexts[id]) { applyPackTexts(dict, packTexts[id]); return Promise.resolve(dict); }
    return fetch('/api/packages/texts?lang=' + encodeURIComponent(id), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) {
        var labels = res && res.labels ? res.labels : {};
        packTexts[id] = labels;
        applyPackTexts(dict, labels);
        return dict;
      })
      .catch(function () { return dict; });
  }
  function applyPackTexts(dict, labels) {
    if (!dict.flow) dict.flow = {};
    if (!dict.flow.flowLabels) dict.flow.flowLabels = {};
    Object.keys(labels).forEach(function (key) {
      if (!Object.prototype.hasOwnProperty.call(dict.flow.flowLabels, key)) dict.flow.flowLabels[key] = labels[key];
    });
  }

  function applyLanguage(id) {
    var lang = LANGUAGES.filter(function (l) { return l.id === id; })[0];
    var effectiveId = (lang && lang.ready) ? id : 'en';
    document.documentElement.setAttribute('lang', effectiveId);
    loadDict(effectiveId).then(function (dict) {
      return mergePackageTexts(dict, effectiveId);
    }).then(function (dict) {
      applyStrings(dict);
      syncPanelState(effectiveId);
      // Lets scripts that build their own DOM (the hub's tag filter chips)
      // re-render in the new language once its dictionary is in the cache.
      document.dispatchEvent(new CustomEvent('nomad-i18n-applied', { detail: { lang: effectiveId } }));
    });
  }

  function setLanguage(id) {
    try { localStorage.setItem(LANG_KEY, id); } catch (_) {}
    applyLanguage(id);
  }

  function buildPanelList(container) {
    if (!container || container.dataset.i18nBuilt) return;
    container.dataset.i18nBuilt = '1';
    LANGUAGES.forEach(function (lang) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cs-lang-option' + (lang.ready ? '' : ' is-disabled');
      btn.setAttribute('data-i18n-lang-option', lang.id);
      if (!lang.ready) btn.disabled = true;

      var name = document.createElement('span');
      name.className = 'cs-lang-option-name';
      name.textContent = lang.label;
      btn.appendChild(name);

      if (!lang.ready) {
        var soon = document.createElement('span');
        soon.className = 'cs-lang-option-soon';
        soon.setAttribute('data-i18n', 'lang.comingSoon');
        soon.textContent = 'Coming soon';
        btn.appendChild(soon);
      }

      btn.addEventListener('click', function () {
        if (lang.ready) setLanguage(lang.id);
      });
      container.appendChild(btn);
    });
  }

  function initPanels() {
    document.querySelectorAll('[data-i18n-lang-list]').forEach(buildPanelList);

    document.querySelectorAll('[data-i18n-lang-toggle]').forEach(function (toggle) {
      var panel = document.getElementById(toggle.getAttribute('data-i18n-lang-toggle'));
      if (!panel) return;
      var overlayId = toggle.getAttribute('data-i18n-lang-overlay');
      var overlay = overlayId ? document.getElementById(overlayId) : null;
      var close = panel.querySelector('[data-i18n-lang-close]');

      function setOpen(open) {
        panel.classList.toggle('is-open', open);
        toggle.setAttribute('aria-expanded', String(open));
      }

      toggle.addEventListener('click', function () {
        setOpen(!panel.classList.contains('is-open'));
      });
      if (close) close.addEventListener('click', function () { setOpen(false); });
      if (overlay) overlay.addEventListener('click', function () { setOpen(false); });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && panel.classList.contains('is-open')) setOpen(false);
      });
    });
  }

  function init() {
    initPanels();
    applyLanguage(getLanguage());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // For page scripts that build DOM dynamically (settings.js tab panels,
  // album_images.js status text, etc.) — data-i18n only covers text that
  // exists in the server-rendered HTML, not text a script writes later.
  // Falls back to `fallback` (or the key itself) if the dict for the
  // current language hasn't finished loading yet (fetch is async — see
  // loadDict) or the key isn't found; callers should always pass the
  // current English copy as `fallback` so a race never shows anything
  // worse than what was already on screen before this existed.
  function t(key, fallback) {
    var effectiveId = getLanguage();
    var lang = LANGUAGES.filter(function (l) { return l.id === effectiveId; })[0];
    if (!lang || !lang.ready) effectiveId = 'en';
    var dict = cache[effectiveId];
    var value = dict ? resolveKey(dict, key) : null;
    return value != null ? value : (fallback != null ? fallback : key);
  }

  // For flow-JSON-driven text (app/instructions/flows/**/*.json — step
  // `label`, field `label`/`placeholder`/`hint`, rendered directly by the
  // generic flow engine in app/static/js/pages/flow/*.js). Those JSON files
  // have no i18n key of their own, just literal English strings, and there
  // are hundreds of them across ~130 flow definitions — adding a dotted key
  // per field isn't practical. Instead this looks the literal English text
  // itself up in a flat `flowLabels` table (dict.flowLabels["Choose
  // engine"] = "Elige el motor") and falls back to the original text
  // unchanged if that exact string isn't in the table yet — so wrapping a
  // render call in tField() is always safe even before every string has
  // been added to the table, and untranslated (long-tail, flow-specific)
  // labels degrade to English instead of breaking.
  function tField(text) {
    if (!text) return text;
    var effectiveId = getLanguage();
    var lang = LANGUAGES.filter(function (l) { return l.id === effectiveId; })[0];
    if (!lang || !lang.ready) effectiveId = 'en';
    var dict = cache[effectiveId];
    var table = dict && dict.flow && dict.flow.flowLabels;
    var value = table && Object.prototype.hasOwnProperty.call(table, text) ? table[text] : null;
    return value != null ? value : text;
  }

  window.NomadI18n = { getLanguage: getLanguage, setLanguage: setLanguage, LANGUAGES: LANGUAGES, t: t, tField: tField };
})();
