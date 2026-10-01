'use strict';
// Aspect-ratio picker: a slider with a live shape preview, rendered into the
// shared options panel (flow-options-panel.js) instead of its own modal.

var _aspectPanelSlider   = null;
var _aspectPanelRect     = null;
var _aspectPanelLabel    = null;
var _aspectPanelHint     = null;
var _ncfAspectPanelApply = null;
var _aspectPanelPresets  = null;   // the list the open panel indexes (#28)

function _updateAspectPreview(idx, presets) {
  var preset = (presets || _aspectPanelPresets || ASPECT_PRESETS)[idx];
  if (!preset || !_aspectPanelRect) return;
  var parts = String(preset.label).split(':');
  var rw = parseFloat(parts[0]) || 1;
  var rh = parseFloat(parts[1]) || 1;
  var maxSize = 96; // px — matches the preview box's inner bounds
  var w, h;
  if (rw >= rh) { w = maxSize; h = maxSize * (rh / rw); }
  else { h = maxSize; w = maxSize * (rw / rh); }
  _aspectPanelRect.style.width  = w + 'px';
  _aspectPanelRect.style.height = h + 'px';
  if (_aspectPanelLabel) _aspectPanelLabel.textContent = preset.label;
  if (_aspectPanelHint) _aspectPanelHint.textContent = preset.hint ? tF(preset.hint) : '';
}

// `presets` (optional): the list `currentIdx` and the index handed to
// onChange refer to — a field's subset of ASPECT_PRESETS (aspectPresetsFor).
// Slider, preview and callback must all use the SAME list (NomadStudio#28).
function openAspectRatioPanel(currentIdx, onChange, presets) {
  _ncfAspectPanelApply = onChange || null;
  _aspectPanelPresets = presets || ASPECT_PRESETS;
  openOptionsPanel(tF('Aspect ratio'), function (body) {
    body.innerHTML =
      '<div class="ncf-aspect-preview-box"><div class="ncf-aspect-preview-rect" id="ncf-aspect-preview-rect"></div></div>' +
      '<p class="ncf-aspect-preview-hint" id="ncf-aspect-preview-hint"></p>' +
      '<p class="ncf-aspect-preview-label" id="ncf-aspect-preview-label">1:1</p>' +
      '<input class="nsc-aspect-slider ncf-aspect-panel-slider" id="ncf-aspect-panel-slider" type="range" min="0" max="' +
        (_aspectPanelPresets.length - 1) + '" step="1" value="' + currentIdx + '" aria-label="' + escHtml(tF('Aspect ratio')) + '">';

    _aspectPanelSlider = body.querySelector('#ncf-aspect-panel-slider');
    _aspectPanelRect   = body.querySelector('#ncf-aspect-preview-rect');
    _aspectPanelLabel  = body.querySelector('#ncf-aspect-preview-label');
    _aspectPanelHint   = body.querySelector('#ncf-aspect-preview-hint');

    _aspectPanelSlider.addEventListener('input', function () {
      var idx = +_aspectPanelSlider.value;
      _updateAspectPreview(idx);
      if (_ncfAspectPanelApply) _ncfAspectPanelApply(idx);
    });

    _updateAspectPreview(currentIdx);
  });
}

// Resolution tier picker: SD/MD/HD/UHD for whichever aspect ratio is
// currently selected — a simple list (unlike the aspect panel's slider,
// there are only 4 discrete options) showing the actual pixel dimensions so
// the choice is never a guess.
var RESOLUTION_TIERS = [
  { id: 'sd',  label: 'SD' },
  { id: 'md',  label: 'MD' },
  { id: 'hd',  label: 'HD' },
  { id: 'uhd', label: 'UHD' },
];

