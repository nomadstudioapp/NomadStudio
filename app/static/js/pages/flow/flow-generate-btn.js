'use strict';
// Generate button: updateGenerateBtn + JSON modal DOM refs

function updateGenerateBtn() {
  // Let the Layer Composer step (if present) refresh its preview whenever any
  // step value changes — e.g. the bg/layer image_picker steps get filled in.
  if (typeof window._ncfLcRefresh === 'function') { try { window._ncfLcRefresh(); } catch (_) {} }
  // Same hook, for the Region Annotate step (flow-step-region-annotate.js)
  // — refreshes its inline thumbnail whenever the source image_picker changes.
  if (typeof window._ncfAnnotateRefresh === 'function') { try { window._ncfAnnotateRefresh(); } catch (_) {} }
  // Same hook, for Refine/Mix's fixed-Resolution readout (flow-render-all.js)
  // — refreshes it whenever the picked image changes.
  if (typeof window._ncfFixedResRefresh === 'function') { try { window._ncfFixedResRefresh(); } catch (_) {} }

  var actionStep = allSteps && allSteps.find(function (s) { return s.type === 'action'; });
  var disabled;
  var tip = '';

  if (actionStep && actionStep.calls === 'generation.submit_upscale') {
    var im = actionStep.input_map || {};
    var hasImage = !!resolveRef(im['imageDataUrl']);
    var hasModel = !!resolveRef(im['modelId']);
    disabled = !hasImage || !hasModel; // enqueueable while generating
    if (!hasImage) tip = 'Pick an image to upscale';
    else if (!hasModel) tip = 'Pick an upscale model';
  } else if (actionStep && actionStep.calls === 'generation.submit_refine') {
    var im = actionStep.input_map || {};
    var hasImage = !!resolveRef(im['imageDataUrl']);
    disabled = !hasImage; // enqueueable while generating
    if (!hasImage) tip = 'Pick an image to refine';
  } else if (actionStep && actionStep.calls === 'generation.submit_mix') {
    var im = actionStep.input_map || {};
    var imagesDef = im['images'];
    // An entry flagged `optional` is satisfied by its image OR — only for
    // entries that actually declare a textFallback (e.g. Clothes Mix's
    // reference photo, backed by a manual description field next to it) —
    // that text instead. An optional entry with no textFallback key at all
    // (e.g. Multi-Reference Compose's 3rd/4th reference slots — nothing to
    // fall back to, they're just skippable extra references) needs neither:
    // being flagged optional is enough on its own.
    var allImagesReady = Array.isArray(imagesDef) && imagesDef.every(function (e) {
      if (!!resolveRef(e.dataUrl)) return true;
      if (!e.optional) return false;
      return e.textFallback ? !!resolveRef(e.textFallback) : true;
    });
    disabled = !allImagesReady; // enqueueable while generating
    if (!allImagesReady) tip = 'Pick all the images to mix';
  } else if (actionStep && actionStep.calls === 'pixel_match.submit') {
    var im = actionStep.input_map || {};
    var hasImage = !!resolveRef(im['imageDataUrl']);
    disabled = !hasImage;
    if (!hasImage) tip = 'Pick an image first';
  } else if (actionStep && actionStep.calls === 'chroma_key.submit') {
    var im = actionStep.input_map || {};
    var hasImage = !!resolveRef(im['imageDataUrl']);
    disabled = !hasImage;
    if (!hasImage) tip = 'Pick an image first';
  } else if (actionStep && actionStep.calls === 'layer_compose.submit') {
    var im = actionStep.input_map || {};
    var hasBg = !!resolveRef(im['bgDataUrl']);
    var hasLayer = !!resolveRef(im['layerDataUrl']);
    disabled = !hasBg || !hasLayer;
    if (!hasBg) tip = 'Pick a background image';
    else if (!hasLayer) tip = 'Pick a layer image';
  } else {
    var hasWorkflow = getMode() === 'advanced'
      ? getGlobalWorkflows().length > 0
      : !!selectedImportId;
    var hasPrompt = false;
    if (getMode() === 'simple') {
      // Simple mode's basicValues.positive target may be a hidden llm_transform
      // output that doesn't exist yet — gate on the one visible prompt box
      // instead; the LLM step runs automatically when Generate is clicked.
      var _simpleMainId = typeof _simpleMainPromptStepId === 'function' ? _simpleMainPromptStepId() : null;
      hasPrompt = !!(_simpleMainId && getVal(_simpleMainId, 'prompt_text'));
    } else if (actionStep && actionStep.input_map && actionStep.input_map['basicValues.positive']) {
      hasPrompt = !!resolveRef(actionStep.input_map['basicValues.positive']);
    } else {
      hasPrompt = !!(getVal('scene_prompt', 'prompt_text') || getVal('world', 'prompt_text'));
    }
    disabled = !hasWorkflow || !hasPrompt; // enqueueable while generating
    if (!hasWorkflow) tip = 'Choose a workflow first';
    else if (!hasPrompt) tip = 'Write a prompt to generate';
  }

  if (generateBtn) {
    generateBtn.disabled = disabled;
    var _tipEl = generateBtn.querySelector('.cs-mode-tip');
    if (_tipEl) _tipEl.textContent = disabled ? tF(tip) : '';
    // While a generation is running, an enabled button enqueues the next job —
    // reflect that by relabeling it to "Enqueue".
    var _btnSpan = generateBtn.querySelector('span');
    if (_btnSpan) {
      if (isGenerating && !disabled) {
        _btnSpan.textContent = tF('Queue');
      } else {
        _btnSpan.textContent = tF((actionStep && actionStep.label) || 'Generate');
      }
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════
// WORKFLOW LOADING (Scenes pattern)
// ══════════════════════════════════════════════════════════════════════════
async function loadWorkflows(selectEl, hintEl, recommendedIds) {
  try {
    var listRes  = await fetch('/api/models/imports');
    if (!listRes.ok) throw new Error('imports list ' + listRes.status);
    var listData = await listRes.json();
    var allImports = Array.isArray(listData.imports) ? listData.imports : [];
    // Some flows name the engines they were built around (Character Sheet:
    // Ideogram 4 and Krea2 Monaco). They used to be a filter and everything else
    // was hidden — which assumes we know what the user has. We don't: engines
    // are imported, so someone's own import may well be the right one, and
    // hiding it makes the product wrong rather than helpful. Recommend, sort
    // to the top, and leave the choice alone.
    var recommendedSet = (Array.isArray(recommendedIds) ? recommendedIds : []).map(String);
    if (recommendedSet.length) {
      allImports = allImports.slice().sort(function (a, b) {
        var ra = recommendedSet.indexOf(String(a.id)) !== -1 ? 0 : 1;
        var rb = recommendedSet.indexOf(String(b.id)) !== -1 ? 0 : 1;
        return ra - rb;
      });
    }
    allImportsList = allImports;

    if (!allImports.length) {
      selectEl.innerHTML = '<option value="">' + escHtml(tF('No workflows — go to Models › Import')) + '</option>';
      if (hintEl) hintEl.textContent = tF('Import a workflow first.');
      return;
    }

    var activeId = '';
    var serverActiveIds = Array.isArray(listData.activeImportIds) ? listData.activeImportIds : [];
    try {
      if (window.openJourneyApi && typeof window.openJourneyApi.getActiveImport === 'function') {
        var activeRes  = await window.openJourneyApi.getActiveImport();
        var activeImps = Array.isArray(activeRes.activeImports) ? activeRes.activeImports : [];
        if (!activeImps.length && activeRes.active) activeImps = [activeRes.active];
        activeImps.forEach(function (r) { if (r && r.id) fullRecordCache[String(r.id)] = r; });
        activeId = activeRes.activeImportId || (activeImps[0] && activeImps[0].id) || '';
        if (activeRes.activeImportIds && activeRes.activeImportIds.length) serverActiveIds = activeRes.activeImportIds;
      }
    } catch (_) {}

    // Auto-init global workflow selection if nothing saved yet
    if (!getGlobalWorkflows().length && serverActiveIds.length) {
      setGlobalWorkflows(serverActiveIds);
    } else if (!getGlobalWorkflows().length && allImports.length) {
      setGlobalWorkflows([String(allImports[0].id)]);
    }
    if (typeof renderWorkflowMultiList === 'function') renderWorkflowMultiList();
    if (typeof renderWfParamsAside === 'function') renderWfParamsAside();

    selectEl.innerHTML = '';
    // Grouped, not renamed: an <optgroup> says which engines this flow was
    // built around while every option keeps the engine's actual name. Putting
    // the note inside the option text renamed them, and anything matching an
    // engine by name — the tutorial recorder, for one — stopped finding it.
    var mkOption = function (imp) {
      var opt = document.createElement('option');
      opt.value = String(imp.id || '');
      opt.textContent = String(imp.name || imp.id || 'Unnamed');
      return opt;
    };
    var recommended = recommendedSet.length
      ? allImports.filter(function (i) { return recommendedSet.indexOf(String(i.id)) !== -1; })
      : [];
    if (recommended.length) {
      var gRec = document.createElement('optgroup');
      gRec.label = tF('Recommended for this flow');
      recommended.forEach(function (imp) { gRec.appendChild(mkOption(imp)); });
      selectEl.appendChild(gRec);
      var rest = allImports.filter(function (i) { return recommendedSet.indexOf(String(i.id)) === -1; });
      if (rest.length) {
        var gAll = document.createElement('optgroup');
        gAll.label = tF('Everything else you have imported');
        rest.forEach(function (imp) { gAll.appendChild(mkOption(imp)); });
        selectEl.appendChild(gAll);
      }
    } else {
      allImports.forEach(function (imp) { selectEl.appendChild(mkOption(imp)); });
    }

    var cached = localStorage.getItem(WORKFLOW_KEY);
    var def = (cached && allImports.find(function (r) { return String(r.id) === cached; }))
           || allImports.find(function (r) { return String(r.id) === String(activeId); })
           || allImports[0];
    // With nothing saved, start on a recommended engine rather than whichever
    // import sorts first — the recommendation is only useful if it is the one
    // you land on.
    if (recommendedSet.length && !cached) {
      var firstRec = allImports.find(function (r) { return recommendedSet.indexOf(String(r.id)) !== -1; });
      if (firstRec) def = firstRec;
    }
    selectEl.value = String(def.id || '');
    await selectImportById(String(def.id || ''), hintEl);

  } catch (err) {
    selectEl.innerHTML = '<option value="">' + escHtml(tF('Error loading workflows')) + '</option>';
    console.error('[FlowEngine] loadWorkflows:', err);
  }
}

async function fetchFullRecord(id) {
  if (fullRecordCache[id]) return fullRecordCache[id];
  var res = await fetch('/api/models/imports/' + encodeURIComponent(id));
  if (!res.ok) throw new Error('import fetch ' + res.status);
  var data = await res.json();
  var record = data.import || data;
  if (record && record.id) fullRecordCache[String(record.id)] = record;
  return record;
}

async function selectImportById(id, hintEl) {
  if (!id) return;
  if (hintEl) hintEl.textContent = tF('Loading…');
  try {
    var record = await fetchFullRecord(id);
    selectedImportId     = id;
    selectedImportRecord = record;
    localStorage.setItem(WORKFLOW_KEY, id);
    if (hintEl) hintEl.textContent = '';
    document.dispatchEvent(new CustomEvent('ncf-workflow-loaded', { detail: record }));
    updateGenerateBtn();
  } catch (err) {
    if (hintEl) hintEl.textContent = tF('Could not load workflow.');
    console.error('[FlowEngine] selectImportById:', err);
  }
}

