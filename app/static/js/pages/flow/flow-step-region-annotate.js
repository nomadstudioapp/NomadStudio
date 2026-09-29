'use strict';
// Step: region_annotate → renderRegionAnnotate
//
// Lets the user paint colored freehand strokes on top of a source image
// (read from stepDef.image_step, e.g. "image") to mark regions the prompt
// can then reference by color ("remove the object in the blue circle...").
// The flattened result (base image + strokes, via canvas.toDataURL()) is
// stored as this step's own `annotated_image_data_url` output for a later
// action step to submit as imageDataUrl — no backend change needed, it's
// just another image data URL by the time it reaches /refine/prepare.
//
// Same inline-preview + heavy-modal split as flow-step-layer-compositor.js
// (compact preview here, real interaction in the static #ncf-annotate-modal
// markup in _flow_body.html).

function renderRegionAnnotate(stepDef, el) {
  var COLORS = [
    { id: 'red', hex: '#ef4444' },
    { id: 'green', hex: '#22c55e' },
    { id: 'blue', hex: '#3b82f6' },
    { id: 'yellow', hex: '#eab308' },
    { id: 'purple', hex: '#a855f7' },
    { id: 'orange', hex: '#f97316' },
  ];
  var DEFAULT_WIDTH = 14;
  var MAX_DIM = 1536; // cap canvas resolution, same idea as image_picker's own resizes

  // ── Compact preview ────────────────────────────────────────────────────
  var preview = document.createElement('div');
  preview.className = 'ncf-annotate-preview';

  var thumbImg = document.createElement('img');
  thumbImg.className = 'ncf-annotate-thumb';
  preview.appendChild(thumbImg);

  // Same button look as every other in-step action trigger in the app
  // (nss-generate-scenes-btn — Generate, Describe reference, Build prompt
  // from zones), not the plain secondary button this used to be. No
  // separate "Ready…"/"Annotated…" status line either — the thumbnail
  // itself (blank vs. showing the marked-up regions) already says that.
  var editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'nss-generate-scenes-btn ncf-annotate-edit-btn';
  editBtn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true" style="width:18px;height:18px"><rect x="3" y="3" width="18" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 8h8v8H8z" fill="none" stroke="currentColor" stroke-width="2"/></svg>' +
    '<span>' + escHtml(tF('Annotate')) + '</span>';
  editBtn.disabled = true;
  preview.appendChild(editBtn);

  el.appendChild(preview);

  // ── Internal state ───────────────────────────────────────────────────
  var _annotatedUrl = null; // last applied flattened data URL
  // Two shapes: freehand ({type:'freehand', color, width, points:[{x,y}…]})
  // and rectangle-outline ({type:'rect', color, width, x0,y0,x1,y1}) — the
  // latter added for MultiComposer (mix.multi_composer), which marks fixed
  // rectangular zones on a background rather than loose freehand loops.
  var _strokes = [];
  var _activeColor = COLORS[0].hex;
  // stepDef.shape_mode: "rectangle" defaults this step's modal to Rectangle
  // (MultiComposer) instead of Freehand (Local Editing's default) — still a
  // toggle either way, just which one starts active.
  var _shapeMode = stepDef.shape_mode === 'rectangle' ? 'rect' : 'freehand';
  var _baseImg = null;      // Image object of the source, (re)loaded whenever the modal opens

  function _sourceUrl() { return getVal(stepDef.image_step, 'image_data_url') || ''; }

  function _refreshPreview() {
    var url = _sourceUrl();
    var ready = !!url;
    editBtn.disabled = !ready;
    if (!ready) {
      thumbImg.removeAttribute('src');
      return;
    }
    thumbImg.src = _annotatedUrl || url;
  }
  window._ncfAnnotateRefresh = _refreshPreview;
  _refreshPreview();

  // ── Modal wiring ─────────────────────────────────────────────────────
  var modalEl    = document.getElementById('ncf-annotate-modal');
  var modalClose = document.getElementById('ncf-annotate-modal-close');
  var modalApply = document.getElementById('ncf-annotate-modal-apply');
  var modalUndo  = document.getElementById('ncf-annotate-undo');
  var modalClear = document.getElementById('ncf-annotate-clear');
  var swatchRow  = document.getElementById('ncf-annotate-swatches');
  var widthInput = document.getElementById('ncf-annotate-width');
  var widthValEl = document.getElementById('ncf-annotate-width-val');
  var mainCanvas = document.getElementById('ncf-annotate-canvas');
  var hintEl       = document.getElementById('ncf-annotate-hint');
  var shapeFreehandBtn = document.getElementById('ncf-annotate-shape-freehand');
  var shapeRectBtn     = document.getElementById('ncf-annotate-shape-rect');
  var _hasModal  = !!(modalEl && mainCanvas && swatchRow);

  var _FREEHAND_HINT = 'Draw a loop or scribble over a region, then reference its color in your prompt ' +
    '(e.g. "remove the object in the blue circle")';
  var _RECT_HINT = 'Drag a rectangle outline over each zone, then assign a reference image to that color.';

  function _syncShapeButtons() {
    if (!shapeFreehandBtn || !shapeRectBtn) return;
    shapeFreehandBtn.classList.toggle('is-active', _shapeMode === 'freehand');
    shapeRectBtn.classList.toggle('is-active', _shapeMode === 'rect');
    if (hintEl) hintEl.textContent = _shapeMode === 'rect' ? _RECT_HINT : _FREEHAND_HINT;
  }
  if (shapeFreehandBtn) shapeFreehandBtn.addEventListener('click', function () { _shapeMode = 'freehand'; _syncShapeButtons(); });
  if (shapeRectBtn) shapeRectBtn.addEventListener('click', function () { _shapeMode = 'rect'; _syncShapeButtons(); });

  if (_hasModal && !swatchRow.childElementCount) {
    COLORS.forEach(function (c, i) {
      var sw = document.createElement('button');
      sw.type = 'button';
      sw.className = 'ncf-annotate-swatch' + (i === 0 ? ' is-active' : '');
      sw.style.backgroundColor = c.hex;
      sw.title = c.id;
      sw.addEventListener('click', function () {
        _activeColor = c.hex;
        Array.prototype.forEach.call(swatchRow.querySelectorAll('.ncf-annotate-swatch'), function (b) {
          b.classList.remove('is-active');
        });
        sw.classList.add('is-active');
      });
      swatchRow.appendChild(sw);
    });
  }
  if (widthInput && widthValEl) {
    widthInput.addEventListener('input', function () { widthValEl.textContent = widthInput.value; });
  }

  function _paintStroke(ctx, s) {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = s.width;
    if (s.type === 'rect') {
      var x = Math.min(s.x0, s.x1), y = Math.min(s.y0, s.y1);
      var w = Math.abs(s.x1 - s.x0), h = Math.abs(s.y1 - s.y0);
      if (w < 1 || h < 1) return;
      ctx.strokeRect(x, y, w, h); // outline only, never filled — a solid block would hide whatever's under it
      return;
    }
    if (!s.points || s.points.length < 2) return;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(s.points[0].x, s.points[0].y);
    for (var i = 1; i < s.points.length; i++) ctx.lineTo(s.points[i].x, s.points[i].y);
    ctx.stroke();
  }

  function _redraw() {
    if (!_hasModal || !_baseImg) return;
    var ctx = mainCanvas.getContext('2d');
    ctx.clearRect(0, 0, mainCanvas.width, mainCanvas.height);
    ctx.drawImage(_baseImg, 0, 0, mainCanvas.width, mainCanvas.height);
    _strokes.forEach(function (s) { _paintStroke(ctx, s); });
    // Rect mode redraws the live in-progress shape too (unlike freehand,
    // which paints incremental segments on top without a full redraw) —
    // a rectangle's final shape depends on where the pointer ends up, so
    // it has to be re-drawn from scratch on every move to preview correctly.
    if (_drawing && _drawing.type === 'rect') _paintStroke(ctx, _drawing);
  }

  var _drawing = null; // current stroke while the pointer is down

  function _canvasPoint(ev) {
    var rect = mainCanvas.getBoundingClientRect();
    var scaleX = mainCanvas.width / rect.width;
    var scaleY = mainCanvas.height / rect.height;
    return { x: (ev.clientX - rect.left) * scaleX, y: (ev.clientY - rect.top) * scaleY };
  }

  function _onPointerDown(ev) {
    if (!_baseImg) return;
    ev.preventDefault();
    var pt = _canvasPoint(ev);
    var width = Number(widthInput ? widthInput.value : DEFAULT_WIDTH) || DEFAULT_WIDTH;
    _drawing = _shapeMode === 'rect'
      ? { type: 'rect', color: _activeColor, width: width, x0: pt.x, y0: pt.y, x1: pt.x, y1: pt.y }
      : { type: 'freehand', color: _activeColor, width: width, points: [pt] };
    if (mainCanvas.setPointerCapture) { try { mainCanvas.setPointerCapture(ev.pointerId); } catch (_) {} }
  }
  function _onPointerMove(ev) {
    if (!_drawing) return;
    var pt = _canvasPoint(ev);
    if (_drawing.type === 'rect') {
      _drawing.x1 = pt.x; _drawing.y1 = pt.y;
      _redraw();
      return;
    }
    var prev = _drawing.points[_drawing.points.length - 1];
    _drawing.points.push(pt);
    // Paint just the new segment instead of a full redraw on every move —
    // strokes already on the canvas stay put, this just extends the line.
    var ctx = mainCanvas.getContext('2d');
    _paintStroke(ctx, { type: 'freehand', color: _drawing.color, width: _drawing.width, points: [prev, pt] });
  }
  function _onPointerUp() {
    if (!_drawing) return;
    var keep = _drawing.type === 'rect'
      ? (Math.abs(_drawing.x1 - _drawing.x0) >= 4 && Math.abs(_drawing.y1 - _drawing.y0) >= 4)
      : _drawing.points.length > 1;
    if (keep) _strokes.push(_drawing);
    _drawing = null;
    if (keep) _redraw(); // clear the rect's live-preview overlay, show the committed stroke in place
  }

  if (_hasModal) {
    mainCanvas.addEventListener('pointerdown', _onPointerDown);
    mainCanvas.addEventListener('pointermove', _onPointerMove);
    mainCanvas.addEventListener('pointerup', _onPointerUp);
    mainCanvas.addEventListener('pointerleave', _onPointerUp);
  }
  if (modalUndo) modalUndo.addEventListener('click', function () { _strokes.pop(); _redraw(); });
  if (modalClear) modalClear.addEventListener('click', function () { _strokes = []; _redraw(); });

  editBtn.addEventListener('click', function () {
    if (!_hasModal) return;
    var url = _sourceUrl();
    if (!url) return;
    var img = new Image();
    img.onload = function () {
      var w = img.naturalWidth || 1, h = img.naturalHeight || 1;
      var scale = Math.min(1, MAX_DIM / Math.max(w, h));
      mainCanvas.width  = Math.max(1, Math.round(w * scale));
      mainCanvas.height = Math.max(1, Math.round(h * scale));
      _baseImg = img;
      // Restore whatever was applied last time instead of wiping it —
      // previously this always reset to [], so reopening the modal after a
      // successful Apply (the picker even says "Annotated — click to
      // adjust") silently threw the rectangles away. Redrawn on top of the
      // clean, un-flattened source image (still `url`, not `_annotatedUrl`)
      // so colors never double-bake from re-editing.
      _strokes = getVal(stepDef.id, 'strokes') || [];
      _syncShapeButtons();
      _redraw();
      modalEl.hidden = false;
      document.body.style.overflow = 'hidden';
    };
    img.onerror = function () {};
    img.src = url;
  });

  function _closeModal() {
    modalEl.hidden = true;
    document.body.style.overflow = '';
    _drawing = null;
  }
  if (_hasModal) modalClose.addEventListener('click', _closeModal);
  if (_hasModal) modalEl.addEventListener('click', function (ev) {
    if (ev.target === modalEl) _closeModal();
  });
  if (_hasModal) modalApply.addEventListener('click', function () {
    _annotatedUrl = mainCanvas.toDataURL('image/png');
    setVal(stepDef.id, 'annotated_image_data_url', _annotatedUrl);
    // The strokes themselves (not just the flattened PNG) — so reopening
    // the modal later can restore them for further editing instead of
    // starting from a blank canvas again.
    setVal(stepDef.id, 'strokes', _strokes);
    _refreshPreview();
    updateGenerateBtn();
    _closeModal();
  });
}

