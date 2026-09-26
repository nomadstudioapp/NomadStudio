'use strict';
// Gallery + lightbox: _extractIdgBboxes, openLightbox, closeLightbox, navigateLightbox, addToFeed, showResultActions

// A card's imgUrl is normally '/api/images/<filename>' (see saveFlowImage,
// flow-render-all.js) once the result has actually been saved server-side —
// extracts the filename so the card's own favorite/diamond buttons can call
// api.updateImageMeta the same way Album's Images mode does. Returns null
// for a raw (unsaved) ComfyUI temp URL, where there's nothing to persist to.
function _filenameFromImageUrl(url) {
  var m = /^\/api\/images\/([^?]+)/.exec(String(url || ''));
  return m ? decodeURIComponent(m[1]) : null;
}

function _extractIdgBboxes(card) {
  var ta = card && card.querySelector('.nss-card-prompt');
  if (!ta || !ta.value) return null;
  try {
    var obj = JSON.parse(ta.value);
    var els = obj.compositional_deconstruction && obj.compositional_deconstruction.elements;
    if (!Array.isArray(els) || !els.length) return null;
    var bboxes = [];
    els.forEach(function (e) {
      if (Array.isArray(e.bbox) && e.bbox.length === 4) {
        bboxes.push({ type: e.type || 'obj', bbox: e.bbox });
      }
    });
    return bboxes.length ? bboxes : null;
  } catch (_) { return null; }
}

// Position the bbox canvas exactly over the displayed image.
function _positionBboxCanvas() {
  if (!lightboxBboxCanvas || !lightboxImgEl) return;
  var imgR = lightboxImgEl.getBoundingClientRect();
  var parR = lightboxBboxCanvas.parentElement.getBoundingClientRect();
  lightboxBboxCanvas.style.left = (imgR.left - parR.left) + 'px';
  lightboxBboxCanvas.style.top  = (imgR.top  - parR.top)  + 'px';
  lightboxBboxCanvas.width  = Math.round(imgR.width);
  lightboxBboxCanvas.height = Math.round(imgR.height);
}

// Draw current bboxes on the overlay canvas.
function _drawLightboxBboxes() {
  if (!lightboxBboxCanvas || !_lbBboxes || !_lbBboxes.length) return;
  _positionBboxCanvas();
  var ctx = lightboxBboxCanvas.getContext('2d');
  if (!ctx) return;
  var W = lightboxBboxCanvas.width, H = lightboxBboxCanvas.height;
  if (!W || !H) return;
  ctx.clearRect(0, 0, W, H);
  // bbox format: [y_min, x_min, y_max, x_max] — coordinate space always 0-1000 on both axes.
  // Canvas W×H already reflects the image's actual aspect ratio, so scale linearly.
  var COLORS = { obj: '#3b82f6', text: '#f59e0b', bg: '#10b981' };
  _lbBboxes.forEach(function (el) {
    var b = el.bbox;  // [y_min, x_min, y_max, x_max]
    var color = COLORS[el.type] || '#888888';
    var cx = (b[1] / 1000) * W;           // x_min
    var cy = (b[0] / 1000) * H;           // y_min
    var cw = ((b[3] - b[1]) / 1000) * W;  // x_max - x_min
    var ch = ((b[2] - b[0]) / 1000) * H;  // y_max - y_min
    ctx.fillStyle   = color + '18';
    ctx.strokeStyle = color + 'bb';
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    ctx.rect(cx, cy, cw, ch);
    ctx.fill();
    ctx.stroke();
  });
}

// Tombstones a card's sessionImages entry on delete instead of splicing it
// out — splicing would shift every later index, and other cards' lightbox
// click-handlers already closed over their original (now-stale) index.
function _removeSessionImageForCard(card) {
  var i = card && card._sessionImgIdx;
  var url = (typeof i === 'number' && sessionImages[i]) ? sessionImages[i].url : '';
  if (typeof i === 'number' && sessionImages[i]) sessionImages[i] = null;
  // The Session's own step keeps its own copy of the output URLs, so a
  // deletion here has to reach it too — otherwise the Steps panel goes on
  // showing a card built around an image that's no longer in the feed.
  // No-op on a standalone flow page (no session holds this URL).
  if (url && window.NomadSession && typeof window.NomadSession.removeImages === 'function') {
    try { window.NomadSession.removeImages([url]); } catch (_) {}
  }
  // Without this, the localStorage "recent sessions" history entry
  // (oj-create-sessions-history-v1) keeps whatever image list the last
  // *generation* wrote — a delete never touched it — so a plain page reload
  // resumed from that stale entry (_readPendingSession's reload-resume path)
  // and the deleted image came right back. saveSessionSnapshot() rebuilds
  // that entry from the live sessionImages array, which already excludes
  // the tombstoned slot set just above.
  if (typeof saveSessionSnapshot === 'function') saveSessionSnapshot();
}

// Tombstoned (deleted) slots are `null` — anything that assumed "the last
// entry" or "the entry at index N" was always a live object needs this
// instead of indexing sessionImages directly.
function _lastValidSessionImageIdx() {
  for (var i = sessionImages.length - 1; i >= 0; i--) { if (sessionImages[i]) return i; }
  return -1;
}

function openLightbox(idx) {
  if (!lightboxEl || !sessionImages.length) return;
  idx = Math.max(0, Math.min(idx, sessionImages.length - 1));
  // Skip tombstoned (deleted) entries — prefer later images, fall back earlier.
  if (!sessionImages[idx]) {
    var fwd = sessionImages.slice(idx).findIndex(function (e) { return e; });
    if (fwd !== -1) { idx = idx + fwd; }
    else {
      var back = -1;
      for (var bi = idx - 1; bi >= 0; bi--) { if (sessionImages[bi]) { back = bi; break; } }
      if (back === -1) return; // nothing left to show
      idx = back;
    }
  }
  lightboxCursor = idx;
  var entry = sessionImages[lightboxCursor];
  lightboxImgEl.src = entry.url;
  _lbBboxes = entry.bboxes || null;
  if (lightboxBboxCanvas) {
    lightboxBboxCanvas.classList.remove('is-visible');
    var ctx = lightboxBboxCanvas.getContext('2d');
    if (ctx) ctx.clearRect(0, 0, lightboxBboxCanvas.width, lightboxBboxCanvas.height);
  }
  if (lightboxCounter) lightboxCounter.textContent = (lightboxCursor + 1) + ' / ' + sessionImages.length;
  if (lightboxPromptEl) {
    var _lbPrompt = (entry.prompt || '').trim();
    lightboxPromptEl.textContent = _lbPrompt;
    lightboxPromptEl.hidden = !_lbPrompt;
  }
  if (lightboxPrevBtn) lightboxPrevBtn.disabled = lightboxCursor === 0;
  if (lightboxNextBtn) lightboxNextBtn.disabled = lightboxCursor === sessionImages.length - 1;
  // Reparent straight onto <body> before showing it. On a session-native
  // mount the lightbox lives nested inside .nsc-main, which sets its own
  // `position: relative; z-index: 1` — that turns .nsc-main into a stacking
  // context of its own, and everything inside it (including this lightbox's
  // z-index: 9000) gets compared against OTHER STACKING CONTEXTS only at
  // .nsc-main's rank (1), not 9000. The session topbar sits outside
  // .nsc-main at z-index: 2, so its "close flow" button — which happens to
  // sit in the exact same top-right corner as the lightbox's own close
  // button — painted on top of it, hiding it completely. Moving the
  // lightbox to be a direct child of <body> escapes that trap for good,
  // on every page (standalone or session-embedded) — same pattern any
  // portal-style overlay uses. Idempotent: a no-op once already there.
  if (lightboxEl.parentElement !== document.body) document.body.appendChild(lightboxEl);
  lightboxEl.removeAttribute('hidden');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  if (!lightboxEl) return;
  lightboxEl.setAttribute('hidden', '');
  lightboxImgEl.src = '';
  _lbBboxes = null;
  if (lightboxBboxCanvas) lightboxBboxCanvas.classList.remove('is-visible');
  if (lightboxPromptEl) { lightboxPromptEl.textContent = ''; lightboxPromptEl.hidden = true; }
  document.body.style.overflow = '';
}

function navigateLightbox(dir) {
  var next = lightboxCursor + dir;
  if (next >= 0 && next < sessionImages.length) openLightbox(next);
}

if (lightboxCloseBtn) lightboxCloseBtn.addEventListener('click', closeLightbox);
if (lightboxPrevBtn)  lightboxPrevBtn.addEventListener('click',  function () { navigateLightbox(-1); });
if (lightboxNextBtn)  lightboxNextBtn.addEventListener('click',  function () { navigateLightbox(1); });

// Bbox hover — draw composition overlay when hovering the image
if (lightboxImgEl) {
  lightboxImgEl.addEventListener('mouseenter', function () {
    if (!_lbBboxes || !lightboxBboxCanvas) return;
    _drawLightboxBboxes();
    lightboxBboxCanvas.classList.add('is-visible');
  });
  lightboxImgEl.addEventListener('mouseleave', function () {
    if (lightboxBboxCanvas) lightboxBboxCanvas.classList.remove('is-visible');
  });
  // Re-position canvas after each image load (handles cached and uncached images)
  lightboxImgEl.addEventListener('load', function () {
    if (_lbBboxes && lightboxBboxCanvas) _positionBboxCanvas();
  });
}
if (lightboxEl) {
  lightboxEl.addEventListener('click', function (e) {
    if (!e.target.closest('.nsc-lightbox-inner, #nsc-lightbox-img, .nsc-lightbox-nav, .nsc-lightbox-close, .nsc-lightbox-counter')) {
      closeLightbox();
    }
  });
}
document.addEventListener('keydown', function (e) {
  if (!lightboxEl || lightboxEl.hasAttribute('hidden')) return;
  if (e.key === 'Escape')     closeLightbox();
  if (e.key === 'ArrowLeft')  navigateLightbox(-1);
  if (e.key === 'ArrowRight') navigateLightbox(1);
});

