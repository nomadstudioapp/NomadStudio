'use strict';
// Core renderer: renderAction, renderAllSteps, resolveOutputTo, revealTriggeredStep + event listeners

var UPSCALE_OUTPUT_OPTIONS = [
  { id: 'none', label: 'None', title: 'Use the result as-is.' },
  { id: '2x_fast', label: '2xFast', title: 'Run RealESRGAN 2x on the result before showing it.' },
  { id: '4x_fast', label: '4xFast', title: 'Run RealESRGAN 4x on the result before showing it.' },
  { id: '4x_sharp', label: '4xSharp', title: 'Run UltraSharp V2 4x on the result before showing it. Great for low resolution images.' },
  { id: '2x', label: '2x', title: 'Run SeedVR2 3B (2x) on the result before showing it. Diffusion-based restoration, higher quality, slower.' },
  { id: '4x', label: '4x', title: 'Run SeedVR2 7B (4x) on the result before showing it. Diffusion-based restoration, highest quality, slowest.' },
];

function _upscaleOutputLabel(mode) {
  var opt = UPSCALE_OUTPUT_OPTIONS.find(function (o) { return o.id === mode; });
  return opt ? opt.label : 'None';
}

// Shared grid-builder for the Upscale Output picker — used both by Create's
// own standalone panel and by Refine/Mix's combined Resolution+Upscale panel
// below. Same visual language as Resolution's tier grid (openResolutionPanel,
// flow-aspect-panel.js) since this is a straight reuse of that pattern
// (issue #74).
function _buildUpscaleOutputGrid(container, onChange) {
  var list = document.createElement('div');
  list.className = 'nsc-quality-list ncf-resolution-grid ncf-upscale-grid';
  list.setAttribute('role', 'radiogroup');
  UPSCALE_OUTPUT_OPTIONS.forEach(function (opt) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nsc-quality-btn' + (opt.id === upscaleOutputMode ? ' is-active' : '');
    btn.setAttribute('role', 'radio');
    btn.setAttribute('aria-checked', opt.id === upscaleOutputMode ? 'true' : 'false');
    btn.title = opt.title;
    btn.innerHTML =
      '<span class="nsc-quality-dot"></span>' +
      '<span class="nsc-quality-copy"><strong>' + opt.label + '</strong></span>';
    btn.addEventListener('click', function () {
      upscaleOutputMode = opt.id;
      list.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
        b.classList.remove('is-active');
        b.setAttribute('aria-checked', 'false');
      });
      btn.classList.add('is-active');
      btn.setAttribute('aria-checked', 'true');
      if (onChange) onChange(opt.id);
    });
    list.appendChild(btn);
  });
  container.appendChild(list);
}

// Refine/Mix: the input image already exists, so there is no "Resolution" to
// pick — only to show. Reads the action step's own input_map (the same
// mechanism the flow engine already uses to wire submit payloads) to find
// whichever image reference this flow's action step actually consumes.
function _resolveFixedSourceImageUrl() {
  var actionStep = Array.isArray(allSteps) && allSteps.find(function (s) { return s.type === 'action'; });
  var im = (actionStep && actionStep.input_map) || {};
  var ref = im.imageDataUrl || im.bgDataUrl ||
    (Array.isArray(im.images) && im.images.length ? im.images[0].dataUrl : null);
  return ref ? resolveRef(ref) : null;
}

var _fixedResDimsCache = {};
function _measureImageDims(dataUrl, cb) {
  if (!dataUrl) { cb(null); return; }
  if (_fixedResDimsCache[dataUrl]) { cb(_fixedResDimsCache[dataUrl]); return; }
  var img = new Image();
  img.onload = function () {
    var dims = { w: img.naturalWidth || 0, h: img.naturalHeight || 0 };
    _fixedResDimsCache[dataUrl] = dims;
    cb(dims);
  };
  img.onerror = function () { cb(null); };
  img.src = dataUrl;
}

// Refine/Mix: single button opening a single panel — a read-only resolution
// readout on top (nothing to pick, the image already exists), the same
// Upscale Output grid right below it.
function _renderFixedResUpscaleControl(el) {
  var wrap = document.createElement('div');
  wrap.className = 'nsc-param-block';
  wrap.innerHTML =
    '<p class="nsc-param-title nsc-param-title--flex">Resolution <span class="nsc-param-value" id="ncf-fixed-res-label">—</span>' +
      '<button type="button" class="nsc-history-btn nsc-options-trigger" id="ncf-fixed-res-picker-btn" aria-label="Resolution and upscale output">' +
        '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1.5" y="6" width="7.5" height="7.5" rx="1.3"/><rect x="7.5" y="1.5" width="9" height="9" rx="1.3"/></svg>' +
      '</button>' +
    '</p>';
  el.appendChild(wrap);
  var labelEl = wrap.querySelector('#ncf-fixed-res-label');
  var pickerBtn = wrap.querySelector('#ncf-fixed-res-picker-btn');

  function refreshLabel() {
    if (!labelEl) return;
    var url = _resolveFixedSourceImageUrl();
    if (!url) { labelEl.textContent = '—'; return; }
    _measureImageDims(url, function (dims) {
      labelEl.textContent = dims ? (dims.w + '×' + dims.h) : '—';
    });
  }
  window._ncfFixedResRefresh = refreshLabel;
  refreshLabel();

  pickerBtn.addEventListener('click', function () {
    openOptionsPanel('Resolution', function (body) {
      var resBlock = document.createElement('div');
      resBlock.className = 'nsc-param-block ncf-fixed-res-readout';
      var url = _resolveFixedSourceImageUrl();
      resBlock.innerHTML = '<p class="nsc-param-title">Source resolution</p>' +
        '<p class="ncf-fixed-res-value">' + (url ? '' : 'No image picked yet') + '</p>';
      body.appendChild(resBlock);
      var valueEl = resBlock.querySelector('.ncf-fixed-res-value');
      if (url) {
        _measureImageDims(url, function (dims) {
          if (valueEl) valueEl.textContent = dims ? (dims.w + '×' + dims.h) : 'Unknown';
        });
      }

      var upBlock = document.createElement('div');
      upBlock.className = 'nsc-param-block';
      upBlock.innerHTML = '<p class="nsc-param-title">Upscale output</p>';
      body.appendChild(upBlock);
      _buildUpscaleOutputGrid(upBlock);
    });
  });
}

function renderUpscaleOutputToggle(el) {
  var isCreateFlow = typeof flowId === 'string' && flowId.indexOf('create.') === 0;
  // Create: Upscale output lives inside the Resolution panel itself now
  // (openResolutionPanel, flow-aspect-panel.js) — nothing to render here.
  if (isCreateFlow) return;
  _renderFixedResUpscaleControl(el);
}

function renderAction(stepDef, el) {
  renderUpscaleOutputToggle(el);

  generateBtn = document.createElement('button');
  generateBtn.className = 'nss-generate-scenes-btn';
  generateBtn.id = 'ncf-generate-btn-' + stepDef.id;
  generateBtn.type = 'button';
  generateBtn.disabled = true;
  generateBtn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true" style="width:18px;height:18px"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>' +
    '<span>' + escHtml(tF(stepDef.label || 'Generate scene')) + '</span>' +
    '<span class="cs-mode-tip"></span>';
  el.appendChild(generateBtn);

  generateStatus = mkHint('');
  generateStatus.id = 'ncf-gen-status';
  generateStatus.setAttribute('aria-live', 'polite');
  // Lives at the top of the results feed (vertically aligned with the zoom
  // controls) instead of under the button in the steps panel — reads more
  // naturally next to the images it's reporting on.
  var resultsHeader = document.getElementById('ncf-results-header');
  if (resultsHeader) resultsHeader.insertBefore(generateStatus, resultsHeader.firstChild);
  else el.appendChild(generateStatus);

  function _proceedToGenerate() {
    if (isGenerating) {
      _enqueueGeneration(stepDef);
      return;
    }
    // Keep the scene prompt after generating — the user may want to regenerate
    // with a different seed/params without retyping or re-running the LLM.
    runGenerate(stepDef);
  }

  generateBtn.addEventListener('click', function () {
    if (getMode() === 'simple') {
      // Simple mode hides any llm_transform step (level/flair pickers, the
      // rewritten-prompt box) — run it now, with its defaults, before we
      // read basicValues.positive off of it.
      generateBtn.disabled = true;
      runPendingSimpleLLMSteps().then(function () {
        generateBtn.disabled = false;
        _proceedToGenerate();
      }).catch(function (err) {
        generateBtn.disabled = false;
        console.error('[FlowEngine] Simple mode LLM prep failed:', err);
        showErrorToast((err && err.message) || 'Could not prepare prompt');
      });
      return;
    }
    _proceedToGenerate();
  });

  updateGenerateBtn();
}

