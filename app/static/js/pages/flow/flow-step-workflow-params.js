'use strict';
// Step: workflow_params + param_group → renderWorkflowParams, renderParamGroup

function renderWorkflowParams(stepDef, el, stepNum) {
  var fields = Array.isArray(stepDef.fields) ? stepDef.fields : [];

  // workflow_file is fixed in the step def — store it immediately, no picker needed
  if (stepDef.workflow_file) {
    setVal(stepDef.id, 'workflow_file', stepDef.workflow_file);
  }

  // ── Prompt (always visible, above everything else) ─────────────────────
  // Fields of type "prompt_history" render here — label + history-clock
  // button + textarea, same look/behaviour as Create's dedicated prompt_input
  // step — instead of as just another row buried in the params list.
  var promptBlockRW = document.createElement('div');
  el.appendChild(promptBlockRW);

  // Parameter fields (non-"advanced" ones only — see below)
  var fieldsWrap = document.createElement('div');
  fieldsWrap.className = 'nsc-adv-params';
  el.appendChild(fieldsWrap);

  // ── Advanced panel — Parameters (fields flagged "advanced": true) +
  // Quantization (workflow_file flows whose `config` node declares one) ──
  // Same "Advanced" round-button + options-panel pattern as Create
  // (renderParamGroup below), but built here for plain workflow_file flows
  // (Refine's Qwen 2511 Edit, Flux Klein Edit, ...) which have no import
  // record to read analysis from.
  // Fields with advanced_group: 'after_quant' (e.g. Face Swap's LoRA
  // quality picker) render into their own block placed AFTER Quantization
  // instead of into the regular "Parameters" block above it — everything
  // else keeps the original order.
  var advFieldsRW = fields.filter(function (f) { return f.advanced === true && f.advanced_group !== 'after_quant'; });
  var postQuantFieldsRW = fields.filter(function (f) { return f.advanced === true && f.advanced_group === 'after_quant'; });
  var paramsBodyRW = null; // container advanced-flagged fields render into (see renderFields)
  var postQuantBodyRW = null; // container for advanced_group: 'after_quant' fields
  var advRowRW = null, advBtnRW = null;

  // Picks the right container for an advanced-flagged field — regular
  // Parameters block, the after-Quantization block, or (non-advanced)
  // straight into the normal fields list.
  function _advFieldBody(f) {
    if (f.advanced_group === 'after_quant' && postQuantBodyRW) return postQuantBodyRW;
    if (f.advanced && paramsBodyRW) return paramsBodyRW;
    return fieldsWrap;
  }

  // A step whose only field is an engine_select (Choose engine, split out by
  // flow_engine.py's _build_mix_flow_definition) sets skip_quantization —
  // its own Quantization/Advanced block would just duplicate the real
  // Parameters step's (same workflow_file on load) and its adv_values are
  // never read anywhere, so there's nothing to show here.
  var _quantEligibleRW = stepDef.workflow_file && !stepDef.skip_quantization;
  if (_quantEligibleRW || advFieldsRW.length || postQuantFieldsRW.length) {
    advRowRW = document.createElement('div');
    advRowRW.className = 'nsc-param-title nsc-param-title--flex nsc-param-title--gap-top';
    advRowRW.style.display = (advFieldsRW.length || postQuantFieldsRW.length) ? '' : 'none'; // shown right away if there are advanced fields; quantization (async) can also reveal it below
    advRowRW.textContent = tF('Advanced');
    el.insertBefore(advRowRW, fieldsWrap.nextSibling);

    advBtnRW = document.createElement('button');
    advBtnRW.type = 'button';
    advBtnRW.className = 'nsc-history-btn nsc-options-trigger';
    advBtnRW.setAttribute('aria-label', 'Advanced options');
    advBtnRW.innerHTML =
      '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M3 4.5h10M3 8h10M3 11.5h10"/><circle cx="6" cy="4.5" r="1.3" fill="currentColor" stroke="none"/>' +
        '<circle cx="10" cy="8" r="1.3" fill="currentColor" stroke="none"/><circle cx="6.5" cy="11.5" r="1.3" fill="currentColor" stroke="none"/>' +
      '</svg>';
    advRowRW.appendChild(advBtnRW);

    var panelBlocksRW = [];

    if (advFieldsRW.length) {
      var paramsBlockRW = document.createElement('div');
      paramsBlockRW.className = 'nsc-param-block';
      paramsBlockRW.innerHTML = '<p class="nsc-param-title">Parameters</p>';
      paramsBodyRW = document.createElement('div');
      paramsBodyRW.className = 'nsc-adv-params';
      paramsBlockRW.appendChild(paramsBodyRW);
      panelBlocksRW.push(paramsBlockRW);
    }

    var quantBlockRW = null, quantListElRW = null;
    if (_quantEligibleRW) {
      quantBlockRW = document.createElement('div');
      quantBlockRW.className = 'nsc-param-block';
      quantBlockRW.innerHTML = '<p class="nsc-param-title">Quantization</p>';
      quantListElRW = document.createElement('div');
      quantListElRW.className = 'nsc-quality-list';
      quantListElRW.setAttribute('role', 'radiogroup');
      quantBlockRW.appendChild(quantListElRW);
      panelBlocksRW.push(quantBlockRW);
    }

    if (postQuantFieldsRW.length) {
      var postQuantBlockRW = document.createElement('div');
      postQuantBlockRW.className = 'nsc-param-block';
      postQuantBlockRW.innerHTML = '<p class="nsc-param-title">' + escHtml(postQuantFieldsRW[0].advanced_group_label || 'LoRA') + '</p>';
      postQuantBodyRW = document.createElement('div');
      postQuantBodyRW.className = 'nsc-adv-params';
      postQuantBlockRW.appendChild(postQuantBodyRW);
      panelBlocksRW.push(postQuantBlockRW);
    }

    advBtnRW.addEventListener('click', function () {
      openOptionsPanel(tF('Advanced'), function (body) {
        panelBlocksRW.forEach(function (b) { body.appendChild(b); });
      });
    });

    if (_quantEligibleRW) {
      fetch('/api/models/workflow-file/analysis?file=' + encodeURIComponent(stepDef.workflow_file))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (res) {
          var analysis = res && res.analysis;
          var record = analysis ? { analysis: analysis } : null;
          buildQuantizationList(record, quantListElRW, buildAdv);
          var hasQuant = !!selectedQuantizationValues;
          if (hasQuant) { advRowRW.style.display = ''; buildAdv(); }
        })
        .catch(function () {});
    }
  }

  // ── Live preview (opt-in via stepDef.live_preview) ─────────────────────────
  // For local/fast refine flows (Remove Background & friends) it's cheap
  // enough to re-run the actual ComfyUI workflow on every param tweak. When
  // enabled, this populates the dedicated #ncf-live-preview-aside column
  // (a real second aside, next to the main steps panel — not squeezed inside
  // the step card) with a debounced re-render, a background swatch picker
  // (to spot alpha edge fringing against checkers/magenta/green/black/white),
  // and a floating magnifier lens on hover.
  var livePreviewEnabled = !!stepDef.live_preview;
  var _scheduleLivePreview = null; // assigned below when enabled

  if (livePreviewEnabled) {
    var lpAside = document.getElementById('ncf-live-preview-aside');
    if (lpAside) {
      lpAside.innerHTML = ''; // avoid stacking duplicates on re-render (mode toggle, etc.)
      lpAside.hidden = false;
      _buildLivePreviewPanel(stepDef, lpAside, function (fn) { _scheduleLivePreview = fn; });
    }
  }

  var previewUpdateFn = null;
  function triggerPreviewUpdate() { if (previewUpdateFn) previewUpdateFn(); }
  var composePreviewUpdaters = {};

  function buildAdv() {
    var advVals = {};
    var previewedKeys = {};
    fields.forEach(function (f) {
      if (f.type === 'compose_preview' && f.adv_key) previewedKeys[f.adv_key] = true;
    });
    fields.forEach(function (f) {
      if (f.type === 'compose' && Array.isArray(f.groups)) {
        if (previewedKeys[f.adv_key]) return;
        var parts = f.groups.map(function (g) {
          return String(getVal(stepDef.id, 'compose_' + f.id + '_' + g.id) || '');
        }).filter(function (v) { return v.trim() !== ''; });
        if (parts.length && f.adv_key) advVals[f.adv_key] = (f.prefix || '') + parts.join(f.separator || ', ');
      } else if (f.type === 'compose_preview') {
        var stored = getVal(stepDef.id, 'field_' + f.id);
        if (stored != null && stored !== '' && f.adv_key) advVals[f.adv_key] = String(stored);
      } else if (f.type === 'aspect_ratio') {
        var _arPSet = (f.presets_id && ASPECT_PRESET_SETS[f.presets_id]) ? ASPECT_PRESET_SETS[f.presets_id] : ASPECT_PRESETS;
        var aspectKey = getVal(stepDef.id, 'field_' + f.id) || f.default || _arPSet[Math.floor(_arPSet.length / 2)].key;
        var preset = _arPSet.filter(function (p) { return p.key === aspectKey; })[0] || _arPSet[Math.floor(_arPSet.length / 2)];
        var dims = preset[f.resolution || 'md'] || preset.md;
        if (f.adv_keys) {
          if (f.adv_keys.width)  advVals[f.adv_keys.width]  = dims.w;
          if (f.adv_keys.height) advVals[f.adv_keys.height] = dims.h;
        }
      } else if (f.type === 'image_scale') {
        // adv_key gets blanked server-side because "_preprocess.scale" is not a
        // real workflow node; fall back to key / the known preprocess key.
        var scKey = f.adv_key || f.key || '_preprocess.scale';
        var stored = getVal(stepDef.id, 'field_' + f.id);
        var val = (stored !== undefined && stored !== null && stored !== '') ? Number(stored) : (f.default !== undefined ? Number(f.default) : 100);
        advVals[scKey] = val;
      } else if (f.type === 'scale_slider') {
        // Percent in the UI (25–200%) maps to a plain multiplier (0.25–2.0)
        // on the actual ImageScaleBy-style node input.
        var stored = getVal(stepDef.id, 'field_' + f.id);
        var pct = (stored !== undefined && stored !== null && stored !== '') ? Number(stored) : (f.default !== undefined ? Number(f.default) : 100);
        if (f.adv_key) advVals[f.adv_key] = pct / 100;
      } else if (f.type === 'position_grid') {
        var posKey = f.key || f.adv_key;
        if (posKey) {
          var storedPos = getVal(stepDef.id, 'field_' + f.id);
          advVals[posKey] = String((storedPos != null && storedPos !== '') ? storedPos : (f.default || 'center'));
        }
        var storedOffX = getVal(stepDef.id, 'field_' + f.id + '_offx');
        var storedOffY = getVal(stepDef.id, 'field_' + f.id + '_offy');
        advVals['_preprocess.offset_x'] = (storedOffX !== undefined && storedOffX !== null && storedOffX !== '') ? Number(storedOffX) : 0;
        advVals['_preprocess.offset_y'] = (storedOffY !== undefined && storedOffY !== null && storedOffY !== '') ? Number(storedOffY) : 0;
      } else if (f.type === 'canvas_preview') {
        // no adv value
      } else if (f.type === 'seed') {
        var stored = getVal(stepDef.id, 'field_' + f.id);
        var val = (stored !== undefined && stored !== null && stored !== '')
          ? Number(stored)
          : Math.floor(Math.random() * 0x7FFFFFFF);
        if (f.adv_key) advVals[f.adv_key] = val;
      } else if (f.type === 'toggle') {
        // ComfyUI node "mode": 0 = active, 4 = bypass/mute. adv_key must be
        // "<nodeId>._mode" so the backend applies it to the node's mode
        // property (not a regular "inputs" field).
        var storedTg = getVal(stepDef.id, 'field_' + f.id);
        var isOn = (storedTg !== undefined && storedTg !== null) ? !!storedTg : !!f.default;
        if (f.adv_key) advVals[f.adv_key] = isOn ? 0 : 4;
      } else if (f.type === 'checkbox') {
        // Plain boolean widget input (e.g. refine_foreground) — unlike
        // "toggle" above, this writes the real JS boolean straight into the
        // node's own input, not a node-mode bypass.
        var storedCb = getVal(stepDef.id, 'field_' + f.id);
        var isOnCb = (storedCb !== undefined && storedCb !== null) ? !!storedCb : !!f.default;
        if (f.adv_key) advVals[f.adv_key] = isOnCb;
      } else if (f.type === 'preset_group') {
        // Doesn't map to a node input itself — it only pushes values into
        // other fields (see f.targets) when clicked. Nothing to add here.
      } else if (f.type === 'engine_select') {
        // Doesn't map to a node input itself — picking an engine mutates the
        // adv_key of the other fields (prompt/steps/cfg/seed) plus
        // stepDef.workflow_file/image_node directly (see the render branch
        // below), so by the time we get here those fields' own branches
        // above already write into the right node ids for whichever engine
        // is currently selected.
      } else {
        var stored = getVal(stepDef.id, 'field_' + f.id);
        var val = (stored !== undefined && stored !== null && stored !== '') ? stored : f.default;
        if (val !== undefined) {
          advVals[f.adv_key] = (f.type === 'number' || f.type === 'slider') ? Number(val) : String(val);
        }
      }
    });
    // Quantization override (INT8/FP8/NVFP4/...) picked in the Advanced panel
    // above — swaps unet_name (and clip_name, if that level pairs one) on top
    // of whatever the field loop produced.
    if (stepDef.workflow_file && selectedQuantizationValues) {
      Object.keys(selectedQuantizationValues).forEach(function (k) {
        advVals[k] = selectedQuantizationValues[k];
      });
    }
    setVal(stepDef.id, 'adv_values', advVals);
    if (_scheduleLivePreview) _scheduleLivePreview();
  }

  function renderFields() {
    fieldsWrap.innerHTML = '';
    if (paramsBodyRW) paramsBodyRW.innerHTML = '';
    if (postQuantBodyRW) postQuantBodyRW.innerHTML = '';
    promptBlockRW.innerHTML = '';
    fields.forEach(function (f) {

      // ── engine_select (base-engine picker — Qwen 2511 Edit / Klein 9B /
      // Klein 4B, ...) — pills above the prompt. Different engines are
      // different ComfyUI graphs (different node ids), so switching engine
      // doesn't just change a value: it swaps stepDef.workflow_file +
      // image_node, and re-points the shared prompt/steps/cfg/seed fields'
      // adv_key at that engine's node ids (mutating the field objects in
      // `fields`, which buildAdv() reads fresh every time it runs — no
      // separate re-render of those fields needed). Also re-fetches the
      // Quantization list in the Advanced panel, since those options are
      // per-workflow-file too. ───────────────────────────────────────────
      if (f.type === 'engine_select') {
        var esEngines = Array.isArray(f.engines) ? f.engines : [];
        if (!esEngines.length) return;

        // Plain full-width <select> (same nsc-select-wrapper/chevron pattern
        // as Create's "Choose a workflow" picker, flow-step-workflow-picker.js)
        // instead of the old icon-button + flyout-menu — same simple look
        // across the app, no icon needed. f.label is optional: when this
        // field is split into its own step (see _build_mix_flow_definition /
        // _build_refine_flow_definition), the step's own heading already
        // says "Choose engine", so no extra label here in that case.
        //
        // The label is its own block title (nsc-param-title — uppercase,
        // same as every other section heading in this panel, e.g. "DOWNSCALE
        // SOURCE"), not an inline nsc-field-label beside the select — it used
        // to be the latter, which read as a smaller, non-uppercase row label
        // instead of matching the rest of the panel (#72).
        if (f.label) {
          var esTitle = document.createElement('p');
          esTitle.className = 'nsc-param-title';
          esTitle.textContent = f.label;
          fieldsWrap.appendChild(esTitle);
        }

        var esRow = document.createElement('div');
        esRow.className = 'nsc-field-row nsc-field-row--prompt';

        var esWrap = document.createElement('div');
        esWrap.className = 'nsc-select-wrapper';
        var esSelect = document.createElement('select');
        esSelect.className = 'nsc-select';
        esWrap.appendChild(esSelect);
        esWrap.insertAdjacentHTML('beforeend',
          '<svg class="nsc-select-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>');
        esRow.appendChild(esWrap);
        fieldsWrap.appendChild(esRow);

        var esStoredId = getVal(stepDef.id, 'field_' + f.id) || f.default || esEngines[0].id;

        esEngines.forEach(function (eng) {
          var opt = document.createElement('option');
          opt.value = eng.id;
          opt.textContent = eng.label;
          if (eng.id === esStoredId) opt.selected = true;
          esSelect.appendChild(opt);
        });

        function esApplyEngine(engineId) {
          var eng = esEngines.filter(function (e) { return e.id === engineId; })[0] || esEngines[0];
          setVal(stepDef.id, 'field_' + f.id, eng.id);
          esSelect.value = eng.id;
          stepDef.workflow_file = eng.workflow_file;
          stepDef.image_node = eng.image_node;
          setVal(stepDef.id, 'workflow_file', eng.workflow_file);

          fields.forEach(function (other) {
            if (other.id === 'prompt'   && eng.prompt_key) other.adv_key = eng.prompt_key;
            if (other.id === 'negative' && eng.neg_key)    other.adv_key = eng.neg_key;
            if (other.id === 'steps'    && eng.steps_key)  other.adv_key = eng.steps_key;
            if (other.id === 'cfg'      && eng.cfg_key)    other.adv_key = eng.cfg_key;
            if (other.id === 'seed'     && eng.seed_key)   other.adv_key = eng.seed_key;
          });

          if (quantListElRW) {
            fetch('/api/models/workflow-file/analysis?file=' + encodeURIComponent(eng.workflow_file))
              .then(function (r) { return r.ok ? r.json() : null; })
              .then(function (res) {
                var analysis = res && res.analysis;
                var record = analysis ? { analysis: analysis } : null;
                buildQuantizationList(record, quantListElRW, buildAdv);
                buildAdv();
                triggerPreviewUpdate();
              })
              .catch(function () { buildAdv(); triggerPreviewUpdate(); });
          } else {
            buildAdv();
            triggerPreviewUpdate();
          }
        }

        esSelect.addEventListener('change', function () { esApplyEngine(esSelect.value); });

        // Apply the initially-selected engine's node mapping right away, so
        // the very first buildAdv() call (and image_node used for preview /
        // submit) already point at the right graph before any click.
        esApplyEngine(esStoredId);
        return;
      }

      // ── prompt_history (label + history-clock button + textarea, always
      // visible above Parameters/Advanced — same widget Create uses for its
      // dedicated prompt_input step) ──────────────────────────────────────
      if (f.type === 'prompt_history') {
        var phRow = document.createElement('div');
        phRow.className = 'nsc-field-row nsc-field-row--prompt';

        var phHeader = document.createElement('div');
        phHeader.className = 'nsc-field-header';
        var phLbl = document.createElement('label');
        phLbl.className = 'nsc-field-label';
        phLbl.textContent = f.label || 'Your prompt';
        phHeader.appendChild(phLbl);

        var phHistBtn = document.createElement('button');
        phHistBtn.type = 'button';
        phHistBtn.className = 'nsc-history-btn nsc-options-trigger';
        phHistBtn.setAttribute('aria-label', 'Prompt history');
        phHistBtn.innerHTML =
          '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
            '<circle cx="8" cy="8" r="6"/><path d="M8 5v3.5l2 1.5"/>' +
          '</svg>';
        phHeader.appendChild(phHistBtn);

        if (f.style_prompt_edit) {
          var phEditBtn = document.createElement('button');
          phEditBtn.type = 'button';
          phEditBtn.className = 'nsc-history-btn nsc-options-trigger';
          phEditBtn.setAttribute('aria-label', 'Edit prompt');
          phEditBtn.title = 'Edit prompt (prefix / idea / suffix)';
          phEditBtn.innerHTML =
            '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M11 2l3 3-8 8-3.5 1 1-3.5z"/>' +
            '</svg>';
          phHeader.appendChild(phEditBtn);
        }
        phRow.appendChild(phHeader);

        var phTa = document.createElement('textarea');
        phTa.className = 'nsc-textarea';
        phTa.rows = f.rows || 3;
        phTa.placeholder = f.placeholder || '';
        var phStored = getVal(stepDef.id, 'field_' + f.id);
        phTa.value = (phStored !== undefined && phStored !== null) ? phStored : (f.default || '');
        setVal(stepDef.id, 'field_' + f.id, phTa.value);
        phRow.appendChild(phTa);

        if (f.style_prompt_edit) {
          (function (phEditBtnRef, phTaRef, fIdRef) {
            function _applyEditedPromptPh(composed) {
              setVal(stepDef.id, 'field_' + fIdRef, composed);
              buildAdv();
              triggerPreviewUpdate();
            }
            phEditBtnRef.addEventListener('click', function () {
              _openEditPromptPanel('image', phTaRef, _applyEditedPromptPh, 'Edit Prompt');
            });
            // Same cross-step registry prompt_input uses (flow-step-prompt-input.js)
            // — lets the sibling image step's "Choose a Style" pick pop this
            // panel open right away, titled "Edit Prompt from Style".
            window._ncfEditPromptOpeners = window._ncfEditPromptOpeners || {};
            window._ncfEditPromptOpeners['image'] = function (title) {
              _openEditPromptPanel('image', phTaRef, _applyEditedPromptPh, title);
            };
          })(phEditBtn, phTa, f.id);
        }

        phHistBtn.addEventListener('click', function () {
          openHistoryModal(stepDef.id + '_' + f.id, function (text) {
            phTa.value = text;
            setVal(stepDef.id, 'field_' + f.id, text.trim());
            buildAdv();
          });
        });
        phTa.addEventListener('input', function () {
          setVal(stepDef.id, 'field_' + f.id, phTa.value);
          buildAdv();
          triggerPreviewUpdate();
        });

        promptBlockRW.appendChild(phRow);
        return;
      }

      // ── style_picker (label + "Choose a Style" button + editable textarea —
      // same shape as prompt_history above, just seeded from a saved Style
      // instead of prompt history). buildAdv()'s generic fallback branch
      // already reads getVal(stepDef.id, 'field_' + f.id) into adv_key, same
      // as prompt_history, so no buildAdv() changes are needed here. ────────
      if (f.type === 'style_picker') {
        var spRow = document.createElement('div');
        spRow.className = 'nsc-field-row nsc-field-row--prompt';

        var spHeader = document.createElement('div');
        spHeader.className = 'nsc-field-header';
        var spLbl = document.createElement('label');
        spLbl.className = 'nsc-field-label';
        spLbl.textContent = f.label || 'Style';
        spHeader.appendChild(spLbl);

        var spPickBtn = document.createElement('button');
        spPickBtn.type = 'button';
        spPickBtn.className = 'nsc-history-btn nsc-options-trigger';
        spPickBtn.setAttribute('aria-label', 'Choose a Style');
        spPickBtn.title = 'Choose a Style';
        spPickBtn.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
            '<circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/>' +
            '<path d="M12 2a10 10 0 1 0 10 10c0-1.1-.9-2-2-2h-2.3a2 2 0 0 1-2-2c0-.5.2-1 .5-1.3A2 2 0 0 0 14.7 3c-.9-.6-1.8-1-2.7-1z"/>' +
          '</svg>';
        spHeader.appendChild(spPickBtn);
        spRow.appendChild(spHeader);

        var spTa = document.createElement('textarea');
        spTa.className = 'nsc-textarea';
        spTa.rows = f.rows || 3;
        spTa.placeholder = f.placeholder || 'Choose a style, or write your own…';
        var spStored = getVal(stepDef.id, 'field_' + f.id);
        spTa.value = (spStored !== undefined && spStored !== null) ? spStored : (f.default || '');
        setVal(stepDef.id, 'field_' + f.id, spTa.value);
        spRow.appendChild(spTa);

        spPickBtn.addEventListener('click', function () {
          _openStylePickerPanel(function (style) {
            // prefix + whatever's already in the box (the actual idea/
            // subject — the style itself carries no scene of its own, only
            // its prefix/suffix wording) + suffix. Picking again later
            // wraps whatever's there *then*, including a previous pick —
            // the field stays freely editable, so that's the user's call,
            // not something to auto-detect and strip.
            var idea = spTa.value.trim();
            var composed = [style.prefix, idea, style.suffix]
              .map(function (s) { return String(s || '').trim(); })
              .filter(Boolean)
              .join(', ');
            spTa.value = composed;
            setVal(stepDef.id, 'field_' + f.id, composed);
            buildAdv();
            triggerPreviewUpdate();
          });
        });
        spTa.addEventListener('input', function () {
          setVal(stepDef.id, 'field_' + f.id, spTa.value);
          buildAdv();
          triggerPreviewUpdate();
        });

        promptBlockRW.appendChild(spRow);
        return;
      }

      // ── aspect_ratio ──────────────────────────────────────────────────────
      if (f.type === 'aspect_ratio') {
        var arPresets  = (f.presets_id && ASPECT_PRESET_SETS[f.presets_id]) ? ASPECT_PRESET_SETS[f.presets_id] : ASPECT_PRESETS;
        var arMid      = Math.floor(arPresets.length / 2);

        var arRow = document.createElement('div');
        arRow.className = 'nsc-field-row nsc-field-row--compose';
        var arLbl = document.createElement('label');
        arLbl.className = 'nsc-field-label';
        arLbl.textContent = f.label || 'Aspect ratio';
        arRow.appendChild(arLbl);

        var storedAr  = getVal(stepDef.id, 'field_' + f.id);
        var initArKey = (storedAr != null && storedAr !== '') ? storedAr : (f.default || arPresets[arMid].key);
        var initArIdx = arMid;
        arPresets.forEach(function (p, i) { if (p.key === initArKey) initArIdx = i; });

        var iconsHtml = arPresets.map(function (p, i) {
          var ic  = p.icon || { vw: 18, vh: 18, rw: 16.5, rh: 16.5 };
          var tip = p.hint ? ' title="' + p.hint + '"' : '';
          return '<div class="nsc-aspect-icon-item" data-idx="' + i + '"' + tip + '>' +
            '<svg viewBox="0 0 ' + ic.vw + ' ' + ic.vh + '" width="' + ic.vw + '" height="' + ic.vh + '">' +
            '<rect x=".75" y=".75" width="' + ic.rw + '" height="' + ic.rh + '" rx="1.5"/></svg></div>';
        }).join('');

        var ticksHtml = arPresets.map(function (p) {
          var tip = p.hint ? ' title="' + p.hint + '"' : '';
          return '<span' + tip + '>' + p.label + '</span>';
        }).join('');

        var arWidget = document.createElement('div');
        arWidget.className = 'nsc-aspect-slider-wrap';
        arWidget.innerHTML =
          '<div class="nsc-aspect-icons' + (arPresets.length > 5 ? ' nsc-aspect-icons--wide' : '') + '" aria-hidden="true">' + iconsHtml + '</div>' +
          '<input class="nsc-aspect-slider" type="range" min="0" max="' + (arPresets.length - 1) + '" step="1" value="' + initArIdx + '" aria-label="Aspect ratio">' +
          '<div class="nsc-aspect-ticks">' + ticksHtml + '</div>';
        arRow.appendChild(arWidget);
        fieldsWrap.appendChild(arRow);

        var arSlider    = arWidget.querySelector('.nsc-aspect-slider');
        var arIconItems = arWidget.querySelectorAll('.nsc-aspect-icon-item');
        var arTickSpans = arWidget.querySelectorAll('.nsc-aspect-ticks span');

        (function (fid, presets) {
          function setArAspect(idx) {
            arSlider.value = idx;
            arIconItems.forEach(function (ic, i) { ic.classList.toggle('is-active', i === idx); });
            arTickSpans.forEach(function (t, i)  { t.classList.toggle('is-active', i === idx); });
            setVal(stepDef.id, 'field_' + fid, presets[idx].key);
            buildAdv();
            triggerPreviewUpdate();
          }
          arSlider.addEventListener('input', function () { setArAspect(+arSlider.value); });
          arTickSpans.forEach(function (t, i) { t.addEventListener('click', function () { setArAspect(i); }); });
          arIconItems.forEach(function (ic, i) { ic.addEventListener('click', function () { setArAspect(i); }); });
          setArAspect(initArIdx);
        }(f.id, arPresets));
        return;
      }

      // ── position_grid ─────────────────────────────────────────────────────
      if (f.type === 'position_grid') {
        var pgRow = document.createElement('div');
        pgRow.className = 'nsc-field-row';
        var pgLbl = document.createElement('label');
        pgLbl.className = 'nsc-field-label';
        pgLbl.textContent = f.label || 'Position';
        pgRow.appendChild(pgLbl);

        var storedPos = getVal(stepDef.id, 'field_' + f.id);
        var initPos   = (storedPos != null && storedPos !== '') ? storedPos : (f.default || 'center');
        var pgPositions = [
          'top-left',    'top-center',    'top-right',
          'middle-left', 'center',        'middle-right',
          'bottom-left', 'bottom-center', 'bottom-right'
        ];

        var pgGrid = document.createElement('div');
        pgGrid.className = 'nsc-pos-grid';
        pgPositions.forEach(function (pos) {
          var cell = document.createElement('button');
          cell.type = 'button';
          cell.className = 'nsc-pos-cell';
          cell.dataset.pos = pos;
          if (pos === initPos) cell.classList.add('is-active');
          (function (p) {
            cell.addEventListener('click', function () {
              pgGrid.querySelectorAll('.nsc-pos-cell').forEach(function (c) { c.classList.remove('is-active'); });
              cell.classList.add('is-active');
              setVal(stepDef.id, 'field_' + f.id, p);
              buildAdv();
              triggerPreviewUpdate();
            });
          }(pos));
          pgGrid.appendChild(cell);
        });
        if (storedPos == null || storedPos === '') setVal(stepDef.id, 'field_' + f.id, initPos);
        pgRow.appendChild(pgGrid);

        // Fine offset (px) on top of the 3x3 grid pick — lets the placed
        // image be nudged off the exact left/center/right + top/middle/bottom
        // anchor instead of only snapping to those 9 spots. Read/written via
        // literal '_preprocess.offset_x'/'_preprocess.offset_y' adv keys
        // (same pattern as '_preprocess.scale'/'_preprocess.background' —
        // not real workflow node inputs, consumed server-side by
        // _apply_preprocess/_pad_canvas), mirrored in buildAdv() below and
        // in the canvas_preview draw so the offset is visible before submit.
        // Stacked X-over-Y, each using the same -/value/+ "numeric-stepper"
        // widget as Batch Size elsewhere in the app, instead of a bare
        // number input.
        var pgOffWrap = document.createElement('div');
        pgOffWrap.className = 'nsc-pos-offset';

        function _pgOffsetInput(axisLabel, storeSuffix) {
          var wrap = document.createElement('div');
          wrap.className = 'nsc-pos-offset-field';
          var lbl = document.createElement('span');
          lbl.className = 'nsc-pos-offset-label';
          lbl.textContent = axisLabel;

          var stored = getVal(stepDef.id, 'field_' + f.id + storeSuffix);
          var val = (stored !== undefined && stored !== null && stored !== '') ? Math.round(Number(stored)) : 0;
          setVal(stepDef.id, 'field_' + f.id + storeSuffix, val);

          var stepper = document.createElement('div');
          stepper.className = 'numeric-stepper';

          var minusBtn = document.createElement('button');
          minusBtn.type = 'button';
          minusBtn.className = 'btn numeric-stepper-btn numeric-stepper-btn-left';
          minusBtn.setAttribute('aria-label', 'Decrease ' + axisLabel + ' offset');

          var inp = document.createElement('input');
          inp.type = 'number';
          inp.step = '1';
          inp.value = val;

          var plusBtn = document.createElement('button');
          plusBtn.type = 'button';
          plusBtn.className = 'btn numeric-stepper-btn numeric-stepper-btn-right';
          plusBtn.setAttribute('aria-label', 'Increase ' + axisLabel + ' offset');

          function commit(v) {
            v = Math.round(Number(v)) || 0;
            inp.value = v;
            setVal(stepDef.id, 'field_' + f.id + storeSuffix, v);
            buildAdv();
            triggerPreviewUpdate();
          }
          minusBtn.addEventListener('click', function () { commit(Number(inp.value) - 1); });
          plusBtn.addEventListener('click', function () { commit(Number(inp.value) + 1); });
          inp.addEventListener('change', function () { commit(inp.value); });

          stepper.appendChild(minusBtn);
          stepper.appendChild(inp);
          stepper.appendChild(plusBtn);
          wrap.appendChild(lbl);
          wrap.appendChild(stepper);
          return wrap;
        }
        pgOffWrap.appendChild(_pgOffsetInput('X', '_offx'));
        pgOffWrap.appendChild(_pgOffsetInput('Y', '_offy'));
        pgRow.appendChild(pgOffWrap);

        fieldsWrap.appendChild(pgRow);
        return;
      }

      // ── image_scale ───────────────────────────────────────────────────────
      if (f.type === 'image_scale') {
        var scRow = document.createElement('div');
        scRow.className = 'nsc-field-row';
        scRow.id = 'nsc-scale-row-' + stepDef.id + '-' + f.id;
        var scLbl = document.createElement('label');
        scLbl.className = 'nsc-field-label';
        scLbl.textContent = f.label || 'Scale';
        scRow.appendChild(scLbl);

        var storedSc = getVal(stepDef.id, 'field_' + f.id);
        var initSc = (storedSc !== undefined && storedSc !== null && storedSc !== '') ? Number(storedSc) : (f.default !== undefined ? Number(f.default) : 100);
        setVal(stepDef.id, 'field_' + f.id, initSc);

        var scWrap = document.createElement('div');
        scWrap.className = 'nsc-scale-wrap';

        var scSlider = document.createElement('input');
        scSlider.type = 'range';
        scSlider.className = 'nsc-scale-slider';
        scSlider.id = 'nsc-scale-slider-' + stepDef.id + '-' + f.id;
        scSlider.min = f.min !== undefined ? String(f.min) : '10';
        scSlider.max = f.max !== undefined ? String(f.max) : '100';
        scSlider.step = '1';
        scSlider.value = String(initSc);

        var scValEl = document.createElement('span');
        scValEl.className = 'nsc-scale-value';
        scValEl.textContent = initSc + '%';

        scWrap.appendChild(scSlider);
        scWrap.appendChild(scValEl);
        scRow.appendChild(scWrap);
        fieldsWrap.appendChild(scRow);

        (function (fid, slider, valSpan) {
          slider.addEventListener('input', function () {
            var v = Number(slider.value);
            valSpan.textContent = v + '%';
            setVal(stepDef.id, 'field_' + fid, v);
            buildAdv();
            triggerPreviewUpdate();
          });
          slider.addEventListener('keydown', function (e) {
            if (!e.ctrlKey && !e.metaKey) return;
            var isDown = e.key === 'ArrowLeft' || e.key === 'ArrowDown';
            var isUp   = e.key === 'ArrowRight' || e.key === 'ArrowUp';
            if (!isDown && !isUp) return;
            e.preventDefault();
            var curr = Number(slider.value);
            var next = isDown
              ? Math.max(Number(slider.min), Math.floor((curr - 1) / 10) * 10)
              : Math.min(Number(slider.max), Math.ceil((curr + 1) / 10) * 10);
            slider.value = String(next);
            slider.dispatchEvent(new Event('input'));
          });
        }(f.id, scSlider, scValEl));
        return;
      }

      // ── scale_slider (styled like the Aspect ratio / Quality header blocks:
      // uppercase title + value badge, then the same thick slider bar) ───────
      if (f.type === 'scale_slider') {
        var ssBlock = document.createElement('div');
        ssBlock.className = 'nsc-param-block';

        var ssTitle = document.createElement('p');
        ssTitle.className = 'nsc-param-title';
        var ssLblText = document.createTextNode(f.label || 'Scale');
        ssTitle.appendChild(ssLblText);
        var ssValEl = document.createElement('span');
        ssValEl.className = 'nsc-param-value';
        ssTitle.appendChild(ssValEl);

        var ssResult = document.createElement('span');
        ssResult.className = 'nsc-param-value';
        ssResult.textContent = '';
        ssTitle.appendChild(ssResult);

        ssBlock.appendChild(ssTitle);

        var storedSs = getVal(stepDef.id, 'field_' + f.id);
        var initSs = (storedSs !== undefined && storedSs !== null && storedSs !== '') ? Number(storedSs) : (f.default !== undefined ? Number(f.default) : 100);
        setVal(stepDef.id, 'field_' + f.id, initSs);
        ssValEl.textContent = initSs + '%';

        var ssWrap = document.createElement('div');
        ssWrap.className = 'nsc-aspect-slider-wrap';

        var ssSlider = document.createElement('input');
        ssSlider.type = 'range';
        ssSlider.className = 'nsc-aspect-slider';
        ssSlider.min = f.min !== undefined ? String(f.min) : '25';
        ssSlider.max = f.max !== undefined ? String(f.max) : '200';
        ssSlider.step = f.step !== undefined ? String(f.step) : '5';
        ssSlider.value = String(initSs);
        ssWrap.appendChild(ssSlider);
        ssBlock.appendChild(ssWrap);

        var ssHint = document.createElement('div');
        ssHint.className = 'nsc-scale-recommend';
        ssHint.style.cssText = 'font-size:0.75em;opacity:0.8;margin:4px 0 0;cursor:pointer;display:none;color:var(--accent, #638cff);text-align:center;';
        ssBlock.appendChild(ssHint);

        fieldsWrap.appendChild(ssBlock);

        (function (field, fid, imgRef, slider, valSpan, resultEl, hintEl) {
          var srcImg = new Image();
          var natW = 0, natH = 0, lastUrl = '';

          function renderResult() {
            var pct = Number(slider.value) || 100;
            if (natW > 0 && natH > 0) {
              var w = Math.max(1, Math.round(natW * pct / 100));
              var h = Math.max(1, Math.round(natH * pct / 100));
              resultEl.textContent = ' · ' + w + '×' + h;
              resultEl.style.display = '';

              // ── Recommendation: suggest upscaling low-res sources, or
              // downscaling very large ones, based on input megapixels.
              var mp = (natW * natH) / 1e6;
              var recPct = null, recTxt = '';
              if (field.recommend_below_mp && mp > 0 && mp < field.recommend_below_mp) {
                recPct = field.recommend_target_pct || 200;
                recTxt = '💡 Low-res source (' + mp.toFixed(1) + ' MP) — recommended ' + recPct + '%. Click to apply.';
              } else if (field.recommend_above_mp && mp > field.recommend_above_mp) {
                var targetMp = field.recommend_target_mp || field.recommend_above_mp;
                var rawPct = Math.sqrt(targetMp / mp) * 100;
                var stepRound = Number(field.step) || 5;
                recPct = Math.max(Number(slider.min) || 25, Math.min(Number(slider.max) || 200,
                  Math.round(rawPct / stepRound) * stepRound));
                recTxt = '💡 Large source (' + mp.toFixed(1) + ' MP) — recommended ' + recPct + '%. Click to apply.';
              }
              if (recPct !== null && recPct !== pct) {
                hintEl.textContent = recTxt;
                hintEl.style.display = 'block';
                hintEl.onclick = function () {
                  slider.value = String(recPct);
                  slider.dispatchEvent(new Event('input'));
                };
              } else {
                hintEl.style.display = 'none';
              }
            } else {
              resultEl.textContent = '';
              resultEl.style.display = 'none';
              hintEl.style.display = 'none';
            }
          }

          function refreshImage() {
            var url = getVal(imgRef, 'image_data_url') || '';
            if (!url) { natW = 0; natH = 0; lastUrl = ''; renderResult(); return; }
            if (url === lastUrl) { renderResult(); return; }
            lastUrl = url;
            srcImg.onload = function () {
              natW = srcImg.naturalWidth || 0;
              natH = srcImg.naturalHeight || 0;
              renderResult();
            };
            srcImg.src = url;
            if (srcImg.complete && srcImg.naturalWidth > 0) {
              natW = srcImg.naturalWidth;
              natH = srcImg.naturalHeight;
            }
            renderResult();
          }

          slider.addEventListener('input', function () {
            var v = Number(slider.value);
            valSpan.textContent = v + '%';
            setVal(stepDef.id, 'field_' + fid, v);
            renderResult();
            buildAdv();
            triggerPreviewUpdate();
          });

          // Recompute whenever this step is (re)rendered — covers the case
          // where the user uploaded/changed the reference image beforehand.
          refreshImage();
          var _prevUpdate = previewUpdateFn;
          previewUpdateFn = function () {
            if (_prevUpdate) _prevUpdate();
            refreshImage();
          };
        }(f, f.id, f.image_ref || 'image', ssSlider, ssValEl, ssResult, ssHint));
        return;
      }

      // ── seed ──────────────────────────────────────────────────────────────
      if (f.type === 'seed') {
        var storedSd = getVal(stepDef.id, 'field_' + f.id);
        var initSd = (storedSd !== undefined && storedSd !== null && storedSd !== '')
          ? Number(storedSd)
          : Math.floor(Math.random() * 0x7FFFFFFF);
        setVal(stepDef.id, 'field_' + f.id, initSd);

        // ── "Visual similarity" toggle variant — same look/behavior as the
        // Create Simple/Guided Advanced panel's switch (flow_data-driven
        // flows like Mix don't need the raw random/fixed/increment picker;
        // ON pins a seed so repeated generations stay visually close, OFF
        // randomizes on every generation). Reuses the exact same
        // seed_mode_<id> storage key ('fixed'/'random') that _snapshotMix()
        // (flow-render-all.js) already reads at enqueue time — only the
        // control changes, not the underlying mechanism. ───────────────────
        if (f.seed_mode === 'similarity') {
          var simStoredMode = getVal(stepDef.id, 'seed_mode_' + f.id) || 'random';
          setVal(stepDef.id, 'seed_mode_' + f.id, simStoredMode);
          var simIsOn = simStoredMode === 'fixed';

          var simBlockRW = document.createElement('div');
          simBlockRW.className = 'nsc-param-block';
          var simToggleRW = document.createElement('button');
          simToggleRW.type = 'button';
          simToggleRW.className = 'create-basic-similarity-toggle' + (simIsOn ? '' : ' off');
          simToggleRW.setAttribute('aria-pressed', simIsOn ? 'true' : 'false');
          simToggleRW.innerHTML =
            '<span class="create-basic-similarity-label">' + escHtml(f.label || 'Visual similarity') + '</span>' +
            '<div class="create-basic-switch"><div class="create-basic-switch-thumb"></div></div>';
          simBlockRW.appendChild(simToggleRW);

          simToggleRW.addEventListener('click', function () {
            var wasOff = simToggleRW.classList.toggle('off');
            var nowOn = !wasOff;
            simToggleRW.setAttribute('aria-pressed', nowOn ? 'true' : 'false');
            if (nowOn) {
              // Pin whatever seed is currently stored so the very next
              // generation matches the last one, then keep it fixed.
              setVal(stepDef.id, 'seed_mode_' + f.id, 'fixed');
            } else {
              setVal(stepDef.id, 'seed_mode_' + f.id, 'random');
            }
            buildAdv();
          });

          _advFieldBody(f).appendChild(simBlockRW);
          return;
        }

        var seedRow = document.createElement('div');
        seedRow.className = 'nsc-field-row nsc-field-row--seed';
        var seedLbl = document.createElement('label');
        seedLbl.className = 'nsc-field-label';
        seedLbl.textContent = f.label || 'Seed';
        seedRow.appendChild(seedLbl);

        // ── seed_mode variant (fixed / increment / random) ──────────────────
        if (f.seed_mode) {
          var storedMode = getVal(stepDef.id, 'seed_mode_' + f.id) || 'random';
          setVal(stepDef.id, 'seed_mode_' + f.id, storedMode);

          var modeSelect = document.createElement('select');
          modeSelect.className = 'nsc-select nsc-select--sm nsc-select--seedmode';
          modeSelect.id = 'ncf-seedmode-' + stepDef.id + '-' + f.id;
          ['random', 'fixed', 'increment'].forEach(function (m) {
            var o = document.createElement('option');
            o.value = m;
            o.textContent = m.charAt(0).toUpperCase() + m.slice(1);
            if (m === storedMode) o.selected = true;
            modeSelect.appendChild(o);
          });

          var sdInput = document.createElement('input');
          sdInput.className = 'nsc-input nsc-input--seed nsc-input--num-fixed';
          sdInput.type = 'number';
          sdInput.min = '0';
          sdInput.id = 'ncf-seed-' + stepDef.id + '-' + f.id;
          sdInput.value = initSd;
          sdInput.disabled = storedMode === 'random';

          var sdBtn = document.createElement('button');
          sdBtn.type = 'button';
          sdBtn.className = 'nsc-icon-btn';
          sdBtn.title = 'New random seed';
          sdBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>';

          (function (inp, sel, btn) {
            sel.addEventListener('change', function () {
              var m = sel.value;
              setVal(stepDef.id, 'seed_mode_' + f.id, m);
              inp.disabled = m === 'random';
            });
            inp.addEventListener('input', function () {
              var v = inp.value === '' ? 0 : (Number(inp.value) || 0);
              setVal(stepDef.id, 'field_' + f.id, v);
              buildAdv();
            });
            btn.addEventListener('click', function () {
              var v = Math.floor(Math.random() * 0x7FFFFFFF);
              inp.value = v;
              setVal(stepDef.id, 'field_' + f.id, v);
              buildAdv();
            });
          }(sdInput, modeSelect, sdBtn));

          seedRow.appendChild(modeSelect);
          seedRow.appendChild(sdInput);
          seedRow.appendChild(sdBtn);
          _advFieldBody(f).appendChild(seedRow);
          return;
        }

        // ── simple seed (random + dice) ─────────────────────────────────────
        var sdInput = document.createElement('input');
        sdInput.className = 'nsc-input nsc-input--seed';
        sdInput.type = 'number';
        sdInput.min = '0';
        sdInput.value = initSd;

        var sdBtn = document.createElement('button');
        sdBtn.type = 'button';
        sdBtn.className = 'nsc-icon-btn';
        sdBtn.title = 'New random seed';
        sdBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>';

        (function (inp) {
          inp.addEventListener('input', function () {
            var v = inp.value === '' ? -1 : (Number(inp.value) || -1);
            setVal(stepDef.id, 'field_' + f.id, v);
            buildAdv();
          });
          sdBtn.addEventListener('click', function () {
            var v = Math.floor(Math.random() * 0x7FFFFFFF);
            inp.value = v;
            setVal(stepDef.id, 'field_' + f.id, v);
            buildAdv();
          });
        }(sdInput));

        seedRow.appendChild(sdInput);
        seedRow.appendChild(sdBtn);
        _advFieldBody(f).appendChild(seedRow);
        return;
      }

      // ── toggle (same look as the "Visual similarity" switch in Create
      // Simple: a full-width button with label + pill switch) ────────────────
      if (f.type === 'toggle' || f.type === 'checkbox') {
        var tgBlock = document.createElement('div');
        tgBlock.className = 'nsc-param-block';

        var storedTg = getVal(stepDef.id, 'field_' + f.id);
        var initOn = (storedTg !== undefined && storedTg !== null) ? !!storedTg : !!f.default;
        setVal(stepDef.id, 'field_' + f.id, initOn);

        var tgBtn = document.createElement('button');
        tgBtn.type = 'button';
        tgBtn.className = 'create-basic-similarity-toggle' + (initOn ? '' : ' off');
        tgBtn.setAttribute('aria-pressed', initOn ? 'true' : 'false');
        tgBtn.innerHTML =
          '<span class="create-basic-similarity-label"></span>' +
          '<div class="create-basic-switch"><div class="create-basic-switch-thumb"></div></div>';
        tgBtn.querySelector('.create-basic-similarity-label').textContent = f.label || f.id;
        tgBlock.appendChild(tgBtn);
        fieldsWrap.appendChild(tgBlock);

        (function (fId, btn) {
          btn.addEventListener('click', function () {
            var nowOn = btn.classList.toggle('off') === false;
            btn.setAttribute('aria-pressed', nowOn ? 'true' : 'false');
            setVal(stepDef.id, 'field_' + fId, nowOn);
            buildAdv();
            triggerPreviewUpdate();
          });
        }(f.id, tgBtn));

        return;
      }

      // ── preset_group (pill buttons that push values into other fields) ────
      if (f.type === 'preset_group') {
        var pgBlock = document.createElement('div');
        pgBlock.className = 'nsc-param-block';
        var pgTitle = document.createElement('p');
        pgTitle.className = 'nsc-param-title';
        pgTitle.textContent = f.label || 'Quality';
        pgBlock.appendChild(pgTitle);

        var pgList = document.createElement('div');
        pgList.className = 'nsc-quality-list';
        pgList.setAttribute('role', 'radiogroup');
        pgBlock.appendChild(pgList);
        fieldsWrap.appendChild(pgBlock);

        var options = Array.isArray(f.options) ? f.options : [];
        var storedPg = getVal(stepDef.id, 'field_' + f.id) ||
          f.default || (options[0] && options[0].id);
        setVal(stepDef.id, 'field_' + f.id, storedPg);

        options.forEach(function (opt) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'nsc-quality-btn' + (opt.id === storedPg ? ' is-active' : '');
          btn.setAttribute('role', 'radio');
          btn.setAttribute('aria-checked', opt.id === storedPg ? 'true' : 'false');
          btn.innerHTML = '<span class="nsc-quality-copy"><strong>' + escHtml(opt.label || opt.id) + '</strong></span>';

          btn.addEventListener('click', function () {
            setVal(stepDef.id, 'field_' + f.id, opt.id);
            pgList.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
              var active = b === btn;
              b.classList.toggle('is-active', active);
              b.setAttribute('aria-checked', active ? 'true' : 'false');
            });
            // Apply this preset's values to the target fields (f.targets maps
            // preset option keys → other field ids in the same fields array).
            var targets = f.targets || {};
            Object.keys(targets).forEach(function (optKey) {
              var targetFieldId = targets[optKey];
              if (opt[optKey] !== undefined) {
                setVal(stepDef.id, 'field_' + targetFieldId, opt[optKey]);
              }
            });
            renderFields();
          });
          pgList.appendChild(btn);
        });
        return;
      }

      // ── quality_pills (2-3 named options as a pill radiogroup, same look
      // as the Quantization INT8/FP8 picker — e.g. Face Swap's Fast/Detailed
      // LoRA choice). Unlike preset_group, this writes straight to its own
      // adv_key (via buildAdv()'s generic fallback branch) instead of
      // pushing values into other fields — it IS the value, not a shortcut
      // for filling several. No inner title: it's meant to sit inside a
      // block that already has one (e.g. the "Quality" advanced_group). ──
      if (f.type === 'quality_pills') {
        var qpBlock = document.createElement('div');
        qpBlock.className = 'nsc-param-block';
        var qpList = document.createElement('div');
        qpList.className = 'nsc-quality-list';
        qpList.setAttribute('role', 'radiogroup');
        qpBlock.appendChild(qpList);

        var qpOptions = Array.isArray(f.options) ? f.options : [];
        var storedQp = getVal(stepDef.id, 'field_' + f.id);
        if (storedQp === undefined || storedQp === null || storedQp === '') {
          var firstOpt = qpOptions[0];
          storedQp = f.default !== undefined ? f.default
            : (firstOpt && typeof firstOpt === 'object' ? (firstOpt.value !== undefined ? firstOpt.value : firstOpt.id) : firstOpt);
          setVal(stepDef.id, 'field_' + f.id, storedQp);
        }

        qpOptions.forEach(function (opt) {
          var optVal = (opt && typeof opt === 'object') ? (opt.value !== undefined ? opt.value : opt.id) : opt;
          var optLabel = (opt && typeof opt === 'object') ? (opt.label || optVal) : opt;
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'nsc-quality-btn' + (optVal === storedQp ? ' is-active' : '');
          btn.setAttribute('role', 'radio');
          btn.setAttribute('aria-checked', optVal === storedQp ? 'true' : 'false');
          btn.innerHTML = '<span class="nsc-quality-copy"><strong>' + escHtml(optLabel) + '</strong></span>';
          btn.addEventListener('click', function () {
            setVal(stepDef.id, 'field_' + f.id, optVal);
            qpList.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
              var active = b === btn;
              b.classList.toggle('is-active', active);
              b.setAttribute('aria-checked', active ? 'true' : 'false');
            });
            buildAdv();
            triggerPreviewUpdate();
          });
          qpList.appendChild(btn);
        });

        _advFieldBody(f).appendChild(qpBlock);
        return;
      }

      // ── canvas_preview ────────────────────────────────────────────────────
      if (f.type === 'canvas_preview') {
        // Client-side preview: draw the input image scaled inside the target
        // canvas so the scaling is actually visible. Geometry mirrors the
        // backend pad_canvas: scale 100% = image fitted to fill the canvas;
        // lower values shrink the image inside the canvas, leaving the
        // outpaint area (shown as a checkerboard) around it.
        var pvWrap = document.createElement('div');
        pvWrap.className = 'nsc-outpaint-preview-wrap';
        pvWrap.id = 'nsc-preview-wrap-' + stepDef.id;

        var pvCanvas = document.createElement('canvas');
        pvCanvas.className = 'nsc-outpaint-preview';
        pvCanvas.style.display = 'none';

        var pvPlaceholder = document.createElement('div');
        pvPlaceholder.className = 'nsc-outpaint-preview nsc-outpaint-preview--placeholder';
        pvPlaceholder.textContent = 'Select an image to preview';

        pvWrap.appendChild(pvCanvas);
        pvWrap.appendChild(pvPlaceholder);
        fieldsWrap.appendChild(pvWrap);

        var _pvSrcImg  = new Image();
        var _pvLastUrl = '';

        (function (canvas, placeholder, srcImg, posFieldId) {
          function doDraw() {
            var advVals  = getVal(stepDef.id, 'adv_values') || {};
            var canvasW  = Number(advVals['11.width'])  || 1024;
            var canvasH  = Number(advVals['11.height']) || 1024;
            var scalePct = advVals['_preprocess.scale'] !== undefined ? Number(advVals['_preprocess.scale']) : 100;
            var scale    = (scalePct > 0 ? scalePct : 100) / 100;
            var pos      = String(advVals['_preprocess.position'] || getVal(stepDef.id, 'field_' + posFieldId) || 'center');

            var imgNW = srcImg.naturalWidth  || 1;
            var imgNH = srcImg.naturalHeight || 1;

            // 100% = image fitted to fill the canvas; slider shrinks from there
            var fitRatio = Math.min(canvasW / imgNW, canvasH / imgNH);
            var eff   = fitRatio * Math.min(scale, 1);
            var drawW = imgNW * eff;
            var drawH = imgNH * eff;

            // top-left placement from the position string, then nudged by
            // the X/Y offset fields (px) and clamped back onto the canvas —
            // mirrors the backend's _pad_canvas clamp exactly.
            var drawX = pos.indexOf('left')  !== -1 ? 0
                      : pos.indexOf('right') !== -1 ? canvasW - drawW
                      : (canvasW - drawW) / 2;
            var drawY = pos.indexOf('top')    !== -1 ? 0
                      : pos.indexOf('bottom') !== -1 ? canvasH - drawH
                      : (canvasH - drawH) / 2;
            var offX = Number(advVals['_preprocess.offset_x']) || 0;
            var offY = Number(advVals['_preprocess.offset_y']) || 0;
            drawX = Math.max(0, Math.min(drawX + offX, Math.max(0, canvasW - drawW)));
            drawY = Math.max(0, Math.min(drawY + offY, Math.max(0, canvasH - drawH)));

            // display canvas: fit within 200px keeping the canvas aspect ratio
            var MAX = 200;
            var dispW, dispH;
            if (canvasH > canvasW) { dispH = MAX; dispW = Math.round(MAX * canvasW / canvasH); }
            else                   { dispW = MAX; dispH = Math.round(MAX * canvasH / canvasW); }

            canvas.width  = dispW;
            canvas.height = dispH;
            canvas.style.display = 'block';
            placeholder.style.display = 'none';

            var ctx = canvas.getContext('2d');
            var sx = dispW / canvasW;
            var sy = dispH / canvasH;

            // outpaint area fill — matches the chosen background. Solid colour
            // only for an "r,g,b" value; transparent / edge_blur / unknown all
            // render as a checkerboard ("area to be filled").
            var bgChoice = String(advVals['_preprocess.background'] || 'transparent');
            var rgb = bgChoice.split(',');
            var isRgb = rgb.length === 3 && rgb.every(function (c) { return c.trim() !== '' && !isNaN(+c); });
            if (isRgb) {
              ctx.fillStyle = 'rgb(' + (+rgb[0]) + ',' + (+rgb[1]) + ',' + (+rgb[2]) + ')';
              ctx.fillRect(0, 0, dispW, dispH);
            } else {
              var sq = 8;
              for (var yy = 0; yy < dispH; yy += sq) {
                for (var xx = 0; xx < dispW; xx += sq) {
                  ctx.fillStyle = ((Math.floor(xx / sq) + Math.floor(yy / sq)) % 2 === 0) ? '#2a2a2e' : '#1f1f23';
                  ctx.fillRect(xx, yy, sq, sq);
                }
              }
            }

            // the scaled input image
            ctx.drawImage(srcImg,
              Math.round(drawX * sx), Math.round(drawY * sy),
              Math.round(drawW * sx), Math.round(drawH * sy));

            // dashed outline around the placed image
            ctx.save();
            ctx.setLineDash([3, 2]);
            ctx.strokeStyle = 'rgba(255,255,255,0.6)';
            ctx.lineWidth = 1;
            ctx.strokeRect(
              Math.round(drawX * sx) + 0.5, Math.round(drawY * sy) + 0.5,
              Math.max(1, Math.round(drawW * sx) - 1), Math.max(1, Math.round(drawH * sy) - 1));
            ctx.restore();
          }

          previewUpdateFn = function () {
            var imgUrl = getVal('image', 'image_data_url') || '';
            if (!imgUrl) {
              canvas.style.display = 'none';
              placeholder.style.display = '';
              _pvLastUrl = '';
              return;
            }
            if (imgUrl !== _pvLastUrl) {
              _pvLastUrl = imgUrl;
              srcImg.onload = function () { doDraw(); };
              srcImg.src = imgUrl;
              // if the browser cached the image, onload won't fire — draw now
              if (srcImg.complete && srcImg.naturalWidth > 0) { doDraw(); }
            } else {
              doDraw();
            }
          };
        }(pvCanvas, pvPlaceholder, _pvSrcImg, f.position_field || 'position'));
        return;
      }

      // ── slider (same look as the Aspect ratio / Quality header blocks:
      // uppercase title + value badge, then the thick slider bar) ────────────
      if (f.type === 'slider') {
        var slBlock = document.createElement('div');
        slBlock.className = 'nsc-param-block';

        var slTitle = document.createElement('p');
        slTitle.className = 'nsc-param-title';
        slTitle.appendChild(document.createTextNode(f.label || f.id));

        if (f.tooltip) {
          var slTip = document.createElement('span');
          slTip.textContent = 'ⓘ';
          slTip.title = f.tooltip;
          slTip.style.cssText = 'margin-left:4px;cursor:help;opacity:0.65;font-size:0.85em;text-transform:none;letter-spacing:normal;';
          slTitle.appendChild(slTip);
        }

        var slValEl = document.createElement('span');
        slValEl.className = 'nsc-param-value';
        slTitle.appendChild(slValEl);
        slBlock.appendChild(slTitle);

        // Decimal places to display, inferred from the step (e.g. step 0.1 → 1
        // decimal) so values don't show float artifacts (0.7000000000000001)
        // or lose a trailing ".0" that Number() would otherwise drop.
        var slStepStr = f.step !== undefined ? String(f.step) : '1';
        var slDecimals = slStepStr.indexOf('.') !== -1 ? slStepStr.split('.')[1].length : 0;
        function slFmt(v) { return slDecimals > 0 ? Number(v).toFixed(slDecimals) : String(Math.round(Number(v))); }

        var storedSl = getVal(stepDef.id, 'field_' + f.id);
        var initSl = (storedSl !== undefined && storedSl !== null && storedSl !== '')
          ? Number(storedSl)
          : (f.default !== undefined ? Number(f.default) : 0);
        setVal(stepDef.id, 'field_' + f.id, initSl);
        slValEl.textContent = slFmt(initSl);

        var slWrap = document.createElement('div');
        slWrap.className = 'nsc-aspect-slider-wrap';

        var slInput = document.createElement('input');
        slInput.type = 'range';
        slInput.className = 'nsc-aspect-slider';
        slInput.min = f.min !== undefined ? String(f.min) : '0';
        slInput.max = f.max !== undefined ? String(f.max) : '100';
        slInput.step = slStepStr;
        slInput.value = String(initSl);
        slWrap.appendChild(slInput);
        slBlock.appendChild(slWrap);

        if (f.note) {
          var slNote = document.createElement('p');
          slNote.className = 'nsc-res-sub';
          slNote.style.cssText = 'margin:0.3rem 0 0;text-align:center;';
          slNote.textContent = f.note;
          slBlock.appendChild(slNote);
        }

        fieldsWrap.appendChild(slBlock);

        (function (fid, inp, valSpan) {
          inp.addEventListener('input', function () {
            var v = Number(inp.value);
            valSpan.textContent = slFmt(v);
            setVal(stepDef.id, 'field_' + fid, v);
            buildAdv();
          });
        }(f.id, slInput, slValEl));
        return;
      }

      var isNum     = f.type === 'number';
      var isCompose = f.type === 'compose' && Array.isArray(f.groups);
      var row = document.createElement('div');
      // f.block: true — render as a stacked "section" (uppercase title above,
      // full-width control below), matching the slider blocks, instead of the
      // default inline "label | input" row. Used for selects/text fields that
      // need more room than the fixed 52px label column allows (e.g.
      // Background / Background color in Remove Background).
      row.className = f.block ? 'nsc-param-block nsc-param-block--field' : 'nsc-field-row';

      var lbl = document.createElement('label');
      lbl.className = f.block ? 'nsc-param-title' : 'nsc-field-label';
      lbl.textContent = f.label || f.id;
      row.appendChild(lbl);

      if (f.block && f.tooltip) {
        // nsc-param-title--flex keeps the (i) icon on the same line as the
        // label text (a plain inline <label> wraps it to its own line once
        // the uppercase, letter-spaced title text nearly fills a narrow
        // panel — flex keeps them together instead of wrapping).
        lbl.classList.add('nsc-param-title--flex');
        var blkTip = document.createElement('span');
        blkTip.textContent = 'ⓘ';
        blkTip.title = f.tooltip;
        // Explicit margin, not just the row's flex gap (#72) — a bare text
        // node ("Edit Prompt") followed by this span doesn't reliably pick up
        // gap the way two real elements do, so the icon read as glued to the
        // label text.
        blkTip.style.cssText = 'cursor:help;opacity:0.65;font-size:0.85em;text-transform:none;letter-spacing:normal;flex-shrink:0;margin-left:0.35rem;';
        lbl.appendChild(blkTip);
      }

      if (isCompose) {
        row.classList.add('nsc-field-row--compose');
        var composeWrap = document.createElement('div');
        composeWrap.className = 'nsc-compose-wrap';
        var hasSingleGroup = f.groups.length === 1;
        f.groups.forEach(function (g) {
          var subRow = document.createElement('div');
          subRow.className = 'nsc-compose-subrow';
          if (!hasSingleGroup) {
            var subLbl = document.createElement('span');
            subLbl.className = 'nsc-compose-sublabel';
            subLbl.textContent = g.label || g.id;
            subRow.appendChild(subLbl);
          }
          var sel = document.createElement('select');
          sel.className = 'nsc-select nsc-select--sm';
          var noneOpt = document.createElement('option');
          noneOpt.value = '';
          noneOpt.textContent = '—';
          sel.appendChild(noneOpt);
          (g.options || []).forEach(function (opt) {
            var o = document.createElement('option');
            o.value = typeof opt === 'object' ? opt.value : opt;
            o.textContent = typeof opt === 'object' ? (opt.label || opt.value) : opt;
            sel.appendChild(o);
          });
          var storedG = getVal(stepDef.id, 'compose_' + f.id + '_' + g.id);
          if (storedG) sel.value = storedG;
          (function (gId, selEl, composeField) {
            selEl.addEventListener('change', function () {
              setVal(stepDef.id, 'compose_' + composeField.id + '_' + gId, selEl.value);
              buildAdv();
              if (composePreviewUpdaters[composeField.adv_key]) composePreviewUpdaters[composeField.adv_key]();
            });
          }(g.id, sel, f));
          subRow.appendChild(sel);
          composeWrap.appendChild(subRow);
        });
        row.appendChild(composeWrap);
        fieldsWrap.appendChild(row);
        return;
      }

      if (f.type === 'compose_preview') {
        row.classList.add('nsc-field-row--compose');
        var previewCompose = null;
        for (var _pci = 0; _pci < fields.length; _pci++) {
          if (fields[_pci].type === 'compose' && fields[_pci].adv_key === f.adv_key) {
            previewCompose = fields[_pci]; break;
          }
        }
        var pTa = document.createElement('textarea');
        pTa.className = 'nsc-textarea';
        pTa.rows = f.rows || 2;
        var pStored = getVal(stepDef.id, 'field_' + f.id);
        (function (field, ta, cf) {
          function getComposedText() {
            if (!cf || !Array.isArray(cf.groups)) return '';
            var parts = cf.groups.map(function (g) {
              return String(getVal(stepDef.id, 'compose_' + cf.id + '_' + g.id) || '');
            }).filter(function (v) { return v.trim() !== ''; });
            return (cf.prefix || '') + parts.join(cf.separator || ', ');
          }
          var pInit = (pStored != null && pStored !== '') ? pStored : getComposedText();
          ta.value = pInit;
          setVal(stepDef.id, 'field_' + field.id, pInit);
          composePreviewUpdaters[field.adv_key] = function () {
            var v = getComposedText();
            ta.value = v;
            setVal(stepDef.id, 'field_' + field.id, v);
            buildAdv();
          };
          ta.addEventListener('input', function () {
            setVal(stepDef.id, 'field_' + field.id, ta.value);
            buildAdv();
          });
        }(f, pTa, previewCompose));
        row.appendChild(pTa);
        fieldsWrap.appendChild(row);
        return;
      }

      var stored = getVal(stepDef.id, 'field_' + f.id);
      var initVal = (stored !== undefined && stored !== null && stored !== '')
        ? stored : (f.default !== undefined ? f.default : '');
      if (f.default !== undefined && (stored === undefined || stored === null || stored === '')) {
        setVal(stepDef.id, 'field_' + f.id, isNum ? Number(f.default) : String(f.default));
      }

      var input;
      if (isNum) {
        input = document.createElement('input');
        input.className = 'nsc-input nsc-input--num-fixed';
        input.type = 'number';
        if (f.min  !== undefined) input.min  = f.min;
        if (f.max  !== undefined) input.max  = f.max;
        if (f.step !== undefined) input.step = f.step;
        input.value = initVal;
      } else if (f.type === 'text') {
        input = document.createElement('input');
        input.type = 'text';
        input.className = 'nsc-input';
        if (f.placeholder) input.placeholder = f.placeholder;
        input.value = initVal;
      } else if (f.type === 'select') {
        input = document.createElement('select');
        input.className = 'nsc-select';

        function _populateSelect(sel, opts, currentVal) {
          sel.innerHTML = '';
          opts.forEach(function (opt) {
            var o = document.createElement('option');
            o.value = typeof opt === 'object' ? opt.value : opt;
            o.textContent = typeof opt === 'object' ? (opt.label || opt.value) : opt;
            if (o.value === String(currentVal)) o.selected = true;
            sel.appendChild(o);
          });
        }

        if (f.options_src) {
          // Populate with the static/curated list (if any) immediately, so the
          // field is usable right away instead of stuck on "Loading…" — the
          // live fetch below replaces it once ComfyUI answers, or silently
          // keeps the static list if the fetch fails or comes back empty.
          if (Array.isArray(f.options) && f.options.length) {
            _populateSelect(input, f.options, initVal);
          } else {
            var placeholder = document.createElement('option');
            placeholder.textContent = 'Loading…';
            placeholder.disabled = true;
            input.appendChild(placeholder);
            input.disabled = true;
          }
          fetch(f.options_src)
            .then(function (r) { return r.json(); })
            .then(function (data) {
              // `loras` (legacy LoRA-picker shape) or the generic `options`
              // shape (plain string array) from /param-options-style endpoints.
              var raw = Array.isArray(data.loras) ? data.loras
                      : Array.isArray(data.options) ? data.options
                      : null;
              if (!raw || !raw.length) { input.disabled = false; return; }
              var opts = raw.map(function (v) { return { value: v, label: v }; });
              // Keep the currently selected/curated value selectable even if
              // the live ComfyUI instance doesn't happen to report it.
              if (initVal && !raw.some(function (v) { return String(v) === String(initVal); })) {
                opts = [{ value: initVal, label: initVal }].concat(opts);
              }
              _populateSelect(input, opts, initVal);
              input.disabled = false;
              buildAdv();
            })
            .catch(function () {
              // Network/ComfyUI unreachable — leave whatever was already
              // populated (static list, or the disabled "Loading…" placeholder
              // if there was no static fallback) instead of erroring out.
              input.disabled = false;
            });
        } else if (Array.isArray(f.options)) {
          _populateSelect(input, f.options, initVal);
        }
      } else {
        input = document.createElement('textarea');
        input.className = 'nsc-textarea';
        input.rows = f.rows || 2;
        input.value = initVal;

        // Preset prompts: a circular icon-only button next to the label that
        // opens the shared side panel (openOptionsPanel) with the default
        // prompts (defined in the flow JSON under the field's "presets") —
        // was a text button ("Presets") + its own inline flyout menu, the
        // only field on this panel not using the shared panel pattern (#72).
        if (Array.isArray(f.presets) && f.presets.length) {
          row.classList.add('nsc-field-row--prompt');
          var header = document.createElement('div');
          header.className = 'nsc-field-header';
          row.insertBefore(header, lbl);
          header.appendChild(lbl); // move the existing "Prompt" label into the header

          var presetWrap = document.createElement('div');
          presetWrap.className = 'nsc-preset-wrap';
          var presetBtn = document.createElement('button');
          presetBtn.type = 'button';
          presetBtn.className = 'nsc-icon-btn nsc-options-trigger';
          presetBtn.setAttribute('aria-label', 'Presets');
          presetBtn.title = 'Presets';
          presetBtn.innerHTML =
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
            '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>' +
            '<line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>' +
            '<line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>';

          (function (field, inp) {
            presetBtn.addEventListener('click', function (e) {
              e.stopPropagation();
              openOptionsPanel('Presets', function (panelBody) {
                var listEl = document.createElement('div');
                listEl.className = 'nse-model-list';
                field.presets.forEach(function (p) {
                  var label = typeof p === 'object' ? (p.label || p.text || p.value || '') : String(p);
                  var text  = typeof p === 'object' ? (p.text || p.value || p.label || '') : String(p);
                  var item = document.createElement('button');
                  item.type = 'button';
                  item.className = 'nse-model-item';
                  item.title = text;
                  var nameEl = document.createElement('span');
                  nameEl.className = 'nse-model-name';
                  nameEl.textContent = label;
                  item.appendChild(nameEl);
                  item.addEventListener('click', function () {
                    inp.value = text;
                    setVal(stepDef.id, 'field_' + field.id, text);
                    buildAdv();
                    triggerPreviewUpdate();
                    closeOptionsPanel();
                  });
                  listEl.appendChild(item);
                });
                panelBody.appendChild(listEl);
              });
            });
          }(f, input));

          presetWrap.appendChild(presetBtn);
          header.appendChild(presetWrap);
        }
      }

      (function (field, inp) {
        var evName = field.type === 'select' ? 'change' : 'input';
        inp.addEventListener(evName, function () {
          var v = field.type === 'number' ? Number(inp.value) : inp.value;
          setVal(stepDef.id, 'field_' + field.id, v);
          buildAdv();
          triggerPreviewUpdate();
        });
      }(f, input));

      // Optional "Detect" button (e.g. Chroma Key's background color field):
      // calls a small server-side endpoint that samples the current image and
      // fills this field with the result — lets the user see (and then tweak)
      // whatever auto-detect would otherwise use under the hood.
      if (f.detect_endpoint) {
        var dHeader = row.querySelector('.nsc-field-header');
        if (!dHeader) {
          dHeader = document.createElement('div');
          dHeader.className = 'nsc-field-header';
          row.insertBefore(dHeader, lbl);
          dHeader.appendChild(lbl);
        }
        var detectBtn = document.createElement('button');
        detectBtn.type = 'button';
        detectBtn.className = 'nsc-preset-btn';
        detectBtn.textContent = f.detect_button_label || 'Detect';
        dHeader.appendChild(detectBtn);

        (function (field, btn, inp) {
          btn.addEventListener('click', async function () {
            var imgUrl = getVal('image', 'image_data_url') || '';
            var origText = f.detect_button_label || 'Detect';
            if (!imgUrl) {
              btn.textContent = 'Pick an image first';
              setTimeout(function () { btn.textContent = origText; }, 1500);
              return;
            }
            btn.disabled = true;
            btn.textContent = 'Detecting…';
            try {
              var res = await fetch(field.detect_endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ imageDataUrl: imgUrl }),
              });
              var data = await res.json();
              if (!res.ok || data.error) throw new Error(data.error || 'Detect failed');
              if (data.bgColorHex) {
                inp.value = data.bgColorHex;
                setVal(stepDef.id, 'field_' + field.id, data.bgColorHex);
                buildAdv();
                triggerPreviewUpdate();
              }
              btn.textContent = origText;
            } catch (err) {
              console.error('[FlowEngine] detect:', err);
              btn.textContent = 'Failed';
              setTimeout(function () { btn.textContent = origText; }, 1500);
            } finally {
              btn.disabled = false;
            }
          });
        }(f, detectBtn, input));
      }

      if (isNum) {
        _applyNcfNumericStepper(input, row);
      } else {
        row.appendChild(input);
      }

      // Quick-pick pills next to a numeric field (e.g. Steps: "4 / 8") — set
      // via f.quick_options: [4, 8, ...] in the flow JSON. Purely a shortcut;
      // the field stays freely editable either way.
      if (isNum && Array.isArray(f.quick_options) && f.quick_options.length) {
        var quickWrap = document.createElement('div');
        quickWrap.className = 'nsc-quick-options';
        (function (field, inp, wrap) {
          field.quick_options.forEach(function (val) {
            var qBtn = document.createElement('button');
            qBtn.type = 'button';
            qBtn.className = 'nsc-quick-option-btn' + (Number(inp.value) === Number(val) ? ' is-active' : '');
            qBtn.textContent = String(val);
            qBtn.addEventListener('click', function () {
              inp.value = val;
              setVal(stepDef.id, 'field_' + field.id, Number(val));
              wrap.querySelectorAll('.nsc-quick-option-btn').forEach(function (b) { b.classList.remove('is-active'); });
              qBtn.classList.add('is-active');
              buildAdv();
              triggerPreviewUpdate();
            });
            wrap.appendChild(qBtn);
          });
          inp.addEventListener('input', function () {
            wrap.querySelectorAll('.nsc-quick-option-btn').forEach(function (b) {
              b.classList.toggle('is-active', Number(b.textContent) === Number(inp.value));
            });
          });
        }(f, input, quickWrap));
      }

      _advFieldBody(f).appendChild(row);
      if (quickWrap) _advFieldBody(f).appendChild(quickWrap);
    });
    buildAdv();
    triggerPreviewUpdate();
  }

  renderFields();

}

