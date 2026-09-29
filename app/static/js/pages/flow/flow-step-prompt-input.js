'use strict';
// Step: prompt_input → renderPromptInput

// Pose presets (Clothes Mix): prompts that carry this exact sentence get a
// "Pose" picker under the subject field (flow-step-image-picker.js). Picking
// a pose swaps the sentence for NCF_POSE_CLAUSE(snippet); "From Picture 1"
// puts the sentence back. Poses: app/static/data/pose_presets.json.
var NCF_POSE_FROM_PICTURE = "Match the pose from Picture 1 to the subject's entire body";
function NCF_POSE_CLAUSE(snippet) {
  return snippet
    ? "Change the subject's pose to " + snippet + ", applied to the subject's entire body"
    : NCF_POSE_FROM_PICTURE;
}

function renderPromptInput(stepDef, el) {
  if (stepDef.note) el.appendChild(mkHint(stepDef.note));

  // ── {{subject}} / {{clothing}} live templating ───────────────────────────
  // Static default/preset text can carry two tokens (e.g. Mix's Clothes
  // flow: "Have the {{subject}} in Figure 1 wear {{clothing}} from Figure
  // 2."): {{subject}} from the "Who is the subject?" field (image_picker
  // step, always id "image" for these flows), and {{clothing}} from
  // whatever "Describe reference" comes back with (see
  // flow-step-vision-describe.js's ncf-vision-described event) — the vision
  // model is only asked for the raw clause, never the whole sentence, since
  // local models are unreliable at "rebuild this sentence yourself" style
  // instructions (repeats the clause, leaves the placeholder text in, etc).
  // _currentTemplate holds the raw, un-interpolated text of whatever's
  // active (default or a picked preset); _clothingDesc is the last clause
  // fetched for it, or null before any describe; _lastAutoValue is what we
  // last wrote into the textarea ourselves — if the user hasn't typed over
  // it since, a subject change re-interpolates in place; if they have, we
  // leave their edit alone.
  var _currentTemplate = '';
  var _clothingDesc = null;
  var _lastAutoValue = null;
  function _subjectValue() {
    var s = (typeof getVal === 'function' ? getVal('image', 'subject') : '') || '';
    return String(s).trim() || 'person';
  }
  // {{clothing}} can be fed by two independent, additive sources: whatever
  // the user typed by hand into image_2's own subject_input field ("What is
  // the clothing?" — see flow-step-image-picker.js) and/or whatever
  // "Describe reference" fetched from the vision model. Neither one
  // overwrites the other — both get joined at rebuild time, so typing a
  // manual hint and still hitting Describe reference (or vice versa) keeps
  // both instead of the last action clobbering the first.
  function _manualClothingValue() {
    var s = (typeof getVal === 'function' ? getVal('image_2', 'subject') : '') || '';
    return String(s).trim();
  }
  function _rebuild() {
    var t = _currentTemplate;
    if (t.indexOf('{{clothing}}') !== -1) {
      var manualClothing = _manualClothingValue();
      var clothingParts = [];
      if (manualClothing) clothingParts.push(manualClothing);
      if (_clothingDesc) clothingParts.push(_clothingDesc);
      var clothingCombined = clothingParts.length ? clothingParts.join(', ') : null;
      t = t.replace(/\{\{clothing\}\}/g, clothingCombined != null ? clothingCombined : '[describe the clothing]');
    }
    if (t.indexOf('{{subject}}') !== -1) t = t.replace(/\{\{subject\}\}/g, _subjectValue());
    if (_poseSnippet) t = t.split(NCF_POSE_FROM_PICTURE).join(NCF_POSE_CLAUSE(_poseSnippet));
    return t;
  }
  var _poseSnippet = '';
  // Fired by the Pose picker. If the textarea still holds what we last wrote,
  // rebuild it; if the user edited it by hand, just swap the pose clause in
  // place so their other edits survive.
  document.addEventListener('ncf-pose-changed', function (e) {
    var next = String((e.detail && e.detail.snippet) || '');
    if (next === _poseSnippet) return;
    var prevClause = NCF_POSE_CLAUSE(_poseSnippet);
    _poseSnippet = next;
    if (_currentTemplate && ta.value === _lastAutoValue) {
      ta.value = _rebuild();
      _lastAutoValue = ta.value;
    } else if (ta.value.indexOf(prevClause) !== -1) {
      ta.value = ta.value.split(prevClause).join(NCF_POSE_CLAUSE(next));
    } else {
      return;
    }
    setVal(stepDef.id, 'prompt_text', ta.value.trim());
    if (typeof _renderPromptChips === 'function') _renderPromptChips();
    if (typeof updateGenerateBtn === 'function') updateGenerateBtn();
  });
  function _applyTemplate(template) {
    _currentTemplate = template;
    // NOTE: _clothingDesc is intentionally *not* reset here. The reference
    // image hasn't changed just because the user picked a different preset
    // wording — if they already hit "Describe reference" once, switching
    // presets should reuse that same clause via {{clothing}}, not throw it
    // away and force a re-describe.
    var value = _rebuild();
    _lastAutoValue = value;
    return value;
  }
  // Fired on blur by both the primary subject field (image) and, if this
  // flow has one, the manual clothing-description field (image_2) — both
  // funnel through the same event, and _rebuild() only touches whichever
  // token(s) are actually present in the current template, so no need to
  // branch on e.detail.stepId here.
  document.addEventListener('ncf-subject-blur', function () {
    if (!_currentTemplate) return;
    var hasToken = _currentTemplate.indexOf('{{subject}}') !== -1 || _currentTemplate.indexOf('{{clothing}}') !== -1;
    if (!hasToken) return;
    if (ta.value !== _lastAutoValue) return; // user already edited it by hand — don't clobber
    ta.value = _rebuild();
    _lastAutoValue = ta.value;
    setVal(stepDef.id, 'prompt_text', ta.value.trim());
    if (typeof _renderPromptChips === 'function') _renderPromptChips();
  });
  document.addEventListener('ncf-vision-described', function (e) {
    var d = e.detail || {};
    if (d.stepId !== stepDef.id) return;
    if (!_currentTemplate || _currentTemplate.indexOf('{{clothing}}') === -1) return; // not in combine mode
    _clothingDesc = String(d.text || '').trim();
    ta.value = _rebuild();
    _lastAutoValue = ta.value;
    setVal(stepDef.id, 'prompt_text', ta.value.trim());
    if (typeof _renderPromptChips === 'function') _renderPromptChips();
    d.handled = true; // tell vision-describe.js not to also full-overwrite via prefill_from
  });

  // History button — appended to this step's label (may be in a parent .nsc-step wrapper)
  var stepLabel = el.querySelector('.nsc-step-label') ||
                  (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));
  if (stepLabel) {
    var histBtn = document.createElement('button');
    histBtn.type = 'button';
    histBtn.className = 'nsc-history-btn nsc-options-trigger';
    histBtn.setAttribute('aria-label', tF('Prompt history'));
    histBtn.innerHTML =
      '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<circle cx="8" cy="8" r="6"/>' +
        '<path d="M8 5v3.5l2 1.5"/>' +
      '</svg>';
    histBtn.addEventListener('click', function () {
      openHistoryModal(stepDef.id, function (text) {
        ta.value = text;
        setVal(stepDef.id, 'prompt_text', text.trim());
        updateGenerateBtn();
      });
    });
    var chevron = stepLabel.querySelector('.nsc-step-chevron');
    if (chevron) stepLabel.insertBefore(histBtn, chevron);
    else stepLabel.appendChild(histBtn);

    // Style button — opt-in via stepDef.style_picker (Create's Styling
    // flows). Same Build > Styles catalog panel as Refine's style_picker
    // field (_openStylePickerPanel, flow-step-workflow-params.js); picking a
    // style wraps whatever is in the box with its prefix and suffix, so the
    // idea stays in the middle and the field stays freely editable.
    if (stepDef.style_picker && typeof _openStylePickerPanel === 'function') {
      var styleBtn = document.createElement('button');
      styleBtn.type = 'button';
      styleBtn.className = 'nsc-history-btn nsc-options-trigger';
      styleBtn.setAttribute('aria-label', tF('Choose a Style'));
      styleBtn.title = tF('Choose a Style');
      styleBtn.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
          '<circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/>' +
          '<path d="M12 2a10 10 0 1 0 10 10c0-1.1-.9-2-2-2h-2.3a2 2 0 0 1-2-2c0-.5.2-1 .5-1.3A2 2 0 0 0 14.7 3c-.9-.6-1.8-1-2.7-1z"/>' +
        '</svg>';
      styleBtn.addEventListener('click', function () {
        _openStylePickerPanel(function (style) {
          // "separate": the idea box stays the idea — the style is kept on
          // the side and a sibling style_compose_from box shows the result.
          if (stepDef.style_picker === 'separate') {
            _setPickedStyle(style);
            return;
          }
          var composed = [style.prefix, ta.value.trim(), style.suffix]
            .map(function (s) { return String(s || '').trim(); })
            .filter(Boolean)
            .join(', ');
          ta.value = composed;
          setVal(stepDef.id, 'prompt_text', composed);
          setVal(stepDef.id, 'style_name', style.name || '');
          ta.dispatchEvent(new Event('input'));
          if (typeof updateGenerateBtn === 'function') updateGenerateBtn();
        });
      });
      if (chevron) stepLabel.insertBefore(styleBtn, chevron);
      else stepLabel.appendChild(styleBtn);
    }

    // "Edit Prompt" button — common to style prompts (opt-in via
    // stepDef.style_prompt_edit, set by flow_engine.py whenever the sibling
    // "image" step declares style_image_input): opens a small
    // Prefix/Idea/Suffix builder (P/S pre-filled from whatever style image
    // was picked via the Styles button, flow-step-image-picker.js) plus a
    // "Refine with LLM" pass (LM Studio) on just the idea clause before
    // composing everything back into this textarea.
    if (stepDef.style_prompt_edit) {
      function _applyEditedPrompt(composed) {
        ta.dispatchEvent(new Event('input'));
        setVal(stepDef.id, 'prompt_text', composed);
        if (typeof updateGenerateBtn === 'function') updateGenerateBtn();
      }

      var editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'nsc-history-btn nsc-options-trigger';
      editBtn.setAttribute('aria-label', tF('Edit prompt'));
      editBtn.title = tF('Edit prompt (prefix / idea / suffix)');
      editBtn.innerHTML =
        '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M11 2l3 3-8 8-3.5 1 1-3.5z"/>' +
        '</svg>';
      editBtn.addEventListener('click', function () {
        _openEditPromptPanel('image', ta, _applyEditedPrompt, 'Edit Prompt');
      });
      if (chevron) stepLabel.insertBefore(editBtn, chevron);
      else stepLabel.appendChild(editBtn);

      // A style picked or described on the image step goes straight into
      // this prompt — no panel, no Apply.
      _bindStyleAutoApply('image', ta, _applyEditedPrompt);
    }

  }

  // Bracket field editor — same idea as the JSON panel, for templates whose
  // fields live inside [square brackets] instead of a JSON object.
  //
  // It cannot live in the step label like the other icons: a prompt_input that
  // prefills from another step has its label suppressed on purpose
  // (flow-render-all.js skipLabel — it reads as a continuation of the step
  // above), and this is exactly such a step. So when there is no label to hang
  // off, it gets its own small right-aligned row above the textarea.
  if (stepDef.bracket_editor) {
    var bracketBtn = document.createElement('button');
    bracketBtn.type = 'button';
    bracketBtn.className = 'nsc-history-btn nsc-options-trigger';
    bracketBtn.setAttribute('aria-label', tF('Edit template fields'));
    bracketBtn.title = tF('Edit the [bracketed] fields as a form');
    bracketBtn.innerHTML =
      '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M6 2H3v12h3M10 2h3v12h-3"/>' +
      '</svg>';
    bracketBtn.addEventListener('click', function () {
      openBracketEditorPanel(stepDef, ta, function () {
        if (typeof updateGenerateBtn === 'function') updateGenerateBtn();
      });
    });
    var bracketHost = el.querySelector('.nsc-step-label') ||
                      (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));
    if (bracketHost) {
      var bChev = bracketHost.querySelector('.nsc-step-chevron');
      if (bChev) bracketHost.insertBefore(bracketBtn, bChev);
      else bracketHost.appendChild(bracketBtn);
    } else {
      var toolbar = document.createElement('div');
      toolbar.className = 'ncf-bracket-toolbar';
      toolbar.appendChild(bracketBtn);
      el.insertBefore(toolbar, el.firstChild);
    }
  }

  if (stepDef.copy_button) {
    var copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'nsc-history-btn';
    copyBtn.setAttribute('aria-label', tF('Copy prompt'));
    copyBtn.title = tF('Copy this prompt to the clipboard');
    var _copyIcon =
      '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5V4a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5"/>' +
      '</svg>';
    var _doneIcon =
      '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M3 8.5l3.5 3.5L13 5"/>' +
      '</svg>';
    copyBtn.innerHTML = _copyIcon;
    copyBtn.addEventListener('click', function () {
      var text = ta.value || '';
      if (!text) return;
      function ok() {
        copyBtn.innerHTML = _doneIcon;
        copyBtn.classList.add('is-copied');
        setTimeout(function () {
          copyBtn.innerHTML = _copyIcon;
          copyBtn.classList.remove('is-copied');
        }, 1400);
      }
      // navigator.clipboard needs a secure context; a local flow page served
      // over plain http is not one, so keep the textarea fallback.
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(ok).catch(function () {
          ta.select(); document.execCommand('copy'); ta.setSelectionRange(0, 0); ok();
        });
      } else {
        ta.select(); document.execCommand('copy'); ta.setSelectionRange(0, 0); ok();
      }
    });
    var copyHost = el.querySelector('.nsc-step-label') ||
                   (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));
    if (copyHost) {
      var cChev = copyHost.querySelector('.nsc-step-chevron');
      if (cChev) copyHost.insertBefore(copyBtn, cChev);
      else copyHost.appendChild(copyBtn);
    } else {
      var copyBar = el.querySelector('.ncf-bracket-toolbar');
      if (!copyBar) {
        copyBar = document.createElement('div');
        copyBar.className = 'ncf-bracket-toolbar';
        el.insertBefore(copyBar, el.firstChild);
      }
      copyBar.appendChild(copyBtn);
    }
  }

  // ── Presets (e.g. Look Book's pre-written scene descriptions) ───────────
  // The actual button+menu UI no longer lives on this step's own card — for
  // flows that also have a subject_input (e.g. Mix's Clothes flow),
  // flow-step-image-picker.js renders it right below "Who is the subject?"
  // instead, since picking a base wording logically comes before describing
  // the reference, not after. What stays here is the *behavior*: applying a
  // preset's text/system_prompt to this exact step, registered on
  // window._ncfPromptPresetSteps so the image-picker step (which renders
  // earlier and has no access to this closure's `ta`/`_applyTemplate`) can
  // trigger it by id. Flows with no subject_input still show the plain
  // in-card button (see below).
  function _choosePreset(pr) {
    var prText = typeof pr === 'object' ? (pr.text || pr.label || '') : String(pr);
    ta.value = _applyTemplate(prText);
    ta.dispatchEvent(new Event('input'));
    updateGenerateBtn();
    // Style flows: the preset is the idea — keep the picked style's
    // prefix/suffix wrapped around it instead of dropping them.
    if (stepDef.style_prompt_edit) {
      _applyStyleToPrompt('image', ta, function (composed) {
        ta.dispatchEvent(new Event('input'));
        setVal(stepDef.id, 'prompt_text', composed);
        updateGenerateBtn();
      }, ta.value);
    }

    // Presets that pair a base prompt with its own "Describe reference"
    // instruction (e.g. Mix's Clothes flow: Simple / Detailed / Preserve
    // everything each need a different vision-assist system_prompt) —
    // mutate the sibling vision_describe step in place. It re-reads
    // stepDef.system_prompt fresh on every click (see
    // flow-step-vision-describe.js), so this takes effect immediately,
    // no re-render needed.
    if (typeof pr === 'object' && pr.system_prompt && Array.isArray(allSteps)) {
      var visionStep = allSteps.find(function (s) { return s.type === 'vision_describe' && s.output_to === stepDef.id; });
      if (visionStep) visionStep.system_prompt = pr.system_prompt;
    }
  }

  if (Array.isArray(stepDef.presets) && stepDef.presets.length) {
    window._ncfPromptPresetSteps = window._ncfPromptPresetSteps || {};
    window._ncfPromptPresetSteps[stepDef.id] = {
      presets: stepDef.presets,
      label: stepDef.presets_label,
      choose: _choosePreset,
    };

    // No sibling image_picker step claimed this preset set (plain prompt
    // flows, e.g. Look Book) — fall back to the original in-card button so
    // presets are never silently hidden.
    var _claimedBySubjectStep = Array.isArray(allSteps) && allSteps.some(function (s) {
      return s.type === 'image_picker' && s.subject_input;
    });
    if (!_claimedBySubjectStep) {
      var piPresetWrap = document.createElement('div');
      piPresetWrap.className = 'nsc-preset-wrap ncf-prompt-preset-wrap';
      var piPresetBtn = document.createElement('button');
      piPresetBtn.type = 'button';
      piPresetBtn.className = 'nsc-preset-btn';
      piPresetBtn.innerHTML =
        '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>' +
        '<line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>' +
        '<line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>' +
        '<span>' + escHtml(stepDef.presets_label || 'Presets') + '</span>';
      piPresetBtn.classList.add('nsc-options-trigger');
      piPresetBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        _openPromptPresetsPanel(stepDef.presets_label || 'Presets', stepDef.presets, _choosePreset, ta.value);
      });

      piPresetWrap.appendChild(piPresetBtn);
      el.appendChild(piPresetWrap);
    }
  }

  var ta = document.createElement('textarea');
  ta.className = 'nsc-textarea';
  ta.id = 'ncf-input-' + stepDef.id;
  ta.rows = stepDef.rows || 3;
  ta.placeholder = stepDef.placeholder || '';
  el.appendChild(ta);

  // Static default text (flows without a vision/LLM step to generate one
  // dynamically, e.g. mix flows with a fixed instruction) — real editable
  // value, not just greyed placeholder hint text.
  if (stepDef.default) {
    ta.value = _applyTemplate(String(stepDef.default));
    setVal(stepDef.id, 'prompt_text', ta.value.trim());
  }

  // Chat flows: scene_prompt starts disabled until the LLM fills it
  var _isChatScenePrompt = typeof flowId === 'string' && flowId.indexOf('.chat') !== -1 && stepDef.id === 'scene_prompt';
  if (_isChatScenePrompt) {
    ta.disabled = true;
    ta.classList.add('is-prefill-pending');
    ta.placeholder = tF('Click "Update scene prompt" to generate with AI…');
  }

  // Phrase chips (Chat's scene_prompt only, #109): a session's prompt grows by
  // edit after edit, and leftover fragments the image model misreads are hard
  // to spot in a wall of comma-separated text. Mirrors ta.value read-only, one
  // chip per ","/"."-separated phrase — click a chip to drop that phrase
  // (with its trailing separator) from the real textarea below, which stays
  // fully free-text and editable exactly as before. Kept in sync with every
  // in-file place that sets ta.value directly (below); flow-gallery.js's chat
  // bar, which also writes this textarea from outside this closure, re-fires
  // a real "input" event after it does so the listener here catches it too.
  var chipsWrap = null;
  if (_isChatScenePrompt) {
    chipsWrap = document.createElement('div');
    chipsWrap.className = 'ncf-prompt-chips';
    chipsWrap.hidden = true;
    el.insertBefore(chipsWrap, ta);
  }
  function _splitPromptPhrases(text) {
    // Alternating [phrase, separator, phrase, separator, …] — the separator
    // carries its punctuation plus any following whitespace, so re-joining
    // every kept pair reproduces the original spacing exactly.
    var parts = String(text || '').split(/([,.]+\s*)/);
    var phrases = [];
    for (var i = 0; i < parts.length; i += 2) {
      var phrase = parts[i] || '';
      var sep = parts[i + 1] || '';
      if (phrase.trim() || sep.trim()) phrases.push({ phrase: phrase, sep: sep });
    }
    return phrases;
  }
  function _renderPromptChips() {
    if (!chipsWrap) return;
    var phrases = _splitPromptPhrases(ta.value);
    chipsWrap.innerHTML = '';
    var shown = 0;
    phrases.forEach(function (p, idx) {
      var label = p.phrase.trim();
      if (!label) return; // pure leading/stray separator — nothing to show
      shown++;
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'ncf-prompt-chip';
      chip.textContent = label;
      chip.title = tF('Remove this phrase');
      chip.addEventListener('click', function () {
        var rest = phrases.slice();
        rest.splice(idx, 1);
        ta.value = rest.map(function (r) { return r.phrase + r.sep; }).join('').trim();
        _syncOnConfirm();
        _renderPromptChips();
        if (typeof updateGenerateBtn === 'function') updateGenerateBtn();
      });
      chipsWrap.appendChild(chip);
    });
    chipsWrap.hidden = !shown;
  }

  // Restore prompt from session history click
  try {
    if (_pendingSession) {
      var _restoredPrompt = (_pendingSession.data && _pendingSession.data.prompt) || _pendingSession.prompt || '';
      if (_restoredPrompt && stepDef.id === 'prompt') {
        ta.value = _restoredPrompt;
        setVal(stepDef.id, 'prompt_text', _restoredPrompt.trim());
      }
    }
  } catch (_) {}
  _renderPromptChips();

  // --ar / --no / --seed… (flow-prompt-params.js): Create flows only — their
  // graphs are the ones built by workflow_service._apply_prompt_params.
  if (typeof NcfPromptParams !== 'undefined' && typeof flowId === 'string' && flowId.indexOf('create.') === 0) {
    NcfPromptParams.attach(ta);
  }

  function _syncOnConfirm() {
    setVal(stepDef.id, 'prompt_text', ta.value.trim());
    // Chat flows: mirror world text into scene_prompt store so Generate works when AI is skipped
    if (typeof flowId === 'string' && flowId.indexOf('.chat') !== -1 && stepDef.id === 'world') {
      var _sTa = document.getElementById('ncf-input-scene_prompt');
      if (_sTa && _sTa.disabled) {
        setVal('scene_prompt', 'prompt_text', ta.value.trim());
      }
    }
    if (!stepDef._sessionSyncFrozen && stepDef.on_confirm && stepDef.on_confirm.set_session) {
      Object.keys(stepDef.on_confirm.set_session).forEach(function (k) {
        if (stepDef.on_confirm.set_session[k] === 'steps.' + stepDef.id + '.output.prompt_text') {
          sessionState[k] = ta.value.trim();
        }
      });
    }
    _renderPromptChips();
  }

  ta.addEventListener('input', _syncOnConfirm);
  ta.addEventListener('change', _syncOnConfirm);
  ta.addEventListener('paste', function () { setTimeout(_syncOnConfirm, 0); });

  // ── Style kept apart from the idea (style_picker: "separate") ────────────
  // The picked style lives in this step's own values (style_prefix /
  // style_suffix / style_name) and shows as a removable chip under the box;
  // an "ncf-style-changed" event tells the compose box below to rebuild.
  var _styleChip = null;
  function _renderStyleChip() {
    if (!_styleChip) return;
    var name = getVal(stepDef.id, 'style_name') || '';
    _styleChip.hidden = !name;
    if (!name) { _styleChip.innerHTML = ''; return; }
    _styleChip.innerHTML = '';
    var lbl = document.createElement('span');
    lbl.textContent = tF('Style') + ': ' + tF(name);
    var x = document.createElement('button');
    x.type = 'button';
    x.className = 'ncf-style-chip-clear';
    x.setAttribute('aria-label', tF('Remove style'));
    x.textContent = '×';
    x.addEventListener('click', function () { _setPickedStyle(null); });
    _styleChip.appendChild(lbl);
    _styleChip.appendChild(x);
  }
  function _setPickedStyle(style) {
    setVal(stepDef.id, 'style_prefix', style ? String(style.prefix || '').trim() : '');
    setVal(stepDef.id, 'style_suffix', style ? String(style.suffix || '').trim() : '');
    setVal(stepDef.id, 'style_name', style ? String(style.name || '') : '');
    _renderStyleChip();
    document.dispatchEvent(new CustomEvent('ncf-style-changed', { detail: { stepId: stepDef.id } }));
    if (typeof updateGenerateBtn === 'function') updateGenerateBtn();
  }
  if (stepDef.style_picker === 'separate') {
    _styleChip = document.createElement('div');
    _styleChip.className = 'ncf-style-chip';
    _styleChip.hidden = true;
    if (ta.nextSibling) el.insertBefore(_styleChip, ta.nextSibling);
    else el.appendChild(_styleChip);
    _renderStyleChip();
  }

  // ── Composed prompt (style_compose_from: "<idea step id>") ──────────────
  // Live "prefix, idea, suffix" of the source step's text and picked style.
  // Stays editable: a hand edit is kept while the idea changes, and only a
  // new style pick (an explicit action) rebuilds over it.
  // The idea comes from style_compose_from; the style's wording from
  // style_source (defaults to the same step) — e.g. Refine's Style Reference
  // takes it from the image step, whose Styles button loads a catalog
  // style's picture AND its prefix/suffix.
  if (stepDef.style_compose_from) {
    var _srcId = stepDef.style_compose_from;
    var _styleSrcId = stepDef.style_source || _srcId;
    var _lastComposed = null;
    function _compose() {
      var srcTa = document.getElementById('ncf-input-' + _srcId);
      var idea = srcTa ? srcTa.value.trim() : (getVal(_srcId, 'prompt_text') || '');
      return [getVal(_styleSrcId, 'style_prefix'), idea, getVal(_styleSrcId, 'style_suffix')]
        .map(function (s) { return String(s || '').trim(); })
        .filter(Boolean)
        .join(', ');
    }
    function _rebuildComposed(force) {
      if (!force && _lastComposed !== null && ta.value !== _lastComposed) return; // hand-edited
      var next = _compose();
      ta.value = next;
      _lastComposed = next;
      _syncOnConfirm();
      if (typeof updateGenerateBtn === 'function') updateGenerateBtn();
    }
    // Style picked on a different step (the image): show which style's
    // wording is mixed in here, with × to drop just the wording.
    var _composeChip = null;
    function _renderComposeChip() {
      if (!_composeChip) return;
      var name = getVal(_styleSrcId, 'style_name') || '';
      var hasText = !!(getVal(_styleSrcId, 'style_prefix') || getVal(_styleSrcId, 'style_suffix'));
      _composeChip.hidden = !(name && hasText);
      _composeChip.innerHTML = '';
      if (_composeChip.hidden) return;
      var lbl = document.createElement('span');
      lbl.textContent = tF('Style') + ': ' + tF(name);
      var x = document.createElement('button');
      x.type = 'button';
      x.className = 'ncf-style-chip-clear';
      x.setAttribute('aria-label', tF('Remove style wording'));
      x.title = tF('Remove the style wording (keeps the reference image)');
      x.textContent = '×';
      x.addEventListener('click', function () {
        setVal(_styleSrcId, 'style_prefix', '');
        setVal(_styleSrcId, 'style_suffix', '');
        _renderComposeChip();
        _rebuildComposed(true);
      });
      _composeChip.appendChild(lbl);
      _composeChip.appendChild(x);
    }
    if (_styleSrcId !== _srcId) {
      _composeChip = document.createElement('div');
      _composeChip.className = 'ncf-style-chip';
      _composeChip.hidden = true;
      if (ta.nextSibling) el.insertBefore(_composeChip, ta.nextSibling);
      else el.appendChild(_composeChip);
    }
    var _srcTa = document.getElementById('ncf-input-' + _srcId);
    if (_srcTa) _srcTa.addEventListener('input', function () { _rebuildComposed(false); });
    document.addEventListener('ncf-style-changed', function (e) {
      if (e.detail && e.detail.stepId === _styleSrcId) {
        _renderComposeChip();
        _rebuildComposed(true);
      }
    });
    if (!ta.value.trim()) _rebuildComposed(true);
    else _lastComposed = ta.value;
  }

  // ── Drop an image → extract its embedded prompt (ComfyUI or A1111/CivitAI
  // metadata) and fill this textarea with it. The image's workflow doesn't
  // need to be one of ours — we only read whatever text is embedded, we
  // never import/run it. ─────────────────────────────────────────────────
  if (stepDef.drop_image_prompt) {
    ta.addEventListener('dragover', function (e) {
      e.preventDefault();
      ta.classList.add('is-drag-over');
    });
    ta.addEventListener('dragleave', function () {
      ta.classList.remove('is-drag-over');
    });
    ta.addEventListener('drop', function (e) {
      e.preventDefault();
      ta.classList.remove('is-drag-over');
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file || !/^image\//.test(file.type)) return;
      file.arrayBuffer().then(function (buf) {
        var chunks = _readImageMetadataChunks(buf);
        var allCandidates = _extractPromptCandidatesFromImageMeta(chunks);

        // The sampler's "negative" link (see _extractPromptCandidatesFromComfyGraph)
        // tells us exactly which text node is the negative prompt — but we no
        // longer apply it silently: it gets its own explicit "Apply negative
        // prompt" button in the picker panel, so the user decides whether to
        // overwrite their current negative prompt.
        var negativeCandidate = allCandidates.find(function (c) { return c.role === 'negative'; });
        var candidates = allCandidates.filter(function (c) { return c.role !== 'negative'; });

        if (!candidates.length && !negativeCandidate) {
          if (typeof showErrorToast === 'function') showErrorToast(tF('No prompt found in this image’s metadata'));
          return;
        }

        function fill(text) {
          ta.value = text;
          ta.dispatchEvent(new Event('input'));
          ta.focus();
        }
        function applyNegative() {
          if (!negativeCandidate) return;
          selectedNegativePrompt = negativeCandidate.text;
          var negTa = document.getElementById('ncf-negative-prompt');
          if (negTa) negTa.value = negativeCandidate.text;
          if (typeof saveParams === 'function') saveParams();
          if (typeof showToast === 'function') showToast(tF('Negative prompt applied from image metadata'), 'info');
        }

        // Unambiguous positive prompt — fill it straight away, same as
        // before. A negative candidate on top of that still gets its own
        // panel below (with only the "Apply negative" action, no list).
        if (candidates.length === 1) fill(candidates[0].text);

        if (candidates.length <= 1 && !negativeCandidate) return;

        var panelTitle = candidates.length > 1 ? 'Choose a prompt' : 'Apply negative prompt';
        openOptionsPanel(panelTitle, function (body) {
          if (candidates.length > 1) {
            var list = document.createElement('div');
            list.className = 'nse-model-list';
            candidates.forEach(function (c) {
              var btn = document.createElement('button');
              btn.type = 'button';
              btn.className = 'nse-model-item ncf-history-item';
              btn.title = c.text;
              var preview = c.text.length > 140 ? c.text.slice(0, 140) + '…' : c.text;
              btn.innerHTML =
                '<strong style="display:block;font-size:var(--fs-xxs);opacity:0.6;margin-bottom:2px;font-weight:600;">' +
                escHtml(c.label) + '</strong>' + escHtml(preview);
              btn.addEventListener('click', function () {
                fill(c.text);
                closeOptionsPanel();
              });
              list.appendChild(btn);
            });
            body.appendChild(list);
          }

          if (negativeCandidate) {
            var negList = document.createElement('div');
            negList.className = 'nse-model-list ncf-negative-apply-list';
            var negBtn = document.createElement('button');
            negBtn.type = 'button';
            negBtn.className = 'nse-model-item ncf-history-item ncf-negative-apply-btn';
            negBtn.title = negativeCandidate.text;
            var negPreview = negativeCandidate.text.length > 140 ? negativeCandidate.text.slice(0, 140) + '…' : negativeCandidate.text;
            negBtn.innerHTML =
              '<strong style="display:block;font-size:var(--fs-xxs);opacity:0.6;margin-bottom:2px;font-weight:600;">' +
              'Apply negative prompt</strong>' + escHtml(negPreview);
            negBtn.addEventListener('click', function () {
              applyNegative();
              negBtn.disabled = true;
              negBtn.classList.add('is-applied');
            });
            negList.appendChild(negBtn);
            body.appendChild(negList);
          }
        });
      }).catch(function () {
        if (typeof showErrorToast === 'function') showErrorToast(tF('Could not read this image'));
      });
    });
  }

  if (stepDef.hint) el.appendChild(mkHint(stepDef.hint));

  // ── Strip buttons (remove_elements / remove_characters / remove_background) ──
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

    var _activeStrips = {};
    var stripRow = document.createElement('div');
    stripRow.className = 'ncf-strip-row';

    // Apply button
    var applyStripBtn = document.createElement('button');
    applyStripBtn.type = 'button';
    applyStripBtn.className = 'ncf-strip-apply';
    applyStripBtn.textContent = tF('Apply');
    applyStripBtn.disabled = true;

    // Restore button
    var restoreBtn = document.createElement('button');
    restoreBtn.type = 'button';
    restoreBtn.className = 'ncf-strip-restore';
    restoreBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 109-9 9.75 9.75 0 00-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg> Restore';
    restoreBtn.hidden = true;

    function _syncApplyBtn() {
      applyStripBtn.disabled = !Object.keys(_activeStrips).some(function (k) { return _activeStrips[k]; });
    }

    restoreBtn.addEventListener('click', function () {
      var base = getVal(stepDef.id, '_base_text');
      if (base == null) return;
      ta.value = base;
      setVal(stepDef.id, 'prompt_text', base);
      setVal(stepDef.id, '_base_text', null);
      restoreBtn.hidden = true;
      // Reset all toggles
      Object.keys(_activeStrips).forEach(function (k) { _activeStrips[k] = false; });
      stripRow.querySelectorAll('.ncf-strip-btn').forEach(function (b) { b.classList.remove('is-active'); });
      _syncApplyBtn();
      updateGenerateBtn();
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
        _syncApplyBtn();
      });

      stripRow.appendChild(btn);
    });

    applyStripBtn.addEventListener('click', async function () {
      var currentText = ta.value.trim();
      if (!currentText) return;

      // Build combined system prompt from active modes
      var activeDescs = stepDef.strip_buttons
        .filter(function (m) { return _activeStrips[m] && _STRIP_CFG[m]; })
        .map(function (m) { return '- ' + _STRIP_CFG[m].removeDesc; });
      if (!activeDescs.length) return;

      var sysPrompt = 'Task: edit a Stable Diffusion / Flux prompt (comma-separated tags).\n' +
        'DELETE every tag that belongs to the following categories:\n' +
        activeDescs.join('\n') +
        '\nKEEP all tags that are: clothing, character accessories (watch, jewelry...), body features, character names, quality tags (masterpiece, best quality, highres, 8k...), LoRA triggers (word-style, word-mix...), lighting and rendering terms, or environment/location words.\n' +
        'Return ONLY the edited tag list, no explanation.';

      applyStripBtn.classList.add('is-loading');
      applyStripBtn.textContent = '…';
      stripRow.querySelectorAll('.ncf-strip-btn').forEach(function (b) { b.disabled = true; });

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
        // Save original before first apply
        if (getVal(stepDef.id, '_base_text') == null) {
          setVal(stepDef.id, '_base_text', currentText);
        }
        // Update textarea without input event (session.world_context stays intact)
        ta.value = stripped;
        setVal(stepDef.id, 'prompt_text', stripped);
        restoreBtn.hidden = false;
        updateGenerateBtn();
      } catch (err) {
        console.warn('[strip apply]', err);
      } finally {
        applyStripBtn.classList.remove('is-loading');
        applyStripBtn.textContent = tF('Apply');
        stripRow.querySelectorAll('.ncf-strip-btn').forEach(function (b) { b.disabled = false; });
      }
    });

    stripRow.appendChild(applyStripBtn);
    stripRow.appendChild(restoreBtn);
    el.appendChild(stripRow);
  }

  // ── loop_back_to: confirm button for iterative chat steps ──────────────────
  if (stepDef.loop_back_to) {
    var loopRow = document.createElement('div');
    loopRow.className = 'ncf-loop-row';
    var loopBtn = document.createElement('button');
    loopBtn.type = 'button';
    loopBtn.className = 'ncf-loop-apply-btn';
    loopBtn.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><path d="M5 12h14M12 5l7 7-7 7"/></svg>' +
      '<span>' + escHtml(tF('Apply change')) + '</span>';
    loopBtn.addEventListener('click', function () {
      var instrText = ta.value.trim();
      if (!instrText) return;
      setVal(stepDef.id, 'prompt_text', instrText);
      var llmDef = allSteps.find(function (s) { return s.type === 'llm_transform'; });
      if (llmDef && llmDef._llmRefs && llmDef._llmRefs.writeBtn) {
        llmDef._llmRefs.writeBtn.click();
      }
    });
    ta.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        loopBtn.click();
      }
    });
    loopRow.appendChild(loopBtn);
    el.appendChild(loopRow);
  }

  // ── quick_llm_action: inline LLM button on prompt_input step ─────────────
  var qla = stepDef.quick_llm_action;
  if (qla && qla.calls && qla.output_to) {
    var qlaRow = document.createElement('div');
    qlaRow.className = 'ncf-qla-row';

    var qlaBtn = document.createElement('button');
    qlaBtn.type = 'button';
    qlaBtn.id = 'ncf-qla-btn-' + stepDef.id;
    qlaBtn.className = 'nss-generate-scenes-btn ncf-qla-btn';
    qlaBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true" style="width:15px;height:15px"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>' +
      '<span>' + escHtml(qla.label || 'Generate') + '</span>';

    var qlaStatus = document.createElement('span');
    qlaStatus.className = 'ncf-qla-status';

    qlaBtn.addEventListener('click', async function () {
      if (isWritingScene) return;
      var inputText = ta.value.trim();
      if (!inputText) { qlaStatus.textContent = tF('Enter a scene description first.'); return; }

      var syntheticStep = {
        calls: qla.calls,
        input_from: 'steps.' + stepDef.id + '.output.prompt_text',
        context_from: qla.context_from || {},
        system_prompt: qla.system_prompt || undefined,
      };

      var targetTa = document.getElementById('ncf-input-' + qla.output_to);
      await runLLM(syntheticStep, qlaBtn, qlaBtn.querySelector('span'), qlaStatus, targetTa);

      // runLLM stores result under syntheticStep.id (undefined) — manually sync the target step
      if (targetTa && targetTa.value) {
        setVal(qla.output_to, 'prompt_text', targetTa.value.trim());
        updateGenerateBtn();
      }
    });

    qlaRow.appendChild(qlaBtn);
    qlaRow.appendChild(qlaStatus);
    el.appendChild(qlaRow);
  }
}

