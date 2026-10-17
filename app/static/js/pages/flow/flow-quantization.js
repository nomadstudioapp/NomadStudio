'use strict';
// Quantization presets (INT4/INT8/FP8 diffusion-model variants): buildQuantizationList

// Disable the pills whose files ComfyUI doesn't have (/api/models/quantization/
// presence) — picking one would only fail at queue time. When the selected
// option turns out missing, `pick(option)` moves the selection to the first
// installed one (without saving it: the user's own choice comes back once the
// file is installed). ComfyUI unreachable → nothing is disabled. Shared with
// library.js.
function markQuantizationPresence(listEl, options, getSelectedId, pick) {
  if (!listEl || !options || !options.length) return;
  // The Advanced panel keeps its lists detached until it opens, so no
  // isConnected check — only the newest request for this list may apply.
  var seq = listEl._quantPresenceSeq = (listEl._quantPresenceSeq || 0) + 1;
  fetch('/api/models/quantization/presence', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ options: options }),
  })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (res) {
      var present = res && res.present;
      if (!present || seq !== listEl._quantPresenceSeq) return;
      var tip = window.NomadI18n ? window.NomadI18n.tField('Not installed in ComfyUI') : 'Not installed in ComfyUI';
      listEl.querySelectorAll('[data-quantization-id]').forEach(function (btn) {
        var missing = present[btn.getAttribute('data-quantization-id')] === false;
        btn.disabled = missing;
        btn.classList.toggle('is-missing', missing);
        // Nomad Studio tooltip (.action-tip, floated by services/tooltips.js)
        var tipEl = btn.querySelector('.action-tip');
        if (missing && !tipEl) {
          tipEl = document.createElement('span');
          tipEl.className = 'action-tip';
          tipEl.textContent = tip;
          btn.appendChild(tipEl);
        } else if (!missing && tipEl) {
          tipEl.remove();
        }
      });
      if (present[getSelectedId()] !== false) return;
      var fallback = options.filter(function (o) { return present[o.id] !== false; })[0];
      if (fallback) pick(fallback);
    })
    .catch(function () {});
}

// Variations (Normal / Turbo …, analysis.quantization.variations): other
// checkpoints of the same graph, each with its own precisions and step count.
// Pills like Quantization's; a variation none of whose precisions ComfyUI has
// is disabled. Returns the selected variation (selectedId if it exists, else
// the first), or null when there is nothing to pick from — the caller then
// uses the plain quantization options. onSelect(variation) fires on a click
// and when the selected one turns out not to be installed.
function buildVariationList(quant, listEl, selectedId, onSelect) {
  if (!listEl) return null;
  var block = listEl.closest ? listEl.closest('.nsc-param-block') : null;
  var variations = (quant && Array.isArray(quant.variations)) ? quant.variations : [];
  listEl.innerHTML = '';
  if (variations.length < 2) {
    if (block) block.style.display = 'none';
    return null;
  }
  if (block) block.style.display = '';
  var selected = variations.filter(function (v) { return v.id === selectedId; })[0] || variations[0];
  var tr = window.NomadI18n ? window.NomadI18n.tField : function (s) { return s; };

  function mark(id) {
    listEl.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
      var a = b.getAttribute('data-variation-id') === id;
      b.classList.toggle('is-active', a); b.setAttribute('aria-checked', a ? 'true' : 'false');
    });
  }

  variations.forEach(function (v) {
    var btn = document.createElement('button');
    btn.className = 'nsc-quality-btn' + (v.id === selected.id ? ' is-active' : '');
    btn.type = 'button';
    btn.setAttribute('role', 'radio');
    btn.setAttribute('data-variation-id', v.id);
    btn.setAttribute('aria-checked', v.id === selected.id ? 'true' : 'false');
    btn.innerHTML =
      '<span class="nsc-quality-dot"></span>' +
      '<span class="nsc-quality-copy"><strong>' + escHtml(tr(v.label)) + '</strong></span>';
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      mark(v.id);
      onSelect(v);
    });
    listEl.appendChild(btn);
  });

  // One presence request for every precision of every variation; ids are
  // namespaced so INT8 of Normal and INT8 of Turbo don't collide.
  var seq = listEl._variationPresenceSeq = (listEl._variationPresenceSeq || 0) + 1;
  var all = [];
  variations.forEach(function (v) {
    (v.options || []).forEach(function (o) { all.push(Object.assign({}, o, { id: v.id + ':' + o.id })); });
  });
  fetch('/api/models/quantization/presence', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ options: all }),
  })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (res) {
      var present = res && res.present;
      if (!present || seq !== listEl._variationPresenceSeq) return;
      var installed = {};
      variations.forEach(function (v) {
        installed[v.id] = (v.options || []).some(function (o) { return present[v.id + ':' + o.id] !== false; });
      });
      var tip = tr('Not installed in ComfyUI');
      listEl.querySelectorAll('[data-variation-id]').forEach(function (btn) {
        var missing = !installed[btn.getAttribute('data-variation-id')];
        btn.disabled = missing;
        btn.classList.toggle('is-missing', missing);
        var tipEl = btn.querySelector('.action-tip');
        if (missing && !tipEl) {
          tipEl = document.createElement('span');
          tipEl.className = 'action-tip';
          tipEl.textContent = tip;
          btn.appendChild(tipEl);
        } else if (!missing && tipEl) {
          tipEl.remove();
        }
      });
      var current = listEl.querySelector('.nsc-quality-btn.is-active');
      if (current && !current.disabled) return;
      var fallback = variations.filter(function (v) { return installed[v.id]; })[0];
      if (fallback) { mark(fallback.id); onSelect(fallback); }
    })
    .catch(function () {});

  return selected;
}