// ══════════════════════════════════════════════════════════════════════════
// RENDER ALL STEPS AT ONCE
// ══════════════════════════════════════════════════════════════════════════
function renderAllSteps() {
  if (!stepsEl) return;
  var stepsScrollEl = document.getElementById('ncf-steps-scroll') || stepsEl;
  var stepsFooterEl = document.getElementById('ncf-steps-footer');
  stepsScrollEl.innerHTML = '';
  if (stepsFooterEl) stepsFooterEl.innerHTML = '';
  var visibleNum = 0;
  allSteps.forEach(function (stepDef) {
    if (stepDef.type === 'result_view') return;
    var isTriggered = !!stepDef.triggered_by;
    var wrap = document.createElement('div');
    wrap.className = 'nsc-step';
    wrap.id = 'ncf-step-wrap-' + stepDef.id;
    if (isTriggered) wrap.style.display = 'none';

    // Label — no more numeric badge, just the section text (reduces visual load).
    // Steps no longer expand/collapse — only the nested "Advanced" toggle
    // inside Parameters keeps that behavior (see renderParamGroup).
    var lbl = document.createElement('p');
    lbl.className = 'nsc-step-label';
    if (!isTriggered) visibleNum++;
    lbl.appendChild(document.createTextNode(tF(stepDef.label || stepDef.id)));

    var contentEl = wrap;
    // Action (Generate) skips its title — the button already carries the
    // same label text. Parameters skips its title too — it reads fine as a
    // plain block of controls with no heading above it. A prompt_input that
    // prefills from another step's output (e.g. Assist's "Enhanced prompt")
    // reads as a continuation of that step, not a new heading of its own.
    var skipLabel = stepDef.type === 'action' || stepDef.type === 'param_group' ||
      (stepDef.type === 'workflow_params' && !stepDef.show_label) ||
      (stepDef.type === 'prompt_input' && !!stepDef.prefill_from);
    if (!skipLabel) wrap.appendChild(lbl);

    switch (stepDef.type) {
      case 'workflow_picker': renderWorkflowPicker(stepDef, contentEl);  break;
      case 'prompt_input':    renderPromptInput(stepDef, contentEl);     break;
      case 'json_input':      renderJsonInput(stepDef, contentEl);       break;
      case 'civitai_paste':   renderCivitAIPaste(stepDef, contentEl);    break;
      case 'llm_transform':   renderLLMTransform(stepDef, contentEl);    break;
      case 'param_group':     renderParamGroup(stepDef, contentEl, visibleNum);      break;
      case 'image_picker':       renderImagePicker(stepDef, contentEl);       break;
      case 'template_picker':    renderTemplatePicker(stepDef, contentEl);    break;
      case 'lettering_builder':  renderLetteringBuilder(stepDef, contentEl); break;
      case 'upscale_picker':     renderUpscalePicker(stepDef, contentEl);    break;
      case 'workflow_params':     renderWorkflowParams(stepDef, contentEl, visibleNum);    break;
      case 'vision_describe':     renderVisionDescribe(stepDef, contentEl);    break;
      case 'bulk_vision':         renderBulkVision(stepDef, contentEl);        break;
      case 'scene_builder':     renderSceneBuilder(stepDef, contentEl);     break;
      case 'ideogram_composer':
        try { renderIdeogramComposer(stepDef, contentEl); }
        catch (e) { console.error('[FlowEngine] ideogram_composer:', e); }
        break;
      case 'layer_compositor':
        try { renderLayerCompositor(stepDef, contentEl); }
        catch (e) { console.error('[FlowEngine] layer_compositor:', e); }
        break;
      case 'action':              renderAction(stepDef, wrap);                break;
    }
    if (stepDef.type === 'action' && stepsFooterEl) stepsFooterEl.appendChild(wrap);
    else stepsScrollEl.appendChild(wrap);
  });

  // Pin the "Advanced" trigger (Quantization/Parameters/Quality/...) right
  // above Upscale output + Generate in the sticky footer, instead of
  // leaving it wherever its owning step (Parameters/workflow_params) landed
  // in the scrollable list above. That step is otherwise often near-empty
  // (e.g. Mix flows whose only fields are all "advanced"), which left the
  // button stranded with a big blank gap below it and no visual connection
  // to the controls it actually affects. Works for both the workflow_file
  // (renderWorkflowParams) and Create-guided (renderParamGroup) variants —
  // both share the same aria-label, only their wrapper row's class differs.
  var advTriggerBtn = stepsScrollEl.querySelector('button[aria-label="Advanced options"]');
  var advTriggerRow = advTriggerBtn && advTriggerBtn.closest('.nsc-param-title');
  if (advTriggerRow && stepsFooterEl) {
    advTriggerRow.classList.add('ncf-advanced-row--pinned');
    stepsFooterEl.insertBefore(advTriggerRow, stepsFooterEl.firstChild);
  }

  // Bulk Vision's "Generate All" (renderBulkVision, flow-step-bulk-vision.js)
  // plays the same role as the standard action step's Generate button — it
  // pushes straight onto the generation queue — but bulk_vision isn't type
  // 'action' so it never got the stepsFooterEl treatment above and stayed
  // stranded in the scrollable list, ABOVE the Advanced trigger once that
  // got pinned to the true bottom instead of below it like every other
  // flow's submit button. Same extract-and-move pattern as Advanced.
  var bulkGenerateAllBtn = stepsScrollEl.querySelector('[id^="ncf-bulk-generate-all-"]');
  if (bulkGenerateAllBtn && stepsFooterEl) {
    stepsFooterEl.appendChild(bulkGenerateAllBtn);
  }

  // Post-render: resolve output_to references so LLM writes directly into target textarea
  resolveOutputTo();

  // Simple mode: hide the workflow_picker and param_group/workflow_params
  // steps entirely — Simple reuses whatever workflow/quality/quantization
  // was last selected in Guided mode under the hood, it just shows no
  // controls. Only Prompt + Generate (+ Result) remain visible.
  syncSimpleModeStepVisibility();

  // The Custom-params aside renders before allSteps does (mode is applied
  // pre-render), so its step number is only known once renderAllSteps ran.
  if (typeof renderWfParamsAside === 'function') renderWfParamsAside();

  // Story action buttons — only for flows that have a continue_story trigger
  var hasStoryContinue = allSteps.some(function (s) { return s.triggered_by === 'result.action.continue_story'; });
  if (hasStoryContinue) {
    var storyActions = document.createElement('div');
    storyActions.id = 'ncf-story-actions';
    storyActions.className = 'ncf-story-actions nss-queue-actions';
    storyActions.style.display = 'none';
    storyActions.innerHTML =
      '<button class="nss-queue-all-btn" id="ncf-continue-btn" type="button">' +
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M12 5l7 7-7 7"/></svg>' +
        ' Continue story' +
      '</button>' +
      '<button class="nss-queue-selected-btn" id="ncf-end-btn" type="button">End story</button>';
    (stepsFooterEl || stepsScrollEl).appendChild(storyActions);
  }
}

// Simple mode: only the first "main prompt" step (prompt_input/json_input)
// and the action (Generate) step stay visible — everything else (workflow
// picker, quality/quantization/resolution params, llm_transform controls,
// image/template/scene pickers…) collapses to its default/last-used value
// with no UI. Steps that are `triggered_by` another step are left alone —
// their visibility is owned by revealTriggeredStep(), not by mode.
var SIMPLE_MAIN_PROMPT_TYPES = { prompt_input: true, json_input: true };
function _simpleMainPromptStepId() {
  for (var i = 0; i < allSteps.length; i++) {
    var s = allSteps[i];
    if (s.triggered_by) continue;
    if (SIMPLE_MAIN_PROMPT_TYPES[s.type]) return s.id;
  }
  return null;
}
function syncSimpleModeStepVisibility() {
  var isSimple = getMode() === 'simple';
  var mainPromptId = isSimple ? _simpleMainPromptStepId() : null;
  allSteps.forEach(function (stepDef) {
    if (stepDef.triggered_by) return;
    var stepWrap = document.getElementById('ncf-step-wrap-' + stepDef.id);
    if (!stepWrap) return;
    if (!isSimple) { stepWrap.style.display = ''; return; }
    var keep = stepDef.type === 'action' || stepDef.id === mainPromptId;
    stepWrap.style.display = keep ? '' : 'none';
  });
  // The Advanced trigger is pinned into the footer (see renderAllSteps),
  // detached from whatever step (Parameters/workflow_params) it came from —
  // its owning step is never the action step or the main prompt, so Simple
  // mode always hid it before and should keep doing so now that it's lived
  // outside that step's own wrap.
  var pinnedAdv = document.querySelector('.ncf-advanced-row--pinned');
  if (pinnedAdv) pinnedAdv.style.display = isSimple ? 'none' : '';
}
document.addEventListener('ncf-mode-change', syncSimpleModeStepVisibility);

// Simple mode has no UI for llm_transform steps (level/flair/genre pickers,
// the rewritten-prompt textarea) — they still need to run, with their
// default values, before the actual image generation. Reuses the exact
// same runLLM() the hidden "Write" button would have called. Throws if a
// step fails to produce output, since runLLM itself only surfaces errors on
// its own (hidden) status line — the caller shows the error on the visible
// Generate status instead of silently submitting a blank prompt.
async function runPendingSimpleLLMSteps() {
  var llmSteps = allSteps.filter(function (s) {
    return s.type === 'llm_transform' && !s.triggered_by && s.output_mode !== 'prompt_cards';
  });
  for (var i = 0; i < llmSteps.length; i++) {
    var s = llmSteps[i];
    var refs = s._llmRefs;
    if (!refs || !refs.writeBtn) continue;
    var already = String(getVal(s.id, 'transformed_text') || '').trim();
    if (already) continue;
    await runLLM(s, refs.writeBtn, refs.writeLbl, refs.llmStatus, refs.outputTa);
    var produced = String(getVal(s.id, 'transformed_text') || '').trim();
    if (!produced) {
      throw new Error('Could not prepare the prompt (' + (s.label || s.id) + ' failed) — try Guided mode to see details.');
    }
  }
}

function resolveOutputTo() {
  allSteps.forEach(function (stepDef) {
    if (stepDef.type !== 'llm_transform' || !stepDef.output_to) return;
    // Check if output_to targets an ideogram_composer step
    var targetStep = allSteps.find(function (s) { return s.id === stepDef.output_to; });
    if (targetStep && targetStep.type === 'ideogram_composer') return; // handled in runLLM via _fillFn
    var targetTa = document.getElementById('ncf-input-' + stepDef.output_to);
    if (!targetTa || !stepDef._llmRefs) return;
    stepDef._llmRefs.outputTa = targetTa;
    // Wire input event so editing the target textarea also updates stepValues
    targetTa.addEventListener('input', function () {
      setVal(stepDef.id, 'transformed_text', targetTa.value.trim());
    });
  });
}

function revealTriggeredStep(stepId) {
  var wrap = document.getElementById('ncf-step-wrap-' + stepId);
  if (wrap) { wrap.style.display = ''; wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
}

// ══════════════════════════════════════════════════════════════════════════
// LLM CALL
// ══════════════════════════════════════════════════════════════════════════
var _NCF_SPIN_ICON = '<svg class="ncf-spin ncf-status-spin" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.5" stroke-dasharray="28 56" stroke-linecap="round"/></svg>';

// Shared "in progress" status renderer — spinning ring + text, used by every
// step that runs an async job (LLM write, generate image, upscale, refine,
// mix, pixel match…). Success/error states just overwrite via .textContent,
// which naturally clears the icon.
function _setBusyStatus(el, text) {
  if (!el) return;
  el.classList.add('is-busy');
  el.innerHTML = _NCF_SPIN_ICON + '<span>' + text + '</span>';
}

// Superqueue: when ComfyUI (or LM Studio) is busy on another computer, the
// server holds the request until the GPU is free. Without this the button just
// says "Composing…" for minutes and looks stuck. Polls while the request is in
// flight and shows what it is waiting for; returns a stop function.
function _watchGpuQueue(label, statusEl) {
  var t = function (key, fallback) {
    return (window.NomadI18n && window.NomadI18n.t) ? window.NomadI18n.t(key, fallback) : fallback;
  };
  var busyText = label ? label.textContent : '';
  var shown = false;
  var stopped = false;
  function tick() {
    if (stopped) return;
    fetch('/api/models/gpu/waiting', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) {
        if (stopped || !res) return;
        var item = (res.items || [])[0];
        if (item) {
          var msg = item.waitingFor === 'comfy'
            ? t('flow.queue.waitingComfy', 'Waiting for ComfyUI to finish…')
            : t('flow.queue.waitingLms', 'Waiting for LM Studio to finish…');
          if (!shown) busyText = label ? label.textContent : busyText;
          shown = true;
          if (label) label.textContent = msg;
          if (statusEl) statusEl.textContent = msg;
        } else if (shown) {
          shown = false;
          if (label) label.textContent = busyText;
        }
      })
      .catch(function () {})
      .then(function () { if (!stopped) setTimeout(tick, 1500); });
  }
  setTimeout(tick, 800);
  return function () { stopped = true; };
}