// ── Prompt presets subpanel ─────────────────────────────────────────────────
// Presets open in the side options panel (same place as Edit Prompt,
// Downscale, Advanced…), not a floating dropdown over the prompt: each row
// shows the preset's name and the start of its wording; the one matching the
// current prompt is marked. Used by prompt_input's own Presets button and the
// subject step's copy of it (flow-step-image-picker.js).
function _openPromptPresetsPanel(title, presets, choose, currentText) {
  var current = String(currentText || '').trim();
  openOptionsPanel(tF(title || 'Presets'), function (body) {
    var list = document.createElement('div');
    list.className = 'nsc-quality-list ncf-preset-list';
    list.setAttribute('role', 'radiogroup');
    presets.forEach(function (pr) {
      var prLabel = typeof pr === 'object' ? (pr.label || pr.text || '') : String(pr);
      var prText  = typeof pr === 'object' ? (pr.text || pr.label || '') : String(pr);
      var active = !!current && current.indexOf(prText.trim()) !== -1;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'nsc-quality-btn' + (active ? ' is-active' : '');
      btn.setAttribute('role', 'radio');
      btn.setAttribute('aria-checked', active ? 'true' : 'false');
      btn.innerHTML = '<span class="nsc-quality-dot"></span>' +
        '<span class="nsc-quality-copy"><strong></strong><small></small></span>';
      btn.querySelector('strong').textContent = tF(prLabel);
      if (prText !== prLabel) btn.querySelector('small').textContent = prText;
      btn.addEventListener('click', function () {
        choose(pr);
        closeOptionsPanel();
      });
      list.appendChild(btn);
    });
    body.appendChild(list);
  });
}

