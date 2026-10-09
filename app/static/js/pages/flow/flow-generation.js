'use strict';
// Generation: _fmtEta, _startEtaCountdown, updateCardProgress, _enqueueGeneration, addGeneratingCard, renderPromptCards, buildPromptCard

function _fmtEta(secs) {
  if (secs <= 0) return '';
  if (secs < 60) return secs + 's';
  return Math.floor(secs / 60) + ':' + String(Math.round(secs % 60)).padStart(2, '0');
}

function _startEtaCountdown(etaEl, seconds) {
  var remaining = Math.round(seconds);
  etaEl.textContent = _fmtEta(remaining);
  return setInterval(function () {
    remaining = Math.max(0, remaining - 1);
    etaEl.textContent = _fmtEta(remaining);
    if (remaining === 0) etaEl.textContent = '';
  }, 1000);
}

function updateCardProgress(card, value, max) {
  if (!card || !max || max <= 0) return;
  var pct    = Math.min(100, Math.round((value / max) * 100));
  var offset = RING_CIRC * (1 - pct / 100);
  var imgWrap = card.querySelector('.nss-card-img-wrap');
  if (!imgWrap) return;
  var ring    = imgWrap.querySelector('.nsc-ring');
  var fill    = imgWrap.querySelector('.nsc-ring-fill');
  var pctEl   = imgWrap.querySelector('.nsc-ring-pct');
  var stepsEl = imgWrap.querySelector('.nsc-ring-steps');
  var etaEl   = imgWrap.querySelector('.nsc-ring-eta');
  if (ring)    ring.classList.remove('nsc-ring--indeterminate');
  if (fill)    fill.style.strokeDashoffset = offset;
  if (pctEl)   pctEl.textContent  = pct + '%';
  if (stepsEl) stepsEl.textContent = value + ' / ' + max;
  if (etaEl && card._genStartTime && pct > 0 && pct < 100) {
    var elapsed = (Date.now() - card._genStartTime) / 1000;
    var remaining = Math.round(elapsed * (100 - pct) / pct);
    if (card._etaInterval) clearInterval(card._etaInterval);
    card._etaInterval = _startEtaCountdown(etaEl, remaining);
  } else if (pct >= 100 && etaEl) {
    if (card._etaInterval) { clearInterval(card._etaInterval); card._etaInterval = null; }
    etaEl.textContent = '';
  }
}