async function runLLM(stepDef, writeBtn, writeLbl, statusEl, outputTa) {
  isWritingScene = true;
  writeBtn.disabled = true;
  writeBtn.classList.add('is-composing');
  if (writeLbl) writeLbl.textContent = 'Composing…';
  // Swap the static icon for a spinning progress ring while busy — the
  // orange color alone was static; this makes "working" visibly dynamic.
  var _btnIcon = writeBtn.querySelector('.nss-btn-icon');
  if (_btnIcon) _btnIcon.style.display = 'none';
  // createElementNS is required here — plain createElement('svg') always
  // creates the element in the HTML namespace regardless of tag name, which
  // silently fails to render as an actual SVG (and its innerHTML <circle>
  // children never become real SVG shapes either).
  var _btnRing = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  _btnRing.setAttribute('class', 'nsc-ring nsc-ring--indeterminate nss-btn-ring');
  _btnRing.setAttribute('viewBox', '0 0 44 44');
  _btnRing.setAttribute('aria-hidden', 'true');
  _btnRing.innerHTML = '<circle class="nsc-ring-bg" cx="22" cy="22" r="18"/><circle class="nsc-ring-fill" cx="22" cy="22" r="18"/>';
  writeBtn.insertBefore(_btnRing, _btnIcon || writeBtn.firstChild);
  if (statusEl) {
    statusEl.classList.add('is-busy');
    statusEl.innerHTML = _NCF_SPIN_ICON + '<span>Calling LM Studio…</span>';
  }
  var _stopQueueWatch = _watchGpuQueue(writeLbl, statusEl);

  // Progress goes to the button as well as to statusEl, and that is the whole
  // point: statusEl is deliberately never added to the DOM (see
  // renderLLMTransform's comment about visual clutter), so every "Variation 3
  // of 6" written to it went nowhere. Asking for six scenes meant minutes with
  // no sign of life. The button is already changing state while it runs, so
  // putting the count in its label costs no layout at all — which is exactly
  // what Bulk Vision does, and it is the one batch flow that felt responsive.
  // The finally block restores the label, so nothing needs undoing here.
  function _progress(text) {
    if (statusEl) statusEl.textContent = text;
    if (writeLbl) writeLbl.textContent = text;
  }

  try {
    var input = resolveRef(stepDef.input_from) || '';
    var resolvedCtx = {};
    if (stepDef.context_from && typeof stepDef.context_from === 'object') {
      Object.keys(stepDef.context_from).forEach(function (k) {
        resolvedCtx[k] = resolveRef(stepDef.context_from[k]);
      });
    }

    var result = '';

    if (stepDef.calls === 'llm.story_continue') {
      var worldCtx = resolvedCtx.world_context || sessionState.world_context
        || getVal('world', 'prompt_text')
        || getVal('scene_prompt', 'prompt_text')
        || '';
      var history = Array.isArray(resolvedCtx.scene_history || sessionState.story_history)
        ? (resolvedCtx.scene_history || sessionState.story_history) : [];
      var instruction = input || '';
      var styleRef = resolvedCtx.civitai_style || undefined;

      var res = await fetch('/api/models/chat/studio-story', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          worldContext: worldCtx, storyHistory: history,
          instruction: instruction, level: selectedLevel, flair: flairValue,
          genre: selectedGenre || undefined,
          systemPrompt: stepDef.system_prompt || undefined,
          styleReference: styleRef,
          characterAnchor: sessionState.character_anchor || undefined,
        }),
      });
      var data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || 'LLM error');
      result = data.scene || '';
      // First turn derives the anchor; every turn after pins it — persisted
      // on sessionState so it survives across scene_gen calls for this story.
      if (data.anchor && !sessionState.character_anchor) sessionState.character_anchor = data.anchor;
      // This branch only ever runs for the very first scene of a story now
      // (every continuation after that goes through _submitStoryInstruction's
      // own sequential loop in flow-gallery.js) — stash the narrative summary
      // so showResultActions() can persist scene 1 to the story project JSON
      // once the image itself has actually been generated (see
      // story_project_service.py / append_story_project_scene).
      sessionState._pendingStoryNarrativeSummary = data.narrativeSummary || '';

    } else if (stepDef.calls === 'llm.studio_templateize') {
      var tplSys = stepDef.system_prompt || undefined;
      var tplUsr = resolveTpl(stepDef.user_prompt, { prompt: input }) || undefined;
      var tplRes = await fetch('/api/models/chat/studio-templateize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: input, systemPrompt: tplSys, userPrompt: tplUsr }),
      });
      var tplData = await tplRes.json();
      if (!tplRes.ok || tplData.error) throw new Error(tplData.error || 'Templateize error');
      result = tplData.template || '';

    } else if (stepDef.calls === 'llm.studio_enhance') {
      // Same options_group lookup llm.ideogram_compose already does below: a
      // flow whose poster_type group picks a kind (Posters: movie, gig, travel)
      // selects its system prompt by that kind. Assist and the rest declare no
      // such group, so the key stays empty and the level still decides.
      var enhType = _optGroupValues['poster_type'] ||
        (stepDef._paramValues && stepDef._paramValues.poster_type) || '';
      var enhSysPrompt = (stepDef.system_prompts && (
        (enhType && (stepDef.system_prompts[enhType + '_' + selectedLevel] ||
                     stepDef.system_prompts[enhType])) ||
        stepDef.system_prompts[selectedLevel])) || undefined;
      var enhRefPrompt = stepDef.context_from && stepDef.context_from.reference_prompt
        ? (resolveRef(stepDef.context_from.reference_prompt) || undefined)
        : undefined;
      var enhRes = await fetch('/api/models/chat/studio-enhance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: input, level: selectedLevel, flair: flairValue,
          systemPrompt: enhSysPrompt, referencePrompt: enhRefPrompt, thinkMode: assistThinkMode }),
      });
      var enhData = await enhRes.json();
      if (!enhRes.ok || enhData.error) throw new Error(enhData.error || 'Enhance error');
      result = enhData.enhancedPrompt || '';

    } else if (stepDef.calls === 'llm.edit_prompt') {
      // Rewrites an existing base prompt (context_from.current_prompt) using
      // a separate user instruction (input_from) — e.g. Describe Image: base
      // = the vision_describe output, instruction = the "idea" field. Reuses
      // the same /chat/edit-prompt endpoint the topbar chat edit-prompt
      // toggle already calls (flow-gallery.js), just wired as a normal
      // llm_transform step so any flow can declare it.
      var epCurrentPrompt = (stepDef.context_from && stepDef.context_from.current_prompt)
        ? (resolveRef(stepDef.context_from.current_prompt) || '')
        : '';
      if (!epCurrentPrompt) throw new Error('No base description to edit yet — describe the image first.');
      var epRes = await fetch('/api/models/chat/edit-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'single', instruction: input, currentPrompt: epCurrentPrompt, thinking: false }),
      });
      var epData = await epRes.json();
      if (!epRes.ok || epData.error) throw new Error(epData.error || 'Edit prompt error');
      var epEdited = String(epData.editedPrompt || '').trim();
      // Same echo-fallback the topbar chat uses: if the model just echoed the
      // instruction back, combine manually instead of losing the base prompt.
      result = (epEdited && epEdited.toLowerCase() !== String(input || '').toLowerCase())
        ? epEdited
        : ((epCurrentPrompt ? epCurrentPrompt + ', ' : '') + (input || ''));

    } else if (stepDef.calls === 'llm.studio_scenes') {
      var nParam = Math.max(1, Math.min(100,
        parseInt((stepDef._paramValues && stepDef._paramValues.n) ||
          (stepDef.params && stepDef.params.n && stepDef.params.n.default) || 6, 10) || 6));
      var scenesCtx = Object.assign({ n: nParam, idea: input }, stepDef._paramValues || {});
      var scenesSys = resolveTpl(stepDef.system_prompt, scenesCtx);
      var scenesUsr = resolveTpl(stepDef.user_prompt, scenesCtx);
      var scenesRes = await fetch('/api/models/chat/studio-scenes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          idea: input, n: nParam, level: selectedLevel, flair: flairValue,
          genre: selectedGenre || undefined,
          systemPrompt: scenesSys || undefined, userPrompt: scenesUsr || undefined,
          thinkMode: assistThinkMode,
        }),
      });
      var scenesData = await scenesRes.json();
      if (!scenesRes.ok || scenesData.error) throw new Error(scenesData.error || 'Scenes error');
      var scenesArr = Array.isArray(scenesData.scenes) ? scenesData.scenes : [];
      if (stepDef.output_mode === 'prompt_cards') {
        result = scenesArr;
      } else {
        result = scenesArr.join('\n---\n');
        setVal(stepDef.id, 'scenes', scenesArr);
      }
      if (scenesData.anchor) {
        setVal(stepDef.id, 'anchor', scenesData.anchor);
        _showScenesAnchor(stepDef.id, scenesData.anchor, scenesArr);
      }

    } else if (stepDef.calls === 'llm.studio_variations_json') {
      var vjN = Math.max(1, Math.min(20,
        parseInt((stepDef._paramValues && stepDef._paramValues.n) ||
          (stepDef.params && stepDef.params.n && stepDef.params.n.default) || 4, 10) || 4));
      var vjTemplate = (input && typeof input === 'object') ? input
        : (function () { try { return JSON.parse(String(input)); } catch (_) { return {}; } })();
      var vjSys = stepDef.system_prompt || '';
      var vjUsr = stepDef.user_prompt || '';
      var vjContinuous = !!stepDef.continuous_chat;
      var vjContinueMsg = stepDef.continue_message || '';
      var vjArr = [];
      for (var vji = 0; vji < vjN; vji++) {
        _progress('Variation ' + (vji + 1) + ' of ' + vjN + '…');
        var vjBody = { template: vjTemplate };
        if (vjSys) vjBody.systemPrompt = vjSys;
        if (vjUsr) vjBody.userPrompt = vjUsr;
        if (vjContinuous) {
          vjBody.continuousChat = true;
          vjBody.previousVariations = vjArr.slice();
          if (vjContinueMsg) vjBody.continueMessage = vjContinueMsg;
        }
        var vjRes = await fetch('/api/models/chat/studio-variations-json', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(vjBody),
        });
        var vjData = await vjRes.json();
        if (!vjRes.ok || vjData.error) throw new Error(vjData.error || 'Variations JSON error');
        // A variation identical to one already in the set is not a variation.
        // It happens: with the previous answers in the chat history the model
        // can lock onto its own last output and re-emit it verbatim, and the
        // loop used to accept that as one of your N. Spend one retry before
        // keeping it — the call is not free, but neither is a card that is a
        // byte-for-byte copy of the one beside it.
        if (vjData.variation && vjArr.indexOf(vjData.variation) !== -1) {
          _progress('Variation ' + (vji + 1) + ' of ' + vjN + ' — retrying…');
          var vjRetry = await fetch('/api/models/chat/studio-variations-json', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(vjBody),
          });
          var vjRetryData = await vjRetry.json();
          if (vjRetry.ok && !vjRetryData.error && vjRetryData.variation) vjData = vjRetryData;
        }
        if (vjData.variation) vjArr.push(vjData.variation);
      }
      result = vjArr;

    } else if (stepDef.calls === 'llm.studio_variations') {
      var vNParam = Math.max(1, Math.min(20,
        parseInt((stepDef._paramValues && stepDef._paramValues.n) ||
          (stepDef.params && stepDef.params.n && stepDef.params.n.default) || 4, 10) || 4));
      var vSys = resolveTpl(stepDef.system_prompt, { template: input });
      var vUsr = resolveTpl(stepDef.user_prompt, { template: input });
      var continuousChat = !!stepDef.continuous_chat;
      var continueMsg = stepDef.continue_message || '';
      var varArr = [];
      for (var vi = 0; vi < vNParam; vi++) {
        _progress('Variation ' + (vi + 1) + ' of ' + vNParam + '…');
        var reqBody = {
          template: input,
          systemPrompt: vSys || undefined, userPrompt: vUsr || undefined,
        };
        if (continuousChat) {
          reqBody.continuousChat = true;
          reqBody.previousVariations = varArr.slice();
          if (continueMsg) reqBody.continueMessage = continueMsg;
        }
        var varRes = await fetch('/api/models/chat/studio-variations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(reqBody),
        });
        var varData = await varRes.json();
        if (!varRes.ok || varData.error) throw new Error(varData.error || 'Variations error');
        if (varData.variation) varArr.push(varData.variation);
      }
      result = varArr;
    } else if (stepDef.calls === 'llm.ideogram_storyboard') {
      var sbSubject = resolveRef(stepDef.input_from) || '';
      var sbGridSize = (stepDef._paramValues && stepDef._paramValues['grid_size']) || '2×3';
      var sbStyle    = (stepDef._paramValues && stepDef._paramValues['style']) || 'cinematic photography';
      var sbSys = (stepDef.system_prompts && stepDef.system_prompts[sbStyle]) || '';
      if (!sbSys) throw new Error('No system prompt found for style: ' + sbStyle);
      if (!sbSubject) throw new Error('No subject text to generate storyboard from');

      _progress('Generating storyboard…');
      var sbRes = await fetch('/api/models/chat/studio-ideogram-storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject: sbSubject,
          gridSize: sbGridSize,
          systemPrompt: sbSys,
        }),
      });
      var sbData = await sbRes.json();
      if (!sbRes.ok || sbData.error) throw new Error(sbData.error || 'Storyboard generation failed');
      var sbJsonObj = sbData.ideogramJson || {};
      result = JSON.stringify(sbJsonObj, null, 2);

      // Feed into linked ideogram_composer step
      var sbTargetStep = stepDef.output_to && allSteps.find(function (s) { return s.id === stepDef.output_to; });
      if (sbTargetStep && sbTargetStep.type === 'ideogram_composer' && sbTargetStep._fillFn) {
        sbTargetStep._fillFn(result);
        setVal(stepDef.id, 'transformed_text', result);
        if (statusEl) statusEl.textContent = '✓ Storyboard ready — ' + sbData.panels + ' panels (' + sbData.gridSize + ')';
        updateGenerateBtn();
        return;
      }

    } else if (stepDef.calls === 'llm.ideogram_compose') {
      var idgInput = resolveRef(stepDef.input_from) || '';
      var idgFragments = String(idgInput).split(';').map(function (s) { return s.trim(); }).filter(Boolean);
      var idgLevel = selectedLevel || 'scene';
      var idgAspectLabel = (ASPECT_PRESETS[selectedAspectIdx] || {}).label || '1:1';
      // Reference image support — context_from may supply reference_image + ref_type
      var idgRefImage = resolvedCtx.reference_image || '';
      var idgRefType  = resolvedCtx.ref_type || 'character';

      // ── Two-phase charref diptych flow ────────────────────────────────────
      // Phase 1: vision pass → character description
      // Phase 2: scene compose (W×H standalone) → scene JSON
      // Phase 3 (JS): remap x coords to right panel, add left panel element
      var idgJsonObj = {};
      if (stepDef.diptych_charref && idgRefType === 'character' && idgRefImage && stepDef.system_prompts) {
        // Diptych geometry
        var _dd = getDims();
        var _dW = _dd.w, _dH = _dd.h;
        var _dS = Math.min(_dW, _dH);           // reference square side
        var _dCW = _dS + _dW;                    // full canvas width
        var _leftX = Math.round(_dS / _dCW * 1000); // boundary in 0-1000 space
        // Scene panel aspect ratio correction: y/x = W/H for standalone scene
        var _sceneFactor = +(_dW / _dH).toFixed(3);

        // ── Phase 1: vision only ─────────────────────────────────────────
        _progress('Analyzing reference…');
        var visRes = await fetch('/api/models/chat/studio-ideogram', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fragments: ['reference'],
            level: idgLevel,
            systemPrompt: ' ',
            canvasWidth: 1000, canvasHeight: 1000, aspectRatio: idgAspectLabel,
            referenceImageDataUrl: idgRefImage,
            referenceType: idgRefType,
            visionOnly: true,
          }),
        });
        var visData = await visRes.json();
        if (!visRes.ok || visData.error) throw new Error(visData.error || 'Vision pass failed');
        var charDesc = visData.characterDescription || '';

        // ── Phase 2: scene compose (standalone W×H) ──────────────────────
        _progress('Composing scene…');
        var sceneSys = stepDef.system_prompts[idgLevel] || stepDef.system_prompts['scene'] || '';
        // Inject OUTPUT DIMENSIONS for the scene panel (standalone W×H, no diptych)
        if (sceneSys) {
          sceneSys += '\n\nOUTPUT DIMENSIONS (scene panel — injected at runtime):' +
            '\n- Output image: ' + _dW + 'px × ' + _dH + 'px (aspect ratio ' + idgAspectLabel + ')' +
            '\n- Canvas is 1000×1000 normalized. Pixel ratio: ' + _dW + '×' + _dH + '.' +
            '\n- For a visually square element: y-extent / x-extent = ' + _sceneFactor +
            '\n- Full canvas bbox: [0, 0, 1000, 1000]  |  With margins: [20, 20, 980, 980]' +
            '\n- Example: 200-unit wide element → ~' + Math.round(200 * _sceneFactor) + ' units tall to appear square';
        }
        var sceneRes = await fetch('/api/models/chat/studio-ideogram', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fragments: idgFragments,
            level: idgLevel,
            systemPrompt: sceneSys,
            canvasWidth: 1000, canvasHeight: 1000, aspectRatio: idgAspectLabel,
            characterDescription: charDesc,
          }),
        });
        var sceneData = await sceneRes.json();
        if (!sceneRes.ok || sceneData.error) throw new Error(sceneData.error || 'Scene compose failed');
        var sceneJson = sceneData.ideogramJson || {};

        // ── Phase 3: programmatic diptych assembly ───────────────────────
        // Remap scene element x coords from [0,1000] → [_leftX, 1000]
        var _xScale = (1000 - _leftX) / 1000;
        var assembled = JSON.parse(JSON.stringify(sceneJson));
        var aEls = (assembled.compositional_deconstruction && assembled.compositional_deconstruction.elements) || [];
        function _remapXToRightPanel(el) {
          // Elements without bbox are valid (Ideogram spec) — skip remap, keep as-is
          if (!el.bbox) return;
          if (!Array.isArray(el.bbox) || el.bbox.length < 4) return;
          // BBOX format: [y_min, x_min, y_max, x_max]
          el.bbox[1] = Math.round(_leftX + el.bbox[1] * _xScale); // x_min → right panel
          el.bbox[3] = Math.round(_leftX + el.bbox[3] * _xScale); // x_max → right panel
        }
        aEls.forEach(_remapXToRightPanel);

        // Collect elements from alternative top-level keys the LLM sometimes uses
        // (e.g. "scene_elements", "objects", "items") — remap and merge them in
        var _altKeys = ['scene_elements', 'objects', 'items', 'components', 'layers', 'figures', 'scene_objects'];
        _altKeys.forEach(function (key) {
          var extras = assembled[key];
          if (!Array.isArray(extras)) return;
          extras.forEach(function (el) {
            if (!el || typeof el !== 'object') return;
            var copy = JSON.parse(JSON.stringify(el));
            if (!copy.type) copy.type = 'obj';
            _remapXToRightPanel(copy);
            aEls.push(copy);
          });
          delete assembled[key]; // remove non-standard key so output is clean
        });

        // Capture original scene descriptions before modifying
        var _origHld = assembled.high_level_description || '';
        var _origBg = (assembled.compositional_deconstruction && assembled.compositional_deconstruction.background) || '';

        // OBJ 1: left panel — reference character
        var _leftEl = {
          type: 'obj',
          bbox: [40, 20, 960, Math.max(20, _leftX - 20)],
          desc: charDesc
            ? charDesc + ' As seen in the reference photograph, in their original pose and setting.'
            : 'The reference character in their original pose and setting.',
        };

        // OBJ 2: scene anchor — defines full extent of right panel, environment only (no character to avoid duplication)
        var _sceneAnchorEl = {
          type: 'obj',
          bbox: [40, _leftX + 20, 960, 980],
          desc: _origBg,
        };

        // OBJ 3+: remapped sub-elements
        assembled.compositional_deconstruction.elements = [_leftEl, _sceneAnchorEl].concat(aEls);

        // Update high_level_description and background for diptych
        assembled.high_level_description =
          'A two-panel diptych: left panel — ' +
          (charDesc ? charDesc.substring(0, 300) + ' As seen in the reference photograph. ' : '') +
          'Right panel — ' + _origHld;
        if (assembled.compositional_deconstruction) {
          assembled.compositional_deconstruction.background =
            'Left panel: reference photo setting. Right panel: ' + _origBg;
        }
        idgJsonObj = assembled;

      } else {
        // ── Standard single-call compose (non-charref flows) ─────────────
        // If an options_group value is set (e.g. poster_type), look up composite key first:
        // e.g. "tv_series_scene" → fallback "scene". Allows fully differentiated prompts per type.
        var _posterType = _optGroupValues['poster_type'] || (stepDef._paramValues && stepDef._paramValues.poster_type);
        var _compositeKey = _posterType ? (_posterType + '_' + idgLevel) : null;
        var idgFlowSys = stepDef.system_prompts && (
          (_compositeKey && stepDef.system_prompts[_compositeKey]) ||
          stepDef.system_prompts[idgLevel] ||
          stepDef.system_prompts['scene']
        );
        var idgSys = idgFlowSys || _getActiveComposePromptText() || undefined;
        var idgBody = {
          fragments: idgFragments,
          level: idgLevel,
          systemPrompt: idgSys,
          canvasWidth: 1000,
          canvasHeight: 1000,
          aspectRatio: idgAspectLabel,
        };
        if (idgRefImage) {
          idgBody.referenceImageDataUrl = idgRefImage;
          idgBody.referenceType = idgRefType;
        }
        // Lettering elements support
        var idgLettering = resolvedCtx.lettering_elements;
        if (Array.isArray(idgLettering) && idgLettering.length) {
          idgBody.letteringElements = idgLettering;
        }
        var idgRes = await fetch('/api/models/chat/studio-ideogram', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(idgBody),
        });
        var idgData = await idgRes.json();
        if (!idgRes.ok || idgData.error) throw new Error(idgData.error || 'Ideogram compose error');
        idgJsonObj = idgData.ideogramJson || {};
      }
      result = JSON.stringify(idgJsonObj, null, 2);

      // Feed directly into the ideogram_composer step if output_to is set
      var idgTargetStep = stepDef.output_to && allSteps.find(function (s) { return s.id === stepDef.output_to; });
      if (idgTargetStep && idgTargetStep.type === 'ideogram_composer' && idgTargetStep._fillFn) {
        idgTargetStep._fillFn(result);
        setVal(stepDef.id, 'transformed_text', result);
        if (statusEl) statusEl.textContent = '✓ Composition ready — edit if needed';
        updateGenerateBtn();

        // Reference analysis feedback panel
        // charDesc is set in the two-phase charref path; idgData may be set in the standard path
        var _refDesc = (typeof charDesc !== 'undefined' && charDesc)
          ? charDesc
          : ((typeof idgData !== 'undefined' && idgData.referenceDescription) ? idgData.referenceDescription : '');
        var _refAnalyzed = !!_refDesc;
        var _hadRefImage = idgRefImage || (typeof idgBody !== 'undefined' && idgBody.referenceImageDataUrl);
        // statusEl is intentionally kept out of the DOM now (see renderLLMTransform)
        // to cut visual clutter, so this feedback panel has nothing to anchor to.
        if (statusEl && statusEl.parentNode) {
          var refPanelId = 'ncf-ref-analysis-' + stepDef.id;
          var existingPanel = document.getElementById(refPanelId);
          if (existingPanel) existingPanel.remove();
          if (_refAnalyzed) {
            var refPanel = document.createElement('details');
            refPanel.id = refPanelId;
            refPanel.style.cssText = 'margin-top:8px;font-size:11px;border:1px solid rgba(100,200,100,0.3);border-radius:6px;padding:6px 8px;background:rgba(0,255,100,0.04);';
            var refSum = document.createElement('summary');
            refSum.style.cssText = 'cursor:pointer;color:#4ade80;font-weight:600;list-style:none;';
            refSum.textContent = '✓ Reference analyzed';
            var refBody = document.createElement('p');
            refBody.style.cssText = 'margin:6px 0 0;color:rgba(255,255,255,0.55);line-height:1.5;white-space:pre-wrap;';
            refBody.textContent = _refDesc;
            refPanel.appendChild(refSum);
            refPanel.appendChild(refBody);
            statusEl.parentNode.insertBefore(refPanel, statusEl.nextSibling);
          } else if (_hadRefImage && !_refAnalyzed) {
            var warnEl = document.createElement('p');
            warnEl.id = refPanelId;
            warnEl.style.cssText = 'margin-top:8px;font-size:11px;color:#fbbf24;padding:6px 8px;border:1px solid rgba(251,191,36,0.3);border-radius:6px;background:rgba(251,191,36,0.05);';
            warnEl.textContent = '⚠ Reference image not analyzed — configure a vision model in Settings to enable character consistency';
            statusEl.parentNode.insertBefore(warnEl, statusEl.nextSibling);
          }
        }

        return; // skip generic output handling below
      }
    }

    // Generic output handling: array + output_mode:"prompt_cards" → editable cards
    if (stepDef.output_mode === 'prompt_cards' && Array.isArray(result)) {
      renderPromptCards(result, stepDef.id);
      if (statusEl) statusEl.textContent = '✓ ' + result.length + ' ready — edit if needed, then Generate Images';
    } else {
      if (outputTa) outputTa.value = result;
      setVal(stepDef.id, 'transformed_text', result);
      syncPrefillTargets(stepDef.id, 'transformed_text', result);
      if (statusEl) statusEl.textContent = '✓ Done — edit if needed';
    }
    updateGenerateBtn();

  } catch (err) {
    if (statusEl) statusEl.textContent = '✗ ' + (err.message || 'LLM error');
    showErrorToast(tF(stepDef.label || 'AI step') + ': ' + (err.message || 'something went wrong'));
    console.error('[FlowEngine] runLLM:', err);
  } finally {
    _stopQueueWatch();
    isWritingScene = false;
    writeBtn.disabled = false;
    writeBtn.classList.remove('is-composing');
    if (writeLbl) writeLbl.textContent = tF(stepDef.label || 'Write scene');
    if (statusEl) statusEl.classList.remove('is-busy');
    var _doneRing = writeBtn.querySelector('.nss-btn-ring');
    if (_doneRing) _doneRing.remove();
    var _doneIcon = writeBtn.querySelector('.nss-btn-icon');
    if (_doneIcon) _doneIcon.style.display = '';
  }
}

