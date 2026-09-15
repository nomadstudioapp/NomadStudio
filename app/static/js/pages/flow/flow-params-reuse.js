'use strict';
// Capture / re-apply the parameters that produced a result.
// Powers: (1) params stored in image metadata + session step, (2) the
// "Apply parameters" button on done cards, (3) restore on Session → Open.
//
// All access to flow globals is defensive (typeof guards) so this module is
// safe to load on any flow page and never throws if a global is absent.

// Build a plain, serialisable snapshot of the current generation parameters.
// `extra` adds path-specific fields (prompt, advancedValues, kind, …) and wins
// over the auto-collected values.
function buildParamsSnapshot(extra) {
  var snap = {};
  try {
    if (typeof getMode === 'function') snap.mode = getMode();
    if (typeof selectedAspectIdx     !== 'undefined') snap.aspectIdx    = selectedAspectIdx;
    if (typeof selectedResolution    !== 'undefined') snap.resolution   = selectedResolution;
    if (typeof selectedQualityId     !== 'undefined' && selectedQualityId) snap.qualityId = selectedQualityId;
    if (typeof selectedQualityValues !== 'undefined' && selectedQualityValues) snap.qualityValues = selectedQualityValues;
    if (typeof selectedQuantizationId     !== 'undefined' && selectedQuantizationId) snap.quantizationId = selectedQuantizationId;
    if (typeof selectedQuantizationValues !== 'undefined' && selectedQuantizationValues) snap.quantizationValues = selectedQuantizationValues;
    if (typeof selectedLoraValues !== 'undefined' && selectedLoraValues) snap.loraValues = selectedLoraValues;
    if (typeof selectedSeed          !== 'undefined') snap.seed = selectedSeed;
    // ── Everything below is what "100% reproducible" actually needs ───────
    // Which flow made this. Without it a snapshot read back from a PNG can't
    // say where to re-apply it, and nothing in the image told you either.
    if (typeof flowId !== 'undefined' && flowId) snap.flowId = flowId;
    // Guided sizing: customResDims was already *restored* by
    // applyParamsSnapshot but never captured here, so a custom resolution was
    // reproducible only by accident (when it happened to match a preset).
    if (typeof customResDims !== 'undefined' && customResDims) snap.customResDims = customResDims;
    if (typeof selectedNegativePrompt !== 'undefined' && selectedNegativePrompt) snap.negativePrompt = selectedNegativePrompt;
    if (typeof similarityOn !== 'undefined' && similarityOn) snap.similarity = true;
    if (typeof guidedFixedSeed !== 'undefined' && guidedFixedSeed >= 0) snap.guidedFixedSeed = guidedFixedSeed;
    if (typeof selectedDisabledSubgraphs !== 'undefined' && selectedDisabledSubgraphs &&
        selectedDisabledSubgraphs.length) snap.disabledSubgraphs = selectedDisabledSubgraphs.slice();
    if (typeof _loraKeywordsOff !== 'undefined' && _loraKeywordsOff &&
        Object.keys(_loraKeywordsOff).length) snap.loraKeywordsOff = Object.assign({}, _loraKeywordsOff);
    if (typeof upscaleOutputMode !== 'undefined' && upscaleOutputMode && upscaleOutputMode !== 'none') {
      snap.upscaleOutputMode = upscaleOutputMode;
    }
    // ── Assist dial ───────────────────────────────────────────────────────
    // Level and Flair are the main control of every llm_transform step and
    // they decide which system_prompt is sent, so the *same idea* at a
    // different level produces a different prompt. Genre cards preset both.
    if (typeof selectedLevel !== 'undefined' && selectedLevel) snap.level = selectedLevel;
    if (typeof flairValue    !== 'undefined' && flairValue != null) snap.flair = flairValue;
    if (typeof assistThinkMode !== 'undefined' && assistThinkMode) snap.thinkMode = true;
    if (typeof selectedGenre !== 'undefined' && selectedGenre) snap.genre = selectedGenre;
    // options_groups picks (poster type, angle set, …) — they can rewrite the
    // system prompt AND the aspect ratio, so they belong in the snapshot.
    if (typeof _optGroupValues !== 'undefined' && _optGroupValues &&
        Object.keys(_optGroupValues).length) snap.optionGroups = Object.assign({}, _optGroupValues);
    // The model that wrote the prompt. Recorded, never re-applied: it's a
    // server-wide setting, and silently switching someone's model because
    // they reused an old image's params would be a surprise. Knowing which
    // one produced this text is the reproducible part.
    if (typeof _pickerSettings !== 'undefined' && _pickerSettings) {
      var _llmModel = _pickerSettings.lmStudioPromptModel || _pickerSettings.lmStudioModel || '';
      if (_llmModel) snap.llmModel = String(_llmModel);
    }
    if (typeof getDims === 'function') {
      var d = getDims();
      if (d) { snap.width = d.w; snap.height = d.h; }
    }
    // Custom/Advanced mode keeps its real overrides in _wfAdvOverrides[workflowId]
    // (one bucket per workflow tab, flow-workflow-params-aside.js) — that's what
    // submitWorkflowAndWait/the multi-prompt loop actually reads at generate time
    // (see flow-render-all.js/flow-generation.js's `isCustom ? _wfAdvOverrides[...]`
    // branches). currentAdvOverrides is a *different*, mostly-unused bucket for
    // non-tabbed flows — capturing it here in Custom mode silently snapshotted the
    // wrong (empty) object, so "Apply params" had nothing real to restore
    // (quantization/quality/LoRA picked in the aside never made it into the snapshot).
    var _wfIdForSnap = (extra && extra.workflowId) || null;
    if (typeof getMode === 'function' && getMode() === 'advanced' &&
        typeof _wfAdvOverrides !== 'undefined' && _wfAdvOverrides &&
        _wfIdForSnap && _wfAdvOverrides[_wfIdForSnap] &&
        Object.keys(_wfAdvOverrides[_wfIdForSnap]).length) {
      snap.advancedValues = Object.assign({}, _wfAdvOverrides[_wfIdForSnap]);
    } else if (typeof currentAdvOverrides !== 'undefined' && currentAdvOverrides &&
        Object.keys(currentAdvOverrides).length) {
      snap.advancedValues = Object.assign({}, currentAdvOverrides);
    }
    // Refine/Mix flows keep their real parameter values somewhere else again:
    // the workflow_params step's own `adv_values`, rebuilt by buildAdv() from
    // the fields (prompt, steps, cfg, seed — each keyed by its adv_key). They
    // are NOT in currentAdvOverrides, which only ever holds Custom-mode
    // overrides and is empty in these flows. _runRefine passes them in
    // `extra`, so a card created by a live generation had them — but every
    // snapshot taken anywhere else did not: the session save
    // (_collectFlowSnapshot) and therefore every card restored from history
    // or reopened from the Session came back with no advancedValues at all.
    // That's why "Apply params" on a Flux Klein Edit card put back neither
    // the prompt nor the steps: there was nothing to put back. Read them
    // straight from the step as a fallback (a caller that passes its own
    // still wins, via the `extra` merge below).
    if (!snap.advancedValues && typeof allSteps !== 'undefined' && Array.isArray(allSteps) &&
        typeof getVal === 'function') {
      var _pStep = allSteps.find(function (s) {
        return s && s.type === 'workflow_params' && s.workflow_file;
      });
      var _pAdv = _pStep && getVal(_pStep.id, 'adv_values');
      if (_pAdv && typeof _pAdv === 'object' && Object.keys(_pAdv).length) {
        snap.advancedValues = Object.assign({}, _pAdv);
        // Which graph those node ids belong to — "132.steps" means nothing
        // without it, and a restored card is the one place nobody can tell.
        if (!snap.workflowFile) snap.workflowFile = _pStep.workflow_file;
      }
    }
    // Prompt text per prompt_input step (so multi-prompt flows restore exactly).
    if (typeof allSteps !== 'undefined' && Array.isArray(allSteps) && typeof getVal === 'function') {
      var prompts = {};
      allSteps.forEach(function (s) {
        if (s && s.type === 'prompt_input') {
          var v = getVal(s.id, 'prompt_text');
          if (v) prompts[s.id] = v;
        }
      });
      if (Object.keys(prompts).length) snap.prompts = prompts;
      // An llm_transform's own edited output (transformed_text). Usually it
      // has already been pushed into a prompt_input and captured above, but
      // when output_to points at an ideogram_composer — or the step has no
      // target at all — this is the only copy of what the model wrote.
      var llmOut = {};
      allSteps.forEach(function (s) {
        if (s && s.type === 'llm_transform') {
          var t = getVal(s.id, 'transformed_text');
          if (t) llmOut[s.id] = t;
        }
      });
      if (Object.keys(llmOut).length) snap.llmOutputs = llmOut;
    }
  } catch (_) {}

  if (extra && typeof extra === 'object') {
    Object.keys(extra).forEach(function (k) {
      var v = extra[k];
      if (v !== undefined && v !== null && v !== '') snap[k] = v;
    });
  }

  // If no prompt was captured directly, derive it from the workflow_params
  // prompt/compose field (many refine flows put their prompt there, e.g. a
  // "restoration" compose field whose text lives in advancedValues).
  if (!snap.prompt && !snap.positive && !snap.promptText && !snap.prompts) {
    try {
      var adv = snap.advancedValues ||
                (typeof currentAdvOverrides !== 'undefined' ? currentAdvOverrides : null);
      if (adv && typeof allSteps !== 'undefined' && Array.isArray(allSteps)) {
        var ps = allSteps.find(function (s) { return s && s.type === 'workflow_params' && Array.isArray(s.fields); });
        if (ps) {
          var pf = ps.fields.find(function (f) {
            return f && f.adv_key && (
              f.type === 'compose' || f.type === 'prompt' || f.type === 'textarea' ||
              f.type === 'prompt_history' ||
              /prompt|restor|descri/i.test(String(f.label || ''))
            );
          });
          var pv = pf && adv[pf.adv_key];
          if (pv && String(pv).trim() && String(pv).trim().toLowerCase() !== 'none') {
            snap.prompt = String(pv);
          }
        }
      }
    } catch (_) {}
  }

  return snap;
}