async function waitForImage(comfyUrl, clientId, promptId, card, readyLabel) {
  return new Promise(function (resolve, rejectJob) {
    // A job ComfyUI failed must not leave its card spinning: the direct
    // (non-queued) runners only report the error in the status line, and the
    // next job overwrites that — the card stayed "generating" forever and the
    // failure was invisible.
    function reject(err) {
      _markCardError(card, err && err.message);
      rejectJob(err);
    }
    if (activeES) { try { activeES.close(); } catch (_) {} activeES = null; }
    var params = new URLSearchParams({ comfyApiUrl: comfyUrl, clientId: clientId });
    activeES = new EventSource('/api/images/comfy/progress-stream?' + params);
    var imgUrl = null;
    // ComfyUI accepting the prompt only means it's queued — another
    // client's job already running on a shared server can sit ahead of it.
    // Show "queued" until the first execution-scoped event over THIS
    // client_id's own stream confirms our prompt actually started (see
    // issue #73: this used to flip to "Generating…" the moment /prompt
    // returned a prompt_id, well before real execution began).
    var executionStarted = false;
    if (generateStatus) _setBusyStatus(generateStatus, tF('Queued — waiting for ComfyUI…'));

    // See waitForImageLocal's comment for why this is a heuristic (no real
    // download progress is exposed by ComfyUI for custom-node model fetches):
    // a node stuck "executing" for a while with no progress/executed
    // following is very likely blocked downloading a model, not computing.
    var noteTimer = null;
    var noteShown = false;
    var statusBeforeNote = '';
    var DOWNLOAD_STALL_MS = 4000;
    function clearNote() {
      if (noteTimer) { clearTimeout(noteTimer); noteTimer = null; }
      if (noteShown) {
        noteShown = false;
        // Flash a confirmation instead of silently snapping back to
        // "Generating…" — the user was staring at "Model initializing…" for
        // a while, so acknowledging it finished reads less like the status
        // just got stuck/reset.
        if (generateStatus) {
          _setBusyStatus(generateStatus, tF('Model initialization complete!'));
          setTimeout(function () {
            if (generateStatus) _setBusyStatus(generateStatus, statusBeforeNote || tF('Generating…'));
          }, 1200);
        }
      }
    }
    function armDownloadNote() {
      if (noteTimer) clearTimeout(noteTimer);
      noteTimer = setTimeout(function () {
        noteShown = true;
        if (generateStatus) {
          statusBeforeNote = (generateStatus.querySelector('span') || {}).textContent || 'Generating…';
          // Most stalls here are the model being loaded into VRAM (weights
          // decompress/move on first use each session), not an actual
          // internet download — "Downloading model" was misleading most of
          // the time. There's no signal from ComfyUI to tell the two apart,
          // so this now defaults to the more common, more honest case.
          _setBusyStatus(generateStatus, tF('Model initializing… this can take a while'));
        }
      }, DOWNLOAD_STALL_MS);
    }

    activeES.onmessage = function (e) {
      try {
        var msg = JSON.parse(e.data);
        var t = String(msg.type || '').toLowerCase();
        if (t === 'executing') {
          clearNote(); armDownloadNote();
          if (!executionStarted) {
            executionStarted = true;
            if (generateStatus) _setBusyStatus(generateStatus, readyLabel || tF('Generating…'));
          }
        } else if (t === 'progress' && msg.max > 0) {
          clearNote();
          var pct = Math.max(1, Math.min(99, Math.round((msg.value / msg.max) * 100)));
          if (generateStatus) generateStatus.textContent = tF('Generating…') + ' ' + pct + '%';
          updateCardProgress(card, msg.value, msg.max);
        } else if (t === 'executed' || t === 'execution_cached') {
          clearNote();
        } else if (t === 'image_ready') {
          imgUrl = msg.url || msg.image_url;
        } else if (t === 'done') {
          clearNote();
          activeES.close(); activeES = null;
          if (imgUrl) resolve(imgUrl);
          else pollComfy(promptId, comfyUrl).then(function (imgs) {
            resolve((imgs[0] && imgs[0].url) || '');
          }).catch(reject);
        } else if (t === 'error' || t === 'connection_lost') {
          clearNote();
          activeES.close(); activeES = null;
          if (imgUrl) resolve(imgUrl);
          else reject(new Error(msg.message || 'Stream error'));
        }
      } catch (_) {}
    };
    activeES.onerror = function () {
      clearNote();
      activeES.close(); activeES = null;
      if (imgUrl) resolve(imgUrl);
      else pollComfy(promptId, comfyUrl).then(function (imgs) {
        resolve((imgs[0] && imgs[0].url) || '');
      }).catch(reject);
    };
  });
}

