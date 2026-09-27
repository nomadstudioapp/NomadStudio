'use strict';
// Midjourney-style --parameters in Create's prompt (NomadStudio#27):
// "a red bike --ar 16:9 --no people --seed 42". Pills under the prompt box
// say what was understood. The meaning comes from the backend
// (/api/models/prompt-params, app/services/prompt_params.py) — the same
// parser the graph builder applies — so the pills never promise something
// generation doesn't do. Only in Create flows: Refine/Mix graphs don't go
// through that builder.

var NcfPromptParams = (function () {
  var PATTERN = /(^|\s)--[A-Za-z]/;

  function _t(text) { return typeof tF === 'function' ? tF(text) : text; }
  function _fill(text, value) { return _t(text).replace('{v}', value); }

  function has(text) { return PATTERN.test(String(text || '')); }

  function parse(text) {
    return fetch('/api/models/prompt-params', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: String(text || '') }),
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  // The text without its parameters, and the parameters as typed — for flows
  // that send the prompt through an LLM first (it would rewrite or drop them).
  function split(text) {
    var s = String(text || '');
    var m = s.match(PATTERN);
    if (!m) return { text: s, params: '' };
    var at = m.index + m[1].length;
    return { text: s.slice(0, at).trim(), params: s.slice(at).trim() };
  }

  // --r N: how many times to run this prompt (1 when absent).
  function repeatCount(text) {
    var m = String(text || '').match(/(?:^|\s)--(?:r|repeat)\s+(\d+)/i);
    var n = m ? parseInt(m[1], 10) : 1;
    return n >= 1 && n <= 4 ? n : 1;
  }

  function _pill(kind, label, tip) {
    var pill = document.createElement('span');
    pill.className = 'ncf-param-pill ncf-param-pill--' + kind;
    pill.textContent = label;
    if (tip) {
      // Nomad Studio tooltip (services/tooltips.js floats it).
      var tipEl = document.createElement('span');
      tipEl.className = 'action-tip';
      tipEl.textContent = tip;
      pill.appendChild(tipEl);
    }
    return pill;
  }

  var _SPEED_LABELS = { fast: 'Fast', balanced: 'Balanced', max: 'Max' };

  // Installed engine for "--v monaco" / "--anime": same rule as the MCP
  // (app/mcp/preferences.resolve_model) — a piece of the name, case and
  // "-"/"_" ignored; the first match in the engine list wins. undefined =
  // the engine list isn't loaded yet (can't tell), null = not installed.
  function findEngine(name) {
    if (!name) return null;
    if (typeof allImportsList === 'undefined' || !Array.isArray(allImportsList) || !allImportsList.length) return undefined;
    function norm(s) { return String(s || '').toLowerCase().replace(/[-_]/g, ' ').replace(/\s+/g, ' ').trim(); }
    var needle = norm(name);
    return allImportsList.find(function (imp) { return imp && norm(imp.name).indexOf(needle) >= 0; }) || null;
  }

  function _render(wrap, params) {
    wrap.innerHTML = '';
    var p = params || {};
    if (p.aspect) wrap.appendChild(_pill('on', _fill('Aspect {v}', p.aspect)));
    if (p.no) wrap.appendChild(_pill('on', _fill('No: {v}', p.no)));
    if (p.seed != null) wrap.appendChild(_pill('on', _fill('Seed {v}', p.seed)));
    if (p.steps != null) wrap.appendChild(_pill('on', _fill('{v} steps', p.steps)));
    if (p.repeat != null) wrap.appendChild(_pill('on', _fill('{v} images', p.repeat)));
    if (p.model) {
      var engine = findEngine(p.model);
      wrap.appendChild(engine === null
        ? _pill('bad', _fill('Engine not installed: {v}', p.model))
        : _pill('on', _fill('Engine: {v}', engine ? (engine.name || engine.id) : p.model)));
    }
    if (p.speed) wrap.appendChild(_pill('on', _fill('Quality: {v}', _SPEED_LABELS[p.speed] || p.speed)));
    if (p.quantization) wrap.appendChild(_pill('on', _fill('Quantization: {v}', p.quantization.toUpperCase())));
    // Midjourney-only ones (--stylize, --chaos…) are dropped silently: no pill.
    Object.keys(p.invalid || {}).forEach(function (name) {
      wrap.appendChild(_pill('bad', _fill('{v} · wrong value', '--' + name),
        _t('This value can\'t be used: it is ignored.')));
    });
    wrap.hidden = !wrap.childNodes.length;
    _announce(p);
  }

  // Other controls (Aspect ratio / Resolution, flow-step-workflow-params.js)
  // show what the prompt overrides.
  var _last = {};
  function _announce(params) {
    _last = params || {};
    document.dispatchEvent(new CustomEvent('ncf-prompt-params', { detail: { params: params || {} } }));
  }

  // Same sizing as the backend (prompt_params.size_for_aspect, multiples of
  // 16 in the app): ratio "16:9" at the pixel count of `dims`.
  function sizeFor(aspect, dims) {
    var m = /^(\d+):(\d+)$/.exec(String(aspect || ''));
    if (!m) return null;
    var rw = +m[1], rh = +m[2];
    var area = dims && dims.w > 0 && dims.h > 0 ? dims.w * dims.h : 1024 * 1024;
    var width = Math.sqrt(area * rw / rh);
    var height = width * rh / rw;
    return { w: Math.max(16, Math.round(width / 16) * 16), h: Math.max(16, Math.round(height / 16) * 16) };
  }

  // Pills right under `ta`, kept in sync as the user types.
  function attach(ta) {
    if (!ta || !ta.parentNode) return;
    var wrap = document.createElement('div');
    wrap.className = 'ncf-param-pills';
    wrap.hidden = true;
    ta.parentNode.insertBefore(wrap, ta.nextSibling);
    var timer = null;
    var seq = 0;
    function refresh() {
      var text = ta.value;
      if (!has(text)) { wrap.innerHTML = ''; wrap.hidden = true; _announce(null); return; }
      var mine = ++seq;
      parse(text).then(function (res) {
        if (mine !== seq) return;
        _render(wrap, res && res.params);
      });
    }
    function schedule() { clearTimeout(timer); timer = setTimeout(refresh, 250); }
    ta.addEventListener('input', schedule);
    ta.addEventListener('change', schedule);
    _attached.push(refresh);
    refresh();
    return { refresh: refresh };
  }

  // Re-read every attached prompt box — e.g. once the engine list has
  // loaded, so "--v monaco" can be matched and applied.
  var _attached = [];
  function refreshAll() { _attached.forEach(function (fn) { fn(); }); }

  return { has: has, split: split, repeatCount: repeatCount, attach: attach, refreshAll: refreshAll, sizeFor: sizeFor, findEngine: findEngine,
           last: function () { return _last; } };
})();