// Scenes ("+llm.studio_scenes") bakes a shared character/style anchor into
// every generated scene's prompt text for visual consistency — that text is
// otherwise only visible by opening each card individually. This surfaces
// the anchor plus a quick per-scene outline (each scene's text minus the
// anchor prefix) right under the step, so the whole generated "story" can be
// read/analyzed at a glance.
function _showScenesAnchor(stepId, anchorText, scenesArr) {
  var wrap = document.getElementById('ncf-step-wrap-' + stepId);
  if (!wrap) return;
  var box = document.getElementById('ncf-scenes-anchor-' + stepId);
  if (!box) {
    box = document.createElement('div');
    box.id = 'ncf-scenes-anchor-' + stepId;
    box.className = 'ncf-scenes-anchor';
    wrap.appendChild(box);
  }
  var html = '<p class="ncf-scenes-anchor-title">Character / style anchor</p>' +
    '<p class="ncf-scenes-anchor-text">' + escHtml(anchorText) + '</p>';
  if (Array.isArray(scenesArr) && scenesArr.length) {
    var anchorLower = anchorText.toLowerCase();
    var items = scenesArr.map(function (s, i) {
      var beat = s;
      if (s.toLowerCase().indexOf(anchorLower) === 0) beat = s.slice(anchorText.length).replace(/^[,\s]+/, '');
      return '<li>' + escHtml(beat || s) + '</li>';
    }).join('');
    html += '<p class="ncf-scenes-anchor-title">Story outline (' + scenesArr.length + ' scenes)</p>' +
      '<ol class="ncf-scenes-anchor-list">' + items + '</ol>';
  }
  box.innerHTML = html;
}