// ── Edit Prompt panel (Prefix / Prompt idea / Suffix → Final prompt) ───────
// Shared by prompt_input (this file) and the prompt_history field type
// (flow-step-workflow-params.js) — both call this the same way.
//
// Persistence: Prefix/Idea/Suffix are stored independently under the image
// step's namespace (setVal(imageStepId, 'edit_prompt_<field>', ...)) so the
// three clauses are never re-derived from the target textarea's *composed*
// value (reopening used to show "prefix, idea, suffix" back in the Idea box).
//
// No Apply button: every change lands in the prompt right away. A style
// picked or described on the image step is applied the same way without the
// panel ever opening (_applyStyleToPrompt below) — the panel is only for
// hand-tuning the wording.

// "oil painting," + "a fox" + ", thick impasto" → "oil painting, a fox, thick
// impasto": catalog prefixes end in a comma and suffixes start with one, so
// joining them raw doubled the commas.
function _editPromptJoin(prefix, idea, suffix) {
  return [prefix, idea, suffix]
    .map(function (s) { return String(s || '').replace(/^[\s,]+|[\s,]+$/g, ''); })
    .filter(Boolean)
    .join(', ');
}

// The idea clause for imageStepId. Once the panel or a style pick has stored
// one it is the source of truth — unless the user has since typed straight
// into the prompt box, in which case what they typed (minus the prefix/suffix
// last composed around it) becomes the idea.
function _editPromptIdea(imageStepId, ta) {
  var stored = getVal(imageStepId, 'edit_prompt_idea');
  var current = String(ta.value || '').trim();
  var last = getVal(imageStepId, 'edit_prompt_last');
  var hasStored = stored !== undefined && stored !== null;
  // No composition on record: a session from before this existed (its box
  // may hold an old composed prompt — trust the stored idea) or a first run.
  if (!last) return hasStored ? stored : current;
  if (current === '' || current === last) return hasStored ? stored : '';
  var clean = function (s) { return String(s || '').replace(/^[\s,]+|[\s,]+$/g, ''); };
  var oldPrefix = clean(getVal(imageStepId, 'edit_prompt_last_prefix'));
  var oldSuffix = clean(getVal(imageStepId, 'edit_prompt_last_suffix'));
  var idea = current;
  if (oldPrefix && idea.indexOf(oldPrefix) === 0) idea = idea.slice(oldPrefix.length);
  if (oldSuffix && idea.slice(-oldSuffix.length) === oldSuffix) idea = idea.slice(0, idea.length - oldSuffix.length);
  return clean(idea);
}

