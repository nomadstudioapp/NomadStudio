'use strict';
// Adv params: openLoraNamePickerPanel, _nudgeNcfInput, _applyNcfNumericStepper, buildAdvParams, mkHint

function openLoraNamePickerPanel(title, options, current, onSelect) {
  // Nested (not the regular options panel): this is typically triggered from
  // a button that already lives inside an open options panel (e.g. "Choose a
  // LoRA" inside the Advanced panel's LoRAs section) — opening it in its own
  // 4th column keeps that panel's content/scroll intact instead of replacing it.
  openNestedOptionsPanel(title, function (body) {
    var listEl = document.createElement('div');
    listEl.className = 'nse-model-list';
    listEl.setAttribute('role', 'listbox');
    listEl.setAttribute('aria-label', 'Options');
    options.forEach(function (opt) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'nse-model-item' + (opt === current ? ' is-active' : '');
      btn.textContent = opt === '__bypass__' ? 'None (bypass)' : opt;
      btn.setAttribute('role', 'option');
      btn.setAttribute('aria-selected', opt === current ? 'true' : 'false');
      btn.addEventListener('click', function () {
        onSelect(opt);
        // Stays open — picking one is a live change (the strength steppers
        // right behind it in the Advanced panel keep working too), not a
        // one-shot pick like Aspect ratio. The user closes it themselves.
        listEl.querySelectorAll('.nse-model-item').forEach(function (b) {
          var active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-selected', active ? 'true' : 'false');
        });
      });
      listEl.appendChild(btn);
    });
    body.appendChild(listEl);
    var first = listEl.querySelector('.is-active') || listEl.querySelector('.nse-model-item');
    if (first) { first.scrollIntoView({ block: 'nearest' }); setTimeout(function () { first.focus(); }, 60); }
  }, { wide: true, flexBody: true });
}

async function enhanceAdvParamsWithOptions(record, containerEl, overridesObj) {
  if (!record || !record.id || !containerEl) return;
  if (!overridesObj) overridesObj = currentAdvOverrides;

  // Trigger words captured for this import's LoRAs at import time (#102),
  // matched on file name so a LoRA picked here still finds its own words.
  function _loraTriggerWordsFor(fileName) {
    var ann = (record && record.annotation) || {};
    var list = Array.isArray(ann.loras) ? ann.loras : [];
    var needle = String(fileName || '').toLowerCase();
    for (var i = 0; i < list.length; i += 1) {
      if (String(list[i].fileName || '').toLowerCase() === needle) {
        return String(list[i].triggerWords || '').trim();
      }
    }
    return '';
  }
  try {
    var res = await fetch('/api/models/imports/' + encodeURIComponent(record.id) + '/param-options');
    if (!res.ok) return;
    var data = await res.json();
    var optMap = data.options || {};
    containerEl.querySelectorAll('[data-adv-key]').forEach(function (row) {
      var key = row.getAttribute('data-adv-key');
      var opts = optMap[key];
      if (!Array.isArray(opts) || !opts.length) return;
      var inp = row.querySelector('[data-adv-input]');
      if (!inp) return;
      var currentVal = inp.value || opts[0];
      var lbl = row.querySelector('.nsc-field-label');
      var title = lbl ? lbl.textContent : key;
      overridesObj[key] = currentVal;
      var selectedRaw = currentVal;
      var pickerBtn = document.createElement('button');
      pickerBtn.type = 'button';
      pickerBtn.className = 'nse-model-hint ncf-enum-picker-btn nsc-options-trigger';
      pickerBtn.style.cssText = 'flex:1;justify-content:space-between;min-width:0;';
      var nameSpan = document.createElement('span');
      nameSpan.className = 'nse-model-hint-name';
      nameSpan.textContent = currentVal === '__bypass__' ? 'None (bypass)' : currentVal;
      pickerBtn.appendChild(nameSpan);
      pickerBtn.insertAdjacentHTML('beforeend',
        '<svg class="nse-model-hint-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>');
      inp.parentNode.replaceChild(pickerBtn, inp);
      pickerBtn.addEventListener('click', function () {
        openLoraNamePickerPanel(title, opts, selectedRaw, function (chosen) {
          selectedRaw = chosen;
          nameSpan.textContent = chosen === '__bypass__' ? 'None (bypass)' : chosen;
          overridesObj[key] = chosen;
          if (typeof _syncKeywordToggle === 'function') _syncKeywordToggle();
          saveParams();
        });
      });

      // Trigger-word toggle (#102). Only on LoRA rows: the words typed for
      // this LoRA at import time are prepended to the prompt at generation,
      // and this is the opt-out for one run — the stored value is untouched.
      var _syncKeywordToggle = null;
      if (/lora_name$/.test(key)) {
        var kwLabel = document.createElement('label');
        kwLabel.className = 'ncf-lora-keyword-toggle';
        var kwBox = document.createElement('input');
        kwBox.type = 'checkbox';
        var kwText = document.createElement('span');
        kwLabel.appendChild(kwBox);
        kwLabel.appendChild(kwText);

        _syncKeywordToggle = function () {
          var file = String(selectedRaw || '').split(/[\\/]/).pop();
          var known = _loraTriggerWordsFor(file);
          // Nothing to offer when the LoRA has no words recorded — say so
          // rather than showing a tick that does nothing.
          kwLabel.hidden = !file || file === '__bypass__';
          kwBox.disabled = !known;
          kwText.textContent = known
            ? 'Add trigger words: ' + known
            : 'No trigger words saved for this LoRA';
          kwBox.checked = known ? !(_loraKeywordsOff || {})[file.toLowerCase()] : false;
        };
        kwBox.addEventListener('change', function () {
          var file = String(selectedRaw || '').split(/[\\/]/).pop().toLowerCase();
          if (!file) return;
          if (!_loraKeywordsOff) _loraKeywordsOff = {};
          _loraKeywordsOff[file] = !kwBox.checked;
        });
        _syncKeywordToggle();
        row.appendChild(kwLabel);
      }
    });
  } catch (e) {
    console.warn('[FlowEngine] enhanceAdvParamsWithOptions:', e);
  }
}

