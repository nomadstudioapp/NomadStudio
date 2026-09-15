'use strict';
// Canvas Composer — bringing images in: file picker + native OS drag & drop.

window.CC = window.CC || {};

(function (CC) {
  function loadImageFile(file) {
    if (!file || file.type.indexOf('image/') !== 0) return;
    var url = URL.createObjectURL(file);
    var img = new Image();
    img.onload = function () { CC.createLayer(img, url); };
    img.onerror = function () { URL.revokeObjectURL(url); };
    img.src = url;
  }

  function loadFileList(files) {
    Array.prototype.forEach.call(files || [], loadImageFile);
  }

  CC.initImport = function () {
    var addBtn = document.getElementById('cc-add-image-btn');
    var fileInput = document.getElementById('cc-file-input');
    var stage = CC.getStage();

    addBtn.addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () {
      loadFileList(fileInput.files);
      fileInput.value = '';
    });

    var dragDepth = 0;
    stage.addEventListener('dragenter', function (ev) {
      ev.preventDefault();
      dragDepth++;
      stage.classList.add('cc-drag-over');
    });
    stage.addEventListener('dragover', function (ev) { ev.preventDefault(); });
    stage.addEventListener('dragleave', function () {
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) stage.classList.remove('cc-drag-over');
    });
    stage.addEventListener('drop', function (ev) {
      ev.preventDefault();
      dragDepth = 0;
      stage.classList.remove('cc-drag-over');

      var trayUrl = ev.dataTransfer && ev.dataTransfer.getData('application/x-cc-tray-url');
      if (trayUrl) {
        var pt = CC.stagePoint(ev);
        CC.addTrayImageAt(trayUrl, pt.x, pt.y);
        return;
      }

      var files = ev.dataTransfer && ev.dataTransfer.files;
      loadFileList(files);
    });
  };
})(window.CC);
