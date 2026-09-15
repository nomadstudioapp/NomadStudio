'use strict';
// Per-model "Custom" params aside (Custom mode only): one shared Seed at the
// top, plus a tab (1, 2, 3…) per selected workflow holding that workflow's
// own advanced-parameter overrides — replaces the old single shared panel.

var _wfAsideEl      = document.getElementById('ncf-model-params-aside');
var _wfTabsBarEl    = document.getElementById('ncf-wf-tabs');
var _wfTabBodiesEl  = document.getElementById('ncf-wf-tab-bodies');
var _wfAsideSeedEl  = document.getElementById('ncf-wf-aside-seed');
var _wfAsideSeedRnd = document.getElementById('ncf-wf-aside-seed-random');

var _wfTabBtnEls   = {};  // workflowId -> tab button el
var _wfTabBodyEls  = {};  // workflowId -> tab body el
var _wfActiveTabId = null;
// workflowId -> function that re-renders that tab's preset pills, state
// label and custom-param inputs from the current _wfAdvOverrides[id]/
// _wfActivePreset[id] — lets outside code (flow-params-reuse.js's "Apply
// params") mutate those objects directly and have the UI catch up, the same
// way clicking a preset pill in this tab already does.
var _wfTabRefreshFns = {};

// ── LoRA treeview (shared by every "Choose a LoRA" button) ─────────────────
// Fetches ComfyUI's own LoRA catalog (GET /api/models/comfy/loras — already
// includes each file's real subfolder path, e.g.
// "qwen_2511_loras\Qwen-Image-Lightning-4steps-V2.0-bf16.safetensors")
// and builds a real folder tree from it client-side, instead of guessing a
// folder-per-model naming convention (users' actual lora folders are rarely
// that tidy). onPick(fullPath) fires when a leaf is clicked.
function _fillLoraTreePanel(panelBody, onPick) {
  panelBody.innerHTML = '<p class="nsc-step-hint">Loading…</p>';
  fetch('/api/models/comfy/loras')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var loras = Array.isArray(data.loras) ? data.loras : [];
      panelBody.innerHTML = '';
      if (!loras.length) {
        panelBody.innerHTML = '<p class="nsc-step-hint">No LoRAs found — check ComfyUI is running and reachable.</p>';
        return;
      }
      var root = {};
      loras.forEach(function (path) {
        var parts = String(path).split(/[\\/]/).filter(Boolean);
        if (!parts.length) return;
        var node = root;
        parts.forEach(function (part, i) {
          if (i === parts.length - 1) {
            node.__files = node.__files || [];
            node.__files.push({ name: part, fullPath: path });
          } else {
            node[part] = node[part] || {};
            node = node[part];
          }
        });
      });
      var treeEl = document.createElement('div');
      treeEl.className = 'nsc-lora-tree';
      _renderLoraTreeLevel(treeEl, root, onPick);
      panelBody.appendChild(treeEl);
    })
    .catch(function () {
      panelBody.innerHTML = '<p class="nsc-step-hint">Failed to load LoRA list.</p>';
    });
}

function _renderLoraTreeLevel(parentEl, node, onPick) {
  Object.keys(node).filter(function (k) { return k !== '__files'; }).sort().forEach(function (folderName) {
    var details = document.createElement('details');
    details.className = 'nsc-lora-tree-folder';
    var summary = document.createElement('summary');
    summary.textContent = folderName;
    details.appendChild(summary);
    _renderLoraTreeLevel(details, node[folderName], onPick);
    parentEl.appendChild(details);
  });
  (node.__files || []).sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (file) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nsc-lora-tree-file';
    btn.textContent = file.name;
    btn.addEventListener('click', function () { onPick(file.fullPath); });
    parentEl.appendChild(btn);
  });
}

