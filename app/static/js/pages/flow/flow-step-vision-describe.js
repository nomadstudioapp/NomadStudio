'use strict';
// Step: vision_describe → renderVisionDescribe
// On click: interpolates {{subject}} (read from subject_from ref) into system_prompt,
// calls describe-image API, then prefills the target prompt_input step.

var _VD_ICON_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true" style="width:16px;height:16px;flex-shrink:0"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>';
var _VD_RING_SVG = '<svg class="nsc-ring nsc-ring--indeterminate" viewBox="0 0 44 44" aria-hidden="true" style="width:18px;height:18px;flex-shrink:0"><circle class="nsc-ring-bg" cx="22" cy="22" r="18"/><circle class="nsc-ring-fill" cx="22" cy="22" r="18"/></svg>';

function renderVisionDescribe(stepDef, el) {
  var imageFrom    = stepDef.image_from    || '';
  var outputTo     = stepDef.output_to     || '';
  var subjectFrom  = stepDef.subject_from  || '';   // e.g. "steps.image.output.subject"
  // NOTE: system_prompt is read fresh from stepDef inside _describe() below,
  // not cached here — a prompt-input preset (see flow-step-prompt-input.js)
  // can mutate stepDef.system_prompt in place when the user picks a
  // different base-prompt style, and this button needs to pick that up
  // without a re-render.

  // ── Vision model picker — icon-only, next to the step's own label ───────────────
  // Same picker as the image_picker's vision-analysis row (makeVisionModelBtn,
  // flow-model-picker.js: quality/speed badges, relative time vs. the fastest
  // model) but shown compact — just the eye icon, no model-name text — and
  // placed beside the "Describe reference" heading itself (same slot the
  // Prompt step's history clock button uses), not next to the action button.
  // It's a global app setting (PATCH /api/models/chat/settings), same one
  // describe-image already reads server-side — no extra wiring needed here.
  var stepLabel = el.querySelector('.nsc-step-label') ||
                  (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));
  if (stepLabel && typeof makeVisionModelBtn === 'function') {
    var vModelBtn = makeVisionModelBtn();
    vModelBtn.className = 'nsc-history-btn nsc-options-trigger ncf-vision-model-btn nsc-history-btn--named';
    vModelBtn.setAttribute('aria-label', tF('Change vision model'));
    // The name used to be stripped here, leaving a bare eye. In the one flow
    // whose entire premise is "a model looks at your picture", that made the
    // model doing the looking the only thing on screen you couldn't see —
    // while Bulk Vision, where vision is incidental, showed it plainly.
    // It matters: a vision model too small for the job doesn't error, it just
    // describes badly, and the blame lands on the image engine that hasn't
    // run yet. Keep the name.
    // makeVisionModelBtn()'s icon is drawn as a filled shape (styled via
    // .ncf-model-icon-btn svg { stroke: currentColor; fill: none; } — a
    // class we just stripped off). Re-set the same stroke/fill directly on
    // the <svg> so it inherits color from .nsc-history-btn/.nsc-options-trigger
    // exactly like the Advanced (⋮) button's icon does, instead of falling
    // back to the browser default (solid black).
    var vModelIcon = vModelBtn.querySelector('svg');
    if (vModelIcon) {
      vModelIcon.setAttribute('fill', 'none');
      vModelIcon.setAttribute('stroke', 'currentColor');
      vModelIcon.setAttribute('stroke-width', '1.5');
      vModelIcon.setAttribute('stroke-linecap', 'round');
      vModelIcon.setAttribute('stroke-linejoin', 'round');
    }
    var chevron = stepLabel.querySelector('.nsc-step-chevron');
    if (chevron) stepLabel.insertBefore(vModelBtn, chevron);
    else stepLabel.appendChild(vModelBtn);
  }

  // ── Describe button ───────────────────────────────────────────────────────────
  var descBtn = document.createElement('button');
  descBtn.type = 'button';
  descBtn.id = 'ncf-vd-btn-' + stepDef.id;
  descBtn.className = 'nss-generate-scenes-btn';
  descBtn.style.cssText = 'width:100%;margin-top:0;';
  descBtn.disabled = true;

  var descBtnLbl = document.createElement('span');
  descBtnLbl.textContent = tF('Describe reference');
  descBtn.insertAdjacentHTML('afterbegin', _VD_ICON_SVG);
  descBtn.appendChild(descBtnLbl);
  // Say why it's dead. The button starts disabled and, until now, gave no
  // reason at all — a new user with no image yet sees a greyed button and
  // nothing pointing at the step above it. Generate already solves this with
  // a .cs-mode-tip, and the CSS that reveals it on hover is generic
  // (.nss-generate-scenes-btn:disabled:hover .cs-mode-tip:not(:empty)), so
  // this needs no new styling — only the element and a sentence.
  var descBtnTip = document.createElement('span');
  descBtnTip.className = 'cs-mode-tip';
  // Set here, not only in _syncBtn: that function returns early when the
  // resolved image URL hasn't changed, and on first render it hasn't ('' to
  // ''), so the very state this tip exists to explain would ship without it.
  descBtnTip.textContent = tF('Add a reference image first');
  descBtn.appendChild(descBtnTip);
  el.appendChild(descBtn);

  // ── Status hint ──────────────────────────────────────────────────────────────
  var statusEl = document.createElement('p');
  statusEl.id = 'ncf-vd-status-' + stepDef.id;
  statusEl.className = 'nsc-step-hint';
  statusEl.style.marginTop = '6px';
  el.appendChild(statusEl);

  // ── Helpers ──────────────────────────────────────────────────────────────────
  var currentImageDataUrl = '';

  function _syncBtn() {
    var url = resolveRef(imageFrom) || '';
    if (url === currentImageDataUrl) return;
    currentImageDataUrl = url;
    if (!descBtn.classList.contains('is-composing')) {
      descBtn.disabled = !url;
      descBtnTip.textContent = url ? '' : 'Add a reference image first';
    }
  }

  function _prefillTarget(text) {
    if (!outputTo) return;
    setVal(outputTo, 'prompt_text', text);
    var targetTa = document.getElementById('ncf-input-' + outputTo);
    if (targetTa) {
      targetTa.value = text;
      targetTa.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  async function _describe() {
    var dataUrl = resolveRef(imageFrom) || '';
    if (!dataUrl) return;

    // Interpolate {{subject}} into system prompt — read fresh from stepDef
    // (not a cached local) so a preset picked after this step first
    // rendered is respected.
    var subject = (resolveRef(subjectFrom) || '').trim() || 'person';
    var resolvedSysPrompt = String(stepDef.system_prompt || '').replace(/\{\{subject\}\}/g, subject);

    // Swap icon → ring inside the button
    var iconEl = descBtn.querySelector('svg');
    if (iconEl) iconEl.outerHTML = _VD_RING_SVG;

    descBtn.disabled = true;
    descBtn.classList.add('is-composing');
    descBtnLbl.textContent = tF('Describing…');
    statusEl.textContent = '';

    try {
      var res = await fetch('/api/models/chat/describe-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          imageDataUrl:   dataUrl,
          describeType:   'prompt',
          describeScope:  'full',
          describeFormat: 'paragraph',
          forceRefresh:   true,   // subject may have changed — never use stale cache
          systemPrompt:   resolvedSysPrompt || undefined,
        }),
      });
      var data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || 'Describe failed');
      var desc = String(data.description || '').trim();
      setVal(stepDef.id, 'description', desc);

      // If the target prompt step has an active {{clothing}}-templated
      // preset (see flow-step-prompt-input.js), let it slot this raw clause
      // into its own template itself — far more reliable than asking the
      // vision model to also rebuild the whole sentence + not repeat itself,
      // which local models often botch (leftover placeholder text, or the
      // clause restated twice). Falls back to the old full-overwrite
      // behavior for any step that isn't in "combine" mode.
      var combineEvt = { stepId: outputTo, text: desc, handled: false };
      document.dispatchEvent(new CustomEvent('ncf-vision-described', { detail: combineEvt }));
      if (!combineEvt.handled) _prefillTarget(desc);

      // No "✓ Done" text — the button already reflects success by returning
      // to its normal (non-disabled, ring-removed) state. Errors still get
      // a message below since those aren't otherwise visible.
      statusEl.textContent = '';
    } catch (err) {
      statusEl.textContent = '✗ ' + (err.message || 'Failed');
    } finally {
      // Restore icon
      var ringEl = descBtn.querySelector('svg');
      if (ringEl) ringEl.outerHTML = _VD_ICON_SVG;

      descBtn.classList.remove('is-composing');
      descBtnLbl.textContent = tF('Describe reference');
      descBtn.disabled = !resolveRef(imageFrom);
    }
  }

  descBtn.addEventListener('click', _describe);

  // ── Poll for upstream image ───────────────────────────────────────────────────
  var _pollInterval = setInterval(function () {
    if (!descBtn.isConnected) { clearInterval(_pollInterval); return; }
    _syncBtn();
  }, 500);

  _syncBtn();
}
