'use strict';
// Step: image_picker → renderImagePicker

function renderImagePicker(stepDef, el) {
  var UPSCALE_SRC_KEY = 'oj-upscale-source-image-v1';
  // Set right before loading an image whose style text is already known
  // (the Styles catalog pick, below) so the auto-Vision hook doesn't also
  // fire for it and stomp the catalog's own prefix/suffix + "Edit Prompt
  // from Style" panel with a redundant description call.
  var _skipVisionOnNextLoad = false;

  var wrap = document.createElement('div');
  wrap.className = 'nsc-image-picker';
  wrap.id = 'ncf-image-picker-' + stepDef.id;
  el.appendChild(wrap);

  // Same "find this step's own label, may be in a parent .nsc-step wrapper"
  // lookup flow-step-prompt-input.js's History button uses — the "⋯ More"
  // trigger (built further down, once the Crop/Inputs/Tray/History click
  // handlers exist) is appended there too, next to e.g. "SOURCE IMAGE",
  // instead of floating inside the drop zone.
  var stepLabelEl = el.querySelector('.nsc-step-label') ||
                    (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));

  var fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = 'image/png,image/jpeg,image/webp';
  fileInput.style.display = 'none';
  fileInput.id = 'ncf-image-file-' + stepDef.id;
  if (stepDef.multiple) fileInput.multiple = true;
  wrap.appendChild(fileInput);

  // issue #20: the CROP/INPUTS/TRAY/HISTORY column used to sit beside the
  // drop zone, narrowing it — collapsed into one "⋯ More" trigger appended
  // to the step's own label (stepLabelEl, above) instead, so the drop zone
  // no longer shares its row with anything and goes back to full width.
  var dropZone = document.createElement('div');
  dropZone.className = 'nsc-image-drop-zone';
  dropZone.setAttribute('role', 'button');
  dropZone.setAttribute('tabindex', '0');
  dropZone.setAttribute('aria-label', 'Drop image or click to choose');
  dropZone.innerHTML =
    '<div class="nsc-image-drop-placeholder">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<rect x="3" y="3" width="18" height="18" rx="2"/>' +
        '<circle cx="8.5" cy="8.5" r="1.5"/>' +
        '<path d="M21 15l-5-5L5 21"/>' +
      '</svg>' +
      '<p>Drop image' + (stepDef.multiple ? 's' : '') + ' here<br><span>or click to choose' +
      (stepDef.multiple ? ' (multiple allowed)' : '') + '</span></p>' +
    '</div>';
  wrap.appendChild(dropZone);

  // "From flow" — pick any image produced earlier in this session.
  if (sessionImages().length) {
    var prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'ncf-prevflow-btn';
    prevBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" ' +
      'stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h13l-3-3M3 7l3 3"/>' +
      '<rect x="14" y="13" width="7" height="7" rx="1.5"/></svg>' +
      '<span>From flow</span>';
    prevBtn.addEventListener('click', openPrevFlowModal);
    wrap.appendChild(prevBtn);
  }

  var previewEl = null;
  var clearBtn  = null;

  // ── Downscale-on-upload ───────────────────────────────────────────────────
  // Persistent per-picker setting (1x/2x/3x/4x pills below the image, not a
  // one-off button floating on top of it where it's easy to miss). Whatever
  // factor is selected gets applied automatically to every incoming image —
  // drag/drop, file picker, tray, previous-flow, batch — via handleDataUrl()
  // and addImages(), the two funnels every source goes through.
  var _downscaleFactor = 1; // 1x = off, the default
  var _currentImgW = 0, _currentImgH = 0; // dims of whatever's actually displayed right now (hover badge)
  var _origImgW = 0, _origImgH = 0; // dims of the untouched original — the "result" readout must always divide from here, never from an already-shrunk copy
  // Untouched, raw (pre-downscale) source data — kept so that switching the
  // pill on an already-loaded image can re-derive from the true original
  // instead of compounding shrinkage on top of an already-shrunk copy.
  var _originals = []; // parallel to image_data_urls, multi mode
  var _singleOriginal = ''; // single-image mode

  function _measureDims(dataUrl) {
    return new Promise(function (resolve) {
      var img = new Image();
      img.onload = function () { resolve({ w: img.naturalWidth || 0, h: img.naturalHeight || 0 }); };
      img.onerror = function () { resolve({ w: 0, h: 0 }); };
      img.src = dataUrl;
    });
  }

  // issue #20: was an always-visible label+result header AND a permanent
  // row of 4 pills — collapsed into the same "current value + trigger
  // button opens the shared options panel" pattern Aspect ratio/Resolution
  // already use (flow-step-workflow-params.js's aspectWrap/resTierWrap), so
  // this reads as the same kind of control instead of one-off pills.
  var downscaleWrap = document.createElement('div');
  downscaleWrap.className = 'nsc-param-block nsc-picker-downscale';
  downscaleWrap.innerHTML =
    '<p class="nsc-param-title nsc-param-title--flex">Downscale Source <span class="nsc-param-value" id="ncf-downscale-label-' + stepDef.id + '">1x</span>' +
      '<button type="button" class="nsc-history-btn nsc-options-trigger" id="ncf-downscale-picker-btn-' + stepDef.id + '" aria-label="Choose downscale">' +
        '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9h10M9 4v10"/></svg>' +
      '</button>' +
    '</p>';
  wrap.appendChild(downscaleWrap);
  var downscaleLabelEl   = downscaleWrap.querySelector('#ncf-downscale-label-' + stepDef.id);
  var downscalePickerBtn = downscaleWrap.querySelector('#ncf-downscale-picker-btn-' + stepDef.id);

  function _updateDownscaleResult() {
    if (!downscaleLabelEl) return;
    if (!_origImgW || !_origImgH) { downscaleLabelEl.textContent = _downscaleFactor + 'x'; return; }
    var w2 = Math.max(1, Math.round(_origImgW / _downscaleFactor));
    var h2 = Math.max(1, Math.round(_origImgH / _downscaleFactor));
    downscaleLabelEl.textContent = _downscaleFactor + 'x · ' + w2 + '×' + h2;
  }

  function _setDownscaleFactor(factor) {
    _downscaleFactor = factor;
    _updateDownscaleResult();
    _reprocessCurrentImages();
  }

  // Same .nsc-quality-list/.nsc-quality-btn row shape as Resolution's own
  // panel (flow-aspect-panel.js's openResolutionPanel) — dot + bold value +
  // small resulting-dimensions line, since this is the same kind of choice
  // (pick a tier, see the pixel result) just for downscale instead of res.
  downscalePickerBtn.addEventListener('click', function () {
    openOptionsPanel('Downscale', function (body) {
      var list = document.createElement('div');
      list.className = 'nsc-quality-list';
      list.setAttribute('role', 'radiogroup');
      [1, 2, 3, 4].forEach(function (factor) {
        var w2 = _origImgW ? Math.max(1, Math.round(_origImgW / factor)) : 0;
        var h2 = _origImgH ? Math.max(1, Math.round(_origImgH / factor)) : 0;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nsc-quality-btn' + (factor === _downscaleFactor ? ' is-active' : '');
        btn.setAttribute('role', 'radio');
        btn.setAttribute('aria-checked', factor === _downscaleFactor ? 'true' : 'false');
        btn.title = factor === 1 ? 'No downscale' : 'Shrink each side to 1/' + factor + ' on upload';
        btn.innerHTML =
          '<span class="nsc-quality-dot"></span>' +
          '<span class="nsc-quality-copy"><strong>' + factor + 'x</strong>' +
          (w2 && h2 ? '<small>' + w2 + '×' + h2 + '</small>' : '') + '</span>';
        btn.addEventListener('click', function () {
          _setDownscaleFactor(factor);
          closeOptionsPanel();
        });
        list.appendChild(btn);
      });
      body.appendChild(list);
    });
  });

  // ── Styles (opt-in via stepDef.style_image_input) ──────────────────────
  // For flows where the source image IS a style reference (e.g. RF Inversion
  // style transfer), reuses the same Styles catalog panel other flows use
  // for their text-only style_picker field (_openStylePickerPanel,
  // flow-step-workflow-params.js) — but on pick, loads that style's own
  // reference image straight into this picker via loadUrlAsImage() (defined
  // below), instead of composing a prefix/suffix prompt string.
  if (stepDef.style_image_input) {
    var stylesBtn = document.createElement('button');
    stylesBtn.type = 'button';
    stylesBtn.className = 'nsc-history-btn nsc-options-trigger';
    stylesBtn.setAttribute('aria-label', 'Choose a Style');
    stylesBtn.title = 'Choose a Style';
    stylesBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
        '<circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/>' +
        '<path d="M12 2a10 10 0 1 0 10 10c0-1.1-.9-2-2-2h-2.3a2 2 0 0 1-2-2c0-.5.2-1 .5-1.3A2 2 0 0 0 14.7 3c-.9-.6-1.8-1-2.7-1z"/>' +
      '</svg>';
    // In the step's own header, next to its "⋯" button — not a separate
    // "Styles" row under the drop zone.
    if (stepLabelEl) {
      var stylesChevron = stepLabelEl.querySelector('.nsc-step-chevron');
      if (stylesChevron) stepLabelEl.insertBefore(stylesBtn, stylesChevron);
      else stepLabelEl.appendChild(stylesBtn);
    } else {
      wrap.insertBefore(stylesBtn, wrap.firstChild);
    }

    // "Describe style" — for a reference image of the user's own (no catalog
    // wording attached): the vision model reads its look and returns a
    // style's prefix/suffix (same /api/styles/generate-from-image Build uses
    // to create a style from a picture), which the composed prompt picks up
    // like a catalog pick.
    var describeBtn = document.createElement('button');
    describeBtn.type = 'button';
    describeBtn.className = 'nsc-history-btn ncf-describe-style-btn';
    describeBtn.setAttribute('aria-label', 'Describe style');
    describeBtn.title = 'Describe this image\'s style with the vision model';
    var _describeIcon =
      '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>' +
      '</svg>';
    describeBtn.innerHTML = _describeIcon;
    if (stylesBtn.parentNode) stylesBtn.parentNode.insertBefore(describeBtn, stylesBtn.nextSibling);
    describeBtn.addEventListener('click', function () {
      var dataUrl = getVal(stepDef.id, 'image_data_url');
      if (!dataUrl) {
        if (typeof showErrorToast === 'function') showErrorToast(tF('Pick a style reference image first.'));
        return;
      }
      if (!window.openJourneyApi || typeof window.openJourneyApi.generateStyleFromImage !== 'function') return;
      describeBtn.disabled = true;
      describeBtn.classList.add('is-busy');
      describeBtn.innerHTML =
        '<svg class="nsc-ring nsc-ring--indeterminate" viewBox="0 0 44 44" aria-hidden="true" style="width:16px;height:16px">' +
        '<circle class="nsc-ring-bg" cx="22" cy="22" r="18"/><circle class="nsc-ring-fill" cx="22" cy="22" r="18"/></svg>';
      window.openJourneyApi.generateStyleFromImage({ imageDataUrl: dataUrl })
        .then(function (data) {
          var style = (data && data.style) || {};
          setVal(stepDef.id, 'style_prefix', String(style.prefix || '').trim());
          setVal(stepDef.id, 'style_suffix', String(style.suffix || '').trim());
          setVal(stepDef.id, 'style_name', String(style.title || 'Your image').trim());
          // Flows still on the Edit Prompt panel (Mix style flows) get the
          // same pre-fill a catalog pick gives them.
          setVal(stepDef.id, 'edit_prompt_prefix', String(style.prefix || '').trim());
          setVal(stepDef.id, 'edit_prompt_suffix', String(style.suffix || '').trim());
          document.dispatchEvent(new CustomEvent('ncf-style-changed', { detail: { stepId: stepDef.id } }));
        })
        .catch(function (err) {
          if (typeof showErrorToast === 'function') showErrorToast(tF('Describe style') + ': ' + ((err && err.message) || 'failed'));
        })
        .then(function () {
          describeBtn.disabled = false;
          describeBtn.classList.remove('is-busy');
          describeBtn.innerHTML = _describeIcon;
        });
    });

    stylesBtn.addEventListener('click', function () {
      _openStylePickerPanel(function (style) {
        if (style && style.has_image && style.image_url) {
          _skipVisionOnNextLoad = true;
          loadUrlAsImage(style.image_url);
        }
        // Stash the style's own prefix/suffix on this step so the prompt
        // step's "Edit Prompt" panel (flow-step-prompt-input.js /
        // flow-step-workflow-params.js) can pre-fill Prefix/Suffix from it —
        // this image-style picker only loads the reference image above, it
        // doesn't touch the prompt text itself.
        var pickedPrefix = (style && style.prefix) || '';
        var pickedSuffix = (style && style.suffix) || '';
        setVal(stepDef.id, 'style_prefix', pickedPrefix);
        setVal(stepDef.id, 'style_suffix', pickedSuffix);
        // Also overwrite the panel's own persisted Prefix/Suffix — picking a
        // *different* style should replace whatever was there before, not
        // leave the previous style's wording stuck (the panel's own
        // persistence is for the user's later hand-edits, not for this).
        setVal(stepDef.id, 'edit_prompt_prefix', pickedPrefix);
        setVal(stepDef.id, 'edit_prompt_suffix', pickedSuffix);
        setVal(stepDef.id, 'style_name', (style && style.name) || '');
        // A prompt_input with style_source pointing here (e.g. Style
        // Reference's "Final prompt") rebuilds itself live — same event the
        // Create style flows use.
        // The prompt step applies it on its own (_bindStyleAutoApply,
        // flow-step-prompt-input.js) — no panel to confirm.
        document.dispatchEvent(new CustomEvent('ncf-style-changed', { detail: { stepId: stepDef.id } }));
      });
    });
  }

  function _downscaleByFactor(dataUrl, factor) {
    return new Promise(function (resolve) {
      if (!factor || factor <= 1) { resolve(dataUrl); return; }
      var img = new Image();
      img.onload = function () {
        if (!img.naturalWidth || !img.naturalHeight) { resolve(dataUrl); return; }
        var w = Math.max(1, Math.round(img.naturalWidth / factor));
        var h = Math.max(1, Math.round(img.naturalHeight / factor));
        var canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        var ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high'; // best resampling the browser offers (bicubic-ish) instead of the 'low' default
        ctx.drawImage(img, 0, 0, w, h);
        var outMime = dataUrl.indexOf('image/png') === 5 ? 'image/png' : 'image/jpeg';
        resolve(canvas.toDataURL(outMime, 0.92));
      };
      img.onerror = function () { resolve(dataUrl); }; // fail open — keep the original rather than block the upload
      img.src = dataUrl;
    });
  }

  function _persistUpload(url, onDone) {
    if (!url || !url.startsWith('data:image/')) return;
    fetch('/api/images/save-upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataUrl: url, filenamePrefix: 'flow-input', subdir: 'input' })
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) { if (res && res.ok && res.url && onDone) onDone(res.url); })
      .catch(function () {});
  }

  // Re-applies the current _downscaleFactor to whatever is already loaded,
  // always starting from the untouched original(s) so switching pills never
  // compounds shrinkage (e.g. 2x then 4x should give 4x-from-original, not
  // 4x-on-top-of-2x).
  function _reprocessCurrentImages() {
    if (stepDef.multiple) {
      if (!_originals.length) return;
      Promise.all(_originals.map(function (u) { return _downscaleByFactor(u, _downscaleFactor); }))
        .then(function (resized) {
          setVal(stepDef.id, 'image_data_urls', resized);
          setVal(stepDef.id, 'image_data_url', resized[0] || '');
          showPreview(resized[0]);
          renderThumbStrip(resized);
          updateGenerateBtn();
          _persistUpload(resized[0], function (url) { setVal(stepDef.id, 'image_server_url', url); });
        });
    } else {
      if (!_singleOriginal) return;
      _downscaleByFactor(_singleOriginal, _downscaleFactor).then(function (resized) {
        setVal(stepDef.id, 'image_data_url', resized);
        showPreview(resized);
        updateGenerateBtn();
        _persistUpload(resized, function (url) { setVal(stepDef.id, 'image_server_url', url); });
      });
    }
  }

  function showPreview(dataUrl) {
    dropZone.innerHTML = '';
    previewEl = document.createElement('img');
    previewEl.className = 'nsc-image-preview';
    previewEl.id = 'nsc-ip-' + stepDef.id;
    previewEl.src = dataUrl;
    previewEl.alt = 'Selected image';
    dropZone.appendChild(previewEl);
    clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'nsc-image-clear-btn';
    clearBtn.setAttribute('aria-label', 'Remove image');
    clearBtn.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13"/></svg>';
    clearBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      clearImage();
    });
    dropZone.appendChild(clearBtn);

    var resBadge = document.createElement('span');
    resBadge.className = 'nsc-image-res-badge';
    resBadge.textContent = '…';
    dropZone.appendChild(resBadge);

    previewEl.addEventListener('load', function () {
      var w = previewEl.naturalWidth, h = previewEl.naturalHeight;
      if (!w || !h) return;
      var mp = (w * h) / 1e6;
      resBadge.textContent = w + ' × ' + h + ' (' + mp.toFixed(1) + ' MP)';
      previewEl.title = w + ' × ' + h + ' — ' + mp.toFixed(1) + ' MP';
      _currentImgW = w;
      _currentImgH = h;
      _updateDownscaleResult();
    });
  }

  function clearImage() {
    setVal(stepDef.id, 'image_data_url', '');
    setVal(stepDef.id, 'image_data_urls', []);
    fileInput.value = '';
    if (multiStripEl) { multiStripEl.remove(); multiStripEl = null; }
    dropZone.innerHTML =
      '<div class="nsc-image-drop-placeholder">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          '<rect x="3" y="3" width="18" height="18" rx="2"/>' +
          '<circle cx="8.5" cy="8.5" r="1.5"/>' +
          '<path d="M21 15l-5-5L5 21"/>' +
        '</svg>' +
        '<p>Drop image here<br><span>or click to choose</span></p>' +
      '</div>';
    _currentImgW = 0;
    _currentImgH = 0;
    _origImgW = 0;
    _origImgH = 0;
    _originals = [];
    _singleOriginal = '';
    _updateDownscaleResult();
    updateGenerateBtn();
  }

  // ── Multi-image support (opt-in via stepDef.multiple) ───────────────────
  // Several images can be selected for the same picker; the flow later runs
  // once per image (sequential queue), one output card each.
  var multiStripEl = null;

  function removeImageAt(idx) {
    var list = (getVal(stepDef.id, 'image_data_urls') || []).slice();
    list.splice(idx, 1);
    _originals.splice(idx, 1);
    if (idx === 0) {
      // The "result" readout tracks the first image's original dims — re-measure
      // against the new first original (or clear it if nothing's left).
      if (_originals[0]) {
        _measureDims(_originals[0]).then(function (d) { _origImgW = d.w; _origImgH = d.h; _updateDownscaleResult(); });
      } else {
        _origImgW = 0; _origImgH = 0;
      }
    }
    setMultiImages(list);
  }

  function renderThumbStrip(list) {
    if (multiStripEl) { multiStripEl.remove(); multiStripEl = null; }
    if (!stepDef.multiple || list.length < 2) return;

    multiStripEl = document.createElement('div');
    multiStripEl.className = 'nsc-multi-image-strip';

    var lbl = document.createElement('p');
    lbl.className = 'nsc-multi-image-label';
    lbl.textContent = list.length + ' images selected — will run one after another';
    multiStripEl.appendChild(lbl);

    var row = document.createElement('div');
    row.className = 'nsc-multi-image-row';
    list.forEach(function (url, idx) {
      var cell = document.createElement('div');
      cell.className = 'nsc-multi-image-cell';
      var imgEl = document.createElement('img');
      imgEl.src = url;
      imgEl.alt = 'Image ' + (idx + 1);
      imgEl.loading = 'lazy';
      cell.appendChild(imgEl);
      var rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'nsc-multi-image-remove';
      rm.setAttribute('aria-label', 'Remove image ' + (idx + 1));
      rm.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13"/></svg>';
      rm.addEventListener('click', function (e) { e.stopPropagation(); removeImageAt(idx); });
      cell.appendChild(rm);
      row.appendChild(cell);
    });
    multiStripEl.appendChild(row);
    wrap.appendChild(multiStripEl);
  }

  function setMultiImages(list) {
    setVal(stepDef.id, 'image_data_urls', list);
    setVal(stepDef.id, 'image_data_url', list[0] || '');
    if (!list.length) { clearImage(); return; }
    showPreview(list[0]);
    renderThumbStrip(list);
    updateGenerateBtn();
  }

  function addImages(dataUrls) {
    // Record the raw (undownscaled) originals now, in the same order they'll
    // land in image_data_urls, so a later pill change can reprocess from them.
    var wasEmpty = _originals.length === 0;
    dataUrls.forEach(function (u) { if (u) _originals.push(u); });
    if (wasEmpty && dataUrls[0]) {
      _measureDims(dataUrls[0]).then(function (d) { _origImgW = d.w; _origImgH = d.h; _updateDownscaleResult(); });
    }
    Promise.all(dataUrls.map(function (u) { return _downscaleByFactor(u, _downscaleFactor); }))
      .then(function (resized) {
        var list = (getVal(stepDef.id, 'image_data_urls') || []).slice();
        resized.forEach(function (u) {
          if (!u) return;
          var isFirstOverall = list.length === 0;
          list.push(u);
          // Persist to server so the session history stores a small URL instead of base64
          _persistUpload(u, function (url) { if (isFirstOverall) setVal(stepDef.id, 'image_server_url', url); });
        });
        setMultiImages(list);
        if (resized[0]) _maybeOpenVisionEditPanel(resized[0]);
      });
  }

  // Opt-in via stepDef.style_image_input: any image landing in this picker
  // that *didn't* come from the Styles catalog (which already carries its
  // own prefix/suffix text, see _skipVisionOnNextLoad above) has no
  // style text of its own: the previous style's wording is dropped from the
  // prompt, and the user can read this one's with "Describe style" (header
  // eye) or the Edit Prompt panel's Short/Detailed buttons.
  function _maybeOpenVisionEditPanel(dataUrl) {
    if (!stepDef.style_image_input || _skipVisionOnNextLoad) { _skipVisionOnNextLoad = false; return; }
    setVal(stepDef.id, 'style_prefix', '');
    setVal(stepDef.id, 'style_suffix', '');
    setVal(stepDef.id, 'edit_prompt_prefix', '');
    setVal(stepDef.id, 'edit_prompt_suffix', '');
    setVal(stepDef.id, 'style_name', '');
    // A previous catalog style's wording no longer belongs to this image —
    // tell a composed "Final prompt" (style_source) to drop it.
    document.dispatchEvent(new CustomEvent('ncf-style-changed', { detail: { stepId: stepDef.id } }));
  }

  function handleDataUrl(dataUrl) {
    if (!dataUrl) return;
    // In "multiple" mode addImages() already applies the downscale factor —
    // route there instead of resizing here too (would otherwise shrink twice).
    if (stepDef.multiple) { addImages([dataUrl]); return; }
    _singleOriginal = dataUrl;
    _measureDims(dataUrl).then(function (d) { _origImgW = d.w; _origImgH = d.h; _updateDownscaleResult(); });
    _downscaleByFactor(dataUrl, _downscaleFactor).then(function (resized) {
      setVal(stepDef.id, 'image_data_url', resized);
      showPreview(resized);
      updateGenerateBtn();
      // Persist to server so the session history stores a small URL instead of base64
      _persistUpload(resized, function (url) { setVal(stepDef.id, 'image_server_url', url); });
      _maybeOpenVisionEditPanel(resized);
    });
  }

  function handleFile(file) {
    if (!file || !file.type.startsWith('image/')) return;
    var reader = new FileReader();
    reader.onload = function (e) { handleDataUrl(String(e.target.result || '')); };
    reader.readAsDataURL(file);
  }

  function handleFiles(files) {
    var arr = Array.prototype.slice.call(files || []).filter(function (f) {
      return f && f.type && f.type.indexOf('image/') === 0;
    });
    if (!arr.length) return;
    if (!stepDef.multiple || arr.length === 1) { handleFile(arr[0]); return; }
    var readers = arr.map(function (f) {
      return new Promise(function (resolve) {
        var reader = new FileReader();
        reader.onload = function (e) { resolve(String(e.target.result || '')); };
        reader.onerror = function () { resolve(''); };
        reader.readAsDataURL(f);
      });
    });
    Promise.all(readers).then(function (dataUrls) { addImages(dataUrls.filter(Boolean)); });
  }

  // Load any image URL (server or data:) into this picker as the source image.
  function loadUrlAsImage(url) {
    if (!url) return;
    if (url.indexOf('data:image/') === 0) { handleDataUrl(url); return; }
    fetch(url).then(function (r) { return r.blob(); }).then(function (blob) {
      var rd = new FileReader();
      rd.onload = function (e) { handleDataUrl(String(e.target.result || '')); };
      rd.readAsDataURL(blob);
    }).catch(function () {
      // Fallback: use the URL directly so the preview at least shows.
      setVal(stepDef.id, 'image_data_url', url);
      showPreview(url);
      updateGenerateBtn();
    });
  }

  // Gather every image produced in the current session (newest steps first).
  // Only when this flow was actually launched *from* a Session — i.e.
  // pending.sessionId is set (see flow-boot.js's own "normal mode → leave
  // the default chrome" check for the same distinction). V.getActive() is
  // just "the last session you ever opened" (used by the Session hub list
  // itself, nomad_studio.js) — falling back to it here made this button
  // show up on every standalone Create/Refine/Mix flow as long as any
  // session existed anywhere, not just when actually chaining one.
  function sessionImages() {
    try {
      var V = window.NomadSession;
      if (!V) return [];
      var p = V.getPending && V.getPending();
      var bid = p && p.sessionId;
      if (!bid) return [];
      var b = V.find && V.find(bid);
      if (!b || !Array.isArray(b.steps)) return [];
      var out = [];
      b.steps.slice().reverse().forEach(function (s) {
        var imgs = (Array.isArray(s.images) && s.images.length) ? s.images : (s.imageUrl ? [s.imageUrl] : []);
        imgs.forEach(function (u) { if (u) out.push({ url: u, label: s.flowLabel || 'Step' }); });
      });
      return out;
    } catch (_) { return []; }
  }

  // Modal to choose a source image from the session's previous outputs.
  function openPrevFlowModal() {
    var imgs = sessionImages();
    if (!imgs.length) { alert('No previous images in this session yet.'); return; }

    var backdrop = document.createElement('div');
    backdrop.className = 'ncf-prevflow-modal';
    var panel = document.createElement('div');
    panel.className = 'ncf-prevflow-panel';

    var head = document.createElement('div');
    head.className = 'ncf-prevflow-head';
    head.innerHTML = '<span class="ncf-prevflow-title">Choose an image from this session</span>';
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'ncf-prevflow-close';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13"/></svg>';
    head.appendChild(closeBtn);
    panel.appendChild(head);

    var grid = document.createElement('div');
    grid.className = 'ncf-prevflow-grid';
    imgs.forEach(function (it) {
      var cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'ncf-prevflow-cell';
      cell.innerHTML =
        '<img src="' + it.url + '" alt="' + escHtml(it.label) + '" loading="lazy">' +
        '<span>' + escHtml(it.label) + '</span>';
      cell.addEventListener('click', function () { close(); loadUrlAsImage(it.url); });
      grid.appendChild(cell);
    });
    panel.appendChild(grid);

    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);

    function close() {
      if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
      document.removeEventListener('keydown', onKey);
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    closeBtn.addEventListener('click', close);
    backdrop.addEventListener('click', function (e) { if (e.target === backdrop) close(); });
    document.addEventListener('keydown', onKey);
  }

  dropZone.addEventListener('click', function () { fileInput.click(); });
  dropZone.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener('change', function () {
    if (fileInput.files && fileInput.files.length) handleFiles(fileInput.files);
  });
  dropZone.addEventListener('dragover', function (e) { e.preventDefault(); dropZone.classList.add('is-drag-over'); });
  dropZone.addEventListener('dragleave', function () { dropZone.classList.remove('is-drag-over'); });
  dropZone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropZone.classList.remove('is-drag-over');
    var files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) handleFiles(files);
  });

  // ── Right-click → Paste image ───────────────────────────────────────────
  // Reuses the tiny floating context-menu look already used for the Model
  // list's right-click "favorite" toggle (.ncf-model-ctx-menu/-item,
  // flow-model-options-panel.js) — same visual language, own local state
  // here since that one's a module-global singleton scoped to that file.
  var _pasteCtxMenuEl = null;
  function _hidePasteCtxMenu() {
    if (_pasteCtxMenuEl) { _pasteCtxMenuEl.remove(); _pasteCtxMenuEl = null; }
  }
  function _showPasteCtxMenu(x, y) {
    _hidePasteCtxMenu();
    _pasteCtxMenuEl = document.createElement('div');
    _pasteCtxMenuEl.className = 'ncf-model-ctx-menu nsc-options-exempt';
    var item = document.createElement('button');
    item.type = 'button';
    item.className = 'ncf-model-ctx-item';
    item.textContent = 'Paste image';
    item.addEventListener('click', function () {
      item.textContent = 'Pasting…';
      item.disabled = true;
      _pasteFromClipboard()
        .then(function (ok) {
          if (ok) { _hidePasteCtxMenu(); return; }
          item.textContent = 'No image in clipboard';
          setTimeout(_hidePasteCtxMenu, 1200);
        })
        .catch(function () {
          item.textContent = 'Paste failed — check permissions';
          setTimeout(_hidePasteCtxMenu, 1600);
        });
    });
    _pasteCtxMenuEl.appendChild(item);
    document.body.appendChild(_pasteCtxMenuEl);
    var rect = _pasteCtxMenuEl.getBoundingClientRect();
    _pasteCtxMenuEl.style.left = Math.min(x, window.innerWidth - rect.width - 8) + 'px';
    _pasteCtxMenuEl.style.top  = Math.min(y, window.innerHeight - rect.height - 8) + 'px';
  }
  document.addEventListener('mousedown', function (e) {
    if (_pasteCtxMenuEl && !_pasteCtxMenuEl.contains(e.target)) _hidePasteCtxMenu();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') _hidePasteCtxMenu();
  });

  // Reads an image off the system clipboard (Clipboard API — needs a secure
  // context and, in most browsers, a user gesture, which the right-click
  // + menu-item click chain already provides). Resolves false (not
  // rejects) when the clipboard simply has no image, so the caller can
  // show "No image in clipboard" instead of the generic failure message.
  function _pasteFromClipboard() {
    if (!navigator.clipboard || !navigator.clipboard.read) return Promise.resolve(false);
    return navigator.clipboard.read().then(function (items) {
      for (var i = 0; i < items.length; i++) {
        var imgType = items[i].types.filter(function (t) { return t.indexOf('image/') === 0; })[0];
        if (!imgType) continue;
        return items[i].getType(imgType).then(function (blob) {
          return new Promise(function (resolve) {
            var rd = new FileReader();
            rd.onload = function (e) { handleDataUrl(String(e.target.result || '')); resolve(true); };
            rd.onerror = function () { resolve(false); };
            rd.readAsDataURL(blob);
          });
        });
      }
      return false;
    });
  }
  dropZone.addEventListener('contextmenu', function (e) {
    e.preventDefault();
    _showPasteCtxMenu(e.clientX, e.clientY);
  });

  // Pre-load from sessionStorage (set by "send_to_refine" / upscale page)
  try {
    var stored = sessionStorage.getItem(UPSCALE_SRC_KEY) || '';
    if (stored) {
      sessionStorage.removeItem(UPSCALE_SRC_KEY);
      if (stored.startsWith('data:image/')) {
        handleDataUrl(stored);
      } else if (stored.startsWith('/') || stored.startsWith('http')) {
        fetch(stored).then(function (r) { return r.blob(); }).then(function (blob) {
          var rd = new FileReader();
          rd.onload = function (e) { handleDataUrl(String(e.target.result || '')); };
          rd.readAsDataURL(blob);
        }).catch(function () {});
      }
    }
  } catch (_) {}

  // Pre-load a whole batch (set by the "Refine" tab in a create flow's results
  // bar — sends every generated image as input to this flow in one go). Only
  // the primary source picker consumes it, and only once.
  var BATCH_SRC_KEY = 'oj-refine-batch-images-v1';
  if (stepDef.id === 'image') {
    try {
      var rawBatch = sessionStorage.getItem(BATCH_SRC_KEY) || '';
      if (rawBatch) {
        sessionStorage.removeItem(BATCH_SRC_KEY);
        var urls = [];
        try { urls = JSON.parse(rawBatch); } catch (_) { urls = []; }
        if (Array.isArray(urls) && urls.length) {
          var toDataUrl = function (u) {
            if (u.indexOf('data:image/') === 0) return Promise.resolve(u);
            return fetch(u).then(function (r) { return r.blob(); }).then(function (blob) {
              return new Promise(function (resolve) {
                var rd = new FileReader();
                rd.onload = function (e) { resolve(String(e.target.result || '')); };
                rd.onerror = function () { resolve(''); };
                rd.readAsDataURL(blob);
              });
            }).catch(function () { return ''; });
          };
          Promise.all(urls.map(toDataUrl)).then(function (dataUrls) {
            var clean = dataUrls.filter(Boolean);
            if (!clean.length) return;
            if (stepDef.multiple) addImages(clean);
            else handleDataUrl(clean[0]);
          });
        }
      }
    } catch (_) {}
  }

  // Restore from session history (set by nomad_studio.js when clicking a history row)
  try {
    if (_pendingSession && _pendingSession.data && !getVal(stepDef.id, 'image_data_url')) {
      var _d = _pendingSession.data;
      // `inputs` ({picker step id: URL}) covers every picker a flow has —
      // image1/image2 only ever knew the first two.
      var _imgSrc = (_d.inputs && _d.inputs[stepDef.id]) ||
        (stepDef.id === 'image' ? _d.image1 : (stepDef.id === 'image_2' ? _d.image2 : null));
      if (_imgSrc) {
        if (_imgSrc.startsWith('data:image/')) {
          handleDataUrl(_imgSrc);
        } else if (_imgSrc.startsWith('/') || _imgSrc.startsWith('http')) {
          fetch(_imgSrc).then(function (r) { return r.blob(); }).then(function (blob) {
            var rd = new FileReader();
            rd.onload = function (e) { handleDataUrl(String(e.target.result || '')); };
            rd.readAsDataURL(blob);
          }).catch(function () {});
        }
      }
    }
  } catch (_) {}

  // ── Image sources (Inputs / From Build / Tray / History) ───────────────
  // The thumbnail panels live at file level (ncfImageSourceItems, below), so
  // the Session workspace's Add Images panel can offer the same sources. Here
  // a pick goes through this picker's own loadUrlAsImage() — the same funnel
  // drag/drop and "From flow" use — and closes the panel.
  function _pickFromSource(url) {
    loadUrlAsImage(url);
    closeOptionsPanel();
  }

  // ── Crop panel ───────────────────────────────────────────────────────────
  // Two interaction modes, picked via an aspect-ratio slider (issue #90):
  //  - "Free" (default, _renderFreeCropStage): the original behaviour —
  //    drag/resize a rectangle over a static image, unrestricted ratio.
  //  - A locked ratio (_renderLockedCropStage): the crop WINDOW is fixed to
  //    that ratio and the user pans/zooms the IMAGE behind it instead
  //    (Instagram/Canva-style) — the inverse interaction model, so it's a
  //    separate renderer rather than a generalisation of the free one.
  // Both funnel their result through handleDataUrl() on Apply — the same
  // path every other image source (upload, tray, previous-flow) already
  // goes through, so preview/dims/server persistence/Generate-button state
  // all update for free.
  var _cropAspectPresets = [{ key: 'free', label: 'Free', hint: 'Freeform crop, no locked ratio' }]
    .concat(OUTPAINT_ASPECT_PRESETS);

  function _fillCropPanel(bodyEl) {
    var currentUrl = getVal(stepDef.id, 'image_data_url');
    if (!currentUrl) {
      var empty = document.createElement('p');
      empty.className = 'nsc-step-hint';
      empty.textContent = 'Pick an image first.';
      bodyEl.appendChild(empty);
      return;
    }

    var arRow = document.createElement('div');
    arRow.className = 'nsc-field-row nsc-field-row--compose';
    var arLbl = document.createElement('label');
    arLbl.className = 'nsc-field-label';
    arLbl.textContent = 'Aspect ratio';
    arRow.appendChild(arLbl);

    var iconsHtml = _cropAspectPresets.map(function (p, i) {
      var ic = p.icon || { vw: 18, vh: 18, rw: 16.5, rh: 16.5 };
      var tip = p.hint ? ' title="' + p.hint + '"' : '';
      return '<div class="nsc-aspect-icon-item" data-idx="' + i + '"' + tip + '>' +
        '<svg viewBox="0 0 ' + ic.vw + ' ' + ic.vh + '" width="' + ic.vw + '" height="' + ic.vh + '">' +
        '<rect x=".75" y=".75" width="' + ic.rw + '" height="' + ic.rh + '" rx="1.5"/></svg></div>';
    }).join('');
    var ticksHtml = _cropAspectPresets.map(function (p) {
      var tip = p.hint ? ' title="' + p.hint + '"' : '';
      return '<span' + tip + '>' + p.label + '</span>';
    }).join('');

    var arWidget = document.createElement('div');
    arWidget.className = 'nsc-aspect-slider-wrap';
    arWidget.innerHTML =
      '<div class="nsc-aspect-icons nsc-aspect-icons--wide" aria-hidden="true">' + iconsHtml + '</div>' +
      '<input class="nsc-aspect-slider" type="range" min="0" max="' + (_cropAspectPresets.length - 1) + '" step="1" value="0" aria-label="Aspect ratio">' +
      '<div class="nsc-aspect-ticks">' + ticksHtml + '</div>';
    arRow.appendChild(arWidget);
    bodyEl.appendChild(arRow);

    var stage = document.createElement('div');
    stage.className = 'nsc-crop-stage';
    bodyEl.appendChild(stage);

    var actions = document.createElement('div');
    actions.className = 'nsc-crop-actions';
    var applyBtn = document.createElement('button');
    applyBtn.type = 'button';
    applyBtn.className = 'nsc-crop-btn nsc-crop-btn--primary';
    applyBtn.textContent = 'Apply crop';
    var cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'nsc-crop-btn';
    cancelBtn.textContent = 'Cancel';
    actions.appendChild(cancelBtn);
    actions.appendChild(applyBtn);
    bodyEl.appendChild(actions);
    cancelBtn.addEventListener('click', closeOptionsPanel);

    var arSlider = arWidget.querySelector('.nsc-aspect-slider');
    var arIconItems = arWidget.querySelectorAll('.nsc-aspect-icon-item');
    var arTickSpans = arWidget.querySelectorAll('.nsc-aspect-ticks span');

    function renderForIdx(idx) {
      arSlider.value = idx;
      arIconItems.forEach(function (ic, i) { ic.classList.toggle('is-active', i === idx); });
      arTickSpans.forEach(function (t, i) { t.classList.toggle('is-active', i === idx); });
      stage.innerHTML = '';
      applyBtn.onclick = null;
      var preset = _cropAspectPresets[idx];
      if (preset.key === 'free') _renderFreeCropStage(stage, currentUrl, applyBtn);
      else _renderLockedCropStage(stage, currentUrl, applyBtn, preset);
    }

    arSlider.addEventListener('input', function () { renderForIdx(+arSlider.value); });
    arTickSpans.forEach(function (t, i) { t.addEventListener('click', function () { renderForIdx(i); }); });
    arIconItems.forEach(function (ic, i) { ic.addEventListener('click', function () { renderForIdx(i); }); });

    renderForIdx(0); // "Free" by default — matches today's behaviour exactly
  }

  // Free-drag rectangle over a static image — unchanged from before issue #90,
  // just parameterised so the aspect-ratio switcher above can re-invoke it.
  function _renderFreeCropStage(stage, currentUrl, applyBtn) {
    var img = document.createElement('img');
    img.className = 'nsc-crop-img';
    img.src = currentUrl;
    img.alt = 'Image to crop';
    stage.appendChild(img);

    var box = document.createElement('div');
    box.className = 'nsc-crop-box';
    ['nw', 'ne', 'sw', 'se'].forEach(function (corner) {
      var handle = document.createElement('div');
      handle.className = 'nsc-crop-handle nsc-crop-handle--' + corner;
      handle.dataset.corner = corner;
      box.appendChild(handle);
    });
    stage.appendChild(box);

    // Rect state in DISPLAYED-pixel coordinates, relative to `stage`.
    var rect = { x: 0, y: 0, w: 0, h: 0 };
    function applyRectToBox() {
      box.style.left = rect.x + 'px';
      box.style.top = rect.y + 'px';
      box.style.width = rect.w + 'px';
      box.style.height = rect.h + 'px';
    }
    function initRect() {
      var sw = stage.clientWidth, sh = stage.clientHeight;
      var iw = img.clientWidth, ih = img.clientHeight;
      var ix = (sw - iw) / 2, iy = (sh - ih) / 2;
      // Default: full image (drag from there to actually crop).
      rect = { x: ix, y: iy, w: iw, h: ih };
      applyRectToBox();
    }
    // openOptionsPanel() runs this fillFn while the panel is still
    // `hidden` (it only unhides afterwards), and a data: URL image is
    // already `.complete` synchronously — so calling initRect() straight
    // away here reads clientWidth/clientHeight off a display:none tree
    // and gets 0 every time. Deferring past the current synchronous run
    // (setTimeout, not requestAnimationFrame — rAF callbacks can be
    // withheld entirely on a backgrounded/inactive tab, and there's no
    // reason to depend on that here) runs it after the panel has actually
    // unhidden and laid out. The `load`-event path doesn't need this: by
    // the time a slower (server URL) image finishes decoding, the panel
    // has been visible for a while already.
    if (img.complete && img.naturalWidth) setTimeout(initRect, 0);
    else img.addEventListener('load', initRect, { once: true });

    // Drag the whole box to move it; drag a corner handle to resize it.
    // Clamped to the image's own displayed bounds throughout.
    function imgBounds() {
      var sw = stage.clientWidth, sh = stage.clientHeight;
      var iw = img.clientWidth, ih = img.clientHeight;
      return { x: (sw - iw) / 2, y: (sh - ih) / 2, w: iw, h: ih };
    }
    function clampRect() {
      var b = imgBounds();
      rect.w = Math.max(20, Math.min(rect.w, b.w));
      rect.h = Math.max(20, Math.min(rect.h, b.h));
      rect.x = Math.max(b.x, Math.min(rect.x, b.x + b.w - rect.w));
      rect.y = Math.max(b.y, Math.min(rect.y, b.y + b.h - rect.h));
    }

    function startDrag(e, mode, corner) {
      e.preventDefault();
      e.stopPropagation();
      var startX = e.clientX, startY = e.clientY;
      var startRect = { x: rect.x, y: rect.y, w: rect.w, h: rect.h };
      function onMove(ev) {
        var dx = ev.clientX - startX, dy = ev.clientY - startY;
        if (mode === 'move') {
          rect.x = startRect.x + dx;
          rect.y = startRect.y + dy;
        } else {
          // Resize from the opposite corner — the dragged corner tracks the pointer.
          if (corner.indexOf('e') !== -1) rect.w = startRect.w + dx;
          if (corner.indexOf('s') !== -1) rect.h = startRect.h + dy;
          if (corner.indexOf('w') !== -1) { rect.x = startRect.x + dx; rect.w = startRect.w - dx; }
          if (corner.indexOf('n') !== -1) { rect.y = startRect.y + dy; rect.h = startRect.h - dy; }
        }
        clampRect();
        applyRectToBox();
      }
      function onUp() {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
      }
      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
    }
    box.addEventListener('pointerdown', function (e) {
      if (e.target.classList.contains('nsc-crop-handle')) return; // handles have their own listener below
      startDrag(e, 'move', null);
    });
    box.querySelectorAll('.nsc-crop-handle').forEach(function (h) {
      h.addEventListener('pointerdown', function (e) { startDrag(e, 'resize', h.dataset.corner); });
    });

    applyBtn.onclick = function () {
      var b = imgBounds();
      if (!b.w || !b.h || !img.naturalWidth) { closeOptionsPanel(); return; }
      var scale = img.naturalWidth / b.w;
      var sx = (rect.x - b.x) * scale;
      var sy = (rect.y - b.y) * scale;
      var sw = rect.w * scale;
      var sh = rect.h * scale;
      var canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(sw));
      canvas.height = Math.max(1, Math.round(sh));
      var ctx = canvas.getContext('2d');
      ctx.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
      var croppedUrl = canvas.toDataURL('image/png');
      closeOptionsPanel();
      handleDataUrl(croppedUrl);
    };
  }

  // Ratio-locked crop-to-fill — the window is fixed to `preset`'s ratio and
  // the user pans/zooms the image behind it (mouse wheel to zoom, drag to
  // pan), like Instagram/Canva's crop tool. The image never leaves the
  // window uncovered: minimum zoom is the "cover" scale, and pan is clamped
  // to the image's own displayed bounds throughout, same spirit as
  // _renderFreeCropStage's clampRect() but applied to the image's offset
  // instead of a selection rectangle.
  function _renderLockedCropStage(stage, currentUrl, applyBtn, preset) {
    // Parse the exact ratio from the label ("9:16", "2.39:1"...) rather than any pixel
    // tier's w/h — sd/md/hd/uhd are rounded to a 16px grid for diffusion model use and
    // can drift a percent or two off the ratio the label actually promises.
    var ratio = (function () {
      var parts = String(preset.label || '').split(':');
      var w = parseFloat(parts[0]), h = parseFloat(parts[1]);
      return (w > 0 && h > 0) ? (w / h) : (preset.sd.w / preset.sd.h);
    }());
    var MAX_ZOOM = 4;

    var winEl = document.createElement('div');
    winEl.className = 'nsc-crop-window';
    stage.appendChild(winEl);

    var img = document.createElement('img');
    img.className = 'nsc-crop-pan-img';
    img.src = currentUrl;
    img.alt = 'Image to crop';
    img.draggable = false;
    winEl.appendChild(img);

    var winW = 0, winH = 0;       // window size, CSS px
    var coverScale = 1;           // scale at which the image exactly covers the window
    var zoom = 1;                 // user zoom on top of coverScale, >= 1
    var offX = 0, offY = 0;       // image top-left offset within the window, CSS px

    function totalScale() { return coverScale * zoom; }

    function applyTransform() {
      var s = totalScale();
      img.style.width = (img.naturalWidth * s) + 'px';
      img.style.height = (img.naturalHeight * s) + 'px';
      img.style.transform = 'translate(' + offX + 'px,' + offY + 'px)';
    }

    function clampOffset() {
      var s = totalScale();
      var dispW = img.naturalWidth * s, dispH = img.naturalHeight * s;
      offX = Math.max(winW - dispW, Math.min(0, offX));
      offY = Math.max(winH - dispH, Math.min(0, offY));
    }

    function setupOnLoad() {
      // Fit the chosen ratio into the space the stage actually has available
      // — same "still hidden while fillFn runs" issue _renderFreeCropStage
      // already works around (see its comment on initRect/setTimeout), so
      // window sizing is deferred here too.
      var maxW = stage.clientWidth || stage.parentElement.clientWidth || 360;
      var maxH = Math.round(window.innerHeight * 0.6);
      if (maxW / ratio <= maxH) { winW = maxW; winH = maxW / ratio; }
      else { winH = maxH; winW = maxH * ratio; }
      winEl.style.width = winW + 'px';
      winEl.style.height = winH + 'px';

      coverScale = Math.max(winW / img.naturalWidth, winH / img.naturalHeight);
      zoom = 1;
      var dispW = img.naturalWidth * coverScale, dispH = img.naturalHeight * coverScale;
      offX = (winW - dispW) / 2;
      offY = (winH - dispH) / 2;
      applyTransform();
    }
    if (img.complete && img.naturalWidth) setTimeout(setupOnLoad, 0);
    else img.addEventListener('load', setupOnLoad, { once: true });

    winEl.addEventListener('wheel', function (e) {
      e.preventDefault();
      if (!img.naturalWidth) return;
      var oldS = totalScale();
      var dispW = img.naturalWidth * oldS, dispH = img.naturalHeight * oldS;
      // Fraction of the currently-displayed image the window's own center
      // points at — kept stable across the zoom so the image doesn't jump.
      var fx = (winW / 2 - offX) / dispW;
      var fy = (winH / 2 - offY) / dispH;
      zoom = Math.max(1, Math.min(MAX_ZOOM, zoom * Math.pow(1.0018, -e.deltaY)));
      var newS = totalScale();
      var newDispW = img.naturalWidth * newS, newDispH = img.naturalHeight * newS;
      offX = winW / 2 - fx * newDispW;
      offY = winH / 2 - fy * newDispH;
      clampOffset();
      applyTransform();
    }, { passive: false });

    winEl.addEventListener('pointerdown', function (e) {
      e.preventDefault();
      var startX = e.clientX, startY = e.clientY;
      var startOffX = offX, startOffY = offY;
      function onMove(ev) {
        offX = startOffX + (ev.clientX - startX);
        offY = startOffY + (ev.clientY - startY);
        clampOffset();
        applyTransform();
      }
      function onUp() {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
      }
      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
    });

    applyBtn.onclick = function () {
      if (!img.naturalWidth || !winW) { closeOptionsPanel(); return; }
      var s = totalScale();
      var sx = -offX / s;
      var sy = -offY / s;
      var sw = winW / s;
      var sh = winH / s;
      var canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(sw));
      canvas.height = Math.max(1, Math.round(sh));
      var ctx = canvas.getContext('2d');
      ctx.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
      var croppedUrl = canvas.toDataURL('image/png');
      closeOptionsPanel();
      handleDataUrl(croppedUrl);
    };
  }

  // ── Side button column ───────────────────────────────────────────────────
  // issue #20: Crop/Inputs/Tray/History used to be 4 permanently-visible
  // icon buttons — collapsed into a single "⋯" trigger that opens the shared
  // options panel with those 4 as a menu (.nsc-options-menu-item, same
  // row shape as "Send to Depot"'s category list — flow-gallery.js's
  // _openSendToDepotPanel — just with an icon). Picking one calls that
  // item's own already-existing openOptionsPanel(...) call, which swaps the
  // (same, singleton) panel's content in place — Crop/Inputs/Tray/History
  // themselves are unchanged, only how you get to them is.
  function _makeSideBtn(label, svgInner, onClick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'nsc-history-btn nsc-options-trigger';
    b.setAttribute('aria-label', label);
    b.title = label;
    b.innerHTML = svgInner;
    b.addEventListener('click', onClick);
    return b;
  }

  var _pickerMoreItems = [
    {
      label: 'Crop',
      svgInner: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/></svg>',
      onClick: function () { openOptionsPanel('Crop', _fillCropPanel, { wide: true }); },
    },
  ].concat(ncfImageSourceItems().map(function (src) {
    return {
      label: src.label,
      svgInner: src.svgInner,
      onClick: function () {
        openOptionsPanel(src.title, function (body) { src.fill(body, _pickFromSource); }, { wide: true });
      },
    };
  }));

  var moreBtn = _makeSideBtn(
    'More',
    '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></svg>',
    function () {
      openOptionsPanel('More', function (body) { ncfFillOptionsMenu(body, _pickerMoreItems); });
    }
  );
  // Next to the step's own label ("SOURCE IMAGE"), same spot/pattern the
  // Prompt step's History button uses — not floating inside the drop zone.
  if (stepLabelEl) {
    var stepChevron = stepLabelEl.querySelector('.nsc-step-chevron');
    if (stepChevron) stepLabelEl.insertBefore(moreBtn, stepChevron);
    else stepLabelEl.appendChild(moreBtn);
  } else {
    wrap.insertBefore(moreBtn, wrap.firstChild);
  }

  // ── ref_type toggle (optional) ──────────────────────────────────────────
  // If the step definition includes ref_type_options, render a segmented pill
  // control so the user can specify how the reference image will be used.
  if (Array.isArray(stepDef.ref_type_options) && stepDef.ref_type_options.length) {
    var refTypeDefault = stepDef.ref_type_default || stepDef.ref_type_options[0];
    setVal(stepDef.id, 'ref_type', refTypeDefault);

    var refTypeWrap = document.createElement('div');
    refTypeWrap.className = 'ncf-ref-type-wrap';
    var refTypeLabel = document.createElement('span');
    refTypeLabel.className = 'ncf-ref-type-label';
    refTypeLabel.textContent = 'Reference';
    refTypeWrap.appendChild(refTypeLabel);

    var refTypePills = document.createElement('div');
    refTypePills.className = 'ncf-ref-type-pills';
    stepDef.ref_type_options.forEach(function (opt) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ncf-ref-type-pill' + (opt === refTypeDefault ? ' is-active' : '');
      btn.textContent = opt.charAt(0).toUpperCase() + opt.slice(1);
      btn.dataset.value = opt;
      btn.addEventListener('click', function () {
        refTypePills.querySelectorAll('.ncf-ref-type-pill').forEach(function (b) {
          b.classList.toggle('is-active', b.dataset.value === opt);
        });
        setVal(stepDef.id, 'ref_type', opt);
      });
      refTypePills.appendChild(btn);
    });
    refTypeWrap.appendChild(refTypePills);
    wrap.appendChild(refTypeWrap);
  }

  // Vision model button — opt-in: only shown when the step explicitly sets
  // has_vision_analysis: true (e.g. reference-image flows that analyse the input).
  // Refine / upscale / edit flows don't need it, so it's hidden by default.
  if (stepDef.has_vision_analysis === true) {
    var visionRow = document.createElement('div');
    visionRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin-top:10px;';
    var visionLabel = document.createElement('span');
    visionLabel.style.cssText = 'font-size:0.67rem;color:var(--muted);flex:1;';
    visionLabel.textContent = 'Vision model';
    visionRow.appendChild(visionLabel);
    visionRow.appendChild(makeVisionModelBtn());
    wrap.appendChild(visionRow);
  }

  // Optional subject text field — rendered when subject_input: true in step definition
  if (stepDef.subject_input) {
    var subjectWrap = document.createElement('div');
    subjectWrap.className = 'ncf-subject-wrap';

    var subjectLabelRow = document.createElement('div');
    subjectLabelRow.className = 'ncf-subject-label-row';

    var subjectLabel = document.createElement('label');
    subjectLabel.className = 'nsc-field-label';
    subjectLabel.setAttribute('for', 'ncf-img-subject-' + stepDef.id);
    subjectLabel.textContent = stepDef.subject_label || 'Who is the subject?';
    subjectLabelRow.appendChild(subjectLabel);

    // ── Optional "detect via vision" pair — round eye button (runs a quick
    // describe on this image and fills the subject field) + the shared
    // vision-model-picker button further right (makeVisionModelBtn,
    // flow-model-picker.js), same icon-only/currentColor treatment used
    // next to "Describe reference" in flow-step-vision-describe.js. Opt-in
    // via stepDef.subject_vision_assist (set server-side from the
    // workflow's meta — see flow_engine.py) so flows with their own
    // separate "Describe reference" step (Clothes Mix) aren't affected.
    if (stepDef.subject_vision_assist && typeof makeVisionModelBtn === 'function') {
      var subjDescribeBtn = document.createElement('button');
      subjDescribeBtn.type = 'button';
      subjDescribeBtn.className = 'nsc-history-btn';
      subjDescribeBtn.disabled = true;
      subjDescribeBtn.setAttribute('aria-label', 'Detect subject with vision');
      subjDescribeBtn.title = 'Detect subject with vision';
      // Not _VD_ICON_SVG (flow-step-vision-describe.js) — that markup has no
      // fill/stroke attributes of its own and only reads right inside the
      // full-width "Describe reference" button's own CSS. Standalone here,
      // it needs the same explicit currentColor treatment as the Advanced
      // (⋮) button's icon, or it renders solid black.
      var _SUBJ_EYE_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;flex-shrink:0"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>';
      var _SUBJ_RING_SVG = (typeof _VD_RING_SVG === 'string') ? _VD_RING_SVG :
        '<svg class="nsc-ring nsc-ring--indeterminate" viewBox="0 0 44 44" aria-hidden="true" style="width:16px;height:16px;flex-shrink:0"><circle class="nsc-ring-bg" cx="22" cy="22" r="18"/><circle class="nsc-ring-fill" cx="22" cy="22" r="18"/></svg>';
      subjDescribeBtn.innerHTML = _SUBJ_EYE_SVG;
      subjectLabelRow.appendChild(subjDescribeBtn);

      var subjVisionBtn = makeVisionModelBtn();
      subjVisionBtn.className = 'nsc-history-btn nsc-options-trigger ncf-vision-model-btn';
      subjVisionBtn.setAttribute('aria-label', 'Change vision model');
      var subjVisionName = subjVisionBtn.querySelector('.ncf-model-icon-name');
      if (subjVisionName) subjVisionName.remove();
      var subjVisionIcon = subjVisionBtn.querySelector('svg');
      if (subjVisionIcon) {
        subjVisionIcon.setAttribute('fill', 'none');
        subjVisionIcon.setAttribute('stroke', 'currentColor');
        subjVisionIcon.setAttribute('stroke-width', '1.5');
        subjVisionIcon.setAttribute('stroke-linecap', 'round');
        subjVisionIcon.setAttribute('stroke-linejoin', 'round');
      }
      subjectLabelRow.appendChild(subjVisionBtn);

      (function () {
        function _syncSubjDescribeBtn() {
          subjDescribeBtn.disabled = !getVal(stepDef.id, 'image_data_url');
        }
        _syncSubjDescribeBtn();
        var _pollInterval = setInterval(function () {
          if (!subjDescribeBtn.isConnected) { clearInterval(_pollInterval); return; }
          _syncSubjDescribeBtn();
        }, 500);

        subjDescribeBtn.addEventListener('click', async function () {
          var dataUrl = getVal(stepDef.id, 'image_data_url') || '';
          if (!dataUrl) return;
          var iconEl = subjDescribeBtn.querySelector('svg');
          if (iconEl) iconEl.outerHTML = _SUBJ_RING_SVG;
          subjDescribeBtn.disabled = true;
          try {
            var res = await fetch('/api/models/chat/describe-image', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                imageDataUrl: dataUrl,
                describeType: 'prompt',
                describeScope: 'full',
                describeFormat: 'paragraph',
                forceRefresh: true,
                systemPrompt: stepDef.subject_vision_assist.system_prompt || undefined,
              }),
            });
            var data = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || 'Describe failed');
            var desc = String(data.description || '').trim();
            if (desc) {
              subjectInput.value = desc;
              setVal(stepDef.id, 'subject', desc);
              document.dispatchEvent(new CustomEvent('ncf-subject-blur', {
                detail: { stepId: stepDef.id, value: desc }
              }));
            }
          } catch (err) {
            if (typeof showErrorToast === 'function') showErrorToast(err.message || 'Could not detect subject');
          } finally {
            var ringEl = subjDescribeBtn.querySelector('svg');
            if (ringEl) ringEl.outerHTML = _SUBJ_EYE_SVG;
            _syncSubjDescribeBtn();
          }
        });
      }());
    }

    subjectWrap.appendChild(subjectLabelRow);

    var subjectInput = document.createElement('input');
    subjectInput.type = 'text';
    subjectInput.className = 'nsc-input ncf-subject-input';
    subjectInput.id = 'ncf-img-subject-' + stepDef.id;
    subjectInput.placeholder = stepDef.subject_placeholder || 'e.g. woman, man, person…';
    // Session-restore only applies to the primary subject field (id "image")
    // — a second subject_input step (e.g. image_2's optional clothing
    // description) has no matching key in old session snapshots, and
    // restoring the person's subject text into a clothing field would just
    // be wrong.
    var _savedSubject = (stepDef.id === 'image' && _pendingSession && _pendingSession.data && _pendingSession.data.subject) || '';
    subjectInput.value = _savedSubject || stepDef.subject_default || '';
    if (subjectInput.value) setVal(stepDef.id, 'subject', subjectInput.value);
    subjectInput.addEventListener('input', function () {
      setVal(stepDef.id, 'subject', subjectInput.value.trim());
    });
    // On blur (not every keystroke — that'd re-interpolate mid-typing) tell
    // any prompt_input step with a {{subject}}-templated preset to refresh
    // its text — see flow-step-prompt-input.js.
    subjectInput.addEventListener('blur', function () {
      document.dispatchEvent(new CustomEvent('ncf-subject-blur', {
        detail: { stepId: stepDef.id, value: subjectInput.value.trim() }
      }));
    });
    subjectWrap.appendChild(subjectInput);

    // ── Prompt presets, moved here from the prompt_input step's own card ──
    // (see flow-step-prompt-input.js) — choosing the base wording logically
    // comes right after naming the subject, before "Describe reference",
    // not sandwiched between the vision step and the final textarea below.
    // Rendered here purely from stepDef metadata (available up-front via
    // allSteps, regardless of render order); the actual apply logic lives
    // on the prompt step and is invoked through window._ncfPromptPresetSteps
    // (populated by the time this button can actually be clicked).
    // Only the primary subject step (id "image") shows this — a second
    // subject_input-style field (e.g. image_2's clothing description) would
    // otherwise render the exact same Presets button a second time.
    var _presetStepDef = (stepDef.id === 'image' && typeof allSteps !== 'undefined' && Array.isArray(allSteps))
      ? allSteps.find(function (s) { return s.type === 'prompt_input' && Array.isArray(s.presets) && s.presets.length; })
      : null;
    if (_presetStepDef) {
      var subjPresetWrap = document.createElement('div');
      subjPresetWrap.className = 'nsc-preset-wrap nsc-preset-wrap--engine ncf-subject-preset-wrap';
      var subjPresetBtn = document.createElement('button');
      subjPresetBtn.type = 'button';
      subjPresetBtn.className = 'nsc-preset-btn nsc-preset-btn--engine';
      subjPresetBtn.innerHTML =
        '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>' +
        '<line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>' +
        '<line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>' +
        '<span>' + escHtml(_presetStepDef.presets_label || 'Presets') + '</span>';
      subjPresetBtn.classList.add('nsc-options-trigger');
      subjPresetBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        var reg = window._ncfPromptPresetSteps && window._ncfPromptPresetSteps[_presetStepDef.id];
        if (!reg || !reg.choose) return;
        var promptTa = document.getElementById('ncf-input-' + _presetStepDef.id);
        _openPromptPresetsPanel(_presetStepDef.presets_label || 'Presets', _presetStepDef.presets, reg.choose,
          promptTa ? promptTa.value : '');
      });

      subjPresetWrap.appendChild(subjPresetBtn);
      subjectWrap.appendChild(subjPresetWrap);
    }

    // ── Pose picker — only for flows whose prompt carries the "Match the
    // pose from Picture 1…" sentence (Clothes Mix). See NCF_POSE_* in
    // flow-step-prompt-input.js for how the pick lands in the prompt.
    var _hasPoseSentence = stepDef.id === 'image' && typeof allSteps !== 'undefined' && Array.isArray(allSteps) &&
      allSteps.some(function (s) {
        if (s.type !== 'prompt_input' || typeof NCF_POSE_FROM_PICTURE === 'undefined') return false;
        var texts = [s.default].concat((s.presets || []).map(function (p) { return typeof p === 'object' ? p.text : p; }));
        return texts.some(function (x) { return x && String(x).indexOf(NCF_POSE_FROM_PICTURE) !== -1; });
      });
    if (_hasPoseSentence) subjectWrap.appendChild(_ncfBuildPoseButton(stepDef));

    wrap.appendChild(subjectWrap);
  }

  // Optional "zone color" select — rendered when zone_picker: true (only
  // MultiComposer, mix.multi_composer). Says which colored rectangle
  // (drawn on the flow's background via region_annotate's rectangle mode)
  // this reference image fills — read by the zone_prompt_builder step to
  // assemble "place the subject from <imageN> in the {color} area" text.
  if (stepDef.zone_picker) {
    var zoneWrap = document.createElement('div');
    zoneWrap.className = 'ncf-subject-wrap';

    var zoneLabel = document.createElement('label');
    zoneLabel.className = 'nsc-field-label';
    zoneLabel.setAttribute('for', 'ncf-img-zone-' + stepDef.id);
    zoneLabel.textContent = 'Goes in zone color';
    zoneWrap.appendChild(zoneLabel);

    var zoneSelectWrap = document.createElement('div');
    zoneSelectWrap.className = 'nsc-select-wrapper';
    var zoneSelect = document.createElement('select');
    zoneSelect.className = 'nsc-select';
    zoneSelect.id = 'ncf-img-zone-' + stepDef.id;
    var zoneNoneOpt = document.createElement('option');
    zoneNoneOpt.value = '';
    zoneNoneOpt.textContent = '— pick a color —';
    zoneSelect.appendChild(zoneNoneOpt);
    (stepDef.zone_colors || []).forEach(function (c) {
      var opt = document.createElement('option');
      opt.value = c.value;
      opt.textContent = c.label || c.value;
      zoneSelect.appendChild(opt);
    });
    var _savedZone = getVal(stepDef.id, 'zone_color') || '';
    if (_savedZone) zoneSelect.value = _savedZone;
    zoneSelect.addEventListener('change', function () {
      setVal(stepDef.id, 'zone_color', zoneSelect.value);
    });
    var zoneChev = document.createElement('span');
    zoneChev.className = 'nsc-select-chevron';
    zoneChev.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>';
    zoneSelectWrap.appendChild(zoneSelect);
    zoneSelectWrap.appendChild(zoneChev);
    zoneWrap.appendChild(zoneSelectWrap);

    wrap.appendChild(zoneWrap);
  }

  // Registry so a result card's "Use as input" button (flow-gallery.js
  // addToFeed) can feed a finished output straight back into this picker
  // without the user having to drag/drop or re-upload it by hand — same
  // loadUrlAsImage() the "From flow" grid already uses.
  window._ncfImagePickers = window._ncfImagePickers || {};
  window._ncfImagePickers[stepDef.id] = { loadUrlAsImage: loadUrlAsImage, wrap: wrap };
}