function addToFeed(imgUrl, idx, card, params, beforeUrl) {
  // If no placeholder card was passed, create a fresh one. Note: this fresh
  // card has no real _genStartTime (it's created right now, not when the
  // generation actually started) — used e.g. when restoring past images from
  // session history, where there's no live generation to time.
  var _hadRealCard = !!card;
  if (!card) {
    card = addGeneratingCard(idx);
  }

  card.setAttribute('data-status', 'done');
  // A card that started life as an editable prompt-editor placeholder
  // (buildPromptCard, e.g. Story/Scenes batches) carries a `data-prompt-card`
  // marker so renderPromptCards() knows to clear it out when a *new* batch of
  // blank placeholders is about to be drawn. Once this card actually has a
  // finished result in it, that marker is stale and must go — otherwise the
  // next continue-story/scenes round's renderPromptCards() clears its own new
  // placeholders via that exact selector and wipes every already-completed
  // scene from a previous round right along with them (they're still sitting
  // in the same results grid, just done).
  card.removeAttribute('data-prompt-card');
  var footerDot = card.querySelector('.nss-card-status-dot');
  var footerLbl = card.querySelector('.nss-card-status-label');
  if (footerDot) footerDot.setAttribute('data-status', 'done');
  if (footerLbl) footerLbl.textContent = 'done';

  // "Apply parameters" — reuse the params that produced this result.
  var _cardPromptStr = '';
  if (params && typeof params === 'object' && Object.keys(params).length) {
    card._params = params;

    // Show the prompt that produced this result (read-only) if not already shown.
    var promptStr = params.prompt || params.positive || params.promptText || '';
    if (!promptStr && params.prompts) {
      var _pk = Object.keys(params.prompts)[0];
      if (_pk) promptStr = params.prompts[_pk];
    }
    _cardPromptStr = promptStr || '';
    if (promptStr) {
      var existingTa = card.querySelector('.nss-card-prompt');
      if (existingTa) {
        existingTa.value = promptStr;
      } else if (!card.querySelector('.nss-card-prompt-used')) {
        var pUsed = document.createElement('div');
        pUsed.className = 'nss-card-prompt-used';
        pUsed.title = promptStr;
        pUsed.textContent = promptStr;
        var footerForPrompt = card.querySelector('.nss-card-footer');
        if (footerForPrompt) card.insertBefore(pUsed, footerForPrompt);
        else card.appendChild(pUsed);
      }
    }

    var footer = card.querySelector('.nss-card-footer');
    if (footer && !footer.querySelector('.nss-card-apply-params')) {
      var applyBtn = document.createElement('button');
      applyBtn.type = 'button';
      applyBtn.className = 'nss-card-apply-params';
      applyBtn.title = 'Apply these parameters';
      applyBtn.setAttribute('aria-label', 'Apply these parameters');
      applyBtn.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M4 4v6h6M20 20v-6h-6"/><path d="M20 9a8 8 0 0 0-14-3L4 8M4 15a8 8 0 0 0 14 3l2-2"/>' +
        '</svg><span>Apply params</span>';
      applyBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        if (typeof applyParamsSnapshot === 'function') applyParamsSnapshot(card._params);
        applyBtn.classList.add('is-applied');
        if (typeof generateStatus !== 'undefined' && generateStatus) generateStatus.textContent = '✓ Parameters applied';
        setTimeout(function () { applyBtn.classList.remove('is-applied'); }, 1200);
      });
      footer.appendChild(applyBtn);
    }
  }

  // Quantization + generation time used for this result — computed here so
  // both the on-image labels below AND the persisted sessionImages entry
  // (picked up by _collectFlowSnapshot for localStorage/session restore)
  // agree, instead of falling back to whatever's currently selected in the
  // UI (which is wrong for anything but the very last image generated).
  var _quantId = params && params.quantizationId ? String(params.quantizationId) : '';
  // Prefer a real live-card timing; fall back to a persisted duration handed
  // in via params (restored sessions/sessions — see flow-boot.js) so time
  // survives a page reload too, instead of only ever existing in-memory.
  var _genSecondsRaw = (_hadRealCard && card._genStartTime)
    ? Math.max(0, (Date.now() - card._genStartTime) / 1000)
    : (params && typeof params.genSeconds === 'number' ? params.genSeconds : null);

  // Track image for lightbox (include composition bboxes if this came from ideogram_composer)
  // — also remember the prompt that produced it, so the chat "Scene" picker
  // can use it as the starting point for edits/new generations.
  var lbIdx = sessionImages.length;
  sessionImages.push({
    url: imgUrl,
    bboxes: _extractIdgBboxes(card),
    prompt: _cardPromptStr,
    quantizationId: _quantId,
    genSeconds: _genSecondsRaw,
  });
  // Remember which sessionImages slot this card owns, so deleting the card
  // can tombstone the right entry without reshuffling indices that other
  // cards' lightbox click-handlers already closed over.
  card._sessionImgIdx = lbIdx;

  // Update header badge label and add open-in-new-tab button
  var header = card.querySelector('.nss-card-header');
  var numBadge = header.querySelector('.nss-card-num');
  if (numBadge) numBadge.textContent = 'Scene ' + idx;
  var openBtn = document.createElement('button');
  openBtn.type = 'button';
  openBtn.id = 'nss-card-open-btn-' + idx;
  openBtn.className = 'nss-card-select-btn';
  openBtn.setAttribute('aria-label', 'Open in new tab');
  openBtn.title = 'Open in new tab';
  openBtn.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 2h4v4M14 2l-6 6M6 14H2v-4M2 14l6-6"/></svg>';
  openBtn.addEventListener('click', function (e) { e.stopPropagation(); window.open(imgUrl, '_blank'); });
  header.appendChild(openBtn);

  // The header used to carry its own delete button (id
  // nss-card-delete-btn-<idx>, class .nss-card-delete-btn) — the image
  // itself (imgWrap, on hover) already has one further down, deleteImgBtn,
  // with the exact same confirm + _removeSessionImageForCard/card.remove().
  // Two delete controls on one finished result card was just redundant, so
  // this one is gone. Note buildPromptCard's own .nss-card-delete-btn
  // (flow-generation.js) is a *different*, still-needed case: that's the
  // pre-generation "Variation N" placeholder card, which has no image (and
  // so no imgWrap) to hang a delete button off of yet.

  // Replace spinner with image — click anywhere on wrap opens lightbox
  var imgWrap = card.querySelector('.nss-card-img-wrap');
  if (card._etaInterval) { clearInterval(card._etaInterval); card._etaInterval = null; }
  imgWrap.innerHTML = '';
  imgWrap.style.cursor = 'pointer';
  var img = document.createElement('img');
  img.src = imgUrl; img.alt = 'Scene ' + idx; img.loading = 'lazy';
  imgWrap.appendChild(img);

  // Favorite/diamond — same functionality (and same server sidecar via
  // api.updateImageMeta) as the thumbnails in Album's Images mode
  // (album/album_images.js), just styled to match this card's own 28×28
  // dark-chip icon buttons instead of Explore's floating glyph style, and
  // placed top-left since top-right is already the share/download/open
  // cluster. Only shown once the result is a real saved server file — a raw
  // ComfyUI temp URL (save failed) has no sidecar to persist to. Freshly
  // generated images have no prior favorite/diamond state to restore, so
  // both start unset; a restored session's images could theoretically
  // already carry state set elsewhere (e.g. from Album) that this doesn't
  // fetch back — a known, accepted gap, not attempted here.
  var _favFilename = _filenameFromImageUrl(imgUrl);
  if (_favFilename) {
    var _isFav = false;
    var _isDiamond = false;
    var heartBtn = document.createElement('button');
    heartBtn.type = 'button';
    heartBtn.id = 'nss-card-heart-btn-' + idx;
    heartBtn.className = 'nss-card-heart';
    heartBtn.setAttribute('aria-label', 'Toggle favorite');
    heartBtn.title = 'Favorite';
    heartBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.5s-7-4.35-9.5-8.5C.9 9 2.4 5.5 6 5.5c2.1 0 3.4 1.1 4.6 2.6C11.8 6.6 13.1 5.5 15.2 5.5c3.6 0 5.1 3.5 3.5 6.5C21 16.15 12 20.5 12 20.5z"/></svg>';
    heartBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      _isFav = !_isFav;
      heartBtn.classList.toggle('active', _isFav);
      if (window.openJourneyApi && typeof window.openJourneyApi.updateImageMeta === 'function') {
        window.openJourneyApi.updateImageMeta(_favFilename, { favorite: _isFav }).catch(function () {});
      }
    });
    imgWrap.appendChild(heartBtn);

    var diamondBtn = document.createElement('button');
    diamondBtn.type = 'button';
    diamondBtn.id = 'nss-card-diamond-btn-' + idx;
    diamondBtn.className = 'nss-card-diamond';
    diamondBtn.setAttribute('aria-label', 'Toggle diamond');
    diamondBtn.title = 'Diamond';
    diamondBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l9 9-9 9-9-9z"/></svg>';
    diamondBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      _isDiamond = !_isDiamond;
      diamondBtn.classList.toggle('active', _isDiamond);
      if (window.openJourneyApi && typeof window.openJourneyApi.updateImageMeta === 'function') {
        window.openJourneyApi.updateImageMeta(_favFilename, { diamond: _isDiamond }).catch(function () {});
      }
    });
    imgWrap.appendChild(diamondBtn);
  }

  var downloadBtn = document.createElement('button');
  downloadBtn.type = 'button';
  downloadBtn.id = 'nss-card-download-btn-' + idx;
  downloadBtn.className = 'nss-card-img-download';
  downloadBtn.setAttribute('aria-label', 'Download image');
  downloadBtn.title = 'Download';
  downloadBtn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M12 3v13m0 0l-4.5-4.5M12 16l4.5-4.5"/><path d="M4 20h16"/>' +
    '</svg>';
  downloadBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    var a = document.createElement('a');
    a.href = imgUrl;
    a.download = 'scene-' + idx + '.png';
    document.body.appendChild(a);
    a.click();
    a.remove();
  });
  imgWrap.appendChild(downloadBtn);

  // Share button — icon only, same 28×28 chrome as download/open. Sits to
  // the left of download. Opens a modal to share the image (with its
  // prompt) or, when a "before" image is available (refine flows only), a
  // looping before/after fade video too.
  var shareBtn = document.createElement('button');
  shareBtn.type = 'button';
  shareBtn.id = 'nss-card-share-btn-' + idx;
  shareBtn.className = 'nss-card-img-share';
  shareBtn.setAttribute('aria-label', 'Share');
  shareBtn.title = 'Share';
  shareBtn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
      '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>' +
      '<path d="M8.6 10.5l6.8-3.9M8.6 13.5l6.8 3.9"/>' +
    '</svg>';
  shareBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    _openShareModal(imgUrl, beforeUrl, _cardPromptStr);
  });
  imgWrap.appendChild(shareBtn);

  // Use as input — feeds this result straight back into the flow's own
  // source-image picker, for chaining edits (refine the refined output)
  // without dragging the file out and back in. Only shown when the flow
  // actually has a single-image picker to target (registered by
  // renderImagePicker in flow-step-image-picker.js) — Mix/multi-image flows
  // and image-less Create flows just don't get the button.
  var _imgPickerReg = window._ncfImagePickers && window._ncfImagePickers['image'];
  if (_imgPickerReg) {
    var useInputBtn = document.createElement('button');
    useInputBtn.type = 'button';
    useInputBtn.id = 'nss-card-use-input-btn-' + idx;
    useInputBtn.className = 'nss-card-img-use-input';
    useInputBtn.setAttribute('aria-label', 'Use as input');
    useInputBtn.title = 'Use as input for this flow';
    useInputBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a5 5 0 015 5v1"/>' +
      '</svg>';
    useInputBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var reg = window._ncfImagePickers && window._ncfImagePickers['image'];
      if (!reg) return; // picker was removed/re-rendered since the button appeared
      reg.loadUrlAsImage(imgUrl);
      if (reg.wrap && reg.wrap.scrollIntoView) reg.wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
      useInputBtn.classList.add('is-applied');
      if (typeof generateStatus !== 'undefined' && generateStatus) generateStatus.textContent = '✓ Set as new source image';
      setTimeout(function () { useInputBtn.classList.remove('is-applied'); }, 1200);
    });
    imgWrap.appendChild(useInputBtn);
  }

  var overlayBtn = document.createElement('button');
  overlayBtn.type = 'button';
  overlayBtn.id = 'nss-card-open-full-btn-' + idx;
  overlayBtn.className = 'nss-card-img-open';
  overlayBtn.setAttribute('aria-label', 'View full size');
  overlayBtn.title = 'View full size';
  overlayBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>';
  imgWrap.appendChild(overlayBtn);
  var resLabel = document.createElement('span');
  resLabel.className = 'nit-img-res';
  img.addEventListener('load', function () {
    if (img.naturalWidth && img.naturalHeight) {
      resLabel.textContent = img.naturalWidth + '×' + img.naturalHeight;
    }
  });
  imgWrap.appendChild(resLabel);

  // Generation time (seconds) — sits just above the resolution label.
  if (_genSecondsRaw !== null) {
    var timeLabel = document.createElement('span');
    timeLabel.className = 'nit-img-time';
    // Show one decimal under 10s so fast/cached generations don't just read "0s".
    timeLabel.textContent = (_genSecondsRaw < 10 ? _genSecondsRaw.toFixed(1) : Math.round(_genSecondsRaw)) + 's';
    imgWrap.appendChild(timeLabel);
  }

  // Quantization used for this generation — sits above the time label.
  if (_quantId) {
    var quantLabel = document.createElement('span');
    quantLabel.className = 'nit-img-quant';
    quantLabel.textContent = _quantId.toUpperCase();
    imgWrap.appendChild(quantLabel);
  }
  var sendTrayBtn = document.createElement('button');
  sendTrayBtn.type = 'button';
  sendTrayBtn.id = 'nit-send-tray-btn-' + idx;
  sendTrayBtn.className = 'nit-send-tray-btn';
  sendTrayBtn.setAttribute('aria-label', 'Send to tray');
  sendTrayBtn.title = 'Send to tray';
  sendTrayBtn.setAttribute('data-tray-img-url', imgUrl);
  sendTrayBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20M2 12v8a2 2 0 002 2h16a2 2 0 002-2v-8M2 12l3-9h14l3 9"/></svg>';
  imgWrap.appendChild(sendTrayBtn);

  // Send to Depot — only meaningful while a Depot is active (see
  // depots_routes.py's /api/depots/active); the panel itself checks and
  // shows a nudge to activate one if not, rather than hiding the button
  // (hiding it would make "why isn't this here" a mystery on every card).
  var sendDepotBtn = document.createElement('button');
  sendDepotBtn.type = 'button';
  sendDepotBtn.id = 'nit-send-depot-btn-' + idx;
  sendDepotBtn.className = 'nit-send-tray-btn nit-send-depot-btn nsc-options-trigger';
  sendDepotBtn.setAttribute('aria-label', 'Send to Depot');
  sendDepotBtn.title = 'Send to Depot';
  sendDepotBtn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>' +
      '<path d="M3.3 7 12 12l8.7-5M12 22V12"/>' +
    '</svg>';
  sendDepotBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    _openSendToDepotPanel(imgUrl, _cardPromptStr);
  });
  imgWrap.appendChild(sendDepotBtn);

  // Send to Character / Send to Background — a side panel: a new Build
  // Character or Background from this result (image + the card's prompt), or
  // this image for one that already exists (issue #13); see
  // _openSendToBuildPanel below. Distinct from "Send to Depot" above, which
  // files the image into the active Depot's own buckets.
  [
    { kind: 'character', label: 'Send to Character',
      svg: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>' },
    { kind: 'background', label: 'Send to Background',
      svg: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 16l5-5 4 4 3-3 6 6"/><circle cx="16" cy="9" r="1.5"/>' },
  ].forEach(function (target) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'nit-send-' + target.kind + '-btn-' + idx;
    btn.className = 'nit-send-tray-btn nit-send-' + target.kind + '-btn nsc-options-trigger';
    btn.setAttribute('aria-label', tF(target.label));
    btn.title = tF(target.label);
    btn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
      target.svg + '</svg>';
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      _openSendToBuildPanel(target.kind, imgUrl, _cardPromptStr, btn);
    });
    imgWrap.appendChild(btn);
  });

  // Auto-save to the active Depot's Flows section — every generation while
  // a depot is active, no manual picking. Distinct from the button above
  // (which lets the user additionally curate a specific result into
  // Background/Character/Asset). Fire-and-forget: the endpoint itself
  // resolves the active depot from the session and just 400s with no side
  // effect when none is active, which this silently treats as a no-op.
  fetch('/api/depots/active/items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category: 'flow', url: imgUrl, caption: _cardPromptStr || '', sourceUrl: window.location.href }),
  }).catch(function () {});

  var deleteImgBtn = document.createElement('button');
  deleteImgBtn.type = 'button';
  deleteImgBtn.id = 'nit-delete-img-btn-' + idx;
  deleteImgBtn.className = 'nit-send-tray-btn nit-delete-img-btn';
  deleteImgBtn.setAttribute('aria-label', 'Delete image');
  deleteImgBtn.title = 'Delete image';
  deleteImgBtn.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
      '<polyline points="3,6 21,6"/>' +
      '<path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>' +
    '</svg>';
  deleteImgBtn.addEventListener('click', function (e) {
    // The wrap itself has its own click listener (opens the lightbox) added
    // further down. It's registered AFTER this one, but on the same element
    // tree — stopImmediatePropagation stops it deterministically instead of
    // relying on bubble-order between sibling/parent listeners.
    e.stopPropagation();
    e.preventDefault();
    if (window.confirm('Delete this image from the session?')) {
      _removeSessionImageForCard(card);
      card.remove();
    }
  });
  imgWrap.appendChild(deleteImgBtn);

  imgWrap.setAttribute('draggable', 'true');
  (function (u) {
    imgWrap.addEventListener('dragstart', function (e) {
      // Starting a native drag on top of a nested button swallows the click
      // that would otherwise fire on mouseup — the browser treats the tiny
      // mousedown-to-mouseup movement as a drag gesture instead of a click,
      // silently (no error) killing button clicks like send-to-tray/delete.
      // Bail out of the drag entirely when it starts on one of those buttons.
      if (e.target.closest('button')) { e.preventDefault(); return; }
      e.dataTransfer.setData('application/x-tray-url', u);
      e.dataTransfer.effectAllowed = 'copy';
    });
  }(imgUrl));
  (function (i) {
    imgWrap.addEventListener('click', function () { openLightbox(i); });
  }(lbIdx));
}