// opts.customDims: { w, h } | null — current custom override, if any.
// opts.onCustomChange: fn({w,h}|null) — called live as the width/height
// inputs change, so the caller can update customResDims/labels/saveParams.
// opts.presets: the list aspectIdx refers to (default ASPECT_PRESETS) — same
// rule as openAspectRatioPanel; also hides tiers that subset doesn't offer.
function openResolutionPanel(aspectIdx, currentTier, onChange, opts) {
  opts = opts || {};
  openOptionsPanel(tF('Resolution'), function (body) {
    var preset = (opts.presets || ASPECT_PRESETS)[aspectIdx];
    var list = document.createElement('div');
    list.className = 'nsc-quality-list ncf-resolution-grid';
    list.setAttribute('role', 'radiogroup');
    RESOLUTION_TIERS.forEach(function (tier) {
      var dims = preset && preset[tier.id];
      if (!dims) return;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'nsc-quality-btn' + (tier.id === currentTier ? ' is-active' : '');
      btn.setAttribute('role', 'radio');
      btn.setAttribute('aria-checked', tier.id === currentTier ? 'true' : 'false');
      btn.innerHTML =
        '<span class="nsc-quality-dot"></span>' +
        '<span class="nsc-quality-copy"><strong>' + tier.label + '</strong>' +
        '<small>' + dims.w + '×' + dims.h + '</small></span>';
      btn.addEventListener('click', function () {
        if (onChange) onChange(tier.id);
        list.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
          b.classList.remove('is-active');
          b.setAttribute('aria-checked', 'false');
        });
        btn.classList.add('is-active');
        btn.setAttribute('aria-checked', 'true');
        // Mirror the picked tier's dims into the Custom resolution fields
        // right below — one live cycle: pick a tier, or fine-tune the exact
        // numbers, either way the same two boxes always show the truth.
        if (wInput) wInput.value = dims.w;
        if (hInput) hInput.value = dims.h;
      });
      list.appendChild(btn);
    });
    body.appendChild(list);

    // Custom resolution — type your own exact width/height, for anyone who
    // wants something other than the SD/MD/HD/UHD presets above. Sits
    // between the tier grid and Upscale output, in the same panel.
    var customBlock = document.createElement('div');
    customBlock.className = 'nsc-param-block';
    customBlock.style.marginTop = '1rem';
    customBlock.innerHTML = '<p class="nsc-param-title">' + escHtml(tF('Custom resolution')) + '</p>';
    var customRow = document.createElement('div');
    customRow.className = 'nsc-field-row';
    customRow.innerHTML =
      '<input class="nsc-input nsc-input--adv" type="number" min="64" step="8" placeholder="' + escHtml(tF('Width')) + '" id="ncf-res-panel-custom-w">' +
      '<span style="color:var(--muted);flex-shrink:0;">×</span>' +
      '<input class="nsc-input nsc-input--adv" type="number" min="64" step="8" placeholder="' + escHtml(tF('Height')) + '" id="ncf-res-panel-custom-h">';
    customBlock.appendChild(customRow);
    body.appendChild(customBlock);
    var wInput = customRow.querySelector('#ncf-res-panel-custom-w');
    var hInput = customRow.querySelector('#ncf-res-panel-custom-h');
    if (opts.customDims) {
      wInput.value = opts.customDims.w;
      hInput.value = opts.customDims.h;
    }
    function emitCustom() {
      var w = parseInt(wInput.value, 10);
      var h = parseInt(hInput.value, 10);
      if (opts.onCustomChange) opts.onCustomChange(w > 0 && h > 0 ? { w: w, h: h } : null);
    }
    wInput.addEventListener('input', emitCustom);
    hInput.addEventListener('input', emitCustom);

    // Upscale output — lives inside this same panel (not its own button):
    // one "Resolution" button covers both the resolution tier and the
    // post-generation upscale pass, per design (issue #74).
    var upTitle = document.createElement('p');
    upTitle.className = 'nsc-param-title';
    upTitle.style.marginTop = '1rem';
    upTitle.textContent = tF('Upscale output');
    body.appendChild(upTitle);
    if (typeof _buildUpscaleOutputGrid === 'function') _buildUpscaleOutputGrid(body);
  });
}