// ── Edge defringe helper ─────────────────────────────────────────────────────
// Shared by the live preview panel (below) and the real "Remove Background"
// action run (flow-render-all.js). Reads the two virtual "_postprocess.*"
// keys from advancedValues (harmless to ComfyUI — the backend prepare route
// silently ignores dot-keys whose left side isn't a real node id) and, if
// enabled, pipes the given image URL through the edge-defringe addon,
// returning a cleaned-up data URL. Returns the original URL untouched if the
// toggle is off, the strength is 0, or anything goes wrong.
// Pass persist:true for a real generation result (Remove Background's actual
// "generate" action) so the cleaned PNG is the one that gets saved to the
// output dir and shows up in history — the live preview panel never persists
// anything, so it calls this with persist left false (default).
async function _maybeDefringeImage(imgUrl, advancedValues, persist) {
  var av = advancedValues || {};
  var enabled = av['_postprocess.defringe'];
  // Only flows that actually declare the "defringe" checkbox field opt in —
  // every other refine flow (photo edits with no alpha channel, etc.) must
  // never pay the extra round-trip, so absence of the key means "off", not
  // "on by default".
  if (enabled === undefined || !enabled) return imgUrl;
  var strength = Number(av['_postprocess.defringe_strength']);
  if (!isFinite(strength)) strength = 4;
  if (strength <= 0) return imgUrl;

  try {
    var blob = await (await fetch(imgUrl)).blob();
    var dataUrl = await new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result || '')); };
      reader.onerror = function () { reject(new Error('Could not read image')); };
      reader.readAsDataURL(blob);
    });
    var res = await fetch('/api/models/edge-defringe/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ imageDataUrl: dataUrl, strength: strength, save: !!persist }),
    });
    var data = await res.json();
    if (!res.ok || data.error) return imgUrl;
    if (persist) return data.imageUrl || imgUrl;
    return data.dataUrl || imgUrl;
  } catch (_) {
    return imgUrl; // never let a defringe hiccup break the actual result
  }
}