(function initWfAsideSeed() {
  if (!_wfAsideSeedEl) return;
  var sp = loadSavedParams() || {};
  if (sp.seed != null && sp.seed !== -1) { _wfAsideSeedEl.value = sp.seed; selectedSeed = sp.seed; }
  _wfAsideSeedEl.addEventListener('input', function () {
    selectedSeed = Number(_wfAsideSeedEl.value) || -1;
    saveParams();
  });
  if (_wfAsideSeedRnd) {
    _wfAsideSeedRnd.addEventListener('click', function () {
      var v = Math.floor(Math.random() * 0x7FFFFFFF);
      _wfAsideSeedEl.value = v;
      selectedSeed = v;
      saveParams();
    });
  }
})();

// Pre-fill the shared seed from whichever workflow loads first (mirrors the
// old per-workflow default-seed behaviour), unless the user already saved one.
document.addEventListener('ncf-workflow-loaded', function (e) {
  if (!_wfAsideSeedEl) return;
  var bv = (e.detail && e.detail.basicValues) || {};
  var wfSeed = Number(bv.seed);
  var sp = loadSavedParams() || {};
  if (!isNaN(wfSeed) && (sp.seed == null || sp.seed === -1)) {
    _wfAsideSeedEl.value = wfSeed;
    selectedSeed = wfSeed;
  }
});

function _activateWfTab(id) {
  if (!id || !_wfTabBtnEls[id]) return;
  _wfActiveTabId = id;
  Object.keys(_wfTabBtnEls).forEach(function (tid) {
    _wfTabBtnEls[tid].classList.toggle('is-active', tid === id);
  });
  Object.keys(_wfTabBodyEls).forEach(function (tid) {
    _wfTabBodyEls[tid].hidden = tid !== id;
  });
}