// "Send to Depot" — classify a result image as Background/Character/Asset
// and attach it to whichever Depot is currently active (server-side session
// state, see depots_routes.py). Reuses the shared lateral options panel
// (flow-options-panel.js) rather than a one-off modal.
function _openSendToDepotPanel(imgUrl, caption) {
  fetch('/api/depots/active').then(function (r) { return r.json(); }).then(function (data) {
    var depot = data && data.depot;
    openOptionsPanel('Send to Depot', function (body) {
      var info = document.createElement('p');
      info.className = 'ncf-depot-send-info';
      body.appendChild(info);

      if (!depot) {
        info.textContent = 'No active Depot. Open a Depot from Build and hit Activate first.';
        return;
      }
      info.textContent = 'Sending to "' + depot.name + '":';

      var optionsWrap = document.createElement('div');
      optionsWrap.className = 'ncf-depot-send-options';
      body.appendChild(optionsWrap);

      [
        { key: 'background', label: 'Background' },
        { key: 'character', label: 'Character' },
        { key: 'asset', label: 'Asset' },
      ].forEach(function (opt) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ncf-depot-category-btn';
        btn.textContent = opt.label;
        btn.addEventListener('click', function () {
          optionsWrap.querySelectorAll('.ncf-depot-category-btn').forEach(function (b) { b.disabled = true; });
          fetch('/api/depots/active/items', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category: opt.key, url: imgUrl, caption: caption || '', sourceUrl: window.location.href }),
          }).then(function (r) {
            return r.json().then(function (d) { return { ok: r.ok, data: d }; });
          }).then(function (res) {
            if (!res.ok) throw new Error((res.data && res.data.error) || 'Failed');
            info.textContent = 'Sent to "' + depot.name + '" as ' + opt.label + '.';
            setTimeout(closeOptionsPanel, 900);
          }).catch(function (err) {
            console.error('[FlowGallery] Send to depot failed:', err);
            info.textContent = 'Failed to send: ' + (err && err.message ? err.message : err);
            optionsWrap.querySelectorAll('.ncf-depot-category-btn').forEach(function (b) { b.disabled = false; });
          });
        });
        optionsWrap.appendChild(btn);
      });
    });
  }).catch(function (err) {
    console.error('[FlowGallery] Failed to check active depot:', err);
  });
}

// "Send to Character" / "Send to Background" — turn a result into a new
// Build Character or Background on the spot: POST /api/characters (or
// /api/backgrounds) with a description taken from the start of the card's
// prompt and the full prompt as the item's own prompt, then set this image as
// its reference image (PATCH …/<keyword>/image, same call Build's "Change
// image" makes). The server picks a unique keyword (character, character_2…).
function _sendResultToBuild(kind, imgUrl, prompt, btn) {
  var plural = kind + 's';
  var fullPrompt = String(prompt || '').trim();
  var words = fullPrompt.split(/\s+/).filter(Boolean);
  var description = words.slice(0, 12).join(' ');
  if (words.length > 12) description += '…';
  if (!description) description = kind === 'character' ? 'New character' : 'New background';
  if (btn) btn.disabled = true;
  fetch('/api/' + plural, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword: kind, description: description, prompt: fullPrompt || description }),
  }).then(function (r) {
    return r.json().then(function (d) { return { ok: r.ok, data: d }; });
  }).then(function (res) {
    if (!res.ok) throw new Error((res.data && res.data.error) || 'Create failed');
    var item = res.data[kind] || {};
    var itemUrl = '/api/' + plural + '/' + encodeURIComponent(item.keyword);
    return fetch(itemUrl + '/image', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ imageUrl: imgUrl }),
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error((d && d.error) || 'Image failed');
        return item;
      });
    }).catch(function (err) {
      // No image, no character: drop the one just created instead of
      // leaving an empty entry behind in Build.
      return fetch(itemUrl, { method: 'DELETE' }).catch(function () {}).then(function () { throw err; });
    });
  }).then(function (item) {
    if (typeof showToast === 'function') {
      showToast((kind === 'character' ? tF('Character created') : tF('Background created')) +
        ': ' + item.keyword + ' — ' + tF('edit it in Build.'), 'info');
    }
  }).catch(function (err) {
    console.error('[FlowGallery] Send to ' + kind + ' failed:', err);
    if (typeof showErrorToast === 'function') showErrorToast((err && err.message) || String(err));
  }).then(function () {
    if (btn) btn.disabled = false;
  });
}

// The side panel behind a result's "Send to Character / Background" (issue
// #13): "New character" on top — the old one-click action — and below it the
// existing ones of that kind (flow-step-image-picker.js ncfFillBuildPanel).
// Picking one asks first, in the panel itself, then makes this result its
// image (PATCH …/<keyword>/image — the same call Build's "Change image"
// makes; its prompt and description stay as they are).
function _openSendToBuildPanel(kind, imgUrl, prompt, btn) {
  var isChar = kind === 'character';
  var plural = kind + 's';
  var title = tF(isChar ? 'Send to Character' : 'Send to Background');

  function renderChoose(body) {
    body.innerHTML = '';
    ncfFillOptionsMenu(body, [{
      label: tF(isChar ? 'New character' : 'New background'),
      svgInner: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
      onClick: function () {
        closeOptionsPanel();
        _sendResultToBuild(kind, imgUrl, prompt, btn);
      },
    }]);
    var hint = document.createElement('p');
    hint.className = 'nsc-step-hint ncf-send-build-hint';
    hint.textContent = tF('Or use it as the image of one that already exists:');
    body.appendChild(hint);
    ncfFillBuildPanel(body, function (currentUrl, item) {
      renderConfirm(body, currentUrl, item);
    }, plural);
  }

  // Replacing loses the current image, so the panel shows both and asks.
  function renderConfirm(body, currentUrl, item) {
    body.innerHTML = '';
    var q = document.createElement('p');
    q.className = 'ncf-send-build-question';
    var strong = document.createElement('strong');
    strong.textContent = item.name;
    q.appendChild(strong);
    q.appendChild(document.createTextNode(' — ' + tF('Replace its image with this one? The current image is lost.')));
    body.appendChild(q);

    var pair = document.createElement('div');
    pair.className = 'ncf-send-build-pair';
    [currentUrl, imgUrl].forEach(function (src, i) {
      var fig = document.createElement('figure');
      var im = document.createElement('img');
      im.src = src;
      im.alt = '';
      im.addEventListener('error', function () { fig.classList.add('is-empty'); im.remove(); });
      var cap = document.createElement('figcaption');
      cap.textContent = tF(i ? 'New' : 'Now');
      fig.appendChild(im);
      fig.appendChild(cap);
      pair.appendChild(fig);
      if (!i) {
        var arrow = document.createElement('span');
        arrow.className = 'ncf-send-build-arrow';
        arrow.setAttribute('aria-hidden', 'true');
        arrow.textContent = '→';
        pair.appendChild(arrow);
      }
    });
    body.appendChild(pair);

    var actions = document.createElement('div');
    actions.className = 'ncf-send-build-actions';
    var ok = document.createElement('button');
    ok.type = 'button';
    ok.className = 'nss-generate-scenes-btn ncf-send-build-ok';
    ok.textContent = tF('Replace');
    var back = document.createElement('button');
    back.type = 'button';
    back.className = 'ncf-send-build-back';
    back.textContent = tF('Cancel');
    back.addEventListener('click', function () { renderChoose(body); });
    ok.addEventListener('click', function () {
      ok.disabled = back.disabled = true;
      fetch('/api/' + plural + '/' + encodeURIComponent(item.keyword) + '/image', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ imageUrl: imgUrl }),
      }).then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw new Error((d && d.error) || 'Image failed');
        });
      }).then(function () {
        closeOptionsPanel();
        if (typeof showToast === 'function') showToast(tF('Image updated') + ': ' + item.keyword, 'info');
      }).catch(function (err) {
        console.error('[FlowGallery] Replace ' + kind + ' image failed:', err);
        ok.disabled = back.disabled = false;
        if (typeof showErrorToast === 'function') showErrorToast((err && err.message) || String(err));
      });
    });
    actions.appendChild(ok);
    actions.appendChild(back);
    body.appendChild(actions);
  }

  openOptionsPanel(title, renderChoose, { wide: true });
}

// ── Story project persistence (narrative continuity) ────────────────────────
// Per-story JSON on disk (app/data/stories/<id>.json — see
// story_project_service.py), separate from the flat localStorage session
// history that drives the History panel / Album. One entry per scene, 1:1
// across narrative_thread (plot summary) and scene_thread (image prompt +
// the vision description used to write it) — see [[Sesiones - JSON de
// proyecto]] in the Obsidian vault for the full spec/rationale.
//
// sessionState.story_project_id is created lazily, the first time any scene
// actually finishes generating (not when "world" is typed — a story that
// never gets an image shouldn't leave an empty project file behind).
function _ensureStoryProject() {
  if (sessionState.story_project_id) return Promise.resolve(sessionState.story_project_id);
  var title = (sessionState.world_context || getVal('world', 'prompt_text') || '').slice(0, 120);
  return fetch('/api/stories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title }),
  }).then(function (r) { return r.json(); }).then(function (data) {
    sessionState.story_project_id = data && data.story_id;
    return sessionState.story_project_id;
  }).catch(function (err) {
    console.warn('[FlowEngine] _ensureStoryProject failed:', err);
    return null;
  });
}

function _persistStoryScene(fields) {
  return _ensureStoryProject().then(function (storyId) {
    if (!storyId) return null;
    return fetch('/api/stories/' + storyId + '/scenes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        narrativeSummary: fields.narrativeSummary || '',
        promptUsed: fields.promptUsed || '',
        style: fields.style || '',
        visionSummary: fields.visionSummary || '',
        imagePath: fields.imagePath || '',
      }),
    }).catch(function (err) {
      console.warn('[FlowEngine] _persistStoryScene failed:', err);
      return null;
    });
  });
}

// Scene 1 goes through the plain step flow (world → write scene → Generate
// Image), not _submitStoryInstruction's loop — this is the one place common
// to both paths that fires exactly once right after a scene's image is
// actually in sessionImages, so it's where scene 1 gets persisted. Every
// scene after that is persisted directly inside _submitStoryInstruction's
// loop instead, since it already has its own narrativeSummary/visionContext
// in hand there without needing to guess.
// Renders the raw persisted story JSON (app/data/stories/<id>.json) into the
// shared lateral options panel, so the user can actually see what
// narrative_thread/scene_thread look like without opening a file on disk.
// A refresh icon re-fetches, since scenes get appended while the panel is
// still open (the user is generating the next scene).
function _openStoryJsonPanel() {
  openOptionsPanel('Story JSON', function (body) {
    var pre = document.createElement('pre');
    pre.className = 'ncf-story-json-pre';
    body.appendChild(pre);

    function render() {
      var storyId = sessionState.story_project_id;
      if (!storyId) {
        pre.remove();
        body.innerHTML = '<p class="ncf-story-json-empty">No scene has finished generating yet — the story JSON is created after the first image.</p>';
        return;
      }
      fetch('/api/stories/' + storyId).then(function (r) { return r.json(); }).then(function (data) {
        pre.textContent = JSON.stringify(data, null, 2);
      }).catch(function (err) {
        pre.textContent = 'Failed to load story JSON: ' + (err && err.message || err);
      });
    }
    render();

    setOptionsPanelAction(
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
      render,
      { icon: true, label: 'Refresh' }
    );
  });
}

function _persistFirstStorySceneIfNeeded() {
  if (sessionState.story_project_id) return; // scene 1 already handled
  var lastIdx = _lastValidSessionImageIdx();
  if (lastIdx < 0) return;
  var entry = sessionImages[lastIdx];
  _persistStoryScene({
    narrativeSummary: sessionState._pendingStoryNarrativeSummary || '',
    promptUsed: getVal('scene_prompt', 'prompt_text') || '',
    style: (typeof selectedGenre !== 'undefined' && selectedGenre) || '',
    visionSummary: '', // nothing to look at yet — this is the opening scene
    imagePath: entry.url,
  });
  sessionState._pendingStoryNarrativeSummary = '';
}

function showResultActions(actionStepDef) {
  var actionsBar = document.getElementById('ncf-story-actions');
  var continueBtn = document.getElementById('ncf-continue-btn');
  var endBtn = document.getElementById('ncf-end-btn');

  // For .chat flows: show the inline chat bar instead of Continue/End story buttons
  var _isChatFlow = typeof flowId === 'string' && flowId.indexOf('.chat') !== -1;

  if (_isChatFlow) {
    _showChatBar(actionStepDef);
    _syncChatSceneSelect();
    return;
  }

  // For story flows (llm.story_continue step present): show the inline story
  // bar instead of the old sidebar Continue/End story buttons.
  var _isStoryFlow = allSteps.some(function (s) { return s.calls === 'llm.story_continue'; });
  if (_isStoryFlow) {
    _persistFirstStorySceneIfNeeded();
    _showStoryBar(actionStepDef);
    return;
  }

  // Plain create/refine/mix flows (no chat bar, no story bar, no legacy
  // continue_story sidebar) have nothing further to show here — batch-send
  // to Refine is always available from the toolbar's "Refine" button.
  if (!actionsBar) {
    return;
  }

  actionsBar.style.display = '';
  if (continueBtn) continueBtn.disabled = false;
  if (endBtn) endBtn.disabled = false;

  // Wire Continue story (idempotent — skip if already wired)
  if (continueBtn && !continueBtn._wired) {
    continueBtn._wired = true;
    continueBtn.addEventListener('click', function () {
      var worldDef = allSteps.find(function (s) { return s.type === 'prompt_input' && !s.triggered_by; });
      var instrDef = allSteps.find(function (s) { return s.triggered_by === 'result.action.continue_story'; });
      if (worldDef) {
        worldDef._sessionSyncFrozen = true;
        var instrPlaceholder = (instrDef && instrDef.placeholder)
          || 'Turn right toward the jungle / nightfall / a figure appears…';
        var worldWrap = document.getElementById('ncf-step-wrap-' + worldDef.id);
        var worldTa   = document.getElementById('ncf-input-' + worldDef.id);
        if (worldWrap) {
          var lbl = worldWrap.querySelector('.nsc-step-label');
          if (lbl) {
            var numSpan = lbl.querySelector('.nsc-step-num');
            lbl.textContent = '';
            if (numSpan) lbl.appendChild(numSpan);
            lbl.appendChild(document.createTextNode(' What happens next?'));
          }
        }
        if (worldTa) {
          worldTa.placeholder = instrPlaceholder;
          worldTa.value = '';
          setVal(worldDef.id, 'prompt_text', '');
        }
        guidedFixedSeed = -1;
        var llmDef = allSteps.find(function (s) { return s.type === 'llm_transform'; });
        if (instrDef) revealTriggeredStep(instrDef.id);
        if (llmDef && llmDef._llmRefs && llmDef._llmRefs.writeBtn) {
          llmDef._llmRefs.writeBtn.click();
        }
      }
    });
  }
}

