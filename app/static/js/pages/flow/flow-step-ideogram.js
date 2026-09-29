'use strict';
// Step: ideogram_composer → renderIdeogramComposer

function renderIdeogramComposer(stepDef, el) {
  var IDG_TYPE_COLORS = { obj: '#3b82f6', text: '#f59e0b', bg: '#10b981' };

  // ── Compact preview ────────────────────────────────────────────────────
  var preview = document.createElement('div');
  preview.className = 'ncf-idg-preview';
  preview.id = 'ncf-idg-preview-' + stepDef.id;

  var miniSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  miniSvg.setAttribute('viewBox', '0 0 1000 1000');
  miniSvg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  miniSvg.setAttribute('class', 'ncf-idg-mini-svg');
  miniSvg.id = 'ncf-idg-mini-svg-' + stepDef.id;
  var miniSvgBg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  miniSvgBg.setAttribute('width', '1000'); miniSvgBg.setAttribute('height', '1000');
  miniSvgBg.setAttribute('fill', '#1e1e1e'); miniSvgBg.setAttribute('rx', '8');
  miniSvg.appendChild(miniSvgBg);
  preview.appendChild(miniSvg);

  var previewMeta = document.createElement('div');
  previewMeta.className = 'ncf-idg-preview-meta';
  var metaCount = document.createElement('span');
  metaCount.className = 'ncf-idg-preview-count';
  metaCount.id = 'ncf-idg-count-' + stepDef.id;
  metaCount.textContent = tF('No composition yet');
  previewMeta.appendChild(metaCount);

  var pasteBtn = document.createElement('button');
  pasteBtn.type = 'button';
  pasteBtn.className = 'ncf-btn ncf-btn--ghost ncf-idg-paste-btn';
  pasteBtn.title = tF('Paste an Ideogram composition JSON generated externally');
  pasteBtn.innerHTML =
    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="width:13px;height:13px">' +
    '<rect x="4.5" y="1.5" width="7" height="2.5" rx="1"/>' +
    '<path d="M4.5 3h-2A1.5 1.5 0 001 4.5v9A1.5 1.5 0 002.5 15h11a1.5 1.5 0 001.5-1.5v-9A1.5 1.5 0 0013.5 3h-2"/>' +
    '</svg> Paste JSON';
  previewMeta.appendChild(pasteBtn);
  preview.appendChild(previewMeta);

  var pasteHint = mkHint('');
  pasteHint.className = 'nsc-step-hint ncf-idg-paste-hint';
  pasteHint.id = 'ncf-idg-paste-hint-' + stepDef.id;
  preview.appendChild(pasteHint);

  function _refreshPasteHint() {
    var dims = getDims();
    var cvH = Math.round(1000 * dims.h / dims.w);
    var ratioLabel = (ASPECT_PRESETS[selectedAspectIdx] || {}).label || '1:1';
    var txt = 'Pasting JSON: bboxes use a 1000 × 1000 coordinate space regardless of aspect ratio — x∈[0,1000], y∈[0,1000] for all formats.';
    pasteHint.textContent = txt;
    pasteBtn.title = txt;
  }
  _refreshPasteHint();
  pasteBtn.addEventListener('mouseenter', _refreshPasteHint);
  pasteBtn.addEventListener('focus', _refreshPasteHint);

  var editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'ncf-btn ncf-btn--secondary ncf-idg-edit-btn';
  editBtn.textContent = tF('Edit Composition');
  editBtn.disabled = true;
  preview.appendChild(editBtn);

  // ── Inline refine chat ─────────────────────────────────────────────────
  var refineArea = document.createElement('div');
  refineArea.className = 'ncf-idg-refine';
  refineArea.hidden = true;

  var refineTa = document.createElement('textarea');
  refineTa.className = 'ncf-idg-refine-input';
  refineTa.placeholder = tF('e.g. change the woman swimming in the water');
  refineTa.rows = 2;

  var refineRow = document.createElement('div');
  refineRow.className = 'ncf-idg-refine-row';

  var refineSendBtn = document.createElement('button');
  refineSendBtn.type = 'button';
  refineSendBtn.className = 'ncf-btn ncf-btn--secondary ncf-idg-refine-btn';
  refineSendBtn.textContent = tF('Refine');

  var refineStatus = document.createElement('span');
  refineStatus.className = 'ncf-idg-refine-status';

  refineRow.appendChild(refineSendBtn);
  refineRow.appendChild(refineStatus);
  refineArea.appendChild(refineTa);
  refineArea.appendChild(refineRow);
  preview.appendChild(refineArea);

  async function _runRefine() {
    var req = refineTa.value.trim();
    if (!req || !_idgModel) return;
    var linkedLLMStep = allSteps.find(function (s) { return s.type === 'llm_transform' && s.output_to === stepDef.id; });
    var level = selectedLevel || 'scene';
    var sys = linkedLLMStep && linkedLLMStep.system_prompts && (linkedLLMStep.system_prompts[level] || linkedLLMStep.system_prompts['scene']);
    if (!sys) { refineStatus.textContent = tF('No system prompt available'); return; }
    refineSendBtn.disabled = true;
    refineStatus.textContent = tF('Refining…');
    try {
      var res = await fetch('/api/models/chat/studio-ideogram-refine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ currentJson: _idgModel, changeRequest: req, systemPrompt: sys }),
      });
      var data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || 'Refine failed');
      stepDef._fillFn(JSON.stringify(data.ideogramJson));
      refineStatus.textContent = tF('✓ Updated');
      refineTa.value = '';
    } catch (e) {
      refineStatus.textContent = '✗ ' + e.message;
    } finally {
      refineSendBtn.disabled = false;
    }
  }

  refineSendBtn.addEventListener('click', _runRefine);
  refineTa.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); _runRefine(); }
  });

  el.appendChild(preview);

  // Internal JSON model (live, updated by modal edits)
  var _idgModel = null;

  // ── Fill function — set first so runLLM can call it even if modal wiring fails
  stepDef._fillFn = function (jsonString) {
    var parsed = null;
    // Both failure paths below used to be silent: a malformed response just
    // returned, and a response missing `compositional_deconstruction` threw
    // inside _sanitizeBboxes and was swallowed by runLLM. Either way the user
    // was left with a disabled Generate button and no explanation, with the
    // only trace in the browser console (#98). Report them the same way the
    // paste path already does.
    try { parsed = JSON.parse(jsonString); } catch (_) {
      _flashMetaCount('Model returned invalid JSON — run Compose again', true);
      return;
    }
    if (!parsed || typeof parsed !== 'object' || !parsed.compositional_deconstruction) {
      _flashMetaCount('Model left out "compositional_deconstruction" — run Compose again', true);
      return;
    }
    // Coerce string bboxes → arrays, drop conceptual/unparseable elements.
    // NOTE: no format detection here — the system prompt instructs the LLM to
    // output [x_min, y_min, x_max, y_max], so we trust it.  Detection only
    // runs in the paste path (user may paste external/Ideogram-native JSON).
    _sanitizeBboxes(parsed);
    if (!(parsed.compositional_deconstruction.elements || []).length) {
      _flashMetaCount('Composition came back with no usable elements — run Compose again', true);
      return;
    }
    _idgModel = parsed;
    // Update canvas viewBox to match current aspect ratio
    var dims = getDims();
    var cvH = Math.round(1000 * dims.h / dims.w);
    miniSvg.setAttribute('viewBox', '0 0 1000 ' + cvH);
    miniSvgBg.setAttribute('height', cvH);
    if (mainCanvas) {
      mainCanvas.setAttribute('viewBox', '0 0 1000 ' + cvH);
      if (mainCanvas.firstElementChild) mainCanvas.firstElementChild.setAttribute('height', cvH);
    }
    _renderMiniCanvas(parsed);
    var count = (parsed.compositional_deconstruction && parsed.compositional_deconstruction.elements || []).length;
    // Through _flashMetaCount, not a bare textContent assignment: the error
    // paths above paint this line red, and only _flashMetaCount clears the
    // colour again. Otherwise a failed Compose followed by a successful one
    // leaves "4 elements" showing in red.
    _flashMetaCount(count + ' element' + (count !== 1 ? 's' : ''), false);
    editBtn.disabled = false;
    refineArea.hidden = false;
    refineStatus.textContent = '';
    setVal(stepDef.id, 'ideogram_json', parsed);
    // transformed_text goes to ComfyUI — native [y_min, x_min, y_max, x_max] Ideogram format (no swap)
    setVal(stepDef.id, 'transformed_text', JSON.stringify(_modelForExport(parsed), null, 2));
    updateGenerateBtn();
  };

  // ── Paste external JSON (clipboard, falling back to a prompt dialog) ───
  function _flashMetaCount(text, isError) {
    metaCount.textContent = text;
    metaCount.style.color = isError ? 'var(--nss-red, #f87171)' : '';
  }

  // External JSONs may use raw pixel coordinates (eg. a 1920×1080 canvas) instead
  // of the normalized 0–1000 system.  Only rescale if values actually exceed 1000
  // in either axis — never touch already-normalized JSON (0–1000 range is valid even
  // on non-square canvases because the model always works in a 1000-unit space).
  function _normalizeIdgBboxes(model) {
    var elements = (model.compositional_deconstruction && model.compositional_deconstruction.elements) || [];
    if (!elements.length) return;
    var maxX = 0, maxY = 0;
    elements.forEach(function (el) {
      if (!Array.isArray(el.bbox) || el.bbox.length < 4) return;
      maxX = Math.max(maxX, +el.bbox[1] || 0, +el.bbox[3] || 0); // bbox[1]=x_min, bbox[3]=x_max
      maxY = Math.max(maxY, +el.bbox[0] || 0, +el.bbox[2] || 0); // bbox[0]=y_min, bbox[2]=y_max
    });
    if (maxX <= 0 || maxY <= 0) return;
    // Already within the normalized range — do not rescale
    if (maxX <= 1000 * 1.02 && maxY <= 1000 * 1.02) return;
    // Pixel coordinates: fit to 1000×1000 space
    var scale = Math.min(1000 / maxX, 1000 / maxY);
    elements.forEach(function (el) {
      if (!Array.isArray(el.bbox) || el.bbox.length < 4) return;
      el.bbox = el.bbox.map(function (v) { return Math.max(0, Math.round((+v || 0) * scale)); });
    });
  }

  // ── Sanitize raw bboxes from LLM output ───────────────────────────────────
  // LLMs sometimes emit bboxes as JSON strings ("[0,0,450,450]") or as
  // plain-language descriptions ("Center: Approx 450,450", "Overall Scene").
  // This pass coerces strings → arrays and drops elements whose bbox can't
  // be resolved to 4 finite numbers.
  function _sanitizeBboxes(model) {
    // The read below was already defensive, but the write-back at the end of
    // this function was not — so a model response missing
    // `compositional_deconstruction` threw "Cannot set properties of
    // undefined (setting 'elements')", runLLM swallowed it, and a perfectly
    // good 200 response was discarded with no user-visible error (#98).
    // Callers validate and report; this function's job is to never throw.
    var cd = model && model.compositional_deconstruction;
    if (!cd) return;
    if (!Array.isArray(cd.elements)) { cd.elements = []; return; }
    var elements = cd.elements;
    // Normalize bbox so that index 0 <= index 2 and index 1 <= index 3.
    // This works for both [y,x,y,x] and [x,y,x,y] formats: in either case
    // the first value in each pair (0,2) and (1,3) should be the smaller one.
    function _normPair(nums) {
      if (nums[0] > nums[2]) { var t0 = nums[0]; nums[0] = nums[2]; nums[2] = t0; }
      if (nums[1] > nums[3]) { var t1 = nums[1]; nums[1] = nums[3]; nums[3] = t1; }
      return nums;
    }
    cd.elements = elements.filter(function (el) {
      // No bbox at all — valid per Ideogram spec (position inferred from desc). Keep as-is.
      if (el.bbox === undefined || el.bbox === null) return true;
      // Already a valid array?
      if (Array.isArray(el.bbox) && el.bbox.length >= 4) {
        var nums = el.bbox.map(Number);
        if (nums.every(isFinite)) { el.bbox = _normPair(nums); return true; }
      }
      // String bbox — try JSON parse
      if (typeof el.bbox === 'string') {
        // Strip any wrapping quotes left by the LLM
        var s = el.bbox.trim().replace(/^"+|"+$/g, '');
        try {
          var arr = JSON.parse(s);
          if (Array.isArray(arr) && arr.length >= 4) {
            var nums2 = arr.map(Number);
            if (nums2.every(isFinite)) { el.bbox = _normPair(nums2); return true; }
          }
        } catch (_) { /* fall through */ }
        // Graceful fallback: extract the first 4 integers found in the string
        var ints = s.match(/-?\d+(\.\d+)?/g);
        if (ints && ints.length >= 4) {
          var nums3 = ints.slice(0, 4).map(Number);
          if (nums3.every(isFinite)) { el.bbox = _normPair(nums3); return true; }
        }
        // Unparseable string bbox — remove it so the element has no bbox
        delete el.bbox;
        return true;
      }
      // Invalid bbox of unknown type — drop the whole element
      console.warn('[IdgComposer] dropped element with unparseable bbox:', el.desc || el.type, el.bbox);
      return false;
    });
  }

  // ── Detect and normalize bbox format ──────────────────────────────────────
  // The Ideogram model and most LLMs output [y_min, x_min, y_max, x_max],
  // but our canvas works internally with [x_min, y_min, x_max, y_max].
  // This function detects which format the incoming JSON uses and converts
  // all bboxes to [x_min, y_min, x_max, y_max] for internal use.
  function _detectAndConvertBboxFormat(model) {
    var elements = (model.compositional_deconstruction && model.compositional_deconstruction.elements) || [];
    var valid = elements.filter(function (el) { return Array.isArray(el.bbox) && el.bbox.length >= 4; });
    if (!valid.length) return;

    var dims = getDims();
    var cvH = Math.round(1000 * dims.h / dims.w);

    // ── Hard signal: values > 1000 pin the tall axis ─────────────────────
    // On a portrait canvas (cvH > 1000), only y can legally exceed 1000.
    // If bbox[0] or bbox[2] exceed 1000 → those are y values → format is [y,x,y,x].
    // If bbox[1] or bbox[3] exceed 1000 → those are y values → format is [x,y,x,y].
    if (cvH !== 1000) {
      var yxyx_votes = 0, xyxy_votes = 0;
      valid.forEach(function (el) {
        var a = +el.bbox[0], b = +el.bbox[1], c = +el.bbox[2], d = +el.bbox[3];
        if (a > 1000 || c > 1000) yxyx_votes++;
        if (b > 1000 || d > 1000) xyxy_votes++;
      });
      if (yxyx_votes > xyxy_votes) { _swapBboxesYXYXtoXYXY(valid); return; }
      if (xyxy_votes > yxyx_votes) return; // already [x,y,x,y]
    }

    // ── Soft signal: keyword scoring from element descriptions ────────────
    // Check if positions implied by [y,x,y,x] match spatial keywords better.
    var yxyx_score = 0, xyxy_score = 0;
    var TOP_RE    = /\b(top|upper|above|header|title|heading)\b/i;
    var BOTTOM_RE = /\b(bottom|lower|below|footer|base)\b/i;
    var LEFT_RE   = /\b(left|western)\b/i;
    var RIGHT_RE  = /\b(right|eastern)\b/i;
    var WIDE_RE   = /\b(horizontal|banner|wide|strip|full.width|spanning|across)\b/i;
    var TALL_RE   = /\b(vertical|column|tall|side)\b/i;

    valid.forEach(function (el) {
      var desc = (el.desc || '') + ' ' + (el.text || '');
      var a = +el.bbox[0], b = +el.bbox[1], c = +el.bbox[2], d = +el.bbox[3];
      var midA = (a + c) / 2, midB = (b + d) / 2;
      var spanA = Math.abs(c - a), spanB = Math.abs(d - b);

      // [y,x,y,x] interpretation: a=y_min, b=x_min → midA=center_y, midB=center_x
      // [x,y,x,y] interpretation: a=x_min, b=y_min → midA=center_x, midB=center_y

      if (TOP_RE.test(desc))    { yxyx_score += (midA < 400) ? 1 : -1; xyxy_score += (midB < 400) ? 1 : -1; }
      if (BOTTOM_RE.test(desc)) { yxyx_score += (midA > 600) ? 1 : -1; xyxy_score += (midB > 600) ? 1 : -1; }
      if (LEFT_RE.test(desc))   { yxyx_score += (midB < 400) ? 1 : -1; xyxy_score += (midA < 400) ? 1 : -1; }
      if (RIGHT_RE.test(desc))  { yxyx_score += (midB > 600) ? 1 : -1; xyxy_score += (midA > 600) ? 1 : -1; }
      if (WIDE_RE.test(desc))   { yxyx_score += (spanB > spanA) ? 1 : -1; xyxy_score += (spanA > spanB) ? 1 : -1; }
      if (TALL_RE.test(desc))   { yxyx_score += (spanA > spanB) ? 1 : -1; xyxy_score += (spanB > spanA) ? 1 : -1; }
    });

    if (yxyx_score > xyxy_score) { _swapBboxesYXYXtoXYXY(valid); return; }
    // If tied or xyxy wins, leave as-is (already [x,y,x,y] or indeterminate)
    // Default assumption for tied/no-signal: treat as [y,x,y,x] (Ideogram's native format)
    if (yxyx_score === xyxy_score) _swapBboxesYXYXtoXYXY(valid);
  }

  // Convert bboxes in-place from [y_min, x_min, y_max, x_max] → [x_min, y_min, x_max, y_max]
  function _swapBboxesYXYXtoXYXY(elements) {
    elements.forEach(function (el) {
      if (!Array.isArray(el.bbox) || el.bbox.length < 4) return;
      var tmp = el.bbox.slice();
      el.bbox = [tmp[1], tmp[0], tmp[3], tmp[2]]; // [x_min, y_min, x_max, y_max]
    });
  }

  // Build a model clone for export to ComfyUI.
  // The ComfyUI Ideogram 4 model uses the same [x_min, y_min, x_max, y_max] format
  // as the internal representation, so no conversion is needed.
  // (The official Ideogram HTTP API uses [y_min, x_min, y_max, x_max], but the
  //  ComfyUI local model does NOT — confirmed via the workflow default examples.)
  function _modelForExport(model) {
    return JSON.parse(JSON.stringify(model));
  }

  pasteBtn.addEventListener('click', async function () {
    _refreshPasteHint();
    var text = '';
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        text = await navigator.clipboard.readText();
      }
    } catch (_) { /* permission denied / unsupported — fall back to prompt */ }
    if (!text || !text.trim()) {
      text = window.prompt(tF('Paste Ideogram composition JSON:')) || '';
    }
    text = text.trim();
    if (!text) return;

    var parsed;
    try {
      parsed = JSON.parse(text);
    } catch (_) {
      _flashMetaCount('Invalid JSON — paste failed', true);
      return;
    }
    if (!parsed || typeof parsed !== 'object' || !parsed.compositional_deconstruction) {
      _flashMetaCount('Not an Ideogram composition JSON', true);
      return;
    }
    _normalizeIdgBboxes(parsed);
    // Pasted JSON is expected in [y_min, x_min, y_max, x_max] (Ideogram native).
    // Only sanitize (coerce string bboxes, drop bad ones) — no format conversion.
    _sanitizeBboxes(parsed);
    stepDef._fillFn(JSON.stringify(parsed));
  });

  // ── Mini canvas renderer ───────────────────────────────────────────────
  function _renderMiniCanvas(model) {
    // Remove all rects except background
    while (miniSvg.childNodes.length > 1) miniSvg.removeChild(miniSvg.lastChild);
    if (!model || !model.compositional_deconstruction) return;
    // bbox coords are always 0-1000 for both axes; scale y to fit the viewBox height (aspect ratio)
    var _mvbH = parseFloat((miniSvg.getAttribute('viewBox') || '0 0 1000 1000').split(' ')[3]) || 1000;
    var _mscaleY = _mvbH / 1000;
    var elements = model.compositional_deconstruction.elements || [];
    elements.forEach(function (el) {
      if (!Array.isArray(el.bbox) || el.bbox.length < 4) return;
      var r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      // Ideogram format: [y_min, x_min, y_max, x_max] — y scaled to viewBox, x stays 0-1000
      var y1 = el.bbox[0] * _mscaleY, x1 = el.bbox[1], y2 = el.bbox[2] * _mscaleY, x2 = el.bbox[3];
      r.setAttribute('x', Math.min(x1, x2)); r.setAttribute('y', Math.min(y1, y2));
      r.setAttribute('width', Math.abs(x2 - x1)); r.setAttribute('height', Math.abs(y2 - y1));
      r.setAttribute('fill', (IDG_TYPE_COLORS[el.type] || '#888') + '33');
      r.setAttribute('stroke', IDG_TYPE_COLORS[el.type] || '#888');
      r.setAttribute('stroke-width', '6'); r.setAttribute('rx', '4');
      miniSvg.appendChild(r);
    });
  }

  // ── Modal wiring ───────────────────────────────────────────────────────
  var modalEl   = document.getElementById('ncf-ideogram-modal');
  var modalClose = document.getElementById('ncf-ideogram-modal-close');
  var modalApply = document.getElementById('ncf-ideogram-modal-apply');
  var jsonToggle = document.getElementById('ncf-idg-json-toggle');
  var visualEl  = document.getElementById('ncf-idg-visual');
  var rawEl     = document.getElementById('ncf-idg-raw');
  var rawTa     = document.getElementById('ncf-idg-raw-ta');
  var rawStatus = document.getElementById('ncf-idg-raw-status');
  var cardsPanel = document.getElementById('ncf-idg-cards-panel');
  var mainCanvas = document.getElementById('ncf-idg-canvas');
  var canvasWrap = document.getElementById('ncf-idg-canvas-wrap');
  var headerActions = modalEl && modalEl.querySelector('.ncf-idg-header-actions');

  var _hasModal = !!(modalEl && jsonToggle && rawTa && cardsPanel && mainCanvas);

  // "Select All" — group move/scale toggle, injected next to the Raw JSON button
  var selectAllBtn = document.getElementById('ncf-idg-selectall-btn');
  if (_hasModal && headerActions && !selectAllBtn) {
    selectAllBtn = document.createElement('button');
    selectAllBtn.type = 'button';
    selectAllBtn.id = 'ncf-idg-selectall-btn';
    selectAllBtn.className = 'ncf-btn ncf-btn--ghost ncf-idg-selectall-btn';
    selectAllBtn.title = tF('Select all elements to move or scale them together');
    selectAllBtn.textContent = tF('Select All');
    headerActions.insertBefore(selectAllBtn, jsonToggle);
  }

  // Zoom controls — injected into the canvas panel, next to the drag/resize hint
  var zoomBar = null, zoomOutBtn = null, zoomInBtn = null, zoomResetBtn = null, zoomLabel = null;
  var canvasHintEl = modalEl && modalEl.querySelector('.ncf-idg-canvas-hint');
  if (_hasModal && canvasHintEl && !document.getElementById('ncf-idg-zoom-bar')) {
    zoomBar = document.createElement('div');
    zoomBar.className = 'ncf-idg-zoom-bar';
    zoomBar.id = 'ncf-idg-zoom-bar';
    zoomOutBtn = document.createElement('button');
    zoomOutBtn.type = 'button';
    zoomOutBtn.className = 'ncf-idg-zoom-btn';
    zoomOutBtn.textContent = '−';
    zoomOutBtn.title = tF('Zoom out');
    zoomLabel = document.createElement('span');
    zoomLabel.className = 'ncf-idg-zoom-label';
    zoomLabel.textContent = '100%';
    zoomInBtn = document.createElement('button');
    zoomInBtn.type = 'button';
    zoomInBtn.className = 'ncf-idg-zoom-btn';
    zoomInBtn.textContent = '+';
    zoomInBtn.title = tF('Zoom in');
    zoomResetBtn = document.createElement('button');
    zoomResetBtn.type = 'button';
    zoomResetBtn.className = 'ncf-idg-zoom-btn ncf-idg-zoom-reset';
    zoomResetBtn.textContent = tF('Reset');
    zoomResetBtn.title = tF('Reset zoom');
    zoomBar.appendChild(zoomOutBtn);
    zoomBar.appendChild(zoomLabel);
    zoomBar.appendChild(zoomInBtn);
    zoomBar.appendChild(zoomResetBtn);
    canvasHintEl.parentNode.insertBefore(zoomBar, canvasHintEl);
  } else {
    zoomBar = document.getElementById('ncf-idg-zoom-bar');
    if (zoomBar) {
      zoomOutBtn = zoomBar.querySelector('.ncf-idg-zoom-btn:nth-child(1)');
      zoomLabel = zoomBar.querySelector('.ncf-idg-zoom-label');
      zoomInBtn = zoomBar.querySelector('.ncf-idg-zoom-btn:nth-child(3)');
      zoomResetBtn = zoomBar.querySelector('.ncf-idg-zoom-reset');
    }
  }

  var ZOOM_MIN = 0.5, ZOOM_MAX = 3, ZOOM_STEP = 0.25;
  var _zoomLevel = 1;
  function _applyZoom() {
    if (!mainCanvas) return;
    mainCanvas.style.transform = _zoomLevel === 1 ? '' : 'scale(' + _zoomLevel + ')';
    if (canvasWrap) canvasWrap.classList.toggle('is-zoomed', _zoomLevel !== 1);
    if (zoomLabel) zoomLabel.textContent = Math.round(_zoomLevel * 100) + '%';
    if (zoomOutBtn) zoomOutBtn.disabled = _zoomLevel <= ZOOM_MIN;
    if (zoomInBtn) zoomInBtn.disabled = _zoomLevel >= ZOOM_MAX;
  }
  function _setZoom(level) {
    _zoomLevel = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, +level.toFixed(2)));
    _applyZoom();
  }
  if (zoomOutBtn)   zoomOutBtn.addEventListener('click', function () { _setZoom(_zoomLevel - ZOOM_STEP); });
  if (zoomInBtn)    zoomInBtn.addEventListener('click', function () { _setZoom(_zoomLevel + ZOOM_STEP); });
  if (zoomResetBtn) zoomResetBtn.addEventListener('click', function () { _setZoom(1); });

  var _rawMode = false;
  var _activeCardIdx = -1;
  var _selectAllMode = false;
  var _dragState = null;  // { elIdx, startX, startY, origBbox, mode: 'move'|'resize', handle }
  var _groupDrag = null;  // { mode: 'move'|'resize', handle, startX, startY, origGroup: [x1,y1,x2,y2], origBboxes: [...] }

  function _setSelectAllMode(on) {
    _selectAllMode = on;
    if (selectAllBtn) selectAllBtn.classList.toggle('ncf-btn--active', on);
    if (on) {
      _activeCardIdx = -1;
      document.querySelectorAll('.ncf-idg-card').forEach(function (c) { c.classList.remove('ncf-idg-card--active'); });
    }
    _renderMainCanvas(_idgModel);
  }
  if (selectAllBtn) selectAllBtn.addEventListener('click', function () { _setSelectAllMode(!_selectAllMode); });

  // -- Toggle raw/visual --
  function _setRawMode(on) {
    if (!_hasModal) return;
    _rawMode = on;
    jsonToggle.textContent = on ? 'Visual' : 'Raw JSON';
    jsonToggle.classList.toggle('ncf-btn--active', on);
    rawEl.hidden = !on;
    visualEl.hidden = on;
    if (on && _idgModel) {
      rawTa.value = JSON.stringify(_idgModel, null, 2);
      rawStatus.textContent = '';
    }
  }

  if (_hasModal) jsonToggle.addEventListener('click', function () { _setRawMode(!_rawMode); });

  if (_hasModal) rawTa.addEventListener('input', function () {
    try {
      var p = JSON.parse(rawTa.value);
      _idgModel = p;
      rawStatus.textContent = tF('✓ Valid JSON');
      rawStatus.style.color = 'var(--nss-green, #4ade80)';
      _renderVisual(p);
    } catch (_) {
      rawStatus.textContent = tF('✗ Invalid JSON');
      rawStatus.style.color = 'var(--nss-red, #f87171)';
    }
  });

  // -- Visual rendering (modal canvas + cards) --
  function _renderVisual(model) {
    if (!model) return;
    _renderMainCanvas(model);
    _renderCards(model);
  }

  // ── Main canvas ────────────────────────────────────────────────────────
  function _renderMainCanvas(model) {
    while (mainCanvas.childNodes.length > 1) mainCanvas.removeChild(mainCanvas.lastChild);
    var _vbH = parseFloat((mainCanvas.getAttribute('viewBox') || '0 0 1000 1000').split(' ')[3]) || 1000;
    // bbox coords are always 0-1000 for both axes; scale y to viewBox height for display only
    var _scaleY = _vbH / 1000;
    if (mainCanvas.firstElementChild) mainCanvas.firstElementChild.setAttribute('height', _vbH);
    if (!model || !model.compositional_deconstruction) return;
    var elements = model.compositional_deconstruction.elements || [];
    // Render bg types first so they sit below obj/text in SVG z-order
    var TYPE_ORDER = { bg: 0, obj: 1, text: 2 };
    var sorted = elements
      .map(function (el, i) { return { el: el, idx: i }; })
      .sort(function (a, b) { return (TYPE_ORDER[a.el.type] || 1) - (TYPE_ORDER[b.el.type] || 1); });
    sorted.forEach(function (item) {
      var elem = item.el; var idx = item.idx;
      if (!Array.isArray(elem.bbox) || elem.bbox.length < 4) return;
      // Ideogram format: [y_min, x_min, y_max, x_max] — y scaled to viewBox, x stays 0-1000
      var y1 = elem.bbox[0] * _scaleY, x1 = elem.bbox[1], y2 = elem.bbox[2] * _scaleY, x2 = elem.bbox[3];
      var color = IDG_TYPE_COLORS[elem.type] || '#888';
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('data-idx', idx);
      g.style.cursor = 'move';

      // Main rect
      var r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      r.setAttribute('x', x1); r.setAttribute('y', y1);
      r.setAttribute('width', x2 - x1); r.setAttribute('height', y2 - y1);
      r.setAttribute('fill', color + '22');
      r.setAttribute('stroke', color);
      r.setAttribute('stroke-width', idx === _activeCardIdx ? '8' : '4');
      r.setAttribute('rx', '6');
      r.setAttribute('class', 'ncf-idg-main-rect');
      g.appendChild(r);

      // Label
      var lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lbl.setAttribute('x', x1 + 12); lbl.setAttribute('y', y1 + 30);
      lbl.setAttribute('fill', color); lbl.setAttribute('font-size', '28');
      lbl.setAttribute('font-family', 'monospace'); lbl.setAttribute('font-weight', 'bold');
      lbl.setAttribute('pointer-events', 'none');
      lbl.textContent = (idx + 1) + ' ' + (elem.type || 'obj').toUpperCase();
      g.appendChild(lbl);

      // Corner resize handles (8px visual, 40px hit area) — y already in SVG space
      var handles = [[x1,y1,'nw'],[x2,y1,'ne'],[x1,y2,'sw'],[x2,y2,'se']];
      handles.forEach(function (h) {
        var hit = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        hit.setAttribute('x', h[0] - 20); hit.setAttribute('y', h[1] - 20);
        hit.setAttribute('width', 40); hit.setAttribute('height', 40);
        hit.setAttribute('fill', 'transparent');
        hit.setAttribute('cursor', h[2] + '-resize');
        hit.setAttribute('data-handle', h[2]);
        hit.setAttribute('data-idx', idx);
        hit.addEventListener('mousedown', _onHandleMouseDown);
        g.appendChild(hit);

        var dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        dot.setAttribute('cx', h[0]); dot.setAttribute('cy', h[1]); dot.setAttribute('r', '8');
        dot.setAttribute('fill', color); dot.setAttribute('pointer-events', 'none');
        g.appendChild(dot);
      });

      // In select-all mode every element drags as a group; otherwise only the active one is interactive
      if (_selectAllMode) {
        r.addEventListener('mousedown', _onGroupRectMouseDown);
      } else if (idx === _activeCardIdx) {
        r.addEventListener('mousedown', function (ev) { _onRectMouseDown(ev, idx); });
      } else {
        g.style.pointerEvents = 'none';
        g.style.opacity = '0.45';
      }

      mainCanvas.appendChild(g);
    });

    // Group overlay — dashed union bbox with corner handles to move/scale every element together
    if (_selectAllMode) {
      var group = _groupBbox(model);
      if (group) {
        // group = [x_min, y_min, x_max, y_max] in 0-1000 space — scale y for SVG display
        var gx1 = group[0], gy1 = group[1] * _scaleY, gx2 = group[2], gy2 = group[3] * _scaleY;
        var overlay = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        overlay.setAttribute('class', 'ncf-idg-group-overlay');

        var orect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        orect.setAttribute('x', gx1); orect.setAttribute('y', gy1);
        orect.setAttribute('width', gx2 - gx1); orect.setAttribute('height', gy2 - gy1);
        orect.setAttribute('fill', 'transparent');
        orect.setAttribute('stroke', '#fbbf24');
        orect.setAttribute('stroke-width', '3');
        orect.setAttribute('stroke-dasharray', '10 6');
        orect.setAttribute('rx', '4');
        orect.style.cursor = 'move';
        orect.addEventListener('mousedown', _onGroupRectMouseDown);
        overlay.appendChild(orect);

        var ghandles = [[gx1, gy1, 'nw'], [gx2, gy1, 'ne'], [gx1, gy2, 'sw'], [gx2, gy2, 'se']];
        ghandles.forEach(function (h) {
          var hit = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          hit.setAttribute('x', h[0] - 22); hit.setAttribute('y', h[1] - 22);
          hit.setAttribute('width', 44); hit.setAttribute('height', 44);
          hit.setAttribute('fill', 'transparent');
          hit.setAttribute('cursor', h[2] + '-resize');
          hit.setAttribute('data-handle', h[2]);
          hit.addEventListener('mousedown', _onGroupHandleMouseDown);
          overlay.appendChild(hit);

          var dot = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          dot.setAttribute('x', h[0] - 9); dot.setAttribute('y', h[1] - 9);
          dot.setAttribute('width', 18); dot.setAttribute('height', 18);
          dot.setAttribute('fill', '#fbbf24'); dot.setAttribute('stroke', '#1a1a1a'); dot.setAttribute('stroke-width', '2');
          dot.setAttribute('pointer-events', 'none');
          overlay.appendChild(dot);
        });

        mainCanvas.appendChild(overlay);
      }
    }
  }

  // ── Drag / resize logic ────────────────────────────────────────────────
  function _svgPoint(ev) {
    var rect = mainCanvas.getBoundingClientRect();
    var vbParts = (mainCanvas.getAttribute('viewBox') || '0 0 1000 1000').split(' ');
    var vbW = parseFloat(vbParts[2]) || 1000;
    var vbH = parseFloat(vbParts[3]) || 1000;
    // Account for preserveAspectRatio="xMidYMid meet" letterboxing
    var svgAspect  = vbW / vbH;
    var elemAspect = rect.width / rect.height;
    var renderW, renderH, offX = 0, offY = 0;
    if (elemAspect > svgAspect) {
      renderH = rect.height; renderW = rect.height * svgAspect;
      offX = (rect.width - renderW) / 2;
    } else {
      renderW = rect.width; renderH = rect.width / svgAspect;
      offY = (rect.height - renderH) / 2;
    }
    return {
      x: ((ev.clientX - rect.left - offX) / renderW) * vbW,
      y: ((ev.clientY - rect.top  - offY) / renderH) * vbH,
    };
  }

  function _onRectMouseDown(ev, idx) {
    ev.stopPropagation();
    ev.preventDefault();
    var pt = _svgPoint(ev);
    var bbox = _idgModel.compositional_deconstruction.elements[idx].bbox.slice();
    _dragState = { elIdx: idx, startX: pt.x, startY: pt.y, origBbox: bbox, mode: 'move' };
    document.addEventListener('mousemove', _onMouseMove);
    document.addEventListener('mouseup', _onMouseUp);
  }

  function _onHandleMouseDown(ev) {
    ev.stopPropagation();
    ev.preventDefault();
    var idx = parseInt(ev.target.getAttribute('data-idx'), 10);
    var handle = ev.target.getAttribute('data-handle');
    var pt = _svgPoint(ev);
    var bbox = _idgModel.compositional_deconstruction.elements[idx].bbox.slice();
    _dragState = { elIdx: idx, startX: pt.x, startY: pt.y, origBbox: bbox, mode: 'resize', handle: handle };
    document.addEventListener('mousemove', _onMouseMove);
    document.addEventListener('mouseup', _onMouseUp);
  }

  function _onMouseMove(ev) {
    if (!_dragState) return;
    var pt = _svgPoint(ev);
    var dx = pt.x - _dragState.startX;
    var dy = pt.y - _dragState.startY;
    // _svgPoint returns x in [0,1000] and y in [0,vbH] — convert y delta to bbox space (0-1000)
    var cvH = parseFloat((mainCanvas.getAttribute('viewBox') || '0 0 1000 1000').split(' ')[3]) || 1000;
    var bboxDy = dy * 1000 / cvH;
    var ob = _dragState.origBbox;
    var elem = _idgModel.compositional_deconstruction.elements[_dragState.elIdx];
    var nb;
    // bbox format: [y_min, x_min, y_max, x_max]  —  all coords in 0-1000 space
    // dx moves x (indices 1,3); bboxDy moves y (indices 0,2)
    if (_dragState.mode === 'move') {
      nb = [
        Math.max(0, Math.min(ob[0] + bboxDy, 1000 - (ob[2] - ob[0]))),  // y_min
        Math.max(0, Math.min(ob[1] + dx,     1000 - (ob[3] - ob[1]))),  // x_min
        0, 0
      ];
      nb[2] = nb[0] + (ob[2] - ob[0]);
      nb[3] = nb[1] + (ob[3] - ob[1]);
    } else {
      nb = ob.slice();
      var h = _dragState.handle;
      if (h === 'nw') { nb[0] = Math.min(ob[0] + bboxDy, ob[2] - 20); nb[1] = Math.min(ob[1] + dx, ob[3] - 20); }
      else if (h === 'ne') { nb[3] = Math.max(ob[3] + dx, ob[1] + 20); nb[0] = Math.min(ob[0] + bboxDy, ob[2] - 20); }
      else if (h === 'sw') { nb[1] = Math.min(ob[1] + dx, ob[3] - 20); nb[2] = Math.max(ob[2] + bboxDy, ob[0] + 20); }
      else if (h === 'se') { nb[3] = Math.max(ob[3] + dx, ob[1] + 20); nb[2] = Math.max(ob[2] + bboxDy, ob[0] + 20); }
      // all indices clamp to [0, 1000] — coordinate space is always 0-1000 regardless of aspect ratio
      nb = nb.map(function (v) { return Math.max(0, Math.min(Math.round(v), 1000)); });
    }
    elem.bbox = nb.map(function (v) { return Math.round(v); });
    _renderMainCanvas(_idgModel);
    _updateCardCoords(_dragState.elIdx, elem.bbox);
  }

  function _onMouseUp() {
    _dragState = null;
    document.removeEventListener('mousemove', _onMouseMove);
    document.removeEventListener('mouseup', _onMouseUp);
  }

  // ── Group move / scale (Select All) ─────────────────────────────────────
  function _groupBbox(model) {
    var elements = (model.compositional_deconstruction && model.compositional_deconstruction.elements) || [];
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    // bbox format: [y_min, x_min, y_max, x_max]
    elements.forEach(function (el) {
      if (!Array.isArray(el.bbox) || el.bbox.length < 4) return;
      minY = Math.min(minY, el.bbox[0]);
      minX = Math.min(minX, el.bbox[1]);
      maxY = Math.max(maxY, el.bbox[2]);
      maxX = Math.max(maxX, el.bbox[3]);
    });
    if (minX === Infinity) return null;
    return [minX, minY, maxX, maxY]; // returns [x,y,x,y] for SVG rendering
  }

  function _startGroupDrag(ev, mode, handle) {
    ev.stopPropagation();
    ev.preventDefault();
    var group = _groupBbox(_idgModel);
    if (!group) return;
    var elements = _idgModel.compositional_deconstruction.elements;
    var pt = _svgPoint(ev);
    _groupDrag = {
      mode: mode,
      handle: handle,
      startX: pt.x,
      startY: pt.y,
      origGroup: group,
      origBboxes: elements.map(function (el) { return Array.isArray(el.bbox) ? el.bbox.slice() : null; })
    };
    document.addEventListener('mousemove', _onGroupMouseMove);
    document.addEventListener('mouseup', _onGroupMouseUp);
  }

  function _onGroupRectMouseDown(ev) { _startGroupDrag(ev, 'move', null); }
  function _onGroupHandleMouseDown(ev) { _startGroupDrag(ev, 'resize', ev.target.getAttribute('data-handle')); }

  function _onGroupMouseMove(ev) {
    if (!_groupDrag) return;
    var pt = _svgPoint(ev);
    var dx = pt.x - _groupDrag.startX;
    var dy = pt.y - _groupDrag.startY;
    var og = _groupDrag.origGroup;  // [x_min, y_min, x_max, y_max] in 0-1000 bbox space
    var elements = _idgModel.compositional_deconstruction.elements;
    // _svgPoint returns x in [0,1000] and y in [0,vbH] — convert y delta to bbox space (0-1000)
    var cvH = parseFloat((mainCanvas.getAttribute('viewBox') || '0 0 1000 1000').split(' ')[3]) || 1000;
    var bboxDy = dy * 1000 / cvH;

    if (_groupDrag.mode === 'move') {
      // og[0]=x_min, og[1]=y_min, og[2]=x_max, og[3]=y_max — all in 0-1000 space
      var ndx = Math.max(-og[0], Math.min(dx,     1000 - og[2]));
      var ndy = Math.max(-og[1], Math.min(bboxDy, 1000 - og[3]));
      elements.forEach(function (el, i) {
        var ob = _groupDrag.origBboxes[i];
        if (!ob) return;
        // bbox[0]=y_min, bbox[1]=x_min, bbox[2]=y_max, bbox[3]=x_max
        el.bbox = [
          Math.round(ob[0] + ndy), Math.round(ob[1] + ndx),
          Math.round(ob[2] + ndy), Math.round(ob[3] + ndx)
        ];
      });
    } else {
      // Scale every bbox relative to the corner opposite the dragged handle
      var h = _groupDrag.handle;
      var anchorX = (h === 'nw' || h === 'sw') ? og[2] : og[0];  // x in 0-1000
      var anchorY = (h === 'nw' || h === 'ne') ? og[3] : og[1];  // y in 0-1000
      var gw = og[2] - og[0], gh = og[3] - og[1];
      if (gw < 1 || gh < 1) return;

      var newW = (h === 'nw' || h === 'sw') ? (anchorX - (og[0] + dx))      : ((og[2] + dx)      - anchorX);
      var newH = (h === 'nw' || h === 'ne') ? (anchorY - (og[1] + bboxDy))  : ((og[3] + bboxDy)  - anchorY);
      newW = Math.max(20, newW);
      newH = Math.max(20, newH);

      var sx = newW / gw, sy = newH / gh;
      // Clamp so the scaled group stays within [0, 1000] on both axes
      sx = Math.min(sx, (h === 'nw' || h === 'sw') ? (anchorX / gw)        : ((1000 - anchorX) / gw));
      sy = Math.min(sy, (h === 'nw' || h === 'ne') ? (anchorY / gh)        : ((1000 - anchorY) / gh));

      elements.forEach(function (el, i) {
        var ob = _groupDrag.origBboxes[i];
        if (!ob) return;
        // bbox[0]=y_min, bbox[1]=x_min, bbox[2]=y_max, bbox[3]=x_max — all clamp to [0,1000]
        el.bbox = [
          Math.max(0, Math.min(1000, Math.round(anchorY + (ob[0] - anchorY) * sy))),
          Math.max(0, Math.min(1000, Math.round(anchorX + (ob[1] - anchorX) * sx))),
          Math.max(0, Math.min(1000, Math.round(anchorY + (ob[2] - anchorY) * sy))),
          Math.max(0, Math.min(1000, Math.round(anchorX + (ob[3] - anchorX) * sx)))
        ];
      });
    }

    _renderMainCanvas(_idgModel);
    elements.forEach(function (el, i) { _updateCardCoords(i, el.bbox); });
  }

  function _onGroupMouseUp() {
    _groupDrag = null;
    document.removeEventListener('mousemove', _onGroupMouseMove);
    document.removeEventListener('mouseup', _onGroupMouseUp);
  }

  // ── Cards panel ────────────────────────────────────────────────────────
  function _renderCards(model) {
    cardsPanel.innerHTML = '';
    if (!model || !model.compositional_deconstruction) return;

    // Background scene description card (not a positioned element)
    var bgDesc = model.compositional_deconstruction.background;
    if (typeof bgDesc === 'string') {
      var bgCard = document.createElement('div');
      bgCard.className = 'ncf-idg-card ncf-idg-card--bg-desc';
      var bgHdr = document.createElement('div');
      bgHdr.className = 'ncf-idg-card-hdr';
      var bgDot = document.createElement('span');
      bgDot.className = 'ncf-idg-card-dot';
      bgDot.style.background = '#64748b';
      var bgBadge = document.createElement('span');
      bgBadge.className = 'ncf-idg-card-badge';
      bgBadge.textContent = 'BG';
      bgBadge.style.borderColor = '#64748b'; bgBadge.style.color = '#64748b';
      var bgNum = document.createElement('span');
      bgNum.className = 'ncf-idg-card-num';
      bgNum.textContent = tF('Scene');
      bgHdr.appendChild(bgDot); bgHdr.appendChild(bgNum); bgHdr.appendChild(bgBadge);
      bgCard.appendChild(bgHdr);
      var bgTa = document.createElement('textarea');
      bgTa.className = 'ncf-idg-card-desc';
      bgTa.rows = 3;
      bgTa.value = bgDesc;
      bgTa.addEventListener('input', function () {
        _idgModel.compositional_deconstruction.background = bgTa.value;
      });
      bgCard.appendChild(bgTa);
      cardsPanel.appendChild(bgCard);
    }

    var elements = model.compositional_deconstruction.elements || [];
    elements.forEach(function (elem, idx) {
      var color = IDG_TYPE_COLORS[elem.type] || '#888';
      var card = document.createElement('div');
      card.className = 'ncf-idg-card';
      card.id = 'ncf-idg-card-' + idx;
      card.setAttribute('data-idx', idx);
      if (idx === _activeCardIdx) card.classList.add('ncf-idg-card--active');

      // Header
      var hdr = document.createElement('div');
      hdr.className = 'ncf-idg-card-hdr';
      var dot = document.createElement('span');
      dot.className = 'ncf-idg-card-dot';
      dot.style.background = color;
      var badge = document.createElement('span');
      badge.className = 'ncf-idg-card-badge';
      badge.textContent = (elem.type || 'obj').toUpperCase();
      badge.style.borderColor = color; badge.style.color = color;
      var num = document.createElement('span');
      num.className = 'ncf-idg-card-num';
      num.textContent = '#' + (idx + 1);
      hdr.appendChild(dot); hdr.appendChild(num); hdr.appendChild(badge);
      card.appendChild(hdr);

      // Description textarea
      var descTa = document.createElement('textarea');
      descTa.className = 'ncf-idg-card-desc';
      descTa.rows = 3;
      descTa.value = elem.desc || '';
      descTa.addEventListener('input', function () {
        _idgModel.compositional_deconstruction.elements[idx].desc = descTa.value;
      });
      card.appendChild(descTa);

      // Coords row
      var coords = document.createElement('div');
      coords.className = 'ncf-idg-card-coords';
      coords.id = 'ncf-idg-coords-' + idx;
      var bbox = Array.isArray(elem.bbox) ? elem.bbox : [0, 0, 500, 500];
      // Ideogram format [y_min, x_min, y_max, x_max] → labels T, L, B, R
      ['T', 'L', 'B', 'R'].forEach(function (lbl, ci) {
        var wrap = document.createElement('label');
        wrap.className = 'ncf-idg-coord-wrap';
        var span = document.createElement('span');
        span.textContent = lbl;
        var inp = document.createElement('input');
        inp.type = 'number'; inp.min = 0; inp.max = 1000;
        inp.value = Math.round(bbox[ci === 0 ? 0 : ci === 1 ? 1 : ci === 2 ? 2 : 3]);
        inp.setAttribute('data-ci', ci);
        inp.addEventListener('change', function () {
          var newBbox = _idgModel.compositional_deconstruction.elements[idx].bbox.slice();
          newBbox[parseInt(inp.getAttribute('data-ci'), 10)] = Math.max(0, Math.min(1000, parseInt(inp.value, 10) || 0));
          _idgModel.compositional_deconstruction.elements[idx].bbox = newBbox;
          _renderMainCanvas(_idgModel);
          _renderMiniCanvas(_idgModel);
        });
        wrap.appendChild(span); wrap.appendChild(inp);
        coords.appendChild(wrap);
      });
      card.appendChild(coords);

      card.addEventListener('click', function (ev) {
        if (ev.target.tagName === 'TEXTAREA' || ev.target.tagName === 'INPUT') return;
        _highlightCard(idx);
      });
      cardsPanel.appendChild(card);
    });
  }

  function _highlightCard(idx) {
    if (_selectAllMode) {
      _selectAllMode = false;
      if (selectAllBtn) selectAllBtn.classList.remove('ncf-btn--active');
    }
    _activeCardIdx = idx;
    document.querySelectorAll('.ncf-idg-card').forEach(function (c) {
      c.classList.toggle('ncf-idg-card--active', parseInt(c.getAttribute('data-idx'), 10) === idx);
    });
    _renderMainCanvas(_idgModel);
    var cardEl = document.getElementById('ncf-idg-card-' + idx);
    if (cardEl) cardEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function _updateCardCoords(idx, bbox) {
    var coordsEl = document.getElementById('ncf-idg-coords-' + idx);
    if (!coordsEl) return;
    var inputs = coordsEl.querySelectorAll('input');
    [0, 1, 2, 3].forEach(function (ci) {
      if (inputs[ci]) inputs[ci].value = Math.round(bbox[ci]);
    });
  }

  // ── Open / close / apply ───────────────────────────────────────────────
  editBtn.addEventListener('click', function () {
    if (!_idgModel || !_hasModal) return;
    _setRawMode(false);
    // Select first element by default when no active selection
    if (_activeCardIdx < 0) {
      var firstEl = (_idgModel.compositional_deconstruction && _idgModel.compositional_deconstruction.elements || [])[0];
      if (firstEl) _activeCardIdx = 0;
    }
    _renderVisual(_idgModel);
    modalEl.hidden = false;
    document.body.style.overflow = 'hidden';
  });

  function _closeModal() {
    modalEl.hidden = true;
    document.body.style.overflow = '';
    _dragState = null;
    _groupDrag = null;
    if (_selectAllMode) {
      _selectAllMode = false;
      if (selectAllBtn) selectAllBtn.classList.remove('ncf-btn--active');
    }
    _setZoom(1);
  }

  if (_hasModal) modalClose.addEventListener('click', _closeModal);
  if (_hasModal) modalEl.addEventListener('click', function (ev) {
    if (ev.target === modalEl) _closeModal();
  });

  if (_hasModal) modalApply.addEventListener('click', function () {
    if (!_idgModel) { _closeModal(); return; }
    if (_rawMode) {
      try { _idgModel = JSON.parse(rawTa.value); } catch (_) { return; }
      // Raw edits are typed in the internal [x_min, y_min, x_max, y_max] format
      // (the textarea shows that format), so only sanitize — no format detection.
      _sanitizeBboxes(_idgModel);
    }
    setVal(stepDef.id, 'ideogram_json', _idgModel);
    // Export to model with [y_min, x_min, y_max, x_max] as Ideogram expects
    setVal(stepDef.id, 'transformed_text', JSON.stringify(_modelForExport(_idgModel), null, 2));
    _renderMiniCanvas(_idgModel);
    var count = (_idgModel.compositional_deconstruction && _idgModel.compositional_deconstruction.elements || []).length;
    _flashMetaCount(count + ' element' + (count !== 1 ? 's' : ''), false);
    updateGenerateBtn();
    _closeModal();
  });
}

// ── action ─────────────────────────────────────────────────────────────────