// Writes `composed` into the prompt box and remembers what it was built from,
// so the next style pick can swap the style wording without touching the idea.
function _editPromptWrite(imageStepId, ta, onApply, composed, prefix, suffix) {
  setVal(imageStepId, 'edit_prompt_last', composed);
  setVal(imageStepId, 'edit_prompt_last_prefix', prefix || '');
  setVal(imageStepId, 'edit_prompt_last_suffix', suffix || '');
  ta.value = composed;
  onApply(composed);
}

// A style picked from the catalog or described from the image: wrap the
// current idea in its prefix/suffix and apply — no panel, no Apply click.
function _applyStyleToPrompt(imageStepId, ta, onApply, ideaOverride) {
  var prefix = getVal(imageStepId, 'edit_prompt_prefix');
  if (prefix === undefined || prefix === null) prefix = getVal(imageStepId, 'style_prefix') || '';
  var suffix = getVal(imageStepId, 'edit_prompt_suffix');
  if (suffix === undefined || suffix === null) suffix = getVal(imageStepId, 'style_suffix') || '';
  var idea = (ideaOverride !== undefined) ? ideaOverride : _editPromptIdea(imageStepId, ta);
  setVal(imageStepId, 'edit_prompt_idea', idea);
  _editPromptWrite(imageStepId, ta, onApply, _editPromptJoin(prefix, idea, suffix), prefix, suffix);
}