// ── Image sources, shared ──────────────────────────────────────────────────
// An image picker's ⋯ menu and the Session workspace's Add Images panel
// (nomad_studio.js) offer the same places to take an image from. Each item's
// fill(bodyEl, onPick) builds its panel and calls onPick(url) on a click; the
// caller decides what a pick does (load it into the picker, or add it to the
// session as an "Imported image" step).
function ncfImageSourceItems() {
  var t = _ncfPoseT; // generic NomadI18n.t wrapper, despite the name
  return [
    {
      key: 'inputs',
      label: 'Previously used inputs',
      title: 'Inputs',
      svgInner: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
      fill: function (body, onPick) {
        ncfFillThumbGrid(body, '/api/images/inputs?limit=20', 'No previously used reference images yet.', onPick);
      },
    },
    {
      key: 'build',
      label: t('flow.fromBuild.menu', 'From Build'),
      title: t('flow.fromBuild.panelTitle', 'From Build'),
      svgInner: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12"/></svg>',
      fill: ncfFillBuildPanel,
    },
    {
      key: 'tray',
      label: 'From tray',
      title: 'Tray',
      svgInner: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20M2 12v8a2 2 0 002 2h16a2 2 0 002-2v-8M2 12l3-9h14l3 9"/></svg>',
      fill: function (body, onPick) {
        ncfFillThumbGrid(body, '/api/images/tray', 'Tray is empty.', onPick);
      },
    },
    {
      key: 'history',
      label: 'Recent generations',
      title: 'History',
      svgInner: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
      fill: function (body, onPick) {
        ncfFillThumbGrid(body, '/api/images?limit=20', 'No generated images yet.', onPick);
      },
    },
  ];
}

