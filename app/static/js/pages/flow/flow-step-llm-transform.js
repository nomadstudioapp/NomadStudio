'use strict';
// Step: llm_transform → renderLLMTransform, syncPrefillTargets

function renderLLMTransform(stepDef, el) {
  var params = stepDef.params || {};

  // Enhance level / Flair and the LLM model choice each get their own icon
  // button next to the step title (same pattern as Aspect ratio) instead of
  // showing everything inline — keeps the step down to just its title +
  // Assist button + prompt below.
  var llmStepLabelEl = el.querySelector('.nsc-step-label');
  if (llmStepLabelEl) {
    // Enhance level and Creativity are what the panel is for. A step that
    // declares neither used to open a panel containing a single switch —
    // and once the Context slider came out (it promised speed it could not
    // deliver and silently truncated prompts instead), that was every step
    // like this one. A panel to reach one toggle is a worse control than the
    // toggle, so those steps put Think straight in the label row instead.
    var hasPanelOptions = !!(params.level || params.flair);

    // The controls go on their own line under the title. Sharing the title's
    // row meant a step named "Generate variations" had to wrap to two lines to
    // make room for them in a narrow panel, and the chips were squeezed against
    // the right edge. Given the full width, the title fits on one line and the
    // controls read as a row of controls.
    var llmTools = document.createElement('span');
    llmTools.className = 'ncf-step-label-tools';

    // Bare icon-only circles always sit at the row's right edge — text/name
    // chips (the model button) and switches (Think) come first, reading
    // left to right, with the one control that's a plain circle (Assist
    // options) pushed past all of them via margin-left:auto. Was the other
    // way round (circle first); the model chip's own name text made it read
    // like a label for the circle instead of a control in its own right.
    var llmModelBtn = document.createElement('button');
    llmModelBtn.type = 'button';
    // --named so the model's name fits beside the icon. It used to be a bare
    // icon, which left the step that hands your idea to a language model as
    // the one place that never said which model was about to write — and the
    // model moves the result more than most controls on this page. Same
    // treatment the vision picker got in the Describe step.
    // ncf-llm-model-btn is the hook _saveModelSettings repaints through, so
    // every one of these chips renames itself the moment a model is picked.
    llmModelBtn.className = 'nsc-history-btn nsc-history-btn--named nsc-options-trigger ncf-llm-model-btn';
    llmModelBtn.setAttribute('aria-haspopup', 'dialog');
    llmModelBtn.setAttribute('aria-label', tF('Change LLM model'));
    llmModelBtn.innerHTML =
      '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<rect x="2" y="5" width="14" height="9" rx="1.5"/>' +
        '<line x1="5" y1="8" x2="5.01" y2="8"/><line x1="9" y1="8" x2="9.01" y2="8"/><line x1="13" y1="8" x2="13.01" y2="8"/>' +
        '<line x1="5" y1="11" x2="13" y2="11"/>' +
      '</svg>';
    var llmModelName = document.createElement('span');
    llmModelName.className = 'ncf-model-icon-name';
    llmModelBtn.appendChild(llmModelName);
    llmModelBtn.addEventListener('click', function () { openModelOptionsPanel(); });
    llmTools.appendChild(llmModelBtn);
    if (typeof loadPromptModelHint === 'function') {
      loadPromptModelHint(llmModelBtn, llmModelName);
    }

    if (!hasPanelOptions) {
      var thinkLabel = document.createElement('label');
      thinkLabel.className = 'ncf-chat-ep-toggle ncf-inline-think';
      thinkLabel.innerHTML =
        '<input type="checkbox" class="ncf-chat-ep-input">' +
        '<span class="ncf-chat-ep-track"><span class="ncf-chat-ep-thumb"></span></span>' +
        '<span class="ncf-chat-ep-text">' + escHtml(tF('Think')) + '</span>' +
        '<span class="ncf-chat-tip ncf-chat-tip--wide" role="tooltip">Off: fast, no reasoning. ' +
        'On: the model jots a brief thinking outline before writing the result — still fast, ' +
        'this is prompted, not a special reasoning mode.</span>';
      var thinkInput = thinkLabel.querySelector('input');
      thinkInput.checked = assistThinkMode;
      thinkInput.addEventListener('change', function () {
        assistThinkMode = thinkInput.checked;
        // One flow can show several of these, and they all read the same
        // setting — move them together so no two disagree on screen.
        document.querySelectorAll('.ncf-inline-think .ncf-chat-ep-input')
          .forEach(function (other) { other.checked = assistThinkMode; });
      });
      llmTools.appendChild(thinkLabel);
    }

    if (hasPanelOptions) {
      var llmOptionsBtn = document.createElement('button');
      llmOptionsBtn.type = 'button';
      llmOptionsBtn.className = 'nsc-history-btn nsc-options-trigger';
      llmOptionsBtn.setAttribute('aria-label', tF('Assist options'));
      llmOptionsBtn.innerHTML =
        '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">' +
          '<line x1="3" y1="5" x2="15" y2="5"/><circle cx="11" cy="5" r="1.6" fill="currentColor" stroke="none"/>' +
          '<line x1="3" y1="13" x2="15" y2="13"/><circle cx="7" cy="13" r="1.6" fill="currentColor" stroke="none"/>' +
        '</svg>';
      llmOptionsBtn.addEventListener('click', function () { openLLMOptionsPanel(params); });
      llmTools.appendChild(llmOptionsBtn);
    }

    llmStepLabelEl.appendChild(llmTools);
  }

  // Compose-prompt chip — only for ideogram_compose steps
  if (stepDef.calls === 'llm.ideogram_compose') {
    renderComposePromptChip(stepDef, el);
  }

  // Genre — used to be a full 3x3 card grid inline (a lot of vertical space
  // for a rarely-changed choice); now a compact title-row chip that opens
  // the shared side panel, same pattern as Presets (flow-step-workflow-
  // params.js) and Resolution/Aspect ratio above.
  if (params.genre) {
    var genreBlock = document.createElement('div');
    genreBlock.className = 'nse-control-block';
    genreBlock.innerHTML =
      '<p class="nsc-param-title nsc-param-title--flex">Genre ' +
      '<span class="nsc-param-value" id="ncf-genre-label-' + stepDef.id + '">' + escHtml(tF('None')) + '</span>' +
      '<button type="button" class="nsc-history-btn nsc-options-trigger" id="ncf-genre-picker-btn-' + stepDef.id + '" aria-label="' + escHtml(tF('Choose genre')) + '"></button>' +
      '</p>';
    el.appendChild(genreBlock);
    var genreLabelEl  = genreBlock.querySelector('#ncf-genre-label-' + stepDef.id);
    var genrePickerBtn = genreBlock.querySelector('#ncf-genre-picker-btn-' + stepDef.id);
    genrePickerBtn.innerHTML =
      '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M9 2l1.8 3.7L15 6.3l-3 3 .7 4.2L9 11.6 5.3 13.5 6 9.3l-3-3 4.2-.6z"/>' +
      '</svg>';

    function updateGenreLabel() {
      if (!genreLabelEl) return;
      if (!selectedGenre) { genreLabelEl.textContent = tF('None'); return; }
      var found = (_genresCache || []).find(function (g) { return g.id === selectedGenre; });
      genreLabelEl.textContent = found ? (found.label || found.id) : selectedGenre;
    }

    function renderGenreCards(genreCardsEl, genres) {
      genreCardsEl.innerHTML = '';

      // "None" card — clears the genre and leaves level/flair untouched
      var noneCard = document.createElement('button');
      noneCard.type = 'button';
      noneCard.className = 'nse-genre-card' + (!selectedGenre ? ' is-active' : '');
      noneCard.dataset.genre = '';
      noneCard.innerHTML = '<span class="nse-genre-icon">—</span><span class="nse-genre-label">' + escHtml(tF('None')) + '</span>';
      noneCard.addEventListener('click', function () {
        selectedGenre = '';
        updateGenreLabel();
        closeOptionsPanel();
      });
      genreCardsEl.appendChild(noneCard);

      genres.forEach(function (g) {
        var card = document.createElement('button');
        card.type = 'button';
        card.className = 'nse-genre-card' + (selectedGenre === g.id ? ' is-active' : '');
        card.dataset.genre = g.id;
        card.title = g.context_hint || '';
        card.innerHTML = '<span class="nse-genre-icon">' + escHtml(g.icon || '') + '</span>' +
          '<span class="nse-genre-label">' + escHtml(g.label || g.id) + '</span>';
        card.addEventListener('click', function () {
          selectedGenre = g.id;
          updateGenreLabel();

          // Apply the genre's suggested flair/level — still editable by the
          // user after, via the options modal (level/flair now live there,
          // not inline — just refresh it in case it's open).
          if (g.flair != null) flairValue = Number(g.flair);
          if (g.level) selectedLevel = g.level;
          if (typeof syncLLMOptionsModalUI === 'function') syncLLMOptionsModalUI();
          closeOptionsPanel();
        });
        genreCardsEl.appendChild(card);
      });
    }

    genrePickerBtn.addEventListener('click', function () {
      openOptionsPanel(tF('Genre'), function (panelBody) {
        var cardsEl = document.createElement('div');
        cardsEl.className = 'nse-genre-cards';
        cardsEl.setAttribute('role', 'group');
        panelBody.appendChild(cardsEl);
        if (_genresCache) {
          renderGenreCards(cardsEl, _genresCache);
        } else {
          cardsEl.innerHTML = '<span class="nse-genre-loading">' + escHtml(tF('Loading genres…')) + '</span>';
          fetch('/api/flows/genres')
            .then(function (r) { return r.json(); })
            .then(function (data) {
              _genresCache = Array.isArray(data.genres) ? data.genres : [];
              renderGenreCards(cardsEl, _genresCache);
            })
            .catch(function () {
              cardsEl.innerHTML = '<span class="nse-genre-loading">' + escHtml(tF('Could not load genres.')) + '</span>';
            });
        }
      });
    });
  }

  // Enhance level / Flair defaults — the controls themselves now live in the
  // options modal (opened via the icon button added above), not inline.
  if (params.level) {
    selectedLevel = params.level.default || 'scene';
  }
  if (params.flair) {
    flairValue = params.flair.default != null ? Number(params.flair.default) : 30;
  }

  // user_choice params: numeric inputs or select dropdowns
  if (!stepDef._paramValues) stepDef._paramValues = {};
  Object.keys(params).forEach(function (paramKey) {
    if (paramKey === 'level' || paramKey === 'flair' || paramKey === 'genre') return;
    var paramDef = params[paramKey];
    if (!paramDef || paramDef.type !== 'user_choice') return;

    // Only show a heading when someone actually wrote one. Falling back to the
    // param key printed the raw identifier above the control — the "Generate
    // variations" step carried a heading reading "N", which names the variable
    // in the flow JSON and nothing the user has any use for. Every other
    // user_choice param in every flow defines a label; `n` is the one that
    // never did.
    var paramTitle = paramDef.label
      ? paramDef.label.charAt(0).toUpperCase() + paramDef.label.slice(1)
      : '';
    var paramTitleHtml = paramTitle
      ? '<p class="nsc-param-title">' + escHtml(paramTitle) + '</p>'
      : '';
    var paramBlock = document.createElement('div');
    paramBlock.className = 'nse-control-block';

    if (Array.isArray(paramDef.options)) {
      // Enum select dropdown
      var defStr = paramDef.default != null ? String(paramDef.default) : (paramDef.options[0] || '');
      stepDef._paramValues[paramKey] = defStr;
      var wrapper = document.createElement('div');
      wrapper.className = 'nsc-select-wrapper';
      var sel = document.createElement('select');
      sel.className = 'nsc-select';
      if (paramDef.required === false) {
        var anyOpt = document.createElement('option');
        anyOpt.value = '';
        anyOpt.textContent = tF('— any —');
        sel.appendChild(anyOpt);
      }
      paramDef.options.forEach(function (opt) {
        var o = document.createElement('option');
        o.value = opt;
        o.textContent = opt.charAt(0).toUpperCase() + opt.slice(1).replace(/_/g, ' ');
        if (opt === defStr) o.selected = true;
        sel.appendChild(o);
      });
      var chev = document.createElement('span');
      chev.className = 'nsc-select-chevron';
      chev.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>';
      wrapper.appendChild(sel);
      wrapper.appendChild(chev);
      paramBlock.innerHTML = paramTitleHtml;
      paramBlock.appendChild(wrapper);
      sel.addEventListener('change', function () {
        stepDef._paramValues[paramKey] = sel.value;
        // set_aspect_ratio: { "value": "label" } → auto-update aspect slider
        if (paramDef.set_aspect_ratio && paramDef.set_aspect_ratio[sel.value]) {
          var _arLabel = paramDef.set_aspect_ratio[sel.value];
          var _arIdx = ASPECT_PRESETS.findIndex(function (p) { return p.label === _arLabel; });
          if (_arIdx >= 0 && typeof _ncfSetAspectFn === 'function') {
            _ncfSetAspectFn(_arIdx);
          }
        }
      });
    } else {
      // Numeric stepper
      var defVal = paramDef.default != null ? Number(paramDef.default) : 1;
      var minVal  = paramDef.min != null ? Number(paramDef.min) : 1;
      var maxVal  = paramDef.max != null ? Number(paramDef.max) : 100;
      stepDef._paramValues[paramKey] = defVal;

      paramBlock.innerHTML = paramTitleHtml;

      var stepperOuter = document.createElement('div');
      stepperOuter.style.cssText = 'max-width:140px;margin:0 auto;';

      var stepper = document.createElement('div');
      stepper.className = 'numeric-stepper';

      var minusBtn = document.createElement('button');
      minusBtn.type = 'button';
      minusBtn.className = 'btn numeric-stepper-btn numeric-stepper-btn-left';
      minusBtn.setAttribute('aria-label', tF('Decrease'));
      minusBtn.innerHTML = '<span aria-hidden="true">&#9664;</span>';

      var numInput = document.createElement('input');
      numInput.type = 'number';
      // With the heading gone there is no visible text tying this stepper to
      // anything, so name it for screen readers off the step it belongs to.
      numInput.setAttribute('aria-label', paramTitle || (stepDef.label || 'Amount'));
      numInput.min  = minVal;
      numInput.max  = maxVal;
      numInput.value = defVal;

      var plusBtn = document.createElement('button');
      plusBtn.type = 'button';
      plusBtn.className = 'btn numeric-stepper-btn numeric-stepper-btn-right';
      plusBtn.setAttribute('aria-label', tF('Increase'));
      plusBtn.innerHTML = '<span aria-hidden="true">&#9654;</span>';

      stepper.appendChild(minusBtn);
      stepper.appendChild(numInput);
      stepper.appendChild(plusBtn);
      stepperOuter.appendChild(stepper);
      paramBlock.appendChild(stepperOuter);

      minusBtn.addEventListener('click', function () {
        var v = parseInt(numInput.value, 10) || defVal;
        if (v > minVal) { numInput.value = v - 1; stepDef._paramValues[paramKey] = v - 1; }
      });
      plusBtn.addEventListener('click', function () {
        var v = parseInt(numInput.value, 10) || defVal;
        if (v < maxVal) { numInput.value = v + 1; stepDef._paramValues[paramKey] = v + 1; }
      });
      numInput.addEventListener('input', function () {
        stepDef._paramValues[paramKey] = parseInt(numInput.value, 10) || defVal;
      });
    }

    el.appendChild(paramBlock);
  });

  // Write scene button row — model choice now lives in the options modal
  // (opened via the icon next to the step title) instead of its own icon here.
  var writeRow = document.createElement('div');
  writeRow.style.cssText = 'display:flex;align-items:stretch;gap:8px;margin-top:14px;';

  var writeBtn = document.createElement('button');
  writeBtn.className = 'nss-generate-scenes-btn';
  writeBtn.id = 'ncf-write-btn-' + stepDef.id;
  writeBtn.style.flex = '1';
  writeBtn.style.marginTop = '0';
  writeBtn.type = 'button';
  var writeLbl = document.createElement('span');
  writeLbl.textContent = stepDef.label || 'Write scene';
  writeBtn.insertAdjacentHTML('afterbegin',
    '<svg class="nss-btn-icon" viewBox="0 0 24 24" aria-hidden="true" style="width:16px;height:16px"><path d="M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8L12 15l-4.9 3.2 1.9-5.8L4 8.8h6.1z"/></svg>');
  writeBtn.appendChild(writeLbl);
  writeRow.appendChild(writeBtn);

  el.appendChild(writeRow);

  // Status hint — kept detached from the DOM (not appended) to cut visual
  // clutter under the button; runLLM still writes to it internally (used by
  // multi-call loops to track progress), and errors now go to a toast instead.
  var llmStatus = mkHint('');
  llmStatus.id = 'ncf-llm-status-' + stepDef.id;

  // If output_to is defined, the output goes directly into the target step's textarea.
  // We skip rendering a duplicate textarea here; the ref is resolved after all steps render.
  var outputTa = null;
  if (!stepDef.output_to && stepDef.output_mode !== 'prompt_cards') {
    outputTa = document.createElement('textarea');
    outputTa.className = 'nsc-textarea';
    outputTa.id = 'ncf-llm-output-' + stepDef.id;
    outputTa.rows = 4;
    outputTa.placeholder = tF('AI-generated scene will appear here…');
    el.appendChild(outputTa);
    outputTa.addEventListener('input', function () {
      setVal(stepDef.id, 'transformed_text', outputTa.value.trim());
      syncPrefillTargets(stepDef.id, 'transformed_text', outputTa.value);
    });
  }

  writeBtn.addEventListener('click', function () {
    if (isWritingScene) return;
    // Read outputTa lazily — may have been resolved by resolveOutputTo() after render
    runLLM(stepDef, writeBtn, writeLbl, llmStatus, stepDef._llmRefs.outputTa);
  });

  // Store refs (outputTa resolved later if output_to is set)
  stepDef._llmRefs = { writeBtn: writeBtn, writeLbl: writeLbl, llmStatus: llmStatus, outputTa: outputTa };
}

// Auto-fill steps that have prefill_from pointing to stepId.field
function syncPrefillTargets(fromStepId, fromField, value) {
  allSteps.forEach(function (s) {
    if (!s.prefill_from) return;
    var parts = String(s.prefill_from).split('||');
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].trim() === 'steps.' + fromStepId + '.output.' + fromField) {
        var target = document.getElementById('ncf-input-' + s.id);
        if (target) {
          target.value = value;
          // If the target was disabled while waiting for prefill, unlock it now
          if (target.disabled) {
            target.disabled = false;
            target.classList.remove('is-prefill-pending');
            target.placeholder = '';
          }
          setVal(s.id, 'prompt_text', String(value || '').trim());
        }
        break;
      }
    }
  });
}

// ── image_picker ───────────────────────────────────────────────────────────