// Listens for the image step's style changes (catalog pick, Describe style,
// a new image clearing the old style) and applies them to `ta`. Stops on its
// own once `ta` leaves the page (flow switch / re-render).
function _bindStyleAutoApply(imageStepId, ta, onApply) {
  function onStyle(e) {
    if (!ta.isConnected) { document.removeEventListener('ncf-style-changed', onStyle); return; }
    if (!e.detail || e.detail.stepId !== imageStepId) return;
    _applyStyleToPrompt(imageStepId, ta, onApply);
  }
  document.addEventListener('ncf-style-changed', onStyle);
}

function _openEditPromptPanel(imageStepId, ta, onApply, title) {
  var storeId = imageStepId;

  openOptionsPanel(tF(title || 'Edit Prompt'), function (body) {
    function _stored(key, fallback) {
      var v = getVal(storeId, key);
      return (v !== undefined && v !== null) ? v : fallback;
    }
    var initialPrefix = _stored('edit_prompt_prefix', getVal(imageStepId, 'style_prefix') || '');
    var initialSuffix = _stored('edit_prompt_suffix', getVal(imageStepId, 'style_suffix') || '');
    var initialIdea = _editPromptIdea(imageStepId, ta);

    // label (+ optional action on the right) and its input, same look as the
    // rest of the options panel.
    function _field(labelText, value, rows, action) {
      var row = document.createElement('div');
      row.className = 'nsc-field-row nsc-field-row--compose';
      var head = document.createElement('div');
      head.className = 'nsc-field-header ncf-ep-head';
      var lbl = document.createElement('label');
      lbl.className = 'nsc-param-title';
      lbl.textContent = tF(labelText);
      head.appendChild(lbl);
      if (action) head.appendChild(action);
      row.appendChild(head);
      var input = document.createElement(rows > 1 ? 'textarea' : 'input');
      input.className = 'nsc-input' + (rows > 1 ? ' nsc-textarea' : '');
      if (rows > 1) input.rows = rows;
      else input.type = 'text';
      input.value = value || '';
      row.appendChild(input);
      body.appendChild(row);
      return input;
    }

    function _pillBtn(label, iconSvg, extraClass) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ncf-ep-pill' + (extraClass ? ' ' + extraClass : '');
      b.innerHTML = iconSvg + '<span></span>';
      b.querySelector('span').textContent = tF(label);
      return b;
    }
    function _setBusy(btn, busyLabel) {
      var span = btn.querySelector('span');
      var orig = span.textContent;
      btn.disabled = true;
      btn.classList.add('is-busy');
      span.textContent = tF(busyLabel);
      return function () {
        btn.disabled = false;
        btn.classList.remove('is-busy');
        span.textContent = orig;
      };
    }

    // ── Style from image (vision) — only when the image step holds a style
    // reference. Manual trigger only: the user picks the vision model and
    // how much detail they want back (auto-running it used to label photos
    // as illustrations and skew generation toward a painted look).
    var styleImageUrl = getVal(imageStepId, 'image_data_url') || '';
    // Shared classification preamble both vision prompts open with — decide
    // the image's broad kind FIRST, then describe only with vocabulary that
    // fits it (a photo described with "linework"/"cel-shading", or a 3D
    // render described with "brushstrokes", biases the generator toward the
    // wrong medium).
    var _VISION_KIND_PREAMBLE = 'You are a visual style analyst. Look at the reference image and first ' +
      'silently classify it into exactly one of these four kinds: ' +
      '"photo" (a real photograph), "anime_cartoon" (anime, cartoon, or other cel-shaded/flat-color ' +
      'stylized art), "illustration_painting" (painterly illustration, concept art, digital or ' +
      'traditional painting, comic/graphic-novel art), or "3d_render" (3D-rendered CGI, ' +
      'video-game render, or product render). ';
    var prefixInput, ideaInput, suffixInput, finalInput;

    if (styleImageUrl && typeof makeVisionModelBtn === 'function') {
      var visionTitle = document.createElement('p');
      visionTitle.className = 'nsc-param-title';
      visionTitle.textContent = tF('Style from image');
      body.appendChild(visionTitle);

      var visionRow = document.createElement('div');
      visionRow.className = 'ncf-ep-vision-row';
      var eyeIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
      var listIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/></svg>';
      var getStyleBtn = _pillBtn('Short', eyeIcon);
      getStyleBtn.title = tF('Short style tags into Prefix');
      var detailedVisionBtn = _pillBtn('Detailed', listIcon);
      detailedVisionBtn.title = tF('Full style breakdown into Prompt idea');
      var visionBtn = makeVisionModelBtn();
      visionBtn.classList.add('ncf-ep-vision-model');
      visionRow.appendChild(getStyleBtn);
      visionRow.appendChild(detailedVisionBtn);
      visionRow.appendChild(visionBtn);
      body.appendChild(visionRow);

      // POSTs describe-image with the given systemPrompt and hands the
      // trimmed description to onDone(desc).
      function _runVisionDescribe(btn, busyLabel, systemPrompt, onDone) {
        var done = _setBusy(btn, busyLabel);
        fetch('/api/models/chat/describe-image', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            imageDataUrl: styleImageUrl,
            describeType: 'style',
            describeScope: 'style',
            describeFormat: 'phrase',
            forceRefresh: true,
            systemPrompt: systemPrompt,
          }),
        })
          .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
          .then(function (res) {
            if (!res.ok || res.data.error) throw new Error(res.data.error || 'Vision describe failed');
            var desc = String(res.data.description || '').trim();
            if (desc) onDone(desc);
          })
          .catch(function (err) {
            if (typeof showErrorToast === 'function') showErrorToast(tF('Vision describe failed:') + ' ' + err.message);
          })
          .finally(done);
      }

      getStyleBtn.addEventListener('click', function () {
        _runVisionDescribe(getStyleBtn, 'Looking…', _VISION_KIND_PREAMBLE +
          'Then describe ONLY the visual style — never the subject, pose, or composition — ' +
          'as a single concise comma-separated list of style qualities, in English, using ONLY the ' +
          'vocabulary for that one kind: ' +
          '"photo": lighting, color grading, lens/depth-of-field character, film grain or texture, ' +
          'exposure and contrast. Never mention linework, cel-shading, brushstrokes, or rendering engine terms. ' +
          '"anime_cartoon": line style, cel-shading vs. flat color, outline weight, color palette, ' +
          'shading style (e.g. cel-shaded, flat, gradient), art style reference if recognizable. ' +
          '"illustration_painting": medium (e.g. watercolor, oil, digital painting, ink), technique, ' +
          'linework, brushwork, color palette, rendering/painting style. ' +
          '"3d_render": material and surface qualities (e.g. glossy, matte, subsurface scattering), ' +
          'lighting setup, render engine look (e.g. photorealistic, stylized, toon-shaded), texture detail. ' +
          'Return ONLY the comma-separated style phrase — no explanation, no preamble, no quotes, and never ' +
          'mention which of the four kinds you picked.',
        function (desc) {
          prefixInput.value = desc;
          setVal(storeId, 'edit_prompt_prefix', desc);
          _recompose();
        });
      });

      // Detailed — the long, numbered-headers technical breakdown, same
      // photo-vs-illustration-vs-anime-vs-render branch as Short so the
      // vocabulary fits the kind. Written into Prompt idea (the multi-line
      // box), not Prefix — it's a full report, not a short tag list.
      detailedVisionBtn.addEventListener('click', function () {
        _runVisionDescribe(detailedVisionBtn, 'Analyzing…', _VISION_KIND_PREAMBLE +
          'Start section 1 by stating that kind as the Image Type. Then, using ONLY vocabulary that fits ' +
          'the kind you picked (do not describe brushwork/linework on a photo, do not describe camera/lens ' +
          'terms on an illustration or 3D render, do not describe painting technique on a 3D render), write ' +
          'a structured technical breakdown of the visual style as markdown with EXACTLY these ten "### N. Title" ' +
          'sections, each 1-4 sentences: ' +
          '1. Image Type — the kind you classified it as. ' +
          '2. Chiaroscuro & tonal values. ' +
          '3. Lighting treatment. ' +
          '4. Shadow language. ' +
          '5. Color palette & harmony. ' +
          '6. Color grading & tonal treatment. ' +
          '7. Texture & surface rendering. ' +
          '8. Depth & spatial rendering. ' +
          '9. Technical & medium-specific signatures. ' +
          '10. Mood & stylistic reference. ' +
          'Describe ONLY the visual style — never the subject, pose, or composition, except where needed to ' +
          'illustrate a style point. Write in English. Do not wrap the output in any special tokens or code fences.',
        function (desc) {
          ideaInput.value = desc;
          setVal(storeId, 'edit_prompt_idea', desc);
          _recompose();
        });
      });
    }

    var sparkIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>';
    var refineBtn = _pillBtn('Refine with LLM', sparkIcon, 'ncf-ep-pill--small');

    prefixInput = _field('Prefix', initialPrefix, 1);
    ideaInput   = _field('Prompt idea', initialIdea, 4);
    suffixInput = _field('Suffix', initialSuffix, 1);
    finalInput  = _field('Final prompt', '', 4, refineBtn);
    finalInput.classList.add('ncf-ep-final');

    var hint = document.createElement('p');
    hint.className = 'ncf-ep-hint';
    hint.textContent = tF('Changes apply to the prompt as you type.');
    body.appendChild(hint);

    function _apply(composed) {
      _editPromptWrite(imageStepId, ta, onApply, composed, prefixInput.value.trim(), suffixInput.value.trim());
    }
    // Editing Prefix/Idea/Suffix rebuilds Final prompt (dropping any Refine
    // result or hand edit on it) and applies it.
    function _recompose() {
      finalInput.value = _editPromptJoin(prefixInput.value, ideaInput.value, suffixInput.value);
      _apply(finalInput.value);
    }
    finalInput.value = _editPromptJoin(initialPrefix, initialIdea, initialSuffix);
    setVal(storeId, 'edit_prompt_idea', initialIdea);

    prefixInput.addEventListener('input', function () { setVal(storeId, 'edit_prompt_prefix', prefixInput.value); _recompose(); });
    ideaInput.addEventListener('input',   function () { setVal(storeId, 'edit_prompt_idea',   ideaInput.value);   _recompose(); });
    suffixInput.addEventListener('input', function () { setVal(storeId, 'edit_prompt_suffix', suffixInput.value); _recompose(); });
    finalInput.addEventListener('input',  function () { _apply(finalInput.value.trim()); });

    // Refine reads Idea but never writes back into it — the user's own
    // wording stays put so they can tweak it and re-refine; only Final
    // prompt (and so the prompt itself) gets the LLM's rewrite.
    refineBtn.addEventListener('click', function () {
      var current = ideaInput.value.trim();
      if (!current) return;
      var done = _setBusy(refineBtn, 'Refining…');
      fetch('/api/models/chat/studio-enhance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: current,
          level: 'quick',
          flair: 0,
          // Own systemPrompt (not the shared "studioQuick" default) so we can
          // pin the output language regardless of what the idea was typed in.
          systemPrompt: 'You are a prompt refinement assistant for AI image generation. ' +
            'Improve the given prompt clause with vivid, concrete visual detail while keeping its original meaning and intent. ' +
            'Keep the same format (comma-separated tags or a short flowing phrase, matching the input). ' +
            'Always respond in English, regardless of what language the input is written in. ' +
            'Return ONLY the improved prompt text — no explanation, no quotes, no preamble.',
        }),
      })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (res) {
          if (!res.ok || res.data.error) throw new Error(res.data.error || 'Refine error');
          if (res.data.enhancedPrompt) {
            finalInput.value = _editPromptJoin(prefixInput.value, res.data.enhancedPrompt.trim(), suffixInput.value);
            _apply(finalInput.value);
          }
        })
        .catch(function (err) {
          if (typeof showErrorToast === 'function') showErrorToast(tF('Refine failed:') + ' ' + err.message);
        })
        .finally(done);
    });
  });
}