// Independent EventSource per call — used for parallel multi-workflow generation.
//
// onNote(text) — optional. ComfyUI doesn't expose real download progress for
// custom nodes fetching a model for the first time (they just block while
// pulling from HF/civitai, logging to their own console); the closest signal
// we get over the websocket is "executing" for a node with no "progress" or
// "executed" following it for a while. That's a heuristic, not a real
// progress bar, but it's enough to tell the user "this node is probably
// downloading a model" instead of leaving them staring at a stuck spinner.
// Called with '' to clear the note once real progress/completion resumes.
async function waitForImageLocal(comfyUrl, clientId, promptId, card, onNote) {
  return new Promise(function (resolve, reject) {
    var params = new URLSearchParams({ comfyApiUrl: comfyUrl, clientId: clientId });
    var es = new EventSource('/api/images/comfy/progress-stream?' + params);
    var imgUrl = null;
    var noteTimer = null;
    var noteShown = false;
    var DOWNLOAD_STALL_MS = 4000;

    function clearNote() {
      if (noteTimer) { clearTimeout(noteTimer); noteTimer = null; }
      if (noteShown) {
        noteShown = false;
        // Same brief confirmation flash as waitForImage's clearNote — see
        // that comment for why.
        if (typeof onNote === 'function') {
          onNote(tF('Model initialization complete!'));
          setTimeout(function () { if (typeof onNote === 'function') onNote(''); }, 1200);
        }
      }
    }
    function armDownloadNote() {
      if (noteTimer) clearTimeout(noteTimer);
      noteTimer = setTimeout(function () {
        noteShown = true;
        // See waitForImage's armDownloadNote comment: usually VRAM loading,
        // not a real download — wording now reflects the common case.
        if (typeof onNote === 'function') onNote('Model initializing… this can take a while');
      }, DOWNLOAD_STALL_MS);
    }

    es.onmessage = function (e) {
      try {
        var msg = JSON.parse(e.data);
        var t = String(msg.type || '').toLowerCase();
        if (t === 'executing') { clearNote(); armDownloadNote(); }
        else if (t === 'progress' && msg.max > 0) { clearNote(); updateCardProgress(card, msg.value, msg.max); }
        else if (t === 'executed' || t === 'execution_cached') { clearNote(); }
        else if (t === 'image_ready') imgUrl = msg.url || msg.image_url;
        else if (t === 'done') {
          clearNote();
          es.close();
          if (imgUrl) resolve(imgUrl);
          else pollComfy(promptId, comfyUrl).then(function (imgs) { resolve((imgs[0] && imgs[0].url) || ''); }).catch(reject);
        } else if (t === 'error' || t === 'connection_lost') {
          clearNote();
          es.close();
          if (imgUrl) resolve(imgUrl); else reject(new Error(msg.message || 'Stream error'));
        }
      } catch (_) {}
    };
    es.onerror = function () {
      clearNote();
      es.close();
      if (imgUrl) resolve(imgUrl);
      else pollComfy(promptId, comfyUrl).then(function (imgs) { resolve((imgs[0] && imgs[0].url) || ''); }).catch(reject);
    };
  });
}

async function submitWorkflowAndWait(wfId, positivePrompt, seedVal, card, dims) {
  var isCustom = (getMode() === 'advanced');
  var prepRes = await fetch('/api/models/imports/prepare-queue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      basicValues:    { positive: positivePrompt, negative: (typeof effectiveNegativePrompt === 'function' ? effectiveNegativePrompt() : (selectedNegativePrompt || '')), seed: seedVal, width: dims.w, height: dims.h, loraKeywordsOff: loraKeywordsOffList() },
      advancedValues: Object.assign({}, isCustom ? (_wfAdvOverrides[wfId] || {}) : (selectedQualityValues || {}), isCustom ? {} : (selectedQuantizationValues || {}), isCustom ? {} : (selectedLoraValues || {}), _civitaiAdvancedOverrides),
      disabledSubgraphs: selectedDisabledSubgraphs || [],
      numImages:      1,
      targetImportId: wfId,
    }),
  });
  var prepData = await prepRes.json();
  if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');
  var submitRes = await fetch('/api/images/comfy/prompt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ comfyApiUrl: prepData.comfyApiUrl, prompt: prepData.workflow, client_id: prepData.clientId }),
  });
  var submitData = await submitRes.json();
  if (!submitRes.ok || submitData.error) {
    var ce = submitData.error;
    throw new Error(typeof ce === 'object' ? (ce.message || ce.type || JSON.stringify(ce)) : String(ce || 'Queue rejected'));
  }
  if (!submitData.prompt_id) throw new Error(tF('ComfyUI did not return a prompt_id'));
  var _params = buildParamsSnapshot({ kind: 'generate', positive: positivePrompt, seed: seedVal, width: dims.w, height: dims.h, workflowId: wfId });
  if (card) card._params = _params;
  var rawUrl = await waitForImageLocal(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, card);
  return saveFlowImage(rawUrl, prepData.comfyApiUrl, prepData.importId, positivePrompt, seedVal, _params);
}

async function pollComfy(promptId, comfyUrl) {
  var failures = 0;
  for (var i = 0; i < 720; i++) {
    try {
      var res  = await fetch('/api/images/comfy/history/' + encodeURIComponent(promptId) + '?comfyApiUrl=' + encodeURIComponent(comfyUrl), { cache: 'no-store' });
      var data = await res.json();
      var entry = data && data[promptId];
      if (entry && entry.status && (entry.status.completed || entry.status.status_str === 'success')) {
        var images = [];
        Object.keys(entry.outputs || {}).forEach(function (nId) {
          var n = entry.outputs[nId];
          if (Array.isArray(n.images)) n.images.forEach(function (img) {
            if (img.filename) images.push({ url: comfyUrl + '/view?filename=' +
              encodeURIComponent(img.filename) + '&subfolder=' + encodeURIComponent(img.subfolder || '') +
              '&type=' + encodeURIComponent(img.type || 'output') });
          });
        });
        if (!images.length) throw new Error(tF('ComfyUI finished but no images.'));
        return images;
      }
      failures = 0;
    } catch (err) {
      if (++failures >= 15) throw err;
    }
    await sleep(1000);
  }
  throw new Error(tF('Generation timed out.'));
}

