'use strict';
// Album — full, uncapped archive of everything generated across Create
// (Scenes/Simple/Enhance/flow pages). Reads the exact same localStorage list
// as the "Generations" recent panel (see flow-state.js / create/index.js
// saveSessionSnapshot()) — Album just never truncates the display.
//
// Cards reuse the same .rp-card poster markup and CSS as the Refine >
// Presets cards (ns_refine_presets.html / refine_presets.css): a real <img>
// fills the card, with a bottom scrim fading to the theme's card color and
// a cursor-tracked spotlight on hover — see attachSpotlight() below.
//
// The expanded preview (crossfading images, prompt, "go to flow" button)
// used to open on hover (dwell timer + portal overlay). That caused a pile
// of z-order edge cases: the overlay could visually overlap neighboring
// cards, which either stole their hover or bled native :hover through to
// them. Click-to-open sidesteps all of it — no continuous hover state to
// fight over, just a discrete open/close.

(function albumGalleryPage() {
  var SESS_KEY = 'oj-create-sessions-history-v1';
  var CYCLE_MS = 1400;
  var grid = document.getElementById('album-grid');
  var emptyEl = document.getElementById('album-empty');
  var countEl = document.getElementById('album-count');
  // #album-flows-view's own hidden state — this module's zoom buttons are
  // shared with Images mode (album/album_images.js); guarding on this stops
  // the two from fighting over disabled-state/clicks (see applyZoom below).
  var flowsView = document.getElementById('album-flows-view');
  if (!grid) return;

  // ── Card size zoom (reset/+/-) ────────────────────────────────────────
  // Same idea as Nomad Studio's own --cs-card-size zoom (nomad_studio.js),
  // adapted to Album's .rp-grid: steps set --rp-card-min, which drives the
  // grid's minmax() column width (see .rp-grid in refine_presets.css).
  var ZOOM_STEPS = [180, 220, 260, 300, 340, 380];
  var ZOOM_DEFAULT = 3; // index of 300px — widened default (issue #78, less dead space at 1080p)
  var ZOOM_KEY = 'ns-album-card-zoom-step';

  function getZoomStep() {
    var i = parseInt(localStorage.getItem(ZOOM_KEY), 10);
    if (isNaN(i) || i < 0 || i >= ZOOM_STEPS.length) i = ZOOM_DEFAULT;
    return i;
  }

  function applyZoom(i) {
    document.documentElement.style.setProperty('--rp-card-min', ZOOM_STEPS[i] + 'px');
    var inBtn  = document.getElementById('album-card-zoom-in');
    var outBtn = document.getElementById('album-card-zoom-out');
    // Only claim the shared buttons' disabled state while Flows is the
    // visible mode — Images mode (album_images.js) sets the same attribute
    // for its own bounds when it's the one showing.
    if (flowsView && flowsView.hidden) return;
    if (inBtn)  inBtn.disabled  = (i >= ZOOM_STEPS.length - 1);
    if (outBtn) outBtn.disabled = (i <= 0);
  }

  applyZoom(getZoomStep());

  var zoomInBtn    = document.getElementById('album-card-zoom-in');
  var zoomOutBtn   = document.getElementById('album-card-zoom-out');
  var zoomResetBtn = document.getElementById('album-card-zoom-reset');
  if (zoomInBtn) {
    zoomInBtn.addEventListener('click', function () {
      if (flowsView && flowsView.hidden) return; // Images mode owns this press instead
      var i = Math.min(getZoomStep() + 1, ZOOM_STEPS.length - 1);
      localStorage.setItem(ZOOM_KEY, String(i));
      applyZoom(i);
    });
  }
  if (zoomOutBtn) {
    zoomOutBtn.addEventListener('click', function () {
      if (flowsView && flowsView.hidden) return;
      var i = Math.max(getZoomStep() - 1, 0);
      localStorage.setItem(ZOOM_KEY, String(i));
      applyZoom(i);
    });
  }
  if (zoomResetBtn) {
    zoomResetBtn.addEventListener('click', function () {
      if (flowsView && flowsView.hidden) return;
      localStorage.setItem(ZOOM_KEY, String(ZOOM_DEFAULT));
      applyZoom(ZOOM_DEFAULT);
    });
  }

  function loadSessions() {
    try {
      var raw = localStorage.getItem(SESS_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list.filter(function (s) {
        return s && s.data && Array.isArray(s.data.images) && s.data.images.length;
      }) : [];
    } catch (_) {
      return [];
    }
  }

  // Drops one entry from the shared session history — used when the image
  // file behind a card is gone (issue #82), so a dead entry doesn't sit in
  // the Album forever. Matches by instanceId (falls back to id) rather than
  // the in-memory `sess` object, since the list is re-read fresh from
  // localStorage instead of mutated in place.
  function removeSession(sess) {
    try {
      var raw = localStorage.getItem(SESS_KEY);
      var list = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(list)) return;
      var key = sess.instanceId || sess.id;
      var next = key
        ? list.filter(function (s) { return !s || (s.instanceId || s.id) !== key; })
        : list.filter(function (s) { return s !== sess; });
      localStorage.setItem(SESS_KEY, JSON.stringify(next));
    } catch (_) {}
  }

  function imgUrl(u, w) {
    if (!u) return '';
    if (u.indexOf('/api/images/') === 0 && u.indexOf('/thumb') === -1) {
      return u + '/thumb?w=' + w;
    }
    return u;
  }

  // object-fit/background-position: cover centers by default, which for a
  // portrait (taller-than-wide) source image usually crops off the top of
  // the subject (heads, etc.) — anchor those to the top instead. Landscape
  // and square images keep the normal centered crop.
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

  function formatDate(ts) {
    if (!ts) return '';
    try {
      return new Date(ts).toLocaleString(undefined, {
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      });
    } catch (_) { return ''; }
  }

  // Same routing rules as the History panel's row click handler
  // (nomad_studio.js) — kept here too since Album is a separate page.
  function goToFlow(sess) {
    try { sessionStorage.setItem('oj-load-session', JSON.stringify(sess)); } catch (_) {}
    var type = sess.type || '';
    if (type.indexOf('refine.') === 0) {
      window.location.href = '/nomad-studio/refine/' + type.slice(7).replace(/_/g, '-');
    } else if (type.indexOf('mix.') === 0) {
      window.location.href = '/nomad-studio/mix/' + type.slice(4).replace(/_/g, '-');
    } else if (type.indexOf('create.') === 0) {
      window.location.href = '/nomad-studio/create/' + type.slice(7).replace(/_/g, '-');
    } else if (type === 'scenes') {
      window.location.href = '/nomad-studio/create/scenes';
    } else if (type === 'assist') {
      window.location.href = '/nomad-studio/create/assist';
    } else {
      window.location.href = '/nomad-studio';
    }
  }

  // ── Expand overlay (click-to-open) ───────────────────────────────────────
  // Lives in <body> (a real portal) rather than nested inside the card —
  // .cs-card has overflow:hidden, and a card mid entry-animation becomes a
  // containing block for `position: fixed` descendants, which clips the
  // overlay to the tiny card box otherwise.
  var activeOverlay = null;
  var activeCard = null;
  var activeCycle = null;

  function closeOverlay() {
    if (activeOverlay) {
      activeOverlay.classList.remove('is-open');
      if (activeCycle) activeCycle.stop();
      var toRemove = activeOverlay;
      setTimeout(function () { if (toRemove.parentNode) toRemove.parentNode.removeChild(toRemove); }, 200);
    }
    // Return focus to the card that opened this overlay — otherwise a
    // keyboard user closing it (Escape, or clicking-outside via keyboard
    // activation elsewhere) loses their place entirely (issue #80).
    var cardToRefocus = activeCard;
    activeOverlay = null;
    activeCard = null;
    activeCycle = null;
    if (cardToRefocus) cardToRefocus.focus();
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && activeOverlay) closeOverlay();
  });

  function buildExpand(card, sess) {
    var expand = document.createElement('div');
    expand.className = 'album-card-expand';
    // Focusable-but-not-tab-stopped container (standard dialog pattern) —
    // openOverlayFor() focuses it on open so keyboard users land somewhere
    // inside the overlay instead of on whatever was under their cursor
    // (issue #80). Tab from here reaches the real "Go to flow" button below.
    expand.tabIndex = -1;
    expand.setAttribute('role', 'dialog');
    expand.setAttribute('aria-label', sess.label || sess.type || 'Flow');

    var media = document.createElement('div');
    media.className = 'album-card-expand-media';

    var imgsWrap = document.createElement('div');
    imgsWrap.className = 'album-card-expand-imgs';
    var layerA = document.createElement('img');
    layerA.className = 'album-card-expand-img is-visible';
    var layerB = document.createElement('img');
    layerB.className = 'album-card-expand-img';
    // Quant/time are per-image data already collected by
    // _collectFlowSnapshot but never surfaced anywhere (issue #83) — same
    // classes/positions as flow-gallery's on-image labels for a consistent
    // look, forced visible here instead of hover-gated since the overlay is
    // already a deliberate "show me the details" view. No resolution label:
    // unlike flow-gallery's own cards (which render the real full image),
    // these layers load a 640px thumbnail (see `urls` below) — its
    // naturalWidth would show the thumb's size, not the actual generation
    // resolution, which isn't stored anywhere to check it against.
    var timeLabel = document.createElement('span');
    timeLabel.className = 'nit-img-time';
    var quantLabel = document.createElement('span');
    quantLabel.className = 'nit-img-quant';
    [layerA, layerB].forEach(function (layer) {
      layer.addEventListener('load', function () {
        layer.style.objectPosition = (layer.naturalHeight > layer.naturalWidth) ? 'center top' : 'center center';
      });
    });
    imgsWrap.appendChild(layerA);
    imgsWrap.appendChild(layerB);
    imgsWrap.appendChild(timeLabel);
    imgsWrap.appendChild(quantLabel);
    media.appendChild(imgsWrap);

    var top = document.createElement('div');
    top.className = 'album-card-expand-top';
    var badge = document.createElement('span');
    badge.className = 'album-card-expand-badge';
    badge.textContent = sess.label || sess.type || 'Flow';
    var date = document.createElement('span');
    date.className = 'album-card-expand-date';
    date.textContent = formatDate(sess.ts);
    top.appendChild(badge);
    top.appendChild(date);
    media.appendChild(top);

    expand.appendChild(media);

    var bottom = document.createElement('div');
    bottom.className = 'album-card-expand-bottom';
    var prompt = document.createElement('p');
    prompt.className = 'album-card-expand-prompt';
    var prompts = sess.data.imagePrompts || [];
    prompt.textContent = prompts[0] || sess.prompt || '';

    var quants = sess.data.imageQuantizations || [];
    var genSeconds = sess.data.imageGenSeconds || [];
    function setMetaLabels(i) {
      quantLabel.textContent = quants[i] ? String(quants[i]).toUpperCase() : '';
      var secs = genSeconds[i];
      timeLabel.textContent = (typeof secs === 'number')
        ? (secs < 10 ? secs.toFixed(1) : Math.round(secs)) + 's'
        : '';
    }
    setMetaLabels(0);
    var gotoBtn = document.createElement('button');
    gotoBtn.type = 'button';
    gotoBtn.className = 'album-card-expand-goto';
    gotoBtn.setAttribute('aria-label', tF('Go to flow'));
    gotoBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M5 12h14M13 5l7 7-7 7"/></svg>' +
      '<span class="cs-mode-tip">' + tH('Go to flow') + '</span>';
    gotoBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      goToFlow(sess);
    });
    bottom.appendChild(prompt);
    bottom.appendChild(gotoBtn);
    expand.appendChild(bottom);

    // Clicking inside the overlay (but not the goto button) shouldn't bubble
    // up to the document-level "click outside closes it" listener.
    expand.addEventListener('click', function (e) { e.stopPropagation(); });

    document.body.appendChild(expand);

    var urls = sess.data.images.map(function (u) { return imgUrl(u, 640); });
    var idx = 0;
    var showingA = true;
    layerA.src = urls[0] || '';

    var cycleTimer = null;
    function tick() {
      if (urls.length < 2) return;
      idx = (idx + 1) % urls.length;
      var incoming = showingA ? layerB : layerA;
      var outgoing = showingA ? layerA : layerB;
      incoming.src = urls[idx];
      incoming.classList.add('is-visible');
      outgoing.classList.remove('is-visible');
      showingA = !showingA;
      prompt.textContent = prompts[idx] || sess.prompt || '';
      setMetaLabels(idx);
    }

    return {
      el: expand,
      start: function () { if (urls.length > 1 && !cycleTimer) cycleTimer = setInterval(tick, CYCLE_MS); },
      stop: function () { if (cycleTimer) { clearInterval(cycleTimer); cycleTimer = null; } },
    };
  }

  // Square 1:1 overlay grown out from the card's own rect, clamped to stay
  // fully on-screen.
  function positionExpand(card, expandEl) {
    var rect = card.getBoundingClientRect();
    var scale = 1.5;
    var size = Math.round(rect.width * scale);
    var w = size, h = size;
    var cx = rect.left + rect.width / 2;
    var cy = rect.top + rect.height / 2;
    var left = cx - w / 2;
    var top = cy - h / 2;

    var margin = 10;
    var vw = window.innerWidth, vh = window.innerHeight;
    var maxSize = Math.min(vw, vh) - margin * 2;
    if (size > maxSize) { w = h = maxSize; }
    if (left < margin) left = margin;
    if (top < margin) top = margin;
    if (left + w > vw - margin) left = vw - margin - w;
    if (top + h > vh - margin) top = vh - margin - h;

    expandEl.style.left = left + 'px';
    expandEl.style.top = top + 'px';
    expandEl.style.width = w + 'px';
    expandEl.style.height = h + 'px';
  }

  function openOverlayFor(card, sess) {
    if (activeCard === card) return; // already open for this card
    closeOverlay();
    var expandCtl = buildExpand(card, sess);
    positionExpand(card, expandCtl.el);
    activeOverlay = expandCtl.el;
    activeCard = card;
    activeCycle = expandCtl;
    requestAnimationFrame(function () {
      if (activeOverlay !== expandCtl.el) return; // superseded already
      expandCtl.el.classList.add('is-open');
      expandCtl.el.focus();
    });
    setTimeout(function () {
      if (activeCycle === expandCtl) expandCtl.start();
    }, 150);
  }

  // Click anywhere outside the open overlay (and outside the card that
  // opened it) closes it.
  document.addEventListener('click', function (e) {
    if (!activeOverlay) return;
    if (activeOverlay.contains(e.target)) return;
    if (activeCard && activeCard.contains(e.target)) return;
    closeOverlay();
  });

  // Cursor-tracked spotlight — same mechanism as the Presets cards
  // (attachSpotlight in nomad_studio.js / the inline version in
  // ns_refine_presets.html), reimplemented here since Album doesn't load
  // either of those scripts.
  function attachSpotlight(card) {
    card.addEventListener('mousemove', function (e) {
      var rect = card.getBoundingClientRect();
      var x = ((e.clientX - rect.left) / rect.width  * 100).toFixed(1) + '%';
      var y = ((e.clientY - rect.top)  / rect.height * 100).toFixed(1) + '%';
      card.style.setProperty('--cs-mx', x);
      card.style.setProperty('--cs-my', y);
    });
    card.addEventListener('mouseleave', function () {
      card.style.setProperty('--cs-mx', '50%');
      card.style.setProperty('--cs-my', '50%');
    });
  }

  function buildCard(sess, idx) {
    // Same markup/CSS as the Refine > Presets cards (.rp-card, see
    // refine_presets.css) — full-bleed photo with a bottom scrim fading to
    // the theme's card color, instead of the old --cs-card-bg background
    // trick.
    var card = document.createElement('div');
    card.className = 'rp-card album-rp-card';
    card.style.animationDelay = Math.min(idx * 25, 400) + 'ms';
    card.tabIndex = 0;
    card.setAttribute('role', 'button');

    var media = document.createElement('div');
    media.className = 'rp-card-media';
    var img = document.createElement('img');
    img.loading = 'lazy';
    // Decorative: the flow name and prompt are already adjacent visible text
    // (.rp-card-name/.rp-card-desc below) — a non-empty alt here just made a
    // screen reader announce the flow name twice per card (issue #81).
    img.alt = '';
    var cardImgUrl = imgUrl(sess.data.images[0], 420);
    img.src = cardImgUrl;
    media.appendChild(img);
    card.appendChild(media);

    probeOrientation(cardImgUrl, function (o) {
      img.style.objectPosition = (o === 'portrait') ? 'center top' : 'center center';
    });

    // The session list lives in localStorage; the files live on disk. They
    // drift apart whenever the output folder is moved/cleaned/repointed —
    // the entry survives, the file doesn't. Without this the card silently
    // renders the browser's broken-image glyph (issue #82). The prompt/name
    // below stays readable either way, and a Remove button lets the user
    // drop the now-useless entry instead of it sitting there forever.
    var isBroken = false;
    img.addEventListener('error', function () {
      if (isBroken) return; // onerror can fire more than once for one <img>
      isBroken = true;
      card.classList.add('is-broken');
      media.classList.add('rp-card-media--broken');
      media.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" ' +
        'stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/>' +
        '<path d="m3 16 5-5 4 4 4-5 5 6"/><circle cx="8.5" cy="8.5" r="1.5"/></svg>' +
        '<span>' + tH('Image missing') + '</span>';

      var delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'cs-session-recent-del album-card-del';
      delBtn.title = tF('Remove from Album');
      delBtn.setAttribute('aria-label', tF('Remove from Album'));
      delBtn.innerHTML =
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>' +
        '<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>';
      delBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        removeSession(sess);
        render();
      });
      card.appendChild(delBtn);
    });

    var body = document.createElement('div');
    body.className = 'rp-card-body';
    var name = document.createElement('p');
    name.className = 'rp-card-name';
    name.textContent = sess.label || sess.type || 'Flow';
    var desc = document.createElement('p');
    desc.className = 'rp-card-desc';
    // sess.prompt is whatever was last in the prompt box when the session
    // snapshot was written — not necessarily the prompt that made THIS
    // (the first) image. imagePrompts is index-aligned with images, so use
    // that when present (issue #79).
    desc.textContent = (sess.data.imagePrompts && sess.data.imagePrompts[0]) || sess.prompt || '';
    body.appendChild(name);
    body.appendChild(desc);
    card.appendChild(body);

    card.setAttribute('aria-label', (name.textContent + (desc.textContent ? ': ' + desc.textContent : '')));

    card.addEventListener('click', function (e) {
      e.stopPropagation();
      if (isBroken) return; // nothing to preview — the Remove button is the only action
      openOverlayFor(card, sess);
    });
    // Enter/Space activate the card like a real button — the grid has no
    // other way in for keyboard users (issue #80). Space's default action
    // (page scroll) is prevented like any other button would.
    card.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
      e.preventDefault();
      e.stopPropagation();
      if (isBroken) return;
      openOverlayFor(card, sess);
    });
    attachSpotlight(card);

    return card;
  }

  function render() {
    var sessions = loadSessions();
    grid.innerHTML = '';
    closeOverlay();

    if (!sessions.length) {
      if (emptyEl) emptyEl.hidden = false;
      if (countEl) countEl.textContent = '';
      return;
    }
    if (emptyEl) emptyEl.hidden = true;
    if (countEl) countEl.textContent = sessions.length + (sessions.length === 1 ? ' entry' : ' entries');

    var frag = document.createDocumentFragment();
    sessions.forEach(function (sess, i) { frag.appendChild(buildCard(sess, i)); });
    grid.appendChild(frag);
  }

  render();

  // Re-render if another tab/page updates the shared history list.
  window.addEventListener('storage', function (e) {
    if (e.key === SESS_KEY) render();
  });

  // Exposed so view_mode.js can resync the shared count badge and zoom
  // buttons right when Flows becomes the active mode again.
  window.albumGalleryPage = {
    refresh: render,
    syncZoom: function () { applyZoom(getZoomStep()); },
  };
})();
