(function mobilePage() {
  'use strict';

  document.body.classList.add('mobile-page-body');
  document.documentElement.classList.add('mobile-page-body');

  // -------------------------------------------------------------------------
  // DOM refs
  // -------------------------------------------------------------------------
  const viewerEl        = document.getElementById('mobile-viewer');
  const viewerStatusEl  = document.getElementById('mobile-viewer-status');
  const slideEl         = document.getElementById('mobile-slide');
  const slideImgEl      = document.getElementById('mobile-slide-image');
  const prevBtn         = document.getElementById('mobile-prev-btn');
  const nextBtn         = document.getElementById('mobile-next-btn');
  const editBtn         = document.getElementById('mobile-edit-btn');
  const moveLockBtn         = document.getElementById('mobile-move-lock-btn');
  const diamondToggleBtn    = document.getElementById('mobile-diamond-toggle-btn');
  const saveBtn         = document.getElementById('mobile-save-btn');
  const counterEl       = document.getElementById('mobile-slide-counter');
  const thumbstripEl    = document.getElementById('mobile-thumbstrip');
  const thumbTrackEl    = document.getElementById('mobile-thumbstrip-track');
  const floatingProgressEl = document.getElementById('mobile-floating-progress');
  const floatingProgressBarEl = document.getElementById('mobile-floating-progress-bar');
  const floatingProgressTextEl = document.getElementById('mobile-floating-progress-text');

  const editPanelEl     = document.getElementById('mobile-edit-panel');
  const editBackdropEl  = document.getElementById('mobile-edit-backdrop');
  const editHandleEl    = document.getElementById('mobile-edit-handle');

  const resultWrapEl    = document.getElementById('mobile-edit-result-wrap');
  const resultImageEl   = document.getElementById('mobile-edit-result-image');
  const resultDownloadEl= document.getElementById('mobile-edit-result-download');

  const presetBtns      = Array.from(document.querySelectorAll('.mobile-preset-btn'));
  const refineActionBtns = Array.from(document.querySelectorAll('.mobile-preset-btn[data-refine-action]'));
  const promptToggleBtn = document.getElementById('mobile-prompt-toggle-btn');
  const seedActionBtn = document.getElementById('mobile-seed-action-btn');
  const seedRandomizeToggleBtn = document.getElementById('mobile-seed-randomize-toggle');
  const seedRandomizeLabelEl = document.getElementById('mobile-seed-randomize-label');
  const thinkToggleBtn = document.getElementById('mobile-think-toggle');
  const thinkLabelEl = document.getElementById('mobile-think-label');
  const customInputStackEl = document.getElementById('mobile-edit-input-stack');
  const customInputEl = document.getElementById('mobile-edit-custom-input');
  const customSendBtn = document.getElementById('mobile-edit-custom-send');

  const statusRowEl     = document.getElementById('mobile-edit-status-row');
  const statusEl        = document.getElementById('mobile-edit-status');
  const progressBarEl   = document.getElementById('mobile-edit-progress-bar');

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  let allImages     = [];
  let currentIndex  = 0;
  let currentItem   = null;
  let progressTimer = null;
  let progressValue = 0;
  let isMovementLocked = false;
  let isThumbstripOpen = false;
  let randomizeSeedForEdits = false;
  let thinkModeEnabled = false;
  let hideDiamondImages = false;
  let sourceImages = [];

  const MOBILE_HIDE_DIAMOND_KEY = 'oj-mobile-hide-diamond-v1';

  const MOBILE_SEED_RANDOMIZE_KEY = 'oj-mobile-seed-randomize-v1';
  const MOBILE_THINK_KEY = 'oj-mobile-think-v1';

  function isDiamondMarked(value) {
    if (value === true) return true;
    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      return normalized === 'true' || normalized === '1' || normalized === 'yes' || normalized === 'on';
    }
    if (typeof value === 'number') return value === 1;
    return false;
  }

  const PRESET_PLACEHOLDERS = {
    person:     'Change the person/character: ',
    background: 'Change the background to: ',
    pose:       'Change the pose to: ',
  };

  // -------------------------------------------------------------------------
  // Load
  // -------------------------------------------------------------------------
  async function loadImages() {
    try {
      const res = await fetch('/api/images');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      sourceImages = Array.isArray(data.images) ? data.images : [];
      applyDiamondFilter();
      if (!allImages.length) {
        if (viewerStatusEl) viewerStatusEl.textContent = 'No images yet. Generate some in Studio first.';
        return;
      }
      if (viewerStatusEl) viewerStatusEl.remove();
      slideEl.removeAttribute('hidden');
      buildThumbstrip();
      showSlide(0);
      if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
      }
    } catch (err) {
      if (viewerStatusEl) {
        viewerStatusEl.textContent = `Could not load images: ${err.message}`;
        viewerStatusEl.classList.add('status-error');
      }
    }
  }

  // -------------------------------------------------------------------------
  // Gallery navigation
  // -------------------------------------------------------------------------
  function updateImageFitMode() {
    const nw = slideImgEl.naturalWidth || 0;
    const nh = slideImgEl.naturalHeight || 0;
    if (!nw || !nh) return;

    const viewportRatio = window.innerWidth / Math.max(1, window.innerHeight);
    const imageRatio = nw / nh;

    // If image is wider than viewport (e.g. 16:9 on portrait), fill height and crop sides.
    const useCover = imageRatio > viewportRatio;
    slideImgEl.classList.toggle('fit-cover', useCover);
  }

  // Pan state for fit-cover images (zoom = 1)
  let panX = 50; // object-position X %
  let panY = 50; // object-position Y %
  // Zoom state
  let imgZoom = 1;

  function resetPan() {
    panX = 50;
    panY = 50;
    imgZoom = 1;
    slideImgEl.style.objectPosition = '50% 50%';
    slideImgEl.style.transform = '';
  }

  function playVerticalSlideAnimation(direction = 0) {
    if (!slideImgEl || !direction) return;
    const cls = direction > 0 ? 'slide-enter-up' : 'slide-enter-down';
    slideImgEl.classList.remove('slide-enter-up', 'slide-enter-down');
    // Reflow ensures repeated swipes retrigger the keyframe animation.
    void slideImgEl.offsetWidth;
    slideImgEl.classList.add(cls);
    slideImgEl.addEventListener('animationend', () => {
      slideImgEl.classList.remove('slide-enter-up', 'slide-enter-down');
    }, { once: true });
  }

  function showSlide(index, direction = 0) {
    if (!allImages.length) return;
    currentIndex = Math.max(0, Math.min(index, allImages.length - 1));
    currentItem  = allImages[currentIndex];

    const filename = String(currentItem.filename || '');
    slideImgEl.classList.remove('fit-cover');
    resetPan();
    slideImgEl.onload = updateImageFitMode;
    slideImgEl.src = `/api/images/${encodeURIComponent(filename)}`;
    slideImgEl.alt = filename;
    if (slideImgEl.complete) updateImageFitMode();
    saveBtn.href = `/api/images/${encodeURIComponent(filename)}`;
    saveBtn.setAttribute('download', filename);
    playVerticalSlideAnimation(direction);

    prevBtn.toggleAttribute('hidden', currentIndex === 0);
    nextBtn.toggleAttribute('hidden', currentIndex >= allImages.length - 1);

    if (counterEl) counterEl.textContent = `${currentIndex + 1} / ${allImages.length}`;
    syncThumbstripActive();
  }

  function setThumbstripOpen(open) {
    if (!thumbstripEl) return;
    isThumbstripOpen = !!open;
    thumbstripEl.toggleAttribute('hidden', !isThumbstripOpen);
    thumbstripEl.setAttribute('aria-hidden', isThumbstripOpen ? 'false' : 'true');
  }

  function buildThumbstrip() {
    if (!thumbTrackEl) return;
    thumbTrackEl.innerHTML = allImages
      .map((item, index) => {
        const filename = String(item && item.filename ? item.filename : '');
        if (!filename) return '';
        const encoded = encodeURIComponent(filename);
        return (
          `<button type="button" class="mobile-thumb-item" data-thumb-index="${index}" aria-label="Open image ${index + 1}">` +
          `<img src="/api/images/${encoded}/thumb?w=180" alt="Image ${index + 1}" loading="lazy" decoding="async" />` +
          '</button>'
        );
      })
      .join('');
    syncThumbstripActive();
  }

  function syncThumbstripActive() {
    if (!thumbTrackEl) return;
    const nodes = thumbTrackEl.querySelectorAll('.mobile-thumb-item');
    nodes.forEach((node) => {
      const idx = Number(node.getAttribute('data-thumb-index'));
      const active = idx === currentIndex;
      node.classList.toggle('active', active);
      if (active) {
        node.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'auto' });
      }
    });
  }

  function applyDiamondFilter() {
    allImages = hideDiamondImages
      ? sourceImages.filter((item) => !isDiamondMarked(item.sidecar && item.sidecar.diamond))
      : sourceImages.slice();
  }

  function persistDiamondToggle() {
    try {
      localStorage.setItem(MOBILE_HIDE_DIAMOND_KEY, hideDiamondImages ? '1' : '0');
    } catch {
      // ignore
    }
  }

  function restoreDiamondToggle() {
    try {
      hideDiamondImages = localStorage.getItem(MOBILE_HIDE_DIAMOND_KEY) === '1';
    } catch {
      hideDiamondImages = false;
    }
  }

  function applyDiamondToggleUi() {
    if (!diamondToggleBtn) return;
    diamondToggleBtn.classList.toggle('active', hideDiamondImages);
    diamondToggleBtn.setAttribute('aria-pressed', hideDiamondImages ? 'true' : 'false');
    diamondToggleBtn.setAttribute('aria-label', hideDiamondImages ? 'Show diamond images' : 'Hide diamond images');
    diamondToggleBtn.setAttribute('title', hideDiamondImages ? 'Show diamond images' : 'Hide diamond images');
    const glyph = diamondToggleBtn.querySelector('.mobile-diamond-glyph');
    if (glyph) glyph.textContent = hideDiamondImages ? '◆' : '◇';
  }

  function applyMovementLockUi() {
    if (!moveLockBtn) return;
    moveLockBtn.classList.toggle('active', isMovementLocked);
    moveLockBtn.setAttribute('aria-pressed', isMovementLocked ? 'true' : 'false');
    moveLockBtn.setAttribute('title', isMovementLocked ? 'Unlock image movement' : 'Lock image movement');
    moveLockBtn.setAttribute('aria-label', isMovementLocked ? 'Unlock image movement' : 'Lock image movement');
  }

  function setCustomPromptOpen(open) {
    if (!customInputStackEl) return;
    customInputStackEl.toggleAttribute('hidden', !open);
    if (promptToggleBtn) {
      promptToggleBtn.classList.toggle('active', !!open);
      promptToggleBtn.setAttribute('aria-pressed', open ? 'true' : 'false');
    }
    if (open && customInputEl) {
      window.setTimeout(() => customInputEl.focus(), 0);
    }
  }

  function persistSeedRandomizeToggle() {
    try {
      localStorage.setItem(MOBILE_SEED_RANDOMIZE_KEY, randomizeSeedForEdits ? '1' : '0');
    } catch {
      // ignore storage failures
    }
  }

  function restoreSeedRandomizeToggle() {
    try {
      randomizeSeedForEdits = localStorage.getItem(MOBILE_SEED_RANDOMIZE_KEY) === '1';
    } catch {
      randomizeSeedForEdits = false;
    }
  }

  function applySeedRandomizeUi() {
    if (!seedRandomizeToggleBtn || !seedRandomizeLabelEl) return;
    seedRandomizeToggleBtn.classList.toggle('active', randomizeSeedForEdits);
    seedRandomizeToggleBtn.setAttribute('aria-pressed', randomizeSeedForEdits ? 'true' : 'false');
    seedRandomizeToggleBtn.setAttribute('title', `Random seed for edits: ${randomizeSeedForEdits ? 'On' : 'Off'}`);
    seedRandomizeLabelEl.textContent = randomizeSeedForEdits ? 'On' : 'Off';
  }

  function persistThinkToggle() {
    try {
      localStorage.setItem(MOBILE_THINK_KEY, thinkModeEnabled ? '1' : '0');
    } catch {
      // ignore storage failures
    }
  }

  function restoreThinkToggle() {
    try {
      thinkModeEnabled = localStorage.getItem(MOBILE_THINK_KEY) === '1';
    } catch {
      thinkModeEnabled = false;
    }
  }

  function applyThinkUi() {
    if (!thinkToggleBtn || !thinkLabelEl) return;
    thinkToggleBtn.classList.toggle('active', thinkModeEnabled);
    thinkToggleBtn.setAttribute('aria-pressed', thinkModeEnabled ? 'true' : 'false');
    thinkToggleBtn.setAttribute('title', `Think mode: ${thinkModeEnabled ? 'On' : 'Off'}`);
    thinkLabelEl.textContent = thinkModeEnabled ? 'On' : 'Off';
  }

  prevBtn.addEventListener('click', () => showSlide(currentIndex - 1, -1));
  nextBtn.addEventListener('click', () => showSlide(currentIndex + 1, 1));
  window.addEventListener('resize', updateImageFitMode);

  if (counterEl) {
    counterEl.setAttribute('role', 'button');
    counterEl.setAttribute('tabindex', '0');
    counterEl.setAttribute('aria-label', 'Open quick image carousel');
    counterEl.addEventListener('click', () => {
      setThumbstripOpen(!isThumbstripOpen);
      if (isThumbstripOpen) syncThumbstripActive();
    });
    counterEl.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      setThumbstripOpen(!isThumbstripOpen);
      if (isThumbstripOpen) syncThumbstripActive();
    });
  }

  if (thumbTrackEl) {
    thumbTrackEl.addEventListener('click', (e) => {
      const button = e.target && e.target.closest ? e.target.closest('[data-thumb-index]') : null;
      if (!button) return;
      const idx = Number(button.getAttribute('data-thumb-index'));
      if (!Number.isFinite(idx)) return;
      const direction = idx > currentIndex ? 1 : (idx < currentIndex ? -1 : 0);
      showSlide(idx, direction);
      setThumbstripOpen(false);
    });
  }

  document.addEventListener('pointerdown', (e) => {
    if (!isThumbstripOpen) return;
    const target = e.target;
    if (counterEl && counterEl.contains(target)) return;
    if (thumbstripEl && thumbstripEl.contains(target)) return;
    setThumbstripOpen(false);
  });

  // Swipe up/down on the viewer image (disabled when zoomed or in cover/pan mode).
  (function setupSwipeUD() {
    let startY = 0;
    let trackingSwipe = false;
    let startedInThumbstrip = false;

    function canSwipeNavigate() {
      return isMovementLocked || (imgZoom <= 1 && !slideImgEl.classList.contains('fit-cover'));
    }

    function isThumbstripTarget(target) {
      if (!thumbstripEl || !target || !target.closest) return false;
      return !!target.closest('#mobile-thumbstrip');
    }

    function resetSwipeVisual() {
      slideImgEl.style.transition = 'transform 140ms ease, opacity 140ms ease';
      slideImgEl.style.transform = '';
      slideImgEl.style.opacity = '';
      window.setTimeout(() => {
        slideImgEl.style.transition = '';
      }, 160);
    }

    slideEl.addEventListener('touchstart', (e) => {
      if (e.touches.length !== 1) return;
      startedInThumbstrip = isThumbstripTarget(e.target);
      if (startedInThumbstrip) return;
      if (!canSwipeNavigate()) return;
      startY = e.touches[0].clientY;
      trackingSwipe = true;
      slideImgEl.style.transition = 'none';
    }, { passive: true });

    slideEl.addEventListener('touchmove', (e) => {
      if (startedInThumbstrip) return;
      if (!trackingSwipe) return;
      if (e.touches.length !== 1) {
        trackingSwipe = false;
        resetSwipeVisual();
        return;
      }

      const dy = e.touches[0].clientY - startY;
      const fade = Math.max(0.62, 1 - (Math.abs(dy) / 420));
      e.preventDefault();
      slideImgEl.style.transform = `translateY(${dy}px)`;
      slideImgEl.style.opacity = String(fade);
    }, { passive: false });

    slideEl.addEventListener('touchend', (e) => {
      if (startedInThumbstrip) {
        startedInThumbstrip = false;
        return;
      }
      if (!trackingSwipe) return;
      trackingSwipe = false;
      const dy = e.changedTouches[0].clientY - startY;
      resetSwipeVisual();
      if (Math.abs(dy) > 50) {
        if (dy < 0) showSlide(currentIndex + 1, 1);
        else         showSlide(currentIndex - 1, -1);
      }
    }, { passive: true });

    slideEl.addEventListener('touchcancel', () => {
      if (startedInThumbstrip) {
        startedInThumbstrip = false;
        return;
      }
      if (!trackingSwipe) return;
      trackingSwipe = false;
      resetSwipeVisual();
    }, { passive: true });
  })();

  // Pan + Pinch-zoom on the viewer image
  (function setupZoomPan() {
    // Transform-based state (used when zoom > 1)
    let tX = 0, tY = 0;      // translate px

    // Pinch state
    let pinchActive = false;
    let startDist   = 1;
    let startZoom   = 1;
    let midX0 = 0, midY0 = 0;
    let startTX = 0, startTY = 0;

    // Single-finger pan state
    let panActive  = false;
    let p1x0 = 0, p1y0 = 0;
    let startPanTX = 0, startPanTY = 0;

    // object-position pan state (fit-cover, zoom = 1)
    let opActive  = false;
    let startTouchX = 0, startTouchY = 0;
    let startPanX = 50, startPanY = 50;

    function dist2(t1, t2) {
      const dx = t2.clientX - t1.clientX;
      const dy = t2.clientY - t1.clientY;
      return Math.sqrt(dx * dx + dy * dy);
    }

    function applyTransform() {
      slideImgEl.style.transform = (imgZoom === 1 && tX === 0 && tY === 0)
        ? ''
        : `translate(${tX}px, ${tY}px) scale(${imgZoom})`;
    }

    function clampTranslate() {
      if (imgZoom <= 1) { tX = 0; tY = 0; return; }
      const rect = slideImgEl.getBoundingClientRect();
      const hx = rect.width  * (imgZoom - 1) / 2;
      const hy = rect.height * (imgZoom - 1) / 2;
      tX = Math.max(-hx, Math.min(hx, tX));
      tY = Math.max(-hy, Math.min(hy, tY));
    }

    slideImgEl.addEventListener('touchstart', (e) => {
      if (isMovementLocked) return;
      if (e.touches.length === 2) {
        // --- Pinch start ---
        pinchActive = true;
        opActive    = false;
        panActive   = false;
        startDist   = dist2(e.touches[0], e.touches[1]);
        startZoom   = imgZoom;
        midX0 = (e.touches[0].clientX + e.touches[1].clientX) / 2;
        midY0 = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        startTX = tX;
        startTY = tY;
      } else if (e.touches.length === 1) {
        pinchActive = false;
        if (imgZoom > 1) {
          // --- Transform pan (zoomed) ---
          panActive  = true;
          opActive   = false;
          p1x0       = e.touches[0].clientX;
          p1y0       = e.touches[0].clientY;
          startPanTX = tX;
          startPanTY = tY;
        } else if (slideImgEl.classList.contains('fit-cover')) {
          // --- Object-position pan (fit-cover, zoom = 1) ---
          opActive    = true;
          panActive   = false;
          startTouchX = e.touches[0].clientX;
          startTouchY = e.touches[0].clientY;
          startPanX   = panX;
          startPanY   = panY;
        }
      }
    }, { passive: true });

    slideImgEl.addEventListener('touchmove', (e) => {
      if (isMovementLocked) return;
      if (pinchActive && e.touches.length >= 2) {
        e.preventDefault();
        const d = dist2(e.touches[0], e.touches[1]);
        imgZoom = Math.max(1, Math.min(5, startZoom * (d / startDist)));
        const midX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
        const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        tX = startTX + (midX - midX0);
        tY = startTY + (midY - midY0);
        clampTranslate();
        applyTransform();
      } else if (panActive && e.touches.length >= 1 && imgZoom > 1) {
        e.preventDefault();
        tX = startPanTX + (e.touches[0].clientX - p1x0);
        tY = startPanTY + (e.touches[0].clientY - p1y0);
        clampTranslate();
        applyTransform();
      } else if (opActive && e.touches.length >= 1) {
        e.preventDefault();
        const dx = e.touches[0].clientX - startTouchX;
        const dy = e.touches[0].clientY - startTouchY;
        const rect = slideImgEl.getBoundingClientRect();
        const nw = slideImgEl.naturalWidth  || 1;
        const nh = slideImgEl.naturalHeight || 1;
        const imgRatio = nw / nh;
        const vpRatio  = rect.width / Math.max(1, rect.height);
        if (imgRatio > vpRatio) {
          const overflowX = Math.max(1, (rect.height / nh) * nw - rect.width);
          panX = Math.max(0, Math.min(100, startPanX - (dx / overflowX) * 100));
        } else {
          const overflowY = Math.max(1, (rect.width / nw) * nh - rect.height);
          panY = Math.max(0, Math.min(100, startPanY - (dy / overflowY) * 100));
        }
        slideImgEl.style.objectPosition = `${panX}% ${panY}%`;
      }
    }, { passive: false });

    slideImgEl.addEventListener('touchend', (e) => {
      if (isMovementLocked) return;
      if (e.touches.length < 2) pinchActive = false;
      if (e.touches.length === 0) { panActive = false; opActive = false; }
      if (imgZoom <= 1.05) {
        imgZoom = 1; tX = 0; tY = 0;
        applyTransform();
      }
    }, { passive: true });

    slideImgEl.addEventListener('touchcancel', () => {
      if (isMovementLocked) return;
      pinchActive = false; panActive = false; opActive = false;
    }, { passive: true });

    // Double-tap to reset zoom
    let lastTap = 0;
    slideImgEl.addEventListener('touchend', (e) => {
      if (isMovementLocked) return;
      if (e.touches.length !== 0) return;
      const now = Date.now();
      if (now - lastTap < 300) {
        imgZoom = 1; tX = 0; tY = 0;
        applyTransform();
      }
      lastTap = now;
    }, { passive: true });
  })();

  // Edit button opens panel
  editBtn.addEventListener('click', () => {
    if (currentItem) openEditPanel(currentItem);
  });

  if (moveLockBtn) {
    moveLockBtn.addEventListener('click', () => {
      isMovementLocked = !isMovementLocked;
      if (isMovementLocked) {
        resetPan();
      }
      applyMovementLockUi();
    });
    applyMovementLockUi();
  }

  if (diamondToggleBtn) {
    restoreDiamondToggle();
    applyDiamondToggleUi();
    diamondToggleBtn.addEventListener('click', () => {
      hideDiamondImages = !hideDiamondImages;
      persistDiamondToggle();
      applyDiamondToggleUi();
      applyDiamondFilter();
      buildThumbstrip();
      showSlide(0);
    });
  }

  if (seedRandomizeToggleBtn) {
    seedRandomizeToggleBtn.addEventListener('click', () => {
      randomizeSeedForEdits = !randomizeSeedForEdits;
      persistSeedRandomizeToggle();
      applySeedRandomizeUi();
    });
  }

  if (thinkToggleBtn) {
    thinkToggleBtn.addEventListener('click', () => {
      thinkModeEnabled = !thinkModeEnabled;
      persistThinkToggle();
      applyThinkUi();
    });
  }

  // -------------------------------------------------------------------------
  // Edit panel (bottom sheet)
  // -------------------------------------------------------------------------
  function openEditPanel(item) {
    currentItem = item;
    hideResult();
    hideStatus();
    setCustomPromptOpen(false);
    editPanelEl.classList.add('open');
    editPanelEl.removeAttribute('aria-hidden');
    document.body.classList.add('mobile-edit-open');
  }

  function closeEditPanel(shouldStopProgress = true) {
    editPanelEl.classList.remove('open');
    editPanelEl.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('mobile-edit-open');
    if (shouldStopProgress) stopProgress();
  }

  editBackdropEl.addEventListener('click', closeEditPanel);

  // Swipe-down handle to close
  (function setupSwipeDown() {
    let startY = 0;
    let dragging = false;
    const shell = editPanelEl.querySelector('.mobile-edit-shell');

    editHandleEl.addEventListener('touchstart', (e) => {
      startY = e.touches[0].clientY;
      dragging = true;
    }, { passive: true });

    document.addEventListener('touchmove', (e) => {
      if (!dragging) return;
      const delta = e.touches[0].clientY - startY;
      if (delta > 0) shell.style.transform = `translateY(${delta}px)`;
    }, { passive: true });

    document.addEventListener('touchend', (e) => {
      if (!dragging) return;
      dragging = false;
      const delta = e.changedTouches[0].clientY - startY;
      shell.style.transform = '';
      if (delta > 80) closeEditPanel();
    }, { passive: true });
  })();

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && editPanelEl.classList.contains('open')) closeEditPanel();
    if (!editPanelEl.classList.contains('open')) {
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft')  showSlide(currentIndex - 1, -1);
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') showSlide(currentIndex + 1, 1);
    }
  });

  // -------------------------------------------------------------------------
  // Result display
  // -------------------------------------------------------------------------
  function showResult(savedFilename) {
    resultImageEl.src = `/api/images/${encodeURIComponent(savedFilename)}`;
    resultImageEl.alt = savedFilename;
    resultDownloadEl.href = `/api/images/${encodeURIComponent(savedFilename)}`;
    resultDownloadEl.setAttribute('download', savedFilename);
    resultWrapEl.removeAttribute('hidden');
    resultWrapEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function hideResult() {
    resultImageEl.src = '';
    resultWrapEl.setAttribute('hidden', '');
  }

  // -------------------------------------------------------------------------
  // Status / progress
  // -------------------------------------------------------------------------
  function showStatus(msg, isError = false) {
    statusEl.textContent = msg;
    statusEl.classList.toggle('status-error', isError);
    statusRowEl.removeAttribute('hidden');

    if (floatingProgressEl && floatingProgressTextEl) {
      floatingProgressTextEl.textContent = msg;
      floatingProgressEl.classList.toggle('status-error', isError);
      floatingProgressEl.removeAttribute('hidden');
    }
  }

  function hideStatus() {
    statusRowEl.setAttribute('hidden', '');
    statusEl.textContent = '';
    statusEl.classList.remove('status-error');

    if (floatingProgressEl && floatingProgressTextEl) {
      floatingProgressEl.setAttribute('hidden', '');
      floatingProgressTextEl.textContent = '';
      floatingProgressEl.classList.remove('status-error');
    }
    setProgressBar(0);
  }

  function setProgressBar(pct) {
    progressValue = Math.max(0, Math.min(100, pct));
    if (progressBarEl) progressBarEl.style.width = `${progressValue}%`;
    if (floatingProgressBarEl) floatingProgressBarEl.style.width = `${progressValue}%`;
  }

  function startProgress(options = {}) {
    stopProgress();
    const min = Number.isFinite(options.min) ? options.min : 2;
    const max = Number.isFinite(options.max) ? options.max : 88;
    const perSec = Number.isFinite(options.perSec) ? options.perSec : 0.45;
    const label = String(options.label || 'Generating…');
    const startTime = Date.now();
    setProgressBar(min);
    progressTimer = setInterval(() => {
      const sim = Math.min(max, min + ((Date.now() - startTime) / 1000) * perSec);
      const next = Math.max(progressValue, sim);
      setProgressBar(next);
      showStatus(`${label} ${Math.round(next)}%`);
    }, 700);
  }

  function stopProgress(finalPct = 0) {
    if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
    setProgressBar(finalPct);
  }

  // -------------------------------------------------------------------------
  // Preset buttons — tap to run directly
  // -------------------------------------------------------------------------
  presetBtns.forEach((btn) => {
    // The two Refine-flow buttons (Relight/Remove BG) share the
    // `.mobile-preset-btn` class for shared sizing/disable-state handling,
    // but have `data-refine-action` instead of `data-edit-type` and are
    // wired up separately below via runRefineAction — skip them here so
    // they don't fall through to the `editType || 'custom'` default and
    // run the LM Studio prompt-rewrite flow with an empty instruction.
    if (btn.dataset.refineAction) return;
    btn.addEventListener('click', () => {
      const editType = btn.dataset.editType || 'custom';
      if (editType === 'prompt') {
        setCustomPromptOpen(!(customInputStackEl && customInputStackEl.hidden === false));
        return;
      }
      if (editType === 'seed') {
        setCustomPromptOpen(false);
        runEdit('custom', '', { seedMode: 'random', seedOnly: true });
        return;
      }
      setCustomPromptOpen(false);
      runEdit(editType, '', { seedMode: randomizeSeedForEdits ? 'random' : 'fixed' });
    });
  });

  if (customSendBtn) {
    customSendBtn.addEventListener('click', () => {
      const instruction = String(customInputEl && customInputEl.value ? customInputEl.value : '').trim();
      if (!instruction) {
        showStatus('Write a custom instruction first.', true);
        return;
      }
      runEdit('custom', instruction, { seedMode: randomizeSeedForEdits ? 'random' : 'fixed' });
    });
  }

  if (customInputEl) {
    customInputEl.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (customSendBtn) customSendBtn.click();
      }
    });
  }

  // -------------------------------------------------------------------------
  // Send / Generate
  // -------------------------------------------------------------------------
  async function runEdit(editType = 'custom', customInstruction = '', options = {}) {
    if (!currentItem) return;
    const seedMode = options.seedMode || 'fixed';
    const seedOnly = !!options.seedOnly;
    hideResult();
    closeEditPanel(false);
    if (seedOnly) {
      showStatus('Generating with random seed…');
      startProgress({ min: 50, max: 94, perSec: 0.7, label: 'Generating image…' });
    } else {
      showStatus('Refining prompt…');
      startProgress({ min: 2, max: 49, perSec: 1.0, label: 'Refining prompt…' });
    }
    presetBtns.forEach((b) => { b.disabled = true; });
    if (customInputEl) customInputEl.disabled = true;
    if (customSendBtn) customSendBtn.disabled = true;

    if (seedActionBtn) {
      seedActionBtn.classList.add('active');
      window.setTimeout(() => seedActionBtn.classList.remove('active'), 260);
    }

    try {
      let refinedPrompt = '';

      if (!seedOnly) {
        const refineRes = await fetch('/api/mobile/edit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: currentItem.filename,
            editType,
            instruction: String(customInstruction || '').trim(),
            seedMode,
            thinking: thinkModeEnabled,
            previewOnly: true,
          }),
        });
        const refineData = await refineRes.json();
        if (!refineRes.ok) throw new Error(refineData.error || `Server error ${refineRes.status}`);

        refinedPrompt = String(refineData.refinedPrompt || '').trim();
        if (!refinedPrompt) throw new Error('Could not refine prompt.');

        stopProgress(50);
        showStatus('Generating image… 50%');
        startProgress({ min: 50, max: 94, perSec: 0.55, label: 'Generating image…' });
      }

      const generatePayload = {
        filename: currentItem.filename,
        editType,
        instruction: String(customInstruction || '').trim(),
        seedMode,
      };
      if (seedOnly) {
        generatePayload.seedOnly = true;
      } else {
        generatePayload.refinedPrompt = refinedPrompt;
      }

      const generateRes = await fetch('/api/mobile/edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(generatePayload),
      });
      const data = await generateRes.json();
      if (!generateRes.ok) throw new Error(data.error || `Server error ${generateRes.status}`);

      stopProgress(100);
      showStatus('Done! 100%');
      if (data.savedFilename) {
        prependNewImage(data.savedFilename);
      }
      window.setTimeout(() => {
        hideStatus();
      }, 900);
    } catch (err) {
      stopProgress(0);
      showStatus(err.message || 'Generation failed.', true);
    } finally {
      presetBtns.forEach((b) => { b.disabled = false; });
      if (customInputEl) customInputEl.disabled = false;
      if (customSendBtn) customSendBtn.disabled = false;
    }
  }

  // -------------------------------------------------------------------------
  // Refine actions — real flow engine (issue #77: combined with the 5
  // legacy prompt-rewrite presets above). Unlike those, these edit the
  // existing pixels directly via the same `/api/models/refine/generate`
  // endpoint the desktop Refine UI uses (workflowFile/imageDataUrl/
  // advancedValues — see app/mcp/nomad_client.py's submit_refine for the
  // reference shape), not a prompt rewrite + full regenerate. Values below
  // mirror app/instructions/flows/refine/portrait-fix/pf_relight.json and
  // .../core/remove_bg_simple.json.
  // -------------------------------------------------------------------------
  const REFINE_ACTIONS = {
    relight: {
      workflowFile: 'workflows/refine/refine_qwen_2511_edit.json',
      imageNodeId: '7',
      label: 'Relighting…',
      buildAdvancedValues: () => ({
        '13.prompt': "Relight this image with warm golden hour sunlight coming from one side, "
          + "creating soft warm highlights on the skin and a gentle long shadow, while keeping "
          + "the rest of the lighting natural. Preserve the subject's identity, pose, composition "
          + "and all details exactly. Only change the lighting.",
        '15.steps': 4,
        '15.cfg': 1,
        '15.seed': Math.floor(Math.random() * 1e9),
      }),
    },
    remove_background: {
      workflowFile: 'workflows/refine/refine_remove_background_simple.json',
      imageNodeId: '17',
      label: 'Removing background…',
      buildAdvancedValues: () => ({
        '29.bg_removal_name': 'birefnet.safetensors',
        '_postprocess.defringe': true,
        '_postprocess.defringe_strength': 4,
      }),
    },
  };

  // /api/models/refine/generate requires a base64 data: URL, not a
  // filename/path — the slide's <img src> is a server URL
  // (/api/images/<filename>), so it has to be fetched and re-encoded.
  async function imageUrlToDataUrl(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Could not read image (HTTP ${res.status})`);
    const blob = await res.blob();
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('Could not read image.'));
      reader.readAsDataURL(blob);
    });
  }

  async function runRefineAction(actionKey) {
    const action = REFINE_ACTIONS[actionKey];
    if (!action || !currentItem) return;

    hideResult();
    closeEditPanel(false);
    showStatus(`${action.label} 0%`);
    startProgress({ min: 4, max: 92, perSec: 0.4, label: action.label });
    presetBtns.forEach((b) => { b.disabled = true; });
    if (customInputEl) customInputEl.disabled = true;
    if (customSendBtn) customSendBtn.disabled = true;

    try {
      const imageUrl = `/api/images/${encodeURIComponent(currentItem.filename)}`;
      const imageDataUrl = await imageUrlToDataUrl(imageUrl);

      const res = await fetch('/api/models/refine/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflowFile: action.workflowFile,
          imageDataUrl,
          imageNodeId: action.imageNodeId,
          advancedValues: action.buildAdvancedValues(),
        }),
      });
      const data = await res.json();
      if (!res.ok || data.ok === false) throw new Error(data.error || `Server error ${res.status}`);

      stopProgress(100);
      showStatus('Done! 100%');
      if (data.savedFilename) prependNewImage(data.savedFilename);
      window.setTimeout(() => { hideStatus(); }, 900);
    } catch (err) {
      stopProgress(0);
      showStatus(err.message || 'Generation failed.', true);
    } finally {
      presetBtns.forEach((b) => { b.disabled = false; });
      if (customInputEl) customInputEl.disabled = false;
      if (customSendBtn) customSendBtn.disabled = false;
    }
  }

  refineActionBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      setCustomPromptOpen(false);
      runRefineAction(btn.dataset.refineAction);
    });
  });

  // -------------------------------------------------------------------------
  // Prepend newly generated image at index 0, navigate to it
  // -------------------------------------------------------------------------
  function prependNewImage(savedFilename) {
    allImages.unshift({ filename: savedFilename });
    buildThumbstrip();
    showSlide(0, -1);
  }

  // -------------------------------------------------------------------------
  // Boot
  // -------------------------------------------------------------------------
  restoreSeedRandomizeToggle();
  applySeedRandomizeUi();
  restoreThinkToggle();
  applyThinkUi();
  buildThumbstrip();
  loadImages();
})();
