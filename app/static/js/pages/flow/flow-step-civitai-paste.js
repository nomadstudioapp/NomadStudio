
// Applied the same way the seed and size are: written into the value the
// generation path reads, and mirrored into the visible Negative prompt field so
// the user can see what was taken from the block and edit it.
function applyCivitaiNegative(negative) {
  var text = (negative || '').trim();
  if (!text) return;
  selectedNegativePrompt = text;
  var negTa = document.getElementById('ncf-negative-prompt');
  if (negTa) negTa.value = text;
}

'use strict';
// Step: civitai_paste → renderCivitAIPaste

function renderCivitAIPaste(stepDef, el) {
  var stepId   = stepDef.id;
  var parsed   = null;

  // Open button — round icon trigger next to the step label ("CivitAI
  // generation"), same placement/pattern as the History/Edit icons on
  // prompt_input and json_input steps, opening the shared lateral panel.
  var openBtn = document.createElement('button');
  openBtn.type = 'button';
  openBtn.className = 'nsc-history-btn nsc-options-trigger';
  openBtn.setAttribute('aria-label', tF('Import from CivitAI'));
  openBtn.innerHTML =
    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="1" y="3" width="14" height="10" rx="1.5"/><path d="M5 3V1.5M11 3V1.5M1 7h14"/></svg>';
  var stepLabel = el.querySelector('.nsc-step-label') ||
                  (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));
  if (stepLabel) {
    var chevron = stepLabel.querySelector('.nsc-step-chevron');
    if (chevron) stepLabel.insertBefore(openBtn, chevron);
    else stepLabel.appendChild(openBtn);
  } else {
    el.appendChild(openBtn);
  }


  // ── Style anchor: editable positive prompt + optional strip buttons ─────
  var _styleAnchorEl  = null;
  var _styleAnchorTa  = null;
  var _stripRow       = null;
  var _applyStripBtn  = null;
  var _restoreStripBtn= null;
  var _activeStrips   = {};

  if (Array.isArray(stepDef.strip_buttons) && stepDef.strip_buttons.length) {
    var _STRIP_CFG = {
      remove_elements: {
        label: tF('No elements'),
        icon: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><line x1="14" y1="17" x2="21" y2="17"/><line x1="17.5" y1="13.5" x2="17.5" y2="20.5"/></svg>',
        removeDesc: 'physical scene objects and props: furniture, vehicles (ship, boat, car...), weapons, tools, storage containers (crate, box...), navigational items (compass, map...), food, and any other tangible object placed in the scene.',
      },
      remove_characters: {
        label: tF('No characters'),
        icon: '<svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/><line x1="4" y1="4" x2="20" y2="20"/></svg>',
        removeDesc: 'characters and everything tied to them: people (1girl, solo...), body descriptions, clothing, accessories, hairstyles, poses, expressions, emotions, and character names.',
      },
      remove_background: {
        label: tF('No background'),
        icon: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9l4-4 4 4 4-5 4 5"/><line x1="3" y1="3" x2="21" y2="21"/></svg>',
        removeDesc: 'background and environment: settings, locations (outdoors, forest, city...), sky, ground, water, architecture, nature elements (trees, grass...), and weather conditions.',
      },
    };

    _styleAnchorEl = document.createElement('div');
    _styleAnchorEl.className = 'ncf-civitai-style-anchor';
    _styleAnchorEl.id = 'ncf-civitai-style-anchor-' + stepId;
    _styleAnchorEl.hidden = true;

    _styleAnchorTa = document.createElement('textarea');
    _styleAnchorTa.className = 'nsc-textarea';
    _styleAnchorTa.id = 'ncf-civitai-style-ta-' + stepId;
    _styleAnchorTa.rows = 3;
    _styleAnchorTa.placeholder = tF('Style anchor prompt…');
    _styleAnchorTa.addEventListener('input', function () {
      setVal(stepId, 'positive_prompt', _styleAnchorTa.value.trim());
    });

    // ── Ctrl+hover overlay: blue token highlight + click-to-delete ──────────
    var _taWrap = document.createElement('div');
    _taWrap.className = 'ncf-civ-ta-wrap';

    var _ctrlOverlay = document.createElement('div');
    _ctrlOverlay.className = 'ncf-civ-ctrl-overlay';

    function _buildOverlay() {
      var toks = _styleAnchorTa.value.split(',').map(function (t) { return t.trim(); }).filter(Boolean);
      _ctrlOverlay.innerHTML = '';
      toks.forEach(function (tok, i) {
        if (i > 0) {
          var sep = document.createElement('span');
          sep.className = 'ncf-civ-sep';
          sep.textContent = ', ';
          _ctrlOverlay.appendChild(sep);
        }
        var span = document.createElement('span');
        span.className = 'ncf-civ-token';
        span.textContent = tok;
        span.addEventListener('click', function () {
          var all = _styleAnchorTa.value.split(',').map(function (t) { return t.trim(); }).filter(Boolean);
          all.splice(i, 1);
          var newText = all.join(', ');
          _styleAnchorTa.value = newText;
          setVal(stepId, 'positive_prompt', newText);
          if (all.length) _buildOverlay(); else _hideOverlay();
        });
        _ctrlOverlay.appendChild(span);
      });
    }

    function _showOverlay() {
      _buildOverlay();
      _ctrlOverlay.classList.add('is-visible');
    }
    function _hideOverlay() {
      _ctrlOverlay.classList.remove('is-visible');
    }

    _taWrap.addEventListener('mouseenter', function (e) {
      if (e.ctrlKey || e.metaKey) _showOverlay();
    });
    _taWrap.addEventListener('mouseleave', _hideOverlay);
    _ctrlOverlay.addEventListener('mouseleave', _hideOverlay);

    document.addEventListener('keydown', function (e) {
      if ((e.key === 'Control' || e.key === 'Meta') && _taWrap.matches(':hover')) _showOverlay();
    });
    document.addEventListener('keyup', function (e) {
      if (e.key === 'Control' || e.key === 'Meta') _hideOverlay();
    });

    _taWrap.appendChild(_styleAnchorTa);
    _taWrap.appendChild(_ctrlOverlay);
    _styleAnchorEl.appendChild(_taWrap);

    _stripRow = document.createElement('div');
    _stripRow.className = 'ncf-strip-row';

    _applyStripBtn = document.createElement('button');
    _applyStripBtn.type = 'button';
    _applyStripBtn.className = 'ncf-strip-apply';
    _applyStripBtn.textContent = tF('Apply');
    _applyStripBtn.disabled = true;

    _restoreStripBtn = document.createElement('button');
    _restoreStripBtn.type = 'button';
    _restoreStripBtn.className = 'ncf-strip-restore';
    _restoreStripBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 109-9 9.75 9.75 0 00-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg> Restore';
    _restoreStripBtn.hidden = true;

    function _syncStripApplyBtn() {
      _applyStripBtn.disabled = !Object.keys(_activeStrips).some(function (k) { return _activeStrips[k]; });
    }

    _restoreStripBtn.addEventListener('click', function () {
      var base = getVal(stepId, '_base_positive');
      if (base == null) return;
      _styleAnchorTa.value = base;
      setVal(stepId, 'positive_prompt', base);
      setVal(stepId, '_base_positive', null);
      _restoreStripBtn.hidden = true;
      Object.keys(_activeStrips).forEach(function (k) { _activeStrips[k] = false; });
      _stripRow.querySelectorAll('.ncf-strip-btn').forEach(function (b) { b.classList.remove('is-active'); });
      _syncStripApplyBtn();
    });

    stepDef.strip_buttons.forEach(function (mode) {
      var cfg = _STRIP_CFG[mode];
      if (!cfg) return;
      _activeStrips[mode] = false;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ncf-strip-btn';
      btn.innerHTML = cfg.icon + '<span>' + escHtml(cfg.label) + '</span>';
      btn.title = cfg.label;
      btn.dataset.stripMode = mode;
      btn.addEventListener('click', function () {
        _activeStrips[mode] = !_activeStrips[mode];
        btn.classList.toggle('is-active', _activeStrips[mode]);
        btn.setAttribute('aria-pressed', String(_activeStrips[mode]));
        _syncStripApplyBtn();
      });
      _stripRow.appendChild(btn);
    });

    _applyStripBtn.addEventListener('click', async function () {
      var currentText = (_styleAnchorTa.value || '').trim();
      if (!currentText) return;
      var activeDescs = stepDef.strip_buttons
        .filter(function (m) { return _activeStrips[m] && _STRIP_CFG[m]; })
        .map(function (m) { return '- ' + _STRIP_CFG[m].removeDesc; });
      if (!activeDescs.length) return;
      var sysPrompt = 'Task: edit a Stable Diffusion / Flux prompt (comma-separated tags).\n' +
        'DELETE every tag that belongs to the following categories:\n' +
        activeDescs.join('\n') +
        '\nKEEP all tags that are: clothing, character accessories (watch, jewelry...), body features, character names, quality tags (masterpiece, best quality, highres, 8k...), LoRA triggers (word-style, word-mix...), lighting and rendering terms, or environment/location words.\n' +
        'Return ONLY the edited tag list, no explanation.';
      _applyStripBtn.classList.add('is-loading');
      _applyStripBtn.textContent = '…';
      _stripRow.querySelectorAll('.ncf-strip-btn').forEach(function (b) { b.disabled = true; });
      try {
        var res = await fetch('/api/models/chat/studio-enhance', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: currentText, level: 'quick', flair: 0, systemPrompt: sysPrompt }),
        });
        var data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'Strip error');
        var stripped = (data.enhancedPrompt || '').trim();
        if (!stripped) return;
        if (getVal(stepId, '_base_positive') == null) setVal(stepId, '_base_positive', currentText);
        _styleAnchorTa.value = stripped;
        setVal(stepId, 'positive_prompt', stripped);
        _restoreStripBtn.hidden = false;
      } catch (err) {
        console.warn('[civitai strip]', err);
      } finally {
        _applyStripBtn.classList.remove('is-loading');
        _applyStripBtn.textContent = tF('Apply');
        _stripRow.querySelectorAll('.ncf-strip-btn').forEach(function (b) { b.disabled = false; });
      }
    });

    _stripRow.appendChild(_applyStripBtn);
    _stripRow.appendChild(_restoreStripBtn);
    _styleAnchorEl.appendChild(_stripRow);
    el.appendChild(_styleAnchorEl);
  }

  function showSummary(p) {
    // The tag-list summary (model/LoRAs/seed/steps/cfg + an "Edit" button)
    // used to live inline here — redundant now that the same info is always
    // one click away in the panel via the header button, so this just does
    // the style-anchor reset that used to be bundled alongside it.
    // Show style anchor textarea with current positive (reset strips when re-importing)
    if (_styleAnchorEl && _styleAnchorTa) {
      var currentPositive = getVal(stepId, 'positive_prompt') || p.positive || '';
      _styleAnchorTa.value = currentPositive;
      setVal(stepId, '_base_positive', null);
      _restoreStripBtn.hidden = true;
      Object.keys(_activeStrips).forEach(function (k) { _activeStrips[k] = false; });
      _stripRow.querySelectorAll('.ncf-strip-btn').forEach(function (b) {
        b.classList.remove('is-active');
        b.disabled = false;
      });
      _applyStripBtn.disabled = true;
      _styleAnchorEl.hidden = false;
    }
  }

  // Panel content DOM refs — a detached subtree (see the template) that gets
  // moved into #ncf-options-panel-body on open and stays there (event
  // listeners survive the reparent) until the next step re-opens it.
  var panelContent = document.getElementById('ncf-civitai-panel-content');
  var pasteArea   = document.getElementById('ncf-civitai-paste-ta');
  var pasteBtn    = document.getElementById('ncf-civitai-paste-btn');
  var detectedEl  = document.getElementById('ncf-civitai-detected');
  var detectedList= document.getElementById('ncf-civitai-detected-list');
  var wfSelect    = document.getElementById('ncf-civitai-wf-select');
  var matchBtn    = document.getElementById('ncf-civitai-match-btn');
  var matchResults= document.getElementById('ncf-civitai-match-results');
  var matchList   = document.getElementById('ncf-civitai-match-list');
  var applyBtn    = document.getElementById('ncf-civitai-apply-btn');
  var cancelBtn   = document.getElementById('ncf-civitai-cancel-btn');

  var _pending    = null;   // parsed result in-flight
  var _matchedWfId= null;   // workflow resolved by Match

  function _populateWfSelect() {
    wfSelect.innerHTML = '<option value="">— select workflow —</option>';
    allImportsList.forEach(function (imp) {
      var opt = document.createElement('option');
      opt.value = String(imp.id);
      opt.textContent = imp.name || imp.id;
      if (String(imp.id) === selectedImportId) opt.selected = true;
      wfSelect.appendChild(opt);
    });
    // Auto-select: prefer selectedImportId match, fall back to first import
    if (!wfSelect.value && allImportsList.length) {
      wfSelect.value = String(allImportsList[0].id);
    }
  }

  function openModal() {
    detectedEl.hidden    = true;
    matchResults.hidden  = true;
    applyBtn.disabled    = true;
    _matchedWfId         = null;

    openOptionsPanel(tF('CivitAI generation'), function (body) {
      panelContent.hidden = false;
      body.appendChild(panelContent);
    });

    if (!allImportsList.length) {
      // Imports not yet loaded — fetch now then re-populate
      wfSelect.innerHTML = '<option value="">' + escHtml(tF('Loading workflows…')) + '</option>';
      fetch('/api/models/imports').then(function (r) { return r.json(); }).then(function (data) {
        allImportsList = Array.isArray(data.imports) ? data.imports : [];
        _populateWfSelect();
      }).catch(function () {
        wfSelect.innerHTML = '<option value="">' + escHtml(tF('Failed to load — refresh page')) + '</option>';
      });
    } else {
      _populateWfSelect();
    }

    if (parsed) { _pending = parsed; renderDetected(parsed); applyBtn.disabled = false; }
    pasteArea.focus();
  }

  function closeModal() { closeOptionsPanel(); }

  openBtn.addEventListener('click', openModal);
  cancelBtn.addEventListener('click', closeModal);
  pasteBtn.addEventListener('click', function () {
    if (!navigator.clipboard || !navigator.clipboard.readText) return;
    navigator.clipboard.readText().then(function (text) {
      if (!text) return;
      pasteArea.value = text;
      pasteArea.dispatchEvent(new Event('input'));
      pasteArea.focus();
    }).catch(function () {
      // Clipboard read denied/unavailable — user can still Ctrl+V manually.
    });
  });

  var _parseTimer = null;
  pasteArea.addEventListener('input', function () {
    clearTimeout(_parseTimer);
    _parseTimer = setTimeout(function () {
      var txt = pasteArea.value.trim();
      if (!txt) { detectedEl.hidden = true; applyBtn.disabled = true; _pending = null; return; }
      _pending = parseCivitAI(txt);
      renderDetected(_pending);
      matchResults.hidden = true;
      applyBtn.disabled = false;
    }, 300);
  });

  function renderDetected(p) {
    var html = '';
    if (p.model) html += _detRow('Model', escHtml(p.model));
    p.loras.forEach(function (l) {
      html += _detRow('LoRA', escHtml(l.name) + ' <em>×' + l.weight + '</em>');
    });
    // Split by what actually happens to each value, rather than listing them
    // flat. A flat "Steps 30 · CFG 6.5 · Seed … · 1024×1024 · Clip skip 2"
    // reads as a promise that all five will be used, and two of them are only
    // ever informational — the size comes from your own aspect ratio picker,
    // and steps/CFG are dropped unless the model they belong to was matched
    // (see the Sampler row after Match). Saying so here, before the user even
    // presses Match, is cheaper than letting them find out from a bad render.
    var applied = [];
    if (p.seed != null)     applied.push('Seed '      + p.seed);
    if (p.clipSkip != null) applied.push('Clip skip ' + p.clipSkip);
    if (applied.length) html += _detRow('Will be used', escHtml(applied.join(' · ')));

    var reference = [];
    if (p.steps != null) reference.push('Steps ' + p.steps);
    if (p.cfg   != null) reference.push('CFG '   + p.cfg);
    if (p.width && p.height) reference.push(p.width + '×' + p.height);
    if (reference.length) {
      html += _detRow('For reference', escHtml(reference.join(' · ')) +
        ' <em>— sampler settings apply only if the model matches; size comes from your aspect ratio</em>');
    }
    detectedList.innerHTML = html || '<em>' + escHtml(tF('Nothing detected.')) + '</em>';
    detectedEl.hidden = false;
  }

  function _detRow(key, valHtml) {
    return '<div class="ncf-civ-row"><span class="ncf-civ-key">' + escHtml(key) +
           '</span><span>' + valHtml + '</span></div>';
  }

  // Advanced keys captured during Match for use in Apply
  var _ckptAdvancedKeys      = [];
  var _loraAdvancedKeys      = [];
  var _clipSkipAdvancedKeys  = [];
  var _samplerNodeId         = null;
  var _unmatchedLoraCount    = 0;
  // Did Match actually identify the model the block was recorded on? Gates
  // whether its Steps/CFG get applied — see the Apply handler.
  var _ckptResolved          = false;

  matchBtn.addEventListener('click', async function () {
    if (!_pending) {
      matchList.innerHTML = '<p class="ncf-civ-error">' + escHtml(tF('Paste a CivitAI generation block first.')) + '</p>';
      matchResults.hidden = false;
      return;
    }
    if (!wfSelect.value) {
      matchList.innerHTML = '<p class="ncf-civ-error">' + escHtml(tF('Select a workflow from the dropdown above.')) + '</p>';
      matchResults.hidden = false;
      return;
    }
    var wfId = wfSelect.value;
    matchBtn.disabled = true;
    matchBtn.textContent = tF('Matching…');
    _ckptAdvancedKeys      = [];
    _loraAdvancedKeys      = [];
    _clipSkipAdvancedKeys  = [];
    _samplerNodeId         = null;
    _unmatchedLoraCount    = 0;
    _ckptResolved          = false;
    try {
      // Fetch record + checkpoint list + lora list in parallel
      var results = await Promise.allSettled([
        fetchFullRecord(wfId),
        fetch('/api/models/imports/' + encodeURIComponent(wfId) + '/checkpoints').then(function (r) { return r.json(); }),
        fetch('/api/models/imports/' + encodeURIComponent(wfId) + '/loras').then(function (r) { return r.json(); }),
      ]);
      var record    = results[0].status === 'fulfilled' ? results[0].value : {};
      var ckptData  = results[1].status === 'fulfilled' ? results[1].value : {};
      var loraData  = results[2].status === 'fulfilled' ? results[2].value : {};
      _samplerNodeId = (record.analysis && record.analysis.detected && record.analysis.detected.samplerNodeId) || null;

      var rows = [];

      // ── Checkpoint ──────────────────────────────────────────────────────
      if (_pending.model) {
        var ckptList = Array.isArray(ckptData.checkpoints) ? ckptData.checkpoints : [];
        _ckptAdvancedKeys     = Array.isArray(ckptData.advancedKeys)     ? ckptData.advancedKeys     : [];
        _clipSkipAdvancedKeys = Array.isArray(ckptData.clipSkipAdvancedKeys) ? ckptData.clipSkipAdvancedKeys : [];

        // Try exact/fuzzy match first
        var autoMatch = ckptList.find(function (c) { return _civitaiFuzzyMatch(_pending.model, c); });
        if (autoMatch) {
          rows.push(_mRow('✓', 'Checkpoint / Diffusion model', escHtml(autoMatch), 'ok'));
          _ckptResolved = true;
          _matchedWfId = wfId;
        } else if (ckptList.length) {
          // Show checkpoint dropdown (not workflow dropdown)
          var fbHtml = '<select class="ncf-civ-fallback-select" id="ncf-civ-ckpt-fallback">' +
            '<option value="">— keep workflow default —</option>';
          ckptList.forEach(function (c) {
            var sel = (ckptData.selected && c === ckptData.selected) ? ' selected' : '';
            fbHtml += '<option value="' + escHtml(c) + '"' + sel + '>' + escHtml(c) + '</option>';
          });
          fbHtml += '</select>';
          rows.push(_mRow('⚠', 'Checkpoint / Diffusion model',
            escHtml(_pending.model) + ' — select from available:', 'warn', fbHtml));
          _matchedWfId = wfId;
        } else {
          // Two very different reasons land here, and saying "ComfyUI offline?"
          // for both was wrong. When the workflow has no checkpoint loader at
          // all — it loads a diffusion model through UNETLoader, like every
          // Krea 2 import does — the server returns an empty list without ever
          // asking ComfyUI anything. Blaming the connection sent people to
          // check a service that was running fine.
          var noLoader = !_ckptAdvancedKeys.length;
          rows.push(_mRow('⚠', 'Checkpoint / Diffusion model',
            escHtml(_pending.model) + (noLoader
              ? ' — this engine loads a diffusion model, so there is no checkpoint to match'
              : ' — not found (is ComfyUI running?)'), 'warn'));
          _matchedWfId = wfId;
        }
      }

      // ── LoRAs ────────────────────────────────────────────────────────────
      var liveLoraList  = Array.isArray(loraData.loras) ? loraData.loras : [];
      _loraAdvancedKeys = Array.isArray(loraData.advancedKeys) ? loraData.advancedKeys : [];
      var annLoras      = Array.isArray((record.annotations || {}).loras) ? record.annotations.loras : [];
      var unmatchedIdx  = 0;

      _pending.loras.forEach(function (l) {
        // Check annotations first (no ComfyUI needed)
        var annMatch = annLoras.some(function (al) {
          return _civitaiFuzzyMatch(l.name, al.fileName || al.name || '');
        });
        if (annMatch) {
          rows.push(_mRow('✓', 'LoRA', escHtml(l.name), 'ok'));
          return;
        }
        // Try fuzzy against live list
        var liveMatch = liveLoraList.find(function (lo) { return _civitaiFuzzyMatch(l.name, lo); });
        if (liveMatch) {
          rows.push(_mRow('✓', 'LoRA', escHtml(l.name) + ' → ' + escHtml(liveMatch), 'ok'));
          return;
        }
        // No match → show LoRA dropdown if we have the live list
        if (liveLoraList.length) {
          var loraId = 'ncf-civ-lora-fallback-' + unmatchedIdx;
          var lFb = '<select class="ncf-civ-fallback-select" id="' + loraId + '">' +
            '<option value="">— skip this LoRA —</option>';
          liveLoraList.forEach(function (lo) {
            lFb += '<option value="' + escHtml(lo) + '">' + escHtml(lo) + '</option>';
          });
          lFb += '</select>';
          rows.push(_mRow('⚠', 'LoRA', escHtml(l.name) + ' — select from available:', 'warn', lFb));
          unmatchedIdx++;
        } else {
          rows.push(_mRow('⚠', 'LoRA', escHtml(l.name) + ' — not found (ComfyUI offline?)', 'warn'));
        }
      });
      _unmatchedLoraCount = unmatchedIdx;

      // ── Params info ──────────────────────────────────────────────────────
      // Steps and CFG only mean anything alongside the model they were
      // recorded on. Applied to a different engine they are not "someone
      // else's settings", they are wrong numbers: every Krea 2 import is a
      // turbo checkpoint that runs at 8-12 steps and CFG 1, and a pasted
      // "Steps 30, CFG 6.5" from a base model silently overcooks every render.
      // So when the model could not be resolved, leave them alone and let the
      // flow's own quality preset (Balanced by default) stand.
      var pp = [];
      var applyingSampler = _ckptResolved;
      if (_pending.steps != null) pp.push('Steps ' + _pending.steps);
      if (_pending.cfg   != null) pp.push('CFG '   + _pending.cfg);
      var samplerNote = pp.length
        ? (applyingSampler
            ? escHtml(pp.join(', ')) + ' — will be applied'
            : escHtml(pp.join(', ')) + ' — <strong>' + escHtml(tF('not applied')) + '</strong>: without the model '
              + 'they were recorded on they would fight this engine. Keeping this '
              + 'flow&rsquo;s own quality preset instead.')
        : '';
      var pp2 = [];
      if (_pending.seed     != null) pp2.push('Seed '      + _pending.seed);
      if (_pending.clipSkip != null) pp2.push('Clip skip ' + _pending.clipSkip);
      if (samplerNote) rows.push(_mRow('·', 'Sampler', samplerNote, applyingSampler ? 'info' : 'warn'));
      if (pp2.length) rows.push(_mRow('·', 'Params', escHtml(pp2.join(', ')) + ' — will be applied', 'info'));

      if (!rows.length) {
        var detected = [];
        if (_pending.positive) detected.push('positive prompt');
        if (_pending.negative) detected.push('negative prompt');
        rows.push(_mRow('·', 'Info',
          'No model or params found in the parsed block.' +
          (detected.length ? ' (found: ' + escHtml(detected.join(', ')) + ')' : '') +
          ' Prompts will still be applied.', 'info'));
      }

      matchList.innerHTML = rows.join('');
      matchResults.hidden = false;
    } catch (err) {
      matchList.innerHTML = '<p class="ncf-civ-error">Match failed: ' + escHtml(String(err)) + '</p>';
      matchResults.hidden = false;
    }
    matchBtn.textContent = tF('Match');
    matchBtn.disabled = false;
  });

  function _mRow(icon, key, textHtml, type, extraHtml) {
    return '<div class="ncf-civ-match-row ncf-civ-match-row--' + type + '">' +
      '<span class="ncf-civ-match-icon">' + icon + '</span>' +
      '<span class="ncf-civ-match-key">'  + escHtml(key) + '</span>' +
      '<span class="ncf-civ-match-text">' + textHtml + (extraHtml || '') + '</span>' +
      '</div>';
  }

  applyBtn.addEventListener('click', function () {
    if (!_pending) return;
    parsed = _pending;

    // Store reference values in step store
    setVal(stepId, 'positive_prompt', parsed.positive);
    syncPrefillTargets(stepId, 'positive_prompt', parsed.positive);
    setVal(stepId, 'negative_prompt', parsed.negative);
    // ...and actually use it. The parsed negative used to be stored here and
    // then dropped: the generate step's input_map carries no
    // `basicValues.negative`, so generation fell back to the workflow's own.
    // For a flow whose whole premise is reproducing a recorded prompt exactly,
    // applying the positive and the seed but silently discarding the negative
    // half is the one thing it must not do.
    applyCivitaiNegative(parsed.negative);
    setVal(stepId, 'model',           parsed.model);
    setVal(stepId, 'loras_text',      parsed.lorasText);
    if (parsed.seed     != null) setVal(stepId, 'seed',      parsed.seed);
    if (parsed.steps    != null) setVal(stepId, 'steps',     parsed.steps);
    if (parsed.cfg      != null) setVal(stepId, 'cfg',       parsed.cfg);
    if (parsed.width    != null) setVal(stepId, 'width',     parsed.width);
    if (parsed.height   != null) setVal(stepId, 'height',    parsed.height);
    if (parsed.clipSkip != null) setVal(stepId, 'clip_skip', parsed.clipSkip);

    // Apply seed globally
    if (parsed.seed != null) {
      selectedSeed = parsed.seed;
      var si = document.getElementById('ncf-seed-input');
      if (si) { si.value = String(parsed.seed); saveParams(); }
    }

    // ── Checkpoint override → _civitaiAdvancedOverrides ──
    var ckptSel = document.getElementById('ncf-civ-ckpt-fallback');
    if (ckptSel && ckptSel.value && _ckptAdvancedKeys.length) {
      _ckptAdvancedKeys.forEach(function (key) {
        _civitaiAdvancedOverrides[key] = ckptSel.value;
      });
    }

    // ── LoRA overrides → _civitaiAdvancedOverrides ──
    for (var i = 0; i < _unmatchedLoraCount; i++) {
      var loraSel = document.getElementById('ncf-civ-lora-fallback-' + i);
      if (loraSel && loraSel.value && _loraAdvancedKeys[i]) {
        _civitaiAdvancedOverrides[_loraAdvancedKeys[i]] = loraSel.value;
      }
    }

    // ── Clip skip override → _civitaiAdvancedOverrides ──
    if (parsed.clipSkip != null && _clipSkipAdvancedKeys.length) {
      _clipSkipAdvancedKeys.forEach(function (clipKey) {
        _civitaiAdvancedOverrides[clipKey] = -parsed.clipSkip;
      });
    }

    // ── Steps / CFG override → _civitaiAdvancedOverrides ── same pattern as
    // quality presets (advKey "<samplerNodeId>.steps" / ".cfg"), but sourced
    // from the pasted CivitAI block instead of a preset — only for this flow
    // instance (a plain in-memory var, never written back to the workflow).
    //
    // Only when the model itself was resolved. Picking a checkpoint from the
    // fallback dropdown counts: at that point the user has said which model
    // these numbers belong to. Otherwise they are dropped, and because
    // _civitaiAdvancedOverrides is merged last (flow-generation.js), simply
    // not writing them here leaves selectedQualityValues — the flow's own
    // Balanced preset — in charge, which is the whole point.
    if (_samplerNodeId && (_ckptResolved || (ckptSel && ckptSel.value))) {
      if (parsed.steps != null) _civitaiAdvancedOverrides[_samplerNodeId + '.steps'] = parsed.steps;
      if (parsed.cfg   != null) _civitaiAdvancedOverrides[_samplerNodeId + '.cfg']   = parsed.cfg;
    }

    // Switch workflow if needed
    var targetWfId = _matchedWfId || wfSelect.value;
    if (targetWfId && targetWfId !== selectedImportId) {
      var pickerSel = document.getElementById('ncf-workflow-select');
      if (pickerSel) pickerSel.value = targetWfId;
      selectImportById(targetWfId, null);
    }

    setVal(stepId, '_parsed', parsed);
    showSummary(parsed);
    closeModal();
  });

  // Expose restore hook so loadPendingSession can rebuild UI from saved stepValues
  stepDef._restoreFn = function (sv) {
    if (!sv) return;
    var p = Object.assign({ loras: [] }, sv._parsed || {
      positive: sv.positive_prompt || '',
      negative: sv.negative_prompt || '',
      model: sv.model || '',
      lorasText: sv.loras_text || '',
      seed: sv.seed != null ? sv.seed : null,
      steps: sv.steps != null ? sv.steps : null,
      cfg: sv.cfg != null ? sv.cfg : null,
      width: sv.width != null ? sv.width : null,
      height: sv.height != null ? sv.height : null,
      clipSkip: sv.clip_skip != null ? sv.clip_skip : null,
    });
    // positive_prompt reflects any edits made after import (e.g. ctrl+click deletions)
    if (sv.positive_prompt != null) p.positive = sv.positive_prompt;
    parsed = p;
    setVal(stepId, 'positive_prompt', p.positive);
    setVal(stepId, 'negative_prompt', p.negative);
    setVal(stepId, 'model',           p.model);
    setVal(stepId, 'loras_text',      p.lorasText);
    if (p.seed     != null) setVal(stepId, 'seed',      p.seed);
    if (p.steps    != null) setVal(stepId, 'steps',     p.steps);
    if (p.cfg      != null) setVal(stepId, 'cfg',       p.cfg);
    if (p.width    != null) setVal(stepId, 'width',     p.width);
    if (p.height   != null) setVal(stepId, 'height',    p.height);
    if (p.clipSkip != null) setVal(stepId, 'clip_skip', p.clipSkip);
    if (p.seed != null) {
      selectedSeed = p.seed;
      var si = document.getElementById('ncf-seed-input');
      if (si) { si.value = String(p.seed); saveParams(); }
    }
    showSummary(p);
  };
}

// ── Compose-prompt chip + modal ────────────────────────────────────────────
var _composePromptState = { variants: [], activeId: '', defaultText: '', loaded: false };

