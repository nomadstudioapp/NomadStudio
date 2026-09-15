'use strict';
// UI helpers: applyMode, setMode, applyNcfZoom, persistNcfZoom

function applyMode(mode) {
  modeBtns.forEach(function (b) { b.classList.toggle('is-active', b.dataset.ncfMode === mode); });
  document.body.setAttribute('data-ns-mode', mode);
  document.dispatchEvent(new CustomEvent('ncf-mode-change', { detail: mode }));
}
function setMode(mode) { localStorage.setItem(NS_MODE_KEY, mode); applyMode(mode); }
modeBtns.forEach(function (b) { b.addEventListener('click', function () { setMode(b.dataset.ncfMode); }); });

// ── Results gallery zoom ───────────────────────────────────────────────────
var NCF_GRID_ZOOM_KEY  = 'oj-ncf-grid-zoom-v1';
var NCF_GRID_ZOOM_MIN  = 160;
var NCF_GRID_ZOOM_MAX  = 480;
var NCF_GRID_ZOOM_STEP = 40;
var ncfGridZoom        = 240;

function applyNcfZoom() {
  var bounded = Math.max(NCF_GRID_ZOOM_MIN, Math.min(NCF_GRID_ZOOM_MAX, ncfGridZoom));
  ncfGridZoom = bounded;
  if (resultsGrid) resultsGrid.style.setProperty('--ncf-grid-min', bounded + 'px');
  if (ncfZoomInBtn)  ncfZoomInBtn.disabled  = bounded >= NCF_GRID_ZOOM_MAX;
  if (ncfZoomOutBtn) ncfZoomOutBtn.disabled = bounded <= NCF_GRID_ZOOM_MIN;
}

function persistNcfZoom() {
  try { localStorage.setItem(NCF_GRID_ZOOM_KEY, String(ncfGridZoom)); } catch { /* ignore */ }
}

(function restoreNcfZoom() {
  try {
    var raw = Number(localStorage.getItem(NCF_GRID_ZOOM_KEY));
    if (Number.isFinite(raw) && raw > 0) ncfGridZoom = raw;
  } catch { /* ignore */ }
  applyNcfZoom();
})();

// dataset guard: page_runtime.js injects this script fresh on every SPA
// navigation into the flow page (document.body.appendChild), and only
// removes the <script> tag on the way out — it does NOT undo listeners
// already bound. Re-entering a flow N times without a full page reload
// would otherwise stack N click listeners on the same persistent button,
// which is exactly the "first click works, then needs two, then two
// again" pattern: with 2 listeners bound, half the "clicks" the user
// perceives are actually the 2nd of a pair firing back-to-back with no
// visible intermediate frame difference on a bounded/clamped value, and
// timing makes it look inconsistent. Guard against rebinding entirely.
if (ncfZoomInBtn && !ncfZoomInBtn.dataset.zoomBound) {
  ncfZoomInBtn.dataset.zoomBound = '1';
  ncfZoomInBtn.addEventListener('click', function () {
    ncfGridZoom += NCF_GRID_ZOOM_STEP; applyNcfZoom(); persistNcfZoom();
  });
}
if (ncfZoomOutBtn && !ncfZoomOutBtn.dataset.zoomBound) {
  ncfZoomOutBtn.dataset.zoomBound = '1';
  ncfZoomOutBtn.addEventListener('click', function () {
    ncfGridZoom -= NCF_GRID_ZOOM_STEP; applyNcfZoom(); persistNcfZoom();
  });
}

document.addEventListener('ncf-mode-change', function () {
  if (typeof renderWorkflowMultiList === 'function') renderWorkflowMultiList();
  updateGenerateBtn();
});

// ── Generate button gating ─────────────────────────────────────────────────
