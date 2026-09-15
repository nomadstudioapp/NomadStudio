'use strict';
// Canvas Composer — entry point: fits the stage to the viewport and wires
// up the other cc-*.js modules once the page has loaded.

(function () {
  function fitStage() {
    var viewport = document.getElementById('cc-stage-viewport');
    var stage = document.getElementById('cc-stage');
    if (!viewport || !stage) return;
    var wrap = viewport.parentElement; // .cc-body
    var CC = window.CC;
    var availW = wrap.clientWidth - 48;
    var availH = wrap.clientHeight - 48;
    var scale = Math.max(0.05, Math.min(1, Math.min(availW / CC.STAGE_W, availH / CC.STAGE_H)));
    stage.style.transform = 'scale(' + scale + ')';
    viewport.style.width = (CC.STAGE_W * scale) + 'px';
    viewport.style.height = (CC.STAGE_H * scale) + 'px';
    if (CC.renderLockOverlay) CC.renderLockOverlay();
  }

  document.addEventListener('DOMContentLoaded', function () {
    window.CC.fitStage = fitStage;
    window.CC.initCanvasPanel();
    window.CC.applyStageSize();
    window.CC.initInteractions();
    window.CC.initImport();
    window.CC.initTray();
    window.CC.initExport();
    window.CC.initSaveLoad();
    fitStage();
    window.addEventListener('resize', fitStage);
  });
})();