// ══════════════════════════════════════════════════════════════════════════
// IMAGE GENERATION
// ══════════════════════════════════════════════════════════════════════════

// Save a ComfyUI image to the server output dir so the Album can see it.
// Returns the Flask API URL for the saved file, or the original URL on failure.
async function saveFlowImage(imgUrl, comfyUrl, importId, positivePrompt, seedVal, params) {
  if (!window.openJourneyApi || typeof window.openJourneyApi.saveComfyImages !== 'function') return imgUrl;
  if (!imgUrl || !comfyUrl) return imgUrl;
  try {
    var u = new URL(imgUrl);
    var filename = u.searchParams.get('filename') || '';
    if (!filename) return imgUrl;
    var subfolder = u.searchParams.get('subfolder') || '';
    var type      = u.searchParams.get('type') || 'output';
    var metadata = {
      positive: String(positivePrompt || ''),
      seed:     String(seedVal || ''),
      source:   'nomad-flow',
      workflow: String(importId || ''),
    };
    if (params && typeof params === 'object') {
      try { metadata.params = JSON.stringify(params); } catch (_) {}
    }
    var saveRes = await window.openJourneyApi.saveComfyImages({
      comfyApiUrl:    comfyUrl,
      importId:       String(importId || ''),
      filenamePrefix: 'ns-flow',
      images: [{ filename: filename, subfolder: subfolder, type: type }],
      metadata: metadata,
    });
    var savedFilename = saveRes && Array.isArray(saveRes.savedFilenames) && saveRes.savedFilenames[0];
    if (savedFilename && window.openJourneyApi.getImageUrl) {
      return window.openJourneyApi.getImageUrl(savedFilename);
    }
  } catch (_) {}
  return imgUrl;
}

async function _submitOneImage(positivePrompt) {
  var isCustom = (getMode() === 'advanced');
  var dims = getDims();
  var seedVal = (isCustom && selectedSeed >= 0) ? selectedSeed : Math.floor(Math.random() * 0x7FFFFFFF);

  var prepRes = await fetch('/api/models/imports/prepare-queue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      basicValues:    { positive: positivePrompt, seed: seedVal, width: dims.w, height: dims.h, loraKeywordsOff: loraKeywordsOffList() },
      advancedValues: Object.assign({}, isCustom ? currentAdvOverrides : (selectedQualityValues || {}), isCustom ? {} : (selectedQuantizationValues || {}), isCustom ? {} : (selectedLoraValues || {}), _civitaiAdvancedOverrides),
      numImages:      1,
      targetImportId: selectedImportId,
    }),
  });
  var prepData = await prepRes.json();
  if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');

  var submitRes = await fetch(prepData.comfyApiUrl + '/prompt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prepData.workflow, client_id: prepData.clientId }),
  });
  var submitData = await submitRes.json();
  if (!submitRes.ok || submitData.error) throw new Error('Queue rejected');
  if (!submitData.prompt_id) throw new Error('ComfyUI did not return a prompt_id');

  var pendingCard = addGeneratingCard(generatedCount + 1, positivePrompt);
  var _params = buildParamsSnapshot({ kind: 'generate', positive: positivePrompt, seed: seedVal, width: dims.w, height: dims.h, workflowId: selectedImportId });
  var imgUrl = await waitForImage(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, pendingCard, 'Generating…');
  imgUrl = await saveFlowImage(imgUrl, prepData.comfyApiUrl, prepData.importId, positivePrompt, seedVal, _params);
  imgUrl = await _maybeUpscaleOutput(imgUrl, pendingCard);
  generatedCount++;
  addToFeed(imgUrl, generatedCount, pendingCard, _params);
  return imgUrl;
}

// ── Snapshot helpers ──────────────────────────────────────────────────────
// Capture the resolved inputs for an action flow at enqueue time, so a queued
// job runs with the same parameters even if the user changes the UI afterwards.
function _snapshotUpscale(stepDef) {
  var inputMap = stepDef.input_map || {};
  var imageDataUrl = resolveRef(inputMap['imageDataUrl']) || '';
  if (!imageDataUrl) return { __invalid: true };
  var promptRefine = resolveRef(inputMap['promptRefinement']) || '';
  return {
    imageDataUrl:   imageDataUrl,
    promptRefine:   promptRefine,
    upscaleModelId: resolveRef(inputMap['modelId']) || '',
    cardPrompt:     promptRefine || 'Upscaling…',
  };
}

function _snapshotRefine(stepDef) {
  var inputMap = stepDef.input_map || {};
  var imageDataUrl = resolveRef(inputMap['imageDataUrl']) || '';
  if (!imageDataUrl) return { __invalid: true };
  var paramsStep = allSteps.find(function (s) { return s.type === 'workflow_params'; });
  var promptText = resolveRef(inputMap['cardPrompt']) || '';
  var promptHistoryId = null; // used below to push to history on generate
  if (!promptText) {
    allSteps.forEach(function (s) {
      if (s.type === 'prompt_input' && !promptText) {
        var v = getVal(s.id, 'prompt_text');
        if (v) { promptText = v; promptHistoryId = s.id; }
      }
    });
  }
  // Refine flows keep the prompt as a "prompt_history" field inside their
  // workflow_params step (see flow-step-workflow-params.js) rather than a
  // standalone prompt_input step — check there too.
  if (!promptText && paramsStep && Array.isArray(paramsStep.fields)) {
    paramsStep.fields.forEach(function (f) {
      if (f.type === 'prompt_history' && !promptText) {
        var v = getVal(paramsStep.id, 'field_' + f.id);
        if (v) { promptText = v; promptHistoryId = paramsStep.id + '_' + f.id; }
      }
    });
  }

  // Multi-image support: if the source image_picker step holds more than one
  // image (stepDef.multiple), expose the full list so the caller can fan out
  // one refine job per image instead of just the primary one.
  var imageDataUrls = [imageDataUrl];
  var imgRef = String(inputMap['imageDataUrl'] || '');
  var imgStepId = imgRef.split('.')[1]; // "steps.image.output.image_data_url" → "image"
  if (imgStepId) {
    var multi = getVal(imgStepId, 'image_data_urls');
    if (Array.isArray(multi) && multi.length > 1) imageDataUrls = multi;
  }

  var advancedValues = resolveRef(inputMap['advancedValues']) || {};

  // Seed handling (same logic as Mix's _snapshotMix below): buildAdv()'s
  // "seed" branch (flow-step-workflow-params.js) just echoes back whatever
  // is stored in field_<id>, which is only randomized once when the field
  // is first created — with the "Visual similarity" toggle OFF (seed_mode
  // 'random'), every subsequent Generate reused that same stale value
  // instead of rolling a fresh one. Recomputed here, once per Generate
  // click, so ON keeps pinning the stored seed and OFF always sends a new
  // random one. ──────────────────────────────────────────────────────────
  if (paramsStep && Array.isArray(paramsStep.fields)) {
    paramsStep.fields.forEach(function (f) {
      if (f.seed_mode && f.adv_key) {
        var mode = getVal(paramsStep.id, 'seed_mode_' + f.id) || 'random';
        var cur  = Number(getVal(paramsStep.id, 'field_' + f.id)) || 0;
        var seed = mode === 'random' ? Math.floor(Math.random() * 0x7FFFFFFF) : cur;
        advancedValues[f.adv_key] = seed;
      }
    });
  }

  return {
    workflowFile:   resolveRef(inputMap['workflowFile']) || '',
    imageDataUrl:   imageDataUrl,
    imageDataUrls:  imageDataUrls,
    advancedValues: advancedValues,
    imageNodeId:      paramsStep ? (paramsStep.image_node || null) : null,
    promptText:       promptText,
    promptHistoryId:  promptHistoryId,
    cardPrompt:       promptText || 'Refining…',
  };
}