// ── zone_prompt_builder (MultiComposer, mix.multi_composer) ────────────────
// A single button, no LLM: reads each image step listed in
// stepDef.source_steps (e.g. image_2/image_3/image_4) that has BOTH a
// picked image AND a zone_color (set by image_picker's zone_picker select,
// see flow-step-image-picker.js), and assembles one natural-language
// sentence — close to the phrasing a user would type by hand ("Reference
// the background as <image1>, place the subject from <image2> in the red
// rectangle and the subject from <image3> in the green rectangle") plus a
// fixed closing clause about scale/lighting, since that's the thing a
// composite most commonly needs and the model won't infer it from the
// rectangles alone. Pushed into stepDef.target_step (the flow's final
// prompt_input step) via the same push-to-sibling-step mechanism
// flow-step-workflow-params.js's compose_preview uses for the Quick flow's
// role picker. Same button look as every other in-step action trigger in
// the app (nss-generate-scenes-btn — see flow-step-vision-describe.js's
// "Describe reference"), not a one-off style.
function renderZonePromptBuilder(stepDef, el) {
  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'nss-generate-scenes-btn';
  btn.style.cssText = 'width:100%;margin-top:0;';
  // A grid/zones icon, not the bolt Generate already uses — that one reads
  // as "run the generation", which this button doesn't do (it only fills
  // the prompt text below, Generate is a separate later step).
  btn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true" style="width:18px;height:18px" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="3" width="8" height="8" rx="1"/><rect x="3" y="13" width="8" height="8" rx="1"/><rect x="13" y="13" width="8" height="8" rx="1"/></svg>' +
    '<span>' + escHtml(stepDef.label || 'Build prompt from zones') + '</span>';
  el.appendChild(btn);

  var hint = mkHint('');
  hint.style.marginTop = '6px';
  el.appendChild(hint);

  // "image"/"background" has no numeric suffix (it's always <image1> — the
  // background, per this flow's own generate step wiring), image_2/3/4 map
  // 1:1 to <image2>/<image3>/<image4>.
  function _imageTagFor(stepId) {
    if (stepId === 'image' || stepId === 'background') return '<image1>';
    var m = /^image_(\d+)$/.exec(stepId);
    return m ? ('<image' + m[1] + '>') : null;
  }

  btn.addEventListener('click', function () {
    var backgroundTag = stepDef.background_ref || '<image1>';
    var sourceSteps = Array.isArray(stepDef.source_steps) ? stepDef.source_steps : [];
    var clauses = [];
    sourceSteps.forEach(function (stepId) {
      var hasImage = !!getVal(stepId, 'image_data_url');
      var color = getVal(stepId, 'zone_color');
      var tag = _imageTagFor(stepId);
      if (!hasImage || !color || !tag) return;
      clauses.push('the subject from ' + tag + ' in the ' + color + ' rectangle');
    });
    if (!clauses.length) {
      hint.textContent = tF('Pick at least one reference image and its zone color first.');
      return;
    }
    // Join with commas, "and" before the last one — "A, B and C", not
    // "A, and B, and C".
    var joined = clauses.length === 1 ? clauses[0]
      : clauses.slice(0, -1).join(', ') + ' and ' + clauses[clauses.length - 1];
    var text = 'Reference the background as ' + backgroundTag + ', place ' + joined + ', matching each ' +
      "person's scale, perspective and pose to the scene, and blending them into the background's existing " +
      'lighting, shadows and color grading so everyone looks naturally photographed together.';
    hint.textContent = '';
    if (stepDef.target_step) {
      setVal(stepDef.target_step, 'prompt_text', text);
      var targetTa = document.getElementById('ncf-input-' + stepDef.target_step);
      if (targetTa) {
        targetTa.value = text;
        targetTa.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
    updateGenerateBtn();
  });
}

// ── compose_template_picker (MultiComposer, mix.multi_composer) ───────────
// A dropdown of starting-point prompt templates (Swap Face, Group Photo
// Composer, Outfit Builder, Product Scene Placer, Interior/Scene Composer,
// Style Transfer — see MULTI_COMPOSER_TEMPLATES in build_packages.py) for
// compositing jobs the color-zone builder doesn't fit (it only knows
// "reference N goes in the color-N rectangle"). Picking one fills
// stepDef.target_step's textarea, same push mechanism as
// zone_prompt_builder above — {{bracketed}} placeholders are left in for
// the user to hand-edit (e.g. how many images, what to redraw), not
// auto-filled here.
function renderComposeTemplatePicker(stepDef, el) {
  var templates = Array.isArray(stepDef.templates) ? stepDef.templates : [];

  var wrap = document.createElement('div');
  wrap.className = 'nsc-select-wrapper';
  var select = document.createElement('select');
  select.className = 'nsc-select';
  var noneOpt = document.createElement('option');
  noneOpt.value = '';
  noneOpt.textContent = tF('— pick a template —');
  select.appendChild(noneOpt);
  templates.forEach(function (t, i) {
    var opt = document.createElement('option');
    opt.value = String(i);
    opt.textContent = t.label || ('Template ' + (i + 1));
    select.appendChild(opt);
  });
  var chev = document.createElement('span');
  chev.className = 'nsc-select-chevron';
  chev.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>';
  wrap.appendChild(select);
  wrap.appendChild(chev);
  el.appendChild(wrap);

  select.addEventListener('change', function () {
    var idx = select.value;
    if (idx === '') return;
    var tpl = templates[+idx];
    if (!tpl || !stepDef.target_step) return;
    setVal(stepDef.target_step, 'prompt_text', tpl.text);
    var targetTa = document.getElementById('ncf-input-' + stepDef.target_step);
    if (targetTa) {
      targetTa.value = tpl.text;
      targetTa.dispatchEvent(new Event('input', { bubbles: true }));
    }
    updateGenerateBtn();
  });
}
