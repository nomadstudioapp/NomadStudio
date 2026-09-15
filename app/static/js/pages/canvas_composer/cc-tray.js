'use strict';
// Canvas Composer — left panel listing the user's image Tray (the shared
// "send to tray" collection used elsewhere in Nomad Studio), so images
// already in the app can be dropped straight onto the canvas instead of
// only accepting fresh uploads from the OS file system.

window.CC = window.CC || {};

(function (CC) {
  function loadImageFromUrl(url) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = reject;
      img.src = url;
    });
  }

  // Adds a tray image centered on the canvas (click-to-add).
  function addTrayImageToCanvas(fullUrl) {
    loadImageFromUrl(fullUrl).then(function (img) {
      CC.createLayer(img, fullUrl);
    }).catch(function () {});
  }

  // Adds a tray image centered on a specific stage point (drag-and-drop).
  CC.addTrayImageAt = function (fullUrl, stageX, stageY) {
    loadImageFromUrl(fullUrl).then(function (img) {
      var layer = CC.createLayer(img, fullUrl);
      layer.x = stageX - layer.w / 2;
      layer.y = stageY - layer.h / 2;
      CC.renderLayer(layer);
      CC.recalcStageBounds();
    }).catch(function () {});
  };

  function renderTray(images, gridEl, emptyEl) {
    gridEl.innerHTML = '';
    if (!images.length) { emptyEl.hidden = false; return; }
    emptyEl.hidden = true;
    images.forEach(function (img) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'cc-tray-thumb';
      item.draggable = true;
      item.title = img.filename;

      var thumb = document.createElement('img');
      thumb.src = img.thumb_url;
      thumb.alt = img.filename;
      thumb.loading = 'lazy';
      item.appendChild(thumb);

      item.addEventListener('click', function () { addTrayImageToCanvas(img.url); });
      item.addEventListener('dragstart', function (ev) {
        ev.dataTransfer.setData('application/x-cc-tray-url', img.url);
        ev.dataTransfer.effectAllowed = 'copy';
      });

      gridEl.appendChild(item);
    });
  }

  function refreshTray() {
    var gridEl = document.getElementById('cc-tray-grid');
    var emptyEl = document.getElementById('cc-tray-empty');
    if (!gridEl) return;
    fetch('/api/images/tray')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderTray((data && data.images) || [], gridEl, emptyEl);
      })
      .catch(function () {});
  }

  CC.initTray = function () {
    var refreshBtn = document.getElementById('cc-tray-refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', refreshTray);
    refreshTray();
  };
})(window.CC);