function _snapshotMix(stepDef) {
  var inputMap = stepDef.input_map || {};
  var imagesDef = inputMap['images'] || [];
  var images = imagesDef.map(function (e) {
    return { dataUrl: resolveRef(e.dataUrl) || '', nodeId: e.nodeId, optional: !!e.optional };
  });
  // An optional slot (e.g. Clothes Mix's reference photo) may stay empty —
  // updateGenerateBtn already required its textFallback to be filled before
  // Generate could be clicked at all, so an empty dataUrl here just means
  // "text-only, no reference image" rather than a missing required input.
  if (!images.every(function (e) { return !!e.dataUrl || e.optional; })) return { __invalid: true };

  var advancedValues = resolveRef(inputMap['advancedValues']) || {};

  // Seed handling (same logic as live run; computed once per enqueue)
  var paramsStep = allSteps.find(function (s) { return s.type === 'workflow_params'; });
  if (paramsStep && Array.isArray(paramsStep.fields)) {
    paramsStep.fields.forEach(function (f) {
      if (f.seed_mode && f.adv_key) {
        var mode = getVal(paramsStep.id, 'seed_mode_' + f.id) || 'random';
        var cur  = Number(getVal(paramsStep.id, 'field_' + f.id)) || 0;
        var seed;
        if (mode === 'random') {
          seed = Math.floor(Math.random() * 0x7FFFFFFF);
        } else if (mode === 'increment') {
          seed = cur;
          setVal(paramsStep.id, 'field_' + f.id, cur + 1);
          var inp = document.getElementById('ncf-seed-' + paramsStep.id + '-' + f.id);
          if (inp) inp.value = cur + 1;
        } else {
          seed = cur;
        }
        if (!advancedValues || typeof advancedValues !== 'object') advancedValues = {};
        advancedValues[f.adv_key] = seed;
      }
    });
  }

  var promptKey   = inputMap['promptKey']   || '';
  var promptValue = resolveRef(inputMap['promptValue']) || '';
  if (promptKey && promptValue) {
    if (!advancedValues || typeof advancedValues !== 'object') advancedValues = {};
    advancedValues[promptKey] = promptValue;
  }

  // issue #70: cardPrompt fell straight through to the bare 'Mix…' fallback
  // whenever it couldn't resolve (the composed {{subject}}/{{clothing}}
  // prompt_text, for flows that have one) — same convention every other
  // action step's fallback uses (_snapshotRefine's 'Refining…', Layer
  // Compose's 'Composing layers…'), but far less useful here since a Mix
  // flow's own "Who is the subject?"/"What is the clothing?" fields
  // (image_step/image_2_step's subject_input, flow_engine.py) almost always
  // have something typed even when there's no separate prompt step at all
  // — so try composing from those before giving up to the generic label.
  var subjectVal = String((typeof getVal === 'function' ? getVal('image', 'subject') : '') || '').trim();
  var clothingVal = String((typeof getVal === 'function' ? getVal('image_2', 'subject') : '') || '').trim();
  var composedFallback = [subjectVal, clothingVal].filter(Boolean).join(' · ');

  return {
    images:         images,
    advancedValues: advancedValues,
    workflowFile:   resolveRef(inputMap['workflowFile']) || inputMap['workflowFile'] || undefined,
    cardPrompt:     resolveRef(inputMap['cardPrompt']) || promptValue || composedFallback || 'Mix…',
  };
}

// ── Pixel Matcher snapshot ────────────────────────────────────────────────
function _snapshotPixelMatch(stepDef) {
  var inputMap = stepDef.input_map || {};
  var imageDataUrl = resolveRef(inputMap['imageDataUrl']) || '';
  if (!imageDataUrl) return { __invalid: true };
  // Pass advancedValues as-is — the addon backend reads whatever it needs.
  var advancedValues = resolveRef(inputMap['advancedValues']) || {};
  return {
    imageDataUrl:   imageDataUrl,
    advancedValues: advancedValues,
  };
}

// ── Pixel Matcher execution ───────────────────────────────────────────────
// The three "local" (non-ComfyUI) action runners below — _runPixelMatch,
// _runChromaKey, _runLayerCompose — each hit their own dedicated
// /api/models/*/process endpoint directly instead of going through
// openJourneyApi.saveComfyImages, the one function session-store.js wraps to
// auto-capture a generation's output into a pending Session (see its own
// captureImages()). Every ComfyUI-backed runner (_runRefine, _runMix,
// _runUpscale — via saveFlowImage) gets that for free; these three never
// did, so a Session created around one of them (or one added to an existing
// Session via "Add Flow") silently ended up with only its Create step and no
// second step for whatever this flow produced. Call this explicitly
// wherever one of the three addToFeed()s a fresh result.
// params: this run's buildParamsSnapshot() result, so the captured step
// carries something for "Apply params" to read — same as a ComfyUI-backed
// step gets via session-store.js's wrap() reading payload.metadata.params
// and stashing it on pending.flowParams *before* calling captureImages(),
// which is what actually copies pending.flowParams onto the new/updated
// step. These three never went through that wrapper, so pending.flowParams
// has to be set the same way here, by hand, right before captureImages().
function _captureIntoPendingSession(imgUrl, params) {
  if (!imgUrl || !window.NomadSession) return;
  var Session = window.NomadSession;
  if (params && typeof Session.getPending === 'function' && typeof Session.setPending === 'function') {
    var p = Session.getPending();
    if (p && p.sessionId) { p.flowParams = params; Session.setPending(p); }
  }
  if (typeof Session.captureImages === 'function') {
    try { Session.captureImages([imgUrl]); } catch (_) {}
  }
}

async function _runPixelMatch(stepDef, ctx) {
  var snap = (ctx && ctx.snapshot) || _snapshotPixelMatch(stepDef);
  if (snap.__invalid) throw new Error('No source image selected');

  _setBusyStatus(generateStatus, 'Processing…');

  var pendingCard = (ctx && ctx.card) ? ctx.card : addGeneratingCard(generatedCount + 1, 'Pixel art…');

  // Send imageDataUrl + all advancedValues directly — no hardcoded field mapping.
  var res = await fetch('/api/models/pixel-match/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ imageDataUrl: snap.imageDataUrl }, snap.advancedValues)),
  });
  var data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || 'Pixel match failed');

  var imgUrl = data.imageUrl;
  if (!imgUrl) throw new Error('No output image returned');

  var _params = buildParamsSnapshot({ kind: 'pixel-match', advancedValues: snap.advancedValues });
  setVal(stepDef.id, 'image_url', imgUrl);
  generatedCount++;
  addToFeed(imgUrl, generatedCount, pendingCard, _params);
  _captureIntoPendingSession(imgUrl, _params);
  showResultActions(stepDef);
  if (generateStatus) generateStatus.textContent = '✓ Pixel art ready';
  saveSessionSnapshot();
}

// ── Chroma Key snapshot ────────────────────────────────────────────────────
function _snapshotChromaKey(stepDef) {
  var inputMap = stepDef.input_map || {};
  var imageDataUrl = resolveRef(inputMap['imageDataUrl']) || '';
  if (!imageDataUrl) return { __invalid: true };
  // Pass advancedValues as-is — the addon backend reads whatever it needs.
  var advancedValues = resolveRef(inputMap['advancedValues']) || {};
  return {
    imageDataUrl:   imageDataUrl,
    advancedValues: advancedValues,
  };
}

// ── Chroma Key execution ───────────────────────────────────────────────────
async function _runChromaKey(stepDef, ctx) {
  var snap = (ctx && ctx.snapshot) || _snapshotChromaKey(stepDef);
  if (snap.__invalid) throw new Error('No source image selected');

  _setBusyStatus(generateStatus, 'Keying out background…');

  var pendingCard = (ctx && ctx.card) ? ctx.card : addGeneratingCard(generatedCount + 1, 'Chroma key…');

  var res = await fetch('/api/models/chroma-key/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ imageDataUrl: snap.imageDataUrl, save: true }, snap.advancedValues)),
  });
  var data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || 'Chroma key failed');

  var imgUrl = data.imageUrl;
  if (!imgUrl) throw new Error('No output image returned');

  var _params = buildParamsSnapshot({ kind: 'chroma-key', advancedValues: snap.advancedValues });
  setVal(stepDef.id, 'image_url', imgUrl);
  generatedCount++;
  addToFeed(imgUrl, generatedCount, pendingCard, _params);
  _captureIntoPendingSession(imgUrl, _params);
  showResultActions(stepDef);
  if (generateStatus) {
    generateStatus.textContent = data.warning ? '⚠ ' + data.warning : '✓ Background removed';
  }
  saveSessionSnapshot();
}

// ── Layer Composer snapshot ───────────────────────────────────────────────
function _snapshotLayerCompose(stepDef) {
  var inputMap = stepDef.input_map || {};
  var bgDataUrl = resolveRef(inputMap['bgDataUrl']) || '';
  var layerDataUrl = resolveRef(inputMap['layerDataUrl']) || '';
  if (!bgDataUrl || !layerDataUrl) return { __invalid: true };
  var transform = resolveRef(inputMap['transform']) || { x_frac: 0, y_frac: 0, w_frac: 0.3 };
  var lighting = resolveRef(inputMap['lighting']) || { brightness: 0, warmth: 0, hue: 0, match_enabled: false, match_strength: 0.3 };
  return {
    bgDataUrl:    bgDataUrl,
    layerDataUrl: layerDataUrl,
    transform:    transform,
    lighting:     lighting,
  };
}

// ── Layer Composer execution ──────────────────────────────────────────────
async function _runLayerCompose(stepDef, ctx) {
  var snap = (ctx && ctx.snapshot) || _snapshotLayerCompose(stepDef);
  if (snap.__invalid) throw new Error('Pick both a background and a layer image first');

  _setBusyStatus(generateStatus, 'Compositing…');

  var pendingCard = (ctx && ctx.card) ? ctx.card : addGeneratingCard(generatedCount + 1, 'Composing layers…');

  var res = await fetch('/api/models/layer-compose/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bgDataUrl:    snap.bgDataUrl,
      layerDataUrl: snap.layerDataUrl,
      transform:    snap.transform,
      lighting:     snap.lighting,
    }),
  });
  var data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || 'Layer compose failed');

  var imgUrl = data.imageUrl;
  if (!imgUrl) throw new Error('No output image returned');

  var _params = buildParamsSnapshot({ kind: 'layer-compose', advancedValues: Object.assign({}, snap.transform, { lighting: snap.lighting }) });
  setVal(stepDef.id, 'image_url', imgUrl);
  generatedCount++;
  addToFeed(imgUrl, generatedCount, pendingCard, _params);
  _captureIntoPendingSession(imgUrl, _params);
  showResultActions(stepDef);
  if (generateStatus) generateStatus.textContent = '✓ Layers composed';
  saveSessionSnapshot();
}

// ── Upscale execution ─────────────────────────────────────────────────────
async function _runUpscale(stepDef, ctx) {
  var snap = (ctx && ctx.snapshot) || _snapshotUpscale(stepDef);
  if (snap.__invalid) throw new Error('No source image selected');
  var imageDataUrl   = snap.imageDataUrl;
  var promptRefine   = snap.promptRefine;
  var upscaleModelId = snap.upscaleModelId;

  allSteps.forEach(function (s) {
    if (s.type === 'prompt_input') {
      var v = getVal(s.id, 'prompt_text');
      if (v) pushPromptHistory(s.id, v);
    }
  });

  _setBusyStatus(generateStatus, 'Preparing…');

  var prepRes = await fetch('/api/models/upscale/prepare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      imageDataUrl:     imageDataUrl,
      promptRefinement: promptRefine || undefined,
      modelId:          upscaleModelId || undefined,
    }),
  });
  var prepData = await prepRes.json();
  if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');

  var submitRes = await fetch(prepData.comfyApiUrl + '/prompt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prepData.workflow, client_id: prepData.clientId }),
  });
  var submitData = await submitRes.json();
  if (!submitRes.ok || submitData.error) throw new Error('Queue rejected');
  if (!submitData.prompt_id) throw new Error('ComfyUI did not return a prompt_id');

  var pendingCard = (ctx && ctx.card) ? ctx.card : addGeneratingCard(generatedCount + 1, promptRefine || 'Upscaling…');

  var _params = buildParamsSnapshot({ kind: 'upscale', prompt: promptRefine, promptRefine: promptRefine, upscaleModelId: upscaleModelId });
  var imgUrl = await waitForImage(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, pendingCard, 'Upscaling…');
  imgUrl = await saveFlowImage(imgUrl, prepData.comfyApiUrl, prepData.importId, promptRefine, 0, _params);
  if (!imgUrl) throw new Error('No output image returned from upscale');

  setVal(stepDef.id, 'image_url', imgUrl);
  generatedCount++;
  addToFeed(imgUrl, generatedCount, pendingCard, _params);

  showResultActions(stepDef);
  if (generateStatus) generateStatus.textContent = '✓ Upscaled';
  saveSessionSnapshot();
}

