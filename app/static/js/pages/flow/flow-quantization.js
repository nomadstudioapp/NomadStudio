'use strict';
// Quantization presets (INT4/INT8/FP8 diffusion-model variants): buildQuantizationList

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
        selectedQuantizationId = option.id;
        selectedQuantizationValues = valuesFor(option);
        listEl.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
          var a = b === btn; b.classList.toggle('is-active', a); b.setAttribute('aria-checked', a ? 'true' : 'false');
        });
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
}
