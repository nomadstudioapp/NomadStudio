'use strict';
// Assist "Enhance level" + "Flair" — rendered into the shared options panel
// (flow-options-panel.js) instead of their own modal. Same icon-in-the-
// step-label trigger as Aspect ratio, so llm_transform steps (Assist,
// Scenes, Story…) don't front-load every decision inline.

function _t(key, fallback) {
  return window.NomadI18n ? window.NomadI18n.t(key, fallback) : fallback;
}

// Creativity was a 0-100 slider whose value only ever went into the prompt as
// a sentence ("artistic flair intensity: 45/100"). It changed no sampling
// parameter, so with the configured temperature at 0.1 the model returned
// near-identical text wherever the user put it — three runs of the same idea
// came back with the same opening clause word for word.
//
// The value still travels as 0-100 so nothing else has to change; these four
// steps are the ones worth offering. The numbers map to temperature server
// side (_creativity_temperature in studio_routes.py) and were picked from
// measured run-to-run variety, not taste: 0.1 gives ~0.05, 0.4 gives ~0.70,
// 0.7 gives ~0.75, 0.9 gives ~0.80. There is no fifth step at 1.0 because the
// model starts losing the subject there.
var _CREATIVITY_STEPS = [
  { value: 0,  key: 'flow.creativity.faithful',  label: 'Faithful' },
  { value: 35, key: 'flow.creativity.balanced',  label: 'Balanced' },
  { value: 65, key: 'flow.creativity.inventive', label: 'Inventive' },
  { value: 95, key: 'flow.creativity.bold',      label: 'Bold' }
];

// English fallbacks for the per-step hint, so the panel reads correctly before
// the dictionary finishes loading (t() is async-backed) and in any language
// whose file doesn't carry these keys yet.
var _CREATIVITY_HINTS = {
  'flow.creativity.faithful':  'Sticks close to what you wrote. Best for iterating on a result you already like.',
  'flow.creativity.balanced':  'Real variation between runs, keeping your idea intact.',
  'flow.creativity.inventive': 'Looser interpretation. Expect to be surprised.',
  'flow.creativity.bold':      'Furthest from the prompt. Can drift off your subject.'
};

// Stored values predate these steps (the old slider moved in tens), so snap
// to the nearest rather than dropping anything that isn't an exact match.
function _creativityStepFor(v) {
  var n = Number(v) || 0;
  var best = _CREATIVITY_STEPS[0], bestDist = Infinity;
  _CREATIVITY_STEPS.forEach(function (step) {
    var d = Math.abs(step.value - n);
    if (d < bestDist) { bestDist = d; best = step; }
  });
  return best;
}