// ── Upscale Output helper ────────────────────────────────────────────────────
// Shared by every generation path (Refine, Mix, plain Create) via the
// upscaleOutputMode global (flow-state.js) set by the None/2xFast/4xFast/
// 4xSharp/2x/4x pill above the Generate button (renderAction, flow-render-all.js).
// 2xFast/4xFast/4xSharp run the classic single-node "Upscale (Model)" workflow
// Refine already uses (ESRGAN/UltraSharp); 2x/4x instead route through the
// SeedVR2 diffusion upscaler (3B/7B) for higher quality at the cost of speed —
// see UPSCALE_OUTPUT_SEEDVR2 in flow-state.js. Both paths go through the same
// generic /api/models/refine/prepare route, no dedicated backend endpoint
// needed — and return the upscaled, persisted image URL. Returns the
// original URL untouched if the toggle is off or anything goes wrong, so a
// hiccup here never loses the base result.
async function _maybeUpscaleOutput(imgUrl, card) {
  var mode = upscaleOutputMode;
  if (mode === 'none' || !mode) return imgUrl;
  var seedvr2 = UPSCALE_OUTPUT_SEEDVR2[mode];
  var modelName = UPSCALE_OUTPUT_MODELS[mode];
  if (!seedvr2 && !modelName) return imgUrl;

  if (generateStatus) _setBusyStatus(generateStatus, 'Upscaling…');
  var ringPctEl = null, ringStepsEl = null, ringEtaEl = null;
  if (card && card.querySelector) {
    ringPctEl   = card.querySelector('.nsc-ring-pct');
    ringStepsEl = card.querySelector('.nsc-ring-steps');
    ringEtaEl   = card.querySelector('.nsc-ring-eta');
  }
  if (ringPctEl)   ringPctEl.textContent   = 'Upscaling…';
  if (ringStepsEl) ringStepsEl.textContent = '';
  if (ringEtaEl)   ringEtaEl.textContent   = '';

  try {
    var blob = await (await fetch(imgUrl)).blob();
    var dataUrl = await new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result || '')); };
      reader.onerror = function () { reject(new Error('Could not read image')); };
      reader.readAsDataURL(blob);
    });

    var prepRes = await fetch('/api/models/refine/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(seedvr2 ? {
        workflowFile:   'workflows/upscale/refine_upscale_seedvr2.json',
        imageDataUrl:   dataUrl,
        advancedValues: {
          '66:52.unet_name': seedvr2.unetName,
          '66:57.resize_type.multiplier': seedvr2.scale,
        },
        imageNodeId:    '1',
      } : {
        workflowFile:   'workflows/upscale_2026/refine_upscale_model.json',
        imageDataUrl:   dataUrl,
        advancedValues: { '8.model_name': modelName },
        imageNodeId:    '3',
      }),
    });
    var prepData = await prepRes.json();
    if (!prepRes.ok || prepData.error) {
      _warnUpscaleOutputFailed(prepData.error);
      return imgUrl;
    }

    var submitRes = await fetch(prepData.comfyApiUrl + '/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: prepData.workflow, client_id: prepData.clientId }),
    });
    var submitData = await submitRes.json();
    if (!submitRes.ok || submitData.error || !submitData.prompt_id) {
      _warnUpscaleOutputFailed(submitData.error);
      return imgUrl;
    }

    var upscaledUrl = await waitForImage(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, null, 'Upscaling…');
    upscaledUrl = await saveFlowImage(upscaledUrl, prepData.comfyApiUrl, '', '', 0);
    if (!upscaledUrl) _warnUpscaleOutputFailed();
    return upscaledUrl || imgUrl;
  } catch (err) {
    // never let an upscale-output hiccup break the actual result — but the
    // user still needs to know the "upscaled" image they're looking at is
    // actually the un-upscaled original (e.g. the model file isn't
    // downloaded), since the caller always overwrites generateStatus with a
    // plain "✓ generated" success message right after this returns.
    _warnUpscaleOutputFailed(err && err.message);
    return imgUrl;
  }
}