// ── Image-drop prompt extraction (drop_image_prompt) ────────────────────────
// Reads embedded generation metadata client-side — no upload, no dependency
// on the image's own workflow being one of ours. PNG stores it in tEXt/iTXt
// chunks; WEBP stores it inside an EXIF sub-chunk (TIFF-structured ASCII
// tags) — ComfyUI's "Save Image (WEBP)"-with-metadata nodes write the same
// "prompt:{...}" JSON string there that PNG gets in its "prompt" chunk.
// JPEG (EXIF APP1) isn't handled yet.
function _readImageMetadataChunks(arrayBuffer) {
  var bytes = new Uint8Array(arrayBuffer);
  if (bytes.length >= 8 && bytes[0] === 137 && bytes[1] === 80 && bytes[2] === 78 && bytes[3] === 71) {
    return _readPngTextChunks(arrayBuffer);
  }
  if (bytes.length >= 12 &&
      bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 && // "RIFF"
      bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) { // "WEBP"
    return _readWebpMetadataChunks(arrayBuffer);
  }
  return {};
}

// zTXt (compressed) chunks aren't decoded — rare for the keywords we care about.
function _readPngTextChunks(arrayBuffer) {
  var chunks = {};
  var view = new DataView(arrayBuffer);
  var sig = [137, 80, 78, 71, 13, 10, 26, 10];
  if (view.byteLength < 8) return chunks;
  for (var s = 0; s < 8; s++) { if (view.getUint8(s) !== sig[s]) return chunks; }

  var offset = 8;
  while (offset + 8 <= view.byteLength) {
    var length = view.getUint32(offset);
    var type = String.fromCharCode(
      view.getUint8(offset + 4), view.getUint8(offset + 5),
      view.getUint8(offset + 6), view.getUint8(offset + 7)
    );
    var dataStart = offset + 8;
    if (dataStart + length > view.byteLength) break;

    if (type === 'tEXt') {
      var bytes = new Uint8Array(arrayBuffer, dataStart, length);
      var nullIdx = bytes.indexOf(0);
      if (nullIdx > 0) {
        var keyword = _pngBytesToStr(bytes.subarray(0, nullIdx));
        chunks[keyword] = _pngBytesToStr(bytes.subarray(nullIdx + 1));
      }
    } else if (type === 'iTXt') {
      var ibytes = new Uint8Array(arrayBuffer, dataStart, length);
      var kwEnd = ibytes.indexOf(0);
      if (kwEnd > 0) {
        var keyword2 = _pngBytesToStr(ibytes.subarray(0, kwEnd));
        var compressed = ibytes[kwEnd + 1];
        if (!compressed) {
          var rest = ibytes.subarray(kwEnd + 3); // skip compression flag + method
          var langEnd = rest.indexOf(0);
          var rest2 = rest.subarray(langEnd + 1);
          var transEnd = rest2.indexOf(0);
          chunks[keyword2] = _pngBytesToStr(rest2.subarray(transEnd + 1));
        }
      }
    } else if (type === 'IEND') {
      break;
    }
    offset = dataStart + length + 4; // +4 for the CRC
  }
  return chunks;
}