// ── Chat bar logic ────────────────────────────────────────────────────────────
// Keep the "Scene" picker in sync with sessionImages. Rebuilds the option
// list every time it's called (cheap — there are at most a few dozen scenes)
// and auto-follows the newest image unless the user had explicitly picked an
// earlier one, in which case that choice is preserved across new generations.
function _syncChatSceneSelect() {
  var sceneSelect = document.getElementById('ncf-chat-scene-select');
  if (!sceneSelect || typeof sessionImages === 'undefined' || !sessionImages.length) return;

  var prevValue = sceneSelect.value;
  var prevCount = sceneSelect.options.length;
  var wasFollowingLatest = !prevValue || prevValue === String(prevCount - 1);

  sceneSelect.innerHTML = '';
  sessionImages.forEach(function (_img, i) {
    var opt = document.createElement('option');
    opt.value = String(i);
    opt.textContent = 'Scene ' + (i + 1) + (i === sessionImages.length - 1 ? ' (latest)' : '');
    sceneSelect.appendChild(opt);
  });

  if (wasFollowingLatest) {
    sceneSelect.value = String(sessionImages.length - 1);
  } else {
    var idx = parseInt(prevValue, 10);
    sceneSelect.value = (idx >= 0 && idx < sessionImages.length) ? String(idx) : String(sessionImages.length - 1);
  }
}

function _showChatBar(actionStepDef) {
  var chatBar  = document.getElementById('ncf-chat-bar');
  var chatInput = document.getElementById('ncf-chat-input');
  var sendBtn  = document.getElementById('ncf-chat-send-btn');
  var chatHint = document.getElementById('ncf-chat-hint');
  var wfSelect = document.getElementById('ncf-chat-wf-select');
  if (!chatBar) return;

  chatBar.removeAttribute('hidden');
  if (chatBar._wired) return;
  chatBar._wired = true;

  var epToggleInput = document.getElementById('ncf-chat-ep-toggle');
  var wfEditWith = document.getElementById('ncf-chat-wf-editwith');
  var wfSep = document.getElementById('ncf-chat-wf-sep');

  // Writing-model chip — same picker (openModelOptionsPanel) the Assist step
  // uses, so the chat bar names which LLM rewrites the instruction and lets
  // you switch it without leaving the flow. Changes the same global setting
  // Assist reads (there's only one "writing model" today, not a per-chat one).
  var chatModelBtn  = document.getElementById('ncf-chat-model-btn');
  var chatModelName = document.getElementById('ncf-chat-model-name');
  if (chatModelBtn) {
    chatModelBtn.addEventListener('click', function () { openModelOptionsPanel(); });
    if (typeof loadPromptModelHint === 'function') loadPromptModelHint(chatModelBtn, chatModelName);
  }

  // "Edit with" is only shown once "Edit Prompt" is turned on — the select's
  // own value is never touched by this, it just stays hidden/shown.
  function _updateWfSelectVisibility() {
    var epOn = !!(epToggleInput && epToggleInput.checked);
    if (wfEditWith) wfEditWith.hidden = !epOn;
    if (wfSep) wfSep.hidden = !epOn;
  }
  _updateWfSelectVisibility();
  if (epToggleInput) epToggleInput.addEventListener('change', _updateWfSelectVisibility);

  // Load refine workflows into the edit-with selector
  var _refineFlows = [];
  fetch('/api/flows?category=refine').then(function (r) { return r.json(); }).then(function (data) {
    _refineFlows = Array.isArray(data.flows) ? data.flows : [];
    _refineFlows.forEach(function (rf) {
      var opt = document.createElement('option');
      opt.value = String(rf.id || '');
      opt.textContent = String(rf.label || rf.id || 'Unnamed');
      if (wfSelect) wfSelect.appendChild(opt);
    });
  }).catch(function () {});

  // Auto-resize textarea as user types
  chatInput.addEventListener('input', function () {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  });

  // Ctrl+Enter submits
  chatInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      _submitChatInstruction();
    }
  });

  sendBtn.addEventListener('click', function () {
    _submitChatInstruction();
  });

  // Convert an image URL to a base64 dataUrl
  function _toDataUrl(url) {
    return fetch(url).then(function (r) { return r.blob(); }).then(function (blob) {
      return new Promise(function (resolve, reject) {
        var reader = new FileReader();
        reader.onloadend = function () { resolve(reader.result); };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    });
  }

  // Run refine on the selected scene (defaults to the last generated image)
  // with the chosen refine workflow + prompt
  // card: the queued card _submitChatInstruction already put in the grid
  // before any of this async work started — passed straight through to
  // _runRefine so it updates that card in place instead of creating its own
  // (much) later, once prepare/submit have both round-tripped.
  function _chatRunRefine(refineFlowId, promptText, card) {
    if (!sessionImages.length) return Promise.reject(new Error('No image to edit yet'));
    var sceneSelect = document.getElementById('ncf-chat-scene-select');
    var sceneIdx = sceneSelect && sceneSelect.value !== '' ? parseInt(sceneSelect.value, 10) : NaN;
    if (isNaN(sceneIdx) || sceneIdx < 0 || sceneIdx >= sessionImages.length || !sessionImages[sceneIdx]) {
      sceneIdx = _lastValidSessionImageIdx();
    }
    if (sceneIdx < 0) return Promise.reject(new Error('No image to edit yet'));
    var lastUrl = sessionImages[sceneIdx].url;

    if (chatHint) chatHint.textContent = 'Loading image…';
    return _toDataUrl(lastUrl).then(function (imageDataUrl) {
      // Fetch the full flow definition to extract workflow_file from the workflow_params step
      return fetch('/api/flows/' + encodeURIComponent(refineFlowId)).then(function (r) { return r.json(); }).then(function (data) {
        var steps = (data && data.flow && data.flow.definition && Array.isArray(data.flow.definition.steps))
          ? data.flow.definition.steps : [];
        var paramsStep = steps.find(function (s) { return s.type === 'workflow_params'; });
        var workflowFile = paramsStep ? (paramsStep.workflow_file || '') : '';
        var imageNode = paramsStep ? (paramsStep.image_node || null) : null;

        // Build advancedValues: inject promptText into the prompt field's adv_key
        var advancedValues = {};
        if (paramsStep && Array.isArray(paramsStep.fields)) {
          var promptField = paramsStep.fields.find(function (f) {
            return f.id === 'prompt' || f.type === 'text';
          });
          if (promptField && promptField.adv_key) {
            advancedValues[promptField.adv_key] = promptText;
          }
        }

        if (!workflowFile) return Promise.reject(new Error('No workflow_file found for ' + refineFlowId));

        if (chatHint) chatHint.textContent = 'Editing image…';
        var synthStepDef = { id: 'chat_refine', type: 'action', calls: 'generation.submit_refine' };
        var snapshot = {
          workflowFile:   workflowFile,
          imageDataUrl:   imageDataUrl,
          advancedValues: advancedValues,
          imageNodeId:    imageNode,
          promptText:     promptText,
        };
        return _runRefine(synthStepDef, { snapshot: snapshot, card: card });
      });
    });
  }

  // Prompt stored on the scene currently picked in the "Scene" selector, if any.
  function _selectedScenePrompt() {
    var sceneSelect = document.getElementById('ncf-chat-scene-select');
    var idx = sceneSelect && sceneSelect.value !== '' ? parseInt(sceneSelect.value, 10) : NaN;
    if (isNaN(idx) || !sessionImages[idx]) return '';
    return sessionImages[idx].prompt || '';
  }

  // ── Chat queue — one instruction runs at a time, in the order sent, but
  // sending never blocks: keep typing and hitting Enter, each one gets its
  // own card immediately (queued if something's still ahead of it, straight
  // to generating if it's next) and waits its turn. Running them in order
  // (not in parallel) matters here, not just for politeness — each message
  // edits the scene_prompt the previous one just finished writing, so #2
  // has to see #1's result, not the prompt that was live when #2 was typed.
  var _chatQueue = [];
  var _chatBusy = false;

  function _submitChatInstruction() {
    var text = chatInput.value.trim();
    if (!text) return;

    var selectedWf = wfSelect ? wfSelect.value : '';
    var epToggle = document.getElementById('ncf-chat-ep-toggle');
    var useEditPrompt = epToggle && epToggle.checked;

    // Card goes up the instant you hit send — queued (amber) if something's
    // already running, straight to generating otherwise — instead of
    // leaving nothing but a text hint until everything else finishes (#109).
    // + 1 for the item already shifted out of _chatQueue and running, if any.
    var idx = generatedCount + 1 + _chatQueue.length + (_chatBusy ? 1 : 0);
    var card = _chatBusy
      ? _addQueuedCard(idx, text)
      : ((typeof addGeneratingCard === 'function') ? addGeneratingCard(idx, text) : null);

    _chatQueue.push({ text: text, selectedWf: selectedWf, useEditPrompt: useEditPrompt, card: card });
    chatInput.value = '';
    chatInput.style.height = 'auto';
    chatInput.focus();
    _processChatQueue();
  }

  function _processChatQueue() {
    if (_chatBusy || !_chatQueue.length) return;
    _chatBusy = true;
    var item = _chatQueue.shift();
    if (item.card && item.card.getAttribute('data-status') === 'queuing') {
      _markCardGenerating(item.card);
    }
    if (chatHint) {
      chatHint.textContent = _chatQueue.length ? 'Editing prompt… (' + _chatQueue.length + ' queued)' : 'Editing prompt…';
    }

    _runChatItem(item).then(function () {
      if (chatHint) chatHint.textContent = '';
    }).catch(function (err) {
      if (chatHint) chatHint.textContent = '✗ ' + (err.message || 'Edit failed');
      if (typeof _markCardError === 'function') _markCardError(item.card);
    }).then(function () {
      _chatBusy = false;
      _processChatQueue();
    });
  }

  // Runs exactly one chat instruction (the logic _submitChatInstruction used
  // to run inline) — text/selectedWf/useEditPrompt/card come from the queue
  // item, not the live chat bar, since by the time this runs the user may
  // already be typing the next one.
  function _runChatItem(item) {
    var text = item.text, selectedWf = item.selectedWf, useEditPrompt = item.useEditPrompt, chatCard = item.card;

    if (selectedWf) {
      if (useEditPrompt) {
        // Run edit-prompt LLM first, then pass refined text to refine workflow
        var scenePromptTaEP = document.getElementById('ncf-input-scene_prompt');
        var worldTaEP = document.getElementById('ncf-input-world');
        var basePromptEP = _selectedScenePrompt()
          || (scenePromptTaEP && !scenePromptTaEP.disabled && scenePromptTaEP.value.trim())
          || getVal('scene_prompt', 'prompt_text')
          || (worldTaEP && worldTaEP.value.trim())
          || getVal('world', 'prompt_text')
          || sessionState.world_context
          || '';
        return fetch('/api/models/chat/edit-prompt', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: 'single', instruction: text, currentPrompt: basePromptEP, thinking: false }),
        }).then(function (r) { return r.json(); }).then(function (data) {
          if (data.error) throw new Error(data.error);
          var ep = (data.editedPrompt || '').trim();
          // Fallback: if model just echoed back the instruction, combine manually
          var refined = (ep && ep.toLowerCase() !== text.toLowerCase()) ? ep : ((basePromptEP ? basePromptEP + ', ' : '') + text);
          if (chatHint) chatHint.textContent = 'Editing image…';
          return _chatRunRefine(selectedWf, refined, chatCard);
        });
      }
      // Pass the chat text directly as the prompt to the refine workflow
      if (chatHint) chatHint.textContent = 'Editing image…';
      return _chatRunRefine(selectedWf, text, chatCard);
    }

    // No edit workflow — call edit-prompt LLM then fresh generate
    if (typeof generateStatus !== 'undefined' && generateStatus) generateStatus.textContent = 'LLM processing…';

    var scenePromptTa = document.getElementById('ncf-input-scene_prompt');
    var worldTa = document.getElementById('ncf-input-world');
    var currentPrompt = _selectedScenePrompt()
      || (scenePromptTa && !scenePromptTa.disabled && scenePromptTa.value.trim())
      || getVal('scene_prompt', 'prompt_text')
      || (worldTa && worldTa.value.trim())
      || getVal('world', 'prompt_text')
      || sessionState.world_context
      || '';

    if (!currentPrompt) {
      if (typeof generateStatus !== 'undefined' && generateStatus) generateStatus.textContent = '✗ No base prompt found';
      return Promise.reject(new Error('No base prompt found'));
    }

    return fetch('/api/models/chat/edit-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: 'single',
        instruction: text,
        currentPrompt: currentPrompt,
        thinking: false,
      }),
    }).then(function (r) { return r.json(); }).then(function (data) {
      if (data.error) throw new Error(data.error);
      var newPrompt = (data.editedPrompt || '').trim();
      // Fallback: if model just echoed back the instruction, combine manually
      if (!newPrompt || newPrompt.toLowerCase() === text.toLowerCase()) {
        newPrompt = (currentPrompt ? currentPrompt + ', ' : '') + text;
      }

      if (scenePromptTa) {
        scenePromptTa.value = newPrompt;
        if (scenePromptTa.disabled) {
          scenePromptTa.disabled = false;
          scenePromptTa.classList.remove('is-prefill-pending');
          scenePromptTa.placeholder = '';
        }
        // Written from outside flow-step-prompt-input.js's own closure — a
        // real "input" event is what refreshes its phrase chips.
        scenePromptTa.dispatchEvent(new Event('input', { bubbles: true }));
      }
      setVal('scene_prompt', 'prompt_text', newPrompt);
      if (!sessionState.world_context) sessionState.world_context = currentPrompt;

      // Find the generate action step to pass into runGenerate directly
      var actionStep = allSteps && allSteps.find(function (s) { return s.type === 'action'; });
      if (!actionStep) throw new Error('Generate step not found');

      if (chatHint) chatHint.textContent = 'Generating…';
      // Ensure button is enabled for updateGenerateBtn called inside runGenerate
      if (generateBtn && generateBtn.disabled) generateBtn.removeAttribute('disabled');

      return runGenerate(actionStep, { card: chatCard });
    });
  }
}

