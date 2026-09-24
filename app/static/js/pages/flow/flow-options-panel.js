'use strict';
// Generic right-side "options panel" — replaces the small centered modals
// (Aspect ratio / Assist options / Model) with a persistent lateral panel,
// matching the .panel-right convention used on Studio/Compose/Upscale, but
// built on this page's own aside pattern (.nsc-model-params /
// .nsc-live-preview-aside) since .nsc-main here is flex, not the grid those
// pages use.
//
// Any trigger button that opens the panel must carry the "nsc-options-trigger"
// class so the outside-click handler doesn't treat re-triggering it (to swap
// content) as a dismiss.

var _optionsPanelEl       = null;
var _optionsPanelTitleEl  = null;
var _optionsPanelBodyEl   = null;
var _optionsPanelActionEl = null;
var _optionsPanelInited   = false;
// opts.persistent: the panel only closes with its × (or Escape) — not on a
// click elsewhere. For panels that run long work, e.g. model downloads.
var _optionsPanelPersistent = false;

var _nestedPanelEl      = null;
var _nestedPanelTitleEl = null;
var _nestedPanelBodyEl  = null;
var _nestedPanelInited  = false;

function _ensureOptionsPanel() {
  if (_optionsPanelInited) return;
  _optionsPanelInited  = true;
  _optionsPanelEl      = document.getElementById('ncf-options-panel');
  if (!_optionsPanelEl) return;
  _optionsPanelTitleEl  = document.getElementById('ncf-options-panel-title');
  _optionsPanelBodyEl   = document.getElementById('ncf-options-panel-body');
  _optionsPanelActionEl = document.getElementById('ncf-options-panel-action');
  var closeBtn = document.getElementById('ncf-options-panel-close');
  if (closeBtn) closeBtn.addEventListener('click', closeOptionsPanel);
}

function _ensureNestedOptionsPanel() {
  if (_nestedPanelInited) return;
  _nestedPanelInited = true;
  _nestedPanelEl     = document.getElementById('ncf-options-panel-2');
  if (!_nestedPanelEl) return;
  _nestedPanelTitleEl = document.getElementById('ncf-options-panel-2-title');
  _nestedPanelBodyEl  = document.getElementById('ncf-options-panel-2-body');
  var closeBtn = document.getElementById('ncf-options-panel-2-close');
  if (closeBtn) closeBtn.addEventListener('click', closeNestedOptionsPanel);
}

// Same title/fillFn/opts contract as openOptionsPanel, but opens a genuinely
// separate 4th column beside #ncf-options-panel instead of reusing it — for
// pickers triggered FROM INSIDE an already-open options panel (e.g. "Choose
// a LoRA" clicked from the Advanced panel's LoRAs section), so opening this
// one doesn't blow away the panel it was opened from.
function openNestedOptionsPanel(title, fillFn, opts) {
  _ensureNestedOptionsPanel();
  if (!_nestedPanelEl) return;
  if (_nestedPanelTitleEl) _nestedPanelTitleEl.textContent = title;
  var wideOpt = opts && opts.wide;
  _nestedPanelEl.classList.toggle('nsc-options-panel--wide', !!wideOpt && wideOpt !== 'xl');
  _nestedPanelEl.classList.toggle('nsc-options-panel--xwide', wideOpt === 'xl');
  if (_nestedPanelBodyEl) {
    _nestedPanelBodyEl.classList.toggle('nsc-options-panel-body--flex', !!(opts && opts.flexBody));
    _nestedPanelBodyEl.innerHTML = '';
    if (typeof fillFn === 'function') fillFn(_nestedPanelBodyEl);
  }
  _nestedPanelEl.hidden = false;
}

function closeNestedOptionsPanel() {
  if (_nestedPanelEl) _nestedPanelEl.hidden = true;
}

