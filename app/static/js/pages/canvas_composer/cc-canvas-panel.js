'use strict';
// Canvas Composer — left-panel "Canvas" section: current dimensions, the
// Auto/Locked growth-mode toggle, "Crop canvas to image", and the
// center-horizontal/center-vertical alignment actions.

window.CC = window.CC || {};

(function (CC) {
  var dimsEl, autoBtn, lockedBtn, cropBtn, alignHBtn, alignVBtn;

  function updateDims() {
    if (dimsEl) dimsEl.textContent = Math.round(CC.STAGE_W) + ' × ' + Math.round(CC.STAGE_H) + ' px';
  }

  function updateModeButtons() {
    autoBtn.classList.toggle('active', CC.growMode === 'auto');
    lockedBtn.classList.toggle('active', CC.growMode === 'locked');
  }

  // Crop and both align actions only make sense with a layer selected.
  function updateSelectionDependentButtons() {
    var disabled = CC.selectedId == null;
    cropBtn.disabled = disabled;
    alignHBtn.disabled = disabled;
    alignVBtn.disabled = disabled;
  }

  function setGrowMode(mode) {
    CC.growMode = mode;
    updateModeButtons();
  }

  CC.initCanvasPanel = function () {
    dimsEl = document.getElementById('cc-canvas-dims');
    autoBtn = document.getElementById('cc-canvas-mode-auto');
    lockedBtn = document.getElementById('cc-canvas-mode-locked');
    cropBtn = document.getElementById('cc-crop-to-image-btn');
    alignHBtn = document.getElementById('cc-align-h-btn');
    alignVBtn = document.getElementById('cc-align-v-btn');
    if (!dimsEl || !autoBtn || !lockedBtn || !cropBtn || !alignHBtn || !alignVBtn) return;

    autoBtn.addEventListener('click', function () { setGrowMode('auto'); });
    lockedBtn.addEventListener('click', function () { setGrowMode('locked'); });
    cropBtn.addEventListener('click', function () {
      if (CC.selectedId != null) CC.cropStageToLayer(CC.selectedId);
    });
    alignHBtn.addEventListener('click', function () {
      if (CC.selectedId != null) CC.centerLayerHorizontally(CC.selectedId);
    });
    alignVBtn.addEventListener('click', function () {
      if (CC.selectedId != null) CC.centerLayerVertically(CC.selectedId);
    });

    document.addEventListener('cc:stage-resized', updateDims);
    document.addEventListener('cc:selection-changed', updateSelectionDependentButtons);

    updateDims();
    updateModeButtons();
    updateSelectionDependentButtons();
  };
})(window.CC);
