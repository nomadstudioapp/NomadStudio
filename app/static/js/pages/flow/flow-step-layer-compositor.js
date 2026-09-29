'use strict';
// Step: layer_compositor → renderLayerCompositor
//
// A single foreground "layer" image is placed on top of a background image.
// The canvas defaults to the background's own aspect ratio; the layer can be
// dragged to move and resized from its bottom-right corner, always keeping
// its own native aspect ratio locked.
//
// Internal coordinate space: 0-1000 on X, 0-cvH on Y, where
//   cvH = 1000 * bgHeight / bgWidth
// This makes X and Y units isotropic relative to the background, so a
// layer's on-canvas width/height ratio (w / h) always equals its native
// pixel aspect ratio (layerW / layerH) — no bg-aspect correction needed.
//
// Exported transform is normalized as fractions of the bg image itself:
//   { x_frac, y_frac, w_frac }
// The backend addon derives the final height from the layer's own pixel
// aspect ratio, so only width needs to travel as a fraction.

function renderLayerCompositor(stepDef, el) {
  var DEFAULT_TRANSFORM = { x_frac: 0.35, y_frac: 0.35, w_frac: 0.3 };

  // ── Compact preview ────────────────────────────────────────────────────
  var preview = document.createElement('div');
  preview.className = 'ncf-lc-preview';
  preview.id = 'ncf-lc-preview-' + stepDef.id;

  var miniSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  miniSvg.setAttribute('viewBox', '0 0 1000 1000');
  miniSvg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  miniSvg.setAttribute('class', 'ncf-lc-mini-svg');
  miniSvg.id = 'ncf-lc-mini-svg-' + stepDef.id;
  var miniBg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  miniBg.setAttribute('width', '1000'); miniBg.setAttribute('height', '1000');
  miniBg.setAttribute('fill', '#1e1e1e'); miniBg.setAttribute('rx', '8');
  miniSvg.appendChild(miniBg);
  var miniBgImg = document.createElementNS('http://www.w3.org/2000/svg', 'image');
  miniBgImg.setAttribute('x', '0'); miniBgImg.setAttribute('y', '0');
  miniBgImg.setAttribute('width', '1000');
  miniBgImg.setAttribute('preserveAspectRatio', 'none');
  miniSvg.appendChild(miniBgImg);
  var miniLayerImg = document.createElementNS('http://www.w3.org/2000/svg', 'image');
  miniLayerImg.setAttribute('preserveAspectRatio', 'none');
  miniSvg.appendChild(miniLayerImg);
  preview.appendChild(miniSvg);

  var previewMeta = document.createElement('div');
  previewMeta.className = 'ncf-lc-preview-meta';
  var metaLabel = document.createElement('span');
  metaLabel.className = 'ncf-lc-preview-label';
  metaLabel.textContent = tF('Pick both images to position the layer');
  previewMeta.appendChild(metaLabel);
  preview.appendChild(previewMeta);

  var editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'ncf-btn ncf-btn--secondary ncf-lc-edit-btn';
  editBtn.textContent = tF('Edit Layout');
  editBtn.disabled = true;
  preview.appendChild(editBtn);

  el.appendChild(preview);

  // ── Internal state ──────────────────────────────────────────────────────
  var _transform = null;    // { x_frac, y_frac, w_frac } — last applied
  var _bgAspect = 1;        // bgWidth / bgHeight
  var _layerAspect = 1;     // layerWidth / layerHeight
  var _cvH = 1000;          // canvas viewBox height for the current bg aspect

  function _bgUrl() { return getVal(stepDef.bg_step, 'image_data_url') || ''; }
  function _layerUrl() { return getVal(stepDef.layer_step, 'image_data_url') || ''; }

  function _loadImageDims(url) {
    return new Promise(function (resolve) {
      if (!url) { resolve(null); return; }
      var img = new Image();
      img.onload = function () { resolve({ w: img.naturalWidth || 1, h: img.naturalHeight || 1 }); };
      img.onerror = function () { resolve(null); };
      img.src = url;
    });
  }

  // ── Downscaled copies for the live lighting preview ─────────────────────
  // On a large source photo (e.g. a 4000px camera shot), sending the full-res
  // data URL to /preview-layer on every slider tick is slow both to transfer
  // and to grade server-side — and the canvas only ever displays it at
  // ~1000 viewBox units anyway. Cap what we send for the *preview* round-trip
  // only; the final /process call (real composite) always uses the original,
  // full-quality image. Cached per source URL so repeated slider drags reuse
  // the same downscaled copy instead of re-encoding on every tick.
  var PREVIEW_MAX_DIM = 1200;
  var _downscaleCache = {}; // url -> Promise<dataUrl>

  function _downscaleForPreview(url) {
    if (!url) return Promise.resolve(url);
    if (_downscaleCache[url]) return _downscaleCache[url];
    var p = new Promise(function (resolve) {
      var img = new Image();
      img.onload = function () {
        var w = img.naturalWidth || 1, h = img.naturalHeight || 1;
        if (Math.max(w, h) <= PREVIEW_MAX_DIM) { resolve(url); return; }
        var scale = PREVIEW_MAX_DIM / Math.max(w, h);
        var cw = Math.max(1, Math.round(w * scale));
        var ch = Math.max(1, Math.round(h * scale));
        try {
          var canvas = document.createElement('canvas');
          canvas.width = cw; canvas.height = ch;
          canvas.getContext('2d').drawImage(img, 0, 0, cw, ch);
          resolve(canvas.toDataURL('image/jpeg', 0.85));
        } catch (_) {
          resolve(url); // CORS/taint fallback — fall back to the original URL
        }
      };
      img.onerror = function () { resolve(url); };
      img.src = url;
    });
    _downscaleCache[url] = p;
    return p;
  }

  // Re-run whenever any step value changes (see hook in flow-generate-btn.js)
  function _refreshPreview() {
    var bgUrl = _bgUrl(), layerUrl = _layerUrl();
    var ready = !!(bgUrl && layerUrl);
    editBtn.disabled = !ready;
    metaLabel.textContent = !ready
      ? 'Pick both images to position the layer'
      : (_transform ? 'Layout set — click Edit to adjust' : 'Ready — click Edit Layout to position');
    if (!ready) {
      miniBgImg.setAttribute('href', '');
      miniLayerImg.setAttribute('href', '');
      return;
    }
    miniBgImg.setAttribute('href', bgUrl);
    miniBgImg.setAttribute('height', '1000');
    var t = _transform || DEFAULT_TRANSFORM;
    // Mini preview always assumes a 1:1 mini viewBox for simplicity (image
    // itself is drawn at its real aspect via preserveAspectRatio="none" using
    // whatever _bgAspect/_layerAspect were last computed when the modal opened).
    var lw = t.w_frac * 1000;
    var lh = _layerAspect ? (lw / _layerAspect) : lw;
    miniLayerImg.setAttribute('href', layerUrl);
    miniLayerImg.setAttribute('x', t.x_frac * 1000);
    miniLayerImg.setAttribute('y', t.y_frac * 1000);
    miniLayerImg.setAttribute('width', lw);
    miniLayerImg.setAttribute('height', lh);
  }
  window._ncfLcRefresh = _refreshPreview;
  _refreshPreview();

  // ── Modal wiring ─────────────────────────────────────────────────────────
  var modalEl    = document.getElementById('ncf-layer-modal');
  var modalClose = document.getElementById('ncf-lc-modal-close');
  var modalApply = document.getElementById('ncf-lc-modal-apply');
  var mainCanvas = document.getElementById('ncf-lc-canvas');
  var canvasWrap = document.getElementById('ncf-lc-canvas-wrap');
  var _hasModal = !!(modalEl && mainCanvas && canvasWrap);

  // ── Lighting controls (brightness/warmth sliders + "Match lighting") ────
  var brightnessInput   = document.getElementById('ncf-lc-brightness');
  var brightnessValEl   = document.getElementById('ncf-lc-brightness-val');
  var warmthInput       = document.getElementById('ncf-lc-warmth');
  var warmthValEl       = document.getElementById('ncf-lc-warmth-val');
  var hueInput          = document.getElementById('ncf-lc-hue');
  var hueValEl          = document.getElementById('ncf-lc-hue-val');
  var matchEnabledInput = document.getElementById('ncf-lc-match-enabled');
  var matchStrengthRow  = document.getElementById('ncf-lc-match-strength-row');
  var matchStrengthInput = document.getElementById('ncf-lc-match-strength');
  var matchStrengthValEl = document.getElementById('ncf-lc-match-strength-val');
  var lightingHintEl    = document.getElementById('ncf-lc-lighting-hint');
  var _hasLightingPanel = !!(brightnessInput && warmthInput && matchEnabledInput);
  var _hasHueControl    = !!(hueInput && hueValEl);

  var DEFAULT_LIGHTING = { brightness: 0, warmth: 0, hue: 0, match_enabled: false, match_strength: 0.3 };
  var _lighting = null;          // last applied (persisted on Apply)
  var _previewLayerUrl = null;   // graded layer image, shown in the canvas while editing
  var _lightingToken = 0;

  function _effectiveLayerUrl() { return _previewLayerUrl || _layerUrl(); }

  function _schedulePreview() {
    if (!_hasLightingPanel) return;
    var b = Number(brightnessInput.value) || 0;
    var w2 = Number(warmthInput.value) || 0;
    var hueVal = _hasHueControl ? (Number(hueInput.value) || 0) : 0;
    var matchOn = !!matchEnabledInput.checked;
    var strength = Number(matchStrengthInput.value) || 0.3;

    if (!b && !w2 && !hueVal && !matchOn) {
      _previewLayerUrl = null;
      _renderCanvas();
      if (lightingHintEl) lightingHintEl.textContent = '';
      return;
    }

    var myToken = ++_lightingToken;
    if (lightingHintEl) lightingHintEl.textContent = tF('Updating preview…');

    Promise.all([
      _downscaleForPreview(_layerUrl()),
      matchOn ? _downscaleForPreview(_bgUrl()) : Promise.resolve(undefined),
    ])
      .then(function (small) {
        if (myToken !== _lightingToken) return null;
        return fetch('/api/models/layer-compose/preview-layer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            layerDataUrl: small[0],
            bgDataUrl: small[1],
            lighting: { brightness: b, warmth: w2, hue: hueVal, match_enabled: matchOn, match_strength: strength },
          }),
        });
      })
      .then(function (r) { return r && r.json(); })
      .then(function (data) {
        if (myToken !== _lightingToken || !data) return; // superseded by a newer edit
        if (data.error) { if (lightingHintEl) lightingHintEl.textContent = data.error || 'Preview failed'; return; }
        _previewLayerUrl = data.dataUrl || null;
        _renderCanvas();
        if (lightingHintEl) lightingHintEl.textContent = '';
      })
      .catch(function () {
        if (myToken === _lightingToken && lightingHintEl) lightingHintEl.textContent = tF('Preview failed');
      });
  }

  var _previewDebounce = null;
  function _scheduleLightingPreviewDebounced() {
    if (_previewDebounce) clearTimeout(_previewDebounce);
    _previewDebounce = setTimeout(_schedulePreview, 350);
  }

  if (_hasLightingPanel) {
    brightnessInput.addEventListener('input', function () {
      brightnessValEl.textContent = brightnessInput.value;
      _scheduleLightingPreviewDebounced();
    });
    warmthInput.addEventListener('input', function () {
      warmthValEl.textContent = warmthInput.value;
      _scheduleLightingPreviewDebounced();
    });
    if (_hasHueControl) {
      hueInput.addEventListener('input', function () {
        hueValEl.textContent = hueInput.value;
        _scheduleLightingPreviewDebounced();
      });
    }
    matchStrengthInput.addEventListener('input', function () {
      matchStrengthValEl.textContent = matchStrengthInput.value;
      _scheduleLightingPreviewDebounced();
    });
    matchEnabledInput.addEventListener('change', function () {
      matchStrengthRow.hidden = !matchEnabledInput.checked;
      _schedulePreview(); // no debounce — immediate feedback on toggle
    });
  }

  // Live edit state (canvas units)
  var x = 0, y = 0, w = 300, h = 300;
  var _dragState = null; // { mode: 'move'|'resize', startX, startY, origX, origY, origW }

  function _svgPoint(ev) {
    var rect = mainCanvas.getBoundingClientRect();
    var vbParts = (mainCanvas.getAttribute('viewBox') || '0 0 1000 1000').split(' ');
    var vbW = parseFloat(vbParts[2]) || 1000;
    var vbH = parseFloat(vbParts[3]) || 1000;
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

  function _renderCanvas() {
    if (!_hasModal) return;
    while (mainCanvas.childNodes.length > 1) mainCanvas.removeChild(mainCanvas.lastChild);
    mainCanvas.setAttribute('viewBox', '0 0 1000 ' + _cvH);
    if (mainCanvas.firstElementChild) mainCanvas.firstElementChild.setAttribute('height', _cvH);

    var bgImg = document.createElementNS('http://www.w3.org/2000/svg', 'image');
    bgImg.setAttribute('href', _bgUrl());
    bgImg.setAttribute('x', '0'); bgImg.setAttribute('y', '0');
    bgImg.setAttribute('width', '1000'); bgImg.setAttribute('height', _cvH);
    bgImg.setAttribute('preserveAspectRatio', 'none');
    mainCanvas.appendChild(bgImg);

    var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.style.cursor = 'move';

    var layerImg = document.createElementNS('http://www.w3.org/2000/svg', 'image');
    layerImg.setAttribute('href', _effectiveLayerUrl());
    layerImg.setAttribute('x', x); layerImg.setAttribute('y', y);
    layerImg.setAttribute('width', w); layerImg.setAttribute('height', h);
    layerImg.setAttribute('preserveAspectRatio', 'none');
    layerImg.addEventListener('mousedown', _onMoveMouseDown);
    g.appendChild(layerImg);

    var border = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    border.setAttribute('x', x); border.setAttribute('y', y);
    border.setAttribute('width', w); border.setAttribute('height', h);
    border.setAttribute('fill', 'none');
    border.setAttribute('stroke', '#a855f7');
    border.setAttribute('stroke-width', '3');
    border.setAttribute('stroke-dasharray', '8 5');
    border.setAttribute('pointer-events', 'none');
    g.appendChild(border);

    var handle = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    var hs = 20;
    handle.setAttribute('x', x + w - hs / 2); handle.setAttribute('y', y + h - hs / 2);
    handle.setAttribute('width', hs); handle.setAttribute('height', hs);
    handle.setAttribute('fill', '#a855f7');
    handle.setAttribute('stroke', '#1a1a1a');
    handle.setAttribute('stroke-width', '2');
    handle.setAttribute('rx', '3');
    handle.setAttribute('cursor', 'se-resize');
    handle.addEventListener('mousedown', _onResizeMouseDown);
    g.appendChild(handle);

    mainCanvas.appendChild(g);
  }

  function _onMoveMouseDown(ev) {
    ev.stopPropagation(); ev.preventDefault();
    var pt = _svgPoint(ev);
    _dragState = { mode: 'move', startX: pt.x, startY: pt.y, origX: x, origY: y };
    document.addEventListener('mousemove', _onMouseMove);
    document.addEventListener('mouseup', _onMouseUp);
  }
  function _onResizeMouseDown(ev) {
    ev.stopPropagation(); ev.preventDefault();
    var pt = _svgPoint(ev);
    _dragState = { mode: 'resize', startX: pt.x, startY: pt.y, origW: w, origX: x, origY: y };
    document.addEventListener('mousemove', _onMouseMove);
    document.addEventListener('mouseup', _onMouseUp);
  }
  // Minimum sliver (canvas units) that must stay on-canvas so the layer is
  // never fully lost off-screen and can always be dragged back — beyond
  // that, moving/resizing past the edges is allowed and simply gets
  // cropped by the canvas (and, on export, by the backend compositor).
  var MIN_VISIBLE = 30;

  function _onMouseMove(ev) {
    if (!_dragState) return;
    var pt = _svgPoint(ev);
    var dx = pt.x - _dragState.startX;
    var dy = pt.y - _dragState.startY;
    if (_dragState.mode === 'move') {
      x = Math.max(MIN_VISIBLE - w, Math.min(_dragState.origX + dx, 1000 - MIN_VISIBLE));
      y = Math.max(MIN_VISIBLE - h, Math.min(_dragState.origY + dy, _cvH - MIN_VISIBLE));
    } else {
      var newW = Math.max(20, _dragState.origW + dx);
      w = newW;
      h = w / _layerAspect;
    }
    _renderCanvas();
  }
  function _onMouseUp() {
    _dragState = null;
    document.removeEventListener('mousemove', _onMouseMove);
    document.removeEventListener('mouseup', _onMouseUp);
  }

  editBtn.addEventListener('click', async function () {
    if (!_hasModal) return;
    var bgUrl = _bgUrl(), layerUrl = _layerUrl();
    if (!bgUrl || !layerUrl) return;

    var _bgDims = await _loadImageDims(bgUrl);
    var _layerDims = await _loadImageDims(layerUrl);
    _bgAspect = (_bgDims && _bgDims.h) ? (_bgDims.w / _bgDims.h) : 1;
    _layerAspect = (_layerDims && _layerDims.h) ? (_layerDims.w / _layerDims.h) : 1;
    _cvH = _bgAspect ? Math.round(1000 / _bgAspect) : 1000;

    var t = _transform || DEFAULT_TRANSFORM;
    w = t.w_frac * 1000;
    h = w / _layerAspect;
    x = t.x_frac * 1000;
    y = t.y_frac * _cvH;
    // Keep at least a sliver reachable even if a previous aspect ratio no
    // longer fits — but otherwise allow it to sit partly off-canvas, since
    // that's a valid (cropped) composition.
    x = Math.max(MIN_VISIBLE - w, Math.min(x, 1000 - MIN_VISIBLE));
    y = Math.max(MIN_VISIBLE - h, Math.min(y, _cvH - MIN_VISIBLE));

    // Restore lighting controls from whatever was last applied (or defaults).
    if (_hasLightingPanel) {
      var lt = _lighting || DEFAULT_LIGHTING;
      brightnessInput.value = lt.brightness;
      brightnessValEl.textContent = String(lt.brightness);
      warmthInput.value = lt.warmth;
      warmthValEl.textContent = String(lt.warmth);
      if (_hasHueControl) {
        hueInput.value = lt.hue || 0;
        hueValEl.textContent = String(lt.hue || 0);
      }
      matchEnabledInput.checked = !!lt.match_enabled;
      matchStrengthInput.value = lt.match_strength;
      matchStrengthValEl.textContent = String(lt.match_strength);
      matchStrengthRow.hidden = !lt.match_enabled;
      _previewLayerUrl = null;
      if (lt.brightness || lt.warmth || lt.hue || lt.match_enabled) _schedulePreview();
    }

    _renderCanvas();
    modalEl.hidden = false;
    document.body.style.overflow = 'hidden';
  });

  function _closeModal() {
    modalEl.hidden = true;
    document.body.style.overflow = '';
    _dragState = null;
  }
  if (_hasModal) modalClose.addEventListener('click', _closeModal);
  if (_hasModal) modalEl.addEventListener('click', function (ev) {
    if (ev.target === modalEl) _closeModal();
  });
  if (_hasModal) modalApply.addEventListener('click', function () {
    _transform = { x_frac: x / 1000, y_frac: y / _cvH, w_frac: w / 1000 };
    setVal(stepDef.id, 'transform', _transform);
    if (_hasLightingPanel) {
      _lighting = {
        brightness: Number(brightnessInput.value) || 0,
        warmth: Number(warmthInput.value) || 0,
        hue: _hasHueControl ? (Number(hueInput.value) || 0) : 0,
        match_enabled: !!matchEnabledInput.checked,
        match_strength: Number(matchStrengthInput.value) || 0.3,
      };
      setVal(stepDef.id, 'lighting', _lighting);
    }
    _refreshPreview();
    updateGenerateBtn();
    _closeModal();
  });
}
