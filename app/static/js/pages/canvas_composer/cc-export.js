'use strict';
// Canvas Composer — flatten the stage to a single PNG.
// Literal, deterministic flatten: no generative post-processing (see task.md).

window.CC = window.CC || {};

(function (CC) {
  function roundedRectPath(ctx, x, y, w, h, r) {
    var maxR = Math.min(w, h) / 2;
    r = Math.max(0, Math.min(r, maxR));
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // maxQuality: draw each layer from its untouched original (fullImgEl)
  // instead of the capped on-canvas proxy (imgEl — see cc-layer.js's
  // CC.PREVIEW_MAX_DIM). The output canvas is still CC.STAGE_W×STAGE_H
  // either way — this doesn't change the export's pixel dimensions, only
  // how much real detail drawImage has to resample from, which matters
  // whenever a layer's on-stage size is bigger than the proxy (a photo
  // scaled up beyond ~2048px on the stage) or the extra fidelity of
  // resampling once from the source instead of from an already-shrunk
  // proxy is worth the slower draw.
  function flattenToCanvas(maxQuality) {
    var canvas = document.getElementById('cc-export-canvas');
    canvas.width = CC.STAGE_W;
    canvas.height = CC.STAGE_H;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    CC.layers.forEach(function (layer) {
      var minSide = Math.min(layer.w, layer.h);
      var r = layer.radiusFrac * minSide;
      var cx = layer.x + layer.w / 2;
      var cy = layer.y + layer.h / 2;
      var radians = (layer.rotation || 0) * Math.PI / 180;
      var src = (maxQuality && layer.fullImgEl) ? layer.fullImgEl : layer.imgEl;
      ctx.save();
      ctx.globalAlpha = layer.opacity;
      // Rotate around the layer's own center, matching the CSS
      // transform:rotate() (default transform-origin) used for the live
      // on-canvas preview — draw everything relative to that centered,
      // rotated frame instead of the layer's stage-space x/y.
      ctx.translate(cx, cy);
      ctx.rotate(radians);
      roundedRectPath(ctx, -layer.w / 2, -layer.h / 2, layer.w, layer.h, r);
      ctx.clip();
      ctx.drawImage(src, -layer.w / 2, -layer.h / 2, layer.w, layer.h);
      ctx.restore();
    });
    return canvas;
  }

  function downloadBlob(blob) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'canvas-composer-' + Date.now() + '.png';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function saveToSession(dataUrl) {
    fetch('/api/images/save-upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataUrl: dataUrl,
        filenamePrefix: 'canvas-composer',
        metadata: { source: 'canvas-composer' },
      }),
    }).catch(function () { /* session save is best-effort; the local download already succeeded */ });
  }

  CC.exportComposition = function () {
    if (!CC.layers.length) return;
    var maxQualityEl = document.getElementById('cc-export-max-quality');
    var canvas = flattenToCanvas(!!(maxQualityEl && maxQualityEl.checked));
    canvas.toBlob(function (blob) {
      if (!blob) return;
      downloadBlob(blob);
      saveToSession(canvas.toDataURL('image/png'));
    }, 'image/png');
  };

  CC.initExport = function () {
    document.getElementById('cc-export-btn').addEventListener('click', CC.exportComposition);
  };
})(window.CC);