// A list of menu rows (icon + label) in a panel body — the ⋯ menu's shape.
function ncfFillOptionsMenu(bodyEl, items) {
  var list = document.createElement('div');
  list.className = 'nsc-options-menu';
  items.forEach(function (item) {
    var row = document.createElement('button');
    row.type = 'button';
    row.className = 'nsc-options-menu-item';
    row.innerHTML = '<span class="nsc-options-menu-item-icon">' + item.svgInner + '</span><span>' + item.label + '</span>';
    row.addEventListener('click', item.onClick);
    list.appendChild(row);
  });
  bodyEl.appendChild(list);
}

// Inputs / Tray / History: every endpoint returns
// {images:[{url, thumb_url, filename}]}, so one grid renders all three.
function ncfFillThumbGrid(bodyEl, fetchUrl, emptyMsg, onPick) {
  var loading = document.createElement('p');
  loading.className = 'nsc-step-hint';
  loading.textContent = 'Loading…';
  bodyEl.appendChild(loading);

  fetch(fetchUrl)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var images = (data && Array.isArray(data.images)) ? data.images : [];
      bodyEl.innerHTML = '';
      if (!images.length) {
        var empty = document.createElement('p');
        empty.className = 'nsc-step-hint';
        empty.textContent = emptyMsg;
        bodyEl.appendChild(empty);
        return;
      }
      var grid = document.createElement('div');
      grid.className = 'nit-tray-grid';
      images.forEach(function (img) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nsc-tray-strip-thumb';
        btn.title = img.filename || '';
        var imgEl = document.createElement('img');
        imgEl.src = img.thumb_url || img.url;
        imgEl.alt = img.filename || '';
        imgEl.loading = 'lazy';
        btn.appendChild(imgEl);
        btn.addEventListener('click', function () { onPick(img.url); });
        grid.appendChild(btn);
      });
      bodyEl.appendChild(grid);
    })
    .catch(function () {
      bodyEl.innerHTML = '';
      var err = document.createElement('p');
      err.className = 'nsc-step-hint';
      err.textContent = 'Failed to load images.';
      bodyEl.appendChild(err);
    });
}