function _warnUpscaleOutputFailed(detail) {
  var msg = 'Upscale output failed — showing the un-upscaled image'
    + (detail ? ' (' + detail + ')' : ' (model probably not downloaded)') + '.';
  if (typeof showErrorToast === 'function') showErrorToast(msg);
}

// ── Live preview panel (opt-in via stepDef.live_preview) ────────────────────
// Builds the side panel UI and returns (via callback) the debounced function
// that re-runs the flow's own ComfyUI workflow against the current adv_values
// and paints the result. Kept separate from the main field-rendering code so
// it stays easy to read/maintain on its own.
function _buildLivePreviewPanel(stepDef, parentEl, onReady) {
  var BG_OPTIONS = [
    { id: 'checkers', label: 'Checkers' },
    { id: 'magenta',  label: 'Magenta' },
    { id: 'green',    label: 'Green' },
    { id: 'black',    label: 'Black' },
    { id: 'white',    label: 'White' },
  ];

  // parentEl is the dedicated #ncf-live-preview-aside column itself —
  // build straight into it, no extra wrapper div needed.
  var panel = parentEl;

  var title = document.createElement('p');
  title.className = 'nsc-param-title';
  title.textContent = 'Live Preview';
  panel.appendChild(title);

  var bgRow = document.createElement('div');
  bgRow.className = 'nsc-lp-bg-row';
  panel.appendChild(bgRow);

  var stage = document.createElement('div');
  stage.className = 'nsc-lp-stage nsc-lp-bg--checkers';
  panel.appendChild(stage);

  BG_OPTIONS.forEach(function (opt, i) {
    var swatch = document.createElement('button');
    swatch.type = 'button';
    swatch.className = 'nsc-lp-swatch nsc-lp-swatch--' + opt.id + (i === 0 ? ' is-active' : '');
    swatch.title = opt.label;
    swatch.setAttribute('aria-label', opt.label);
    swatch.addEventListener('click', function () {
      bgRow.querySelectorAll('.nsc-lp-swatch').forEach(function (s) { s.classList.remove('is-active'); });
      swatch.classList.add('is-active');
      stage.className = 'nsc-lp-stage nsc-lp-bg--' + opt.id;
    });
    bgRow.appendChild(swatch);
  });

  var imgWrap = document.createElement('div');
  imgWrap.className = 'nsc-lp-img-wrap';
  stage.appendChild(imgWrap);

  var img = document.createElement('img');
  img.className = 'nsc-lp-img';
  img.alt = 'Live preview';
  img.style.display = 'none';
  imgWrap.appendChild(img);

  var placeholder = document.createElement('p');
  placeholder.className = 'nsc-lp-placeholder';
  placeholder.textContent = 'Pick a source image to see a live preview';
  imgWrap.appendChild(placeholder);

  var spinner = document.createElement('div');
  spinner.className = 'nsc-lp-spinner';
  spinner.hidden = true;
  imgWrap.appendChild(spinner);

  // Shown when a ComfyUI node has been "executing" for a while with no
  // progress/executed event following — usually means it's blocked on a
  // first-time model download (HF/civitai fetch) rather than actually
  // computing. We can't read ComfyUI's console, so this is a heuristic, not
  // a real download progress bar — see waitForImageLocal's onNote param.
  var downloadNote = document.createElement('p');
  downloadNote.className = 'nsc-lp-download-note';
  downloadNote.hidden = true;
  imgWrap.appendChild(downloadNote);

  var errorEl = document.createElement('p');
  errorEl.className = 'nsc-lp-error';
  errorEl.hidden = true;
  imgWrap.appendChild(errorEl);

  // ── Navigator (minimap) ────────────────────────────────────────────────────
  // Since the main preview shows the image at native 100% resolution (scroll,
  // no downscaling), a small thumbnail with a draggable viewport rectangle
  // helps orient — same idea as Photoshop/Figma's navigator panel.
  var naviWrap = document.createElement('div');
  naviWrap.className = 'nsc-lp-navi-wrap';
  naviWrap.hidden = true;
  panel.appendChild(naviWrap);

  var naviImg = document.createElement('img');
  naviImg.className = 'nsc-lp-navi-img';
  naviImg.alt = '';
  naviWrap.appendChild(naviImg);

  var naviRect = document.createElement('div');
  naviRect.className = 'nsc-lp-navi-rect';
  naviWrap.appendChild(naviRect);

  var hint = document.createElement('p');
  hint.className = 'nsc-lp-hint';
  hint.textContent = 'Scroll to inspect at 100% · drag the navigator to pan';
  panel.appendChild(hint);

  var NAVI_MAX = 180;
  function _naviSize() {
    var nw = img.naturalWidth || 1, nh = img.naturalHeight || 1;
    var dispW, dispH;
    if (nh > nw) { dispH = NAVI_MAX; dispW = Math.max(1, Math.round(NAVI_MAX * nw / nh)); }
    else         { dispW = NAVI_MAX; dispH = Math.max(1, Math.round(NAVI_MAX * nh / nw)); }
    naviWrap.style.width  = dispW + 'px';
    naviWrap.style.height = dispH + 'px';
    return { dispW: dispW, dispH: dispH };
  }
  function _refreshNaviRect() {
    if (!img.naturalWidth || img.style.display === 'none') { naviWrap.hidden = true; return; }
    var nw = img.naturalWidth, nh = img.naturalHeight;
    var visW = Math.min(1, imgWrap.clientWidth  / nw);
    var visH = Math.min(1, imgWrap.clientHeight / nh);
    // The whole image already fits inside the preview stage — there's
    // nothing to pan, so the "viewport" rectangle would always cover 100%
    // of the thumbnail. That reads as a rectangle stuck in place rather than
    // useful info, so just hide the navigator instead of showing it.
    if (visW >= 1 && visH >= 1) { naviWrap.hidden = true; return; }
    naviWrap.hidden = false;
    var dims = _naviSize();
    naviRect.style.width  = Math.max(4, visW * dims.dispW) + 'px';
    naviRect.style.height = Math.max(4, visH * dims.dispH) + 'px';
    naviRect.style.left = (imgWrap.scrollLeft / nw) * dims.dispW + 'px';
    naviRect.style.top  = (imgWrap.scrollTop  / nh) * dims.dispH + 'px';
  }
  function _naviSeek(e) {
    var nw = img.naturalWidth, nh = img.naturalHeight;
    if (!nw || !nh) return;
    var rect = naviWrap.getBoundingClientRect();
    var fracX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    var fracY = Math.max(0, Math.min(1, (e.clientY - rect.top)  / rect.height));
    imgWrap.scrollLeft = Math.max(0, Math.min(fracX * nw - imgWrap.clientWidth  / 2, nw - imgWrap.clientWidth));
    imgWrap.scrollTop  = Math.max(0, Math.min(fracY * nh - imgWrap.clientHeight / 2, nh - imgWrap.clientHeight));
    _refreshNaviRect();
  }
  var _naviDragging = false;
  naviWrap.addEventListener('mousedown', function (e) { _naviDragging = true; _naviSeek(e); });
  document.addEventListener('mousemove', function (e) { if (_naviDragging) _naviSeek(e); });
  document.addEventListener('mouseup', function () { _naviDragging = false; });
  imgWrap.addEventListener('scroll', _refreshNaviRect);

  // ── State helpers ─────────────────────────────────────────────────────────
  function _setState(state, msg) {
    placeholder.style.display = state === 'empty' ? '' : 'none';
    spinner.hidden = state !== 'loading';
    errorEl.hidden = state !== 'error';
    if (state === 'error') errorEl.textContent = msg || 'Preview failed';
    if (state !== 'loading') downloadNote.hidden = true;
    if (state !== 'ready') { img.style.display = 'none'; naviWrap.hidden = true; }
  }
  // Keep the current scroll position across preview updates — the user may
  // be inspecting a specific edge/corner and a re-render shouldn't jump them
  // back to the top-left. Must be captured BEFORE _setState('loading') hides
  // the image — hiding it collapses the scrollable area and zeroes the
  // scroll position, so reading it any later would always see 0,0.
  function _setImage(url, keepLeft, keepTop) {
    img.onload = function () {
      img.style.display = 'block';
      _setState('ready');
      imgWrap.scrollLeft = keepLeft || 0;
      imgWrap.scrollTop  = keepTop || 0;
      naviImg.src = url;
      _refreshNaviRect();
    };
    img.src = url;
  }
  _setState('empty');

  // ── Debounced live run ──────────────────────────────────────────────────
  var _debounceTimer = null;
  var _runToken = 0;
  function schedule() {
    if (_debounceTimer) clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(runOnce, 600);
  }
  async function runOnce() {
    var keepLeft = imgWrap.scrollLeft;
    var keepTop  = imgWrap.scrollTop;

    var imageDataUrl   = getVal('image', 'image_data_url') || '';
    var advancedValues = getVal(stepDef.id, 'adv_values') || {};

    // ── Local (non-ComfyUI) addons — e.g. Chroma Key, Pixel Matcher — just
    // POST straight to their own /process endpoint and get a dataUrl back,
    // no ComfyUI prepare/submit/poll round-trip needed. ────────────────────
    if (stepDef.live_preview_endpoint) {
      if (!imageDataUrl) { _setState('empty'); return; }
      var localToken = ++_runToken;
      _setState('loading');
      try {
        var localRes = await fetch(stepDef.live_preview_endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.assign({ imageDataUrl: imageDataUrl, save: false }, advancedValues)),
        });
        var localData = await localRes.json();
        if (localToken !== _runToken) return; // superseded by a newer edit
        if (!localRes.ok || localData.error) throw new Error(localData.error || 'Preview failed');
        var localImgUrl = localData.dataUrl || localData.imageUrl;
        if (!localImgUrl) throw new Error('No preview image returned');
        _setImage(localImgUrl, keepLeft, keepTop);
      } catch (err) {
        if (localToken === _runToken) _setState('error', err.message || 'Preview failed');
      }
      return;
    }

    var workflowFile   = getVal(stepDef.id, 'workflow_file') || stepDef.workflow_file || '';
    if (!imageDataUrl || !workflowFile) { _setState('empty'); return; }

    var myToken = ++_runToken;
    _setState('loading');
    try {
      var prepRes = await fetch('/api/models/refine/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflowFile:   workflowFile,
          imageDataUrl:   imageDataUrl,
          advancedValues: advancedValues,
          imageNodeId:    stepDef.image_node || undefined,
        }),
      });
      var prepData = await prepRes.json();
      if (myToken !== _runToken) return; // superseded by a newer edit
      if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');

      var submitRes = await fetch(prepData.comfyApiUrl + '/prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prepData.workflow, client_id: prepData.clientId }),
      });
      var submitData = await submitRes.json();
      if (myToken !== _runToken) return;
      if (!submitRes.ok || submitData.error) throw new Error('Queue rejected');
      if (!submitData.prompt_id) throw new Error('ComfyUI did not return a prompt_id');

      var imgUrl = await waitForImageLocal(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, null, function (note) {
        if (myToken !== _runToken) return;
        downloadNote.textContent = note || '';
        downloadNote.hidden = !note;
      });
      if (myToken !== _runToken) return; // a newer edit already superseded this result
      if (!imgUrl) throw new Error('No preview image returned');
      imgUrl = await _maybeDefringeImage(imgUrl, advancedValues);
      if (myToken !== _runToken) return;
      _setImage(imgUrl, keepLeft, keepTop);
    } catch (err) {
      if (myToken === _runToken) _setState('error', err.message || 'Preview failed');
    } finally {
      downloadNote.hidden = true;
    }
  }

  onReady(schedule);
}