// Reverse-map advanced values back into a workflow_params step's fields and
// re-render that step so the UI reflects the restored values.
// `forceQuantRefresh`: quantization/quality/LoRA picks (selectedQuantizationId
// & friends, restored separately in applyParamsSnapshot below) aren't tied to
// any field's adv_key — they live in renderWorkflowParams' own Quantization
// pill list, built once from loadSavedParams() when the step first mounts.
// Without an explicit re-render here, "Apply params" updates those globals
// (and persists them via saveParams()) but the already-mounted panel keeps
// showing whatever was selected before: the pill list itself is never
// rebuilt, so restoring e.g. INT8 from an old result never shows up in the
// Advanced panel (and buildAdv() never re-runs to fold it into adv_values,
// so the next generation wouldn't actually use it either).
function _applyAdvancedToFields(adv, forceQuantRefresh) {
  if (typeof allSteps === 'undefined' || !Array.isArray(allSteps)) return;
  var hasAdv = !!(adv && Object.keys(adv).length);
  if (!hasAdv && !forceQuantRefresh) return;
  allSteps.forEach(function (s) {
    if (!s || s.type !== 'workflow_params' || !Array.isArray(s.fields)) return;
    var changed = !!(forceQuantRefresh && s.workflow_file);
    if (!hasAdv) { if (changed) _reRenderWorkflowParamsStep(s); return; }
    s.fields.forEach(function (f) {
      if (f && f.adv_key && Object.prototype.hasOwnProperty.call(adv, f.adv_key)) {
        if (typeof setVal === 'function') setVal(s.id, 'field_' + f.id, adv[f.adv_key]);
        changed = true;
      } else if (f && f.type === 'aspect_ratio' && f.adv_keys && f.adv_keys.width && f.adv_keys.height &&
                 Object.prototype.hasOwnProperty.call(adv, f.adv_keys.width) &&
                 Object.prototype.hasOwnProperty.call(adv, f.adv_keys.height)) {
        // aspect_ratio fields don't map to a single adv_key (they drive two
        // node inputs at once — width/height) so the generic branch above
        // never matches them. Reverse the preset lookup buildAdv() does:
        // find whichever preset in this field's set produces the same
        // width/height at its configured resolution, and restore that.
        var _w = Number(adv[f.adv_keys.width]), _h = Number(adv[f.adv_keys.height]);
        var _pset = (f.presets_id && typeof ASPECT_PRESET_SETS !== 'undefined' && ASPECT_PRESET_SETS[f.presets_id]) ||
                    (typeof ASPECT_PRESETS !== 'undefined' ? ASPECT_PRESETS : []);
        var _match = _pset.filter(function (p) {
          var d = p[f.resolution || 'md'] || p.md;
          return d && d.w === _w && d.h === _h;
        })[0];
        if (_match && typeof setVal === 'function') {
          setVal(s.id, 'field_' + f.id, _match.key);
          changed = true;
        }
      }
      // position_grid's X/Y offset inputs are stored under their own
      // field_<id>_offx/_offy keys (not real workflow node inputs, so they
      // never had their own `fields` entry) — restore them alongside the
      // position itself, which the generic f.adv_key branch above already
      // covers.
      if (f && f.type === 'position_grid') {
        if (Object.prototype.hasOwnProperty.call(adv, '_preprocess.offset_x') && typeof setVal === 'function') {
          setVal(s.id, 'field_' + f.id + '_offx', Number(adv['_preprocess.offset_x']) || 0);
          changed = true;
        }
        if (Object.prototype.hasOwnProperty.call(adv, '_preprocess.offset_y') && typeof setVal === 'function') {
          setVal(s.id, 'field_' + f.id + '_offy', Number(adv['_preprocess.offset_y']) || 0);
          changed = true;
        }
      }
    });
    if (changed) _reRenderWorkflowParamsStep(s);
  });
}

