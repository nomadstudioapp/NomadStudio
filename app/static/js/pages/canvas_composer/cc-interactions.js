'use strict';
// Canvas Composer — selection, drag/resize, and the right-click context menu.

window.CC = window.CC || {};

(function (CC) {
  var MIN_SIZE = 20;
  var stagePoint = CC.stagePoint;

  function layerFromEvent(ev) {
    var el = ev.target.closest ? ev.target.closest('.cc-layer') : null;
    if (!el) return null;
    return CC.getLayer(Number(el.dataset.ccLayerId));
  }

  // ── Move / resize drag state ──────────────────────────────────────────
  var _drag = null; // { mode: 'move'|'resize', layer, corner, startX, startY, origX, origY, origW, origH }

  function onStageMouseDown(ev) {
    var handle = ev.target.closest ? ev.target.closest('.cc-handle') : null;
    if (handle) {
      var layerEl = handle.closest('.cc-layer');
      var layer = CC.getLayer(Number(layerEl.dataset.ccLayerId));
      if (!layer || layer.locked) return;
      ev.preventDefault();
      CC.selectLayer(layer.id);
      var pt = stagePoint(ev);
      _drag = {
        mode: 'resize', layer: layer, corner: handle.dataset.corner,
        startX: pt.x, startY: pt.y,
        origX: layer.x, origY: layer.y, origW: layer.w, origH: layer.h,
      };
      document.addEventListener('mousemove', onDocMouseMove);
      document.addEventListener('mouseup', onDocMouseUp);
      return;
    }

    var layer2 = layerFromEvent(ev);
    if (layer2) {
      CC.selectLayer(layer2.id);
      if (layer2.locked) return;
      ev.preventDefault();
      var pt2 = stagePoint(ev);
      _drag = { mode: 'move', layer: layer2, startX: pt2.x, startY: pt2.y, origX: layer2.x, origY: layer2.y };
      document.addEventListener('mousemove', onDocMouseMove);
      document.addEventListener('mouseup', onDocMouseUp);
      return;
    }

    // Clicked empty canvas — deselect
    CC.deselect();
  }

  function onDocMouseMove(ev) {
    if (!_drag) return;
    var pt = stagePoint(ev);
    var dx = pt.x - _drag.startX;
    var dy = pt.y - _drag.startY;
    var layer = _drag.layer;

    if (_drag.mode === 'move') {
      // No clamp: a layer may be dragged past any edge — recalcStageBounds()
      // grows the canvas to fit it once the drag ends, instead of cropping it.
      layer.x = _drag.origX + dx;
      layer.y = _drag.origY + dy;
    } else {
      var corner = _drag.corner;
      var anchor;
      if (corner === 'se') anchor = { x: _drag.origX, y: _drag.origY };
      else if (corner === 'sw') anchor = { x: _drag.origX + _drag.origW, y: _drag.origY };
      else if (corner === 'ne') anchor = { x: _drag.origX, y: _drag.origY + _drag.origH };
      else anchor = { x: _drag.origX + _drag.origW, y: _drag.origY + _drag.origH }; // nw

      var newW = Math.max(MIN_SIZE, Math.abs(pt.x - anchor.x));
      var newH = newW / layer.aspect;

      if (corner === 'se') { layer.x = anchor.x; layer.y = anchor.y; }
      else if (corner === 'sw') { layer.x = anchor.x - newW; layer.y = anchor.y; }
      else if (corner === 'ne') { layer.x = anchor.x; layer.y = anchor.y - newH; }
      else { layer.x = anchor.x - newW; layer.y = anchor.y - newH; }

      layer.w = newW;
      layer.h = newH;
    }
    CC.renderLayer(layer);
  }

  function onDocMouseUp() {
    _drag = null;
    document.removeEventListener('mousemove', onDocMouseMove);
    document.removeEventListener('mouseup', onDocMouseUp);
    CC.recalcStageBounds();
  }

  // ── Context menu ─────────────────────────────────────────────────────
  var menuEl, positionEl, radiusInput, rotationInput, opacityInput;
  var _menuLayerId = null; // null = "empty canvas" menu

  var LAYER_ONLY_ACTIONS = ['bring-front', 'raise', 'lower', 'send-back', 'lock', 'lock-others', 'delete'];

  function closeMenu() {
    if (!menuEl) return;
    menuEl.hidden = true;
    menuEl.setAttribute('aria-hidden', 'true');
    _menuLayerId = null;
  }

  function setItemVisible(action, visible) {
    var el = menuEl.querySelector('[data-cc-action="' + action + '"]');
    if (el) el.hidden = !visible;
  }

  function openMenuForLayer(layer, clientX, clientY) {
    _menuLayerId = layer.id;
    CC.selectLayer(layer.id);

    if (layer.locked) {
      LAYER_ONLY_ACTIONS.forEach(function (a) { setItemVisible(a, false); });
      setItemVisible('unlock', true);
      setItemVisible('unlock-all', false);
      positionEl.hidden = true;
      radiusInput.closest('.cc-ctx-slider-row').hidden = true;
      rotationInput.closest('.cc-ctx-slider-row').hidden = true;
      opacityInput.closest('.cc-ctx-slider-row').hidden = true;
    } else {
      LAYER_ONLY_ACTIONS.forEach(function (a) { setItemVisible(a, true); });
      setItemVisible('unlock', false);
      setItemVisible('unlock-all', false);
      var total = CC.layers.length;
      var position = total - CC.zIndexOf(layer.id);
      positionEl.hidden = false;
      positionEl.textContent = position + ' of ' + total;
      radiusInput.closest('.cc-ctx-slider-row').hidden = false;
      rotationInput.closest('.cc-ctx-slider-row').hidden = false;
      opacityInput.closest('.cc-ctx-slider-row').hidden = false;
      radiusInput.value = String(Math.round(layer.radiusFrac * 100));
      rotationInput.value = String(Math.round(layer.rotation || 0));
      opacityInput.value = String(Math.round(layer.opacity * 100));
    }
    showMenuAt(clientX, clientY);
  }

  function openMenuForEmptyCanvas(clientX, clientY) {
    _menuLayerId = null;
    CC.deselect();
    LAYER_ONLY_ACTIONS.forEach(function (a) { setItemVisible(a, false); });
    setItemVisible('unlock', false);
    setItemVisible('unlock-all', true);
    positionEl.hidden = true;
    radiusInput.closest('.cc-ctx-slider-row').hidden = true;
    rotationInput.closest('.cc-ctx-slider-row').hidden = true;
    opacityInput.closest('.cc-ctx-slider-row').hidden = true;
    showMenuAt(clientX, clientY);
  }

  function showMenuAt(clientX, clientY) {
    menuEl.hidden = false;
    menuEl.setAttribute('aria-hidden', 'false');
    var maxX = window.innerWidth - menuEl.offsetWidth - 8;
    var maxY = window.innerHeight - menuEl.offsetHeight - 8;
    menuEl.style.left = Math.max(4, Math.min(clientX, maxX)) + 'px';
    menuEl.style.top = Math.max(4, Math.min(clientY, maxY)) + 'px';
  }

  function onContextMenu(ev) {
    var stage = CC.getStage();
    if (!stage.contains(ev.target) && ev.target !== stage) return;
    ev.preventDefault();
    var layer = layerFromEvent(ev);
    if (layer) openMenuForLayer(layer, ev.clientX, ev.clientY);
    else openMenuForEmptyCanvas(ev.clientX, ev.clientY);
  }

  function onMenuAction(ev) {
    var btn = ev.target.closest ? ev.target.closest('[data-cc-action]') : null;
    if (!btn || btn.hidden) return;
    var action = btn.dataset.ccAction;
    var id = _menuLayerId;
    switch (action) {
      case 'bring-front': CC.bringToFront(id); break;
      case 'raise': CC.raiseOne(id); break;
      case 'lower': CC.lowerOne(id); break;
      case 'send-back': CC.sendToBack(id); break;
      case 'lock': CC.lockLayer(id, true); break;
      case 'unlock': CC.lockLayer(id, false); break;
      case 'lock-others': CC.lockAllExcept(id); break;
      case 'unlock-all': CC.unlockAll(); break;
      case 'delete': CC.removeLayer(id); break;
    }
    closeMenu();
  }

  function onRadiusInput() {
    if (_menuLayerId == null) return;
    var layer = CC.getLayer(_menuLayerId);
    if (!layer) return;
    layer.radiusFrac = Number(radiusInput.value) / 100;
    CC.renderLayer(layer);
  }

  function onRotationInput() {
    if (_menuLayerId == null) return;
    var layer = CC.getLayer(_menuLayerId);
    if (!layer) return;
    layer.rotation = Number(rotationInput.value);
    CC.renderLayer(layer);
  }

  function onOpacityInput() {
    if (_menuLayerId == null) return;
    var layer = CC.getLayer(_menuLayerId);
    if (!layer) return;
    layer.opacity = Number(opacityInput.value) / 100;
    CC.renderLayer(layer);
  }

  CC.initInteractions = function () {
    var stage = CC.getStage();
    stage.addEventListener('mousedown', onStageMouseDown);
    document.addEventListener('contextmenu', onContextMenu);

    // Lock badges live in #cc-lock-overlay, a sibling of #cc-stage (see
    // CC.renderLockOverlay in cc-layer.js) — a single click there unlocks
    // + selects the layer, same as before, just wired to the new element.
    var lockOverlay = document.getElementById('cc-lock-overlay');
    if (lockOverlay) {
      lockOverlay.addEventListener('mousedown', function (ev) {
        var badge = ev.target.closest ? ev.target.closest('.cc-lock-badge') : null;
        if (!badge) return;
        ev.preventDefault();
        ev.stopPropagation();
        var id = Number(badge.dataset.ccLayerId);
        CC.lockLayer(id, false);
        CC.selectLayer(id);
      });
    }

    menuEl = document.getElementById('cc-ctx-menu');
    positionEl = document.getElementById('cc-ctx-position');
    radiusInput = document.getElementById('cc-ctx-radius');
    rotationInput = document.getElementById('cc-ctx-rotation');
    opacityInput = document.getElementById('cc-ctx-opacity');

    menuEl.addEventListener('click', onMenuAction);
    radiusInput.addEventListener('input', onRadiusInput);
    rotationInput.addEventListener('input', onRotationInput);
    opacityInput.addEventListener('input', onOpacityInput);

    document.addEventListener('mousedown', function (ev) {
      if (!menuEl.hidden && !menuEl.contains(ev.target)) closeMenu();
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') closeMenu();
    });
  };
})(window.CC);