// From Build (issue #21): Build's Characters and Backgrounds, one titled
// section each (same layout as the Pose panel's categories). Their images
// live at a guessed /static/images/<kind>/<keyword>.png (the Library does the
// same) — an entry with no picture yet just drops out when its <img> fails.
// In a Mix each slot has its own picker: background in slot 1, characters in
// the next ones.
// onPick(url, {kind, keyword, name}). onlyKind ('characters' / 'backgrounds')
// shows just that section, for the result cards' "Send to Character /
// Background" (flow-gallery.js _openSendToBuildPanel), which picks one whose
// image to replace: there an entry with no picture stays, as an empty tile —
// giving it one is the point. The panel appends to bodyEl and leaves anything
// already in it alone.
function ncfFillBuildPanel(bodyEl, onPick, onlyKind) {
  var t = _ncfPoseT;
  var loading = document.createElement('p');
  loading.className = 'nsc-step-hint';
  loading.textContent = t('flow.fromBuild.loading', 'Loading…');
  bodyEl.appendChild(loading);

  var kinds = [
    { key: 'characters', title: t('flow.fromBuild.characters', 'Characters') },
    { key: 'backgrounds', title: t('flow.fromBuild.backgrounds', 'Backgrounds') },
  ].filter(function (k) { return !onlyKind || k.key === onlyKind; });
  // Cache-buster for the thumbnails: an image replaced from here keeps its
  // file name (<keyword>.png), and the browser would show the old one.
  var bust = '?v=' + Date.now();
  Promise.all(kinds.map(function (k) {
    return fetch('/api/' + k.key).then(function (r) { return r.json(); })
      .then(function (data) { return (data && data[k.key]) || []; });
  })).then(function (lists) {
    loading.remove();
    if (!lists.some(function (l) { return l.length; })) {
      var empty = document.createElement('p');
      empty.className = 'nsc-step-hint';
      empty.textContent = t('flow.fromBuild.empty', 'Nothing in Build yet. Add Characters or Backgrounds there first.');
      bodyEl.appendChild(empty);
      return;
    }
    kinds.forEach(function (k, i) {
      if (!lists[i].length) return;
      var block = document.createElement('div');
      block.className = 'nsc-param-block ncf-build-block';
      var title = document.createElement('p');
      title.className = 'nsc-param-title';
      title.textContent = k.title;
      block.appendChild(title);
      var grid = document.createElement('div');
      grid.className = 'nit-tray-grid ncf-build-grid';
      lists[i].forEach(function (item) {
        var url = '/static/images/' + k.key + '/' + encodeURIComponent(item.keyword) + '.png';
        var name = String(item.keyword || '').replace(/_/g, ' ');
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nsc-tray-strip-thumb ncf-build-thumb';
        btn.title = item.description || name;
        var imgEl = document.createElement('img');
        imgEl.src = url + bust;
        imgEl.alt = name;
        imgEl.loading = 'lazy';
        imgEl.addEventListener('error', function () {
          if (onlyKind) { imgEl.remove(); btn.classList.add('ncf-build-thumb--empty'); }
          else btn.remove();
        });
        var cap = document.createElement('span');
        cap.className = 'ncf-build-thumb-name';
        cap.textContent = name;
        btn.appendChild(imgEl);
        btn.appendChild(cap);
        btn.addEventListener('click', function () {
          onPick(url + bust, { kind: k.key, keyword: item.keyword, name: name });
        });
        grid.appendChild(btn);
      });
      block.appendChild(grid);
      bodyEl.appendChild(block);
    });
  }).catch(function () {
    loading.remove();
    var err = document.createElement('p');
    err.className = 'nsc-step-hint';
    err.textContent = t('flow.fromBuild.error', 'Could not load Build.');
    bodyEl.appendChild(err);
  });
}