// ══════════════════════════════════════════════════════════════════════════
// RIGHT PANEL
// ══════════════════════════════════════════════════════════════════════════

// ── Queue management ──────────────────────────────────────────────────────

// Queue dispatch for action flows (refine/upscale/mix).
// Snapshot the resolved inputs of an action flow (refine/upscale/mix) and push
// it to the queue, showing a queued card. Returns true if it handled the step.
function _enqueueAction(stepDef) {
  // Refine flows can carry more than one source image (stepDef.multiple on the
  // image_picker step) — fan out to one queued job per image, each running the
  // same flow/params against a different input, reusing the same sequential
  // queue as any other job.
  if (stepDef.calls === 'generation.submit_refine') {
    var refineSnap = _snapshotRefine(stepDef);
    if (!refineSnap || refineSnap.__invalid) return true;
    var images = (Array.isArray(refineSnap.imageDataUrls) && refineSnap.imageDataUrls.length)
      ? refineSnap.imageDataUrls : [refineSnap.imageDataUrl];
    images.forEach(function (dataUrl, i) {
      var jobSnapshot = Object.assign({}, refineSnap, {
        imageDataUrl: dataUrl,
        cardPrompt: images.length > 1
          ? (refineSnap.cardPrompt || 'Refining…') + ' (' + (i + 1) + '/' + images.length + ')'
          : refineSnap.cardPrompt,
      });
      var slotNum = generatedCount + 1 + _genQueue.length;
      var card = _addQueuedCard(slotNum, jobSnapshot.cardPrompt || '');
      _genQueue.push({ type: 'action', runner: _runRefine, stepDef: stepDef, snapshot: jobSnapshot, card: card });
    });
    if (generateStatus) generateStatus.textContent = _genQueue.length + ' queued';
    return true;
  }

  var snapshot, runner;
  if (stepDef.calls === 'generation.submit_upscale'){ runner = _runUpscale; snapshot = _snapshotUpscale(stepDef); }
  else if (stepDef.calls === 'generation.submit_mix')    { runner = _runMix;     snapshot = _snapshotMix(stepDef); }
  else if (stepDef.calls === 'layer_compose.submit')     { runner = _runLayerCompose; snapshot = _snapshotLayerCompose(stepDef); }
  else return false;

  if (!snapshot || snapshot.__invalid) return true; // nothing valid to enqueue

  var slotNum = generatedCount + 1 + _genQueue.length;
  var card = _addQueuedCard(slotNum, snapshot.cardPrompt || '');
  _genQueue.push({ type: 'action', runner: runner, stepDef: stepDef, snapshot: snapshot, card: card });
  if (generateStatus) generateStatus.textContent = _genQueue.length + ' queued';
  return true;
}

// Snapshot current generation params and push to the queue, showing a queued card.
function _enqueueGeneration(stepDef) {
  if (_enqueueAction(stepDef)) return;

  var isCustom = (getMode() === 'advanced');
  var inputMap = stepDef.input_map || {};
  var rawPositive = resolveRef(inputMap['basicValues.positive'])
    || getVal('scene_prompt', 'prompt_text')
    || getVal('world', 'prompt_text') || '';
  var positivePrompt = Array.isArray(rawPositive) ? (rawPositive.filter(Boolean)[0] || '') : String(rawPositive);
  if (!positivePrompt) return;

  var dims = getDims();
  var seedVal = (isCustom && selectedSeed >= 0) ? selectedSeed : Math.floor(Math.random() * 0x7FFFFFFF);
  var workflowId = (isCustom && getGlobalWorkflows().length > 0) ? getGlobalWorkflows()[0] : selectedImportId;

  var slotNum = generatedCount + 1 + _genQueue.length;
  var card = _addQueuedCard(slotNum, positivePrompt);
  _genQueue.push({ card: card, positivePrompt: positivePrompt, seedVal: seedVal, workflowId: workflowId, dims: dims, stepDef: stepDef });
  if (generateStatus) generateStatus.textContent = _genQueue.length + ' queued';
}

