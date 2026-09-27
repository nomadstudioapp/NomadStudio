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

  function _render(wrap, params) {
    wrap.innerHTML = '';
    var p = params || {};
    if (p.aspect) wrap.appendChild(_pill('on', _fill('Aspect {v}', p.aspect)));
    if (p.no) wrap.appendChild(_pill('on', _fill('No: {v}', p.no)));
    if (p.seed != null) wrap.appendChild(_pill('on', _fill('Seed {v}', p.seed)));
    if (p.steps != null) wrap.appendChild(_pill('on', _fill('{v} steps', p.steps)));
    if (p.repeat != null) wrap.appendChild(_pill('on', _fill('{v} images', p.repeat)));
    if (p.model) wrap.appendChild(_pill('note', _fill('Engine: {v}', p.model),
      _t('In the app, choose the engine in its selector — --v is not applied here yet.')));
    if (p.speed) wrap.appendChild(_pill('note', _fill('Speed: {v}', p.speed),
      _t('In the app, choose Fast / Balanced / Max under Quality — --q is not applied here yet.')));
    if (p.quantization) wrap.appendChild(_pill('note', _fill('Quantization: {v}', p.quantization),
      _t('In the app, choose it in Advanced — --quant is not applied here yet.')));
    (p.ignored || []).forEach(function (name) {
      wrap.appendChild(_pill('off', '--' + name, _t('Midjourney-only parameter: it has no equivalent here and is ignored.')));
    });
    Object.keys(p.invalid || {}).forEach(function (name) {
      wrap.appendChild(_pill('bad', '--' + name, _t('This value can\'t be used: it is ignored.')));
    });
    wrap.hidden = !wrap.childNodes.length;
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
      if (!has(text)) { wrap.innerHTML = ''; wrap.hidden = true; return; }
      var mine = ++seq;
      parse(text).then(function (res) {
        if (mine !== seq) return;
        _render(wrap, res && res.params);
      });
    }
    function schedule() { clearTimeout(timer); timer = setTimeout(refresh, 250); }
    ta.addEventListener('input', schedule);
    ta.addEventListener('change', schedule);
    refresh();
    return { refresh: refresh };
  }

  return { has: has, split: split, repeatCount: repeatCount, attach: attach };
})();