function _pngBytesToStr(bytes) {
  try { return new TextDecoder('utf-8').decode(bytes); } catch (_) {
    var s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return s;
  }
}

// WEBP: walk the RIFF sub-chunks looking for "EXIF", then read its ASCII/
// UNDEFINED TIFF tags (ComfyUI's WEBP-with-metadata nodes stash the same
// "prompt:{...}" JSON string PNG gets, just inside an EXIF tag instead of a
// tEXt chunk — tag id doesn't matter, every string tag value is a candidate).
function _readWebpMetadataChunks(arrayBuffer) {
  var chunks = {};
  var view = new DataView(arrayBuffer);
  if (view.byteLength < 12) return chunks;

  var offset = 12;
  var idx = 0;
  while (offset + 8 <= view.byteLength) {
    var fourcc = String.fromCharCode(
      view.getUint8(offset), view.getUint8(offset + 1),
      view.getUint8(offset + 2), view.getUint8(offset + 3)
    );
    var size = view.getUint32(offset + 4, true); // RIFF sizes are little-endian
    var dataStart = offset + 8;
    if (dataStart + size > view.byteLength) break;

    if (fourcc === 'EXIF') {
      _readExifAsciiTags(arrayBuffer, dataStart, size).forEach(function (text) {
        chunks['exif_' + (idx++)] = text;
      });
    }
    offset = dataStart + size + (size % 2); // RIFF chunks pad to an even size
  }
  return chunks;
}