// Convert an image URL to a base64 dataUrl (shared by chat + story bars).
function _imgUrlToDataUrl(url) {
  return fetch(url).then(function (r) { return r.blob(); }).then(function (blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onloadend = function () { resolve(reader.result); };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  });
}

// ── Story bar logic ───────────────────────────────────────────────────────────
// Mirrors _showChatBar but for story flows: writes N scenes from one
// instruction, one at a time (write → generate → write next…), with a Think
// toggle (LLM reasoning) and a Vision toggle (vision-describes the image the
// PREVIOUS scene in this same batch just produced before writing the next
// one, and pins the seed via the existing Guided "Visual similarity"
// mechanism). Sequential on purpose — it's what lets each scene's vision
// pass actually look at the image right before it instead of whatever was
// last generated before the whole batch started.
function _showStoryBar(actionStepDef) {
  var storyBar = document.getElementById('ncf-story-bar');
  if (!storyBar) return;

  storyBar.removeAttribute('hidden');
  if (storyBar._wired) return;
  storyBar._wired = true;

  var storyInput         = document.getElementById('ncf-story-input');
  var sendBtn             = document.getElementById('ncf-story-send-btn');
  var reasoningSelect     = document.getElementById('ncf-story-reasoning-select');
  var consistencyToggle   = document.getElementById('ncf-story-consistency-toggle');
  var scenesSelect        = document.getElementById('ncf-story-scenes-select');
  var jsonBtn              = document.getElementById('ncf-story-json-btn');
  if (jsonBtn) jsonBtn.addEventListener('click', _openStoryJsonPanel);

  // Populate the "Scenes" count (1–10, default 3).
  for (var _i = 1; _i <= 10; _i++) {
    var _opt = document.createElement('option');
    _opt.value = String(_i);
    _opt.textContent = _i === 1 ? '1 scene' : (_i + ' scenes');
    scenesSelect.appendChild(_opt);
  }
  scenesSelect.value = '3';

  var _storyAutoSimilarity = false; // true if WE turned "Visual similarity" on
  var _storyVisionCache = null;     // { url, description }

  // Pin/unpin the seed for the batch by driving the existing Guided-mode
  // "Visual similarity" toggle (params step) — reuses guidedFixedSeed as-is
  // instead of reimplementing seed logic.
  function _ensureSimilarity(on) {
    var simToggle = document.getElementById('ncf-similarity-toggle');
    if (!simToggle) return;
    var isOn = simToggle.getAttribute('aria-pressed') === 'true';
    if (on && !isOn) {
      simToggle.click();
      _storyAutoSimilarity = true;
    } else if (!on && isOn && _storyAutoSimilarity) {
      simToggle.click();
      _storyAutoSimilarity = false;
    }
  }

  consistencyToggle.addEventListener('change', function () {
    _ensureSimilarity(consistencyToggle.checked);
  });

  // Auto-resize textarea as user types
  storyInput.addEventListener('input', function () {
    storyInput.style.height = 'auto';
    storyInput.style.height = Math.min(storyInput.scrollHeight, 120) + 'px';
  });

  // Ctrl+Enter submits
  storyInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      _submitStoryInstruction();
    }
  });

  sendBtn.addEventListener('click', function () {
    _submitStoryInstruction();
  });

  // Vision-describe the last generated image (character + environment +
  // style), cached per image URL so it isn't re-run every scene.
  function _visionDescribeLastImage() {
    var _lastIdx = _lastValidSessionImageIdx();
    if (_lastIdx < 0) return Promise.resolve('');
    var entry = sessionImages[_lastIdx];
    if (_storyVisionCache && _storyVisionCache.url === entry.url) {
      return Promise.resolve(_storyVisionCache.description);
    }
    return _imgUrlToDataUrl(entry.url).then(function (dataUrl) {
      return fetch('/api/models/chat/describe-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          imageDataUrl: dataUrl,
          describeType: 'prompt',
          describeScope: 'full',
          describeFormat: 'paragraph',
        }),
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (data.error) throw new Error(data.error);
        var desc = String(data.description || '').trim();
        _storyVisionCache = { url: entry.url, description: desc };
        return desc;
      });
    });
  }

  // Three visual states for the send button:
  //  - idle:      default accent, plain arrow icon.
  //  - vision:    blue + blinking eye icon — describing the previous scene's
  //               image with the vision model before writing the next one.
  //  - composing: orange + spinning ring (same look as the Assist "Write"
  //               button's .is-composing, flow-render-all.js runLLM()) —
  //               writing the scene text and/or generating its image.
  var _NCF_EYE_ICON =
    '<svg class="ncf-send-eye-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>';
  function _setSendBtnState(state) {
    var arrowSvg = sendBtn.querySelector('svg:not(.nsc-ring):not(.ncf-send-eye-icon)');
    sendBtn.classList.toggle('is-vision', state === 'vision');
    sendBtn.classList.toggle('is-composing', state === 'composing');

    var existingRing = sendBtn.querySelector('.nsc-ring');
    var existingEye   = sendBtn.querySelector('.ncf-send-eye-icon');

    if (state === 'composing') {
      if (existingEye) existingEye.remove();
      if (arrowSvg) arrowSvg.style.display = 'none';
      if (!existingRing) {
        var ring = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        ring.setAttribute('class', 'nsc-ring nsc-ring--indeterminate');
        ring.setAttribute('viewBox', '0 0 44 44');
        ring.setAttribute('aria-hidden', 'true');
        ring.innerHTML = '<circle class="nsc-ring-bg" cx="22" cy="22" r="18"/><circle class="nsc-ring-fill" cx="22" cy="22" r="18"/>';
        sendBtn.insertBefore(ring, arrowSvg || sendBtn.firstChild);
      }
    } else if (state === 'vision') {
      if (existingRing) existingRing.remove();
      if (arrowSvg) arrowSvg.style.display = 'none';
      if (!existingEye) sendBtn.insertAdjacentHTML('afterbegin', _NCF_EYE_ICON);
    } else {
      if (existingRing) existingRing.remove();
      if (existingEye) existingEye.remove();
      if (arrowSvg) arrowSvg.style.display = '';
    }
  }

  // Writes and generates the batch SEQUENTIALLY, one scene at a time, instead
  // of asking the LLM for all N scene prompts up front in a single call. This
  // is what lets vision actually chain: scene 2's vision pass looks at the
  // image scene 1 just produced (not the image that existed before this
  // whole batch started), scene 3's looks at scene 2's, and so on — each
  // scene is genuinely grounded in the one immediately before it.
  async function _submitStoryInstruction() {
    if (sendBtn.disabled) return;

    var text = storyInput.value.trim();
    var sceneCount = Math.max(1, Math.min(10, parseInt(scenesSelect.value, 10) || 1));
    var reasoningLevel = (reasoningSelect && reasoningSelect.value) || 'off';
    var visionOn = !!(consistencyToggle && consistencyToggle.checked);

    var storyDef = allSteps.find(function (s) { return s.calls === 'llm.story_continue'; });
    var actionStep = allSteps.find(function (s) { return s.type === 'action'; });
    var scenePromptTa = document.getElementById('ncf-input-scene_prompt');

    if (!actionStep) {
      if (generateStatus) generateStatus.textContent = '✗ Generate step not found';
      return;
    }

    sendBtn.disabled = true;
    storyInput.value = '';
    storyInput.style.height = 'auto';
    if (generateBtn && generateBtn.disabled) generateBtn.removeAttribute('disabled');

    _ensureSimilarity(visionOn);

    var genStepDef = Object.assign({}, actionStep, { on_success: null });

    try {
      for (var i = 0; i < sceneCount; i++) {
        var sceneLabel = sceneCount > 1 ? ' (' + (i + 1) + '/' + sceneCount + ')' : '';
        // The typed instruction is one-time direction for kicking off this
        // batch, not a standing order — only scene 1 of the batch should see
        // it. Resending it unchanged to every scene in the batch (old bug)
        // told the model the exact same "what happens next" on every single
        // turn, so it kept re-describing/embellishing that one instruction
        // instead of progressing past it. From scene 2 of the batch onward,
        // leave it blank and let narrative_context/history carry it forward.
        var turnInstruction = i === 0 ? text : '';

        var visionContext = '';
        if (visionOn) {
          _setSendBtnState('vision');
          if (typeof _setBusyStatus === 'function') {
            _setBusyStatus(generateStatus, 'Looking at the last scene…' + sceneLabel);
          } else if (generateStatus) {
            generateStatus.textContent = 'Looking at the last scene…' + sceneLabel;
          }
          visionContext = await _visionDescribeLastImage();
        }

        _setSendBtnState('composing');
        if (typeof _setBusyStatus === 'function') {
          _setBusyStatus(generateStatus, 'Writing next scene…' + sceneLabel);
        } else if (generateStatus) {
          generateStatus.textContent = 'Writing next scene…' + sceneLabel;
        }

        var worldCtx = sessionState.world_context
          || getVal('world', 'prompt_text')
          || getVal('scene_prompt', 'prompt_text')
          || '';
        var history = Array.isArray(sessionState.story_history) ? sessionState.story_history : [];
        var styleRef = (storyDef && storyDef.context_from && storyDef.context_from.civitai_style)
          ? (resolveRef(storyDef.context_from.civitai_style) || undefined)
          : undefined;

        // Bounded narrative window (last 1-3 plot summaries from the story
        // project JSON) — never the full accumulated story. story_history
        // above still carries the last few raw prompts for visual detail;
        // this is separate, short, plot-only context. See
        // story_project_service.py / GET /api/stories/<id>/context.
        var storyId = await _ensureStoryProject();
        var narrativeContext = '';
        if (storyId) {
          try {
            var ctxRes = await fetch('/api/stories/' + storyId + '/context?n=3');
            var ctxData = await ctxRes.json();
            narrativeContext = Array.isArray(ctxData.recent_summaries) ? ctxData.recent_summaries.join(' ') : '';
          } catch (_) { /* fine without it */ }
        }

        var res = await fetch('/api/models/chat/studio-story', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            worldContext: worldCtx,
            storyHistory: history,
            narrativeContext: narrativeContext || undefined,
            instruction: turnInstruction,
            level: selectedLevel,
            flair: flairValue,
            genre: selectedGenre || undefined,
            systemPrompt: (storyDef && storyDef.system_prompt) || undefined,
            styleReference: styleRef,
            reasoningLevel: reasoningLevel,
            sceneCount: 1,
            visionContext: visionContext || undefined,
            characterAnchor: sessionState.character_anchor || undefined,
          }),
        });
        var data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'LLM error');
        var sceneText = data.scene || (Array.isArray(data.scenes) && data.scenes[0]) || '';
        if (!sceneText) throw new Error('No scene returned');
        var narrativeSummary = data.narrativeSummary || '';
        // Without this, every call in this loop lacked characterAnchor, so
        // the backend re-triggered "derive a NEW anchor" mode (scene_count===1
        // + no character_anchor) on EVERY scene instead of just scene 1 —
        // the model kept re-establishing who the character is instead of
        // advancing the plot, which is why the story would stall/repeat.
        if (data.anchor && !sessionState.character_anchor) sessionState.character_anchor = data.anchor;

        if (scenePromptTa) {
          scenePromptTa.value = sceneText;
          if (scenePromptTa.disabled) {
            scenePromptTa.disabled = false;
            scenePromptTa.classList.remove('is-prefill-pending');
            scenePromptTa.placeholder = '';
          }
          scenePromptTa.dispatchEvent(new Event('input', { bubbles: true }));
        }
        setVal('scene_prompt', 'prompt_text', sceneText);

        if (typeof _setBusyStatus === 'function') {
          _setBusyStatus(generateStatus, 'Generating scene…' + sceneLabel);
        } else if (generateStatus) {
          generateStatus.textContent = 'Generating scene…' + sceneLabel;
        }

        await runGenerate(genStepDef);

        // Bookkeeping runGenerate's own on_success would normally do — done
        // manually since it's stripped above (this loop drives it instead).
        if (!Array.isArray(sessionState.story_history)) sessionState.story_history = [];
        sessionState.story_history.push(sceneText);
        sessionState.scene_index = (Number(sessionState.scene_index) || 0) + 1;

        var justGenIdx = _lastValidSessionImageIdx();
        // Must be awaited: the NEXT iteration of this same loop immediately
        // fetches GET /api/stories/<id>/context, which reads this scene back
        // off disk. Without waiting for the POST above to land first, a
        // multi-scene batch (Scenes > 1, one instruction) races ahead and
        // reads a context window that doesn't include the scene that just
        // finished — so the model writes the next scene without knowing it
        // happened, and the story stalls/repeats within that same batch.
        // Single-scene sends (Scenes: 1, user re-triggering by hand) never
        // hit this race, since there's always a real gap before the next
        // click — which is why 1-4 looked fine but a 3-scene batch didn't.
        await _persistStoryScene({
          narrativeSummary: narrativeSummary,
          promptUsed: sceneText,
          style: selectedGenre || '',
          visionSummary: visionContext || '',
          imagePath: justGenIdx >= 0 ? sessionImages[justGenIdx].url : '',
        });
      }
    } catch (err) {
      if (generateStatus) {
        generateStatus.textContent = '✗ ' + (err.message || 'Story generation failed');
        generateStatus.classList.remove('is-busy');
      }
    } finally {
      sendBtn.disabled = false;
      _setSendBtnState('idle');
      storyInput.focus();
    }
  }
}

