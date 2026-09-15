'use strict';
// Step: bulk_vision → renderBulkVision
//
// Takes the N images from a preceding multi-image `image_picker` step
// (stepDef.images_from), a user-typed example prompt ("Reference prompt" —
// a few-shot style template, not a short idea), and a Faithful/Creative
// toggle. There used to be a "Prefix keywords" field here whose whole
// purpose was LoRA trigger words the vision model can't guess; since those
// are injected automatically at the single positive-prompt write point it
// had no job left, so it is gone.
// "Process" runs the vision model once per image (sequential — a
// local LLM doesn't parallelize well anyway) and builds an editable list of
// {image, prompt} rows. "Generate All" pushes every non-empty row straight
// onto the app's existing generation queue (_genQueue/_processQueue,
// flow-generation.js) against whichever engine the sibling "Choose engine"
// (workflow_picker) step selected — no new generation plumbing needed, this
// reuses the exact same queue/results-grid/progress-ring machinery every
// other Create flow uses.

function renderBulkVision(stepDef, el) {
  var imagesStepId = stepDef.images_from || 'images';
  var storeId = stepDef.id;

  var rows = []; // [{ image, prompt }]
  // True while the vision pass is running. Without it "Generate All" lights up
  // the moment the FIRST prompt is written — _renderRows() runs after every
  // image — so pressing it mid-batch queues only the rows written so far and
  // silently drops the rest. The faster the vision model, the smaller the
  // window; on a slow one it is wide open for most of the batch.
  var isProcessing = false;

  // ── Reference prompt ─────────────────────────────────────────────────────
  var REFERENCE_HISTORY_KEY = storeId + '.reference_prompt';
  var refBlock = document.createElement('div');
  refBlock.className = 'nsc-param-block';
  var refTitle = document.createElement('p');
  refTitle.className = 'nsc-param-title';
  refTitle.textContent = 'Reference prompt';
  var refHistBtn = document.createElement('button');
  refHistBtn.type = 'button';
  refHistBtn.className = 'nsc-history-btn nsc-options-trigger';
  refHistBtn.setAttribute('aria-label', 'Reference prompt history');
  refHistBtn.innerHTML =
    '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
      '<circle cx="8" cy="8" r="6"/>' +
      '<path d="M8 5v3.5l2 1.5"/>' +
    '</svg>';
  refHistBtn.addEventListener('click', function () {
    openHistoryModal(REFERENCE_HISTORY_KEY, function (text) {
      refTa.value = text;
      setVal(storeId, 'reference_prompt', text.trim());
    });
  });
  refTitle.appendChild(refHistBtn);
  refBlock.appendChild(refTitle);
  var refTa = document.createElement('textarea');
  refTa.className = 'nsc-textarea';
  refTa.rows = 4;
  refTa.placeholder = stepDef.reference_placeholder ||
    'Paste one example prompt written in the style you want (the model copies its structure and vocabulary, not its content)…';
  refTa.value = getVal(storeId, 'reference_prompt') || '';
  refTa.addEventListener('input', function () { setVal(storeId, 'reference_prompt', refTa.value); });
  refBlock.appendChild(refTa);
  el.appendChild(refBlock);

  // ── Faithful / Creative toggle ────────────────────────────────────────────
  var modeBlock = document.createElement('div');
  modeBlock.className = 'nsc-param-block';
  modeBlock.style.marginTop = '0.75rem';
  modeBlock.innerHTML = '<p class="nsc-param-title">Mode</p>';
  var modeRow = document.createElement('div');
  modeRow.style.cssText = 'display:flex;gap:0.5rem;';
  var mode = getVal(storeId, 'mode') || 'faithful';
  var faithfulBtn = document.createElement('button');
  faithfulBtn.type = 'button';
  faithfulBtn.className = 'nsc-res-btn' + (mode === 'faithful' ? ' is-active' : '');
  faithfulBtn.style.flex = '1';
  faithfulBtn.textContent = 'Faithful';
  faithfulBtn.title = 'Describe literally what is in each image';
  var creativeBtn = document.createElement('button');
  creativeBtn.type = 'button';
  creativeBtn.className = 'nsc-res-btn' + (mode === 'creative' ? ' is-active' : '');
  creativeBtn.style.flex = '1';
  creativeBtn.textContent = 'Creative';
  creativeBtn.title = 'Use each image as loose inspiration, embellish freely';
  function _setMode(m) {
    mode = m;
    setVal(storeId, 'mode', mode);
    faithfulBtn.classList.toggle('is-active', mode === 'faithful');
    creativeBtn.classList.toggle('is-active', mode === 'creative');
  }
  faithfulBtn.addEventListener('click', function () { _setMode('faithful'); });
  creativeBtn.addEventListener('click', function () { _setMode('creative'); });
  modeRow.appendChild(faithfulBtn);
  modeRow.appendChild(creativeBtn);
  modeBlock.appendChild(modeRow);
  el.appendChild(modeBlock);

  // ── Vision model + Process ────────────────────────────────────────────────
  var processRow = document.createElement('div');
  processRow.style.cssText = 'display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-top:1rem;';
  var processBtn = document.createElement('button');
  processBtn.type = 'button';
  processBtn.className = 'nss-generate-scenes-btn';
  processBtn.style.cssText = 'flex:1;margin-top:0;';
  var processBtnLbl = document.createElement('span');
  processBtnLbl.textContent = 'Process';
  processBtn.appendChild(processBtnLbl);
  processRow.appendChild(processBtn);
  if (typeof makeVisionModelBtn === 'function') {
    processRow.appendChild(makeVisionModelBtn());
  }
  el.appendChild(processRow);

  var progressEl = document.createElement('p');
  progressEl.className = 'nsc-step-hint';
  progressEl.style.marginTop = '0.4rem';
  el.appendChild(progressEl);

  // ── Results list (one row per image, filled in as Process completes) ─────
  var listEl = document.createElement('div');
  listEl.className = 'nsc-param-block';
  listEl.style.marginTop = '0.75rem';
  el.appendChild(listEl);

  function _renderRows() {
    listEl.innerHTML = '';
    rows.forEach(function (row, idx) {
      var rowEl = document.createElement('div');
      rowEl.style.cssText = 'display:flex;gap:0.6rem;margin-top:0.6rem;align-items:flex-start;';
      var thumb = document.createElement('img');
      thumb.src = row.image;
      thumb.style.cssText = 'width:64px;height:64px;object-fit:cover;border-radius:8px;flex-shrink:0;';
      var ta = document.createElement('textarea');
      ta.className = 'nsc-textarea';
      ta.rows = 3;
      ta.style.flex = '1';
      ta.value = row.prompt;
      ta.addEventListener('input', function () { rows[idx].prompt = ta.value; });
      rowEl.appendChild(thumb);
      rowEl.appendChild(ta);
      listEl.appendChild(rowEl);
    });
    generateAllBtn.disabled = isProcessing || !rows.some(function (r) { return r.prompt.trim(); });
  }

  var generateAllBtn = document.createElement('button');
  generateAllBtn.type = 'button';
  generateAllBtn.id = 'ncf-bulk-generate-all-' + stepDef.id;
  generateAllBtn.className = 'nss-generate-scenes-btn';
  generateAllBtn.style.marginTop = '0.75rem';
  generateAllBtn.textContent = 'Generate All';
  generateAllBtn.disabled = true;
  el.appendChild(generateAllBtn);

  // A read that gives back style words and no image is a failure, not a
  // prompt. Vision models routinely open with the example verbatim and then
  // describe the image — harmless — but a weak one emits only the style and
  // stops. That row is non-empty, so nothing downstream questions it: Generate
  // All queues words with no subject, and the flow renders an image unrelated
  // to its reference while looking like it worked.
  //
  // Matching the example as a string is not enough, which measuring several
  // models made obvious. Both of these came back with the rooftop photo in
  // front of them, and both are the same failure:
  //
  //   qwen3.5-2b      "warm amber light, cool teal shadows, cinematic editorial photography"
  //   gemma-4-e4b     "golden hour glow, deep azure shadows, cinematic editorial photography"
  //
  // The second is a paraphrase, so no string comparison catches it. Length
  // does: the system prompt demands 40-60 words covering subject, pose,
  // clothing, setting, lighting and mood, and none of that fits in twenty.
  var _MIN_DESCRIPTION_WORDS = 20;

  function _normalized(text) {
    return String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function _isNotADescription(desc, reference) {
    var d = _normalized(desc);
    if (!d) return true;
    if (d.split(' ').length < _MIN_DESCRIPTION_WORDS) return true;
    var r = _normalized(reference);
    if (!r) return false;
    if (d === r) return true;
    return d.indexOf(r) === 0 && _normalized(d.slice(r.length)).length < 24;
  }

  async function _describeOnce(imageDataUrl, systemPrompt) {
    var res = await fetch('/api/models/chat/describe-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        imageDataUrl: imageDataUrl,
        describeType: 'prompt',
        describeScope: 'full',
        describeFormat: 'paragraph',
        forceRefresh: true,
        systemPrompt: systemPrompt,
      }),
    });
    var data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Describe failed');
    return String(data.description || '').trim();
  }

  processBtn.addEventListener('click', async function () {
    var images = getVal(imagesStepId, 'image_data_urls') || [];
    var single = getVal(imagesStepId, 'image_data_url');
    if (!images.length && single) images = [single];
    if (!images.length) {
      if (typeof showErrorToast === 'function') showErrorToast('Add at least one reference image first.');
      return;
    }
    var reference = refTa.value.trim();
    if (!reference) {
      if (typeof showErrorToast === 'function') showErrorToast('Paste a reference prompt first.');
      return;
    }
    pushPromptHistory(REFERENCE_HISTORY_KEY, reference);
    var systemPromptTpl = mode === 'creative'
      ? (stepDef.system_prompt_creative || '')
      : (stepDef.system_prompt_faithful || '');
    var systemPrompt = systemPromptTpl.replace(/\{\{reference\}\}/g, reference);

    rows = [];
    isProcessing = true;
    _renderRows();
    processBtn.disabled = true;
    processBtn.classList.add('is-composing');

    for (var i = 0; i < images.length; i++) {
      progressEl.textContent = 'Processing ' + (i + 1) + '/' + images.length + '…';
      processBtnLbl.textContent = 'Processing ' + (i + 1) + '/' + images.length;
      try {
        var desc = await _describeOnce(images[i], systemPrompt);
        if (_isNotADescription(desc, reference)) {
          // The same image and the same example usually read fine on a second
          // pass — the failure is a sampling accident, not a bad input — so
          // spend one retry before handing the user an empty row.
          progressEl.textContent = 'Retrying ' + (i + 1) + '/' + images.length + '…';
          processBtnLbl.textContent = 'Retrying ' + (i + 1) + '/' + images.length;
          desc = await _describeOnce(images[i], systemPrompt);
          if (_isNotADescription(desc, reference)) desc = '';
        }
        if (!desc && typeof showErrorToast === 'function') {
          showErrorToast('Image ' + (i + 1) + ': the model gave back style words instead of '
            + 'describing the image. Press Process again, or write this one yourself.');
        }
        rows.push({ image: images[i], prompt: desc });
      } catch (err) {
        rows.push({ image: images[i], prompt: '' });
        if (typeof showErrorToast === 'function') showErrorToast('Image ' + (i + 1) + ' failed: ' + err.message);
      }
      _renderRows();
    }

    isProcessing = false;
    processBtn.disabled = false;
    processBtn.classList.remove('is-composing');
    processBtnLbl.textContent = 'Process';
    _renderRows();

    // Say what just happened and what is still missing. This flow's whole
    // shape is two actions with different names, far apart, and nothing used
    // to mark the seam: Process filled the prompts in and stopped, and a user
    // watching the list populate has every reason to think the work is done.
    // Naming the next button is the cheapest possible fix for the flow's
    // biggest confusion.
    var ready = rows.filter(function (r) { return r.prompt.trim(); }).length;
    if (!ready) {
      progressEl.textContent = 'No prompts written — check the vision model and try again.';
    } else if (ready < rows.length) {
      progressEl.textContent = ready + ' of ' + rows.length + ' prompts ready — '
        + 'press "Generate All" to render them. Blank rows are skipped; write them yourself to include them.';
    } else {
      progressEl.textContent = ready + (ready === 1 ? ' prompt' : ' prompts')
        + ' ready — press "Generate All" below to render them.';
    }
  });

  generateAllBtn.addEventListener('click', function () {
    var isCustom = (getMode() === 'advanced');
    var workflowId = (isCustom && getGlobalWorkflows().length > 0) ? getGlobalWorkflows()[0] : selectedImportId;
    if (!workflowId) {
      if (typeof showErrorToast === 'function') showErrorToast('Choose an engine first.');
      return;
    }
    var dims = getDims();
    var queued = 0;
    rows.forEach(function (row) {
      var prompt = row.prompt.trim();
      if (!prompt) return;
      var seedVal = Math.floor(Math.random() * 0x7FFFFFFF);
      var slotNum = generatedCount + 1 + _genQueue.length;
      var card = _addQueuedCard(slotNum, prompt);
      _genQueue.push({ card: card, positivePrompt: prompt, seedVal: seedVal, workflowId: workflowId, dims: dims, stepDef: stepDef });
      queued++;
    });
    if (!queued) return;
    if (generateStatus) generateStatus.textContent = _genQueue.length + ' queued';
    _processQueue();
  });

  _renderRows();
}
