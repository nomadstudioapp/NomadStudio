'use strict';
// Canvas Composer — save/load a whole composition as a .zip on the user's
// own computer (manifest.json + one PNG per layer, via cc-zip.js). This is
// separate from "Export PNG": export flattens to a final image, save/load
// preserves the editable state (every layer's own position, size, lock,
// opacity, corner radius) — fully local, nothing touches the server.

window.CC = window.CC || {};

(function (CC) {
  // Re-encodes a layer's already-loaded image element at full resolution —
  // needed because layer.fullUrl may be an ephemeral blob: URL (local file
  // uploads, or a previously loaded composition) that has no meaning once
  // this session/tab ends. fullImgEl specifically (not imgEl, which is a
  // capped-size on-canvas proxy since cc-layer.js's createLayer/restoreLayer
  // downscale it for GPU/memory headroom — see CC.PREVIEW_MAX_DIM) — this
  // save is meant to preserve full quality for later re-editing.
  function layerPngBytes(layer) {
    var c = document.createElement('canvas');
    c.width = layer.naturalW;
    c.height = layer.naturalH;
    c.getContext('2d').drawImage(layer.fullImgEl, 0, 0, layer.naturalW, layer.naturalH);
    var dataUrl = c.toDataURL('image/png');
    var binary = atob(dataUrl.split(',')[1]);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function safeFilename(name) {
    return (name || 'composition').replace(/[^a-z0-9\-_]+/gi, '_').slice(0, 80) || 'composition';
  }

  function saveComposition() {
    if (!CC.layers.length) return;
    var name = window.prompt('Composition name:', 'composition');
    if (name == null) return; // cancelled

    var manifestLayers = [];
    var entries = [];
    CC.layers.forEach(function (layer, i) {
      var filename = 'layer_' + i + '.png';
      entries.push({ name: filename, bytes: layerPngBytes(layer) });
      manifestLayers.push({
        image: filename,
        x: layer.x, y: layer.y, w: layer.w, h: layer.h,
        radiusFrac: layer.radiusFrac, opacity: layer.opacity, rotation: layer.rotation,
        locked: layer.locked,
      });
    });

    var manifest = {
      name: name,
      stageW: CC.STAGE_W,
      stageH: CC.STAGE_H,
      growMode: CC.growMode,
      savedAt: new Date().toISOString(),
      layers: manifestLayers,
    };
    entries.push({ name: 'manifest.json', bytes: new TextEncoder().encode(JSON.stringify(manifest, null, 2)) });

    var blob = CC.zipCreate(entries);
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = safeFilename(name) + '.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function loadImageFromBlobUrl(url) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = reject;
      img.src = url;
    });
  }

  function loadZipFile(file) {
    file.arrayBuffer()
      .then(function (buf) {
        var entries = CC.zipRead(buf);
        var manifestBytes = entries['manifest.json'];
        if (!manifestBytes) throw new Error('manifest.json not found in the .zip');
        var manifest = JSON.parse(new TextDecoder().decode(manifestBytes));

        CC.clearAll();
        CC.STAGE_W = manifest.stageW || 1080;
        CC.STAGE_H = manifest.stageH || 1080;
        CC.growMode = manifest.growMode || 'auto';
        CC.applyStageSize();

        // Images decode in parallel for speed, but browsers finish decoding
        // in whatever order completes first — not the manifest's saved
        // z-order. restoreLayer must run in manifest order regardless of
        // load-completion order, or the stacking order gets scrambled (a
        // large/slow-to-decode background layer can finish last and end up
        // painted on top, hiding everything beneath it).
        var loads = (manifest.layers || []).map(function (layerData) {
          var imgBytes = entries[layerData.image];
          if (!imgBytes) return null;
          var blob = new Blob([imgBytes], { type: 'image/png' });
          var url = URL.createObjectURL(blob);
          return loadImageFromBlobUrl(url).then(function (img) {
            return { img: img, url: url, layerData: layerData };
          });
        }).filter(Boolean);

        return Promise.all(loads).then(function (loaded) {
          loaded.forEach(function (l) {
            CC.restoreLayer(l.img, l.url, l.layerData);
          });
        });
      })
      .then(function () {
        CC.renderAll();
        if (CC.fitStage) CC.fitStage();
      })
      .catch(function (err) {
        window.alert('Could not load composition: ' + (err && err.message ? err.message : err));
      });
  }

  CC.initSaveLoad = function () {
    var saveBtn = document.getElementById('cc-save-btn');
    var loadBtn = document.getElementById('cc-load-btn');
    var loadFileInput = document.getElementById('cc-load-file-input');
    if (!saveBtn || !loadBtn || !loadFileInput) return;

    saveBtn.addEventListener('click', saveComposition);
    loadBtn.addEventListener('click', function () { loadFileInput.click(); });
    loadFileInput.addEventListener('change', function () {
      var file = loadFileInput.files && loadFileInput.files[0];
      loadFileInput.value = '';
      if (file) loadZipFile(file);
    });
  };
})(window.CC);