// ── Refine execution ──────────────────────────────────────────────────────
async function _runRemoveChecker_REMOVED(stepDef) {
  var inputMap  = stepDef.input_map || {};
  var imageDataUrl = resolveRef(inputMap['imageDataUrl']) || '';
  var tolerance    = parseInt(resolveRef(inputMap['tolerance']) || 30, 10);

  if (!imageDataUrl) throw new Error('No source image selected');

  if (generateStatus) generateStatus.textContent = 'Loading image…';

  // Load the image into an offscreen canvas
  var img = new Image();
  img.crossOrigin = 'anonymous';
  await new Promise(function (resolve, reject) {
    img.onload = resolve;
    img.onerror = function () { reject(new Error('Could not load image')); };
    img.src = imageDataUrl;
  });

  var W = img.naturalWidth, H = img.naturalHeight;
  if (!W || !H) throw new Error('Image has zero dimensions');

  var canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  var ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);

  var imageData = ctx.getImageData(0, 0, W, H);
  var d = imageData.data;

  if (generateStatus) generateStatus.textContent = 'Detecting checker pattern…';

  // ── Auto-detect checker square size ────────────────────────────────
  // JPEG compression creates soft gradients at square boundaries, so we
  // cannot rely on a simple colour-change threshold.  Instead we:
  //   1. Build a luminance profile along the first few rows (averaged for stability).
  //   2. Find all midpoint crossings (both rising and falling) — these sit
  //      reliably at the centre of each blurry boundary regardless of gradient width.
  //   3. Median spacing between consecutive crossings = one checker square size.
  //   4. Sample the two checker colours at the centres of the first two squares
  //      (well away from blurry edges) so we get "pure" reference colours.

  var PROBE = Math.min(8, H);
  var SCAN  = Math.min(1024, W);
  var lum = new Float32Array(SCAN);
  for (var sx = 0; sx < SCAN; sx++) {
    var sum = 0;
    for (var pr = 0; pr < PROBE; pr++) {
      var pi = (pr * W + sx) * 4;
      sum += (d[pi] + d[pi+1] + d[pi+2]) / 3;
    }
    lum[sx] = sum / PROBE;
  }

  var minL = 255, maxL = 0;
  for (var sx = 0; sx < SCAN; sx++) { if (lum[sx] < minL) minL = lum[sx]; if (lum[sx] > maxL) maxL = lum[sx]; }
  var midL = (minL + maxL) / 2;

  // All midpoint crossings (any direction)
  var crossings = [];
  for (var sx = 1; sx < SCAN; sx++) {
    if ((lum[sx-1] < midL) !== (lum[sx] < midL)) crossings.push(sx);
  }

  var detectedSize = 16; // fallback
  if (crossings.length >= 2) {
    var gaps = [];
    for (var ci = 0; ci + 1 < crossings.length; ci++) gaps.push(crossings[ci+1] - crossings[ci]);
    gaps.sort(function (a, b) { return a - b; });
    detectedSize = Math.max(4, gaps[Math.floor(gaps.length / 2)]);
  }

  // Sample checker colours at the centres of the first two squares
  // (at detectedSize/2 and 3*detectedSize/2), averaging a 10%-wide window
  var radius = Math.max(1, Math.round(detectedSize * 0.1));
  function sampleCheckerColor(cx) {
    var r = 0, g = 0, b = 0, n = 0;
    var x0 = Math.max(0, cx - radius), x1 = Math.min(W - 1, cx + radius);
    for (var sx2 = x0; sx2 <= x1; sx2++) {
      var i2 = sx2 * 4;
      r += d[i2]; g += d[i2+1]; b += d[i2+2]; n++;
    }
    return n > 0 ? [r/n, g/n, b/n] : [128, 128, 128];
  }
  var half = Math.round(detectedSize / 2);
  var col1 = sampleCheckerColor(half);
  var col2 = sampleCheckerColor(half * 3);
  var c1r = col1[0], c1g = col1[1], c1b = col1[2];
  var c2r = col2[0], c2g = col2[1], c2b = col2[2];

  // ── Apply alpha mask ────────────────────────────────────────────────
  if (generateStatus) generateStatus.textContent = 'Removing background…';

  var softMax = tolerance * 1.5;
  for (var y = 0; y < H; y++) {
    var sqY = Math.floor(y / detectedSize);
    for (var x = 0; x < W; x++) {
      var idx = (y * W + x) * 4;
      var pr = d[idx], pg = d[idx+1], pb = d[idx+2];

      var sqX = Math.floor(x / detectedSize);
      var useC1 = (sqX + sqY) % 2 === 0;
      var er = useC1 ? c1r : c2r;
      var eg = useC1 ? c1g : c2g;
      var eb = useC1 ? c1b : c2b;

      var dist = Math.sqrt((pr-er)*(pr-er) + (pg-eg)*(pg-eg) + (pb-eb)*(pb-eb));

      if (dist < tolerance) {
        d[idx + 3] = 0; // fully transparent
      } else if (dist < softMax) {
        // Soft edge: linear fade from 0 → 255
        d[idx + 3] = Math.round(((dist - tolerance) / (softMax - tolerance)) * 255);
      }
      // else: leave pixel fully opaque (original alpha)
    }
  }

  ctx.putImageData(imageData, 0, 0);
  var resultDataUrl = canvas.toDataURL('image/png');

  if (generateStatus) generateStatus.textContent = 'Saving…';

  // Save to output dir via server endpoint
  var saveRes = await fetch('/api/images/save-dataurl', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataUrl: resultDataUrl, prefix: 'ns-alpha' }),
  });
  var saveData = await saveRes.json();
  if (!saveRes.ok || saveData.error) throw new Error(saveData.error || 'Save failed');

  var imgUrl = saveData.url;
  var pendingCard = addGeneratingCard(generatedCount + 1, 'Remove checker background');
  generatedCount++;
  addToFeed(imgUrl, generatedCount, pendingCard);
  setVal(stepDef.id, 'image_url', imgUrl);
  if (generateStatus) generateStatus.textContent = '✓ Done — PNG with alpha ready';
  saveSessionSnapshot();
}

async function _runRefine(stepDef, ctx) {
  var snap = (ctx && ctx.snapshot) || _snapshotRefine(stepDef);
  if (snap.__invalid) throw new Error('No source image selected');
  var workflowFile   = snap.workflowFile;
  var imageDataUrl   = snap.imageDataUrl;
  var advancedValues = snap.advancedValues;
  var imageNodeId    = snap.imageNodeId;
  var promptText     = snap.promptText;
  if (snap.promptHistoryId && promptText) pushPromptHistory(snap.promptHistoryId, promptText);

  _setBusyStatus(generateStatus, 'Preparing…');

  var prepRes = await fetch('/api/models/refine/prepare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workflowFile:   workflowFile || undefined,
      imageDataUrl:   imageDataUrl,
      advancedValues: advancedValues,
      imageNodeId:    imageNodeId || undefined,
    }),
  });
  var prepData = await prepRes.json();
  if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');

  if (prepData.inputImageUrl && generateStatus) {
    // Keep the spinner (via _setBusyStatus) instead of replacing it with
    // plain text — "Ready" here was misleading since generation hasn't
    // actually started yet, this is just the upload-to-ComfyUI wait.
    _setBusyStatus(generateStatus, 'Uploading to ComfyUI…');
    var _viewInputLink = document.createElement('a');
    _viewInputLink.href = prepData.inputImageUrl;
    _viewInputLink.target = '_blank';
    _viewInputLink.rel = 'noopener';
    _viewInputLink.style.color = 'var(--accent)';
    _viewInputLink.style.marginLeft = '6px';
    _viewInputLink.textContent = 'view input image ↗';
    generateStatus.appendChild(_viewInputLink);
    await new Promise(function (r) { setTimeout(r, 2500); });
  }

  var submitRes = await fetch(prepData.comfyApiUrl + '/prompt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prepData.workflow, client_id: prepData.clientId }),
  });
  var submitData = await submitRes.json();
  if (!submitRes.ok || submitData.error) throw new Error('Queue rejected');
  if (!submitData.prompt_id) throw new Error('ComfyUI did not return a prompt_id');

  var pendingCard = (ctx && ctx.card) ? ctx.card : addGeneratingCard(generatedCount + 1, promptText || 'Refining…');

  var _params = buildParamsSnapshot({ kind: 'refine', prompt: promptText, advancedValues: advancedValues, workflowFile: workflowFile });
  var imgUrl = await waitForImage(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, pendingCard, 'Refining…');
  imgUrl = await saveFlowImage(imgUrl, prepData.comfyApiUrl, '', promptText, 0, _params);
  if (!imgUrl) throw new Error('No output image returned from refine');
  // Opt-in edge-fringing cleanup (Remove Background's "Clean edge fringing"
  // toggle) — runs on the already-saved result and re-persists the cleaned
  // PNG, so the defringed version is what actually lands in history.
  imgUrl = await _maybeDefringeImage(imgUrl, advancedValues, true);
  imgUrl = await _maybeUpscaleOutput(imgUrl, pendingCard);

  setVal(stepDef.id, 'image_url', imgUrl);
  generatedCount++;
  // 5th arg (beforeUrl) enables the before/after FadeCompare + share-with-
  // video option on this card. Every other addToFeed() call site omits it
  // and is unaffected — see addToFeed() in flow-gallery.js.
  addToFeed(imgUrl, generatedCount, pendingCard, _params, imageDataUrl);

  showResultActions(stepDef);
  if (generateStatus) generateStatus.textContent = '✓ Refined';
  saveSessionSnapshot();
}

async function _runMix(stepDef, ctx) {
  var snap = (ctx && ctx.snapshot) || _snapshotMix(stepDef);
  if (snap.__invalid) throw new Error('Please select both images first');
  var images         = snap.images;
  var advancedValues = snap.advancedValues;
  var cardPrompt     = snap.cardPrompt;
  var workflowFile   = snap.workflowFile;

  _setBusyStatus(generateStatus, 'Preparing…');

  var prepRes = await fetch('/api/models/mix/prepare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workflowFile:   workflowFile,
      images:         images,
      advancedValues: advancedValues,
    }),
  });
  var prepData = await prepRes.json();
  if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');

  var submitRes = await fetch(prepData.comfyApiUrl + '/prompt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prepData.workflow, client_id: prepData.clientId }),
  });
  var submitData = await submitRes.json();
  if (!submitRes.ok || submitData.error) throw new Error('Queue rejected');
  if (!submitData.prompt_id) throw new Error('ComfyUI did not return a prompt_id');

  var pendingCard = (ctx && ctx.card) ? ctx.card : addGeneratingCard(generatedCount + 1, cardPrompt);

  var imgUrl = await waitForImage(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, pendingCard, 'Generating…');
  imgUrl = await saveFlowImage(imgUrl, prepData.comfyApiUrl, '', cardPrompt, 0);
  if (!imgUrl) throw new Error('No output image returned');
  imgUrl = await _maybeUpscaleOutput(imgUrl, pendingCard);

  setVal(stepDef.id, 'image_url', imgUrl);
  generatedCount++;
  // quantizationId: same global the Advanced panel's INT8/FP8 picker sets
  // (buildQuantizationList, shared with Create/Refine) — just wasn't being
  // forwarded to addToFeed() here, so Mix cards never showed the badge
  // Create/Refine cards already do.
  addToFeed(imgUrl, generatedCount, pendingCard, {
    prompt: cardPrompt,
    quantizationId: selectedQuantizationId || '',
  });
  showResultActions(stepDef);
  if (generateStatus) generateStatus.textContent = '✓ Done';
  saveSessionSnapshot();
}