// Minimal TIFF/EXIF reader — just enough to pull out ASCII/UNDEFINED tag
// values (type 2 / type 7); ignores every other tag type (numeric, rational,
// GPS, etc.) since we only care about text.
function _readExifAsciiTags(arrayBuffer, base, length) {
  var out = [];
  if (length < 8) return out;
  var view = new DataView(arrayBuffer, base, length);
  var b0 = view.getUint8(0), b1 = view.getUint8(1);
  var little;
  if (b0 === 0x49 && b1 === 0x49) little = true;       // "II"
  else if (b0 === 0x4D && b1 === 0x4D) little = false; // "MM"
  else return out;
  if (view.getUint16(2, little) !== 42) return out;

  var ifdOffset = view.getUint32(4, little);
  var depth = 0;
  while (ifdOffset > 0 && ifdOffset + 2 <= length && depth < 4) {
    var count = view.getUint16(ifdOffset, little);
    var entryBase = ifdOffset + 2;
    for (var i = 0; i < count; i++) {
      var entryOffset = entryBase + i * 12;
      if (entryOffset + 12 > length) break;
      var type = view.getUint16(entryOffset + 2, little);
      if (type !== 2 && type !== 7) continue; // 2=ASCII, 7=UNDEFINED
      var byteLen = view.getUint32(entryOffset + 4, little);
      if (byteLen <= 0 || byteLen > length) continue;
      var dataOffset = byteLen <= 4 ? entryOffset + 8 : view.getUint32(entryOffset + 8, little);
      if (dataOffset < 0 || dataOffset + byteLen > length) continue;
      var strBytes = new Uint8Array(arrayBuffer, base + dataOffset, byteLen);
      var str = _pngBytesToStr(strBytes).replace(/\0+$/, '');
      if (str.length > 8) out.push(str);
    }
    // Not following the next-IFD pointer — the tags we care about are always
    // in the first IFD (IFD0) for the tools that write them.
    break;
  }
  return out;
}

var _PROMPT_NODE_TYPE_RE = /textencode|text multiline|string literal|primitive.*string/i;

// Any text chunk value that parses as JSON gets treated as a ComfyUI node
// graph (optionally prefixed "prompt:", as WEBP EXIF tags carry it); anything
// else is tried as A1111/CivitAI-style generation-info text. Format-agnostic
// on purpose — the same logic runs whether the text came from a PNG chunk or
// a WEBP EXIF tag.
function _extractPromptCandidatesFromImageMeta(chunks) {
  var candidates = [];

  Object.keys(chunks).forEach(function (key) {
    var raw = chunks[key];
    if (!raw) return;

    var jsonPart = raw;
    var prefixMatch = /^prompt:([\s\S]*)$/.exec(raw);
    if (prefixMatch) jsonPart = prefixMatch[1];

    var graph = null;
    try { graph = JSON.parse(jsonPart); } catch (_) {}
    if (graph && typeof graph === 'object') {
      candidates = candidates.concat(_extractPromptCandidatesFromComfyGraph(graph));
      return;
    }

    try {
      var p = parseCivitAI(raw);
      if (p && p.positive) candidates.push({ label: tF('Positive prompt (image metadata)'), text: p.positive });
    } catch (_) {}
  });

  // Dedup identical text across sources (e.g. PNG's "prompt" and "workflow"
  // chunks often embed the same graph twice).
  var seen = {};
  return candidates.filter(function (c) {
    if (seen[c.text]) return false;
    seen[c.text] = true;
    return true;
  });
}

function _extractPromptCandidatesFromComfyGraph(obj) {
  var candidates = [];
  if (Array.isArray(obj.nodes)) {
    // UI-format: { nodes: [{ id, type, title, widgets_values: [...] }, ...] }
    // No reliable positive/negative link info in this shape — role stays unset.
    obj.nodes.forEach(function (n) {
      if (!n || !_PROMPT_NODE_TYPE_RE.test(n.type || '')) return;
      var widgets = Array.isArray(n.widgets_values) ? n.widgets_values : [];
      widgets.forEach(function (w) {
        if (typeof w === 'string' && w.trim().length > 3) {
          candidates.push({ label: (n.title || n.type) + ' #' + n.id, text: w.trim() });
        }
      });
    });
  } else {
    // API-format: { "3": { class_type, inputs: { text }, _meta: { title } }, ... }
    // Any node with link-shaped "positive"/"negative" inputs (KSampler and
    // its variants) tells us exactly which text node feeds which role —
    // more reliable than guessing from node titles.
    var roleByNodeId = {};
    Object.keys(obj).forEach(function (nodeId) {
      var node = obj[nodeId];
      var inputs = node && node.inputs;
      if (!inputs) return;
      ['positive', 'negative'].forEach(function (role) {
        var link = inputs[role];
        if (Array.isArray(link) && link.length === 2) roleByNodeId[String(link[0])] = role;
      });
    });

    Object.keys(obj).forEach(function (nodeId) {
      var node = obj[nodeId];
      if (!node || typeof node !== 'object') return;
      var classType = node.class_type || '';
      if (!_PROMPT_NODE_TYPE_RE.test(classType)) return;
      var text = node.inputs && node.inputs.text;
      if (typeof text === 'string' && text.trim().length > 3) {
        var title = (node._meta && node._meta.title) || classType;
        var role = roleByNodeId[nodeId] || null;
        candidates.push({ label: title + ' (#' + nodeId + ')', text: text.trim(), role: role });
      }
    });
  }
  return candidates;
}

// ── json_input ─────────────────────────────────────────────────────────────

// ── Bracket field editor ───────────────────────────────────────────────────
// Opt-in via `bracket_editor: true` on a prompt_input step.
//
// A template like
//   "A dramatic portrait of [subject] with [hair style], wearing [clothing]."
// is a set of named fields wearing a sentence. Editing them meant hunting
// inside the paragraph for the right pair of brackets and typing between them,
// which is exactly the job a form does better — and its JSON sibling already
// had one. This gives the same panel: one row per bracket, in order, each
// showing what is currently inside it.
//
// The sentence outside the brackets is never touched. That matters more here
// than in the JSON editor: everything outside the brackets is what the
// variations step is required to preserve verbatim, so an editor that could
// disturb it would break the flow's whole guarantee.

function _bracketSpans(text) {
  var spans = [];
  var re = /\[([^\]]*)\]/g;
  var m;
  while ((m = re.exec(String(text || ''))) !== null) {
    spans.push({ start: m.index, end: m.index + m[0].length, inner: m[1] });
  }
  return spans;
}

// Rebuild right-to-left so earlier offsets stay valid as lengths change.
function _bracketReplace(text, values) {
  var spans = _bracketSpans(text);
  var out = String(text || '');
  for (var i = spans.length - 1; i >= 0; i--) {
    var v = values[i];
    if (v === undefined) continue;
    out = out.slice(0, spans[i].start) + '[' + v + ']' + out.slice(spans[i].end);
  }
  return out;
}

function openBracketEditorPanel(stepDef, ta, onApply) {
  openOptionsPanel(tF('Template fields'), function (body) {
    var spans = _bracketSpans(ta.value);

    var rows = document.createElement('div');
    rows.className = 'ncf-json-rows';

    if (!spans.length) {
      rows.innerHTML =
        '<p style="padding:0.8rem 1rem;font-size:0.74rem;color:var(--muted)">' +
        'No [bracketed fields] in this template yet. Wrap the parts you want varied ' +
        'in square brackets, or use Templateize above to have them found for you.</p>';
      body.appendChild(rows);
      return;
    }

    spans.forEach(function (span, i) {
      var row = document.createElement('div');
      row.className = 'ncf-json-row';

      var lbl = document.createElement('label');
      lbl.className = 'ncf-json-row-label';
      lbl.setAttribute('for', 'ncf-bf-' + i);
      lbl.textContent = tF('field {n}').replace('{n}', i + 1);
      row.appendChild(lbl);

      var control;
      if (span.inner.length > 90) {
        control = document.createElement('textarea');
        control.rows = 3;
        control.className = 'ncf-json-row-textarea';
      } else {
        control = document.createElement('input');
        control.type = 'text';
      }
      control.classList.add('nsc-input', 'ncf-json-row-input');
      control.id = 'ncf-bf-' + i;
      control.dataset.idx = String(i);
      control.value = span.inner;
      row.appendChild(control);

      rows.appendChild(row);
    });

    body.appendChild(rows);

    var footer = document.createElement('div');
    footer.className = 'ncf-json-panel-footer';

    var applyBtn = document.createElement('button');
    applyBtn.type = 'button';
    applyBtn.className = 'nse-modal-apply';
    applyBtn.textContent = tF('Apply');
    applyBtn.addEventListener('click', function () {
      var values = [];
      rows.querySelectorAll('[data-idx]').forEach(function (c) {
        values[Number(c.dataset.idx)] = c.value;
      });
      var next = _bracketReplace(ta.value, values);
      ta.value = next;
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      setVal(stepDef.id, 'prompt_text', next);
      if (typeof onApply === 'function') onApply(next);
      if (typeof closeOptionsPanel === 'function') closeOptionsPanel();
    });
    footer.appendChild(applyBtn);
    body.appendChild(footer);

    var first = rows.querySelector('input, textarea');
    if (first) first.focus();
  }, { wide: true });
}
