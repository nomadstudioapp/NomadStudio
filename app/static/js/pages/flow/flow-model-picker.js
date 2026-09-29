'use strict';
// Vision model picker modal, plus shared model-scoring helpers used by both
// that modal and flow-model-options-panel.js (the "Assist" model picker,
// which renders into the options panel instead of its own modal).

var _modelScoresCache = null;
function _loadModelScores() {
  if (_modelScoresCache) return Promise.resolve(_modelScoresCache);
  return fetch('/static/data/model_scores.json')
    .then(function (r) { return r.json(); })
    .then(function (data) { _modelScoresCache = data; return data; })
    .catch(function () { return null; });
}

// Vision gets its own table, and the reason is worth stating plainly: this
// panel used to badge vision models with model_scores.json, which comes from
// the +Story benchmark — writing three consecutive scenes. Measured against
// actually reading images, that ranking is not merely imprecise, it is
// inverted at the top. qwen3.5-4b showed 9.0 and sat second in the list while
// failing to read a wide scene about half the time; gemma-4-12b showed 8.7,
// sat lower, and never missed. The app was recommending the model that
// couldn't do the job, with a green number next to it.
//
// vision_scores.json is built from describe-image calls instead. Models it
// doesn't cover get no score badge at all — an absent number invites the user
// to try, a wrong one tells them to trust.
var _visionScoresCache = null;
function _loadVisionScores() {
  if (_visionScoresCache) return Promise.resolve(_visionScoresCache);
  return fetch('/static/data/vision_scores.json')
    .then(function (r) { return r.json(); })
    .then(function (data) { _visionScoresCache = data; return data; })
    .catch(function () { return null; });
}
function _sortModelsByScore(models, scoreData) {
  if (!scoreData || !scoreData.models) return models.slice();
  var m = scoreData.models;
  return models.slice().sort(function (a, b) {
    var sa = m[a] ? m[a].average : -1;
    var sb = m[b] ? m[b].average : -1;
    if (sa !== sb) return sb - sa;
    return a.localeCompare(b);
  });
}
function _scoreTierClass(avg) {
  if (avg >= 8) return 'nse-model-score--high';
  if (avg >= 5) return 'nse-model-score--mid';
  return 'nse-model-score--low';
}
// Brain icon (green/red/gray) showing whether this model is known to respect
// "don't think" requests — see issue #1/#76. State comes from the same
// settings.lmStudioThinkCompat map the Settings > Prompts "Check Think
// Compatibility" button writes to (window.openJourneyApi.checkThinkCompatibility),
// keyed by model id so a never-checked model reads as gray, not green.
var _THINK_BRAIN_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M9.5 3a3 3 0 00-3 3 3 3 0 00-2 5 3.5 3.5 0 002 6.4V19a2 2 0 002 2h1a2 2 0 002-2V6a3 3 0 00-2-3z"/>' +
  '<path d="M14.5 3a3 3 0 013 3 3 3 0 012 5 3.5 3.5 0 01-2 6.4V19a2 2 0 01-2 2h-1a2 2 0 01-2-2V6a3 3 0 012-3z"/>' +
  '</svg>';