// ── param_group ────────────────────────────────────────────────────────────
function renderParamGroup(stepDef, el, stepNum) {
  var _sp = loadSavedParams() || {};

  // Guided section
  var guidedEl = document.createElement('div');
  guidedEl.className = 'nsc-params-guided';
  el.appendChild(guidedEl);

  // Aspect ratio — same "icon button → modal" pattern as the Prompt step's
  // history button: the full 15-ratio list would be too much to show inline,
  // so only the current value shows here and picking a new one opens a list.
  //
  // Sits above Resolution now (reversed from the original order, which put
  // Resolution first on the theory of "pick the quality tier, then fine-tune
  // the ratio") — creatively you decide the *shape* first and the pixel
  // count second, not the other way round.
  var aspectWrap = document.createElement('div');
  aspectWrap.className = 'nsc-param-block nss-aspect-guided';
  aspectWrap.innerHTML =
    '<p class="nsc-param-title nsc-param-title--flex">Aspect ratio <span class="nsc-param-value" id="ncf-aspect-label">1:1</span>' +
      '<button type="button" class="nsc-history-btn nsc-options-trigger" id="ncf-aspect-picker-btn" aria-label="Choose aspect ratio">' +
        '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1.5" y="1.5" width="15" height="15" rx="2"/></svg>' +
      '</button>' +
    '</p>';
  guidedEl.appendChild(aspectWrap);

  var aspectLabelEl  = aspectWrap.querySelector('#ncf-aspect-label');
  var aspectPickerBtn = aspectWrap.querySelector('#ncf-aspect-picker-btn');

  // Resolution — same "icon button → panel" pattern as Aspect ratio above it.
  // Picking a tier here only changes which of the current ratio's
  // sd/md/hd/uhd pair getDims() returns — the actual width/height always
  // come from ASPECT_PRESETS[selectedAspectIdx][tier].
  var resTierWrap = document.createElement('div');
  resTierWrap.className = 'nsc-param-block';
  resTierWrap.innerHTML =
    '<p class="nsc-param-title nsc-param-title--flex">Resolution <span class="nsc-param-value" id="ncf-res-tier-label">MD</span>' +
      '<button type="button" class="nsc-history-btn nsc-options-trigger" id="ncf-res-tier-picker-btn" aria-label="Choose resolution">' +
        '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1.5" y="6" width="7.5" height="7.5" rx="1.3"/><rect x="7.5" y="1.5" width="9" height="9" rx="1.3"/></svg>' +
      '</button>' +
    '</p>';
  guidedEl.appendChild(resTierWrap);
  var resTierLabelEl  = resTierWrap.querySelector('#ncf-res-tier-label');
  var resTierPickerBtn = resTierWrap.querySelector('#ncf-res-tier-picker-btn');
  function updateResLabels() {
    var a = ASPECT_PRESETS[selectedAspectIdx];
    var dRes = a && a[selectedResolution];
    if (resTierLabelEl) {
      resTierLabelEl.textContent = customResDims
        ? (customResDims.w + '×' + customResDims.h)
        : (selectedResolution || 'md').toUpperCase() + (dRes ? ' · ' + dRes.w + '×' + dRes.h : '');
    }
    // Keep the custom width/height fields mirroring the active preset until
    // the user actually overrides them by hand.
    if (!customResDims) {
      var cw = guidedEl.querySelector('#ncf-custom-res-w');
      var ch = guidedEl.querySelector('#ncf-custom-res-h');
      if (cw) cw.value = dRes ? dRes.w : '';
      if (ch) ch.value = dRes ? dRes.h : '';
    }
  }
  // Which preset, if any, has the ratio of these dimensions. The key carries
  // it exactly ('r16x9'), so no guessing from the stored pixel pairs — those
  // are rounded to multiples of 8 and drift a little from the true ratio.
  function aspectIdxForDims(w, h) {
    if (!(w > 0 && h > 0)) return -1;
    var target = w / h;
    for (var i = 0; i < ASPECT_PRESETS.length; i++) {
      var m = /^r(\d+)x(\d+)$/.exec(ASPECT_PRESETS[i].key || '');
      if (!m) continue;
      if (Math.abs(target - (+m[1] / +m[2])) < 0.01) return i;
    }
    return -1;
  }

  // Typing a size is also choosing a ratio. Without this the Aspect ratio line
  // kept saying 1:1 next to a 1920x1080 resolution.
  function syncAspectToCustomDims() {
    if (!customResDims) return;
    var idx = aspectIdxForDims(customResDims.w, customResDims.h);
    if (idx >= 0) {
      selectedAspectIdx = idx;
      if (aspectLabelEl) aspectLabelEl.textContent = ASPECT_PRESETS[idx].label;
    } else if (aspectLabelEl) {
      aspectLabelEl.textContent = 'Custom';
    }
  }

  function setAspect(idx) {
    selectedAspectIdx = idx;
    if (aspectLabelEl) aspectLabelEl.textContent = ASPECT_PRESETS[idx].label;
    // A typed size sets the scale you want to work at, so changing the ratio
    // reframes it instead of throwing it away: same pixel count, new shape.
    // Dropping back to the preset here meant 1920x1080 -> 2:3 handed back the
    // MD pair, 832x1216, a third of the pixels nobody asked to lose. Pick a
    // resolution tier to go back to the presets.
    if (customResDims && customResDims.w > 0 && customResDims.h > 0) {
      var _m = /^r(\d+)x(\d+)$/.exec(ASPECT_PRESETS[idx].key || '');
      if (_m) {
        var _area = customResDims.w * customResDims.h;
        var _ratio = +_m[1] / +_m[2];
        // Multiples of 8, like every pair in ASPECT_PRESETS.
        var _snap = function (v) { return Math.max(64, Math.round(v / 8) * 8); };
        customResDims = {
          w: _snap(Math.sqrt(_area * _ratio)),
          h: _snap(Math.sqrt(_area / _ratio)),
        };
        var _cw = guidedEl.querySelector('#ncf-custom-res-w');
        var _ch = guidedEl.querySelector('#ncf-custom-res-h');
        if (_cw) _cw.value = customResDims.w;
        if (_ch) _ch.value = customResDims.h;
      } else {
        customResDims = null;
      }
    }
    updateResLabels();
    saveParams();
  }
  _ncfSetAspectFn = setAspect;
  aspectPickerBtn.addEventListener('click', function () {
    openAspectRatioPanel(selectedAspectIdx, setAspect);
  });
  var _defaultAspectIdx = ASPECT_PRESETS.findIndex(function (p) { return p.key === 'r1x1'; });
  setAspect(_sp.aspectIdx != null ? +_sp.aspectIdx : (_defaultAspectIdx >= 0 ? _defaultAspectIdx : 0));

  function setResolutionTier(tier) {
    selectedResolution = tier;
    customResDims = null;
    updateResLabels();
    saveParams();
  }
  resTierPickerBtn.addEventListener('click', function () {
    openResolutionPanel(selectedAspectIdx, selectedResolution, setResolutionTier, {
      customDims: customResDims,
      onCustomChange: function (dims) {
        customResDims = dims;
        syncAspectToCustomDims();
        updateResLabels();
        saveParams();
      },
    });
  });
  setResolutionTier(_sp.resolution || 'md');

  // Custom resolution (Custom mode only) — type your own width/height instead
  // of picking SD/MD/HD.
  var customResRow = document.createElement('div');
  customResRow.className = 'nsc-field-row ncf-custom-res-row';
  customResRow.style.marginTop = '0.5rem';
  customResRow.innerHTML =
    '<input class="nsc-input nsc-input--adv" type="number" min="64" step="8" placeholder="Width" id="ncf-custom-res-w">' +
    '<span style="color:var(--muted);flex-shrink:0;">×</span>' +
    '<input class="nsc-input nsc-input--adv" type="number" min="64" step="8" placeholder="Height" id="ncf-custom-res-h">';
  guidedEl.appendChild(customResRow);
  var customWInput = customResRow.querySelector('#ncf-custom-res-w');
  var customHInput = customResRow.querySelector('#ncf-custom-res-h');
  function applyCustomRes() {
    var w = parseInt(customWInput.value, 10);
    var h = parseInt(customHInput.value, 10);
    if (w > 0 && h > 0) {
      customResDims = { w: w, h: h };
    } else {
      customResDims = null;
    }
    syncAspectToCustomDims();
    updateResLabels();
    saveParams();
  }
  customWInput.addEventListener('input', applyCustomRes);
  customHInput.addEventListener('input', applyCustomRes);
  if (_sp.customResDims && _sp.customResDims.w && _sp.customResDims.h) {
    customWInput.value = _sp.customResDims.w;
    customHInput.value = _sp.customResDims.h;
    customResDims = _sp.customResDims;
    syncAspectToCustomDims();
    updateResLabels();
  }
  function syncCustomResVisibility() {
    customResRow.style.display = getMode() === 'advanced' ? 'flex' : 'none';
  }
  syncCustomResVisibility();
  document.addEventListener('ncf-mode-change', syncCustomResVisibility);
  updateResLabels();

  // "Advanced" — same title + round icon-button pattern as Aspect ratio /
  // Your prompt (.nsc-history-btn), opening Quantization/Quality/Similarity
  // in the shared options panel (flow-options-panel.js) instead of expanding
  // inline.
  var advToggle = document.createElement('p');
  advToggle.className = 'nsc-param-title nsc-param-title--flex';
  advToggle.textContent = tF('Advanced');
  guidedEl.appendChild(advToggle);

  var advPickerBtn = document.createElement('button');
  advPickerBtn.type = 'button';
  advPickerBtn.className = 'nsc-history-btn nsc-options-trigger';
  advPickerBtn.setAttribute('aria-label', 'Advanced options');
  advPickerBtn.innerHTML =
    '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M3 4.5h10M3 8h10M3 11.5h10"/><circle cx="6" cy="4.5" r="1.3" fill="currentColor" stroke="none"/>' +
      '<circle cx="10" cy="8" r="1.3" fill="currentColor" stroke="none"/><circle cx="6.5" cy="11.5" r="1.3" fill="currentColor" stroke="none"/>' +
    '</svg>';
  advToggle.appendChild(advPickerBtn);

  advPickerBtn.addEventListener('click', function () {
    openOptionsPanel(tF('Advanced'), function (body) {
      body.appendChild(quantBlock);
      body.appendChild(qualBlock);
      body.appendChild(simBlock);
      body.appendChild(negBlock);
      body.appendChild(sgBlock);
      body.appendChild(loraBlock);
    });
  });

  // Quantization list (INT4/INT8/FP8 diffusion-model variants) — only shown
  // when the selected workflow's config declares a "quantization" block.
  // Kept detached until the panel opens (see advToggle above).
  var quantBlock = document.createElement('div');
  quantBlock.className = 'nsc-param-block';
  quantBlock.style.display = 'none';
  quantBlock.innerHTML = '<p class="nsc-param-title">Quantization</p>';
  var quantListEl = document.createElement('div');
  quantListEl.className = 'nsc-quality-list';
  quantListEl.setAttribute('role', 'radiogroup');
  quantBlock.appendChild(quantListEl);

  // Quality list
  var qualBlock = document.createElement('div');
  qualBlock.className = 'nsc-param-block';
  qualBlock.innerHTML = '<p class="nsc-param-title">Quality</p>';
  var qualListEl = document.createElement('div');
  qualListEl.className = 'nsc-quality-list';
  qualListEl.setAttribute('role', 'radiogroup');
  qualBlock.appendChild(qualListEl);

  // Similarity toggle
  var simBlock = document.createElement('div');
  simBlock.className = 'nsc-param-block';
  simBlock.style.marginTop = '1rem';
  var simToggle = document.createElement('button');
  simToggle.className = 'create-basic-similarity-toggle';
  simToggle.id = 'ncf-similarity-toggle';
  simToggle.type = 'button';
  simToggle.setAttribute('aria-pressed', 'false');
  simToggle.classList.add('off');
  simToggle.innerHTML =
    '<span class="create-basic-similarity-label">Visual similarity</span>' +
    '<div class="create-basic-switch"><div class="create-basic-switch-thumb"></div></div>';
  simBlock.appendChild(simToggle);

  simToggle.addEventListener('click', function () {
    var wasOff = simToggle.classList.toggle('off');
    similarityOn = !wasOff;
    simToggle.setAttribute('aria-pressed', similarityOn ? 'true' : 'false');
    if (similarityOn) {
      if (guidedFixedSeed < 0) guidedFixedSeed = Math.floor(Math.random() * 0x7FFFFFFF);
    } else {
      guidedFixedSeed = -1;
    }
    saveParams();
  });
  if (_sp.similarity) simToggle.click();

  // Negative prompt — applied server-side to whichever CLIP Text Encode node
  // the workflow analysis detected as the negative branch (basicValues.negative).
  // A saved value from a previous run of this step always wins; otherwise seed
  // it from the currently-selected imported workflow's own detected default
  // (it was never read here before — the field just stayed empty on first load
  // even though the import analysis had already found the text).
  if (_sp.negativePrompt) {
    selectedNegativePrompt = _sp.negativePrompt;
  } else if (selectedImportRecord) {
    selectedNegativePrompt = (selectedImportRecord.basicValues || {}).negative || '';
  }
  var negBlock = document.createElement('div');
  negBlock.className = 'nsc-param-block';
  negBlock.style.marginTop = '1rem';
  negBlock.innerHTML = '<p class="nsc-param-title">Negative prompt</p>';
  var negTa = document.createElement('textarea');
  negTa.className = 'nsc-textarea';
  negTa.id = 'ncf-negative-prompt';
  negTa.rows = 3;
  negTa.placeholder = 'ugly, blurry, low quality…';
  negTa.value = selectedNegativePrompt || '';
  negTa.addEventListener('input', function () {
    selectedNegativePrompt = negTa.value;
    saveParams();
  });
  negBlock.appendChild(negTa);

  // Optional parts — one checkbox per Subgraph the import detected as safely
  // toggleable (see app/services/subgraph_toggles.py: a Subgraph whose single
  // external output can be traced back to exactly one external input of the
  // same type gets rewired around when unchecked, e.g. skip an "upscale
  // detail pass" and feed the base latent straight to VAE Decode instead).
  // Groups (plain visual boxes) never show up here — they leave no trace at
  // all in the API-format workflow we import, only Subgraphs do.
  var sgBlock = document.createElement('div');
  sgBlock.className = 'nsc-param-block';
  sgBlock.style.marginTop = '1rem';
  var sgListEl = document.createElement('div');
  sgBlock.appendChild(sgListEl);

  function buildOptionalSubgraphsList(record, containerEl) {
    if (!containerEl) return;
    var items = Array.isArray(record && record.annotation && record.annotation.optionalSubgraphs)
      ? record.annotation.optionalSubgraphs : [];
    containerEl.innerHTML = '';
    if (!items.length) { sgBlock.style.display = 'none'; return; }
    sgBlock.style.display = '';
    containerEl.insertAdjacentHTML('afterbegin', '<p class="nsc-param-title">Optional parts</p>');

    var savedDisabled = Array.isArray(_sp.disabledSubgraphs) ? _sp.disabledSubgraphs : null;
    selectedDisabledSubgraphs = items
      .filter(function (it) {
        return savedDisabled ? savedDisabled.indexOf(it.id) !== -1 : !it.defaultEnabled;
      })
      .map(function (it) { return it.id; });

    items.forEach(function (it) {
      var row = document.createElement('label');
      row.className = 'nsc-checkbox-row';
      row.style.cssText = 'display:flex;align-items:flex-start;gap:0.5rem;margin-top:0.5rem;cursor:pointer;';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = selectedDisabledSubgraphs.indexOf(it.id) === -1;
      var textWrap = document.createElement('span');
      var titleEl = document.createElement('span');
      titleEl.textContent = it.label || ('Optional part ' + it.id);
      titleEl.style.display = 'block';
      textWrap.appendChild(titleEl);
      if (it.contains) {
        var hintEl = document.createElement('small');
        hintEl.className = 'nsc-step-hint';
        hintEl.style.display = 'block';
        hintEl.textContent = it.contains;
        textWrap.appendChild(hintEl);
      }
      row.appendChild(cb);
      row.appendChild(textWrap);
      cb.addEventListener('change', function () {
        var idx = selectedDisabledSubgraphs.indexOf(it.id);
        if (cb.checked && idx !== -1) selectedDisabledSubgraphs.splice(idx, 1);
        else if (!cb.checked && idx === -1) selectedDisabledSubgraphs.push(it.id);
        saveParams();
      });
      containerEl.appendChild(row);
    });
  }
  buildOptionalSubgraphsList(selectedImportRecord, sgListEl);

  // LoRAs — lets a Balanced/Guided user adjust LoRA name + strength without
  // switching to full Custom mode. Reuses the same /param-options endpoint
  // and openLoraNamePickerPanel picker Custom mode's per-workflow tab already
  // uses (flow-enum-modal.js) — this is just a second caller of both, grouped
  // by the shared node id so each LoRA node gets one picker button plus a
  // stepper per strength_model/strength_clip param that node exposes.
  var loraBlock = document.createElement('div');
  loraBlock.className = 'nsc-param-block ncf-lora-fields-block';
  loraBlock.style.marginTop = '1rem';
  var loraListEl = document.createElement('div');
  loraBlock.appendChild(loraListEl);

  function buildLoraFieldsList(record, containerEl) {
    if (!containerEl) return;
    containerEl.innerHTML = '';
    var params = Array.isArray(record && record.analysis && record.analysis.advancedParameters)
      ? record.analysis.advancedParameters : [];
    var nodeIds = [];
    var byNode = {};
    params.forEach(function (p) {
      var key = String(p.key || '');
      var dot = key.indexOf('.');
      if (dot === -1) return;
      var nodeId = key.slice(0, dot);
      var inputKey = key.slice(dot + 1);
      if (!byNode[nodeId]) { byNode[nodeId] = {}; nodeIds.push(nodeId); }
      byNode[nodeId][inputKey] = p;
    });
    var loraNodeIds = nodeIds.filter(function (id) { return byNode[id].lora_name; });
    if (!loraNodeIds.length) { loraBlock.style.display = 'none'; return; }
    loraBlock.style.display = '';
    containerEl.insertAdjacentHTML('afterbegin', '<p class="nsc-param-title">LoRAs</p>');

    if (!record || !record.id) return;
    fetch('/api/models/imports/' + encodeURIComponent(record.id) + '/param-options')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var optMap = (data && data.options) || {};
        loraNodeIds.forEach(function (nodeId) {
          var group = byNode[nodeId];
          var nameParam = group.lora_name;
          var nameKey = nameParam.key;
          var opts = optMap[nameKey] || [];

          var row = document.createElement('div');
          row.className = 'ncf-wf-lora-row';
          var pickBtn = document.createElement('button');
          pickBtn.type = 'button';
          pickBtn.className = 'nsc-history-btn ncf-wf-lora-btn nsc-options-trigger';

          function _currentName() {
            return Object.prototype.hasOwnProperty.call(selectedLoraValues, nameKey)
              ? selectedLoraValues[nameKey] : nameParam.value;
          }
          function _syncLabel() {
            var v = _currentName();
            pickBtn.innerHTML = '<span>' + escHtml(v === '__bypass__' ? 'None (bypass)' : (v || 'Choose a LoRA')) + '</span>';
          }
          pickBtn.addEventListener('click', function () {
            if (!opts.length) return;
            openLoraNamePickerPanel(nameParam.label || 'LoRA', opts, _currentName(), function (chosen) {
              if (chosen === nameParam.value) delete selectedLoraValues[nameKey];
              else selectedLoraValues[nameKey] = chosen;
              _syncLabel();
              saveParams();
            });
          });
          _syncLabel();
          row.appendChild(pickBtn);
          containerEl.appendChild(row);

          ['strength_model', 'strength_clip'].forEach(function (inputKey) {
            var sParam = group[inputKey];
            if (!sParam) return;
            var sKey = sParam.key;
            var sRow = document.createElement('div');
            sRow.className = 'nsc-field-row nsc-adv-row';
            var lbl = document.createElement('label');
            lbl.className = 'nsc-field-label';
            lbl.textContent = sParam.label || inputKey;
            var inp = document.createElement('input');
            inp.className = 'nsc-input nsc-input--adv';
            inp.type = 'number';
            inp.step = '0.05';
            var initVal = Object.prototype.hasOwnProperty.call(selectedLoraValues, sKey)
              ? selectedLoraValues[sKey] : sParam.value;
            inp.value = initVal !== undefined ? initVal : '';
            inp.addEventListener('input', function () {
              var v = Number(inp.value);
              if (v === sParam.value) delete selectedLoraValues[sKey]; else selectedLoraValues[sKey] = v;
              saveParams();
            });
            sRow.appendChild(lbl);
            _applyNcfNumericStepper(inp, sRow);
            containerEl.appendChild(sRow);
          });
        });
      })
      .catch(function () {});
  }
  buildLoraFieldsList(selectedImportRecord, loraListEl);

  // options_groups — generic button-group selectors defined in the flow JSON
  // Each entry: { id, label, options: ["val1","val2",...], default, set_aspect_ratio: {...} }
  var optGroups = Array.isArray(stepDef.options_groups) ? stepDef.options_groups : [];
  optGroups.forEach(function (grp) {
    if (!grp.id || !Array.isArray(grp.options) || !grp.options.length) return;
    var defVal = _sp['optgrp_' + grp.id] || grp.default || grp.options[0];
    _optGroupValues[grp.id] = defVal;

    var grpBlock = document.createElement('div');
    grpBlock.className = 'nsc-param-block';
    grpBlock.innerHTML = '<p class="nsc-param-title">' + escHtml(grp.label || grp.id) + '</p>';

    var btnsEl = document.createElement('div');
    btnsEl.className = 'nsc-res-btns';
    btnsEl.setAttribute('role', 'group');

    grp.options.forEach(function (opt) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'nsc-res-btn' + (opt === defVal ? ' is-active' : '');
      btn.dataset.val = opt;
      btn.setAttribute('aria-pressed', opt === defVal ? 'true' : 'false');
      var lbl = document.createElement('span');
      lbl.className = 'nsc-res-label';
      lbl.textContent = opt.charAt(0).toUpperCase() + opt.slice(1).replace(/_/g, ' ');
      btn.appendChild(lbl);

      btn.addEventListener('click', function () {
        _optGroupValues[grp.id] = opt;
        btnsEl.querySelectorAll('.nsc-res-btn').forEach(function (b) {
          var active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        // Save to params
        var saved = loadSavedParams() || {};
        saved['optgrp_' + grp.id] = opt;
        try { localStorage.setItem(PARAMS_KEY, JSON.stringify(saved)); } catch (_) {}
        // set_aspect_ratio hook
        if (grp.set_aspect_ratio && grp.set_aspect_ratio[opt]) {
          var arLabel = grp.set_aspect_ratio[opt];
          var arIdx = ASPECT_PRESETS.findIndex(function (p) { return p.label === arLabel; });
          if (arIdx >= 0) {
            setAspect(arIdx);
          }
        }
      });
      btnsEl.appendChild(btn);
    });

    grpBlock.appendChild(btnsEl);
    guidedEl.appendChild(grpBlock);

    // Apply default aspect ratio on load
    if (grp.set_aspect_ratio && grp.set_aspect_ratio[defVal]) {
      setTimeout(function () {
        var arLabel = grp.set_aspect_ratio[defVal];
        var arIdx = ASPECT_PRESETS.findIndex(function (p) { return p.label === arLabel; });
        if (arIdx >= 0 && selectedAspectIdx !== arIdx) {
          setAspect(arIdx);
        }
      }, 50);
    }
  });

  // Quality / Similarity are derived from a single workflow's analysis (sampler,
  // cfg, steps…) — meaningless once Custom mode lets you queue several
  // workflows at once, where each gets its own override in the per-model
  // aside (flow-workflow-params-aside.js). Aspect ratio and Resolution stay
  // visible in both modes since they control output width/height regardless
  // of how many workflows are selected.
  function syncStepVisibility() {
    var hide = getMode() === 'advanced';
    advToggle.style.display = hide ? 'none' : '';
    if (hide) closeOptionsPanel();
    // Quantization only shows up (inside the panel) for workflows that
    // actually declare quantization variants.
    quantBlock.style.display = selectedQuantizationValues ? '' : 'none';
  }
  syncStepVisibility();
  document.addEventListener('ncf-mode-change', syncStepVisibility);

  // Workflow loaded → rebuild quality + quantization lists, and seed the
  // negative prompt from this workflow's own detected default — but only
  // when the field is still empty, so switching workflows never clobbers
  // something the user already typed.
  document.addEventListener('ncf-workflow-loaded', function (e) {
    buildQuantizationList(e.detail, quantListEl);
    buildQualityList(e.detail, qualListEl);
    buildOptionalSubgraphsList(e.detail, sgListEl);
    buildLoraFieldsList(e.detail, loraListEl);
    syncStepVisibility();
    if (!negTa.value.trim()) {
      var _wfNegative = ((e.detail && e.detail.basicValues) || {}).negative || '';
      if (_wfNegative) {
        selectedNegativePrompt = _wfNegative;
        negTa.value = _wfNegative;
      }
    }
  });
  if (selectedImportRecord) {
    buildQuantizationList(selectedImportRecord, quantListEl);
    buildQualityList(selectedImportRecord, qualListEl);
    buildLoraFieldsList(selectedImportRecord, loraListEl);
    syncStepVisibility();
  }
}