// ── Toolbar "Refine" button — batch-send every result to a refine flow ─────
// Opens the same right-side options panel used for Style Transfer's "Choose
// a Style" picker (search box + category tree + card grid — see
// _openStylePickerPanel in flow-step-workflow-params.js), populated with
// refine flows instead of styles and reusing the .cs-card look from the
// Refine hub (nomad_studio.html) so it reads as the same component. Sends
// the full sessionImages list (every image generated in this flow session)
// as input — the receiving flow's source-image picker already lets you
// drop individual images before running.
var _refineFlowsCache = null;

function _refineGroupLabel(groupId) {
  if (!groupId || groupId === 'core') return 'Core';
  return groupId.replace(/[-_]/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
}

// issue #69: no description/tags — this panel's cards only ever need to
// answer "which flow do I pick", and the extra content (card_desc, tags,
// the complexity indicator) was what made the height-clipping bug (#29)
// possible in the first place — one card with more text than its grid
// row-mates got squeezed to whatever shorter neighbor set the row height.
// Title + icon alone can't reproduce that: there's nothing left to clip.

// Real model brand marks (LobeHub Icons mono set) — copied verbatim from
// nomad_studio.html's qwen_logo()/flux_logo() Jinja macros so the exact
// same glyphs render here.
var _QWEN_LOGO_SVG = '<svg viewBox="0 0 24 24" style="fill: var(--cs-card-accent, var(--accent)); stroke: none;" fill-rule="evenodd"><title>Qwen</title><path d="M12.604 1.34c.393.69.784 1.382 1.174 2.075a.18.18 0 00.157.091h5.552c.174 0 .322.11.446.327l1.454 2.57c.19.337.24.478.024.837-.26.43-.513.864-.76 1.3l-.367.658c-.106.196-.223.28-.04.512l2.652 4.637c.172.301.111.494-.043.77-.437.785-.882 1.564-1.335 2.34-.159.272-.352.375-.68.37-.777-.016-1.552-.01-2.327.016a.099.099 0 00-.081.05 575.097 575.097 0 01-2.705 4.74c-.169.293-.38.363-.725.364-.997.003-2.002.004-3.017.002a.537.537 0 01-.465-.271l-1.335-2.323a.09.09 0 00-.083-.049H4.982c-.285.03-.553-.001-.805-.092l-1.603-2.77a.543.543 0 01-.002-.54l1.207-2.12a.198.198 0 000-.197 550.951 550.951 0 01-1.875-3.272l-.79-1.395c-.16-.31-.173-.496.095-.965.465-.813.927-1.625 1.387-2.436.132-.234.304-.334.584-.335a338.3 338.3 0 012.589-.001.124.124 0 00.107-.063l2.806-4.895a.488.488 0 01.422-.246c.524-.001 1.053 0 1.583-.006L11.704 1c.341-.003.724.032.9.34zm-3.432.403a.06.06 0 00-.052.03L6.254 6.788a.157.157 0 01-.135.078H3.253c-.056 0-.07.025-.041.074l5.81 10.156c.025.042.013.062-.034.063l-2.795.015a.218.218 0 00-.2.116l-1.32 2.31c-.044.078-.021.118.068.118l5.716.008c.046 0 .08.02.104.061l1.403 2.454c.046.081.092.082.139 0l5.006-8.76.783-1.382a.055.055 0 01.096 0l1.424 2.53a.122.122 0 00.107.062l2.763-.02a.04.04 0 00.035-.02.041.041 0 000-.04l-2.9-5.086a.108.108 0 010-.113l.293-.507 1.12-1.977c.024-.041.012-.062-.035-.062H9.2c-.059 0-.073-.026-.043-.077l1.434-2.505a.107.107 0 000-.114L9.225 1.774a.06.06 0 00-.053-.031zm6.29 8.02c.046 0 .058.02.034.06l-.832 1.465-2.613 4.585a.056.056 0 01-.05.029.058.058 0 01-.05-.029L8.498 9.841c-.02-.034-.01-.052.028-.054l.216-.012 6.722-.012z"/></svg>';
var _FLUX_LOGO_SVG = '<svg viewBox="0 0 24 24" style="fill: var(--cs-card-accent, var(--accent)); stroke: none;" fill-rule="evenodd"><title>Flux</title><path d="M0 20.683L12.01 2.5 24 20.683h-2.233L12.009 5.878 3.471 18.806h12.122l1.239 1.877H0z"/><path d="M8.069 16.724l2.073-3.115 2.074 3.115H8.069zM18.24 20.683l-5.668-8.707h2.177l5.686 8.707h-2.196zM19.74 11.676l2.13-3.19 2.13 3.19h-4.26z"/></svg>';

// Same per-action icon mapping as nomad_studio.html's refine_icon() Jinja
// macro — ported to JS since this panel's cards are built client-side from
// /api/flows (which does include each flow's `action`), not server-rendered.
// Kept in the same order/cases so the two stay easy to diff against each
// other if one changes.
function _refineFlowIconSvg(action, group) {
  switch (action) {
    case 'pixel_matcher':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="5" height="5" fill="currentColor" stroke="none"/><rect x="10" y="3" width="5" height="5" fill="currentColor" stroke="none" opacity="0.5"/><rect x="17" y="3" width="4" height="5" fill="currentColor" stroke="none"/><rect x="3" y="10" width="5" height="5" fill="currentColor" stroke="none" opacity="0.5"/><rect x="10" y="10" width="5" height="5" fill="currentColor" stroke="none"/><rect x="17" y="10" width="4" height="5" fill="currentColor" stroke="none" opacity="0.5"/><rect x="3" y="17" width="5" height="4" fill="currentColor" stroke="none"/><rect x="10" y="17" width="5" height="4" fill="currentColor" stroke="none" opacity="0.5"/><rect x="17" y="17" width="4" height="4" fill="currentColor" stroke="none"/></svg>';
    case 'upscale_single':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/><path d="M5 19h14"/></svg>';
    case 'upscale_tiled':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="3" width="8" height="8" rx="1"/><rect x="3" y="13" width="8" height="8" rx="1"/><rect x="13" y="13" width="8" height="8" rx="1"/><path d="M12 2v20M2 12h20" stroke-width="0.75" stroke-dasharray="2 2"/></svg>';
    case 'upscale_2xtiled':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="9" height="9" rx="1"/><rect x="13" y="2" width="9" height="9" rx="1"/><rect x="2" y="13" width="9" height="9" rx="1"/><rect x="13" y="13" width="9" height="9" rx="1"/><path d="M12 7v5M7 12h5M17 12h-2M12 17v-2"/></svg>';
    case 'upscale_megascale':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-9 9M3 21l9-9"/></svg>';
    case 'upscale_klein_4b_single':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M12 15V9M9 12l3-3 3 3"/></svg>';
    case 'upscale_model':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></svg>';
    case 'layer_composer':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l9 5-9 5-9-5 9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 17l9 5 9-5"/></svg>';
    case 'edit_fluxklein_9b_basic':
    case 'edit_fluxklein_4b_basic':
    case 'edit_fluxklein_9b_restore':
      return _FLUX_LOGO_SVG;
    case 'edit_qwen_2511_basic':
      return _QWEN_LOGO_SVG;
    case 'skin_detailer_klein_9b':
    case 'skin_detailer_klein_4b':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M5.5 9c1-1.4 2-1.4 3 0s2 1.4 3 0 2-1.4 3-1.4 2 1.4 3 1.4"/><path d="M5.5 13c1-1.4 2-1.4 3 0s2 1.4 3 0 2-1.4 3-1.4 2 1.4 3 1.4"/><path d="M5.5 17c1-1.4 2-1.4 3 0s2 1.4 3 0 2-1.4 3-1.4 2 1.4 3 1.4"/></svg>';
    case 'qwen_2511_relight':
    case 'upscale_qwen_2511_relight':
    case 'relight':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 22h4M12 2a7 7 0 017 7c0 2.5-1.3 4.7-3.3 6H8.3A7 7 0 015 9a7 7 0 017-7z"/><path d="M12 6v2M7.5 7.5l1.5 1.5M16.5 7.5l-1.5 1.5"/></svg>';
    case 'qwen_2511_restore_light':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="9" r="3"/><path d="M12 2v2M12 14v1.5M5.6 4.6l1.4 1.4M15 14l1.4 1.4M3 9h2M17 9h2M5.6 13.4l1.4-1.4M15 4l1.4 1.4"/><path d="M5 20c1.5-2 3-3 3.5-3s1.5.8 2.5 1.5c1-.7 2-1.5 2.5-1.5S16 18 18 20" stroke-linecap="round"/></svg>';
    case 'qwen_2511_replace_white':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><circle cx="12" cy="9" r="3"/><path d="M8 20v-2a4 4 0 018 0v2"/><path d="M2 15l4-3 3 2 4-4 4 3 4-2"/></svg>';
    case 'smart_selection':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 5h3M16 5h3M19 5v3M19 16v3M19 19h-3M8 19H5M5 19v-3M5 8V5" stroke-dasharray="2.5 2.5"/><circle cx="12" cy="12" r="4"/></svg>';
    case 'smart_selection_fill':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 5h3M16 5h3M19 5v3M19 16v3M19 19h-3M8 19H5M5 19v-3M5 8V5" stroke-dasharray="2.5 2.5"/><path d="M9 12l2 2 4-4"/></svg>';
    case 'remove_bg':
    case 'remove_bg_multi':
    case 'remove_bg_simple':
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="10" y="2" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="18" y="2" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="6" y="6" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="14" y="6" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="2" y="10" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="18" y="10" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="6" y="14" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="14" y="14" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="2" y="18" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="10" y="18" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><rect x="18" y="18" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.25" stroke="none"/><circle cx="12" cy="9" r="3"/><path d="M7 21v-1a5 5 0 0110 0v1"/></svg>';
    default:
      switch (group) {
        case 'creator-pack':
          return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="12" cy="10" r="3"/><path d="M7 19c0-2.8 2.2-4 5-4s5 1.2 5 4"/></svg>';
        case 'look-book':
          return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4a1.5 1.5 0 011.5 1.5c0 .7-.4 1.3-1 1.6"/><path d="M12 7l8.5 6.5c.9.7.4 2-.7 2H4.2c-1.1 0-1.6-1.3-.7-2L12 7z"/><path d="M4 19.5h16"/></svg>';
        case 'photo-editing':
          return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h10M4 12h16M4 18h10"/><circle cx="16" cy="6" r="2"/><circle cx="8" cy="18" r="2"/></svg>';
        case 'portrait-fix':
          return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="12" r="7"/><path d="M8.5 10.5h.01M13.5 10.5h.01M8.5 14c.8.8 1.6 1.2 2.5 1.2s1.7-.4 2.5-1.2"/><path d="M18 5l.8 1.8 1.7.7-1.7.7-.8 1.8-.8-1.8L15.5 7l1.7-.7z"/></svg>';
        case 'presets':
          return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 100 20 2 2 0 002-2c0-.6-.3-1.1-.6-1.5-.3-.4-.6-.8-.6-1.3 0-.9.7-1.5 1.6-1.5H16a4 4 0 004-4c0-5-3.5-9.7-8-9.7z"/><circle cx="7.5" cy="10.5" r="1.2" fill="currentColor" stroke="none"/><circle cx="11" cy="7" r="1.2" fill="currentColor" stroke="none"/><circle cx="15.5" cy="8.5" r="1.2" fill="currentColor" stroke="none"/></svg>';
        default:
          return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
      }
  }
}

// List row (was a "hero" card grid — issue: adding a "Create Session" row +
// hunting one flow among wide 3-column cards didn't read as a picker you
// scan quickly; a plain list scans top-to-bottom like the category tree
// beside it).
function _refineFlowRowHtml(f) {
  return (
    '<button type="button" class="ncf-refine-picker-row" data-refine-flow-id="' + escHtml(f.id) + '" aria-label="' + escHtml(f.label || f.id) + '">' +
      '<span class="ncf-refine-picker-row-icon" aria-hidden="true">' + _refineFlowIconSvg(f.action, f.group) + '</span>' +
      '<span class="ncf-refine-picker-row-text">' +
        '<span class="ncf-refine-picker-row-name">' + escHtml(f.label || f.id) + '</span>' +
        (f.card_desc ? '<span class="ncf-refine-picker-row-desc">' + escHtml(f.card_desc) + '</span>' : '') +
      '</span>' +
      '<svg class="ncf-refine-picker-row-chevron" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>' +
    '</button>'
  );
}

function _openRefinePickerPanel() {
  openOptionsPanel('Choose a Refine Flow', function (body) {
    // "Create Session" is only offered when this tab isn't already tracking
    // a pending session (Session.getPending()) — a flow mounted inside an
    // existing Session (via "Add Flow"/reopening a step) already appends its
    // outputs to that same session on its own; forcing a second, unrelated
    // session on top of it here would just be confusing. See
    // _sendResultsToRefineWithSession below for what turning it on does.
    var offerSession = !!(window.NomadSession && NomadSession.getPending && !NomadSession.getPending());
    var sessionRowHtml = offerSession
      ? (
        '<div class="ncf-refine-session-row">' +
          '<button type="button" class="create-basic-similarity-toggle off ncf-refine-session-toggle" id="ncf-refine-session-toggle" aria-pressed="false">' +
            '<span class="create-basic-similarity-label">' + escHtml(tF('Create Session')) + '</span>' +
            '<div class="create-basic-switch"><div class="create-basic-switch-thumb"></div></div>' +
          '</button>' +
          '<input type="text" class="nsc-input ncf-refine-session-name" id="ncf-refine-session-name" placeholder="' + escHtml(tF('Session name…')) + '" aria-label="' + escHtml(tF('Session name…')) + '" hidden>' +
        '</div>'
      )
      : '';
    body.innerHTML =
      '<div class="ncf-style-picker-search-row">' +
        '<input type="text" class="nsc-input ncf-style-picker-search" placeholder="Search refine flows…" aria-label="Search refine flows">' +
      '</div>' +
      sessionRowHtml +
      '<div class="ncf-style-picker-layout">' +
        '<nav class="ncf-style-picker-tree ncf-style-picker-tree--narrow" aria-label="Refine categories"></nav>' +
        '<div class="ncf-style-picker-grid ncf-style-picker-grid--list"></div>' +
      '</div>';
    var searchInput = body.querySelector('.ncf-style-picker-search');
    var treeEl = body.querySelector('.ncf-style-picker-tree');
    var gridEl = body.querySelector('.ncf-style-picker-grid');
    var sessionToggleBtn = body.querySelector('#ncf-refine-session-toggle');
    var sessionNameInput = body.querySelector('#ncf-refine-session-name');

    if (sessionToggleBtn) {
      sessionToggleBtn.addEventListener('click', function () {
        var nowOn = sessionToggleBtn.classList.toggle('off') === false;
        sessionToggleBtn.setAttribute('aria-pressed', nowOn ? 'true' : 'false');
        if (sessionNameInput) {
          sessionNameInput.hidden = !nowOn;
          if (nowOn) sessionNameInput.focus();
        }
      });
    }

    var allFlows = [];
    var groups = []; // [{ id, label, count }]
    var selectedGroup = '';
    var query = '';

    function renderTree() {
      var items = '<button type="button" class="lib-style-cat-tree-item' + (selectedGroup === '' ? ' is-active' : '') + '" data-group="">All</button>';
      items += groups.map(function (g) {
        return '<button type="button" class="lib-style-cat-tree-item' + (selectedGroup === g.id ? ' is-active' : '') + '" data-group="' + escHtml(g.id) + '">' + escHtml(g.label) + '</button>';
      }).join('');
      treeEl.innerHTML = items;
    }

    function renderGrid() {
      var q = query.trim().toLowerCase();
      var filtered = allFlows.filter(function (f) {
        if (selectedGroup && (f.group || 'core') !== selectedGroup) return false;
        if (q) {
          var hay = [f.label, f.card_desc, f.description].concat(f.card_tags || []).join(' ').toLowerCase();
          if (hay.indexOf(q) === -1) return false;
        }
        return true;
      });
      if (!filtered.length) {
        gridEl.innerHTML = '<p class="ncf-style-picker-empty muted-note">' +
          (allFlows.length ? 'No refine flows match.' : 'No refine flows available.') +
          '</p>';
        return;
      }
      gridEl.innerHTML = filtered.map(_refineFlowRowHtml).join('');
    }

    treeEl.addEventListener('click', function (e) {
      var item = e.target.closest('.lib-style-cat-tree-item');
      if (!item) return;
      selectedGroup = item.dataset.group || '';
      renderTree();
      renderGrid();
    });

    searchInput.addEventListener('input', function () {
      query = searchInput.value;
      renderGrid();
    });

    gridEl.addEventListener('click', function (e) {
      var row = e.target.closest('.ncf-refine-picker-row');
      if (!row) return;
      var flowId = row.dataset.refineFlowId;
      var makeSession = sessionToggleBtn && !sessionToggleBtn.classList.contains('off');
      if (makeSession) {
        var flow = allFlows.filter(function (f) { return f.id === flowId; })[0];
        var name = (sessionNameInput && sessionNameInput.value.trim()) ||
          tF('Untitled Session');
        _sendResultsToRefineWithSession(flowId, name, flow && flow.label);
      } else {
        _sendResultsToRefine(flowId);
      }
    });

    function afterLoad(flows) {
      allFlows = flows;
      var counts = {};
      flows.forEach(function (f) { var g = f.group || 'core'; counts[g] = (counts[g] || 0) + 1; });
      groups = Object.keys(counts)
        .sort(function (a, b) { return (a === 'core' ? -1 : b === 'core' ? 1 : _refineGroupLabel(a).localeCompare(_refineGroupLabel(b))); })
        .map(function (id) { return { id: id, label: _refineGroupLabel(id), count: counts[id] }; });
      renderTree();
      renderGrid();
    }

    if (_refineFlowsCache) {
      afterLoad(_refineFlowsCache);
      return;
    }
    gridEl.innerHTML = '<p class="ncf-style-picker-empty muted-note">Loading…</p>';
    fetch('/api/flows?category=refine&status=active&available=true')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _refineFlowsCache = (data && Array.isArray(data.flows)) ? data.flows : [];
        afterLoad(_refineFlowsCache);
      })
      .catch(function () {
        gridEl.innerHTML = '<p class="ncf-style-picker-empty muted-note">Could not load refine flows.</p>';
      });
  // 'xl' (720px) was sized for the old card grid; a plain scan-down list
  // doesn't need that width — 'wide' (420px, still room for the category
  // tree beside it) matches the content now.
  }, { wide: true, flexBody: true });
}