function _appendThinkCompatBadge(badges, m) {
  var state = window.openJourneyApi.thinkCompatState(_pickerSettings, m);
  var badge = document.createElement('span');
  badge.className = 'nse-model-think nse-model-think--' + state;
  badge.innerHTML = _THINK_BRAIN_SVG;
  badge.title = tF(state === 'supported'
    ? 'Respects "don\'t think" requests.'
    : state === 'unsupported'
      ? 'Does not support disabling thinking — can burn its whole token budget reasoning.'
      : state === 'no_thinking'
        ? 'No thinking/reasoning capability — nothing to toggle.'
        : 'Think compatibility not checked yet (Settings > Prompts).');
  badges.appendChild(badge);
}
// What fits in VRAM right now (GET /api/models/chat/vram, NomadStudio#12):
// with ComfyUI holding most of a 16 GB card, a model that doesn't fit makes
// LM Studio's engine die or crawl on the CPU. Fetched once per picker open
// (short cache) so each row can say so before the user picks it.
var _vramReport = null;
var _vramReportAt = 0;
function _loadVramReport() {
  if (_vramReport && Date.now() - _vramReportAt < 30000) return Promise.resolve(_vramReport);
  return fetch('/api/models/chat/vram')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) { _vramReport = data; _vramReportAt = Date.now(); return data; })
    .catch(function () { return null; });
}
// Wait for the VRAM report alongside a score table, resolving to the table
// (the render callbacks keep their one-argument shape).
function _withVram(scorePromise) {
  return Promise.all([scorePromise, _loadVramReport()]).then(function (r) { return r[0]; });
}
function _fmtGb(bytes) {
  return (bytes / 1e9).toFixed(bytes >= 1e10 ? 0 : 1) + ' GB';
}
function _appendVramBadge(badges, m) {
  var row = _vramReport && _vramReport.models ? _vramReport.models[m] : null;
  if (!row || !row.size) return;
  var badge = document.createElement('span');
  badge.className = 'nse-model-vram nse-model-vram--' + row.fit;
  badge.textContent = _fmtGb(row.size);
  var free = _vramReport.freeBytes ? _fmtGb(_vramReport.freeBytes) : '?';
  badge.title = row.fit === 'loaded' ? tF('Loaded in LM Studio.')
    : row.fit === 'fits' ? tF('Fits in the free GPU memory') + ' (' + free + ').'
    : row.fit === 'needs_comfy_free' ? tF('Only fits once ComfyUI frees its GPU memory — the app does that before loading it.')
    : row.fit === 'too_big' ? tF('Bigger than the free GPU memory') + ' (' + free + '): ' + tF('it may run partly on the CPU (slow) or fail to load.')
    : tF('GPU memory could not be checked.');
  badges.appendChild(badge);
}

function _appendModelBadges(btn, m, scoreData) {
  var entry = scoreData && scoreData.models ? scoreData.models[m] : null;
  var badges = document.createElement('span'); badges.className = 'nse-model-badges';
  _appendVramBadge(badges, m);
  _appendThinkCompatBadge(badges, m);
  if (!entry) { btn.appendChild(badges); return; }
  var scoreBadge = document.createElement('span');
  scoreBadge.className = 'nse-model-score ' + _scoreTierClass(entry.average);
  scoreBadge.textContent = entry.average.toFixed(1);
  scoreBadge.title = scoreData.badgeTitle
    || 'Story benchmark score (avg of reliability/speed/quality/consistency/instruction)';
  badges.appendChild(scoreBadge);
  if (scoreData.fastestDurationSec && entry.durationSec) {
    // Relative SPEED (fastest / this model's duration), not relative
    // duration — the fastest model always reads "1.0x" and slower models
    // drop below 1 (e.g. "0.1x" = a tenth as fast), matching "higher is
    // better" like the score badge next to it. The original duration/fastest
    // ratio showed slow models as big numbers ("22.3x"), which reads as
    // "22.3x faster" at a glance — the opposite of what it meant.
    var rel = scoreData.fastestDurationSec / entry.durationSec;
    var timeBadge = document.createElement('span'); timeBadge.className = 'nse-model-time';
    timeBadge.textContent = (rel >= 0.1 ? rel.toFixed(1) : rel.toFixed(2)) + 'x';
    timeBadge.title = entry.durationSec.toFixed(1) + 's — relative speed vs. fastest model (1.0x = fastest)';
    badges.appendChild(timeBadge);
  }
  btn.appendChild(badges);
}

// ══════════════════════════════════════════════════════════════════════════
// VISION MODEL PICKER — rendered into the shared right-side options panel
// (openOptionsPanel, flow-options-panel.js), same convention the "Model"
// (Assist) picker already migrated to (flow-model-options-panel.js) instead
// of its own centered modal. Clicking a model saves immediately — no
// separate Apply step, matching that same panel's UX.
// ══════════════════════════════════════════════════════════════════════════
function loadVisionModelHint(hintBtn, hintNameEl) {
  if (_pickerSettings && _pickerSettings.lmStudioVisionModel !== undefined) {
    _updateVisionHintLabel(hintBtn, hintNameEl, _pickerSettings.lmStudioVisionModel || '');
    return;
  }
  fetch('/api/models/chat/settings').then(function (r) { return r.json(); }).then(function (data) {
    _pickerSettings = data.settings || {};
    _updateVisionHintLabel(hintBtn, hintNameEl, _pickerSettings.lmStudioVisionModel || '');
  }).catch(function () {});
}