// ── style_picker panel ───────────────────────────────────────────────────────
// Opens the shared lateral options panel (flow-options-panel.js), extra-wide,
// with a search box + category tree + image card grid of the user's own
// saved Styles (Build > Styles, GET /api/styles) — same visual language as
// Build's own Styles browser (library.js's styleCardHtml/deriveStyleCategoryTree)
// so picking a style here is as recognizable as picking one there, not a
// bare text list. Picking one hands it to onPick(style); the style_picker
// field itself decides how to turn it into text (see the render branch
// above, which uses prefix+suffix only, deliberately skipping .prompt's
// example-scene text).
function _stylePickerCategoryTree(items) {
  var flatSet = {};
  var groupMap = {};
  items.forEach(function (it) {
    var c = (it.category || '').trim();
    if (!c) return;
    var slash = c.indexOf('/');
    if (slash === -1) {
      flatSet[c] = true;
    } else {
      var group = c.slice(0, slash);
      var sub = c.slice(slash + 1);
      if (!groupMap[group]) groupMap[group] = {};
      groupMap[group][sub] = c;
    }
  });
  var groupNames = Object.keys(groupMap).sort(function (a, b) { return a.localeCompare(b); });
  var groups = groupNames.map(function (g) {
    var subNames = Object.keys(groupMap[g]).sort(function (a, b) { return a.localeCompare(b); });
    return { name: g, subs: subNames.map(function (s) { return { label: s, full: groupMap[g][s] }; }) };
  });
  var flatNames = Object.keys(flatSet).sort(function (a, b) { return a.localeCompare(b); });
  return { flatNames: flatNames, groups: groups };
}