// Re-render a single workflow_params step in place (used whenever a value
// that doesn't map to a plain field — quantization/quality/LoRA picks, or a
// matched adv_key above — needs the step's DOM, not just its stored value, to
// catch up).
function _reRenderWorkflowParamsStep(s) {
  if (typeof renderWorkflowParams !== 'function') return;
  var wrap = document.getElementById('ncf-step-wrap-' + s.id);
  var contentEl = wrap ? (wrap.querySelector('.ncf-collapse-inner') || wrap) : null;
  if (!contentEl) return;
  try {
    contentEl.innerHTML = '';
    renderWorkflowParams(s, contentEl);
    // renderAllSteps() (flow-render-all.js) pins this step's "Advanced"
    // trigger row into the sticky footer on the initial render — this
    // targeted single-step re-render bypasses that pass entirely, so
    // without redoing it here the OLD pinned row is left stranded in
    // the footer (stale closures) while the fresh render adds a
    // second, unpinned "Advanced" row inside the step itself. Visible
    // as two "Advanced" buttons stacked in the panel — reported after
    // reopening a Session step, which restores params through this
    // same path.
    var stepsFooterEl = document.getElementById('ncf-steps-footer');
    var newAdvBtn = contentEl.querySelector('button[aria-label="Advanced options"]');
    var newAdvRow = newAdvBtn && newAdvBtn.closest('.nsc-param-title');
    if (newAdvRow && stepsFooterEl) {
      var stalePinned = stepsFooterEl.querySelector('.ncf-advanced-row--pinned');
      if (stalePinned) stalePinned.remove();
      newAdvRow.classList.add('ncf-advanced-row--pinned');
      stepsFooterEl.insertBefore(newAdvRow, stepsFooterEl.firstChild);
    }
  } catch (_) {}
}

