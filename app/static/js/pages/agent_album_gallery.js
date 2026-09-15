'use strict';
// Agent Album — read-only view of one MCP agent's plain generations (not
// grouped into flow sessions, unlike /album). Same rp-card visual language
// as album_gallery.js, but the data source is the server-side per-viewer
// image list (GET /api/images?viewer=<slug>) instead of the localStorage
// flow-session history — browsing here never touches the app's own active
// session (see agent_album() in routes/main.py).
//
// Lightbox: same visual language as Create's .nsc-lightbox (dark backdrop,
// round nav/close, counter) but "windowed" — see the .agent-lightbox* CSS
// comment in nomad_studio.css for why (nsc-lightbox's controls drift out to
// the browser's edges when the image doesn't fill the screen; anchoring to
// a bounded window box fixes that).

(function agentAlbumGalleryPage() {
  var root = document.getElementById('agent-album-root');
  var grid = document.getElementById('album-grid');
  var emptyEl = document.getElementById('album-empty');
  var countEl = document.getElementById('album-count');
  var loadMoreBtn = document.getElementById('album-load-more');
  if (!root || !grid) return;

  var api = window.openJourneyApi;
  var agentSlug = root.dataset.agentSlug || '';
  var agentName = root.dataset.agentName || 'Agent';
  var PAGE_LIMIT = 60;

  var state = { total: 0, loaded: 0, nextCursor: null, snapshot: null, loading: false };
  var allEntries = []; // flat list across pages, in display order — lightbox navigates this

  // ── Card size zoom (reset/+/-) — same mechanism as /album, separate
  // localStorage key so the two pages don't fight over card size. ────────
  var ZOOM_STEPS = [180, 220, 260, 300, 340, 380];
  var ZOOM_DEFAULT = 2;
  var ZOOM_KEY = 'ns-agent-album-card-zoom-step';

  function getZoomStep() {
    var i = parseInt(localStorage.getItem(ZOOM_KEY), 10);
    if (isNaN(i) || i < 0 || i >= ZOOM_STEPS.length) i = ZOOM_DEFAULT;
    return i;
  }
  function applyZoom(i) {
    document.documentElement.style.setProperty('--rp-card-min', ZOOM_STEPS[i] + 'px');
    var inBtn = document.getElementById('album-card-zoom-in');
    var outBtn = document.getElementById('album-card-zoom-out');
    if (inBtn) inBtn.disabled = (i >= ZOOM_STEPS.length - 1);
    if (outBtn) outBtn.disabled = (i <= 0);
  }
  applyZoom(getZoomStep());
  var zoomInBtn = document.getElementById('album-card-zoom-in');
  var zoomOutBtn = document.getElementById('album-card-zoom-out');
  var zoomResetBtn = document.getElementById('album-card-zoom-reset');
  if (zoomInBtn) zoomInBtn.addEventListener('click', function () {
    var i = Math.min(getZoomStep() + 1, ZOOM_STEPS.length - 1);
    localStorage.setItem(ZOOM_KEY, String(i));
    applyZoom(i);
  });
  if (zoomOutBtn) zoomOutBtn.addEventListener('click', function () {
    var i = Math.max(getZoomStep() - 1, 0);
    localStorage.setItem(ZOOM_KEY, String(i));
    applyZoom(i);
  });
  if (zoomResetBtn) zoomResetBtn.addEventListener('click', function () {
    localStorage.setItem(ZOOM_KEY, String(ZOOM_DEFAULT));
    applyZoom(ZOOM_DEFAULT);
  });

  function formatDate(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString(undefined, {
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      });
    } catch (_) { return ''; }
  }

  // object-fit: cover centers by default, which crops off the top of a
  // portrait subject — anchor those to the top instead, same as /album.
  var _orientationCache = Object.create(null);
  function probeOrientation(url, cb) {
    if (!url) return;
    if (_orientationCache[url]) { cb(_orientationCache[url]); return; }
    var probe = new Image();
    probe.onload = function () {
      var o = probe.naturalHeight > probe.naturalWidth ? 'portrait' : 'landscape';
      _orientationCache[url] = o;
      cb(o);
    };
    probe.onerror = function () {};
    probe.src = url;
  }

  function attachSpotlight(card) {
    card.addEventListener('mousemove', function (e) {
      var rect = card.getBoundingClientRect();
      var x = ((e.clientX - rect.left) / rect.width * 100).toFixed(1) + '%';
      var y = ((e.clientY - rect.top) / rect.height * 100).toFixed(1) + '%';
      card.style.setProperty('--cs-mx', x);
      card.style.setProperty('--cs-my', y);
    });
    card.addEventListener('mouseleave', function () {
      card.style.setProperty('--cs-mx', '50%');
      card.style.setProperty('--cs-my', '50%');
    });
  }

  // ── Lightbox (static markup in agent_album.html, toggled via [hidden]) ──
  var lightboxEl      = document.getElementById('agent-lightbox');
  var lightboxImgEl   = document.getElementById('agent-lightbox-img');
  var lightboxBadgeEl = document.getElementById('agent-lightbox-badge');
  var lightboxCounter = document.getElementById('agent-lightbox-counter');
  var lightboxPrompt  = document.getElementById('agent-lightbox-prompt');
  var lightboxPrevBtn = document.getElementById('agent-lightbox-prev');
  var lightboxNextBtn = document.getElementById('agent-lightbox-next');
  var lightboxCloseBtn = document.getElementById('agent-lightbox-close');
  var lightboxCopyBtn = document.getElementById('agent-lightbox-copy');
  var lightboxWindowEl = lightboxEl ? lightboxEl.querySelector('.agent-lightbox-window') : null;
  var lightboxIdx = -1;

  function openLightbox(idx) {
    if (!lightboxEl || !allEntries.length) return;
    lightboxIdx = Math.max(0, Math.min(idx, allEntries.length - 1));
    var entry = allEntries[lightboxIdx];
    lightboxImgEl.src = api.getImageUrl(entry.filename, agentSlug);
    lightboxBadgeEl.textContent = (entry.meta && entry.meta.workflow_name) || agentName;
    lightboxCounter.textContent = (lightboxIdx + 1) + ' / ' + allEntries.length;
    lightboxPrompt.textContent = (entry.meta && entry.meta.positive) || '';
    if (lightboxPrevBtn) lightboxPrevBtn.disabled = lightboxIdx === 0;
    if (lightboxNextBtn) lightboxNextBtn.disabled = lightboxIdx === allEntries.length - 1;
    lightboxEl.removeAttribute('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeLightbox() {
    if (!lightboxEl) return;
    lightboxEl.setAttribute('hidden', '');
    lightboxImgEl.src = '';
    document.body.style.overflow = '';
    lightboxIdx = -1;
  }

  function navigateLightbox(dir) {
    var next = lightboxIdx + dir;
    if (next >= 0 && next < allEntries.length) openLightbox(next);
  }

  if (lightboxCloseBtn) lightboxCloseBtn.addEventListener('click', closeLightbox);
  if (lightboxPrevBtn) lightboxPrevBtn.addEventListener('click', function () { navigateLightbox(-1); });
  if (lightboxNextBtn) lightboxNextBtn.addEventListener('click', function () { navigateLightbox(1); });
  if (lightboxEl) {
    // Only the backdrop itself closes on click — not the window or its
    // controls, which is why open/close handlers stopPropagation below.
    lightboxEl.addEventListener('click', function (e) { if (e.target === lightboxEl) closeLightbox(); });
  }
  if (lightboxWindowEl) {
    lightboxWindowEl.addEventListener('click', function (e) { e.stopPropagation(); });
  }
  if (lightboxCopyBtn) {
    lightboxCopyBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var entry = allEntries[lightboxIdx];
      var text = entry && entry.meta && entry.meta.positive || '';
      if (text && navigator.clipboard) navigator.clipboard.writeText(text).catch(function () {});
    });
  }
  document.addEventListener('keydown', function (e) {
    if (!lightboxEl || lightboxEl.hasAttribute('hidden')) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') navigateLightbox(-1);
    if (e.key === 'ArrowRight') navigateLightbox(1);
  });

  function buildCard(entry, globalIdx) {
    var card = document.createElement('div');
    card.className = 'rp-card album-rp-card';
    card.style.animationDelay = Math.min((globalIdx % PAGE_LIMIT) * 25, 400) + 'ms';

    var media = document.createElement('div');
    media.className = 'rp-card-media';
    var img = document.createElement('img');
    img.loading = 'lazy';
    img.alt = (entry.meta && entry.meta.positive) || entry.filename;
    var thumbUrl = api.getImageThumbUrl(entry.filename, 420, agentSlug);
    img.src = thumbUrl;
    media.appendChild(img);
    card.appendChild(media);

    probeOrientation(thumbUrl, function (o) {
      img.style.objectPosition = (o === 'portrait') ? 'center top' : 'center center';
    });

    var body = document.createElement('div');
    body.className = 'rp-card-body';
    var name = document.createElement('p');
    name.className = 'rp-card-name';
    name.textContent = (entry.meta && entry.meta.workflow_name) || 'Generation';
    var desc = document.createElement('p');
    desc.className = 'rp-card-desc';
    desc.textContent = (entry.meta && entry.meta.positive) || '';
    body.appendChild(name);
    body.appendChild(desc);
    card.appendChild(body);

    card.addEventListener('click', function (e) {
      e.stopPropagation();
      openLightbox(globalIdx);
    });
    attachSpotlight(card);

    return card;
  }

  function renderEmpty() {
    if (emptyEl) emptyEl.hidden = false;
    if (countEl) countEl.textContent = '';
    if (loadMoreBtn) loadMoreBtn.hidden = true;
  }

  function appendEntries(entries) {
    if (!entries.length) return;
    var frag = document.createDocumentFragment();
    entries.forEach(function (entry, i) {
      var globalIdx = allEntries.length;
      allEntries.push(entry);
      frag.appendChild(buildCard(entry, globalIdx));
    });
    grid.appendChild(frag);
    state.loaded += entries.length;
    if (countEl) countEl.textContent = state.total + (state.total === 1 ? ' entry' : ' entries');
  }

  function loadPage() {
    if (state.loading) return;
    state.loading = true;
    if (loadMoreBtn) loadMoreBtn.disabled = true;

    api.listImages({
      viewer: agentSlug,
      limit: PAGE_LIMIT,
      cursor: state.nextCursor || undefined,
      snapshot: state.snapshot || undefined,
    }).then(function (data) {
      var entries = Array.isArray(data.images) ? data.images : [];
      var paging = data.paging || {};
      state.total = Number(paging.total) || 0;
      state.snapshot = paging.snapshotCursor || state.snapshot;
      state.nextCursor = paging.nextCursor || null;

      if (state.loaded === 0 && !entries.length) {
        renderEmpty();
        return;
      }
      if (emptyEl) emptyEl.hidden = true;
      appendEntries(entries);
      if (loadMoreBtn) loadMoreBtn.hidden = !paging.hasMore;
    }).catch(function () {
      if (state.loaded === 0) renderEmpty();
    }).finally(function () {
      state.loading = false;
      if (loadMoreBtn) loadMoreBtn.disabled = false;
    });
  }

  if (loadMoreBtn) loadMoreBtn.addEventListener('click', loadPage);

  if (!api || typeof api.listImages !== 'function' || !agentSlug) {
    renderEmpty();
    return;
  }
  loadPage();
})();