function _stylePickerCardHtml(s) {
  var img = s.has_image ? s.image_url : '';
  var snippet = [s.prefix, s.suffix]
    .map(function (v) { return String(v || '').trim(); })
    .filter(Boolean)
    .join(', ');
  var imgBlock = img
    ? '<img src="' + escHtml(img) + '" alt="" onerror="this.closest(\'.lib-style-card-img-wrap\').classList.add(\'lib-style-card-img-wrap--fallback\')">'
    : '';
  return (
    '<div class="lib-style-card-outer">' +
      '<button type="button" class="rp-card lib-style-card ncf-style-picker-card" data-style-id="' + escHtml(String(s.id)) + '">' +
        '<div class="rp-card-media lib-style-card-img-wrap' + (img ? '' : ' lib-style-card-img-wrap--fallback') + '">' +
          imgBlock +
          '<i data-lucide="palette" class="lib-style-card-fallback-icon" aria-hidden="true"></i>' +
        '</div>' +
        '<div class="rp-card-body">' +
          '<p class="rp-card-name">' + escHtml(s.name || 'Untitled') + '</p>' +
          (s.category ? '<p class="lib-style-card-category">' + escHtml(s.category) + '</p>' : '') +
          (snippet ? '<p class="rp-card-desc">' + escHtml(snippet) + '</p>' : '') +
        '</div>' +
      '</button>' +
    '</div>'
  );
}