// Apply a previously-captured params snapshot back into the live form.
function applyParamsSnapshot(params) {
  if (!params || typeof params !== 'object') return;
  try {
    // ── Prompt(s) ──
    var promptsObj  = params.prompts || null;
    var singlePrompt = params.prompt || params.promptText || params.positive || '';
    if (typeof allSteps !== 'undefined' && Array.isArray(allSteps)) {
      allSteps.forEach(function (s) {
        if (!s || s.type !== 'prompt_input') return;
        var val = (promptsObj && promptsObj[s.id] != null) ? promptsObj[s.id] : singlePrompt;
        if (val == null || val === '') return;
        if (typeof setVal === 'function') setVal(s.id, 'prompt_text', val);
        var ta = document.getElementById('ncf-input-' + s.id);
        if (ta) ta.value = val;
      });
    }

    // ── llm_transform outputs (composer targets, untargeted steps) ──
    if (params.llmOutputs && typeof allSteps !== 'undefined' && Array.isArray(allSteps)) {
      allSteps.forEach(function (s) {
        if (!s || s.type !== 'llm_transform') return;
        var t = params.llmOutputs[s.id];
        if (!t) return;
        if (typeof setVal === 'function') setVal(s.id, 'transformed_text', t);
        var outTa = document.getElementById('ncf-llm-output-' + s.id) ||
                    document.getElementById('ncf-input-' + s.id);
        if (outTa) outTa.value = t;
      });
    }

    // ── Assist dial: level / flair / think / genre ──
    // These decide which system_prompt an llm_transform sends, so restoring
    // the prompt text without them reproduces the picture but not the flow:
    // hitting the step again would rewrite it at whatever level was left
    // selected. syncLLMOptionsModalUI() keeps the panel honest if it happens
    // to be open at the time.
    if (params.level     && typeof selectedLevel   !== 'undefined') selectedLevel   = params.level;
    if (params.flair != null && typeof flairValue  !== 'undefined') flairValue      = params.flair;
    if (typeof assistThinkMode !== 'undefined' && params.thinkMode != null) assistThinkMode = !!params.thinkMode;
    if (params.genre     && typeof selectedGenre   !== 'undefined') selectedGenre   = params.genre;
    if ((params.level || params.flair != null) && typeof syncLLMOptionsModalUI === 'function') {
      try { syncLLMOptionsModalUI(); } catch (_) {}
    }

    // ── options_groups (poster type, angle set, …) ──
    // Their buttons are rebuilt from the stored `optgrp_<id>` keys when the
    // workflow_params step re-renders (below), so write both the live object
    // and the persisted one.
    if (params.optionGroups && typeof _optGroupValues !== 'undefined') {
      _optGroupValues = Object.assign({}, _optGroupValues, params.optionGroups);
      try {
        var _savedOpt = (typeof loadSavedParams === 'function' && loadSavedParams()) || {};
        Object.keys(params.optionGroups).forEach(function (gid) {
          _savedOpt['optgrp_' + gid] = params.optionGroups[gid];
        });
        localStorage.setItem(PARAMS_KEY, JSON.stringify(_savedOpt));
      } catch (_) {}
    }

    // ── Seed ──
    if (params.seed != null && typeof selectedSeed !== 'undefined') {
      selectedSeed = params.seed;
      var seedInp = document.getElementById('ncf-seed-input') ||
                    document.querySelector('[id^="ncf-seed-"]');
      if (seedInp && Number(params.seed) >= 0) seedInp.value = params.seed;
    }

    // ── Aspect / resolution / quality (guided globals) ──
    if (params.aspectIdx  != null && typeof selectedAspectIdx  !== 'undefined') selectedAspectIdx  = params.aspectIdx;
    if (params.resolution        && typeof selectedResolution  !== 'undefined') selectedResolution = params.resolution;
    if (typeof customResDims !== 'undefined') customResDims = params.customResDims || null;
    if (params.qualityId         && typeof selectedQualityId   !== 'undefined') selectedQualityId  = params.qualityId;
    if (params.qualityValues     && typeof selectedQualityValues !== 'undefined') selectedQualityValues = params.qualityValues;
    if (params.quantizationId     && typeof selectedQuantizationId   !== 'undefined') selectedQuantizationId  = params.quantizationId;
    if (params.quantizationValues && typeof selectedQuantizationValues !== 'undefined') selectedQuantizationValues = params.quantizationValues;
    if (params.loraValues && typeof selectedLoraValues !== 'undefined') selectedLoraValues = params.loraValues;
    if (params.negativePrompt && typeof selectedNegativePrompt !== 'undefined') selectedNegativePrompt = params.negativePrompt;
    if (params.similarity != null && typeof similarityOn !== 'undefined') similarityOn = !!params.similarity;
    if (params.guidedFixedSeed != null && typeof guidedFixedSeed !== 'undefined') guidedFixedSeed = params.guidedFixedSeed;
    if (params.disabledSubgraphs && typeof selectedDisabledSubgraphs !== 'undefined') selectedDisabledSubgraphs = params.disabledSubgraphs.slice();
    if (params.loraKeywordsOff && typeof _loraKeywordsOff !== 'undefined') _loraKeywordsOff = Object.assign({}, params.loraKeywordsOff);
    if (params.upscaleOutputMode && typeof upscaleOutputMode !== 'undefined') upscaleOutputMode = params.upscaleOutputMode;

    // ── Advanced overrides (used by the next generation) + reflect in UI ──
    // In Custom/Advanced mode these live in _wfAdvOverrides[workflowId] (one
    // per open tab), not currentAdvOverrides — see buildParamsSnapshot's
    // comment above. Restore into whichever tab the snapshot came from if
    // known, else every currently open tab (a single-workflow Custom flow,
    // the common case here, only ever has one), so quantization/quality/LoRA
    // picked via "Apply params" actually reach the payload the next
    // generation reads, and re-render each tab's pills/inputs so the picked
    // preset and quantization option show as selected instead of stale.
    if (params.advancedValues) {
      if (typeof getMode === 'function' && getMode() === 'advanced' &&
          typeof _wfAdvOverrides !== 'undefined' && _wfAdvOverrides) {
        var _wfIdsToRestore = params.workflowId ? [params.workflowId]
          : (typeof getGlobalWorkflows === 'function' ? getGlobalWorkflows() : Object.keys(_wfAdvOverrides));
        _wfIdsToRestore.forEach(function (wid) {
          _wfAdvOverrides[wid] = Object.assign({}, _wfAdvOverrides[wid] || {}, params.advancedValues);
          if (typeof _wfTabRefreshFns !== 'undefined' && _wfTabRefreshFns[wid]) {
            try { _wfTabRefreshFns[wid](); } catch (_) {}
          }
        });
      }
      if (typeof currentAdvOverrides !== 'undefined') {
        currentAdvOverrides = Object.assign({}, currentAdvOverrides, params.advancedValues);
      }
    }
    _applyAdvancedToFields(params.advancedValues,
      !!(params.quantizationId || params.qualityId || params.loraValues || params.optionGroups));

    // ── Ideogram composer (Lettering/Poster/Scene flows) ──
    // The composed JSON isn't a prompt_input value — it lives in the
    // ideogram_composer step's own state and gets pushed into its canvas/cards
    // UI through that step's _fillFn. buildParamsSnapshot's generic prompt
    // handling above never touches it, so restore it explicitly here: prefer
    // the structured object captured at save time (ideogramComposition),
    // falling back to parsing `positive` in case an older snapshot only has
    // the serialized string.
    if (typeof allSteps !== 'undefined' && Array.isArray(allSteps)) {
      var _composerStep = allSteps.find(function (s) { return s && s.type === 'ideogram_composer'; });
      if (_composerStep && typeof _composerStep._fillFn === 'function') {
        var _composition = params.ideogramComposition || null;
        if (!_composition && singlePrompt) {
          try {
            var _parsed = JSON.parse(singlePrompt);
            if (_parsed && _parsed.compositional_deconstruction) _composition = _parsed;
          } catch (_) { /* not JSON — nothing to restore */ }
        }
        if (_composition) {
          try { _composerStep._fillFn(JSON.stringify(_composition)); } catch (_) {}
        }
      }
    }

    if (typeof saveParams === 'function') saveParams();

    // Guided "Create" flow's Advanced panel (param_group step, renderParamGroup)
    // builds its Quantization/Quality pill lists once and only ever rebuilds
    // them off this same 'ncf-workflow-loaded' event (fired today when the
    // selected import/workflow changes) — reading the freshly-saved params
    // above via loadSavedParams(). Firing it here too is what actually makes
    // "Apply params" restore INT8/FP8/etc. and the quality tier in THAT
    // panel; renderWorkflowParams' own (different) Quantization block for
    // plain workflow_file steps is handled separately, above, via
    // _applyAdvancedToFields's forced re-render.
    if ((params.quantizationId || params.qualityId) &&
        typeof selectedImportRecord !== 'undefined' && selectedImportRecord) {
      try { document.dispatchEvent(new CustomEvent('ncf-workflow-loaded', { detail: selectedImportRecord })); } catch (_) {}
    }

    if (typeof updateGenerateBtn === 'function') updateGenerateBtn();
  } catch (e) {
    if (window.console) console.error('[FlowEngine] applyParamsSnapshot:', e);
  }
}
