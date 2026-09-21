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

  var metaLabel = document.createElement('span');
  metaLabel.className = 'ncf-annotate-label';
  metaLabel.textContent = 'Pick a source image to annotate';
  preview.appendChild(metaLabel);

  var editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'ncf-btn ncf-btn--secondary ncf-annotate-edit-btn';
  editBtn.textContent = 'Annotate';
  editBtn.disabled = true;
  preview.appendChild(editBtn);

  el.appendChild(preview);

  // ── Internal state ───────────────────────────────────────────────────
  var _annotatedUrl = null; // last applied flattened data URL
  var _strokes = [];        // { color, width, points: [{x,y}, ...] }[] — canvas-pixel space
  var _activeColor = COLORS[0].hex;
  var _baseImg = null;      // Image object of the source, (re)loaded whenever the modal opens

  function _sourceUrl() { return getVal(stepDef.image_step, 'image_data_url') || ''; }

  function _refreshPreview() {
    var url = _sourceUrl();
    var ready = !!url;
    editBtn.disabled = !ready;
    if (!ready) {
      thumbImg.removeAttribute('src');
      metaLabel.textContent = 'Pick a source image to annotate';
      return;
    }
    thumbImg.src = _annotatedUrl || url;
    metaLabel.textContent = _annotatedUrl ? 'Annotated — click to adjust' : 'Ready — click Annotate to mark regions';
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
  var _hasModal  = !!(modalEl && mainCanvas && swatchRow);

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
    if (s.points.length < 2) return;
    ctx.strokeStyle = s.color;
    ctx.lineWidth = s.width;
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
    _drawing = {
      color: _activeColor,
      width: Number(widthInput ? widthInput.value : DEFAULT_WIDTH) || DEFAULT_WIDTH,
      points: [pt],
    };
    if (mainCanvas.setPointerCapture) { try { mainCanvas.setPointerCapture(ev.pointerId); } catch (_) {} }
  }
  function _onPointerMove(ev) {
    if (!_drawing) return;
    var pt = _canvasPoint(ev);
    var prev = _drawing.points[_drawing.points.length - 1];
    _drawing.points.push(pt);
    // Paint just the new segment instead of a full redraw on every move —
    // strokes already on the canvas stay put, this just extends the line.
    var ctx = mainCanvas.getContext('2d');
    _paintStroke(ctx, { color: _drawing.color, width: _drawing.width, points: [prev, pt] });
  }
  function _onPointerUp() {
    if (!_drawing) return;
    if (_drawing.points.length > 1) _strokes.push(_drawing);
    _drawing = null;
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
      _strokes = [];
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
    _refreshPreview();
    updateGenerateBtn();
    _closeModal();
  });
}