// ── Pose picker (Clothes Mix) ──────────────────────────────────────────────
var _ncfPosePresetsPromise = null;
function _ncfLoadPosePresets() {
  if (!_ncfPosePresetsPromise) {
    _ncfPosePresetsPromise = fetch('/static/data/pose_presets.json')
      .then(function (r) { return r.json(); })
      .catch(function () { _ncfPosePresetsPromise = null; return { categories: [] }; });
  }
  return _ncfPosePresetsPromise;
}

function _ncfPoseT(key, fallback) {
  return (window.NomadI18n && typeof window.NomadI18n.t === 'function') ? window.NomadI18n.t(key, fallback) : fallback;
}

// Per-language label objects ({en, es, zh, ko}) — same "not ready yet → en"
// rule as NomadI18n.t().
function _ncfPoseText(obj) {
  if (!obj || typeof obj !== 'object') return String(obj || '');
  var I = window.NomadI18n;
  var id = I && typeof I.getLanguage === 'function' ? I.getLanguage() : 'en';
  var lang = I && Array.isArray(I.LANGUAGES) ? I.LANGUAGES.filter(function (l) { return l.id === id; })[0] : null;
  if (!lang || !lang.ready) id = 'en';
  return obj[id] || obj.en || '';
}

function _ncfBuildPoseButton(stepDef) {
  var current = null; // { id, label, snippet } or null = from Picture 1

  var poseWrap = document.createElement('div');
  poseWrap.className = 'nsc-preset-wrap nsc-preset-wrap--engine ncf-subject-pose-wrap';
  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'nsc-preset-btn nsc-preset-btn--engine nsc-options-trigger';
  var btnText = document.createElement('span');
  btn.innerHTML =
    '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="12" cy="4.5" r="2"/><path d="M12 7v7M8 22l4-8 4 8M6 10l6-2 6 2"/></svg>';
  btn.appendChild(btnText);

  function refreshLabel() {
    btnText.textContent = _ncfPoseT('flow.pose.button', 'Pose') + ': ' +
      (current ? _ncfPoseText(current.label) : _ncfPoseT('flow.pose.fromPicture', 'From Picture 1'));
  }
  refreshLabel();

  function choose(preset) {
    current = preset;
    refreshLabel();
    setVal(stepDef.id, 'pose', preset ? preset.id : '');
    document.dispatchEvent(new CustomEvent('ncf-pose-changed', {
      detail: { id: preset ? preset.id : '', snippet: preset ? preset.snippet : '' }
    }));
  }

  function makeOption(preset, list) {
    var active = (current ? current.id : '') === (preset ? preset.id : '');
    var opt = document.createElement('button');
    opt.type = 'button';
    opt.className = 'nsc-quality-btn' + (active ? ' is-active' : '');
    opt.setAttribute('role', 'radio');
    opt.setAttribute('aria-checked', active ? 'true' : 'false');
    var copy = document.createElement('span');
    copy.className = 'nsc-quality-copy';
    var strong = document.createElement('strong');
    strong.textContent = preset ? _ncfPoseText(preset.label) : _ncfPoseT('flow.pose.fromPicture', 'From Picture 1');
    var small = document.createElement('small');
    small.textContent = preset ? preset.snippet : _ncfPoseT('flow.pose.fromPictureHint', 'Keep the pose the subject already has');
    copy.appendChild(strong);
    copy.appendChild(small);
    var dot = document.createElement('span');
    dot.className = 'nsc-quality-dot';
    opt.appendChild(dot);
    opt.appendChild(copy);
    opt.addEventListener('click', function () {
      choose(preset);
      document.querySelectorAll('.ncf-pose-list .nsc-quality-btn').forEach(function (b) {
        b.classList.remove('is-active');
        b.setAttribute('aria-checked', 'false');
      });
      opt.classList.add('is-active');
      opt.setAttribute('aria-checked', 'true');
    });
    list.appendChild(opt);
  }

  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    openOptionsPanel(_ncfPoseT('flow.pose.panelTitle', 'Pose'), function (body) {
      var first = document.createElement('div');
      first.className = 'nsc-quality-list ncf-pose-list';
      first.setAttribute('role', 'radiogroup');
      makeOption(null, first);
      body.appendChild(first);

      _ncfLoadPosePresets().then(function (data) {
        (data.categories || []).forEach(function (cat) {
          var block = document.createElement('div');
          block.className = 'nsc-param-block';
          block.style.marginTop = '1rem';
          var title = document.createElement('p');
          title.className = 'nsc-param-title';
          title.textContent = _ncfPoseText(cat.name);
          block.appendChild(title);
          var list = document.createElement('div');
          list.className = 'nsc-quality-list ncf-pose-list';
          list.setAttribute('role', 'radiogroup');
          (cat.presets || []).forEach(function (p) { makeOption(p, list); });
          block.appendChild(list);
          body.appendChild(block);
        });
      });
    });
  });

  poseWrap.appendChild(btn);
  return poseWrap;
}

// ── lettering_builder ──────────────────────────────────────────────────────
