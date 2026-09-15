/* ============================================================
   ns_image_tray.js — Image Tray shared module
   Auto-initializes on DOMContentLoaded on any NS create page
   that includes this script and has #nit-tray-btn in the DOM.
   ============================================================ */
(function () {
  'use strict';

  var TRAY_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20M2 12v8a2 2 0 002 2h16a2 2 0 002-2v-8M2 12l3-9h14l3 9"/></svg>';

  // ── DOM refs (resolved after DOMContentLoaded) ─────────────────────────────
  var trayBtn   = null;
  var trayModal = null;
  var trayClose = null;
  var trayGrid  = null;
  var trayEmpty = null;
  var trayBadge = null;

  var _modalOpen = false;

  // ── Helpers ────────────────────────────────────────────────────────────────

  // Session (and other subfoldered) images are served from
  // /api/images/session/<folder>/<file> — the "filename" the backend
  // actually expects for /meta is everything after "/api/images/", not
  // just the last path segment. Grabbing only the last segment (the old
  // behavior) threw away the "session/<folder>/" prefix, so every
  // meta write (Send to Tray, tags, favorite, …) for an image generated
  // inside a Session silently 404'd against a file that was never at that
  // flattened path — the button still played its "sent" animation
  // (applyTrayMeta had no response.ok check either, see below) even though
  // nothing was actually saved.
  function filenameFromUrl(url) {
    var clean = String(url || '').split('?')[0];
    var marker = '/api/images/';
    var idx = clean.indexOf(marker);
    if (idx !== -1) return clean.slice(idx + marker.length);
    return clean.split('/').pop();
  }

  function applyTrayMeta(filename, value) {
    // Encode each path segment separately (not the whole string) so a
    // "session/<folder>/<file>" filename keeps its literal "/" separators
    // for Flask's <path:filename> route instead of becoming "%2F" (which
    // would just 404).
    var encodedPath = String(filename || '').split('/').map(encodeURIComponent).join('/');
    return fetch('/api/images/' + encodedPath + '/meta', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tray: value }),
    }).then(function (r) {
      if (!r.ok) throw new Error('Tray update failed (' + r.status + ')');
      return r.json();
    });
  }

  // ── Badge ──────────────────────────────────────────────────────────────────

  function refreshBadge() {
    fetch('/api/images/tray')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var count = (data && Array.isArray(data.images)) ? data.images.length : 0;
        if (!trayBadge) return;
        trayBadge.textContent = count;
        trayBadge.hidden = count === 0;
      })
      .catch(function () {});
  }

  // ── Send to tray ───────────────────────────────────────────────────────────

  function preloadThumb(imgUrl) {
    var filename = filenameFromUrl(imgUrl);
    if (!filename) return;
    var encodedPath = filename.split('/').map(encodeURIComponent).join('/');
    var pre = new Image();
    pre.src = '/api/images/' + encodedPath + '/thumb';
  }

  function sendToTray(imgUrl) {
    var filename = filenameFromUrl(imgUrl);
    if (!filename) return;
    preloadThumb(imgUrl);
    applyTrayMeta(filename, true).then(function () {
      refreshBadge();
      if (_modalOpen) openModal();
      showTrayFeedback(imgUrl);
      document.dispatchEvent(new CustomEvent('tray:updated'));
    }).catch(function (err) {
      if (window.console) console.error('[Tray] Send to tray failed:', err);
    });
  }

  function showTrayFeedback(imgUrl) {
    if (!trayBtn) return;
    trayBtn.classList.add('nit-tray-btn--sent');
    setTimeout(function () { trayBtn.classList.remove('nit-tray-btn--sent'); }, 800);
  }

  // ── Remove from tray ──────────────────────────────────────────────────────

  function removeFromTray(filename, itemEl) {
    applyTrayMeta(filename, false).then(function () {
      if (itemEl && itemEl.parentNode) itemEl.parentNode.removeChild(itemEl);
      refreshBadge();
      if (trayGrid && !trayGrid.children.length) {
        if (trayEmpty) trayEmpty.hidden = false;
      }
      // Let the flow's image-picker tray strips (and anything else listening)
      // know an image dropped out of the tray, so they drop it too instead of
      // still offering/showing it as a selectable input.
      document.dispatchEvent(new CustomEvent('tray:updated'));
    }).catch(function () {});
  }

  // ── Modal ─────────────────────────────────────────────────────────────────

  function openModal() {
    if (!trayModal) return;
    _modalOpen = true;
    trayModal.hidden = false;

    // Clear and show loading state
    if (trayGrid) trayGrid.innerHTML = '';
    if (trayEmpty) trayEmpty.hidden = true;

    fetch('/api/images/tray')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var images = (data && Array.isArray(data.images)) ? data.images : [];
        if (!trayGrid) return;
        trayGrid.innerHTML = '';

        if (!images.length) {
          if (trayEmpty) trayEmpty.hidden = false;
          return;
        }

        images.forEach(function (img) {
          var item = document.createElement('div');
          item.className = 'nit-tray-item';
          item.setAttribute('data-tray-filename', img.filename);

          var imgEl = document.createElement('img');
          imgEl.src = img.thumb_url;
          imgEl.alt = img.filename;
          imgEl.loading = 'lazy';
          imgEl.addEventListener('click', function () {
            window.open(img.url, '_blank');
          });
          item.appendChild(imgEl);

          var delBtn = document.createElement('button');
          delBtn.type = 'button';
          delBtn.className = 'nit-tray-del-btn';
          delBtn.setAttribute('aria-label', 'Remove from tray');
          delBtn.innerHTML = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 3l10 10M13 3L3 13"/></svg>';
          (function (fn, el) {
            delBtn.addEventListener('click', function (e) {
              e.stopPropagation();
              removeFromTray(fn, el);
            });
          }(img.filename, item));
          item.appendChild(delBtn);

          trayGrid.appendChild(item);
        });
      })
      .catch(function () {
        if (trayGrid) trayGrid.innerHTML = '<p class="nse-model-empty">Error loading tray.</p>';
      });
  }

  function closeModal() {
    if (!trayModal) return;
    _modalOpen = false;
    trayModal.hidden = true;
  }

  // ── Drag-and-drop on tray button ──────────────────────────────────────────

  function initDragHandlers() {
    if (!trayBtn) return;

    trayBtn.addEventListener('dragover', function (e) {
      if (!e.dataTransfer.types.includes('application/x-tray-url')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      trayBtn.classList.add('drag-over');
    });

    trayBtn.addEventListener('dragleave', function (e) {
      if (!trayBtn.contains(e.relatedTarget)) {
        trayBtn.classList.remove('drag-over');
      }
    });

    trayBtn.addEventListener('drop', function (e) {
      e.preventDefault();
      trayBtn.classList.remove('drag-over');
      var url = e.dataTransfer.getData('application/x-tray-url');
      if (url) sendToTray(url);
    });
  }

  // ── Global delegation for .nit-send-tray-btn clicks (capture phase) ─────
  // Must use capture=true so stopPropagation fires before the parent tile's
  // click handler (lightbox) gets the event.
  //
  // Selector is deliberately narrower than just ".nit-send-tray-btn": the
  // delete button (.nit-delete-img-btn) also carries that class to reuse its
  // positioning/hover CSS, so a plain ".nit-send-tray-btn" match here would
  // catch delete clicks too, stopPropagation() them (in the capture phase,
  // before the delete button's own click handler ever runs) and silently do
  // nothing (it has no data-tray-img-url). Requiring the attribute makes this
  // delegate only to buttons that actually mean "send to tray".

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.nit-send-tray-btn[data-tray-img-url]');
    if (!btn) return;
    e.stopPropagation();
    e.preventDefault();
    var url = btn.getAttribute('data-tray-img-url');
    if (url) sendToTray(url);
  }, true);

  // ── Init ──────────────────────────────────────────────────────────────────

  function init() {
    trayBtn   = document.getElementById('nit-tray-btn');
    trayModal = document.getElementById('nit-tray-modal');
    trayClose = document.getElementById('nit-tray-close');
    trayGrid  = document.getElementById('nit-tray-grid');
    trayEmpty = document.getElementById('nit-tray-empty');
    trayBadge = document.getElementById('nit-tray-badge');

    if (!trayBtn) return; // page doesn't have tray UI

    trayBtn.addEventListener('click', openModal);

    if (trayClose) {
      trayClose.addEventListener('click', closeModal);
    }

    if (trayModal) {
      trayModal.addEventListener('click', function (e) {
        if (e.target === trayModal) closeModal();
      });
    }

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && _modalOpen) closeModal();
    });

    initDragHandlers();
    refreshBadge();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
}());