// Same idea for the writing model. The llm_transform step's own button used to
// be an icon with no text, so the flow that hands your idea to a language model
// never said which one — and the model changes the result a lot more than most
// controls on the page. Mirrors loadVisionModelHint so both buttons behave the
// same and one settings fetch serves both.
function loadPromptModelHint(hintBtn, hintNameEl) {
  if (_pickerSettings && (_pickerSettings.lmStudioModel !== undefined
      || _pickerSettings.lmStudioPromptModel !== undefined)) {
    _updateVisionHintLabel(hintBtn, hintNameEl,
      _pickerSettings.lmStudioPromptModel || _pickerSettings.lmStudioModel || '');
    return;
  }
  fetch('/api/models/chat/settings').then(function (r) { return r.json(); }).then(function (data) {
    _pickerSettings = data.settings || {};
    _updateVisionHintLabel(hintBtn, hintNameEl,
      _pickerSettings.lmStudioPromptModel || _pickerSettings.lmStudioModel || '');
  }).catch(function () {});
}

function _updateVisionHintLabel(hintBtn, hintNameEl, model) {
  if (!hintBtn) return;
  if (model) {
    var short = model.split('/').pop().split('\\').pop();
    if (short.length > 30) short = short.substring(0, 28) + '…';
    if (hintNameEl) hintNameEl.textContent = short;
    hintBtn.setAttribute('title', model);
  } else {
    if (hintNameEl) hintNameEl.textContent = tF('no model');
  }
}

async function _saveVisionModelSetting(model) {
  try {
    var res = await fetch('/api/models/chat/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lmStudioVisionModel: model }),
    });
    var data = await res.json();
    _pickerSettings = data.settings || _pickerSettings;
    // Update ALL vision hint buttons on the page
    document.querySelectorAll('.ncf-vision-model-btn').forEach(function (b) {
      var nameEl = b.querySelector('.ncf-model-icon-name');
      _updateVisionHintLabel(b, nameEl, model);
    });
  } catch (err) {
    console.error('[FlowEngine] saveVisionModelSetting:', err);
    if (typeof showErrorToast === 'function') showErrorToast(tF('Could not save vision model'));
  }
}