function openLLMOptionsPanel(params) {
  openOptionsPanel(tF('Assist options'), function (body) {
    var html = '';
    if (params.level) {
      html +=
        '<div class="nsc-param-block">' +
          '<p class="nsc-param-title">' + escHtml(tF('Enhance level')) + '</p>' +
          '<div class="nse-level-btns" id="ncf-llm-options-level-btns" role="group"></div>' +
        '</div>';
    }
    if (params.flair) {
      html +=
        '<div class="nsc-param-block">' +
          '<p class="nsc-param-title">' + _t('flow.creativity.title', 'Creativity') + '</p>' +
          '<div class="nse-level-btns" id="ncf-llm-options-flair-btns" role="group"></div>' +
          '<p class="nsc-step-hint" id="ncf-llm-options-flair-hint"></p>' +
        '</div>';
    }
    html +=
      '<div class="nsc-param-block">' +
        '<label class="ncf-chat-ep-toggle" id="ncf-llm-options-think-label">' +
          '<input type="checkbox" id="ncf-llm-options-think-toggle" class="ncf-chat-ep-input">' +
          '<span class="ncf-chat-ep-track"><span class="ncf-chat-ep-thumb"></span></span>' +
          '<span class="ncf-chat-ep-text">' + escHtml(tF('Think')) + '</span>' +
          '<span class="ncf-chat-tip ncf-chat-tip--wide" role="tooltip">' + escHtml(tF('Off: fast, no reasoning. On: the model jots a brief thinking outline before writing the result — still fast, this is prompted, not a special reasoning mode.')) + '</span>' +
        '</label>' +
      '</div>';
    body.innerHTML = html;

    if (params.level) {
      var levelBtnsEl = body.querySelector('#ncf-llm-options-level-btns');
      var levels = Array.isArray(params.level.options)
        ? params.level.options : ['quick', 'style', 'scene', 'master'];
      levels.forEach(function (lv) {
        var btn = document.createElement('button');
        btn.className = 'nse-level-btn' + (lv === selectedLevel ? ' is-active' : '');
        btn.type = 'button';
        btn.dataset.level = lv;
        btn.textContent = lv.charAt(0).toUpperCase() + lv.slice(1);
        btn.addEventListener('click', function () {
          selectedLevel = lv;
          levelBtnsEl.querySelectorAll('.nse-level-btn')
            .forEach(function (b) { b.classList.toggle('is-active', b === btn); });
        });
        levelBtnsEl.appendChild(btn);
      });
    }

    if (params.flair) {
      var flairBtnsEl = body.querySelector('#ncf-llm-options-flair-btns');
      var flairHintEl = body.querySelector('#ncf-llm-options-flair-hint');
      var activeStep = _creativityStepFor(flairValue);
      flairValue = activeStep.value;

      function renderFlairHint(step) {
        flairHintEl.textContent = _t(
          step.key + '.hint',
          _CREATIVITY_HINTS[step.key] || ''
        );
      }

      _CREATIVITY_STEPS.forEach(function (step) {
        var btn = document.createElement('button');
        btn.className = 'nse-level-btn' + (step.value === flairValue ? ' is-active' : '');
        btn.type = 'button';
        btn.dataset.flair = String(step.value);
        btn.textContent = _t(step.key, step.label);
        btn.addEventListener('click', function () {
          flairValue = step.value;
          flairBtnsEl.querySelectorAll('.nse-level-btn')
            .forEach(function (b) { b.classList.toggle('is-active', b === btn); });
          renderFlairHint(step);
        });
        flairBtnsEl.appendChild(btn);
      });
      renderFlairHint(activeStep);
    }

    var thinkToggleEl = body.querySelector('#ncf-llm-options-think-toggle');
    if (thinkToggleEl) {
      thinkToggleEl.checked = assistThinkMode;
      thinkToggleEl.addEventListener('change', function () {
        assistThinkMode = thinkToggleEl.checked;
      });
    }

    // The Context slider used to live here. It offered a number nobody can
    // pick well — and measuring it showed the offer was hollow: across a 32x
    // range (2048 / 16384 / 65535) the same Templateize call took 8.6s, 8.4s
    // and 8.7s. "Lower = faster replies" was not visible at all.
    //
    // What it did do went unsaid. Every studio route sized its _clip_text
    // budget from this number, so the low end of the slider quietly cut the
    // user's own prompt: at 512 the Templateize budget was 614 characters.
    // The prompt that exposed all of this is 572 — 42 characters from being
    // truncated mid-sentence with nothing on screen to say so.
    //
    // The window is now derived from the text being sent (_auto_context_size
    // in workflow_service.py), which is what the control was standing in for.
  });
}

// Called when selectedLevel/flairValue change from outside (e.g. a genre
// card applying its suggested level/flair) so the panel's own controls don't
// go stale if this content happens to be showing at the time. Queries live —
// these ids only exist while the panel is currently showing Assist options.
function syncLLMOptionsModalUI() {
  var levelBtnsEl = document.getElementById('ncf-llm-options-level-btns');
  if (levelBtnsEl) {
    levelBtnsEl.querySelectorAll('.nse-level-btn').forEach(function (b) {
      b.classList.toggle('is-active', b.dataset.level === selectedLevel);
    });
  }
  var flairSliderEl = document.getElementById('ncf-llm-options-flair-slider');
  if (flairSliderEl) {
    flairSliderEl.value = flairValue;
    document.getElementById('ncf-llm-options-flair-val').textContent = flairValue;
    document.getElementById('ncf-llm-options-flair-desc').textContent = _flairDescFor(flairValue);
  }
}