// ctx.card: an already-created card (from addGeneratingCard/_addQueuedCard)
// to update in place instead of creating a new one — the chat bar's own
// card, put up the instant it sends, before this function's two network
// round-trips (prepare-queue, then the actual ComfyUI submit) even start.
// Single-workflow, single-prompt path only (pi === 0) — chat never sends more
// than one prompt at a time.
async function runGenerate(stepDef, ctx) {
  isGenerating = true;
  // Reflect the enqueueable state (button stays enabled + relabels to "Enqueue")
  updateGenerateBtn();
  _setBusyStatus(generateStatus, 'Preparing…');

  if (stepDef.calls === 'generation.submit_upscale') {
    try {
      await _runUpscale(stepDef);
    } catch (err) {
      if (generateStatus) generateStatus.textContent = '✗ ' + (err.message || 'Upscale failed');
      console.error('[FlowEngine] _runUpscale:', err);
    } finally {
      isGenerating = false;
      updateGenerateBtn();
      _processQueue();
      if (generateStatus) generateStatus.classList.remove('is-busy');
    }
    return;
  }

  if (stepDef.calls === 'generation.submit_refine') {
    // Multi-image input: fan out to the queue (one job per image) instead of
    // running a single job synchronously, so every image gets its own card.
    var _refineSnap = _snapshotRefine(stepDef);
    if (_refineSnap && !_refineSnap.__invalid &&
        Array.isArray(_refineSnap.imageDataUrls) && _refineSnap.imageDataUrls.length > 1) {
      _enqueueAction(stepDef);
      isGenerating = false;
      updateGenerateBtn();
      _processQueue();
      if (generateStatus) generateStatus.classList.remove('is-busy');
      return;
    }
    try {
      await _runRefine(stepDef, { snapshot: _refineSnap });
    } catch (err) {
      if (generateStatus) generateStatus.textContent = '✗ ' + (err.message || 'Refine failed');
      console.error('[FlowEngine] _runRefine:', err);
    } finally {
      isGenerating = false;
      updateGenerateBtn();
      _processQueue();
      if (generateStatus) generateStatus.classList.remove('is-busy');
    }
    return;
  }

  if (stepDef.calls === 'generation.submit_mix') {
    try {
      await _runMix(stepDef);
    } catch (err) {
      if (generateStatus) generateStatus.textContent = '✗ ' + (err.message || 'Mix failed');
      console.error('[FlowEngine] _runMix:', err);
    } finally {
      isGenerating = false;
      updateGenerateBtn();
      _processQueue();
      if (generateStatus) generateStatus.classList.remove('is-busy');
    }
    return;
  }

  if (stepDef.calls === 'pixel_match.submit') {
    try {
      await _runPixelMatch(stepDef);
    } catch (err) {
      if (generateStatus) generateStatus.textContent = '✗ ' + (err.message || 'Pixel match failed');
      console.error('[FlowEngine] _runPixelMatch:', err);
    } finally {
      isGenerating = false;
      updateGenerateBtn();
      _processQueue();
      if (generateStatus) generateStatus.classList.remove('is-busy');
    }
    return;
  }

  if (stepDef.calls === 'layer_compose.submit') {
    try {
      await _runLayerCompose(stepDef);
    } catch (err) {
      if (generateStatus) generateStatus.textContent = '✗ ' + (err.message || 'Layer compose failed');
      console.error('[FlowEngine] _runLayerCompose:', err);
    } finally {
      isGenerating = false;
      updateGenerateBtn();
      _processQueue();
      if (generateStatus) generateStatus.classList.remove('is-busy');
    }
    return;
  }

  if (stepDef.calls === 'chroma_key.submit') {
    try {
      await _runChromaKey(stepDef);
    } catch (err) {
      if (generateStatus) generateStatus.textContent = '✗ ' + (err.message || 'Chroma key failed');
      console.error('[FlowEngine] _runChromaKey:', err);
    } finally {
      isGenerating = false;
      updateGenerateBtn();
      _processQueue();
      if (generateStatus) generateStatus.classList.remove('is-busy');
    }
    return;
  }

  var isCustom = (getMode() === 'advanced');
  var inputMap = stepDef.input_map || {};
  var _queueRefImageDataUrl = resolveRef(inputMap['imageDataUrl']) || '';
  var rawPositive = resolveRef(inputMap['basicValues.positive'])
    || getVal('scene_prompt', 'prompt_text')
    || getVal('world', 'prompt_text') || '';

  var prompts = Array.isArray(rawPositive) ? rawPositive.filter(Boolean) : [rawPositive];
  var dims = getDims();

  allSteps.forEach(function (s) {
    if (s.type === 'prompt_input') {
      var v = getVal(s.id, 'prompt_text');
      if (v) pushPromptHistory(s.id, v);
    }
  });

  var existingPromptCards = [];
  if (Array.isArray(rawPositive) && resultsGrid) {
    existingPromptCards = Array.from(resultsGrid.querySelectorAll('[data-prompt-card]'))
      .sort(function (a, b) { return Number(a.getAttribute('data-prompt-card')) - Number(b.getAttribute('data-prompt-card')); });
  }

  var workflowIds = (isCustom && getGlobalWorkflows().length > 0)
    ? getGlobalWorkflows()
    : [selectedImportId];
  var multiWorkflow = workflowIds.length > 1;

  // Diptych charref: compute canvas dimensions and node overrides.
  // Workflow canvas = [reference square s×s | output W×H] where s = min(W,H).
  var _diptychAdvOverrides = {};
  if (stepDef.diptych_charref) {
    var _dW = dims.w, _dH = dims.h;
    var _dS = Math.min(_dW, _dH);          // reference panel square side
    var _dCW = _dS + _dW;                  // total canvas width
    var _dCH = _dH;                        // total canvas height (= H, since H >= s)
    _diptychAdvOverrides = {
      'canvas_bg.width':    _dCW,          // EmptyImage — full diptych canvas
      'canvas_bg.height':   _dCH,
      'mask_canvas.width':  _dCW,          // SolidMask(0) — all-locked canvas mask
      'mask_canvas.height': _dCH,
      'mask_right.width':   _dW,           // SolidMask(1) — right output panel
      'mask_right.height':  _dH,
      'scale_ref.width':    _dS,           // ImageScale — reference → square s×s
      'scale_ref.height':   _dS,
      'crop_result.width':  _dW,           // ImageCrop — crop right output panel
      'crop_result.height': _dH,
      'crop_result.x':      _dS,           // crop starts after the reference square
      'sigmas.width':       _dCW,          // Ideogram4Scheduler — full canvas size
      'sigmas.height':      _dCH,
      'mask.x':             _dS,           // MaskComposite x offset — right panel starts at s
    };
  }

  try {
    if (!multiWorkflow) {
      // ── Single-workflow: sequential per prompt (original behaviour) ──────
      for (var pi = 0; pi < prompts.length; pi++) {
        var positivePrompt = prompts[pi];
        if (!positivePrompt) continue;
        _setBusyStatus(generateStatus, prompts.length > 1
          ? 'Generating ' + (pi + 1) + ' of ' + prompts.length + '…' : 'Preparing…');

        var seedVal;
        if (isCustom) {
          seedVal = selectedSeed >= 0 ? selectedSeed : Math.floor(Math.random() * 0x7FFFFFFF);
        } else if (similarityOn) {
          if (guidedFixedSeed < 0) guidedFixedSeed = Math.floor(Math.random() * 0x7FFFFFFF);
          seedVal = guidedFixedSeed;
        } else {
          seedVal = Math.floor(Math.random() * 0x7FFFFFFF);
        }

        var prepRes = await fetch('/api/models/imports/prepare-queue', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.assign({
            basicValues:    { positive: positivePrompt, seed: seedVal, width: dims.w, height: dims.h, loraKeywordsOff: loraKeywordsOffList() },
            advancedValues: Object.assign({}, isCustom ? (_wfAdvOverrides[workflowIds[0]] || {}) : (selectedQualityValues || {}), isCustom ? {} : (selectedQuantizationValues || {}), isCustom ? {} : (selectedLoraValues || {}), _civitaiAdvancedOverrides, _diptychAdvOverrides),
            numImages: 1, targetImportId: workflowIds[0],
          }, _queueRefImageDataUrl ? { imageDataUrl: _queueRefImageDataUrl } : {})),
        });
        var prepData = await prepRes.json();
        if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');

        var submitRes = await fetch(prepData.comfyApiUrl + '/prompt', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: prepData.workflow, client_id: prepData.clientId }),
        });
        var submitData = await submitRes.json();
        if (!submitRes.ok || submitData.error) {
          var ce = submitData.error;
          var errMsg = typeof ce === 'object' ? (ce.message || ce.type || JSON.stringify(ce)) : String(ce || 'Queue rejected');
          if (submitData.node_errors && Object.keys(submitData.node_errors).length)
            errMsg += ' — node errors: ' + Object.keys(submitData.node_errors).join(', ');
          throw new Error(errMsg);
        }
        if (!submitData.prompt_id) throw new Error('ComfyUI did not return a prompt_id');

        var pendingCard;
        if (existingPromptCards[pi]) {
          pendingCard = existingPromptCards[pi];
          pendingCard.setAttribute('data-status', 'generating');
          var dot = pendingCard.querySelector('.nss-card-status-dot');
          var lbl = pendingCard.querySelector('.nss-card-status-label');
          if (dot) dot.setAttribute('data-status', 'generating');
          if (lbl) lbl.textContent = 'generating…';
          // These prompt-editor cards (buildPromptCard) all got their
          // _genStartTime stamped together, in one synchronous loop, the
          // moment the whole scene batch's prompts came back from the LLM —
          // long before this per-scene generation loop actually starts each
          // one. Left as-is, every scene after the first would report
          // (its own time) PLUS (every prior scene's time), since elapsed is
          // measured from that shared original timestamp. Re-stamp it right
          // as this scene's own generation begins so its displayed duration
          // is just its own.
          pendingCard._genStartTime = Date.now();
        } else if (pi === 0 && ctx && ctx.card) {
          pendingCard = ctx.card;
        } else {
          pendingCard = addGeneratingCard(generatedCount + 1, positivePrompt);
        }
        var imgUrl = await waitForImage(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, pendingCard, 'Generating…');
        var _loopParams = buildParamsSnapshot({ kind: 'generate', positive: positivePrompt, seed: seedVal, width: dims.w, height: dims.h, workflowId: workflowIds[0] });
        imgUrl = await saveFlowImage(imgUrl, prepData.comfyApiUrl, prepData.importId, positivePrompt, seedVal, _loopParams);
        imgUrl = await _maybeUpscaleOutput(imgUrl, pendingCard);

        setVal(stepDef.id, 'image_url', imgUrl);
        generatedCount++;
        addToFeed(imgUrl, generatedCount, pendingCard, _loopParams);
        if (existingPromptCards[pi]) {
          var doneD = pendingCard.querySelector('.nss-card-status-dot');
          var doneL = pendingCard.querySelector('.nss-card-status-label');
          if (doneD) doneD.setAttribute('data-status', 'done');
          if (doneL) doneL.textContent = 'done';
        }
      }

    } else {
      // ── Multi-workflow: all prompts × all workflows in parallel ──────────
      _setBusyStatus(generateStatus, 'Launching ' + (prompts.length * workflowIds.length) + ' generations…');
      var parallelSeed = isCustom && selectedSeed >= 0 ? selectedSeed : Math.floor(Math.random() * 0x7FFFFFFF);
      var tasks = [];
      prompts.forEach(function (prompt) {
        if (!prompt) return;
        workflowIds.forEach(function (wfId) {
          generatedCount++;
          var card = addGeneratingCard(generatedCount, prompt);
          var cardNum = generatedCount;
          tasks.push(
            submitWorkflowAndWait(wfId, prompt, parallelSeed, card, dims).then(function (imgUrl) {
              setVal(stepDef.id, 'image_url', imgUrl);
              addToFeed(imgUrl, cardNum, card, card._params);
            })
          );
        });
      });
      await Promise.all(tasks);
    }

    if (stepDef.on_success) applyEffects(stepDef.on_success);
    showResultActions(stepDef);
    if (generateStatus) generateStatus.textContent = '✓ ' + generatedCount + ' generated';
    if (typeof saveSessionSnapshot === 'function') saveSessionSnapshot();

  } catch (err) {
    if (generateStatus) generateStatus.textContent = '✗ ' + (err.message || 'Generation failed');
    console.error('[FlowEngine] runGenerate:', err);
  } finally {
    isGenerating = false;
    updateGenerateBtn();
    _processQueue();
    if (generateStatus) generateStatus.classList.remove('is-busy');
  }
}

var RING_CIRC = 113.1; // 2π × r=18