function openVisionModelOptionsPanel(hintBtn) {
  if (hintBtn) hintBtn.setAttribute('aria-expanded', 'true');
  var visionPickerModel = (_pickerSettings && _pickerSettings.lmStudioVisionModel) || '';

  openOptionsPanel(tF('Vision model'), function (body) {
    body.innerHTML = '<div class="nse-model-list" id="ncf-vision-model-panel-list"></div>';
    var listEl = body.querySelector('#ncf-vision-model-panel-list');

    // Without this line an unscored model reads as "bad", when it only means
    // "not measured" — and the number that IS shown needs to say what it
    // measured, since the obvious assumption (that it ranks writing quality)
    // is exactly the one that put the wrong model here in the first place.
    var scoreNote = document.createElement('p');
    scoreNote.className = 'nsc-step-hint';
    scoreNote.style.cssText = 'margin:0.6rem 0 0;opacity:0.75;';
    scoreNote.textContent = tF('Scores measure reading images, not writing. Models without one simply have not been benchmarked yet.');
    body.appendChild(scoreNote);
    var models = (_pickerSettings.lmStudioVisionModels && _pickerSettings.lmStudioVisionModels.length)
      ? _pickerSettings.lmStudioVisionModels
      : (_pickerSettings.lmStudioModels || []);

    // Score (0-10) + relative-speed badges, from vision_scores.json — models
    // ranked on reading images, not on writing prose. See _loadVisionScores.
    // Anything the benchmark hasn't covered shows no score, sorts below what
    // has been measured, and is explained by the footer below the list.
    function renderList() {
      if (!models.length) {
        listEl.innerHTML = '<p class="nse-model-empty">' + escHtml(tF('No vision models found — is LM Studio running?')) + '</p>';
        return;
      }
      _withVram(_loadVisionScores()).then(function (scoreData) {
        listEl.innerHTML = '';
        _sortModelsByScore(models, scoreData).forEach(function (m) {
          var btn = document.createElement('button');
          btn.className = 'nse-model-item' + (m === visionPickerModel ? ' is-selected' : '');
          btn.type = 'button';
          btn.setAttribute('role', 'option');
          btn.setAttribute('aria-selected', m === visionPickerModel ? 'true' : 'false');
          btn.dataset.model = m;
          var name = document.createElement('span'); name.className = 'nse-model-name';
          name.textContent = m.split('/').pop().split('\\').pop() || m;
          name.title = m;
          btn.appendChild(name);
          _appendModelBadges(btn, m, scoreData);
          btn.addEventListener('click', function () {
            visionPickerModel = m;
            listEl.querySelectorAll('.nse-model-item').forEach(function (el) {
              var sel = el.dataset.model === m;
              el.classList.toggle('is-selected', sel);
              el.setAttribute('aria-selected', sel ? 'true' : 'false');
            });
            _saveVisionModelSetting(m);
          });
          listEl.appendChild(btn);
        });
      });
    }
    renderList();

    // Small refresh button next to the panel title — same LM Studio scan
    // endpoint the Model panel uses, which also refreshes the vision-model
    // snapshot server-side (see chat_routes.py's /models/load).
    var _refreshIconHtml =
      '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M3 12a9 9 0 0115.4-6.4M21 12a9 9 0 01-15.4 6.4"/><path d="M3 3v6h6"/><path d="M21 21v-6h-6"/></svg>';
    setOptionsPanelAction(_refreshIconHtml, function () {
      var actionEl = document.getElementById('ncf-options-panel-action');
      if (actionEl && actionEl.classList.contains('is-spinning')) return;
      if (actionEl) actionEl.classList.add('is-spinning');
      fetch('/api/models/chat/models/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lmStudioApiUrl: _pickerSettings.lmStudioApiUrl || '' }),
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error((res.data && res.data.error) || 'Failed to refresh models');
          _pickerSettings = res.data.settings || _pickerSettings;
          models = (_pickerSettings.lmStudioVisionModels && _pickerSettings.lmStudioVisionModels.length)
            ? _pickerSettings.lmStudioVisionModels
            : (_pickerSettings.lmStudioModels || []);
          renderList();
          if (typeof showToast === 'function') showToast(tF('Model list refreshed ({n})').replace('{n}', models.length), 'info');
        })
        .catch(function (err) {
          if (typeof showErrorToast === 'function') showErrorToast(err.message || tF('Could not refresh models'));
        })
        .finally(function () {
          var el = document.getElementById('ncf-options-panel-action');
          if (el) el.classList.remove('is-spinning');
        });
    }, { icon: true, label: tF('Refresh model list from LM Studio') });
  }, { wide: true, flexBody: true });
}

// Helper: create a vision model icon button (reusable in renderImagePicker + makeCompactDrop)
function makeVisionModelBtn() {
  var btn = document.createElement('button');
  // nsc-options-trigger tells the options panel's outside-click handler
  // that clicking this button again is a re-trigger, not a dismiss.
  btn.className = 'ncf-model-icon-btn ncf-vision-model-btn nsc-options-trigger';
  btn.type = 'button';
  btn.setAttribute('aria-haspopup', 'true');
  btn.setAttribute('aria-label', tF('Change vision model'));
  // A chip with a pupil, not a plain eye. Wherever this button sits next to
  // an action that actually RUNS vision (the "detect subject" eye in
  // flow-step-image-picker.js, "Describe reference" in
  // flow-step-vision-describe.js) two identical eyes side by side read as
  // the same button twice — reported as "dos botones de vision?". This one
  // only picks WHICH model does the looking, so it's drawn as a model.
  // Three shapes only — it renders at 13px next to the eye, where a chip
  // drawn with eight pins turns to mush.
  btn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<rect x="3.5" y="5" width="17" height="14" rx="3"/>' +
      '<circle cx="12" cy="12" r="3.2"/>' +
      '<circle cx="7" cy="8.5" r="0.9"/>' +
    '</svg>';
  var nameEl = document.createElement('span');
  nameEl.className = 'ncf-model-icon-name';
  nameEl.textContent = '—';
  btn.appendChild(nameEl);
  btn.addEventListener('click', function () {
    openVisionModelOptionsPanel(btn);
  });
  loadVisionModelHint(btn, nameEl);
  return btn;
}

// ══════════════════════════════════════════════════════════════════════════
// JSON VARIABLES MODAL
// ══════════════════════════════════════════════════════════════════════════
