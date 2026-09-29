'use strict';

// Export actions for the generated-results rail. The full flow uses the
// existing session exporter so its ZIP contains images plus session.md,
// session.html and session.json; the image-only path stays intentionally small.

function _flowExportImages() {
  return (typeof sessionImages !== 'undefined' ? sessionImages : [])
    .filter(function (entry) { return entry && (typeof entry === 'string' || entry.url); })
    .map(function (entry) { return typeof entry === 'string' ? entry : entry.url; });
}

function _flowExportName() {
  var rootEl = document.getElementById('nsc-flow-root');
  var breadcrumb = document.getElementById('nsc-flow-breadcrumb');
  return (breadcrumb && breadcrumb.textContent.trim()) ||
    (rootEl && rootEl.getAttribute('data-flow-id')) || 'flow';
}

function _downloadFlowExport(blob, filename) {
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(function () { URL.revokeObjectURL(url); }, 0);
}

function _flowExportSnapshot() {
  var rootEl = document.getElementById('nsc-flow-root');
  var flowId = rootEl && rootEl.getAttribute('data-flow-id') || 'flow';
  var split = flowId.split('.');
  var snap = typeof _collectFlowSnapshot === 'function' ? _collectFlowSnapshot() : null;
  var images = _flowExportImages();
  var data = snap && snap.data || {};
  return {
    name: _flowExportName(),
    createdAt: new Date().toISOString(),
    steps: [{
      id: 'flow-export',
      flowLabel: _flowExportName(),
      flowCategory: split[0] || '',
      flowAction: split.slice(1).join('.') || '',
      params: data.params || { prompt: snap && snap.prompt || '' },
      images: images
    }]
  };
}

function _startFlowExport(url, payload, filename, button) {
  if (button) { button.disabled = true; button.classList.add('is-busy'); }
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(function (response) {
      if (!response.ok) return response.json().catch(function () { return {}; }).then(function (data) {
        throw new Error(data.error || 'Export failed (' + response.status + ')');
      });
      return response.blob();
    })
    .then(function (blob) { _downloadFlowExport(blob, filename); closeOptionsPanel(); })
    .catch(function (err) { if (typeof showErrorToast === 'function') showErrorToast(err.message); else alert(err.message); })
    .finally(function () {
      if (button) { button.disabled = false; button.classList.remove('is-busy'); }
    });
}

function _openFlowExportPanel() {
  var images = _flowExportImages();
  openOptionsPanel(tF('Export'), function (body) {
    body.innerHTML =
      '<div class="nsc-options-menu ncf-export-panel">' +
        '<p class="ncf-export-panel-hint">' + escHtml(tF('Choose what to export from this flow.')) + '</p>' +
        '<button type="button" class="nsc-options-menu-item ncf-export-option" data-export-kind="flow">' +
          '<span class="nsc-options-menu-item-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></svg></span><span>' + escHtml(tF('Flow')) + '</span>' +
        '</button>' +
        '<button type="button" class="nsc-options-menu-item ncf-export-option" data-export-kind="images"' + (images.length ? '' : ' disabled') + '>' +
          '<span class="nsc-options-menu-item-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg></span><span>' + escHtml(tF('Images')) + '</span>' +
        '</button>' +
      '</div>';
    body.querySelector('[data-export-kind="flow"]').addEventListener('click', function (event) {
      _startFlowExport('/api/session/export', _flowExportSnapshot(), _flowExportName().replace(/\s+/g, '-').toLowerCase() + '.zip', event.currentTarget);
    });
    body.querySelector('[data-export-kind="images"]').addEventListener('click', function (event) {
      _startFlowExport('/api/flow/export-images', { name: _flowExportName(), images: images }, _flowExportName().replace(/\s+/g, '-').toLowerCase() + '-images.zip', event.currentTarget);
    });
  });
}

(function bindFlowExportButton() {
  var button = document.getElementById('ncf-gallery-export-btn');
  if (!button || button.dataset.exportBound) return;
  button.dataset.exportBound = '1';
  button.addEventListener('click', _openFlowExportPanel);
})();