function _nudgeNcfInput(inp, delta) {
  var step = parseFloat(inp.step) || 1;
  var v = (parseFloat(inp.value) || 0) + delta * step;
  if (inp.min !== '' && inp.min !== undefined) { var mn = parseFloat(inp.min); if (!isNaN(mn) && v < mn) v = mn; }
  if (inp.max !== '' && inp.max !== undefined) { var mx = parseFloat(inp.max); if (!isNaN(mx) && v > mx) v = mx; }
  inp.value = (step === Math.floor(step)) ? Math.round(v) : v;
  inp.dispatchEvent(new Event('input', { bubbles: true }));
}

function _applyNcfNumericStepper(inp, parentEl) {
  var wrapper = document.createElement('div');
  wrapper.className = 'numeric-stepper';
  var decBtn = document.createElement('button');
  decBtn.type = 'button';
  decBtn.className = 'btn numeric-stepper-btn numeric-stepper-btn-left';
  decBtn.setAttribute('aria-label', 'Decrease');
  decBtn.innerHTML = '<span aria-hidden="true">&#9664;</span>';
  var incBtn = document.createElement('button');
  incBtn.type = 'button';
  incBtn.className = 'btn numeric-stepper-btn numeric-stepper-btn-right';
  incBtn.setAttribute('aria-label', 'Increase');
  incBtn.innerHTML = '<span aria-hidden="true">&#9654;</span>';
  wrapper.appendChild(decBtn);
  wrapper.appendChild(inp);
  wrapper.appendChild(incBtn);
  parentEl.appendChild(wrapper);
  decBtn.addEventListener('click', function () { _nudgeNcfInput(inp, -1); });
  incBtn.addEventListener('click', function () { _nudgeNcfInput(inp, 1); });
}

function buildAdvParams(record, containerEl, overridesObj, idPrefix) {
  if (!containerEl) return;
  containerEl.innerHTML = '';
  if (!overridesObj) { currentAdvOverrides = {}; overridesObj = currentAdvOverrides; }
  idPrefix = idPrefix || '';
  var params = Array.isArray(record && record.analysis && record.analysis.advancedParameters)
    ? record.analysis.advancedParameters : [];
  if (!params.length) {
    containerEl.innerHTML = '<p class="nsc-adv-empty">No adjustable parameters.</p>'; return;
  }
  params.forEach(function (param) {
    var key = String(param.key || '');
    var label = String(param.label || param.inputKey || key);
    var defVal = param.value;
    var isNum = typeof defVal === 'number';
    var isInt = isNum && Number.isInteger(defVal);
    var inputId = 'ncf-adv-' + idPrefix + key.replace(/\./g, '-');
    var row = document.createElement('div');
    row.className = 'nsc-field-row nsc-adv-row';
    if (!isNum) row.setAttribute('data-adv-key', key);
    var lbl = document.createElement('label');
    lbl.className = 'nsc-field-label'; lbl.setAttribute('for', inputId); lbl.textContent = label;
    var inp = document.createElement('input');
    inp.className = 'nsc-input nsc-input--adv'; inp.id = inputId;
    inp.type = isNum ? 'number' : 'text';
    if (!isNum) inp.setAttribute('data-adv-input', '');
    if (isInt) inp.step = '1';
    var initVal = Object.prototype.hasOwnProperty.call(overridesObj, key) ? overridesObj[key] : defVal;
    inp.value = initVal !== undefined ? initVal : '';
    (function (k, dv) {
      inp.addEventListener('input', function () {
        var v = isNum ? Number(inp.value) : inp.value;
        if (v === dv) delete overridesObj[k]; else overridesObj[k] = v;
        saveParams();
      });
    }(key, defVal));
    row.appendChild(lbl);
    if (isNum) {
      _applyNcfNumericStepper(inp, row);
    } else {
      row.appendChild(inp);
    }
    containerEl.appendChild(row);
  });
}

// ══════════════════════════════════════════════════════════════════════════
// STEP RENDERERS
// ══════════════════════════════════════════════════════════════════════════
function mkHint(text) {
  return Object.assign(document.createElement('p'), { className: 'nsc-step-hint', textContent: text || '' });
}

// ── workflow_picker ────────────────────────────────────────────────────────