function buildQuantizationList(record, listEl, onChange) {
  if (!listEl) return;
  var block = listEl.closest ? listEl.closest('.nsc-param-block') : null;
  var quant = record && record.analysis && record.analysis.quantization;
  var options = (quant && Array.isArray(quant.options)) ? quant.options : [];
  var targetKey = quant ? String(quant.targetKey || '') : '';
  var clipTargetKey = quant ? String(quant.clipTargetKey || '') : '';
  var unconditionalTargetKey = quant ? String(quant.unconditionalTargetKey || '') : '';

  if (!options.length || !targetKey) {
    selectedQuantizationId     = null;
    selectedQuantizationValues = null;
    listEl.innerHTML = '';
    if (block) block.style.display = 'none';
    return;
  }
  if (block) block.style.display = '';

  function valuesFor(option) {
    var values = {};
    values[targetKey] = option.unet_name;
    if (clipTargetKey && option.clip_name) values[clipTargetKey] = option.clip_name;
    // Dual-branch CFG workflows (e.g. Ideogram 4) load a second "unconditional"
    // UNETLoader that must move to the same precision as the main one.
    if (unconditionalTargetKey && option.unet_unconditional_name) values[unconditionalTargetKey] = option.unet_unconditional_name;
    return values;
  }

  var savedQuantizationId = (loadSavedParams() || {}).quantizationId;
  var initialOpt = (savedQuantizationId && options.find(function (o) { return o.id === savedQuantizationId; }))
    || options[0];
  selectedQuantizationId = initialOpt.id;
  selectedQuantizationValues = valuesFor(initialOpt);

  function select(option, btn) {
    selectedQuantizationId = option.id;
    selectedQuantizationValues = valuesFor(option);
    listEl.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
      var a = b === btn; b.classList.toggle('is-active', a); b.setAttribute('aria-checked', a ? 'true' : 'false');
    });
  }

  listEl.innerHTML = '';
  options.forEach(function (opt) {
    var btn = document.createElement('button');
    btn.className = 'nsc-quality-btn' + (opt.id === selectedQuantizationId ? ' is-active' : '');
    btn.type = 'button';
    btn.setAttribute('role', 'radio');
    btn.setAttribute('data-quantization-id', opt.id);
    btn.setAttribute('aria-checked', opt.id === selectedQuantizationId ? 'true' : 'false');
    btn.innerHTML =
      '<span class="nsc-quality-dot"></span>' +
      '<span class="nsc-quality-copy"><strong>' + escHtml(opt.label) + '</strong></span>';
    (function (option) {
      btn.addEventListener('click', function () {
        select(option, btn);
        saveParams();
        // Some callers (plain workflow_file flows) cache the merged advanced
        // values ahead of submit instead of reading the globals fresh — they
        // need telling explicitly that the selection just changed, or a
        // click here silently has no effect until some other field is touched.
        if (typeof onChange === 'function') onChange();
      });
    }(opt));
    listEl.appendChild(btn);
  });

  markQuantizationPresence(listEl, options,
    function () { return selectedQuantizationId; },
    function (option) {
      select(option, listEl.querySelector('[data-quantization-id="' + option.id + '"]'));
      if (typeof onChange === 'function') onChange();
    });
}