function _createWfTab(id) {
  if (!_wfTabsBarEl || !_wfTabBodiesEl) return;

  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ncf-wf-tab';
  btn.setAttribute('role', 'tab');
  btn.addEventListener('click', function () { _activateWfTab(id); });
  _wfTabsBarEl.appendChild(btn);
  _wfTabBtnEls[id] = btn;

  var body = document.createElement('div');
  body.className = 'ncf-wf-tab-body';
  body.hidden = true;
  _wfTabBodiesEl.appendChild(body);
  _wfTabBodyEls[id] = body;

  var sp = loadSavedParams() || {};
  _wfAdvOverrides[id] = Object.assign({}, (sp.wfAdvOverrides && sp.wfAdvOverrides[id]) || {});
  _wfActivePreset[id] = (sp.wfActivePreset && sp.wfActivePreset[id]) || null;

  body.innerHTML = '<p class="nse-model-empty">Loading…</p>';
  fetchFullRecord(id).then(function (record) {
    body.innerHTML = '';
    var nameEl = document.createElement('p');
    nameEl.className = 'nsc-param-title ncf-wf-tab-name';
    nameEl.textContent = (record && (record.name || record.id)) || id;
    body.appendChild(nameEl);

    // Preset picker: clicking a preset immediately loads its values into the
    // Custom Params inputs below — so values are visible/editable rather than
    // a hidden Guided-mode-only concept. Mirrors buildQualityList() but scoped
    // to this workflow's own tab (Custom mode can queue several).
    var presets = resolveQualityPresets(record);

    var presetListEl = document.createElement('div');
    presetListEl.className = 'nsc-quality-list ncf-wf-preset-list';
    presetListEl.setAttribute('role', 'radiogroup');
    body.appendChild(presetListEl);

    var headerEl = document.createElement('p');
    headerEl.className = 'nsc-param-title nsc-param-title--flex ncf-wf-adv-header';
    var headerLabel = document.createElement('span');
    headerLabel.textContent = 'Custom params';
    var stateLabel = document.createElement('span');
    stateLabel.className = 'ncf-wf-preset-state';
    var resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'nse-modal-secondary ncf-wf-preset-reset';
    resetBtn.textContent = 'Reset';
    headerEl.appendChild(headerLabel);
    headerEl.appendChild(stateLabel);
    headerEl.appendChild(resetBtn);
    body.appendChild(headerEl);

    // "Choose a LoRA" — only for the curated base workflows (the ones with a
    // config.quantization block, same signal the INT8/FP8/NVFP4 picker reads
    // via record.analysis.quantization.targetKey). These ship with no LoRA
    // node of their own, so picking one here dynamically inserts a fresh
    // LoraLoaderModelOnly between the base loader and whatever consumes it
    // (_ensure_lora_loader_node, workflow_service.py) — arbitrary imported
    // workflows are untouched, same as before.
    var quantInfo = record && record.analysis && record.analysis.quantization;
    var unetNodeId = quantInfo && quantInfo.targetKey ? String(quantInfo.targetKey).split('.')[0] : '';
    // Curated base workflows are either "bare" (no LoRA node at all — Krea 2,
    // Z-Image Turbo, Flux Klein, Ideogram 4) or already carry one baked in
    // (Qwen Image's Lightning speedup LoRA). These two cases are handled by
    // two DIFFERENT backend mechanisms and need two different advanced-value
    // keys: a bare workflow needs the bootstrap key
    // "<unet_node_id>.__insert_lora" (_ensure_lora_loader_node,
    // workflow_service.py, synthesizes the first LoRA node from scratch);
    // a workflow with an existing node needs "<existing_lora_node_id>.__lora_chain"
    // (the existing _apply_lora_chain_to_workflow, which clones that node as
    // a template) — writing the bootstrap key there would just get ignored,
    // since _ensure_lora_loader_node no-ops whenever a LoRA node already
    // exists. Find that existing node (if any) straight from the record's
    // own raw graph, already available here from fetchFullRecord(id).
    function _findExistingLoraNodeId(workflow) {
      if (!workflow || typeof workflow !== 'object') return null;
      var found = Object.keys(workflow).find(function (nodeId) {
        var node = workflow[nodeId];
        var classType = node && node.class_type;
        return classType === 'LoraLoader' || classType === 'LoraLoaderModelOnly';
      });
      return found || null;
    }
    var existingLoraNodeId = _findExistingLoraNodeId(record && record.workflow);
    if (unetNodeId) {
      var insertKey = existingLoraNodeId
        ? existingLoraNodeId + '.__lora_chain'
        : unetNodeId + '.__insert_lora';
      var loraRow = document.createElement('div');
      loraRow.className = 'ncf-wf-lora-row';
      var loraBtn = document.createElement('button');
      loraBtn.type = 'button';
      loraBtn.className = 'nsc-history-btn ncf-wf-lora-btn nsc-options-trigger';
      var loraClearBtn = document.createElement('button');
      loraClearBtn.type = 'button';
      loraClearBtn.className = 'nsc-history-btn ncf-wf-lora-clear';
      loraClearBtn.setAttribute('aria-label', 'Remove LoRA');
      loraClearBtn.title = 'Remove LoRA';
      loraClearBtn.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 3l10 10M13 3L3 13"/></svg>';
      loraClearBtn.hidden = true;

      function _loraFileLabel(fullPath) {
        var parts = String(fullPath || '').split(/[\\/]/);
        return parts[parts.length - 1] || fullPath;
      }
      // __lora_chain's value is an array (the chain mechanism's own shape);
      // __insert_lora's is a plain string. Normalize on read so the button
      // label works either way.
      function _currentPickedLora() {
        var val = _wfAdvOverrides[id][insertKey];
        if (existingLoraNodeId) {
          return (Array.isArray(val) && val[0] && val[0].lora_name) || '';
        }
        return val || '';
      }
      function _syncLoraBtnLabel() {
        var picked = _currentPickedLora();
        if (picked) {
          loraBtn.innerHTML = '<span>LoRA: ' + escHtml(_loraFileLabel(picked)) + '</span>';
          loraClearBtn.hidden = false;
        } else {
          loraBtn.innerHTML = '<span>Choose a LoRA</span>';
          loraClearBtn.hidden = true;
        }
      }
      loraClearBtn.addEventListener('click', function () {
        delete _wfAdvOverrides[id][insertKey];
        _syncLoraBtnLabel();
        saveParams();
      });
      loraBtn.addEventListener('click', function () {
        openOptionsPanel('Choose a LoRA', function (panelBody) {
          _fillLoraTreePanel(panelBody, function (pickedPath) {
            _wfAdvOverrides[id][insertKey] = existingLoraNodeId
              ? [{ lora_name: pickedPath }]
              : pickedPath;
            _syncLoraBtnLabel();
            saveParams();
            closeOptionsPanel();
          });
        }, { wide: true });
      });
      _syncLoraBtnLabel();
      loraRow.appendChild(loraBtn);
      loraRow.appendChild(loraClearBtn);
      body.appendChild(loraRow);
    }

    var advWrap = document.createElement('div');
    body.appendChild(advWrap);

    function renderAdvInputs() {
      buildAdvParams(record, advWrap, _wfAdvOverrides[id], id + '-');
      enhanceAdvParamsWithOptions(record, advWrap, _wfAdvOverrides[id]);
    }

    function renderPresetPills() {
      presetListEl.innerHTML = '';
      presets.forEach(function (p) {
        var isApplied = p.id === _wfActivePreset[id];
        var pbtn = document.createElement('button');
        pbtn.type = 'button';
        pbtn.className = 'nsc-quality-btn' + (isApplied ? ' is-active' : '');
        pbtn.setAttribute('role', 'radio');
        pbtn.setAttribute('data-quality-id', p.id);
        pbtn.setAttribute('aria-checked', isApplied ? 'true' : 'false');
        pbtn.innerHTML =
          '<span class="nsc-quality-dot"></span>' +
          '<span class="nsc-quality-copy"><strong>' + escHtml(p.label) + '</strong>' +
          (p.sub ? '<small>' + escHtml(p.sub) + '</small>' : '') + '</span>';
        pbtn.addEventListener('click', function () {
          if (!p.values) return;
          Object.assign(_wfAdvOverrides[id], p.values);
          _wfActivePreset[id] = p.id;
          renderPresetPills();
          updateStateLabel();
          renderAdvInputs();
          saveParams();
        });
        presetListEl.appendChild(pbtn);
      });
    }

    function updateStateLabel() {
      var active = _wfActivePreset[id]
        ? presets.find(function (p) { return p.id === _wfActivePreset[id]; })
        : null;
      stateLabel.textContent = active ? active.label : '';
    }

    resetBtn.addEventListener('click', function () {
      _wfAdvOverrides[id] = {};
      _wfActivePreset[id] = null;
      renderPresetPills();
      updateStateLabel();
      renderAdvInputs();
      saveParams();
    });

    _wfTabRefreshFns[id] = function () {
      renderPresetPills();
      updateStateLabel();
      renderAdvInputs();
    };

    renderPresetPills();
    updateStateLabel();
    renderAdvInputs();
  }).catch(function () {
    body.innerHTML = '<p class="nse-model-empty">Could not load workflow.</p>';
  });
}