// Consume the next queued item and run it.
// Shared "queued → generating" transition — swaps in the spinner ring and
// flips the status dot/label. Used by _processQueue (the main app's own
// queue) and by the chat bar's queue (_processChatQueue, flow-gallery.js),
// so both look the same the moment a card's turn actually comes up.
function _markCardGenerating(card) {
  card.setAttribute('data-status', 'generating');
  var dot = card.querySelector('.nss-card-status-dot');
  var lbl = card.querySelector('.nss-card-status-label');
  if (dot) dot.setAttribute('data-status', 'generating');
  if (lbl) lbl.textContent = tF('generating…');
  var imgWrap = card.querySelector('.nss-card-img-wrap');
  if (imgWrap) {
    imgWrap.innerHTML =
      '<svg class="nsc-ring nsc-ring--indeterminate" viewBox="0 0 44 44" aria-hidden="true">' +
        '<circle class="nsc-ring-bg" cx="22" cy="22" r="18"/>' +
        '<circle class="nsc-ring-fill" cx="22" cy="22" r="18"/>' +
      '</svg>' +
      '<span class="nsc-ring-pct"></span><span class="nsc-ring-steps"></span><span class="nsc-ring-eta"></span>';
    card._genStartTime = Date.now();
  }
}

// Same "error" flip _processQueue's own catch block already used inline —
// shared with the chat queue (flow-gallery.js) so a failed chat send looks
// the same as any other failed queued job.
function _markCardError(card, message) {
  if (!card) return;
  card.setAttribute('data-status', 'error');
  var dot = card.querySelector('.nss-card-status-dot');
  var lbl = card.querySelector('.nss-card-status-label');
  if (dot) dot.setAttribute('data-status', 'error');
  if (lbl) lbl.textContent = 'error';
  // The spinner ring would otherwise keep turning on a job that is over.
  var imgWrap = card.querySelector('.nss-card-img-wrap');
  if (imgWrap && imgWrap.querySelector('.nsc-ring')) {
    imgWrap.innerHTML = '<span class="nss-card-error-msg"></span>';
    imgWrap.firstChild.textContent = message || 'Generation failed';
  }
}

async function _processQueue() {
  // Every run ends here (each runner's finally calls it): with nothing left
  // to do, the Session step started on Generate is settled.
  if (!isGenerating && !_genQueue.length && window.NomadSession &&
      typeof NomadSession.settleStep === 'function') {
    try { NomadSession.settleStep(); } catch (_) {}
  }
  if (isGenerating || !_genQueue.length) return;
  var item = _genQueue.shift();
  var card = item.card;
  _markCardGenerating(card);

  isGenerating = true;
  updateGenerateBtn();
  try {
    if (item.type === 'action') {
      // Refine / upscale / mix — reuse the queued card and the captured snapshot.
      await item.runner(item.stepDef, { snapshot: item.snapshot, card: card });
    } else {
      var imgUrl = await submitWorkflowAndWait(item.workflowId, item.positivePrompt, item.seedVal, card, item.dims);
      imgUrl = await _maybeUpscaleOutput(imgUrl, card);
      generatedCount++;
      addToFeed(imgUrl, generatedCount, card, card._params);
      showResultActions(item.stepDef);
      if (generateStatus) generateStatus.textContent = _genQueue.length
        ? '✓ ' + generatedCount + ' generated · ' + _genQueue.length + ' queued'
        : '✓ ' + generatedCount + ' generated';
      if (typeof saveSessionSnapshot === 'function') saveSessionSnapshot();
    }
  } catch (err) {
    _markCardError(card, err && err.message);
    if (generateStatus) generateStatus.textContent = '✗ ' + (err.message || 'Generation failed');
    console.error('[FlowEngine] queued job failed:', err);
  } finally {
    isGenerating = false;
    updateGenerateBtn();
    _processQueue();
  }
}

