'use strict';
// Step: json_input → renderJsonInput

function renderJsonInput(stepDef, el) {
  // If a static template is provided in the flow JSON, use it as the starting point
  var staticTemplate = stepDef.template || {};
  if (Object.keys(staticTemplate).length && !stepDef._jsonCurrentTemplate) {
    stepDef._jsonCurrentTemplate = staticTemplate;
    setVal(stepDef.id, 'json_data', staticTemplate);
    setVal(stepDef.id, '_prompt', _buildPromptFromJson(staticTemplate));
    var _st = _splitJsonNegative(staticTemplate);
    _applyJsonNegative(_st.negative);
    setVal(stepDef.id, '_json_text', JSON.stringify(_st.clean));
    Object.keys(staticTemplate).forEach(function (k) {
      if (getVal(stepDef.id, k) === undefined) setVal(stepDef.id, k, staticTemplate[k]);
    });
  }

  // ── Header buttons: History + Edit (JSON key/value editor) — same
  // placement/pattern as prompt_input's History icon, both opening the
  // shared lateral panel instead of a centered modal. ──────────────────────
  var stepLabel = el.querySelector('.nsc-step-label') ||
                  (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));
  if (stepLabel) {
    var chevron = stepLabel.querySelector('.nsc-step-chevron');

    var histBtn = document.createElement('button');
    histBtn.type = 'button';
    histBtn.className = 'nsc-history-btn nsc-options-trigger';
    histBtn.setAttribute('aria-label', tF('JSON history'));
    histBtn.innerHTML =
      '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<circle cx="8" cy="8" r="6"/>' +
        '<path d="M8 5v3.5l2 1.5"/>' +
      '</svg>';
    histBtn.addEventListener('click', function () {
      openHistoryModal(stepDef.id, function (text) {
        ta.value = text;
        tryParse(text);
      });
    });

    var editHeaderBtn = document.createElement('button');
    editHeaderBtn.type = 'button';
    editHeaderBtn.className = 'nsc-history-btn nsc-options-trigger';
    editHeaderBtn.setAttribute('aria-label', tF('Edit JSON variables'));
    editHeaderBtn.innerHTML =
      '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M11.5 2.5l2 2-8 8H3.5v-2l8-8z"/>' +
      '</svg>';
    editHeaderBtn.addEventListener('click', function () { openJsonModal(stepDef); });

    if (chevron) {
      stepLabel.insertBefore(histBtn, chevron);
      stepLabel.insertBefore(editHeaderBtn, chevron);
    } else {
      stepLabel.appendChild(histBtn);
      stepLabel.appendChild(editHeaderBtn);
    }
  }

  // ── Text idea → Convert → JSON ───────────────────────────────────────────
  // These used to be one box: "Convert with AI" read the JSON textarea and
  // wrote its result back into it, so the same field meant both "your rough
  // idea" and "the structured prompt". Splitting them makes the direction of
  // travel obvious — you write above, the JSON appears below.
  // Inserted *before* the step's own label, so "JSON PROMPT" ends up titling
  // the JSON box it belongs to rather than the whole step — otherwise the
  // section reads "JSON PROMPT" and then immediately offers a plain-text field.
  var anchor = (stepLabel && stepLabel.parentElement === el) ? stepLabel : null;
  var place = function (node) {
    if (anchor) el.insertBefore(node, anchor); else el.appendChild(node);
  };

  var ideaLabel = document.createElement('p');
  ideaLabel.className = 'nsc-param-title ncf-json-idea-label';
  ideaLabel.textContent = tF('Text idea');
  place(ideaLabel);

  var ideaTa = document.createElement('textarea');
  ideaTa.className = 'nsc-textarea ncf-json-idea-ta';
  ideaTa.id = 'ncf-json-idea-' + stepDef.id;
  ideaTa.rows = 2;
  ideaTa.placeholder = tF('A rough line is enough — the AI turns it into the JSON below.');
  place(ideaTa);

  var convertBtn = document.createElement('button');
  convertBtn.type = 'button';
  convertBtn.className = 'ncf-json-convert-btn';
  convertBtn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8L12 15l-4.9 3.2 1.9-5.8L4 8.8h6.1z"/></svg>' +
    ' Convert with AI';
  convertBtn.disabled = true;
  place(convertBtn);

  ideaTa.addEventListener('input', function () {
    convertBtn.disabled = !ideaTa.value.trim();
  });

  // ── The JSON itself ──────────────────────────────────────────────────────
  var ta = document.createElement('textarea');
  ta.className = 'nsc-textarea ncf-json-paste-ta';
  ta.id = 'ncf-json-ta-' + stepDef.id;
  ta.rows = 8;
  ta.placeholder = '{ "high_level_description": "...", "style_description": { … } }';
  ta.spellcheck = false;
  if (Object.keys(staticTemplate).length) {
    ta.value = JSON.stringify(staticTemplate, null, 2);
  }
  el.appendChild(ta);

  var errMsg = document.createElement('span');
  errMsg.className = 'ncf-json-parse-err';
  errMsg.hidden = true;
  el.appendChild(errMsg);

  // Loading a .json is a rare, one-off action — it belongs with the other
  // header icons, not as a full-width button competing with Convert.
  var fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = '.json,application/json';
  fileInput.style.display = 'none';
  el.appendChild(fileInput);

  if (stepLabel) {
    var fileIconBtn = document.createElement('button');
    fileIconBtn.type = 'button';
    fileIconBtn.className = 'nsc-history-btn';
    fileIconBtn.setAttribute('aria-label', tF('Load a .json file'));
    fileIconBtn.title = tF('Load a .json file');
    fileIconBtn.innerHTML =
      '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" ' +
        'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M2 4h7l2 2h3v8H2z"/>' +
      '</svg>';
    fileIconBtn.addEventListener('click', function () { fileInput.click(); });
    var chev = stepLabel.querySelector('.nsc-step-chevron');
    if (chev) stepLabel.insertBefore(fileIconBtn, chev);
    else stepLabel.appendChild(fileIconBtn);
  }

  // The key/value read-out that used to sit under the toolbar is gone: it
  // restated what the JSON above already says, and the pencil icon opens a
  // panel that edits the same keys properly.

  // ── Parse logic ───────────────────────────────────────────────────────────
  function applyParsed(obj) {
    // Remove stale keys from the previous template that no longer exist
    var prev = stepDef._jsonCurrentTemplate || {};
    Object.keys(prev).forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(obj, k) && stepValues[stepDef.id]) {
        delete stepValues[stepDef.id][k];
      }
    });
    stepDef._jsonCurrentTemplate = obj;
    // The negative never travels inside the positive block — see
    // _splitJsonNegative in flow-json-modal.js.
    var _split = _splitJsonNegative(obj);
    _applyJsonNegative(_split.negative);
    setVal(stepDef.id, 'json_data', obj);
    setVal(stepDef.id, '_prompt', _buildPromptFromJson(obj));
    var jsonText = JSON.stringify(_split.clean);
    setVal(stepDef.id, '_json_text', jsonText);
    Object.keys(obj).forEach(function (k) { setVal(stepDef.id, k, obj[k]); });
    _updateJsonPreview(stepDef);
    errMsg.hidden = true;
    pushPromptHistory(stepDef.id, jsonText);
  }

  function tryParse(text) {
    var t = (text || '').trim();
    if (!t) return;
    try {
      var obj = JSON.parse(t);
      if (typeof obj !== 'object' || Array.isArray(obj) || !obj) throw new Error(tF('must be a JSON object {}'));
      applyParsed(obj);
    } catch (e) {
      errMsg.textContent = e.message;
      errMsg.hidden = false;
    }
  }

  var _parseTimer = null;
  ta.addEventListener('input', function () {
    clearTimeout(_parseTimer);
    _parseTimer = setTimeout(function () { tryParse(ta.value); }, 400);
  });

  fileInput.addEventListener('change', function () {
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function (ev) {
      ta.value = ev.target.result;
      tryParse(ev.target.result);
    };
    reader.readAsText(file);
    fileInput.value = '';
  });

  var _convertRunning = false;
  convertBtn.addEventListener('click', async function () {
    var text = ideaTa.value.trim();
    if (!text || _convertRunning) return;
    _convertRunning = true;
    convertBtn.disabled = true;
    convertBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true" class="ncf-json-spin"><path d="M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8L12 15l-4.9 3.2 1.9-5.8L4 8.8h6.1z"/></svg>' +
      ' Converting…';
    errMsg.hidden = true;
    try {
      var res = await fetch('/api/models/chat/convert-to-json', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text, enhance: false, thinking: false }),
      });
      var data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || 'Conversion failed');
      var parsed = data.json;
      if (typeof parsed === 'string') parsed = JSON.parse(parsed);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(tF('LM Studio returned an invalid JSON object'));
      ta.value = JSON.stringify(parsed, null, 2);
      applyParsed(parsed);
    } catch (e) {
      errMsg.textContent = e.message;
      errMsg.hidden = false;
    } finally {
      _convertRunning = false;
      convertBtn.disabled = !ideaTa.value.trim();
      convertBtn.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8L12 15l-4.9 3.2 1.9-5.8L4 8.8h6.1z"/></svg>' +
        ' Convert with AI';
    }
  });
}

// ── civitai_paste ──────────────────────────────────────────────────────────