var _refineToolbarBtn = document.getElementById('ncf-gallery-refine-btn');
if (_refineToolbarBtn) _refineToolbarBtn.addEventListener('click', _openRefinePickerPanel);

// sessionImages entries are tombstoned to `null` on delete (see
// _removeSessionImageForCard) to keep other cards' lightbox indices stable —
// guard against that here instead of assuming every slot is still an object.
function _refineBatchImageUrls() {
  return (typeof sessionImages !== 'undefined' ? sessionImages : [])
    .map(function (s) { return s && s.url; }).filter(Boolean);
}

function _navigateToRefineBatch(slug, urls) {
  try { sessionStorage.setItem('oj-refine-batch-images-v1', JSON.stringify(urls)); } catch (_) {}
  window.location.href = '/nomad-studio/refine/' + slug;
}

function _sendResultsToRefine(flowId) {
  if (!flowId) return;
  var slug = flowId.replace(/^refine\./, '').replace(/_/g, '-'); // e.g. "refine.upscale_klein_4b_single" → "upscale-klein-4b-single"
  var urls = _refineBatchImageUrls();
  if (!urls.length) return;
  _navigateToRefineBatch(slug, urls);
}

// "Create Session" toggle on the refine picker (_openRefinePickerPanel): the
// current Create/Refine/Mix flow's own results become the session's first
// step, the picked refine flow becomes the second. Every flow inside a
// Session today mounts natively in the workspace document (sessionMountFlow,
// nomad_studio.js) — same as "Add Flow" already does — instead of navigating
// to its own standalone page; this tab (a plain Create/Refine/Mix page) has
// no native container of its own to mount into, so it can't call
// sessionMountFlow directly. Handing the workspace page a one-shot
// "ns-session-autolaunch-v1" instruction and navigating it there instead
// lets IT do the actual mount once loaded (see the autolaunch consumer next
// to _csOpenStandalone in nomad_studio.js) — Session.setPending() only ever
// gets set from within that native-mount context, same as "Add Flow".
function _sendResultsToRefineWithSession(flowId, sessionName, refineFlowLabel) {
  if (!flowId) return;
  var action = flowId.replace(/^refine\./, ''); // underscore form, e.g. "upscale_klein_4b_single"
  var slug = action.replace(/_/g, '-');
  var urls = _refineBatchImageUrls();
  if (!urls.length) return;

  var Session = window.NomadSession;
  if (!Session || !Session.createRemote) { _navigateToRefineBatch(slug, urls); return; }

  var snap = (typeof _collectFlowSnapshot === 'function') ? _collectFlowSnapshot() : null;
  var createType = (snap && snap.type) || (typeof fid !== 'undefined' ? fid : 'create.simple');
  var typeParts = String(createType).split('.');
  var createCategory = typeParts[0] || 'create';
  var createAction = typeParts.slice(1).join('.') || null;

  var firstStep = {
    id: 'step-' + Date.now() + '-' + Math.floor(Math.random() * 1e4),
    flowLabel: (snap && snap.label) || 'Create',
    flowCategory: createCategory,
    flowAction: createAction,
    params: (snap && snap.data && snap.data.params) || null,
    imageUrl: urls[0],
    images: urls.slice(),
    parentId: null,
    createdAt: new Date().toISOString(),
  };

  function afterSession(session) {
    if (!session || !session.id) { _navigateToRefineBatch(slug, urls); return; }

    // Wait for the step to actually reach the server before navigating: the
    // session workspace page we're about to land on re-GETs this same
    // session on load (Session.syncFromServer), and its merge always trusts
    // the server's copy over the local cache — a plain fire-and-forget
    // addStep() here could lose the race and land on a session that looks
    // like it has no first step yet. addStepRemote resolves once the PUT is
    // actually done (or has failed — either way we don't wait forever).
    var stepAdded = Session.addStepRemote
      ? Session.addStepRemote(session.id, firstStep)
      : Promise.resolve(Session.addStep ? Session.addStep(session.id, firstStep) : false);

    stepAdded.then(function () {
      try {
        sessionStorage.setItem('ns-session-autolaunch-v1', JSON.stringify({
          sessionId: session.id,
          category: 'refine',
          action: action,
          label: refineFlowLabel || action,
          parentId: firstStep.id,
        }));
      } catch (_) {}
      // Same batch-image preload the plain (non-session) path uses — read by
      // the refine flow's image_picker once sessionMountFlow actually mounts
      // it (flow-step-image-picker.js's BATCH_SRC_KEY).
      try { sessionStorage.setItem('oj-refine-batch-images-v1', JSON.stringify(urls)); } catch (_) {}
      window.location.href = '/nomad-studio/session/' + encodeURIComponent(session.id);
    });
  }

  Session.createRemote(sessionName).then(afterSession).catch(function () {
    afterSession(Session.create ? Session.create(sessionName) : null);
  });
}

// ══════════════════════════════════════════════════════════════════════════
// SHARE MODAL — image (+prompt) or before/after fade video
// ══════════════════════════════════════════════════════════════════════════
// Built once, lazily, and reused for every card — reuses the existing
// .nse-modal chrome so it matches every other modal in the app with no new
// template markup. Video (fade-compare) is only offered when a beforeUrl
// was passed in from a refine flow (see addToFeed / _runRefine).
var _shareModalEl = null;
var _shareState = { imgUrl: '', beforeUrl: '', promptStr: '', videoBlobUrl: '', videoMime: '', videoExt: '' };

function _ensureShareModal() {
  if (_shareModalEl) return _shareModalEl;
  var backdrop = document.createElement('div');
  backdrop.className = 'nse-modal-backdrop';
  backdrop.id = 'nss-share-modal-backdrop';
  backdrop.hidden = true;
  backdrop.innerHTML =
    '<div class="nse-modal nss-share-modal">' +
      '<div class="nse-modal-header">' +
        '<span class="nse-modal-title">Share</span>' +
        '<button type="button" class="nse-modal-close" id="nss-share-close" aria-label="Close">' +
          '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="nse-modal-body">' +
        '<div class="nss-share-tabs">' +
          '<button type="button" class="nss-share-tab is-active" id="nss-share-tab-img" aria-label="Share image">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="1.5"/><path d="M21 15l-5-5-9 9"/></svg>' +
          '</button>' +
          '<button type="button" class="nss-share-tab" id="nss-share-tab-vid" aria-label="Share video">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="15" height="14" rx="2"/><path d="M17 9l5-3v12l-5-3"/></svg>' +
          '</button>' +
        '</div>' +
        '<div class="nss-share-pane is-active" id="nss-share-pane-img">' +
          '<img id="nss-share-img-preview" alt="">' +
          '<textarea id="nss-share-prompt" class="nss-share-prompt" readonly></textarea>' +
        '</div>' +
        '<div class="nss-share-pane" id="nss-share-pane-vid">' +
          '<div class="nss-share-vid-stage">' +
            // Canvas is the actual captureStream() source — kept rendering
            // at all times but visually hidden (opacity:0, absolute, behind
            // the placeholder/video) so the user only ever sees either the
            // "recording…" placeholder or the finished video, never the
            // raw fade loop driving the capture.
            '<canvas id="nss-share-canvas" class="nss-share-canvas-hidden" width="600" height="600"></canvas>' +
            '<div id="nss-share-vid-placeholder" class="nss-share-vid-placeholder">' +
              '<svg class="nss-share-spin" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.5" stroke-dasharray="28 56" stroke-linecap="round"/></svg>' +
              '<span id="nss-share-vid-status">Recording…</span>' +
            '</div>' +
            '<video id="nss-share-video" controls loop hidden></video>' +
          '</div>' +
          '<button type="button" class="nse-modal-secondary nss-share-rerecord" id="nss-share-record" aria-label="Re-record video">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><circle cx="12" cy="12" r="7"/></svg><span>Re-record</span>' +
          '</button>' +
        '</div>' +
        // Quick-share row — X and WhatsApp have real web "compose" intents
        // that accept prefilled text (no direct file attach possible from
        // JS on any of these, that's a platform security restriction, not
        // ours — see _quickShareTo). Instagram and TikTok have no such web
        // intent at all; those two just copy the caption and open the
        // upload page so the already-downloaded file can be dropped in.
        '<div class="nss-share-quick-row">' +
          '<button type="button" class="nss-share-quick-btn" data-platform="x" aria-label="Share to X" title="Share to X">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M4 3l7.2 9.4L4.3 21h2.3l6-6.9L17.4 21H20l-7.6-9.9L19.4 3h-2.3l-5.6 6.4L8 3H4z"/></svg>' +
          '</button>' +
          '<button type="button" class="nss-share-quick-btn" data-platform="whatsapp" aria-label="Share to WhatsApp" title="Share to WhatsApp">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 10-14.6 4.6L4 21l4.6-1.2A8 8 0 0020 12z"/><path d="M9 10c0 3 2 5 5 5"/><circle cx="9" cy="10" r=".6" fill="currentColor"/><circle cx="12.5" cy="14.5" r=".6" fill="currentColor"/></svg>' +
          '</button>' +
          '<button type="button" class="nss-share-quick-btn" data-platform="instagram" aria-label="Share to Instagram" title="Share to Instagram">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.2" cy="6.8" r="1" fill="currentColor" stroke="none"/></svg>' +
          '</button>' +
          '<button type="button" class="nss-share-quick-btn" data-platform="tiktok" aria-label="Share to TikTok" title="Share to TikTok">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M14 3v10.5a2.5 2.5 0 11-2-2.45V9a4.5 4.5 0 104.5 4.5V9.8a6 6 0 003.5 1.2V8.9a4 4 0 01-2.9-1.6A4 4 0 0116.2 5H14z"/></svg>' +
          '</button>' +
        '</div>' +
      '</div>' +
      '<div class="nse-modal-footer">' +
        '<button type="button" class="nse-modal-secondary" id="nss-share-download" aria-label="Download">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v13m0 0l-4.5-4.5M12 16l4.5-4.5"/><path d="M4 20h16"/></svg>' +
        '</button>' +
        '<button type="button" class="nse-modal-apply" id="nss-share-native" aria-label="Share">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 10.5l6.8-3.9M8.6 13.5l6.8 3.9"/></svg>' +
        '</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(backdrop);
  _shareModalEl = backdrop;

  backdrop.addEventListener('click', function (e) { if (e.target === backdrop) _closeShareModal(); });
  backdrop.querySelector('#nss-share-close').addEventListener('click', _closeShareModal);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !backdrop.hidden) _closeShareModal(); });

  var tabImg = backdrop.querySelector('#nss-share-tab-img');
  var tabVid = backdrop.querySelector('#nss-share-tab-vid');
  var paneImg = backdrop.querySelector('#nss-share-pane-img');
  var paneVid = backdrop.querySelector('#nss-share-pane-vid');
  tabImg.addEventListener('click', function () {
    tabImg.classList.add('is-active'); tabVid.classList.remove('is-active');
    paneImg.classList.add('is-active'); paneVid.classList.remove('is-active');
    _setShareActionsEnabled(true); // image is always ready, no recording gate
  });
  tabVid.addEventListener('click', function () {
    tabVid.classList.add('is-active'); tabImg.classList.remove('is-active');
    paneVid.classList.add('is-active'); paneImg.classList.remove('is-active');
    _startFadePreview();
    // Auto-record as soon as the tab opens — the manual record button was
    // easy to miss below the fold, which left videoBlobUrl empty and made
    // "Download"/"Share" silently fall back to the still image instead.
    if (!_shareState.videoBlobUrl) _recordFadeVideo();
  });

  backdrop.querySelector('#nss-share-record').addEventListener('click', _recordFadeVideo);
  backdrop.querySelector('#nss-share-download').addEventListener('click', _downloadShareAsset);
  backdrop.querySelector('#nss-share-native').addEventListener('click', _nativeShareAsset);
  Array.prototype.slice.call(backdrop.querySelectorAll('.nss-share-quick-btn')).forEach(function (btn) {
    btn.addEventListener('click', function () { _quickShareTo(btn.getAttribute('data-platform')); });
  });

  return backdrop;
}