// Queued placeholder card (amber state, clock icon, no spinner).
function _addQueuedCard(idx, promptText) {
  if (resultsEmpty) resultsEmpty.style.display = 'none';
  if (resultsGrid)  resultsGrid.style.display  = '';

  var card = document.createElement('div');
  card.className = 'nss-card';
  card.setAttribute('data-status', 'queuing');

  var header = document.createElement('div');
  header.className = 'nss-card-header';
  var numBadge = document.createElement('span');
  numBadge.className = 'nss-card-num';
  numBadge.textContent = resultCardLabel(idx);
  header.appendChild(numBadge);
  card.appendChild(header);

  var imgWrap = document.createElement('div');
  imgWrap.className = 'nss-card-img-wrap nss-card-img-wrap--queued';
  imgWrap.innerHTML =
    '<svg class="nss-queued-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" ' +
    'stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">' +
      '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>' +
    '</svg>';
  card.appendChild(imgWrap);

  if (promptText) {
    var promptTa = document.createElement('textarea');
    promptTa.className = 'nss-card-prompt';
    promptTa.value = promptText;
    promptTa.rows = 3;
    card.appendChild(promptTa);
  }

  var footer = document.createElement('div');
  footer.className = 'nss-card-footer';
  var statusDot = document.createElement('span');
  statusDot.className = 'nss-card-status-dot';
  statusDot.setAttribute('data-status', 'queuing');
  var statusLabel = document.createElement('span');
  statusLabel.className = 'nss-card-status-label';
  statusLabel.textContent = 'queued';
  footer.appendChild(statusDot);
  footer.appendChild(statusLabel);
  card.appendChild(footer);

  if (resultsGrid) {
    resultsGrid.appendChild(card);
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  return card;
}

// Creates a placeholder card with a spinner and adds it to the feed.
// Returns the card element so addToFeed can update it once the image is ready.
// Result card badge: "Scene N" in the scene-telling flows (Story, Scenes,
// Chat), "Image N" everywhere else (Simple's --r copies aren't scenes).
function resultCardLabel(idx) {
  var scenes = typeof flowId === 'string' && /\.(story|scenes|chat)/.test(flowId);
  var text = scenes ? 'Scene {n}' : 'Image {n}';
  return (typeof tF === 'function' ? tF(text) : text).replace('{n}', idx);
}

function addGeneratingCard(idx, promptText) {
  if (resultsEmpty) resultsEmpty.style.display = 'none';
  if (resultsGrid)  resultsGrid.style.display  = '';

  var card = document.createElement('div');
  card.className = 'nss-card';
  card.id = 'nss-card-' + idx;
  card.setAttribute('data-status', 'generating');

  var header = document.createElement('div');
  header.className = 'nss-card-header';
  var numBadge = document.createElement('span');
  numBadge.className = 'nss-card-num';
  numBadge.textContent = resultCardLabel(idx);
  header.appendChild(numBadge);
  card.appendChild(header);

  var imgWrap = document.createElement('div');
  imgWrap.className = 'nss-card-img-wrap';
  imgWrap.innerHTML =
    '<svg class="nsc-ring nsc-ring--indeterminate" viewBox="0 0 44 44" aria-hidden="true">' +
      '<circle class="nsc-ring-bg" cx="22" cy="22" r="18"/>' +
      '<circle class="nsc-ring-fill" cx="22" cy="22" r="18"/>' +
    '</svg>' +
    '<span class="nsc-ring-pct"></span>' +
    '<span class="nsc-ring-steps"></span>' +
    '<span class="nsc-ring-eta"></span>';
  card.appendChild(imgWrap);
  card._genStartTime = Date.now();

  if (promptText) {
    var promptTa = document.createElement('textarea');
    promptTa.className = 'nss-card-prompt';
    promptTa.value = promptText;
    promptTa.rows = 3;
    card.appendChild(promptTa);
  }

  var footer = document.createElement('div');
  footer.className = 'nss-card-footer';
  var statusDot = document.createElement('span');
  statusDot.className = 'nss-card-status-dot';
  statusDot.setAttribute('data-status', 'generating');
  var statusLabel = document.createElement('span');
  statusLabel.className = 'nss-card-status-label';
  statusLabel.textContent = tF('generating…');
  footer.appendChild(statusDot);
  footer.appendChild(statusLabel);
  card.appendChild(footer);

  if (resultsGrid) {
    resultsGrid.appendChild(card);
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  return card;
}

// Renders N editable prompt cards (same pattern as +Scenes).
// Cards have an image area (hidden) that runGenerate fills in-place.
function renderPromptCards(arr, stepId) {
  if (resultsGrid) {
    Array.from(resultsGrid.querySelectorAll('[data-prompt-card]')).forEach(function (c) { c.remove(); });
  }
  if (resultsEmpty) resultsEmpty.style.display = 'none';
  if (resultsGrid)  resultsGrid.style.display  = '';

  var liveArr = arr.slice();
  setVal(stepId, 'transformed_text', liveArr);

  // Build in index order and append as a fragment — cards land after any
  // previously generated results, so earlier scenes (Scene 1 first) never
  // get pushed down/around by a new batch. It's a queue, not a stack.
  var frag = document.createDocumentFragment();
  var _firstNewCard = null;
  arr.forEach(function (text, i) {
    var _c = buildPromptCard(text, i, function (newText) {
      liveArr[i] = newText;
      setVal(stepId, 'transformed_text', liveArr.slice());
      updateGenerateBtn();
    });
    if (!_firstNewCard) _firstNewCard = _c;
    frag.appendChild(_c);
  });
  if (resultsGrid) {
    resultsGrid.appendChild(frag);
    if (_firstNewCard) _firstNewCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function buildPromptCard(text, idx, onEdit) {
  var card = document.createElement('div');
  card.className = 'nss-card';
  card.setAttribute('data-status', 'idle');
  card.setAttribute('data-prompt-card', idx);

  // Header
  var header = document.createElement('div');
  header.className = 'nss-card-header';
  var numBadge = document.createElement('span');
  numBadge.className = 'nss-card-num';
  numBadge.textContent = tF('Variation {n}').replace('{n}', idx + 1);
  header.appendChild(numBadge);
  
  var delBtn = document.createElement('button');
  delBtn.type = 'button';
  delBtn.className = 'nss-card-select-btn nss-card-delete-btn';
  delBtn.setAttribute('aria-label', tF('Delete card'));
  delBtn.title = tF('Delete card');
  delBtn.innerHTML =
    '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
      '<polyline points="2,4 14,4"/>' +
      '<path d="M5 4V2h6v2M6 7v5M10 7v5"/>' +
      '<path d="M3 4l1 9a1 1 0 001 1h6a1 1 0 001-1l1-9"/>' +
    '</svg>';
  delBtn.addEventListener('click', function () {
    if (confirm(tF('Delete this card from the flow?'))) {
      card.remove();
      // Notice: editing prompt array on variations not strictly handled by this click but UI will update
    }
  });
  header.appendChild(delBtn);
  
  card.appendChild(header);

  // Image area with spinner — always visible (same as +Scenes)
  var imgWrap = document.createElement('div');
  imgWrap.className = 'nss-card-img-wrap';
  imgWrap.innerHTML =
    '<svg class="nsc-ring nsc-ring--indeterminate" viewBox="0 0 44 44" aria-hidden="true">' +
      '<circle class="nsc-ring-bg" cx="22" cy="22" r="18"/>' +
      '<circle class="nsc-ring-fill" cx="22" cy="22" r="18"/>' +
    '</svg>' +
    '<span class="nsc-ring-pct"></span>' +
    '<span class="nsc-ring-steps"></span>' +
    '<span class="nsc-ring-eta"></span>';
  card.appendChild(imgWrap);
  card._genStartTime = Date.now();

  // Editable prompt textarea
  var ta = document.createElement('textarea');
  ta.className = 'nss-card-prompt';
  ta.value = text;
  ta.rows = 4;
  ta.addEventListener('input', function () { onEdit(ta.value); });
  card.appendChild(ta);

  // Footer — status dot + label + Queue button
  var footer = document.createElement('div');
  footer.className = 'nss-card-footer';

  var statusDot = document.createElement('span');
  statusDot.className = 'nss-card-status-dot';
  statusDot.setAttribute('data-status', 'idle');

  var statusLabel = document.createElement('span');
  statusLabel.className = 'nss-card-status-label';
  statusLabel.textContent = 'idle';

  var queueBtn = document.createElement('button');
  queueBtn.className = 'nss-card-queue-btn';
  queueBtn.type = 'button';
  queueBtn.textContent = tF('Queue');

  footer.appendChild(statusDot);
  footer.appendChild(statusLabel);
  footer.appendChild(queueBtn);
  card.appendChild(footer);

  // Queue button — generate this single card
  queueBtn.addEventListener('click', function () {
    var currentStatus = card.getAttribute('data-status');
    if (currentStatus === 'idle' || currentStatus === 'selected') {
      _generateOneCard(card, ta, statusDot, statusLabel, queueBtn);
    }
  });

  return card;
}

// Generates a single prompt card in-place (triggered by Queue button)
async function _generateOneCard(card, ta, statusDot, statusLabel, queueBtn) {
  var prompt = ta.value.trim();
  var isCustom = (getMode() === 'advanced');
  var effectiveWfId = isCustom ? (getGlobalWorkflows()[0] || selectedImportId) : selectedImportId;
  if (!prompt || !effectiveWfId) return;

  var setStatus = function (s, lbl) {
    card.setAttribute('data-status', s);
    statusDot.setAttribute('data-status', s);
    statusLabel.textContent = lbl || s;
  };

  setStatus('generating', 'generating…');
  queueBtn.disabled = true;
  ta.disabled = true;

  var imgWrap = card.querySelector('.nss-card-img-wrap');
  imgWrap.innerHTML =
    '<svg class="nsc-ring nsc-ring--indeterminate" viewBox="0 0 44 44" aria-hidden="true">' +
      '<circle class="nsc-ring-bg" cx="22" cy="22" r="18"/>' +
      '<circle class="nsc-ring-fill" cx="22" cy="22" r="18"/>' +
    '</svg>' +
    '<span class="nsc-ring-pct"></span>' +
    '<span class="nsc-ring-steps"></span>';

  try {
    var dims = getDims();
    var seedVal = (isCustom && selectedSeed >= 0) ? selectedSeed : Math.floor(Math.random() * 0x7FFFFFFF);

    var prepRes = await fetch('/api/models/imports/prepare-queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        basicValues:    { positive: prompt, negative: (typeof effectiveNegativePrompt === 'function' ? effectiveNegativePrompt() : (selectedNegativePrompt || '')), seed: seedVal, width: dims.w, height: dims.h, loraKeywordsOff: loraKeywordsOffList() },
        advancedValues: Object.assign({}, isCustom ? currentAdvOverrides : (selectedQualityValues || {}), isCustom ? {} : (selectedQuantizationValues || {}), isCustom ? {} : (selectedLoraValues || {}), _civitaiAdvancedOverrides),
        disabledSubgraphs: selectedDisabledSubgraphs || [],
        numImages: 1, targetImportId: effectiveWfId,
      }),
    });
    var prepData = await prepRes.json();
    if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');

    var submitRes = await fetch('/api/images/comfy/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comfyApiUrl: prepData.comfyApiUrl, prompt: prepData.workflow, client_id: prepData.clientId }),
    });
    var submitData = await submitRes.json();
    if (!submitRes.ok || submitData.error) throw _queueRejected(submitData);
    if (!submitData.prompt_id) throw new Error(tF('No prompt_id'));

    var imgUrl = await waitForImage(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id, card, 'Generating…');
    var _cardParams = buildParamsSnapshot({ kind: 'generate', positive: prompt, seed: seedVal, width: dims.w, height: dims.h, workflowId: effectiveWfId });
    // Same local save as every other generation path — with "save space" on,
    // ComfyUI only keeps this image in its temp/ folder (wiped on restart).
    imgUrl = await saveFlowImage(imgUrl, prepData.comfyApiUrl, prepData.importId, prompt, seedVal, _cardParams);
    generatedCount++;
    addToFeed(imgUrl, generatedCount, card, _cardParams);
    setStatus('done', 'done');
  } catch (err) {
    setStatus('error', 'error');
    console.error('[FlowEngine] _generateOneCard:', err);
    queueBtn.disabled = false;
    ta.disabled = false;
  }
}

// ── Lightbox ───────────────────────────────────────────────────────────────
var sessionImages  = [];  // each entry: { url, bboxes } — bboxes may be null
var lightboxCursor = 0;
var _lbBboxes = null;     // bboxes for the currently open lightbox image

// Extract ideogram bboxes from a card's prompt textarea, if present.
