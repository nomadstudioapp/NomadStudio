'use strict';
// Step: workflow_picker → renderWorkflowPicker
// Guided mode: single <select> (one model). Custom mode: inline multi-select
// list in the same step — choosing several workflows runs them all in parallel.

var _wpMultiListEl = null;

function renderWorkflowMultiList() {
  if (!_wpMultiListEl) return;
  _wpMultiListEl.innerHTML = '';
  if (!allImportsList.length) {
    _wpMultiListEl.innerHTML = '<p class="nse-model-empty">No workflows available.</p>';
    return;
  }
  var ids = getGlobalWorkflows();
  allImportsList.forEach(function (imp) {
    var id = String(imp.id);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'ncf-wf-multi-item-' + id;
    btn.className = 'nse-model-item' + (ids.indexOf(id) >= 0 ? ' is-active' : '');
    btn.setAttribute('role', 'option');
    btn.setAttribute('aria-selected', String(ids.indexOf(id) >= 0));
    btn.innerHTML = '<span class="nse-model-name">' + escHtml(imp.name || id) + '</span>' +
      '<svg class="nse-model-check" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8l4 4 6-7"/></svg>';
    btn.addEventListener('click', function () {
      var cur = getGlobalWorkflows();
      var idx = cur.indexOf(id);
      if (idx >= 0) {
        if (cur.length <= 1) return; // always keep at least one model selected
        cur.splice(idx, 1);
      } else {
        cur.push(id);
      }
      setGlobalWorkflows(cur);
      var active = cur.indexOf(id) >= 0;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', String(active));
      if (typeof renderWfParamsAside === 'function') renderWfParamsAside();
      updateGenerateBtn();
    });
    _wpMultiListEl.appendChild(btn);
  });
}

function renderWorkflowPicker(stepDef, el) {
  function syncPickerVisibility() {
    var isCustom = getMode() === 'advanced';
    wrapper.hidden = isCustom;
    multiWrap.hidden = !isCustom;
    multiCaption.hidden = !isCustom;
    if (isCustom) renderWorkflowMultiList();
  }

  var wrapper = document.createElement('div');
  wrapper.className = 'nsc-select-wrapper';
  var select = document.createElement('select');
  select.className = 'nsc-select';
  select.id = 'ncf-workflow-select';
  select.innerHTML = '<option value="">Loading workflows…</option>';
  wrapper.appendChild(select);
  wrapper.insertAdjacentHTML('beforeend',
    '<svg class="nsc-select-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>');
  el.appendChild(wrapper);

  var multiCaption = mkHint('Select one or more models to enqueue generations for.');
  el.appendChild(multiCaption);

  var multiWrap = document.createElement('div');
  multiWrap.id = 'nse-model-list';
  multiWrap.className = 'nse-model-list ncf-workflow-multi-list';
  multiWrap.setAttribute('role', 'listbox');
  multiWrap.setAttribute('aria-multiselectable', 'true');
  multiWrap.setAttribute('aria-label', 'Available workflows');
  el.appendChild(multiWrap);
  _wpMultiListEl = multiWrap;

  var hint = mkHint('');
  el.appendChild(hint);

  select.addEventListener('change', function () {
    if (select.value) selectImportById(select.value, hint);
  });

  syncPickerVisibility();
  document.addEventListener('ncf-mode-change', syncPickerVisibility);

  // "--v monaco" / "--anime" in the prompt (flow-prompt-params.js) picks that
  // engine here, as if chosen by hand — only when the --v changes, and only in
  // the single-engine picker (Custom mode's multi-list is the user's own).
  var _promptEngine = null;
  function applyPromptEngine(name, force) {
    if (!name || typeof NcfPromptParams === 'undefined' || getMode() === 'advanced') return;
    if (name === _promptEngine && !force) return;
    var engine = NcfPromptParams.findEngine(name);
    if (!engine) return;              // list not loaded yet, or not installed (the pill says so)
    _promptEngine = name;
    var id = String(engine.id);
    if (select.value !== id && select.querySelector('option[value="' + id.replace(/"/g, '') + '"]')) {
      select.value = id;
      select.dispatchEvent(new Event('change'));
    }
  }
  document.addEventListener('ncf-prompt-params', function (e) {
    var model = ((e.detail && e.detail.params) || {}).model || null;
    if (!model) { _promptEngine = null; return; }
    applyPromptEngine(model);
  });

  Promise.resolve(loadWorkflows(select, hint, stepDef.recommended_import_ids || stepDef.import_ids)).then(function () {
    if (typeof NcfPromptParams === 'undefined') return;
    NcfPromptParams.refreshAll();   // pills can now tell installed engines apart
    applyPromptEngine(NcfPromptParams.last().model, true);
  });
}

// ── prompt_input ───────────────────────────────────────────────────────────