function _openShareModal(imgUrl, beforeUrl, promptStr) {
  var modal = _ensureShareModal();
  _shareState = { imgUrl: imgUrl, beforeUrl: beforeUrl || '', promptStr: promptStr || '', videoBlobUrl: '', videoMime: '', videoExt: '' };

  modal.querySelector('#nss-share-img-preview').src = imgUrl;
  modal.querySelector('#nss-share-prompt').value = promptStr || '(no prompt recorded for this image)';

  var tabVid = modal.querySelector('#nss-share-tab-vid');
  tabVid.hidden = !beforeUrl;
  var video = modal.querySelector('#nss-share-video');
  video.hidden = true; video.removeAttribute('src');
  modal.querySelector('#nss-share-vid-placeholder').hidden = true;
  _setShareActionsEnabled(true);

  // Default back to the image tab every time it's opened.
  modal.querySelector('#nss-share-tab-img').click();
  modal.hidden = false;
}

function _closeShareModal() {
  if (!_shareModalEl) return;
  _shareModalEl.hidden = true;
  if (_shareState._fadeAnimId) cancelAnimationFrame(_shareState._fadeAnimId);
}

function _drawCover(ctx, img, cw, ch, alpha) {
  var ir = img.width / img.height, cr = cw / ch, sw, sh, sx, sy;
  if (ir > cr) { sh = img.height; sw = sh * cr; sy = 0; sx = (img.width - sw) / 2; }
  else { sw = img.width; sh = sw / cr; sx = 0; sy = (img.height - sh) / 2; }
  ctx.globalAlpha = alpha;
  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, cw, ch);
  ctx.globalAlpha = 1;
}

var _NSS_FADE_HOLD_MS = 900, _NSS_FADE_MS = 700;
// Bounding box, not a fixed size — keeps whatever aspect ratio the source
// image has, just scales it down so neither edge blows past 720p. Never
// upscales a smaller source.
var _NSS_MAX_W = 1280, _NSS_MAX_H = 720;
function _capTo720p(w, h) {
  var scale = Math.min(_NSS_MAX_W / w, _NSS_MAX_H / h, 1);
  return { w: Math.max(1, Math.round(w * scale)), h: Math.max(1, Math.round(h * scale)) };
}

function _startFadePreview() {
  if (!_shareState.beforeUrl || !_shareState.imgUrl) return;
  var canvas = _shareModalEl.querySelector('#nss-share-canvas');
  var ctx = canvas.getContext('2d');
  var imgA = new Image(), imgB = new Image();
  var loaded = 0;
  function ready() {
    loaded++;
    if (loaded < 2) return;
    // Size the capture canvas off the "after" image's real dimensions,
    // capped to 720p — the card thumbnail canvas was a fixed 600×600
    // square regardless of the source's actual aspect ratio, which both
    // distorted non-square refines and needlessly recorded at full res.
    var capped = _capTo720p(imgB.naturalWidth || imgB.width, imgB.naturalHeight || imgB.height);
    canvas.width = capped.w;
    canvas.height = capped.h;
    var stage = _shareModalEl.querySelector('.nss-share-vid-stage');
    if (stage) stage.style.aspectRatio = capped.w + ' / ' + capped.h;
    if (_shareState._fadeAnimId) cancelAnimationFrame(_shareState._fadeAnimId);
    var cycle = (_NSS_FADE_HOLD_MS + _NSS_FADE_MS) * 2;
    var t0 = performance.now();
    function frame(ts) {
      var t = (ts - t0) % cycle;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (t < _NSS_FADE_HOLD_MS) {
        _drawCover(ctx, imgA, canvas.width, canvas.height, 1);
      } else if (t < _NSS_FADE_HOLD_MS + _NSS_FADE_MS) {
        var p = (t - _NSS_FADE_HOLD_MS) / _NSS_FADE_MS;
        _drawCover(ctx, imgA, canvas.width, canvas.height, 1);
        _drawCover(ctx, imgB, canvas.width, canvas.height, p);
      } else if (t < _NSS_FADE_HOLD_MS + _NSS_FADE_MS + _NSS_FADE_HOLD_MS) {
        _drawCover(ctx, imgB, canvas.width, canvas.height, 1);
      } else {
        var p2 = (t - _NSS_FADE_HOLD_MS - _NSS_FADE_MS - _NSS_FADE_HOLD_MS) / _NSS_FADE_MS;
        _drawCover(ctx, imgB, canvas.width, canvas.height, 1);
        _drawCover(ctx, imgA, canvas.width, canvas.height, p2);
      }
      _shareState._fadeAnimId = requestAnimationFrame(frame);
    }
    _shareState._fadeAnimId = requestAnimationFrame(frame);
  }
  imgA.crossOrigin = 'anonymous'; imgB.crossOrigin = 'anonymous';
  imgA.onload = ready; imgB.onload = ready;
  imgA.src = _shareState.beforeUrl;
  imgB.src = _shareState.imgUrl;
}

function _setShareVidStatus(text) {
  var el = _shareModalEl && _shareModalEl.querySelector('#nss-share-vid-status');
  if (el) el.textContent = text;
}

function _setShareActionsEnabled(enabled) {
  var dl = _shareModalEl.querySelector('#nss-share-download');
  var sh = _shareModalEl.querySelector('#nss-share-native');
  dl.disabled = !enabled; sh.disabled = !enabled;
  Array.prototype.slice.call(_shareModalEl.querySelectorAll('.nss-share-quick-btn')).forEach(function (btn) {
    btn.disabled = !enabled;
  });
}

function _recordFadeVideo() {
  var canvas = _shareModalEl.querySelector('#nss-share-canvas');
  var recordBtn = _shareModalEl.querySelector('#nss-share-record');
  if (!canvas || recordBtn.classList.contains('is-recording')) return;
  // A fresh recording invalidates whatever was downloaded/shared before —
  // block Download/Share until this pass finishes so they can't grab a
  // stale (or still-empty) video by clicking mid-recording.
  _shareState.videoBlobUrl = '';
  if (_activeShareTabIsVideo()) _setShareActionsEnabled(false);
  _setShareVidStatus('Recording…');
  var placeholder = _shareModalEl.querySelector('#nss-share-vid-placeholder');
  var video = _shareModalEl.querySelector('#nss-share-video');
  placeholder.hidden = false;
  video.hidden = true;
  var chunks = [];
  var stream = canvas.captureStream(30);
  // X/Twitter (and most other platforms) reject .webm uploads outright —
  // they want mp4/h264. MediaRecorder can only ever produce whatever
  // container the browser itself supports recording to; Chrome/Edge 105+
  // can record straight to mp4/h264, Firefox and older Chromium builds
  // cannot and only ever offer webm. Feature-detect and remember which one
  // we actually got so filenames/mimetypes downstream aren't a lie.
  var mimeType =
    (MediaRecorder.isTypeSupported('video/mp4;codecs=avc1') && 'video/mp4;codecs=avc1') ||
    (MediaRecorder.isTypeSupported('video/mp4') && 'video/mp4') ||
    (MediaRecorder.isTypeSupported('video/webm;codecs=vp9') && 'video/webm;codecs=vp9') ||
    (MediaRecorder.isTypeSupported('video/webm') && 'video/webm') ||
    '';
  _shareState.videoMime = mimeType ? mimeType.split(';')[0] : 'video/webm';
  _shareState.videoExt = _shareState.videoMime === 'video/mp4' ? 'mp4' : 'webm';
  var recorder = mimeType ? new MediaRecorder(stream, { mimeType: mimeType }) : new MediaRecorder(stream);
  recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
  recorder.onstop = function () {
    var blob = new Blob(chunks, { type: _shareState.videoMime });
    _shareState.videoBlobUrl = URL.createObjectURL(blob);
    video.src = _shareState.videoBlobUrl;
    video.hidden = false;
    placeholder.hidden = true;
    recordBtn.classList.remove('is-recording');
    _setShareVidStatus(_shareState.videoExt === 'mp4' ? 'Ready ✓ (mp4)' : 'Ready ✓ (webm — your browser can\'t record mp4 directly; X/Twitter won\'t accept this file)');
    if (_activeShareTabIsVideo()) _setShareActionsEnabled(true);
  };
  recorder.start();
  recordBtn.classList.add('is-recording');
  setTimeout(function () { recorder.stop(); }, (_NSS_FADE_HOLD_MS + _NSS_FADE_MS) * 2);
}

function _activeShareTabIsVideo() {
  return _shareModalEl && _shareModalEl.querySelector('#nss-share-tab-vid').classList.contains('is-active');
}

function _downloadShareAsset() {
  if (_activeShareTabIsVideo() && !_shareState.videoBlobUrl) return; // still recording — button is disabled, but guard anyway
  var a = document.createElement('a');
  if (_activeShareTabIsVideo() && _shareState.videoBlobUrl) {
    a.href = _shareState.videoBlobUrl; a.download = 'nomad-compare.' + (_shareState.videoExt || 'webm');
  } else {
    a.href = _shareState.imgUrl; a.download = 'nomad-image.png';
  }
  document.body.appendChild(a); a.click(); a.remove();
}

async function _nativeShareAsset() {
  if (_activeShareTabIsVideo() && !_shareState.videoBlobUrl) return; // still recording
  if (!navigator.share) { _downloadShareAsset(); return; }
  try {
    if (_activeShareTabIsVideo() && _shareState.videoBlobUrl) {
      var vBlob = await (await fetch(_shareState.videoBlobUrl)).blob();
      var vExt = _shareState.videoExt || 'webm';
      var vFile = new File([vBlob], 'nomad-compare.' + vExt, { type: _shareState.videoMime || 'video/webm' });
      if (navigator.canShare && !navigator.canShare({ files: [vFile] })) {
        // Browser's share sheet won't accept this file type (typically a
        // webm video on iOS/Safari) — fall back to a plain download instead
        // of calling navigator.share and getting a silent/confusing failure.
        _downloadShareAsset();
        return;
      }
      await navigator.share({ title: 'Nomad Studio', files: [vFile] });
    } else {
      var iBlob = await (await fetch(_shareState.imgUrl)).blob();
      var iFile = new File([iBlob], 'nomad-image.png', { type: iBlob.type || 'image/png' });
      await navigator.share({ title: 'Nomad Studio', text: _shareState.promptStr, files: [iFile] });
    }
  } catch (err) {
    console.log('[Share] cancelled or failed', err);
  }
}

// ── Quick-share row ─────────────────────────────────────────────────────
// No web platform lets a page attach a file to a post via a plain link —
// that's a deliberate security restriction on all of them, not something
// we can code around. What differs is whether the platform even offers a
// "compose" URL that accepts prefilled text:
//   X / WhatsApp   — real web intents, take ?text= and open a ready-to-post
//                    compose window. The image/video still has to be
//                    attached by hand (drag the just-downloaded file in).
//   Instagram/TikTok — no web compose intent exists at all. Best case: copy
//                    the caption to the clipboard and land on the upload
//                    page so it's paste + drop the file, not retype it.
function _currentShareCaption() {
  var base = _shareState.promptStr ? _shareState.promptStr + ' — made with Nomad Studio 🦝' : 'Made with Nomad Studio 🦝';
  return base;
}

function _quickShareTo(platform) {
  if (_activeShareTabIsVideo() && !_shareState.videoBlobUrl) return; // still recording
  _downloadShareAsset();
  var caption = _currentShareCaption();

  if (platform === 'x') {
    window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(caption), '_blank', 'noopener');
    return;
  }
  if (platform === 'whatsapp') {
    window.open('https://wa.me/?text=' + encodeURIComponent(caption), '_blank', 'noopener');
    return;
  }
  // Instagram / TikTok — copy caption, then just land the user on the
  // upload surface with the file already sitting in their Downloads.
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(caption).catch(function () {});
  }
  var dest = platform === 'instagram' ? 'https://www.instagram.com/' : 'https://www.tiktok.com/upload';
  window.open(dest, '_blank', 'noopener');
}