function _removeWfTab(id) {
  if (_wfTabBtnEls[id])  { _wfTabBtnEls[id].remove();  delete _wfTabBtnEls[id]; }
  if (_wfTabBodyEls[id]) { _wfTabBodyEls[id].remove(); delete _wfTabBodyEls[id]; }
  if (_wfActiveTabId === id) _wfActiveTabId = null;
  delete _wfAdvOverrides[id];
  delete _wfActivePreset[id];
  saveParams();
}

function renderWfParamsAside() {
  if (!_wfAsideEl) return;
  var isCustom = getMode() === 'advanced';
  var ids = getGlobalWorkflows();
  var show = isCustom && ids.length > 0;
  _wfAsideEl.hidden = !show;
  if (!show) return;

  Object.keys(_wfTabBtnEls).forEach(function (id) {
    if (ids.indexOf(id) === -1) _removeWfTab(id);
  });
  ids.forEach(function (id) {
    if (!_wfTabBtnEls[id]) _createWfTab(id);
  });
  ids.forEach(function (id, idx) { _wfTabBtnEls[id].textContent = String(idx + 1); });

  if (!_wfActiveTabId || ids.indexOf(_wfActiveTabId) === -1) {
    _activateWfTab(ids[0]);
  }
}

document.addEventListener('ncf-mode-change', renderWfParamsAside);
