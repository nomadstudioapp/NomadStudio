'use strict';
// Canvas Composer — layer data model + DOM rendering.
// Internal coordinate space: 0..CC.STAGE_SIZE on both axes, 1:1 with the
// exported PNG's pixel size. CSS scales the whole #cc-stage element to fit
// the viewport (transform: scale), so getBoundingClientRect() on the stage
// always reflects the current on-screen scale — pointer math never needs to
// know the scale factor itself, just the stage's own rect.

window.CC = window.CC || {};

(function (CC) {
  CC.STAGE_W = 1080;
  CC.STAGE_H = 1080;
  CC.STAGE_MIN = 200;      // never shrinks the stage below this on an axis
  CC.DEFAULT_MAX_DIM = 420; // default on-canvas size for newly added images
  CC.growMode = 'auto';    // 'auto' | 'locked' — see recalcStageBounds

  // Every layer's on-canvas image (CSS background while dragging/resizing,
  // and the source drawImage() reads from at export unless "Maximum
  // quality" is checked) is capped to this on its long side — a photo or a
  // UHD generation can be several times bigger than anything the stage
  // itself will ever show, and holding + compositing that full-res bitmap
  // for every layer is what actually costs the GPU/memory, not the drag
  // interaction itself. The untouched original is kept alongside it
  // (layer.fullImgEl/fullUrl) for the "Maximum quality" export option and
  // for Save-composition (cc-save.js), which always wants full fidelity.
  CC.PREVIEW_MAX_DIM = 2048;

  CC.layers = [];      // z-order back → front
  CC.selectedId = null;
  CC._nextId = 1;

  CC.getStage = function () {
    return document.getElementById('cc-stage');
  };

  // Maps a mouse/pointer event to stage-unit coordinates (0..STAGE_W,
  // 0..STAGE_H), independent of the CSS transform:scale() fit-to-viewport
  // factor — getBoundingClientRect() already reflects it.
  CC.stagePoint = function (ev) {
    var rect = CC.getStage().getBoundingClientRect();
    return {
      x: ((ev.clientX - rect.left) / rect.width) * CC.STAGE_W,
      y: ((ev.clientY - rect.top) / rect.height) * CC.STAGE_H,
    };
  };

  CC.applyStageSize = function () {
    var stage = CC.getStage();
    stage.style.width = CC.STAGE_W + 'px';
    stage.style.height = CC.STAGE_H + 'px';
    document.dispatchEvent(new CustomEvent('cc:stage-resized'));
  };

  // Grows the stage (never shrinks) to contain every layer's full extent.
  // Growth on the left/top requires shifting every layer's x/y so nothing
  // ends up at a negative coordinate — this preserves each layer's position
  // relative to the others, it just moves the shared (0,0) origin.
  // Grow-only, and only called on interaction end (mouseup / after adding a
  // layer) rather than during a live drag, so the canvas never jumps under
  // the pointer mid-gesture.
  // No-op entirely when growMode is 'locked' (canvas panel toggle) — the
  // canvas then behaves like a fixed frame and simply clips overflow.
  CC.recalcStageBounds = function () {
    if (CC.growMode === 'locked') return;
    if (!CC.layers.length) return;
    var minX = 0, minY = 0, maxX = CC.STAGE_W, maxY = CC.STAGE_H;
    CC.layers.forEach(function (l) {
      minX = Math.min(minX, l.x);
      minY = Math.min(minY, l.y);
      maxX = Math.max(maxX, l.x + l.w);
      maxY = Math.max(maxY, l.y + l.h);
    });
    var shiftX = Math.max(0, -minX);
    var shiftY = Math.max(0, -minY);
    if (shiftX > 0 || shiftY > 0) {
      CC.layers.forEach(function (l) { l.x += shiftX; l.y += shiftY; });
      maxX += shiftX; maxY += shiftY;
    }
    var newW = Math.max(CC.STAGE_MIN, Math.ceil(maxX));
    var newH = Math.max(CC.STAGE_MIN, Math.ceil(maxY));
    var changed = shiftX > 0 || shiftY > 0 || newW !== CC.STAGE_W || newH !== CC.STAGE_H;
    if (!changed) return;
    CC.STAGE_W = newW;
    CC.STAGE_H = newH;
    CC.applyStageSize();
    CC.renderAll();
    if (CC.fitStage) CC.fitStage();
  };

  // Manually crops the stage to exactly the given layer's current bounding
  // box — unlike recalcStageBounds this can shrink the canvas, and it's an
  // explicit, on-demand action (the "Crop canvas to image" button), not
  // something that runs automatically after every move/resize.
  CC.cropStageToLayer = function (id) {
    var layer = CC.getLayer(id);
    if (!layer) return;
    var shiftX = -layer.x, shiftY = -layer.y;
    CC.layers.forEach(function (l) { l.x += shiftX; l.y += shiftY; });
    CC.STAGE_W = Math.max(CC.STAGE_MIN, Math.round(layer.w));
    CC.STAGE_H = Math.max(CC.STAGE_MIN, Math.round(layer.h));
    CC.applyStageSize();
    CC.renderAll();
    if (CC.fitStage) CC.fitStage();
  };

  // Centers the given layer on the canvas along one axis, leaving the other
  // axis untouched — the "Centrar horizontal" / "Centrar vertical" buttons.
  CC.centerLayerHorizontally = function (id) {
    var layer = CC.getLayer(id);
    if (!layer) return;
    layer.x = (CC.STAGE_W - layer.w) / 2;
    CC.renderLayer(layer);
    CC.recalcStageBounds();
  };

  CC.centerLayerVertically = function (id) {
    var layer = CC.getLayer(id);
    if (!layer) return;
    layer.y = (CC.STAGE_H - layer.h) / 2;
    CC.renderLayer(layer);
    CC.recalcStageBounds();
  };

  CC.getLayer = function (id) {
    for (var i = 0; i < CC.layers.length; i++) {
      if (CC.layers[i].id === id) return CC.layers[i];
    }
    return null;
  };

  // Downscales imgEl to fit within CC.PREVIEW_MAX_DIM (canvas-drawn, so no
  // extra Image-decode round trip is needed — a <canvas> is itself a valid
  // drawImage() source) and returns { imgEl, url } for on-canvas use.
  // Already-small images pass through untouched (same object/url back,
  // `scaled: false`) — no point holding a second copy of a 400px image.
  function _makePreview(imgEl, url, naturalW, naturalH) {
    var longSide = Math.max(naturalW, naturalH);
    if (longSide <= CC.PREVIEW_MAX_DIM) return { imgEl: imgEl, url: url, scaled: false };
    var scale = CC.PREVIEW_MAX_DIM / longSide;
    var cw = Math.max(1, Math.round(naturalW * scale));
    var ch = Math.max(1, Math.round(naturalH * scale));
    var canvas = document.createElement('canvas');
    canvas.width = cw;
    canvas.height = ch;
    canvas.getContext('2d').drawImage(imgEl, 0, 0, cw, ch);
    // JPEG, not PNG: these are only ever composited on-screen or drawImage'd
    // again at export, never re-encoded/downloaded on their own — the
    // smaller memory footprint matters more here than lossless pixels
    // (Maximum quality skips this proxy entirely, see cc-export.js).
    return { imgEl: canvas, url: canvas.toDataURL('image/jpeg', 0.92), scaled: true };
  }

  CC.createLayer = function (imgEl, url) {
    var naturalW = imgEl.naturalWidth || 1;
    var naturalH = imgEl.naturalHeight || 1;
    var aspect = naturalW / naturalH;
    var w, h;
    if (aspect >= 1) { w = CC.DEFAULT_MAX_DIM; h = w / aspect; }
    else { h = CC.DEFAULT_MAX_DIM; w = h * aspect; }

    var preview = _makePreview(imgEl, url, naturalW, naturalH);
    var layer = {
      id: CC._nextId++,
      imgEl: preview.imgEl,
      url: preview.url,
      fullImgEl: imgEl,
      fullUrl: url,
      naturalW: naturalW,
      naturalH: naturalH,
      aspect: aspect,
      x: (CC.STAGE_W - w) / 2,
      y: (CC.STAGE_H - h) / 2,
      w: w,
      h: h,
      radiusFrac: 0,
      opacity: 1,
      rotation: 0, // degrees, -180..180
      locked: false,
      el: null,
    };
    CC.layers.push(layer);
    CC._mountLayer(layer);
    // renderAll (not just renderLayer) — it's the one that assigns z-index
    // based on array position. Without it the new layer's element keeps
    // z-index:auto, which stacks as if it were z-index 0 among siblings
    // that already have an explicit z-index from a prior renderAll, so it
    // would silently paint *behind* every existing layer.
    CC.renderAll();
    CC.recalcStageBounds();
    return layer;
  };

  // Recreates a layer with an explicit transform instead of the default
  // centered placement — used when restoring a saved composition (cc-save.js),
  // where every position/lock/opacity/radius must come back exactly as saved.
  // cc-save.js's own layerPngBytes() always re-encodes at full resolution
  // (see there), so imgEl/url handed in here are already the full original —
  // same downscale-for-preview treatment as createLayer applies to it.
  CC.restoreLayer = function (imgEl, url, props) {
    var naturalW = imgEl.naturalWidth || 1;
    var naturalH = imgEl.naturalHeight || 1;
    var preview = _makePreview(imgEl, url, naturalW, naturalH);
    var layer = {
      id: CC._nextId++,
      imgEl: preview.imgEl,
      url: preview.url,
      fullImgEl: imgEl,
      fullUrl: url,
      naturalW: naturalW,
      naturalH: naturalH,
      aspect: naturalW / naturalH,
      x: props.x, y: props.y, w: props.w, h: props.h,
      radiusFrac: props.radiusFrac || 0,
      opacity: props.opacity != null ? props.opacity : 1,
      rotation: props.rotation || 0,
      locked: !!props.locked,
      el: null,
    };
    CC.layers.push(layer);
    CC._mountLayer(layer);
    return layer;
  };

  // Wipes the canvas back to empty — used before loading a saved composition.
  CC.clearAll = function () {
    CC.layers.forEach(function (l) {
      if (l.el && l.el.parentNode) l.el.parentNode.removeChild(l.el);
    });
    CC.layers = [];
    CC.selectedId = null;
    CC._updateEmptyState();
    document.dispatchEvent(new CustomEvent('cc:selection-changed'));
  };

  CC._mountLayer = function (layer) {
    var el = document.createElement('div');
    el.className = 'cc-layer';
    el.dataset.ccLayerId = String(layer.id);

    var corners = ['nw', 'ne', 'sw', 'se'];
    var handles = {};
    corners.forEach(function (c) {
      var h = document.createElement('div');
      h.className = 'cc-handle';
      h.dataset.corner = c;
      h.hidden = true;
      el.appendChild(h);
      handles[c] = h;
    });

    layer.el = el;
    layer.handleEls = handles;
    CC.getStage().appendChild(el);
  };

  CC.renderLayer = function (layer) {
    if (!layer.el) return;
    var el = layer.el;
    el.style.left = layer.x + 'px';
    el.style.top = layer.y + 'px';
    el.style.width = layer.w + 'px';
    el.style.height = layer.h + 'px';
    el.style.backgroundImage = 'url("' + layer.url + '")';
    el.style.opacity = String(layer.opacity);
    el.style.transform = 'rotate(' + (layer.rotation || 0) + 'deg)';
    var minSide = Math.min(layer.w, layer.h);
    el.style.borderRadius = Math.round(layer.radiusFrac * minSide) + 'px';
    el.classList.toggle('cc-locked', !!layer.locked);
    el.classList.toggle('cc-selected', CC.selectedId === layer.id);
    var showHandles = CC.selectedId === layer.id && !layer.locked;
    Object.keys(layer.handleEls).forEach(function (c) {
      layer.handleEls[c].hidden = !showHandles;
    });
    CC.renderLockOverlay();
  };

  CC.renderAll = function () {
    var stage = CC.getStage();
    CC.layers.forEach(function (layer, i) {
      layer.el.style.zIndex = String(i + 1);
      // Re-append in z-order so DOM order also matches (keeps click/paint order sane)
      stage.appendChild(layer.el);
      CC.renderLayer(layer);
    });
    CC._updateEmptyState();
  };

  // Lock badges live in a sibling overlay OUTSIDE #cc-stage's overflow:hidden
  // clip — a locked layer near/over the stage edge used to hide its own
  // in-layer icon along with the clipped part of the image. The overlay is
  // sized to exactly cover the visually scaled stage (see cc-boot.js
  // fitStage), so stage-unit → overlay-pixel is just "* scale"; each badge
  // is then clamped to the overlay's own box so it's always reachable even
  // if the layer's corner itself is off-canvas.
  CC.renderLockOverlay = function () {
    var overlay = document.getElementById('cc-lock-overlay');
    var stage = CC.getStage();
    if (!overlay || !stage) return;
    var scale = stage.getBoundingClientRect().width / CC.STAGE_W || 1;
    var SIZE = 32, MARGIN = 6;
    var maxLeft = Math.max(0, overlay.clientWidth - SIZE);
    var maxTop = Math.max(0, overlay.clientHeight - SIZE);

    overlay.innerHTML = '';
    CC.layers.forEach(function (layer) {
      if (!layer.locked) return;
      var left = Math.max(0, Math.min((layer.x + layer.w) * scale - SIZE - MARGIN, maxLeft));
      var top = Math.max(0, Math.min(layer.y * scale + MARGIN, maxTop));

      var badge = document.createElement('button');
      badge.type = 'button';
      badge.className = 'cc-lock-badge';
      badge.dataset.ccLayerId = String(layer.id);
      badge.setAttribute('aria-label', tF('Unlock layer'));
      badge.style.left = left + 'px';
      badge.style.top = top + 'px';
      badge.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>';
      overlay.appendChild(badge);
    });
  };

  CC._updateEmptyState = function () {
    var stage = CC.getStage();
    stage.classList.toggle('cc-has-layers', CC.layers.length > 0);
    var exportBtn = document.getElementById('cc-export-btn');
    if (exportBtn) exportBtn.disabled = CC.layers.length === 0;
  };

  CC.removeLayer = function (id) {
    var layer = CC.getLayer(id);
    if (!layer) return;
    if (layer.el && layer.el.parentNode) layer.el.parentNode.removeChild(layer.el);
    CC.layers = CC.layers.filter(function (l) { return l.id !== id; });
    if (CC.selectedId === id) {
      CC.selectedId = null;
      document.dispatchEvent(new CustomEvent('cc:selection-changed'));
    }
    CC._updateEmptyState();
  };

  CC.selectLayer = function (id) {
    CC.selectedId = id;
    CC.layers.forEach(function (l) { CC.renderLayer(l); });
    document.dispatchEvent(new CustomEvent('cc:selection-changed'));
  };

  CC.deselect = function () {
    CC.selectedId = null;
    CC.layers.forEach(function (l) { CC.renderLayer(l); });
    document.dispatchEvent(new CustomEvent('cc:selection-changed'));
  };

  CC.zIndexOf = function (id) {
    for (var i = 0; i < CC.layers.length; i++) if (CC.layers[i].id === id) return i;
    return -1;
  };

  CC.bringToFront = function (id) {
    var i = CC.zIndexOf(id);
    if (i < 0 || i === CC.layers.length - 1) return;
    var layer = CC.layers.splice(i, 1)[0];
    CC.layers.push(layer);
    CC.renderAll();
  };

  CC.sendToBack = function (id) {
    var i = CC.zIndexOf(id);
    if (i <= 0) return;
    var layer = CC.layers.splice(i, 1)[0];
    CC.layers.unshift(layer);
    CC.renderAll();
  };

  CC.raiseOne = function (id) {
    var i = CC.zIndexOf(id);
    if (i < 0 || i === CC.layers.length - 1) return;
    var tmp = CC.layers[i + 1];
    CC.layers[i + 1] = CC.layers[i];
    CC.layers[i] = tmp;
    CC.renderAll();
  };

  CC.lowerOne = function (id) {
    var i = CC.zIndexOf(id);
    if (i <= 0) return;
    var tmp = CC.layers[i - 1];
    CC.layers[i - 1] = CC.layers[i];
    CC.layers[i] = tmp;
    CC.renderAll();
  };

  CC.lockLayer = function (id, locked) {
    var layer = CC.getLayer(id);
    if (!layer) return;
    layer.locked = locked;
    // Locking the selected layer also drops its selection — it's about to
    // go pointer-events:none, so its handles/outline shouldn't linger.
    if (locked && CC.selectedId === id) {
      CC.selectedId = null;
      document.dispatchEvent(new CustomEvent('cc:selection-changed'));
    }
    CC.renderLayer(layer);
  };

  CC.lockAllExcept = function (id) {
    CC.layers.forEach(function (l) { l.locked = l.id !== id; });
    CC.renderAll();
  };

  CC.unlockAll = function () {
    CC.layers.forEach(function (l) { l.locked = false; });
    CC.renderAll();
  };
})(window.CC);