function _openStylePickerPanel(onPick) {
  openOptionsPanel('Choose a Style', function (body) {
    body.innerHTML =
      '<div class="ncf-style-picker-search-row">' +
        '<input type="text" class="nsc-input ncf-style-picker-search" placeholder="Search styles…" aria-label="Search styles">' +
      '</div>' +
      '<div class="ncf-style-picker-layout">' +
        '<nav class="ncf-style-picker-tree" aria-label="Style categories"></nav>' +
        '<div class="ncf-style-picker-grid"></div>' +
      '</div>';
    var searchInput = body.querySelector('.ncf-style-picker-search');
    var treeEl = body.querySelector('.ncf-style-picker-tree');
    var gridEl = body.querySelector('.ncf-style-picker-grid');

    var allStyles = [];
    var tree = { flatNames: [], groups: [] };
    var selectedCategory = '';
    var expandedGroups = {};
    var query = '';

    function renderTree() {
      var items = '<button type="button" class="lib-style-cat-tree-item' + (selectedCategory === '' ? ' is-active' : '') + '" data-cat="">All</button>';
      items += tree.flatNames.map(function (name) {
        return '<button type="button" class="lib-style-cat-tree-item' + (selectedCategory === name ? ' is-active' : '') + '" data-cat="' + escHtml(name) + '">' + escHtml(name) + '</button>';
      }).join('');
      items += tree.groups.map(function (g) {
        var expanded = !!expandedGroups[g.name];
        return '<div class="lib-style-cat-group' + (expanded ? ' is-expanded' : '') + '">' +
          '<button type="button" class="lib-style-cat-group-toggle' + (selectedCategory === g.name ? ' is-active' : '') + '" data-cat-group="' + escHtml(g.name) + '">' +
            '<svg class="lib-style-cat-group-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>' +
            '<span>' + escHtml(g.name) + '</span>' +
          '</button>' +
          (expanded ? '<div class="lib-style-cat-group-children">' +
            g.subs.map(function (s) {
              return '<button type="button" class="lib-style-cat-tree-item' + (selectedCategory === s.full ? ' is-active' : '') + '" data-cat="' + escHtml(s.full) + '">' + escHtml(s.label) + '</button>';
            }).join('') +
          '</div>' : '') +
        '</div>';
      }).join('');
      treeEl.innerHTML = items;
    }

    function renderGrid() {
      var q = query.trim().toLowerCase();
      var filtered = allStyles.filter(function (s) {
        if (selectedCategory) {
          var c = (s.category || '').trim();
          if (c !== selectedCategory && c.indexOf(selectedCategory + '/') !== 0) return false;
        }
        if (q) {
          var hay = [s.name, s.category, s.prefix, s.prompt, s.suffix].join(' ').toLowerCase();
          if (hay.indexOf(q) === -1) return false;
        }
        return true;
      });
      if (!filtered.length) {
        gridEl.innerHTML = '<p class="ncf-style-picker-empty muted-note">' +
          (allStyles.length ? 'No styles match.' : 'No styles saved yet — add some in Build &gt; Styles.') +
          '</p>';
        return;
      }
      gridEl.innerHTML = filtered.map(_stylePickerCardHtml).join('');
      if (window.lucide) window.lucide.createIcons();
    }

    treeEl.addEventListener('click', function (e) {
      var groupToggle = e.target.closest('.lib-style-cat-group-toggle');
      if (groupToggle) {
        var g = groupToggle.dataset.catGroup;
        expandedGroups[g] = !expandedGroups[g];
        selectedCategory = g;
        renderTree();
        renderGrid();
        return;
      }
      var item = e.target.closest('.lib-style-cat-tree-item');
      if (!item) return;
      selectedCategory = item.dataset.cat || '';
      renderTree();
      renderGrid();
    });

    searchInput.addEventListener('input', function () {
      query = searchInput.value;
      renderGrid();
    });

    gridEl.addEventListener('click', function (e) {
      var card = e.target.closest('.ncf-style-picker-card');
      if (!card) return;
      var style = allStyles.find(function (x) { return String(x.id) === card.dataset.styleId; });
      if (!style) return;
      onPick(style);
      closeOptionsPanel();
    });

    gridEl.innerHTML = '<p class="ncf-style-picker-empty muted-note">Loading…</p>';
    window.openJourneyApi.getStyles().then(function (data) {
      allStyles = (data && data.styles) || [];
      tree = _stylePickerCategoryTree(allStyles);
      renderTree();
      renderGrid();
    }).catch(function (err) {
      console.error('[StylePicker] Failed to load styles:', err);
      gridEl.innerHTML = '<p class="ncf-style-picker-empty muted-note">Could not load styles.</p>';
    });
  }, { wide: 'xl', flexBody: true });
}

// ── scene_builder ──────────────────────────────────────────────────────────
// A step type that lets the user define a scene and multiple characters,
// each with orientation, reference image and description.
// On "Build Composition" it assembles an Ideogram JSON and feeds it to the
// linked ideogram_composer step via _fillFn.