// Optional small text/icon button shown in the panel header next to the
// title (e.g. History's "Clear", Model's refresh). Callers set it from
// inside their fillFn, after openOptionsPanel() has already reset it — so it
// never leaks into unrelated panels (Aspect ratio, Model, …).
// opts.icon: true → circular icon-only style (content is trusted inline SVG,
// not user text) instead of the default text-label look.
// opts.label: accessible name — required when opts.icon is set, since an SVG
// alone has no text for aria-label/title.
function setOptionsPanelAction(content, onClick, opts) {
  _ensureOptionsPanel();
  if (!_optionsPanelActionEl) return;
  if (!content) {
    _optionsPanelActionEl.hidden = true;
    _optionsPanelActionEl.onclick = null;
    _optionsPanelActionEl.classList.remove('nsc-options-panel-action--icon');
    return;
  }
  _optionsPanelActionEl.innerHTML = content;
  _optionsPanelActionEl.hidden = false;
  _optionsPanelActionEl.onclick = onClick || null;
  var isIcon = !!(opts && opts.icon);
  _optionsPanelActionEl.classList.toggle('nsc-options-panel-action--icon', isIcon);
  if (isIcon && opts.label) {
    _optionsPanelActionEl.setAttribute('aria-label', opts.label);
    _optionsPanelActionEl.title = opts.label;
  } else {
    _optionsPanelActionEl.removeAttribute('aria-label');
    _optionsPanelActionEl.title = '';
  }
}

// title: string shown in the panel header.
// fillFn: function(bodyEl) — builds this open's content into the panel body.
// opts.wide: true → wider panel (Model picker); 'xl' → extra-wide, for panels
// that need room for a sidebar tree + card grid side by side (Style Transfer's
// "Choose a Style" picker).
// opts.flexBody: true → body becomes a flex column, so a child with flex:1
// (e.g. the Model list) can stretch to fill the rest of the panel's height.
function openOptionsPanel(title, fillFn, opts) {
  _ensureOptionsPanel();
  if (!_optionsPanelEl) return;
  if (_optionsPanelTitleEl) _optionsPanelTitleEl.textContent = title;
  setOptionsPanelAction(null);
  _optionsPanelPersistent = !!(opts && opts.persistent);
  var wideOpt = opts && opts.wide;
  _optionsPanelEl.classList.toggle('nsc-options-panel--wide', !!wideOpt && wideOpt !== 'xl');
  _optionsPanelEl.classList.toggle('nsc-options-panel--xwide', wideOpt === 'xl');
  if (_optionsPanelBodyEl) {
    _optionsPanelBodyEl.classList.toggle('nsc-options-panel-body--flex', !!(opts && opts.flexBody));
    _optionsPanelBodyEl.innerHTML = '';
    if (typeof fillFn === 'function') fillFn(_optionsPanelBodyEl);
  }
  _optionsPanelEl.hidden = false;
}

function closeOptionsPanel() {
  if (_optionsPanelEl) _optionsPanelEl.hidden = true;
  _optionsPanelPersistent = false;
  closeNestedOptionsPanel();
}

// One global listener (not re-added per open/close) — no-ops whenever the
// panel is already closed, so this is cheap to leave attached.
// .nsc-options-exempt is for floating UI that lives outside the panel (e.g.
// the Model list's right-click favorite menu, and the nested panel itself)
// but shouldn't count as an "outside" click either.
document.addEventListener('mousedown', function (e) {
  if (_nestedPanelEl && !_nestedPanelEl.hidden
      && !_nestedPanelEl.contains(e.target)
      && !(e.target.closest && e.target.closest('.nsc-options-trigger'))) {
    closeNestedOptionsPanel();
  }
  if (!_optionsPanelEl || _optionsPanelEl.hidden) return;
  if (_optionsPanelPersistent) return;
  if (_optionsPanelEl.contains(e.target)) return;
  if (e.target.closest && e.target.closest('.nsc-options-trigger')) return;
  if (e.target.closest && e.target.closest('.nsc-options-exempt')) return;
  closeOptionsPanel();
}, true);

document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  if (_nestedPanelEl && !_nestedPanelEl.hidden) { closeNestedOptionsPanel(); return; }
  if (_optionsPanelEl && !_optionsPanelEl.hidden) closeOptionsPanel();
});
