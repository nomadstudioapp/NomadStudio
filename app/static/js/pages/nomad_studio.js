/* Nomad Studio — navigation + spotlight gradient */
(function () {
  'use strict';

  // === EVITAR CARGA MÚLTIPLE ===
  if (window.__nomadStudioLoaded) {
    console.warn('nomad_studio.js ya estaba cargado, saltando ejecución');
    return;
  }
  window.__nomadStudioLoaded = true;
  console.log('nomad_studio.js cargado correctamente');

  // Back/forward can restore this page from the browser's memory (bfcache)
  // without asking the server: after installing a package in Settings the
  // hub would still show the old cards. Reload in that case.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) window.location.reload();
  });

  var viewMain   = document.getElementById('cs-view-main');
  var viewCreate = document.getElementById('cs-view-create');
  var viewRefine = document.getElementById('cs-view-refine');
  var viewMix    = document.getElementById('cs-view-mix');
  var viewSession  = document.getElementById('cs-view-session');
  var backBtn        = document.getElementById('cs-back-btn');
  var refineBackBtn  = document.getElementById('cs-refine-back-btn');
  var mixBackBtn     = document.getElementById('cs-mix-back-btn');
  var sessionBackBtn   = document.getElementById('cs-session-back-btn');
  var themeCycleBtn  = document.getElementById('cs-theme-cycle-btn');
  var settingsBtnEl  = document.getElementById('cs-settings-btn');
  var cardZoomWrap   = document.getElementById('cs-card-zoom');
  var filterToggleWrap = document.getElementById('cs-filter-toggle');
  var langPanelWrap   = document.getElementById('cs-lang-panel');
  var langOverlayWrap = document.getElementById('cs-lang-overlay');
  var historyPanelWrap   = document.getElementById('cs-history-panel');
  var historyOverlayWrap = document.getElementById('cs-history-overlay');

  // Theme toggle only makes sense on the main hub — hide it on every
  // sub-view (Create/Refine/Mix/Session) instead of leaving it floating over
  // unrelated screens. Settings moved out of #cs-view-main (now docked above
  // Theme at the bottom-left, not a child of the view anymore) so it needs
  // the same explicit hide/show — it used to inherit this for free from its
  // parent's aria-hidden toggling.
  function csSyncThemeBtn() {
    if (themeCycleBtn) themeCycleBtn.hidden = !viewMain || viewMain.getAttribute('aria-hidden') === 'true';
    if (settingsBtnEl) settingsBtnEl.hidden = !viewMain || viewMain.getAttribute('aria-hidden') === 'true';
    // Card zoom is the opposite: only useful where a .cs-sub-grid is on
    // screen (Create/Refine/Mix), so hide it on the main hub instead.
    if (cardZoomWrap) cardZoomWrap.hidden = !viewMain || viewMain.getAttribute('aria-hidden') !== 'true';
    // The filter toggle needs more than "not the hub": Session and Album are
    // sub-views too but have no tag sidebar to collapse, so it also checks
    // that one is actually rendered (renderChips un-hides the bar once a view
    // produced tags). Otherwise it'd sit there toggling nothing.
    if (filterToggleWrap) {
      var onSubView = viewMain && viewMain.getAttribute('aria-hidden') === 'true';
      var sidebar = document.querySelector('.cs-view:not([aria-hidden="true"]) .cs-tag-filter--sidebar:not([hidden])');
      filterToggleWrap.hidden = !(onSubView && sidebar);
      if (!filterToggleWrap.hidden) csAlignFilterToggle(sidebar);
    }
    // Language + History are page-level widgets (siblings of #cs-view-main,
    // not children — nothing else here ever hides them), so they used to
    // float over every sub-view including Session's own recent-sessions
    // list — a list of past generations sitting on top of a list of past
    // Sessions read as clutter/duplication there specifically. Every other
    // sub-view (Create/Refine/Mix) still gets them; only Session hides them.
    var onSessionView = !!viewSession && viewSession.getAttribute('aria-hidden') !== 'true';
    [langPanelWrap, langOverlayWrap, historyPanelWrap, historyOverlayWrap].forEach(function (el) {
      if (el) el.hidden = onSessionView;
    });
  }

  /* ── Card size zoom (+/-) ────────────────────────────────────────────────
     Steps through a fixed *size* (not a min/max range) for the .cs-sub-grid
     track width, applied as CSS vars on :root so every grid (Create/Refine
     share .cs-sub-grid--hero; Mix uses plain .cs-sub-grid) resizes together.
     Earlier version used minmax(min,max): with auto-fill/auto-fit, the
     column count is picked using only the *minimum*, and any leftover
     space (always less than one column-width) is what's left to split
     across columns — so real rendered width stayed pinned near the min
     basically regardless of max. Measured on Refine: default was
     minmax(320,420) but cards rendered at ~328px, i.e. barely above min.
     A single fixed size per step removes that ambiguity entirely. */
  // heroSize drives Create/Refine (.cs-sub-grid--hero); size drives Mix
  // (plain .cs-sub-grid). CS_CARD_ZOOM_DEFAULT's step matches each grid's
  // original hard-coded minimum (what was actually rendering in practice
  // either way), so applying it on load causes no visual change.
  // Zoom-out only: JP confirmed 320×190 (hero) is the hard ceiling — +
  // must never exceed it, so there are 0 up-steps (+ stays disabled at
  // the default/top of the range) and only down-steps for shrinking.
  var CS_CARD_ZOOM_DOWN_STEPS = 4;
  var CS_CARD_ZOOM_UP_STEPS = 0;
  var CS_CARD_ZOOM_DEFAULT = CS_CARD_ZOOM_DOWN_STEPS;
  // sessionMin drives Session's own recent-sessions grid
  // (.cs-session-recent-list, a .rp-grid variant — see .cs-session-recent-
  // card-min below). It was missing entirely until now: this whole widget
  // is shown on every sub-view including Session (csSyncThemeBtn further
  // down only checks "not the main hub", same gap the filter-toggle comment
  // right above it already calls out for a different control), but only
  // Create/Refine/Mix's .cs-sub-grid ever read the two properties below —
  // clicking +/-/reset while on Session changed CSS variables nothing on
  // that page's own grid was listening for, so nothing visibly moved.
  // Base 260px matches .rp-grid's own hard-coded minmax() minimum (see
  // refine_presets.css) — same "default step causes no visual change on
  // load" rule the other two already follow.
  var CS_CARD_ZOOM_STEPS = (function () {
    var base = { size: 200, heroSize: 360, sessionMin: 260 }; // original, unzoomed size
    var stepPx = { size: 15, heroSize: 20, sessionMin: 15 };
    var steps = [];
    for (var i = -CS_CARD_ZOOM_DOWN_STEPS; i <= CS_CARD_ZOOM_UP_STEPS; i++) {
      steps.push({
        size: base.size + i * stepPx.size,
        heroSize: base.heroSize + i * stepPx.heroSize,
        sessionMin: base.sessionMin + i * stepPx.sessionMin
      });
    }
    return steps;
  })();
  // Versioned (v2, not just 'ns-card-zoom-step'): a stale index left over
  // in localStorage from an earlier min/max-based version of this feature
  // (same array length, 15) would silently get reinterpreted against the
  // new fixed-size step definitions — that's exactly why cards loaded at
  // 520px (the new top step) instead of the 320px default: JP's browser
  // still had index 14 saved from testing the old scheme. Bumping the key
  // makes it start fresh instead of misreading old data.
  var CS_CARD_ZOOM_KEY = 'ns-card-zoom-step-v2';

  function csGetCardZoomStep() {
    var i = parseInt(localStorage.getItem(CS_CARD_ZOOM_KEY), 10);
    if (isNaN(i) || i < 0 || i >= CS_CARD_ZOOM_STEPS.length) i = CS_CARD_ZOOM_DEFAULT;
    return i;
  }

  function csApplyCardZoom(i) {
    var step = CS_CARD_ZOOM_STEPS[i];
    var base = CS_CARD_ZOOM_STEPS[CS_CARD_ZOOM_DEFAULT]; // == the original, unzoomed size
    document.documentElement.style.setProperty('--cs-card-size', step.size + 'px');
    document.documentElement.style.setProperty('--cs-card-hero-size', step.heroSize + 'px');
    document.documentElement.style.setProperty('--cs-session-card-min', step.sessionMin + 'px');
    // Text (title/desc/tags) inside the cards scales along with the card
    // itself — otherwise a shrunk card just clips its text, and a grown
    // one looks the same as default with extra empty padding.
    document.documentElement.style.setProperty('--cs-card-text-scale', String(step.size / base.size));
    document.documentElement.style.setProperty('--cs-card-hero-text-scale', String(step.heroSize / base.heroSize));
    var zoomInBtn  = document.getElementById('cs-card-zoom-in');
    var zoomOutBtn = document.getElementById('cs-card-zoom-out');
    if (zoomInBtn)  zoomInBtn.disabled  = (i >= CS_CARD_ZOOM_STEPS.length - 1);
    if (zoomOutBtn) zoomOutBtn.disabled = (i <= 0);
  }

  csApplyCardZoom(csGetCardZoomStep());

  var cardZoomInBtn    = document.getElementById('cs-card-zoom-in');
  var cardZoomOutBtn   = document.getElementById('cs-card-zoom-out');
  var cardZoomResetBtn = document.getElementById('cs-card-zoom-reset');
  // dataset guard: belt-and-braces against this exact element somehow
  // getting a second listener bound (e.g. if this IIFE ever runs twice
  // despite the __nomadStudioLoaded guard above) — matches the "works
  // once, then needs two clicks every time after" symptom you'd get from
  // two listeners both firing on click but reading/writing localStorage
  // out of sync with each other.
  if (cardZoomInBtn && !cardZoomInBtn.dataset.zoomBound) {
    cardZoomInBtn.dataset.zoomBound = '1';
    cardZoomInBtn.addEventListener('click', function () {
      var i = Math.min(csGetCardZoomStep() + 1, CS_CARD_ZOOM_STEPS.length - 1);
      localStorage.setItem(CS_CARD_ZOOM_KEY, String(i));
      csApplyCardZoom(i);
    });
  }
  if (cardZoomOutBtn && !cardZoomOutBtn.dataset.zoomBound) {
    cardZoomOutBtn.dataset.zoomBound = '1';
    cardZoomOutBtn.addEventListener('click', function () {
      var i = Math.max(csGetCardZoomStep() - 1, 0);
      localStorage.setItem(CS_CARD_ZOOM_KEY, String(i));
      csApplyCardZoom(i);
    });
  }
  if (cardZoomResetBtn && !cardZoomResetBtn.dataset.zoomBound) {
    cardZoomResetBtn.dataset.zoomBound = '1';
    cardZoomResetBtn.addEventListener('click', function () {
      localStorage.setItem(CS_CARD_ZOOM_KEY, String(CS_CARD_ZOOM_DEFAULT));
      csApplyCardZoom(CS_CARD_ZOOM_DEFAULT);
    });
  }

  /* ── Filter sidebar show/hide ─────────────────────────────────────────── */
  // The state lives as a class on <html>, not on the sidebar's `hidden`
  // attribute: renderChips owns that attribute (it hides the bar when a view
  // produced no tags), so writing to it from here would leave the two
  // overwriting each other. Persisted like the card zoom, since a collapsed
  // sidebar is a workspace preference rather than a per-visit action.
  var CS_FILTERS_KEY = 'ns-filters-hidden';
  var filterToggleBtn = document.getElementById('cs-filter-toggle-btn');

  // The toggle is position:fixed at one height (.cs-filter-toggle `top`),
  // but each view's sidebar starts at its own height — Refine and Mix sat
  // ~14px higher than Create, so the button covered their FILTERS label.
  // Centre it on the visible sidebar's label instead, whatever is above it.
  // The first time a view shows, the button stays invisible until it has
  // been placed (measured on the next frame) — placing it after a visible
  // start made it jump on every load. Each view's spot is remembered, so
  // later visits land there at once; a second measure after the view-switch
  // animation (~450 ms) corrects any in-flight offset. While the sidebar is
  // collapsed the label has no box, so the button keeps its last spot and
  // never moves out from under the cursor.
  var _csAlignTimer = null;
  var _csToggleTops = {};
  function csAlignFilterToggle(sidebar) {
    if (!filterToggleWrap || !sidebar) return;
    var key = sidebar.id || 'default';
    if (_csToggleTops[key] != null) filterToggleWrap.style.top = _csToggleTops[key] + 'px';
    else filterToggleWrap.style.visibility = 'hidden';
    function measure() {
      var label = sidebar.querySelector('.group-label');
      if (!label || filterToggleWrap.hidden) return;
      var r = label.getBoundingClientRect();
      if (r.height) {
        var h = filterToggleWrap.offsetHeight || 34;
        _csToggleTops[key] = Math.round(r.top + r.height / 2 - h / 2);
        filterToggleWrap.style.top = _csToggleTops[key] + 'px';
      }
      filterToggleWrap.style.visibility = '';
    }
    // Remembered spot: confirm on the next frame. First visit: wait out the
    // view-switch animation before measuring, so the one placement is final.
    if (_csToggleTops[key] != null) requestAnimationFrame(function () { requestAnimationFrame(measure); });
    clearTimeout(_csAlignTimer);
    _csAlignTimer = setTimeout(measure, 450);
  }
  window.addEventListener('resize', function () {
    var sb = document.querySelector('.cs-view:not([aria-hidden="true"]) .cs-tag-filter--sidebar:not([hidden])');
    if (sb) csAlignFilterToggle(sb);
  });

  function csApplyFiltersHidden(hidden) {
    document.documentElement.classList.toggle('cs-filters-hidden', hidden);
    if (!filterToggleBtn) return;
    var label = hidden ? 'Show filters' : 'Hide filters';
    filterToggleBtn.setAttribute('aria-pressed', String(hidden));
    filterToggleBtn.setAttribute('aria-label', label);
    var tip = filterToggleBtn.querySelector('[data-cs-filter-tip]');
    if (tip) tip.textContent = label;
  }

  csApplyFiltersHidden(localStorage.getItem(CS_FILTERS_KEY) === '1');

  if (filterToggleBtn && !filterToggleBtn.dataset.filterBound) {
    filterToggleBtn.dataset.filterBound = '1';
    filterToggleBtn.addEventListener('click', function () {
      var next = !document.documentElement.classList.contains('cs-filters-hidden');
      localStorage.setItem(CS_FILTERS_KEY, next ? '1' : '0');
      csApplyFiltersHidden(next);
    });
  }

  /* ── UI mode toggle (Guided / Custom) ─────────────────────────────────── */
  var NS_MODE_KEY = 'ns-ui-mode';

  function getMode() {
    return localStorage.getItem(NS_MODE_KEY) || 'basic';
  }

  function applyMode(mode) {
    var simpleBtn   = document.getElementById('cs-mode-simple');
    var basicBtn    = document.getElementById('cs-mode-basic');
    var advancedBtn = document.getElementById('cs-mode-advanced');
    if (simpleBtn)   simpleBtn.classList.toggle('is-active',   mode === 'simple');
    if (basicBtn)    basicBtn.classList.toggle('is-active',    mode === 'basic');
    if (advancedBtn) advancedBtn.classList.toggle('is-active', mode === 'advanced');
    document.body.setAttribute('data-ns-mode', mode);
  }

  function setMode(mode) {
    localStorage.setItem(NS_MODE_KEY, mode);
    applyMode(mode);
  }

  // Init on load
  applyMode(getMode());

  // ── URL-backed sub-views (/nomad-studio/create|refine|mix) ─────────────
  // Card clicks push a real history entry + title instead of just toggling
  // a hidden div, so the address bar reflects where you are and the
  // browser's Back button actually lands you back on the main hub.
  var CS_VIEW_ROUTES = {
    create:  { path: '/nomad-studio/create',  title: 'NomadStudio - Create',  el: viewCreate },
    refine:  { path: '/nomad-studio/refine',  title: 'NomadStudio - Refine',  el: viewRefine },
    mix:     { path: '/nomad-studio/mix',     title: 'NomadStudio - Mix',     el: viewMix },
    session: { path: '/nomad-studio/session', title: 'NomadStudio - Session', el: viewSession },
  };
  var CS_MAIN_TITLE = 'NomadStudio';
  var _csCurrentView = null; // null = main hub

  // Jumping straight to a view (popstate / direct load) can interrupt a
  // transitionTo() animation mid-flight — e.g. Back pressed while Create was
  // still sliding in. Clearing these classes on every view avoids a stuck
  // .cs-view--entering/exiting from freezing the element at whatever
  // half-finished transform the interrupted keyframe left it at.
  function csClearViewAnimClasses() {
    [viewMain, viewCreate, viewRefine, viewMix, viewSession].forEach(function (el) {
      if (el) el.classList.remove('cs-view--entering', 'cs-view--exiting');
    });
  }

  function csShowViewInstant(key) {
    csClearViewAnimClasses();
    var route = key ? CS_VIEW_ROUTES[key] : null;
    var target = (route && route.el) || viewMain;
    Object.keys(CS_VIEW_ROUTES).forEach(function (k) {
      var el = CS_VIEW_ROUTES[k].el;
      if (el && el !== target) { el.style.display = 'none'; el.setAttribute('aria-hidden', 'true'); }
    });
    if (viewMain && viewMain !== target) { viewMain.style.display = 'none'; viewMain.setAttribute('aria-hidden', 'true'); }
    if (target) { target.style.display = 'flex'; target.removeAttribute('aria-hidden'); }
    _csCurrentView = key || null;
    csSyncThemeBtn();
  }

  // Direct load of /nomad-studio/create etc. — open straight into that view.
  var _rootEl = document.querySelector('.cs-layout');
  var _initialView = _rootEl ? _rootEl.getAttribute('data-ns-initial-view') : '';
  if (_initialView && CS_VIEW_ROUTES[_initialView]) {
    csShowViewInstant(_initialView);
    if (_initialView === 'create') renderWorkflowStrip();
    // Session init is handled by init() at the bottom of this file, which
    // already checks viewSession's display state — avoids double-firing it.
  }
  csSyncThemeBtn();

  window.addEventListener('popstate', function () {
    var path = window.location.pathname;
    var key = Object.keys(CS_VIEW_ROUTES).filter(function (k) { return CS_VIEW_ROUTES[k].path === path; })[0] || null;
    csShowViewInstant(key);
    document.title = key ? CS_VIEW_ROUTES[key].title : CS_MAIN_TITLE;
    if (key === 'create') renderWorkflowStrip();
    if (key === 'session') sessionInit();
  });

  // If arriving via Back from a Create sub-page, jump straight to Create view
  if (window.location.hash === '#create' && viewMain && viewCreate) {
    viewMain.style.display = 'none';
    viewMain.setAttribute('aria-hidden', 'true');
    viewCreate.style.display = 'flex';
    viewCreate.removeAttribute('aria-hidden');
    history.replaceState(null, '', window.location.pathname);
    renderWorkflowStrip();
  }

  // If arriving via Back from a Refine sub-page, jump straight to Refine view
  if (window.location.hash === '#refine' && viewMain && viewRefine) {
    viewMain.style.display = 'none';
    viewMain.setAttribute('aria-hidden', 'true');
    viewRefine.style.display = 'flex';
    viewRefine.removeAttribute('aria-hidden');
    history.replaceState(null, '', window.location.pathname);
  }

  var modeToggleBtns = document.querySelectorAll('[data-mode]');
  modeToggleBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      setMode(btn.dataset.mode);
      renderWorkflowStrip();
    });
  });

  /* ── Global workflow selector ──────────────────────────────────────────── */
  var GLOBAL_WORKFLOWS_KEY = 'ns-global-workflows';
  function getGlobalWorkflows() { try { return JSON.parse(localStorage.getItem(GLOBAL_WORKFLOWS_KEY) || '[]'); } catch(_){ return []; } }
  function setGlobalWorkflows(ids) { try { localStorage.setItem(GLOBAL_WORKFLOWS_KEY, JSON.stringify(ids)); } catch(_){} }

  var _csWfStrip    = document.getElementById('cs-workflow-strip');
  var _csWfChips    = document.getElementById('cs-workflow-chips');
  var _csWfEditBtn  = document.getElementById('cs-workflow-edit-btn');
  var _csWfModal    = document.getElementById('cs-workflow-modal');
  var _csWfMClose   = document.getElementById('cs-workflow-modal-close');
  var _csWfMApply   = document.getElementById('cs-workflow-modal-apply');
  var _csWfMList    = document.getElementById('cs-workflow-modal-list');
  var _csAllImports = [];

  function escHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function(c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  async function loadImportsList() {
    if (_csAllImports.length) return _csAllImports;
    try {
      var res = await fetch('/api/models/imports');
      var data = await res.json();
      _csAllImports = (Array.isArray(data.imports) ? data.imports : []).filter(function(imp) {
        var detected = (imp.analysis || {}).detected || {};
        return imp.saveImageCount > 0 && !detected.hasImageInput;
      });
      // Auto-init global selection from server activeImportIds if nothing saved
      if (!getGlobalWorkflows().length) {
        var serverIds = Array.isArray(data.activeImportIds) ? data.activeImportIds : [];
        if (serverIds.length) setGlobalWorkflows(serverIds);
        else if (_csAllImports.length) setGlobalWorkflows([String(_csAllImports[0].id)]);
      }
    } catch (_) {}
    return _csAllImports;
  }

  function renderWorkflowStrip() {
    var isCustom = getMode() === 'advanced';
    if (!_csWfStrip) return;
    _csWfStrip.hidden = !isCustom;
    if (!isCustom || !_csWfChips) return;
    var ids = getGlobalWorkflows();
    // Drop stale IDs that no longer exist in valid imports
    var validIds = ids.filter(function (id) {
      return _csAllImports.some(function (r) { return String(r.id) === id; });
    });
    if (validIds.length !== ids.length) setGlobalWorkflows(validIds);
    _csWfChips.innerHTML = '';
    if (!validIds.length) {
      _csWfChips.innerHTML = '<span class="cs-workflow-chip cs-workflow-chip--empty">' + tH('None selected') + '</span>';
    } else {
      validIds.forEach(function (id) {
        var rec = _csAllImports.find(function (r) { return String(r.id) === id; });
        var chip = document.createElement('span');
        chip.className = 'cs-workflow-chip';
        chip.textContent = rec.name || id;
        _csWfChips.appendChild(chip);
      });
    }
    // Load imports in background if not loaded yet
    if (!_csAllImports.length) {
      loadImportsList().then(renderWorkflowStrip);
    }
  }

  function openCsWorkflowModal() {
    if (!_csWfModal || !_csWfMList) return;
    _csWfMList.innerHTML = '';
    if (!_csAllImports.length) {
      _csWfMList.innerHTML = '<p class="nse-model-empty">' + tH('Loading…') + '</p>';
      loadImportsList().then(function () { openCsWorkflowModal(); });
      return;
    }
    _csAllImports.forEach(function (imp) {
      var id = String(imp.id);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'nse-model-item' + (getGlobalWorkflows().indexOf(id) >= 0 ? ' is-active' : '');
      btn.setAttribute('role', 'option');
      btn.setAttribute('aria-selected', String(getGlobalWorkflows().indexOf(id) >= 0));
      btn.dataset.csWfId = id;
      btn.id = 'cs-wf-modal-item-' + id;
      btn.innerHTML = '<span class="nse-model-name">' + escHtml(imp.name || id) + '</span>' +
        '<svg class="nse-model-check" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8l4 4 6-7"/></svg>';
      btn.addEventListener('click', function () {
        var ids = getGlobalWorkflows();
        var idx = ids.indexOf(id);
        if (idx >= 0) {
          if (ids.length <= 1) return; // always keep at least one model selected
          ids.splice(idx, 1);
        } else {
          ids.push(id);
        }
        setGlobalWorkflows(ids);
        var active = ids.indexOf(id) >= 0;
        btn.classList.toggle('is-active', active);
        btn.setAttribute('aria-selected', String(active));
        renderWorkflowStrip();
      });
      _csWfMList.appendChild(btn);
    });
    _csWfModal.removeAttribute('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeCsWorkflowModal() {
    if (_csWfModal) _csWfModal.setAttribute('hidden', '');
    document.body.style.overflow = '';
  }

  if (_csWfEditBtn) _csWfEditBtn.addEventListener('click', openCsWorkflowModal);
  if (_csWfMClose)  _csWfMClose.addEventListener('click',  closeCsWorkflowModal);
  if (_csWfModal)   _csWfModal.addEventListener('click',   function (e) { if (e.target === _csWfModal) closeCsWorkflowModal(); });

  // Init strip on load
  loadImportsList().then(renderWorkflowStrip);

  /* ── Spotlight: track mouse per card ──────────────────────────────────── */
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

  document.querySelectorAll('.cs-card').forEach(attachSpotlight);

  /* ── Transition helper ─────────────────────────────────────────────────── */
  function transitionTo(from, to) {
    // Defensive: a rapid click / Back-nav mid-animation can leave a stale
    // entering/exiting class on either element from a previous, interrupted
    // call — clear both before starting a fresh cycle.
    if (typeof csClearViewAnimClasses === 'function') csClearViewAnimClasses();
    from.classList.add('cs-view--exiting');

    from.addEventListener('animationend', function handler() {
      from.removeEventListener('animationend', handler);
      from.classList.remove('cs-view--exiting');
      from.style.display = 'none';
      from.setAttribute('aria-hidden', 'true');

      /* Mostrar destino ANTES de añadir la clase de animación */
      to.style.display = 'flex';
      to.removeAttribute('aria-hidden');
      if (typeof csSyncThemeBtn === 'function') csSyncThemeBtn();

      /* Forzar reflow para que el browser registre el display antes de animar */
      void to.offsetHeight;

      to.classList.add('cs-view--entering');

      to.addEventListener('animationend', function doneHandler() {
        to.removeEventListener('animationend', doneHandler);
        to.classList.remove('cs-view--entering');
        /* display: flex ya está en inline style — el elemento sigue visible */
      });
    });
  }

  /* ── Category card clicks ──────────────────────────────────────────────── */
  document.querySelectorAll('[data-cs-category]').forEach(function (card) {
    card.addEventListener('click', function (e) {
      e.preventDefault();
      var category = card.dataset.csCategory;

      if (CS_VIEW_ROUTES[category]) {
        var route = CS_VIEW_ROUTES[category];
        transitionTo(viewMain, route.el);
        history.pushState({ csView: category }, '', route.path);
        document.title = route.title;
        _csCurrentView = category;
        if (category === 'create') renderWorkflowStrip();
        if (category === 'session') sessionInit();
        return;
      }

      if (category === 'build') {
        window.location.href = '/build';
        return;
      }

      if (category === 'album') {
        window.location.href = '/album';
        return;
      }

      console.log('[Nomad Studio] Category:', category, '— not yet implemented');
    });
  });

  /* ── Back buttons ──────────────────────────────────────────────────────── */
  function csBackToMain(fromEl) {
    transitionTo(fromEl, viewMain);
    history.pushState({ csView: null }, '', '/nomad-studio');
    document.title = CS_MAIN_TITLE;
    _csCurrentView = null;
  }

  if (backBtn) {
    backBtn.addEventListener('click', function () { csBackToMain(viewCreate); });
  }

  if (refineBackBtn) {
    refineBackBtn.addEventListener('click', function () { csBackToMain(viewRefine); });
  }

  if (mixBackBtn) {
    mixBackBtn.addEventListener('click', function () { csBackToMain(viewMix); });
  }

  if (sessionBackBtn) {
    sessionBackBtn.addEventListener('click', function () { csBackToMain(viewSession); });
  }

  /* ── Session ─────────────────────────────────────────────────────────────── */
  // Storage is delegated to the shared window.NomadSession helper so the create
  // pages and this hub stay in sync. A thin local fallback keeps things working
  // even if the shared script failed to load.
  var Session = window.NomadSession || (function () {
    var KEY = 'ns-sessions';
    function load() { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (_) { return []; } }
    function save(b) { try { localStorage.setItem(KEY, JSON.stringify(b)); } catch (_) {} }
    return {
      load: load, save: save,
      find: function (id) { return load().find(function (b) { return b.id === id; }) || null; },
      upsert: function (session) { var b = load(); var i = b.findIndex(function (x) { return x.id === session.id; }); if (i === -1) b.push(session); else b[i] = session; save(b); },
      create: function (name) { var session = { id: 'session-' + Date.now(), name: name || 'Untitled Session', folder: 'session-' + Math.floor(Date.now()/1000), createdAt: new Date().toISOString(), steps: [] }; this.upsert(session); return session; },
      subdirOf: function (b) { return 'session/' + ((b && b.folder) || 'session'); },
      getActive: function () { try { return localStorage.getItem('ns-session-active') || ''; } catch (_) { return ''; } },
      setActive: function (id) { try { localStorage.setItem('ns-session-active', id || ''); } catch (_) {} },
      setPending: function () {}, clearPending: function () {},
      wantsReturn: function () { return false; }, setReturn: function () {}
    };
  })();

  function sessionLoadSessions() { return Session.load(); }
  function sessionSaveSessions(sessions) { Session.save(sessions); }

  // localStorage is only a cache — data/sessions.json on the server is the
  // source of truth, and syncFromServer() overwrites the local copy of a
  // session wholesale with the server's. So any edit saved ONLY locally is
  // undone the next time the list syncs: that's why a deleted step came back
  // when you returned to the session (and why a rename didn't stick either).
  // Every mutation has to reach the server; this debounces the chatty ones
  // (typing a name, clicking through steps) into one PUT.
  var _sessionPushTimer = null;
  function sessionPushSoon(session) {
    if (!session || !Session.pushUpdate) return;
    clearTimeout(_sessionPushTimer);
    _sessionPushTimer = setTimeout(function () { Session.pushUpdate(session); }, 400);
  }

  var sessionCurrentSession = null;   // session currently open in the workspace

  // ── Standalone workspace page (/nomad-studio/session/<id>) ─────────────
  // This page has no entry grid at all — it's server-rendered with just the
  // session id (data-cs-session-id), and its job on load is simply "open
  // that session's workspace". Every other element this file looks for on
  // the hub/entry pages (#cs-view-main, #cs-session-entry, etc.) is just
  // absent here, which every reference above already null-guards against.
  var _csStandaloneSessionEl = document.getElementById('cs-session-workspace-page');
  var _csStandaloneSessionId = _csStandaloneSessionEl && _csStandaloneSessionEl.getAttribute('data-cs-session-id');
  if (_csStandaloneSessionId) {
    if (Session.clearPending) Session.clearPending();
    if (Session.setReturn) Session.setReturn(false);
    var _csOpenStandalone = function () {
      var s = Session.find(_csStandaloneSessionId);
      if (s) { sessionRenderWorkspace(s); _csConsumeAutolaunch(s); return; }
      // Not in the local cache (e.g. fresh browser) — the server sync below
      // will retry; if it truly doesn't exist anywhere, bounce to the list.
      window.location.href = '/nomad-studio/session';
    };
    if (Session.syncFromServer) {
      Session.syncFromServer().then(_csOpenStandalone).catch(_csOpenStandalone);
    } else {
      _csOpenStandalone();
    }
  }

  // One-shot instruction handed off by a flow page that isn't itself a
  // Session's native container (a plain Create/Refine/Mix page — see
  // flow-gallery.js's "Create Session" toggle / _sendResultsToRefineWithSession):
  // "open this freshly-created session, then immediately mount this flow in
  // it" — the exact same two calls the "Add Flow" modal's own click handler
  // makes (Session.setPending + sessionMountFlow, further below), just
  // triggered on load here instead of from a click, since that other tab had
  // no native container to mount into itself.
  function _csConsumeAutolaunch(session) {
    var raw;
    try { raw = sessionStorage.getItem('ns-session-autolaunch-v1'); } catch (_) { raw = null; }
    if (!raw) return;
    try { sessionStorage.removeItem('ns-session-autolaunch-v1'); } catch (_) {}
    var launch;
    try { launch = JSON.parse(raw); } catch (_) { return; }
    if (!launch || launch.sessionId !== session.id || !launch.action) return;

    var category = launch.category || 'refine';
    var slug = String(launch.action).replace(/_/g, '-');
    var flowUrl = '/nomad-studio/' + category + '/' + slug;

    function doMount() {
      if (Session.setPending) {
        Session.setPending({
          sessionId: session.id,
          flowLabel: launch.label || launch.action,
          flowCategory: category,
          flowAction: launch.action,
          parentId: launch.parentId || null,
          subdir: Session.subdirOf ? Session.subdirOf(session) : null,
          ts: Date.now(),
        });
      }
      sessionMountFlow(flowUrl, launch.label || launch.action);
    }

    // sessionMountFlow needs window.FlowEngine, set by flow-boot.js — one of
    // the LAST <script> tags on this page, well after this one. That's not
    // the same server round-trip _sendResultsToRefineWithSession already
    // awaits (addStepRemote, the step actually reaching the server) — this
    // gap is entirely client-side: whether every <script> tag in the initial
    // HTML has finished running yet. Session.syncFromServer's GET resolving
    // normally gives them all time to (script execution is near-instant,
    // network isn't) — but on a fast localhost response it can win that
    // race, and sessionMountFlow's own fallback for "not ready" is a raw
    // navigation to the flow's standalone page — exactly the bug this
    // handoff exists to avoid. document.readyState/DOMContentLoaded is the
    // deterministic signal for "every synchronous script tag from the
    // initial HTML has run" (that's what flow-boot.js is), so await that
    // instead of guessing with a timer.
    (document.readyState === 'loading'
      ? new Promise(function (resolve) { document.addEventListener('DOMContentLoaded', resolve, { once: true }); })
      : Promise.resolve()
    ).then(doMount);
  }

  // ── Hub load ends any session flow still pending in this tab ───────────
  // The pending context is tab-scoped (sessionStorage) and is only cleared
  // when the user comes *back* to a session view — so a tab that opened a
  // session flow and then wandered off somewhere else kept the flag for the
  // rest of its life. Launching Create ▸ Simple from the hub afterwards
  // inherited it, and flow-boot's sessionContextChrome rendered the old
  // session's name in the breadcrumb plus a "Back to session" button on a
  // flow that was never attached to any session.
  //
  // Reaching the hub means this tab is not inside a session any more: every
  // in-session flow is mounted inside the workspace document (sessionMountFlow)
  // and never navigates here. Same clear the standalone workspace page does
  // for itself above. Only `pending` is touched — the RETURN flag lives in
  // localStorage and is shared with other tabs that may still be mid-session.
  if (document.getElementById('cs-view-main') && !_csStandaloneSessionId) {
    if (Session.clearPending) Session.clearPending();
  }

  function sessionInit() {
    // Back in the session view: end any open capture session so later, unrelated
    // generations don't get appended to a session. (Images from the flow we just
    // left were captured live while pending was active.)
    if (Session.clearPending) Session.clearPending();
    // "Return from Add Flow" now lands straight on the workspace's own page
    // (/nomad-studio/session/<id> — see flow-boot.js returnToSession), so
    // this entry-list page never needs to special-case wantsReturn anymore.
    Session.setReturn(false);

    // Show the entry state with recent sessions.
    var entry     = document.getElementById('cs-session-entry');
    var workspace = document.getElementById('cs-session-workspace');
    if (entry)     entry.hidden = false;
    if (workspace) workspace.hidden = true;

    // Pull the current viewer's sessions from the server (own + shared with
    // everyone) so switching browsers/devices shows the same list. Render
    // the local cache immediately, then refresh once the sync resolves.
    if (Session.syncFromServer) {
      Session.syncFromServer().then(function () { sessionRenderRecent(); });
    }
    sessionRenderRecent();
  }

  // Most recent output image across a session's steps — walked back-to-front
  // so a session's poster always shows its latest result, not its first.
  function sessionThumb(b) {
    var steps = Array.isArray(b.steps) ? b.steps : [];
    for (var i = steps.length - 1; i >= 0; i--) {
      var step = steps[i];
      var url = step && (step.imageUrl || (Array.isArray(step.images) && step.images[0]));
      if (url) return url;
    }
    return '';
  }

  function sessionRenderRecent() {
    var sessions = sessionLoadSessions();
    var recentEl = document.getElementById('cs-session-recent');
    var recentList = document.getElementById('cs-session-recent-list');
    if (recentEl && recentList) {
      if (sessions.length > 0) {
        recentList.innerHTML = '';
        // Every session, newest first — same as the Album shows every image.
        // This used to cut the list at six with nothing on screen saying so,
        // which made a delete look like it had hit the wrong one: removing a
        // session simply let an older, previously hidden one into view. The
        // grid (.rp-grid, auto-fill 260px) already flows onto more rows, so
        // there was never a layout reason for the cap.
        sessions.slice().reverse().forEach(function (b) {
          var count = b.steps ? b.steps.length : 0;
          var thumb = sessionThumb(b);

          // Same poster-card structure as Refine ▸ Presets / Album
          // (.rp-card + .rp-card-media + .rp-card-body) — the image is the
          // card, name/count sit in a scrim at the bottom.
          var card = document.createElement('div');
          card.className = 'rp-card cs-session-recent-card';
          card.setAttribute('role', 'button');
          card.setAttribute('tabindex', '0');
          card.setAttribute('aria-label', tF('Open {name}').replace('{name}', b.name || tF('Untitled Session')));

          var media = document.createElement('div');
          media.className = 'rp-card-media';
          if (thumb) {
            media.innerHTML = '<img src="' + thumb + '" alt="" loading="lazy">';
          } else {
            media.classList.add('cs-session-recent-media--empty');
            media.innerHTML =
              '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/></svg>';
          }

          var body = document.createElement('div');
          body.className = 'rp-card-body';
          body.innerHTML =
            '<p class="rp-card-name">' + escHtml(b.name || 'Untitled Session') + '</p>' +
            '<p class="rp-card-desc">' + count + (count === 1 ? ' image' : ' images') + '</p>';

          var del = document.createElement('button');
          del.type = 'button';
          del.className = 'cs-session-recent-del';
          del.title = tF('Delete session');
          del.setAttribute('aria-label', tF('Delete session'));
          del.innerHTML =
            '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
              '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>' +
              '<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>';
          del.addEventListener('click', function (e) {
            e.stopPropagation();
            if (!window.confirm(tF('Delete "{name}"? This removes the session and its history. This cannot be undone.').replace('{name}', b.name || tF('this session')))) return;
            // Drop the card now (the local list is already updated) and only
            // re-sync once the server has confirmed the delete.
            card.remove();
            sessionDeleteSession(b.id).then(function () { sessionInit(); });
          });

          card.appendChild(media);
          card.appendChild(body);
          card.appendChild(del);

          card.addEventListener('click', function () { sessionOpenSession(b.id); });
          card.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sessionOpenSession(b.id); }
          });
          if (typeof attachSpotlight === 'function') attachSpotlight(card);

          recentList.appendChild(card);
        });
        recentEl.hidden = false;
      } else {
        recentEl.hidden = true;
      }
    }
  }

  function sessionCreateSession(name) {
    return Session.create(name);
  }

  function sessionOpenSession(sessionId) {
    // The workspace is its own page now (/nomad-studio/session/<id>), not an
    // inline view inside this hub — navigate instead of rendering in place.
    window.location.href = '/nomad-studio/session/' + encodeURIComponent(sessionId);
  }

  function sessionMeta(session) {
    var count = session.steps ? session.steps.length : 0;
    var created = session.createdAt
      ? new Date(session.createdAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
      : '';
    var parts = [];
    if (count === 0) parts.push('No images yet');
    else parts.push(count + (count === 1 ? ' image' : ' images'));
    if (created) parts.push('Created ' + created);
    return parts.join(' · ');
  }

  function sessionRenderWorkspace(session) {
    var entry      = document.getElementById('cs-session-entry');
    var workspace  = document.getElementById('cs-session-workspace');
    var nameInput  = document.getElementById('cs-session-name-input');
    var breadcrumb = document.getElementById('cs-session-breadcrumb');
    var metaEl     = document.getElementById('cs-session-meta');

    sessionCurrentSession = session;
    Session.setActive(session.id);

    if (entry)     entry.hidden = true;
    if (workspace) workspace.hidden = false;
    if (nameInput) nameInput.value = session.name || '';
    // The workspace is its own page now (Nomad Studio › Session › <name>),
    // same pattern as Create's flow pages (Nomad Studio › Create › Simple)
    // — the last crumb is the specific thing you're in, not the category
    // again, so it tracks the name input live instead of a fixed label.
    if (breadcrumb) breadcrumb.textContent = session.name || 'Untitled Session';
    if (metaEl)    metaEl.textContent = sessionMeta(session);

    // save name on edit
    if (nameInput) {
      nameInput.oninput = function () {
        session.name = nameInput.value.trim() || 'Untitled';
        if (breadcrumb) breadcrumb.textContent = session.name;
        var sessions = sessionLoadSessions();
        var idx = sessions.findIndex(function (b) { return b.id === session.id; });
        if (idx !== -1) { sessions[idx] = session; sessionSaveSessions(sessions); }
        sessionPushSoon(session);
      };
    }

    sessionRenderTree(session);
    sessionWireWorkspaceActions(session);
  }

  function sessionRenderTree(session) {
    var tree = document.getElementById('cs-session-tree');
    if (!tree) return;
    tree.innerHTML = '';

    // No trailing "+ add flow" node here — the always-visible Add Flow
    // button above the tree does exactly the same thing (opens the same
    // flow-picker modal), so a second one at the bottom was pure duplicate
    // UI (see appendAddNode's removal).
    if (!session.steps || session.steps.length === 0) {
      var empty = document.createElement('p');
      empty.className = 'cs-session-tree-empty';
      empty.textContent = tF('No images yet — start by adding a flow.');
      tree.appendChild(empty);
      return;
    }

    session.steps.forEach(function (step, stepIdx) {
      var isSelected = !!step.selected;
      var isChild    = !!step.parentId;

      // Imported steps and generated ones show their imagery differently:
      // an import IS the picture (big backdrop, no thumbnail strip), while a
      // flow's card is about its outputs (thumbnail strip, no backdrop) — one
      // modifier class, both halves handled in CSS. See .cs-session-node--import.
      var isImport = step.flowCategory === 'import';

      // Started on Generate/Queue and still running (session-store.js
      // beginStep) — shown with a spinner until settleStep clears it.
      var isGenerating = !!step.generating;

      var node = document.createElement('div');
      node.className = 'cs-session-node' + (isSelected ? ' is-selected' : '') + (isChild ? ' cs-session-node--child' : '') + (isImport ? ' cs-session-node--import' : '') + (isGenerating ? ' is-generating' : '');
      node.dataset.stepId = step.id;
      node.setAttribute('role', 'treeitem');
      node.setAttribute('aria-selected', isSelected ? 'true' : 'false');
      node.setAttribute('tabindex', '0');

      var imgs = Array.isArray(step.images) && step.images.length
        ? step.images
        : (step.imageUrl ? [step.imageUrl] : []);
      // Card background — the step's first image (see --cs-step-img in
      // nomad_studio.css), shown whole behind the gradient/tint. Imports
      // only: a flow's card leans on its thumbnail strip instead.
      if (isImport && imgs[0]) {
        node.style.setProperty('--cs-step-img', 'url("' + imgs[0].replace(/"/g, '\\"') + '")');
      }
      var outputsHtml = imgs.length > 1
        ? '<div class="cs-session-node-outputs">' +
            imgs.map(function (u) {
              return '<a class="cs-session-node-output" href="' + u + '" target="_blank" rel="noopener" title="' + tH('Open full image') + '">' +
                       '<img src="' + u + '" alt="' + escHtml(step.flowLabel || 'Output') + '" loading="lazy">' +
                     '</a>';
            }).join('') +
          '</div>'
        : '';

      var canOpen = step.flowCategory === 'create' || step.flowCategory === 'refine' || step.flowCategory === 'mix';
      var openBtnHtml = canOpen
        ? '<button type="button" class="cs-session-node-open" data-cs-open-flow="1" ' +
            'aria-label="' + tH('Open this flow') + '" title="' + tH('Open this flow') + '">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8"/></svg>' +
            '<span>' + tH('Open') + '</span>' +
          '</button>'
        : '';

      var delBtnHtml =
        '<button type="button" class="cs-session-node-del" aria-label="' + tH('Delete this step') + '" title="' + tH('Delete this step') + '">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" ' +
          'stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>' +
            '<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>' +
        '</button>';

      // No thumbnail on an import — the backdrop above already shows that
      // exact image, so the small copy was the same picture twice.
      var thumbHtml = isImport
        ? ''
        : '<div class="cs-session-node-thumb">' +
            (step.imageUrl
              ? '<img src="' + step.imageUrl + '" alt="' + escHtml(step.flowLabel || 'Step') + '">'
              : isGenerating
                ? '<div class="cs-session-node-thumb-empty"><span class="cs-session-node-spinner" aria-hidden="true"></span></div>'
                : '<div class="cs-session-node-thumb-empty"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg></div>') +
          '</div>';

      node.innerHTML =
        '<div class="cs-session-node-media">' +
          thumbHtml +
          outputsHtml +
        '</div>' +
        '<div class="cs-session-node-body">' +
          // Step number on the same line as the flow name (and set larger,
          // see .cs-session-node-index) instead of stacked above it — it
          // reads as "step 2 · Flux 2 Klein Edit" and buys back a line of
          // card height for every card in the list.
          '<div class="cs-session-node-top">' +
            '<span class="cs-session-node-index">' + (stepIdx + 1) + '</span>' +
            '<span class="cs-session-node-name">' + escHtml(step.flowLabel || 'Step') + '</span>' +
            (isGenerating
              ? '<span class="cs-session-node-badge cs-session-node-badge--generating">' + tH('Generating…') + '</span>'
              : (isSelected ? '<span class="cs-session-node-badge">' + tH('Selected') + '</span>' : '')) +
          '</div>' +
        '</div>' +
        openBtnHtml +
        delBtnHtml;

      var openBtn = node.querySelector('.cs-session-node-open');
      if (openBtn) {
        openBtn.addEventListener('click', function (ev) {
          ev.stopPropagation();
          sessionReopenStep(session, step);
        });
      }
      var delBtn = node.querySelector('.cs-session-node-del');
      if (delBtn) {
        delBtn.addEventListener('click', function (ev) {
          ev.stopPropagation();
          if (!window.confirm(tF('Delete this step ("{name}")? This cannot be undone.').replace('{name}', step.flowLabel || tF('Step')))) return;
          sessionDeleteStep(session, step.id);
        });
      }
      // Let the output thumbnails open full-size without selecting the node.
      node.querySelectorAll('.cs-session-node-output').forEach(function (a) {
        a.addEventListener('click', function (ev) { ev.stopPropagation(); });
      });

      node.addEventListener('click', function () {
        tree.querySelectorAll('.cs-session-node').forEach(function (n) {
          n.classList.remove('is-selected');
          n.setAttribute('aria-selected', 'false');
          var badge = n.querySelector('.cs-session-node-badge');
          if (badge) badge.remove();
        });
        node.classList.add('is-selected');
        node.setAttribute('aria-selected', 'true');
        var body = node.querySelector('.cs-session-node-top');
        if (body && !node.querySelector('.cs-session-node-badge')) {
          var b = document.createElement('span');
          b.className = 'cs-session-node-badge';
          b.textContent = tF('Selected');
          body.appendChild(b);
        }
        session.steps.forEach(function (s) { s.selected = s.id === step.id; });
        var sessions = sessionLoadSessions();
        var i = sessions.findIndex(function (b) { return b.id === session.id; });
        if (i !== -1) { sessions[i] = session; sessionSaveSessions(sessions); }
        // `selected` lives inside steps[], so it's server state too — without
        // this the highlight snaps back to whatever the server still thinks.
        sessionPushSoon(session);
      });

      tree.appendChild(node);
    });
  }

  // Remove a single step from a session (re-parents orphans, keeps a valid
  // selection, persists, and re-renders the workspace).
  function sessionDeleteStep(session, stepId) {
    if (!session || !Array.isArray(session.steps)) return;
    var idx = session.steps.findIndex(function (s) { return s.id === stepId; });
    if (idx === -1) return;
    var removed = session.steps[idx];
    // Children that pointed at this step now point at its parent.
    session.steps.forEach(function (s) { if (s.parentId === stepId) s.parentId = removed.parentId || null; });
    session.steps.splice(idx, 1);
    // Keep a valid selection if we removed the selected step.
    if (removed.selected && session.steps.length) {
      session.steps.forEach(function (s) { s.selected = false; });
      session.steps[session.steps.length - 1].selected = true;
    }
    var sessions = sessionLoadSessions();
    var bi = sessions.findIndex(function (b) { return b.id === session.id; });
    if (bi !== -1) { sessions[bi] = session; sessionSaveSessions(sessions); }
    // Straight to the server, no debounce — a delete is the one edit where
    // losing the push means the step walks back in on the next sync.
    if (Session.pushUpdate) Session.pushUpdate(session);
    sessionRenderWorkspace(session);
  }

  // Build a "category::label" → action map from the flow picker cards, so steps
  // created before flowAction was persisted can still resolve their route.
  function sessionFlowActionLookup() {
    var map = {};
    var modal = document.getElementById('cs-session-flow-modal');
    if (modal) {
      modal.querySelectorAll('[data-cs-session-flow-action]').forEach(function (c) {
        var key = ((c.dataset.csSessionFlowCategory || '') + '::' + (c.dataset.csSessionFlowLabel || '')).toLowerCase();
        map[key] = c.dataset.csSessionFlowAction;
      });
    }
    return map;
  }

  /* ── In-page flow panel (Session workspace only) ─────────────────────────
     Opening a step, or picking a flow from Add Flow, doesn't navigate away
     from the session — it mounts the flow engine directly into this same
     document, next to the session column, so the name card and History
     stay on screen the whole time. (Used to load a second copy of the page
     inside an <iframe> — dropped in favor of a native mount: same origin,
     same app, no reason to pay for a whole separate document just to avoid
     wiring the engine to accept "which flow, which container" as
     parameters. See flow-boot.js FlowEngine.reset().) */
  var sessionFlowPanel      = document.getElementById('cs-session-flow-panel');
  var sessionFlowPanelClose = document.getElementById('cs-session-flow-panel-close');
  var sessionFlowNative     = document.getElementById('cs-session-flow-native');

  // Topbar controls that mirror the standalone flow page's own topbar —
  // hidden until a flow is mounted, revealed/hidden together with it. See
  // ns_session_workspace.html's topbar comment: same ids the flow engine
  // already looks up by plain document.getElementById(), so once a flow is
  // mounted it fills these in itself (flowBootLoad sets #nsc-flow-breadcrumb's
  // text, ns_image_tray.js/flow-history.js wire up Tray/mode-toggle) with no
  // extra glue needed here beyond showing/hiding the elements.
  var sessionFlowCrumb    = document.getElementById('nsc-flow-breadcrumb');
  var sessionFlowCrumbSep = document.getElementById('cs-session-flow-crumb-sep');
  var sessionFlowTrayBtn  = document.getElementById('nit-tray-btn');
  var sessionFlowModeToggle = document.getElementById('ncf-mode-toggle');
  var sessionSidebarToggle  = document.getElementById('cs-session-sidebar-toggle');
  var sessionSidebarShowBtn = document.getElementById('cs-session-sidebar-show-btn');
  var sessionInputsAside    = document.querySelector('.cs-session-inputs');

  function sessionSetFlowChromeVisible(visible) {
    [sessionFlowCrumb, sessionFlowCrumbSep, sessionFlowTrayBtn, sessionFlowModeToggle, sessionFlowPanelClose]
      // toggleAttribute, not .hidden: the crumb separator is an <svg>, which
      // has no .hidden property — setting it left the attribute in place.
      .forEach(function (el) { if (el) el.toggleAttribute('hidden', !visible); });
    // Collapse the session header (name/meta/icon/delete) down to just its
    // action row while a flow is open — see .cs-session-hdr--compact.
    var hdr = document.querySelector('.cs-session-hdr');
    if (hdr) hdr.classList.toggle('cs-session-hdr--compact', visible);
  }

  // Hides the WHOLE left column (Steps list + Add Flow/Add Images/Duplicate/
  // Export). Used to sit next to a second, narrower control that only
  // folded the step *list* (a chevron + count badge on "Steps" itself) —
  // removed as redundant once this one could do the same "give the open
  // flow more room" job for the whole column in one click. Unlike the
  // flow-mounted-only chrome above (Tray, mode-toggle, Close), this button
  // stays visible and usable whether or not a flow is open — it's a plain
  // viewing preference, not something tied to having somewhere else to send
  // the freed width — so its own state persists across page loads too.
  var CS_SIDEBAR_HIDDEN_KEY = 'ns-session-sidebar-hidden';
  function sessionSetSidebarHidden(hidden) {
    if (sessionInputsAside) sessionInputsAside.classList.toggle('is-hidden', hidden);
    if (sessionSidebarToggle) {
      sessionSidebarToggle.setAttribute('aria-expanded', hidden ? 'false' : 'true');
      sessionSidebarToggle.title = hidden ? 'Show session panel' : 'Hide session panel';
      sessionSidebarToggle.setAttribute('aria-label', hidden ? 'Show session panel' : 'Hide session panel');
    }
    // sessionSidebarToggle itself lives INSIDE the column it hides (next to
    // "Steps"), so it vanishes along with everything else the moment the
    // column is gone — no button left to undo it. This one lives outside
    // as a sibling specifically to stay reachable, appearing exactly when
    // the column doesn't — animated in (CSS class, not the `hidden`
    // attribute — see the CSS comment) so the motion itself teaches a
    // first-time user which button just appeared and why.
    if (sessionSidebarShowBtn) {
      sessionSidebarShowBtn.classList.toggle('is-visible', hidden);
      sessionSidebarShowBtn.setAttribute('aria-hidden', hidden ? 'false' : 'true');
    }
    try { localStorage.setItem(CS_SIDEBAR_HIDDEN_KEY, hidden ? '1' : '0'); } catch (_) {}
  }

  if (sessionSidebarToggle && sessionInputsAside) {
    var _sidebarHiddenSaved = false;
    try { _sidebarHiddenSaved = localStorage.getItem(CS_SIDEBAR_HIDDEN_KEY) === '1'; } catch (_) {}
    sessionSetSidebarHidden(_sidebarHiddenSaved);
    sessionSidebarToggle.addEventListener('click', function () {
      sessionSetSidebarHidden(!sessionInputsAside.classList.contains('is-hidden'));
    });
    if (sessionSidebarShowBtn) {
      sessionSidebarShowBtn.addEventListener('click', function () { sessionSetSidebarHidden(false); });
    }
  }

  function sessionMountFlow(flowUrlPath, title) {
    var m = /^\/nomad-studio\/(create|refine|mix)\/([a-z0-9-]+)$/.exec(String(flowUrlPath || ''));
    if (!m || !sessionFlowNative || !window.FlowEngine) {
      // No native container on this page, or URL doesn't look like a flow
      // page — fall back to a real navigation rather than doing nothing.
      window.location.href = flowUrlPath;
      return;
    }
    var flowId = m[1] + '.' + m[2].replace(/-/g, '_');
    // Set the breadcrumb text immediately from the known title, so there's
    // no flash of the *previous* flow's name while /api/flows/<id> is still
    // loading — flowBootLoad() overwrites it with flowDef.label once ready
    // (normally the same text; harmless either way).
    if (sessionFlowCrumb) sessionFlowCrumb.textContent = title || 'Flow';
    if (sessionFlowPanel) sessionFlowPanel.hidden = false;
    sessionFlowNative.hidden = false;
    sessionSetFlowChromeVisible(true);
    window.FlowEngine.reset(flowId, sessionFlowNative);
  }

  function sessionUnmountFlow() {
    if (window.FlowEngine) window.FlowEngine.cancelPending();
    if (sessionFlowNative) sessionFlowNative.hidden = true;
    if (sessionFlowPanel) sessionFlowPanel.hidden = true;
    sessionSetFlowChromeVisible(false);
    // Pull back whatever the flow added (new steps/images) into this page's
    // own view of the session.
    if (sessionCurrentSession) {
      var fresh = Session.find(sessionCurrentSession.id);
      if (fresh) sessionRenderWorkspace(fresh);
    }
  }

  if (sessionFlowPanelClose) sessionFlowPanelClose.addEventListener('click', sessionUnmountFlow);

  // Exposed for devtools testing (both functions are otherwise local to
  // this file's closure) — harmless to leave reachable, same spirit as
  // window.FlowEngine.
  window.__nomadSessionMountFlow = sessionMountFlow;
  window.__nomadSessionUnmountFlow = sessionUnmountFlow;

  // Lets the mounted flow's own "back to session" control (flow-boot.js /
  // session-store.js) close the panel via a direct same-window call —
  // same global contract those two already used for the iframe case
  // (there it was window.parent.__nomadCloseSessionFlowPanel; now
  // everything lives in one window, so it's just this).
  window.__nomadCloseSessionFlowPanel = sessionUnmountFlow;

  // Live-refresh History the instant a new step is captured — replaces the
  // old `storage`-event listener, which only ever worked because the flow
  // used to run in a separate <iframe> document (the native DOM `storage`
  // event deliberately never fires back on the same document that wrote
  // the key, only on *other* same-origin windows). Now that the flow lives
  // in this same document, session-store.js's captureImages() calls this
  // hook directly instead.
  window.__nomadOnSessionStepCaptured = function () {
    if (!sessionCurrentSession) return;
    var fresh = Session.find(sessionCurrentSession.id);
    if (!fresh) return;
    // Copied into the SAME object, not swapped for the fresh one: the name
    // input and the workspace actions keep a reference to it from
    // sessionRenderWorkspace, and a stale copy there would push its old step
    // list — dropping a step that just arrived (MCP, NomadStudio#24).
    Object.keys(fresh).forEach(function (k) { sessionCurrentSession[k] = fresh[k]; });
    sessionRenderTree(sessionCurrentSession);
  };

  // Back to this window (e.g. from the chat where an agent added a step
  // through the MCP): pick up steps added from outside meanwhile.
  function _sessionRefreshOnReturn() {
    if (document.visibilityState !== 'visible') return;
    if (sessionCurrentSession && Session.refreshSession) Session.refreshSession(sessionCurrentSession.id);
  }
  window.addEventListener('focus', _sessionRefreshOnReturn);
  document.addEventListener('visibilitychange', _sessionRefreshOnReturn);

  function sessionResolveSlug(step) {
    if (step.flowAction) return step.flowAction.replace(/_/g, '-');
    var map = sessionFlowActionLookup();
    var key = ((step.flowCategory || '') + '::' + (step.flowLabel || '')).toLowerCase();
    if (map[key]) return map[key].replace(/_/g, '-');
    return Session.slugify ? Session.slugify(step.flowLabel) : null;
  }

  // Re-enter the flow editor for a given step (uses the step's input image as base).
  function sessionReopenStep(session, step) {
    var category = step.flowCategory;
    if (category !== 'create' && category !== 'refine' && category !== 'mix') return;
    var slug = sessionResolveSlug(step);
    if (!slug) { alert(tF('Could not work out which flow made this step.')); return; }

    var parent = step.parentId
      ? (session.steps || []).find(function (s) { return s.id === step.parentId; })
      : null;
    // Every input the step was made from ({image picker step id: URL}, a Mix
    // step has several); older steps only know their parent's output.
    var inputs = (step.inputs && typeof step.inputs === 'object') ? step.inputs : {};
    var srcImg = inputs.image || (parent && parent.imageUrl) || step.imageUrl;
    var action = step.flowAction || slug.replace(/-/g, '_');
    var params = step.params || null;
    var promptText = params && (params.prompt || params.promptText || params.positive) || '';
    var outputs = Array.isArray(step.images) ? step.images.filter(Boolean) : (step.imageUrl ? [step.imageUrl] : []);

    if (Session.setPending) {
      Session.setPending({
        sessionId: session.id,
        flowLabel: step.flowLabel,
        flowCategory: category,
        flowAction: action,
        flowParams: params,
        parentId: step.parentId || null,
        stepId: step.id,   // keep working inside this entry — new outputs append here
        subdir: (Session.subdirOf ? Session.subdirOf(session) : null),
        ts: Date.now()
      });
    }

    // Hand the full session to the flow page so it restores the input image,
    // the entered prompt/params, and replays the previous outputs into the feed.
    try {
      sessionStorage.setItem('oj-load-session', JSON.stringify({
        type: category + '.' + action,
        prompt: promptText,
        data: {
          image1: srcImg,
          inputs: inputs,
          images: outputs,
          prompt: promptText,
          params: params
        }
      }));
    } catch (_) {}

    if (category === 'refine') {
      try { sessionStorage.setItem('oj-upscale-source-image-v1', srcImg); } catch (_) {}
      sessionMountFlow('/nomad-studio/refine/' + slug, step.flowLabel);
    } else if (category === 'mix') {
      sessionMountFlow('/nomad-studio/mix/' + slug, step.flowLabel);
    } else {
      sessionMountFlow('/nomad-studio/create/' + slug, step.flowLabel);
    }
  }

  /* ── Session flow picker modal ─────────────────────────────────────────── */
  var sessionFlowModal      = document.getElementById('cs-session-flow-modal');
  var sessionFlowModalClose = document.getElementById('cs-session-flow-modal-close');
  var sessionFlowImportImg  = document.getElementById('cs-session-flow-import-img');

  function sessionSelectedStep() {
    if (!sessionCurrentSession || !sessionCurrentSession.steps) return null;
    return sessionCurrentSession.steps.find(function (s) { return s.selected; }) ||
           sessionCurrentSession.steps[sessionCurrentSession.steps.length - 1] || null;
  }

  // The base image URL for a step (outputs may live in imageUrl or images[0]).
  function sessionStepImage(step) {
    if (!step) return '';
    return step.imageUrl || (Array.isArray(step.images) && step.images[0]) || '';
  }

  // Resolve the step to use as a refine base, robustly: the selected/last step,
  // falling back to the freshest stored copy and the last step that has an image.
  function sessionResolveBaseStep() {
    var step = sessionSelectedStep();
    if (sessionStepImage(step)) return step;
    var fresh = (sessionCurrentSession && Session.find) ? Session.find(sessionCurrentSession.id) : null;
    var steps = (fresh && fresh.steps) || (sessionCurrentSession && sessionCurrentSession.steps) || [];
    for (var i = steps.length - 1; i >= 0; i--) {
      if (sessionStepImage(steps[i])) return steps[i];
    }
    return null;
  }

  function sessionUpdateFlowBase() {
    var thumb = document.getElementById('cs-session-flow-base-thumb');
    var label = document.getElementById('cs-session-flow-base-label');
    if (!thumb || !label) return;
    var step = sessionSelectedStep();
    var hasBase = !!(step && step.imageUrl);
    if (hasBase) {
      thumb.innerHTML = '<img src="' + step.imageUrl + '" alt="">';
      label.textContent = tF('Base:') + ' ' + (step.flowLabel || tF('previous step'));
    } else {
      thumb.innerHTML = '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>';
      label.textContent = tF('New image');
    }
    // Show/hide Mix section depending on whether there is a base image
    var grid = document.getElementById('cs-session-flow-grid');
    if (grid) {
      var mixSection = grid.querySelector('[data-cs-session-flow-section="mix"]');
      if (mixSection) mixSection.hidden = !hasBase;
      grid.querySelectorAll('.cs-session-flow-card--mix').forEach(function (c) { c.hidden = !hasBase; });
    }
  }

  // Add Flow and Add Images are side panels docked beside the session column
  // (ns_session_workspace.html, .cs-session-side-panel) — one open at a time.
  function sessionOpenSidePanel(panel) {
    document.querySelectorAll('.cs-session-side-panel').forEach(function (p) {
      if (p !== panel) p.hidden = true;
    });
    if (panel) panel.hidden = false;
  }

  function sessionCloseSidePanels() {
    document.querySelectorAll('.cs-session-side-panel').forEach(function (p) { p.hidden = true; });
  }

  // Click outside an open side panel closes it — except on the buttons that
  // open them (.cs-session-side-trigger), which switch panels themselves.
  document.addEventListener('mousedown', function (e) {
    var open = document.querySelector('.cs-session-side-panel:not([hidden])');
    if (!open || open.contains(e.target)) return;
    if (e.target.closest && e.target.closest('.cs-session-side-trigger')) return;
    sessionCloseSidePanels();
  }, true);

  // Category of the tree beside the flow list: '' (All), create, refine, mix.
  var sessionFlowFilter = '';

  function sessionOpenFlowModal() {
    if (!sessionFlowModal) return;
    sessionUpdateFlowBase();
    var search = document.getElementById('cs-session-flow-search-input');
    if (search) { search.value = ''; sessionFilterFlows(''); }
    sessionOpenSidePanel(sessionFlowModal);
    if (search) requestAnimationFrame(function () { search.focus(); });
  }

  var sessionFlowTree = document.getElementById('cs-session-flow-tree');
  if (sessionFlowTree) {
    sessionFlowTree.addEventListener('click', function (e) {
      var item = e.target.closest('[data-cs-session-flow-filter]');
      if (!item) return;
      sessionFlowFilter = item.dataset.csSessionFlowFilter || '';
      sessionFlowTree.querySelectorAll('[data-cs-session-flow-filter]').forEach(function (b) {
        b.classList.toggle('is-active', b === item);
      });
      var search = document.getElementById('cs-session-flow-search-input');
      sessionFilterFlows(search ? search.value : '');
    });
  }

  function sessionFilterFlows(q) {
    q = (q || '').trim().toLowerCase();
    var grid = document.getElementById('cs-session-flow-grid');
    var empty = document.getElementById('cs-session-flow-empty');
    if (!grid) return;
    var step = sessionSelectedStep();
    var hasBase = !!(step && step.imageUrl);
    var shown = 0;
    grid.querySelectorAll('.cs-session-flow-card').forEach(function (card) {
      var isMix = card.classList.contains('cs-session-flow-card--mix');
      if (isMix && !hasBase) { card.hidden = true; return; }
      var inCategory = !sessionFlowFilter || card.dataset.csSessionFlowCategory === sessionFlowFilter;
      var hay = card.dataset.csSessionFlowSearch || '';
      var match = inCategory && (!q || hay.indexOf(q) !== -1);
      card.hidden = !match;
      if (match) shown++;
    });

    // Toggle section headers if they have matching cards
    grid.querySelectorAll('.cs-session-flow-section').forEach(function (sec) {
      var secName = sec.dataset.csSessionFlowSection;
      var secCards = grid.querySelectorAll('.cs-session-flow-card[data-cs-session-flow-category="' + secName + '"]');
      var hasVisible = false;
      secCards.forEach(function (c) {
        if (!c.hidden) hasVisible = true;
      });
      sec.hidden = !hasVisible;
    });

    if (empty) empty.hidden = shown > 0;
  }

  var sessionFlowSearchInput = document.getElementById('cs-session-flow-search-input');
  if (sessionFlowSearchInput) {
    sessionFlowSearchInput.addEventListener('input', function () { sessionFilterFlows(this.value); });
  }

  function sessionCloseFlowModal() {
    if (sessionFlowModal) sessionFlowModal.hidden = true;
  }

  if (sessionFlowModalClose) {
    sessionFlowModalClose.addEventListener('click', sessionCloseFlowModal);
  }
  var sessionImagesPanelClose = document.getElementById('cs-session-images-panel-close');
  if (sessionImagesPanelClose) {
    sessionImagesPanelClose.addEventListener('click', sessionCloseSidePanels);
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && document.querySelector('.cs-session-side-panel:not([hidden])')) sessionCloseSidePanels();
  });

  // Wire flow cards inside modal — record pending context, then navigate.
  // Create flows start from scratch; Refine flows operate on the selected image
  // (passed to the refine page via the shared upscale-source sessionStorage key).
  var SESSION_REFINE_SRC_KEY = 'oj-upscale-source-image-v1';
  if (sessionFlowModal) {
    sessionFlowModal.querySelectorAll('[data-cs-session-flow-action]').forEach(function (card) {
      card.addEventListener('click', function () {
        var action   = card.dataset.csSessionFlowAction;
        var category = card.dataset.csSessionFlowCategory || 'create';
        var needsBase = card.dataset.csSessionFlowNeedsBase === '1';
        var step = needsBase ? sessionResolveBaseStep() : sessionSelectedStep();
        var baseImg = sessionStepImage(step);

        if (needsBase && !baseImg) {
          alert(tF('Import or generate an image in this session first — Refine flows run on the selected image.'));
          return;
        }

        if (sessionCurrentSession && Session.setPending) {
          Session.setPending({
            sessionId: sessionCurrentSession.id,
            flowLabel: card.dataset.csSessionFlowLabel || action,
            flowCategory: category,
            flowAction: action,
            parentId: step ? step.id : null,
            subdir: (Session.subdirOf ? Session.subdirOf(sessionCurrentSession) : null),
            ts: Date.now()
          });
        }

        var label = card.dataset.csSessionFlowLabel || action;
        var slug  = action.replace(/_/g, '-');
        sessionCloseFlowModal();
        if (category === 'refine') {
          // Hand the selected image to the refine page as its input.
          try { sessionStorage.setItem(SESSION_REFINE_SRC_KEY, baseImg); } catch (_) {}
          sessionMountFlow('/nomad-studio/refine/' + slug, label);
        } else if (category === 'mix') {
          sessionMountFlow('/nomad-studio/mix/' + slug, label);
        } else {
          sessionMountFlow('/nomad-studio/create/' + slug, label);
        }
      });
    });
  }

  // Import image → dedicated image input; adds the image as a step in the session.
  // Uses .onclick / .onchange (idempotent) so re-running this script never stacks
  // duplicate handlers, and resolves the target session from the shared store.
  function sessionActiveSession() {
    if (sessionCurrentSession) return sessionCurrentSession;
    var id = Session.getActive && Session.getActive();
    return id ? Session.find(id) : null;
  }

  var sessionImageInput = document.getElementById('cs-session-image-input');

  // Add Images panel: the same sources as an image picker's ⋯ menu
  // (flow-step-image-picker.js ncfImageSourceItems), plus the device's own
  // files first. A source swaps the panel's content in place, like the ⋯
  // menu does; a pick is imported as an "Imported image" step.
  var sessionImagesPanel = document.getElementById('cs-session-images-panel');

  function sessionPickImageFile() {
    if (window.__sessionPickingImage) return;   // guard against any double trigger
    window.__sessionPickingImage = true;
    setTimeout(function () { window.__sessionPickingImage = false; }, 1200);
    var fi = document.getElementById('cs-session-image-input');
    if (fi) fi.click();
  }

  function sessionSetImagesPanel(title, fill) {
    var titleEl = document.getElementById('cs-session-images-panel-title');
    var body = document.getElementById('cs-session-images-panel-body');
    if (titleEl) titleEl.textContent = title;
    if (!body) return;
    body.innerHTML = '';
    fill(body);
  }

  function sessionOpenImagesPanel() {
    if (!sessionImagesPanel) return;
    var t = function (k, f) { return (window.NomadI18n && NomadI18n.t) ? NomadI18n.t(k, f) : f; };
    var sources = typeof ncfImageSourceItems === 'function' ? ncfImageSourceItems() : [];
    var items = [{
      label: t('session.addImages.device', 'From your device'),
      svgInner: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
      onClick: function () { sessionCloseSidePanels(); sessionPickImageFile(); },
    }].concat(sources.map(function (src) {
      return {
        label: src.label,
        svgInner: src.svgInner,
        onClick: function () {
          sessionSetImagesPanel(src.title, function (body) {
            src.fill(body, function (url) {
              sessionCloseSidePanels();
              sessionImportImageUrl(url);
            });
          });
        },
      };
    }));
    sessionSetImagesPanel(t('session.addImages.title', 'Add Images'), function (body) {
      if (typeof ncfFillOptionsMenu === 'function') ncfFillOptionsMenu(body, items);
    });
    sessionOpenSidePanel(sessionImagesPanel);
  }

  if (sessionFlowImportImg) {
    sessionFlowImportImg.onclick = function (e) {
      e.preventDefault();
      sessionOpenImagesPanel();
    };
  }
  var sessionAddImagesBtn = document.getElementById('cs-session-add-images-btn');
  if (sessionAddImagesBtn) {
    sessionAddImagesBtn.onclick = function (e) {
      e.preventDefault();
      sessionOpenImagesPanel();
    };
  }

  // Downscale/compress an image dataURL via canvas so it fits in localStorage.
  function sessionDownscaleImage(dataUrl, maxDim, cb) {
    var img = new Image();
    img.onload = function () {
      var w = img.naturalWidth || img.width;
      var h = img.naturalHeight || img.height;
      var scale = Math.min(1, maxDim / Math.max(w, h));
      var cw = Math.max(1, Math.round(w * scale));
      var ch = Math.max(1, Math.round(h * scale));
      try {
        var canvas = document.createElement('canvas');
        canvas.width = cw; canvas.height = ch;
        canvas.getContext('2d').drawImage(img, 0, 0, cw, ch);
        cb(canvas.toDataURL('image/jpeg', 0.85));
      } catch (_) {
        cb(dataUrl); // fall back to original on any canvas/CORS error
      }
    };
    img.onerror = function () { cb(dataUrl); };
    img.src = dataUrl;
  }

  // Adds an image to the active session as an "Imported image" step:
  // downscaled (caps the upload), saved to the server's output folder, and
  // only its URL kept in the session. A copy, not a link, so a Build image
  // edited later doesn't change the session.
  function sessionImportDataUrl(dataUrl) {
    var session = sessionActiveSession();
    if (!session || !dataUrl) return;
    sessionDownscaleImage(dataUrl, 1600, function (smallUrl) {
      function commit(finalUrl) {
        var step = {
          id: 'step-' + Date.now(),
          flowLabel: 'Imported image',
          flowCategory: 'import',
          imageUrl: finalUrl,
          images: [finalUrl],
          parentId: null,
          createdAt: new Date().toISOString()
        };
        session.steps = session.steps || [];
        session.steps.forEach(function (s) { s.selected = false; });
        step.selected = true;   // just-imported image becomes the active base
        session.steps.push(step);
        try {
          var all = Session.load();
          var i = all.findIndex(function (b) { return b.id === session.id; });
          if (i !== -1) { all[i] = session; } else { all.push(session); }
          Session.save(all);
        } catch (_) {}
        // Confirm persistence (a data: URL fallback may still exceed quota)
        var ok = false;
        try {
          var check = Session.find(session.id);
          ok = !!(check && check.steps && check.steps.some(function (s) { return s.id === step.id; }));
        } catch (_) {}
        if (!ok && /^data:/.test(finalUrl)) {
          alert(tF('The image was added but could not be saved permanently (storage is full). It will stay until you reload.'));
        }
        sessionRenderWorkspace(session);
      }

      fetch('/api/images/save-upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataUrl: smallUrl, filenamePrefix: 'session-import', subdir: (Session.subdirOf ? Session.subdirOf(session) : 'session') })
      })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) {
        if (res && res.ok && res.url) commit(res.url);  // server URL (tiny)
        else commit(smallUrl);                          // fallback: inline data URL
      })
      .catch(function () { commit(smallUrl); });
    });
  }

  // A picked image from Add Images (Build, tray, history, inputs): fetched
  // and imported like a file from the device.
  function sessionImportImageUrl(url) {
    fetch(url)
      .then(function (r) { return r.blob(); })
      .then(function (blob) {
        var reader = new FileReader();
        reader.onload = function (e) { sessionImportDataUrl(String(e.target.result || '')); };
        reader.readAsDataURL(blob);
      })
      .catch(function () { alert(tF('Could not load that image.')); });
  }

  if (sessionImageInput) {
    sessionImageInput.onchange = function () {
      var file = sessionImageInput.files && sessionImageInput.files[0];
      sessionImageInput.value = '';
      window.__sessionPickingImage = false;
      if (!file || !sessionActiveSession()) return;
      if (!/^image\//.test(file.type)) { alert(tF('Please choose an image file.')); return; }
      var reader = new FileReader();
      reader.onload = function (e) { sessionImportDataUrl(e.target.result); };
      reader.readAsDataURL(file);
    };
  }

  // Returns a promise that settles once the SERVER is done, so the caller can
  // refresh the list afterwards instead of racing its own delete — re-reading
  // while the DELETE is still in flight brought the session straight back.
  function sessionDeleteSession(sessionId) {
    var sessions = sessionLoadSessions().filter(function (b) { return b.id !== sessionId; });
    sessionSaveSessions(sessions);
    if (Session.getActive && Session.getActive() === sessionId && Session.setActive) Session.setActive('');
    if (sessionCurrentSession && sessionCurrentSession.id === sessionId) sessionCurrentSession = null;
    return Session.deleteRemote ? Session.deleteRemote(sessionId) : Promise.resolve();
  }

  function sessionDuplicateSession(session) {
    var copy = JSON.parse(JSON.stringify(session));
    var now = Date.now();
    copy.id = 'session-' + now;
    copy.name = (session.name || 'Untitled Session') + ' (copy)';
    copy.createdAt = new Date().toISOString();
    copy.folder = (Session.slugify ? Session.slugify(copy.name) : 'session') + '-' + Math.floor(now / 1000);
    // Re-id steps (and fix parent links) so the copy is fully independent.
    var idMap = {};
    (copy.steps || []).forEach(function (s, i) {
      var nid = 'step-' + now + '-' + i + '-' + Math.floor(Math.random() * 1e4);
      idMap[s.id] = nid;
      s.id = nid;
    });
    (copy.steps || []).forEach(function (s) {
      if (s.parentId && idMap[s.parentId]) s.parentId = idMap[s.parentId];
    });
    var sessions = sessionLoadSessions();
    sessions.push(copy);
    sessionSaveSessions(sessions);
    // Duplicates are always private to the current viewer — never prompted,
    // never shared with "everyone" — regardless of the source session's scope.
    if (Session.persistAsUser) Session.persistAsUser(copy);
    return copy;
  }

  function sessionWireWorkspaceActions(session) {
    var applyBtn     = document.getElementById('cs-session-apply-btn');
    var exportBtn    = document.getElementById('cs-session-export-btn');
    var deleteBtn    = document.getElementById('cs-session-delete-btn');
    var duplicateBtn = document.getElementById('cs-session-duplicate-btn');

    if (applyBtn) {
      applyBtn.onclick = sessionOpenFlowModal;
    }

    if (duplicateBtn) {
      duplicateBtn.onclick = function () {
        var copy = sessionDuplicateSession(session);
        sessionOpenSession(copy.id);   // open the new copy so it's ready to edit
      };
    }

    if (deleteBtn) {
      deleteBtn.onclick = function () {
        var name = session.name || tF('this session');
        if (!window.confirm(tF('Delete "{name}"? This removes the session and its history. This cannot be undone.').replace('{name}', name))) return;
        // Navigate only once the server has confirmed: leaving the page
        // immediately could cancel the DELETE that was still in flight, and
        // the session then came back on the next sync.
        deleteBtn.disabled = true;
        sessionDeleteSession(session.id).then(function () {
          // The workspace is its own page now (/nomad-studio/session/<id>) —
          // once the session's gone there's nothing left to show here, so go
          // back to the list instead of trying to re-render in place.
          window.location.href = '/nomad-studio/session';
        });
      };
    }

    if (exportBtn) {
      exportBtn.onclick = function () {
        if (exportBtn.disabled) return;
        exportBtn.disabled = true;
        exportBtn.classList.add('is-busy');
        fetch('/api/session/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(session)
        })
        .then(function (r) {
          if (!r.ok) throw new Error('Export failed (' + r.status + ')');
          return r.blob();
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = (session.name || 'session').replace(/\s+/g, '-').toLowerCase() + '.zip';
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
        })
        .catch(function (err) {
          alert(tF('Could not export this session:') + ' ' + (err && err.message || err));
        })
        .finally(function () {
          exportBtn.disabled = false;
          exportBtn.classList.remove('is-busy');
        });
      };
    }
  }

  // Wire Create / Import entry buttons
  var sessionCreateBtn   = document.getElementById('cs-session-create-btn');
  var sessionImportBtn   = document.getElementById('cs-session-import-btn');
  var sessionFileInput   = document.getElementById('cs-session-file-input');
  var sessionNewModal    = document.getElementById('cs-session-new-modal');
  var sessionModalClose  = document.getElementById('cs-session-modal-close');
  var sessionModalInput  = document.getElementById('cs-session-modal-name-input');
  var sessionModalConfirm = document.getElementById('cs-session-modal-confirm');

  function sessionOpenNewModal() {
    if (!sessionNewModal) return;
    if (sessionModalInput) sessionModalInput.value = '';
    sessionNewModal.hidden = false;
    requestAnimationFrame(function () {
      if (sessionModalInput) sessionModalInput.focus();
    });
  }

  function sessionCloseNewModal() {
    if (sessionNewModal) sessionNewModal.hidden = true;
  }

  if (sessionCreateBtn) {
    sessionCreateBtn.addEventListener('click', sessionOpenNewModal);
  }

  if (sessionModalClose) {
    sessionModalClose.addEventListener('click', sessionCloseNewModal);
  }

  // Close on backdrop click
  if (sessionNewModal) {
    sessionNewModal.addEventListener('click', function (e) {
      if (e.target === sessionNewModal) sessionCloseNewModal();
    });
  }

  function sessionSelectedScope(radioName, fallback) {
    var checked = document.querySelector('input[name="' + radioName + '"]:checked');
    return (checked && checked.value) || fallback || 'user';
  }

  // Confirm via button or Enter
  function sessionConfirmNew() {
    var name = sessionModalInput ? sessionModalInput.value.trim() : '';
    if (!name) { if (sessionModalInput) sessionModalInput.focus(); return; }
    var scope = sessionSelectedScope('cs-session-modal-scope', 'user');
    sessionCloseNewModal();
    // Create on the server first (with the chosen scope: all vs just me) so
    // the id we render the workspace with is the real, cross-browser one.
    // Falls back to a local-only session if the server call fails.
    var createP = Session.createRemote ? Session.createRemote(name, scope) : Promise.resolve(sessionCreateSession(name));
    createP.then(function (session) {
      sessionOpenSession(session.id);
    });
  }

  if (sessionModalConfirm) {
    sessionModalConfirm.addEventListener('click', sessionConfirmNew);
  }

  if (sessionModalInput) {
    sessionModalInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') sessionConfirmNew();
      if (e.key === 'Escape') sessionCloseNewModal();
    });
  }

  if (sessionImportBtn) {
    sessionImportBtn.addEventListener('click', function () {
      if (sessionFileInput) sessionFileInput.click();
    });
  }

  // ── Import scope modal — asks "everyone" vs "just me" before the parsed
  // session is persisted server-side, mirroring the New Session prompt. ──────
  var sessionImportScopeModal   = document.getElementById('cs-session-import-scope-modal');
  var sessionImportScopeClose   = document.getElementById('cs-session-import-scope-close');
  var sessionImportScopeConfirm = document.getElementById('cs-session-import-scope-confirm');
  var sessionPendingImport = null;   // parsed-but-not-yet-persisted session from the picked file

  function sessionOpenImportScopeModal(parsedSession) {
    sessionPendingImport = parsedSession;
    if (!sessionImportScopeModal) { sessionFinishImport('user'); return; }
    sessionImportScopeModal.hidden = false;
  }

  function sessionCloseImportScopeModal() {
    if (sessionImportScopeModal) sessionImportScopeModal.hidden = true;
    sessionPendingImport = null;
  }

  function sessionFinishImport(scope) {
    var session = sessionPendingImport;
    sessionPendingImport = null;
    if (sessionImportScopeModal) sessionImportScopeModal.hidden = true;
    if (!session) return;
    if (!session.steps) session.steps = [];

    var importP = Session.importRemote
      ? Session.importRemote(session, scope)
      : Promise.resolve((function () {
          if (!session.id) session.id = 'session-' + Date.now();
          var sessions = sessionLoadSessions();
          if (!sessions.find(function (b) { return b.id === session.id; })) {
            sessions.push(session);
            sessionSaveSessions(sessions);
          }
          return session;
        })());
    importP.then(function (saved) { sessionOpenSession(saved.id); });
  }

  if (sessionImportScopeConfirm) {
    sessionImportScopeConfirm.addEventListener('click', function () {
      sessionFinishImport(sessionSelectedScope('cs-session-import-scope', 'user'));
    });
  }
  if (sessionImportScopeClose) {
    sessionImportScopeClose.addEventListener('click', sessionCloseImportScopeModal);
  }
  if (sessionImportScopeModal) {
    sessionImportScopeModal.addEventListener('click', function (e) {
      if (e.target === sessionImportScopeModal) sessionCloseImportScopeModal();
    });
  }

  if (sessionFileInput) {
    sessionFileInput.addEventListener('change', function () {
      var file = sessionFileInput.files[0];
      if (!file) return;
      var isZip = /\.zip$/i.test(file.name) || file.type === 'application/zip';

      if (isZip) {
        // The browser can't unzip client-side — hand the file to the server,
        // which extracts session.json from the archive (see /api/session/export,
        // the same endpoint that writes it) and hands the parsed object back.
        var form = new FormData();
        form.append('file', file);
        fetch('/api/session/import-zip', { method: 'POST', body: form })
          .then(function (res) { return res.json().then(function (body) { return { ok: res.ok, body: body }; }); })
          .then(function (r) {
            if (!r.ok) throw new Error(r.body && r.body.error ? r.body.error : 'Could not read that .zip.');
            sessionOpenImportScopeModal(r.body);
          })
          .catch(function (err) {
            alert(tF('Could not read session file:') + ' ' + err.message);
          });
      } else {
        var reader = new FileReader();
        reader.onload = function (e) {
          try {
            var session = JSON.parse(e.target.result);
            sessionOpenImportScopeModal(session);
          } catch (err) {
            alert(tF('Could not read session file:') + ' ' + err.message);
          }
        };
        reader.readAsText(file);
      }

      sessionFileInput.value = '';
    });
  }

  /* ── Sub-action clicks ─────────────────────────────────────────────────── */
  document.querySelectorAll('[data-cs-action]').forEach(function (card) {
    card.addEventListener('click', function (e) {
      e.preventDefault();
      var action = card.dataset.csAction;

      if (action === 'simple') {
        window.location.href = '/nomad-studio/create/simple';
        return;
      }

      if (action === 'simple_json') {
        window.location.href = '/nomad-studio/create/simple-json';
        return;
      }

      if (action === 'simple_civitai') {
        window.location.href = '/nomad-studio/create/simple-civitai';
        return;
      }

      if (action === 'assist') {
        window.location.href = '/nomad-studio/create/assist';
        return;
      }

      if (action === 'enhance_civitai') {
        window.location.href = '/nomad-studio/create/enhance-civitai';
        return;
      }

      if (action === 'chat') {
        window.location.href = '/nomad-studio/create/chat';
        return;
      }

      if (action === 'chat_civitai') {
        window.location.href = '/nomad-studio/create/chat-civitai';
        return;
      }

      if (action === 'variations') {
        window.location.href = '/nomad-studio/create/variations';
        return;
      }

      if (action === 'variations_json') {
        window.location.href = '/nomad-studio/create/variations-json';
        return;
      }

      if (action === 'scenes') {
        window.location.href = '/nomad-studio/create/scenes';
        return;
      }

      if (action === 'portraits') {
        window.location.href = '/nomad-studio/create/portraits';
        return;
      }

      if (action === 'story') {
        window.location.href = '/nomad-studio/create/story';
        return;
      }

      // Generic handler for all other create actions
      window.location.href = '/nomad-studio/create/' + action.replace(/_/g, '-');
    });
  });

  /* \u2500\u2500 Refine sub-action clicks \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
  document.querySelectorAll('[data-cs-refine-action]').forEach(function (card) {
    card.addEventListener('click', function (e) {
      e.preventDefault();
      var action = card.dataset.csRefineAction;
      window.location.href = '/nomad-studio/refine/' + action.replace(/_/g, '-');
    });
    attachSpotlight(card);
  });

  /* ── Mix sub-action clicks ──────────────────────────────────────────── */
  document.querySelectorAll('[data-cs-mix-action]').forEach(function (card) {
    card.addEventListener('click', function (e) {
      e.preventDefault();
      var action = card.dataset.csMixAction;
      window.location.href = '/nomad-studio/mix/' + action.replace(/_/g, '-');
    });
    attachSpotlight(card);
  });

  /* ── Sessions History list (bottom of main view) ───────────────────────── */
  function formatSessionDate(ts) {
    try {
      const d = new Date(ts);
      return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' }) + ' ' +
             d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
    } catch (_) {
      return '';
    }
  }

  function getSessionIcon(type) {
    if (type === 'scenes') {
      return '<svg viewBox="0 0 24 24" width="20" height="20"><rect x="3" y="3" width="5" height="5" rx="1"/><rect x="10" y="3" width="5" height="5" rx="1"/><rect x="17" y="3" width="4" height="5" rx="1"/><rect x="3" y="10" width="5" height="5" rx="1"/><rect x="10" y="10" width="5" height="5" rx="1"/><rect x="17" y="10" width="4" height="5" rx="1"/><rect x="3" y="17" width="5" height="4" rx="1"/><rect x="10" y="17" width="5" height="4" rx="1"/><rect x="17" y="17" width="4" height="4" rx="1"/></svg>';
    }
    if (type === 'assist') {
      return '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M15 4V2m0 2v2m0-2h-4.5M3 10h18M5 10v10a1 1 0 001 1h12a1 1 0 001-1V10"/><path d="M12 14v4M10 16h4"/></svg>';
    }
    // simple / default
    return '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M12 5v14M5 12h14"/></svg>';
  }

  function historyEscape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function historyThumbsHtml(imgs) {
    return imgs.slice(0, 4).map(function (img) {
      const src = typeof img === 'string' ? img : (img && img.url ? img.url : '');
      // History rows only ever show these at ~27-108px — fetching the
      // full-res generation output (often 1-3MB) just for that is what
      // makes the panel feel slow to appear. Reuse the same /thumb
      // endpoint the Album gallery uses instead of the raw image.
      const thumbSrc = (src.indexOf('/api/images/') === 0 && src.indexOf('/thumb') === -1)
        ? src + '/thumb?w=100'
        : src;
      // If the thumbnail can't be served, fall back to the original image.
      const fallback = thumbSrc !== src
        ? ` onerror="this.onerror=null;this.src=this.dataset.full" data-full="${historyEscape(src)}"`
        : '';
      return `<img class="cs-session-thumb" src="${historyEscape(thumbSrc)}"${fallback} alt="" loading="lazy">`;
    }).join('');
  }

  function groupHistoryBySession(entries) {
    const known = (window.NomadSession && typeof window.NomadSession.load === 'function')
      ? window.NomadSession.load() : [];
    const byId = {};
    const byFolder = {};
    known.forEach(function (s) {
      if (!s || !s.id) return;
      byId[s.id] = s;
      if (s.folder) byFolder[s.folder] = s;
    });

    function sessionOf(entry) {
      if (entry.sessionId) return byId[entry.sessionId] || null;
      const imgs = (entry.data && Array.isArray(entry.data.images)) ? entry.data.images : [];
      for (let i = 0; i < imgs.length; i++) {
        const src = typeof imgs[i] === 'string' ? imgs[i] : (imgs[i] && imgs[i].url) || '';
        const m = /\/api\/images\/session\/([^/]+)\//.exec(src);
        if (m && byFolder[m[1]]) return byFolder[m[1]];
      }
      return null;
    }

    const rows = [];
    const groups = {};
    entries.forEach(function (entry) {
      if (!entry) return;
      const session = sessionOf(entry);
      if (!session) { rows.push({ kind: 'flow', entry: entry }); return; }
      let group = groups[session.id];
      if (!group) {
        group = groups[session.id] = { kind: 'session', session: session, ts: entry.ts, flows: 0, images: [] };
        rows.push(group);
      }
      group.flows++;
      if (entry.ts > group.ts) group.ts = entry.ts;
      const imgs = (entry.data && Array.isArray(entry.data.images)) ? entry.data.images : [];
      group.images = group.images.concat(imgs);
    });
    return rows;
  }

  function buildSessionHistoryRow(group) {
    const session = group.session;
    const t = (window.NomadI18n && typeof window.NomadI18n.t === 'function')
      ? window.NomadI18n.t : function (_k, fallback) { return fallback; };

    // One thumbnail: the session's first image (its first step with one);
    // the flows' history images are only a fallback.
    let firstImg = null;
    (Array.isArray(session.steps) ? session.steps : []).some(function (step) {
      firstImg = step && (step.imageUrl || (Array.isArray(step.images) && step.images[0])) || null;
      return !!firstImg;
    });
    const imgs = firstImg ? [firstImg] : group.images.slice(0, 1);
    const thumbsBlock = imgs.length
      ? `<div class="cs-session-thumbs">${historyThumbsHtml(imgs)}</div>`
      : `<div class="cs-session-thumbs cs-session-thumbs--icon">${getSessionIcon('session')}</div>`;

    const flowsText = group.flows === 1
      ? t('hub.history.oneFlow', '1 flow')
      : t('hub.history.manyFlows', '{n} flows').replace('{n}', group.flows);
    const badge = `<span class="cs-session-badge">${historyEscape(t('hub.history.sessionBadge', 'Session'))} · ${historyEscape(flowsText)}</span>`;
    const name = `<span class="cs-session-prompt">${historyEscape(session.name || t('hub.history.untitledSession', 'Untitled Session'))}</span>`;
    const date = `<span class="cs-session-date">${formatSessionDate(group.ts)}</span>`;

    const row = document.createElement('div');
    row.className = 'cs-session-row cs-session-row--session';
    row.innerHTML = `
      ${thumbsBlock}
      <div class="cs-session-info">
        <div class="cs-session-info-top">${badge}${date}</div>
        ${name}
      </div>
    `;
    row.addEventListener('click', function () {
      window.location.href = '/nomad-studio/session/' + encodeURIComponent(session.id);
    });
    return row;
  }

  function renderSessionsHistory() {
    const container = document.getElementById('cs-sessions-list');
    if (!container) return;

    // Try to use the helper exposed by create/index.js if available
    let sessions = [];
    if (window.NomadStudio && typeof window.NomadStudio.loadSessionsHistory === 'function') {
      sessions = window.NomadStudio.loadSessionsHistory();
    } else {
      try {
        const raw = localStorage.getItem('oj-create-sessions-history-v1');
        sessions = raw ? JSON.parse(raw) : [];
      } catch (_) { sessions = []; }
    }

    container.innerHTML = '';

    if (!sessions.length) {
      const empty = document.createElement('div');
      empty.className = 'cs-session-empty';
      empty.textContent = tF('No saved sessions yet. Generate something in Scenes, Simple or Enhance and they will show up here.');
      container.appendChild(empty);
      return;
    }

    // Flows run inside a Session are folded into ONE row for that Session
    // (placed where its most recent flow was) instead of one loose row per
    // flow. Entries saved before flows recorded their sessionId are matched
    // by image path instead: session outputs live under
    // /api/images/session/<folder>/. A flow whose session no longer exists
    // stays a plain flow row.
    const rows = groupHistoryBySession(sessions);

    // Storage itself is uncapped now (Album is the full archive) — this
    // quick panel only ever needs to show the most recent ones.
    rows.slice(0, 30).forEach(function (item) {
      if (item.kind === 'session') {
        container.appendChild(buildSessionHistoryRow(item));
        return;
      }
      const sess = item.entry;
      const row = document.createElement('div');
      row.className = 'cs-session-row';

      const imgs = (sess.data && Array.isArray(sess.data.images)) ? sess.data.images : [];
      const thumbsBlock = imgs.length
        ? `<div class="cs-session-thumbs">${historyThumbsHtml(imgs)}</div>`
        : `<div class="cs-session-thumbs cs-session-thumbs--icon">${getSessionIcon(sess.type)}</div>`;

      const badge = `<span class="cs-session-badge">${sess.label || sess.type}</span>`;
      const prompt = `<span class="cs-session-prompt">${(sess.prompt || '').slice(0, 120) || '—'}</span>`;
      const date = `<span class="cs-session-date">${formatSessionDate(sess.ts)}</span>`;

      row.innerHTML = `
        ${thumbsBlock}
        <div class="cs-session-info">
          <div class="cs-session-info-top">${badge}${date}</div>
          ${prompt}
        </div>
      `;

      row.addEventListener('click', function () {
        // Store the full session for the target page to pick up
        try {
          sessionStorage.setItem('oj-load-session', JSON.stringify(sess));
        } catch (_) {}

        // Navigate to the correct page
        if (sess.type && sess.type.startsWith('refine.')) {
          window.location.href = '/nomad-studio/refine/' + sess.type.slice(7).replace(/_/g, '-');
        } else if (sess.type && sess.type.startsWith('mix.')) {
          window.location.href = '/nomad-studio/mix/' + sess.type.slice(4).replace(/_/g, '-');
        } else if (sess.type && sess.type.startsWith('create.')) {
          window.location.href = '/nomad-studio/create/' + sess.type.slice(7).replace(/_/g, '-');
        } else if (sess.type === 'scenes') {
          window.location.href = '/nomad-studio/create/scenes';
        } else if (sess.type === 'assist') {
          window.location.href = '/nomad-studio/create/assist';
        } else {
          window.location.href = '/album';
        }
      });

      container.appendChild(row);
    });
  }


  // ── Init ─────────────────────────────────────────────────────────────────────────
  function init() {
    renderSessionsHistory();
    // If we jumped straight back into the Session (return from Add Flow), build it.
    if (viewSession && viewSession.style.display === 'flex') {
      sessionInit();
    }
  }

  init();

  // ── History Panel Toggle ──────────────────────────────────────────────
  const historyToggle = document.getElementById('cs-history-toggle');
  const historyPanel = document.getElementById('cs-history-panel');
  const historyClose = document.getElementById('cs-history-close');
  const historyOverlay = document.getElementById('cs-history-overlay');
  const historyClear = document.getElementById('cs-history-clear');

  if (historyClear) {
    historyClear.addEventListener('click', function () {
      if (!window.confirm(tF('Clear all history? This cannot be undone.'))) return;
      try { localStorage.removeItem('oj-create-sessions-history-v1'); } catch (_) {}
      renderSessionsHistory();
    });
  }

  if (historyToggle && historyPanel) {
    const historyToggleTip = document.getElementById('cs-history-toggle-tip');

    function setHistoryOpen(open) {
      // Re-read on open: Session rows depend on the sessions list, which the
      // server sync may have refreshed since the page first rendered.
      if (open) renderSessionsHistory();
      historyPanel.classList.toggle('is-open', open);
      historyToggle.setAttribute('aria-expanded', String(open));
      if (historyToggleTip) historyToggleTip.textContent = open ? 'Hide history' : 'Show history';
    }

    historyToggle.addEventListener('click', function () {
      setHistoryOpen(!historyPanel.classList.contains('is-open'));
    });
    if (historyClose) {
      historyClose.addEventListener('click', function () { setHistoryOpen(false); });
    }
    if (historyOverlay) {
      historyOverlay.addEventListener('click', function () { setHistoryOpen(false); });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && historyPanel.classList.contains('is-open')) setHistoryOpen(false);
    });
  }

  // ── Settings Panel Toggle (left side) ───────────────────────────────────
  (function initSettingsPanel() {
    var settingsBtn = document.getElementById('cs-settings-btn');
    var settingsPanel = document.getElementById('cs-settings-panel');
    var settingsClose = document.getElementById('cs-settings-close');
    var settingsOverlay = document.getElementById('cs-settings-overlay');
    if (!settingsPanel) return;

    function setOpen(open) {
      settingsPanel.classList.toggle('is-open', open);
      if (settingsBtn) settingsBtn.setAttribute('aria-expanded', String(open));
      if (!open) setDetailOpen(false);
    }

    if (settingsBtn) {
      settingsBtn.addEventListener('click', function () {
        setOpen(!settingsPanel.classList.contains('is-open'));
      });
    }
    if (settingsClose) {
      settingsClose.addEventListener('click', function () { setOpen(false); });
    }
    if (settingsOverlay) {
      settingsOverlay.addEventListener('click', function () { setOpen(false); });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && settingsPanel.classList.contains('is-open')) setOpen(false);
    });

    // ── Detail flyout: fetches the real technical page (same route the
    // sidebar uses), pulls out just its content, and drops it into the panel
    // — no iframe. The page's own script runs for real against that markup,
    // so editing / saving / deleting behaves exactly like the full page.
    var detailPanel = document.getElementById('cs-settings-detail');
    var detailTitle = document.getElementById('cs-settings-detail-title');
    var detailClose = document.getElementById('cs-settings-detail-close');
    var embedEl = document.getElementById('cs-settings-detail-embed');

    // Body classes some technical pages add (for full-viewport layout
    // tricks). They must not leak onto the Nomad Studio host page.
    var EMBEDDED_BODY_CLASSES = [
      'settings-page', 'models-import-page', 'models-chat-page', 'models-vision-page',
      'workflows-editor-page', 'workflows-describe-benchmark-page', 'nomadui-page',
    ];
    var embedScriptEls = [];
    var embedToken = 0;
    var rowMenuObserver = null;

    // The Images list ships a "+Queue" toggle and five separate action
    // buttons per row (Edit/Reimport/Files/Export/Delete). Inside this
    // narrow flyout that reads as clutter, and the queue toggle doesn't
    // apply here (queueing works differently from Nomad Studio) — so we
    // drop it and collapse the rest behind a "⋮" menu. This only touches
    // the embedded copy of the DOM, never the real page.
    function collapseImportRowActions(root) {
      var rows = root.querySelectorAll('.import-item.import-item-stacked .btn-row:not([data-cs-collapsed])');
      Array.prototype.forEach.call(rows, function (btnRow) {
        btnRow.setAttribute('data-cs-collapsed', '1');

        var queueBtn = btnRow.querySelector('[data-toggle-active-id]');
        if (queueBtn) queueBtn.remove();

        var rest = Array.prototype.slice.call(btnRow.children);
        if (!rest.length) return;

        var wrap = document.createElement('div');
        wrap.className = 'cs-row-menu';

        var toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'cs-row-menu-toggle';
        toggle.setAttribute('aria-haspopup', 'true');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-label', tF('More actions'));
        toggle.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16"><circle cx="12" cy="5" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="19" r="1.6" fill="currentColor"/></svg>';

        var menu = document.createElement('div');
        menu.className = 'cs-row-menu-list';
        rest.forEach(function (btn) { menu.appendChild(btn); });

        wrap.appendChild(toggle);
        wrap.appendChild(menu);
        btnRow.appendChild(wrap);

        toggle.addEventListener('click', function (e) {
          e.stopPropagation();
          var isOpen = wrap.classList.contains('is-open');
          document.querySelectorAll('.cs-row-menu.is-open').forEach(function (openWrap) {
            if (openWrap !== wrap) openWrap.classList.remove('is-open');
          });
          wrap.classList.toggle('is-open', !isOpen);
          toggle.setAttribute('aria-expanded', String(!isOpen));
        });

        Array.prototype.forEach.call(menu.querySelectorAll('button'), function (btn) {
          btn.addEventListener('click', function () { wrap.classList.remove('is-open'); }, true);
        });
      });
    }

    document.addEventListener('click', function () {
      document.querySelectorAll('.cs-row-menu.is-open').forEach(function (w) { w.classList.remove('is-open'); });
    });

    function ensureRowMenuObserver() {
      if (rowMenuObserver || !embedEl) return;
      rowMenuObserver = new MutationObserver(function () {
        collapseImportRowActions(embedEl);
      });
      rowMenuObserver.observe(embedEl, { childList: true, subtree: true });
    }

    function teardownRowMenuObserver() {
      if (rowMenuObserver) {
        rowMenuObserver.disconnect();
        rowMenuObserver = null;
      }
    }

    function stripEmbeddedBodyClasses() {
      EMBEDDED_BODY_CLASSES.forEach(function (c) { document.body.classList.remove(c); });
    }

    function clearEmbedScripts() {
      embedScriptEls.forEach(function (el) { try { el.remove(); } catch (_) {} });
      embedScriptEls = [];
    }

    function loadEmbedScript(src, type) {
      return new Promise(function (resolve, reject) {
        var script = document.createElement('script');
        script.src = src;
        if (type) script.type = type;
        script.async = false;
        script.onload = function () { embedScriptEls.push(script); resolve(); };
        script.onerror = function () { reject(new Error('Failed to load ' + src)); };
        document.body.appendChild(script);
      });
    }

    async function loadEmbedScripts(sources) {
      for (var i = 0; i < sources.length; i++) {
        await loadEmbedScript(sources[i].src, sources[i].type);
      }
    }

    function setDetailOpen(open) {
      if (!detailPanel) return;
      detailPanel.classList.toggle('is-open', open);
      if (!open) {
        embedToken += 1; // invalidate any in-flight fetch/script load
        teardownRowMenuObserver();
        clearEmbedScripts();
        stripEmbeddedBodyClasses();
        if (embedEl) embedEl.innerHTML = '<p class="cs-settings-detail-loading">' + tH('Select an item on the left.') + '</p>';
      }
    }

    async function openDetail(href, label) {
      if (!detailPanel || !embedEl) {
        window.location.href = href;
        return;
      }
      // The href can carry a fragment (e.g. "…/settings#packages") to jump
      // straight to one section of the embedded page instead of dropping
      // the user at its top — fetch() itself never sends the fragment to
      // the server, so it's parsed here and applied after the markup lands.
      var targetHash = '';
      try { targetHash = new URL(href, window.location.href).hash.replace(/^#/, ''); } catch (_) {}
      if (detailTitle) detailTitle.textContent = label || 'Settings';
      setDetailOpen(true);

      var token = (embedToken += 1);
      teardownRowMenuObserver();
      clearEmbedScripts();
      stripEmbeddedBodyClasses();
      embedEl.innerHTML = '<p class="cs-settings-detail-loading">' + tH('Loading…') + '</p>';

      try {
        var res = await fetch(href, {
          method: 'GET',
          headers: { 'X-Requested-With': 'OpenJourneyEmbeddedPanel' },
          credentials: 'same-origin',
        });
        if (!res.ok) throw new Error('Request failed (' + res.status + ')');
        var html = await res.text();
        if (token !== embedToken) return; // a newer click superseded this one

        var doc = new DOMParser().parseFromString(html, 'text/html');
        var incomingMain = doc.querySelector('.main-wrap');
        if (!incomingMain) throw new Error(tF('Unexpected response'));

        // A target fragment (e.g. "…/settings#packages") means "just that
        // section", not "the whole page, scrolled" — Settings is nine
        // sections long, and a flyout meant to be a quick side panel
        // shouldn't make Packages compete with Output/ComfyUI/three prompt
        // editors for space. Rebuilt inside the same settings-layout-v2
        // wrapper the full page uses, so its existing embed CSS (sizing,
        // section-card look) still applies to the lone section.
        var targetSection = targetHash
          ? incomingMain.querySelector('#' + CSS.escape(targetHash))
          : null;
        if (targetSection) {
          var wrap = doc.createElement('div');
          wrap.className = 'settings-layout settings-layout-v2';
          wrap.appendChild(targetSection);
          embedEl.innerHTML = '';
          embedEl.appendChild(wrap);
        } else {
          embedEl.innerHTML = incomingMain.innerHTML;
        }

        var scriptSources = Array.prototype.slice
          .call(doc.querySelectorAll('script[src]:not([data-shell-script])'))
          .map(function (el) {
            return {
              src: new URL(el.getAttribute('src'), window.location.href).toString(),
              type: el.getAttribute('type') || '',
            };
          });

        await loadEmbedScripts(scriptSources);
        if (token !== embedToken) return;

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
          window.lucide.createIcons();
        }

        collapseImportRowActions(embedEl);
        ensureRowMenuObserver();

        if (targetHash) {
          var targetEl = embedEl.querySelector('#' + CSS.escape(targetHash));
          if (targetEl) targetEl.scrollIntoView({ block: 'start' });
        }
      } catch (err) {
        if (token !== embedToken) return;
        embedEl.innerHTML =
          '<p class="cs-settings-detail-error">' + tH('Couldn’t load this section here.') + ' '
          + '<a href="' + href + '" target="_blank" rel="noopener">' + tH('Open it in a new tab') + '</a> ' + tH('instead.') + '</p>';
      }
    }

    if (detailClose) detailClose.addEventListener('click', function () { setDetailOpen(false); });

    var navItems = settingsPanel.querySelectorAll('[data-cs-settings-href]');
    Array.prototype.forEach.call(navItems, function (item) {
      item.addEventListener('click', function (e) {
        var href = item.getAttribute('data-cs-settings-href');
        if (!href) return;
        e.preventDefault();
        var nameEl = item.querySelector('.cs-settings-item-name');
        openDetail(href, nameEl ? nameEl.textContent.trim() : '');
      });
    });

    // The model LEDs are painted by services/nav_status.js. A service that goes down (ComfyUI, LM Studio) opens the panel by itself
    // so its warning triangle is seen — once per outage: the set of services
    // down is remembered for this tab, so closing the panel sticks, and it
    // resets once everything answers again.
    var LED_AUTOOPEN_KEY = 'cs-settings-autoopened-v1';
    function syncLeds() {
      var leds = settingsPanel.querySelectorAll('[data-cs-led]');
      var down = [];
      Array.prototype.forEach.call(leds, function (el) {
        if (el.classList.contains('unavailable')) down.push(el.getAttribute('data-cs-led'));
      });
      var signature = down.sort().join(',');
      var seen = '';
      try { seen = sessionStorage.getItem(LED_AUTOOPEN_KEY) || ''; } catch (_) {}
      if (!signature) {
        if (seen) { try { sessionStorage.removeItem(LED_AUTOOPEN_KEY); } catch (_) {} }
        return;
      }
      if (signature !== seen) {
        try { sessionStorage.setItem(LED_AUTOOPEN_KEY, signature); } catch (_) {}
        setOpen(true);
      }
    }
    syncLeds();
    setInterval(syncLeds, 2000);
  })();

  // ── Theme cycle button ──────────────────────────────────────────────────
  const THEME_KEY = 'oj-theme-v1';
  const THEMES = [
    { id: '1', icon: '🌕', label: 'Dawn' },
    { id: '2', icon: '🌔', label: 'Dusk' },
    { id: '3', icon: '🌓', label: 'Twilight' },
    { id: '4', icon: '🌒', label: 'Night' },
    { id: '5', icon: '🌑', label: 'Void' },
    { id: '6', icon: '🔴', label: 'Mars' },
    { id: '7', icon: '🟣', label: 'Jupiter' },
    { id: '8', icon: '🩵', label: 'Saturn' },
  ];

  function applyTheme(id) {
    document.body.setAttribute('data-theme', id);
    const t = THEMES.find((x) => x.id === id) || THEMES[3];
    const iconEl = document.getElementById('cs-theme-cycle-icon');
    if (iconEl) iconEl.textContent = t.icon;
  }

  const saved = localStorage.getItem(THEME_KEY) || '4';
  applyTheme(saved);

  // Registra el listener del botón de tema
  const themeBtn = document.getElementById('cs-theme-cycle-btn');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const current = document.body.getAttribute('data-theme') || '4';
      const idx = THEMES.findIndex((x) => x.id === current);
      const next = THEMES[(idx + 1) % THEMES.length];
      localStorage.setItem(THEME_KEY, next.id);
      applyTheme(next.id);
    });
  }

  // Nota: #cs-mobile-mode-btn (issue #77) es un enlace normal a /mobile
  // (ver nomad_studio.html), no un toggle — no necesita lógica JS aquí.

  /* ── Tag → Lucide icon map (sidebar chips) ──────────────────────────────
     Lucide is already loaded globally (see layout/base.html) and hydrated
     once via lucide.createIcons() on initial page load. Since these chips
     are (re)rendered dynamically, renderChips() must call createIcons()
     again after every innerHTML write, or the <i data-lucide> placeholders
     stay empty. Unmapped tags simply render without an icon. */
  var TAG_ICONS = {
    'Assist': 'wand-2', 'No LLM': 'hand', 'Chat': 'message-square',
    'AI Compose': 'layout-template', 'CivitAI': 'link', 'Batch': 'layers',
    'Layout': 'layout-grid', 'Loop': 'repeat', 'N variations': 'shuffle',
    'Sequential': 'list-ordered', 'Structured': 'braces', 'AI enhanced': 'sparkles',
    'AI Loop': 'refresh-cw', 'Blend': 'blend', 'Catalog': 'book-open',
    'Character': 'user', 'Characters': 'users', 'Cinematic': 'clapperboard',
    'Consistent': 'check-circle', 'Creative': 'lightbulb', 'Diptych': 'columns-2',
    'Evolve': 'trending-up', 'Fast': 'zap', 'Full AI': 'cpu',
    'Grid': 'grid-3x3', 'I2I': 'image', 'Ideogram': 'type',
    'JSON': 'file-json', 'Lettering': 'type', 'Library': 'library',
    'Lighting': 'sun', 'Master': 'crown', 'N portraits': 'id-card',
    'Narrative': 'book-text', 'Placement': 'move', 'Quick': 'zap',
    'Reference': 'bookmark', 'Scene': 'camera', 'Storyboard': 'film',
    'Style': 'palette', 'Style lock': 'lock', 'Style ref': 'swatch-book',
    'Template': 'layout-panel-top', 'Type Art': 'type', 'Up to 100': 'hash',

    // Refine tags
    'Flux2': 'flame', 'Klein': 'box', 'Qwen': 'bot', 'Edit': 'pencil',
    'Prompt': 'terminal', 'LoRA': 'puzzle', 'Local': 'hard-drive',
    'Canvas': 'square', 'Cutout': 'crop', 'No AI': 'ban', 'Outpaint': 'expand',
    'Refine': 'sparkles', 'Restore': 'rotate-ccw', 'Skin': 'scan-face',
    'Transparent': 'square-dashed', 'Upscale': 'maximize', 'Angles': 'compass',
    'BiRefNet': 'scan', 'Chroma Key': 'pipette', 'Flux': 'flame',
    'Klein 4B': 'box', 'Lightning': 'zap', 'Model': 'cpu', 'Photo': 'image',
    'Pixel Art': 'boxes', 'Relight': 'sun', 'Remove': 'eraser',
    'Replace': 'replace', 'RMBG': 'scissors', 'Single': 'circle',
    'Watermark': 'droplets',

    // Remaining tags found in flow instructions/workflows without an icon
    // yet (audited 2026-08-27 against every card_tags array in
    // app/instructions/**/*.json and app/workflows/**/*.json) — see #30/#33/#37.
    'Anima': 'sparkles', 'Artistic': 'palette', 'Auto-fill': 'wand-2',
    'Avatar': 'user-circle', 'Boogu': 'bot', 'Cartoon': 'smile',
    'Casual': 'shirt', 'Cinema': 'clapperboard', 'Color': 'palette',
    'Comic': 'book-open', 'Compose': 'layout-template', 'Conversation': 'message-circle',
    'Correct': 'check', 'Editorial': 'newspaper', 'Effects': 'sparkles',
    'Enhance': 'sparkles', 'Exposure': 'sun', 'Expression': 'smile',
    'Eyes': 'eye', 'Face': 'scan-face', 'FaceSwap': 'repeat',
    'Fashion': 'shirt', 'Film': 'film', 'Flash': 'zap',
    'Glare': 'sun', 'Glasses': 'glasses', 'Grading': 'sliders-horizontal',
    'Hair': 'scissors', 'Hairstyle': 'scissors', 'Hands': 'hand',
    'Headshot': 'user', 'INT8': 'cpu', 'Idea': 'lightbulb',
    'Illustration': 'palette', 'Klein 9B': 'box', 'Krea2': 'sparkles',
    'LLM': 'brain', 'Layer': 'layers', 'Layers': 'layers',
    'Look Book': 'book-open', 'Migration': 'arrow-right-left', 'Mix': 'shuffle',
    'Native': 'flag', 'No LLM idea': 'hand', 'Ostris': 'puzzle',
    'Pet': 'paw-print', 'Portrait': 'id-card', 'Preset': 'sliders-horizontal',
    'Professional': 'briefcase', 'Profile': 'user', 'Quality': 'gem',
    'RF Inversion': 'undo-2', 'Realistic': 'camera', 'ReferenceLatent': 'link',
    'Repair': 'wrench', 'Retouch': 'brush', 'Retro': 'clock',
    'SAM3': 'scan', 'SeedVR2': 'sparkles', 'Selfie': 'camera',
    'Silhouette': 'moon', 'Subject': 'user', 'Superhero': 'zap',
    'Text Select': 'text-cursor', 'Transform': 'shuffle', 'Turbo': 'gauge',
    'USO': 'swatch-book', 'Vision': 'eye', 'Yearbook': 'book',
    'Z-Image': 'image'
  };

  function tagIconSvg(tag) {
    var name = TAG_ICONS[tag];
    if (!name) {
      // Dynamic tags not in the static map: "N looks" (Look Book packs,
      // one per pack size) and bare model-version numbers (e.g. "2511").
      if (/^\d+\s+looks?$/i.test(tag)) name = 'book-open';
      else if (/^\d+$/.test(tag)) name = 'cpu';
    }
    return name ? '<i data-lucide="' + name + '" class="nav-icon" aria-hidden="true"></i>' : '';
  }

  /* ── Tag filter chips — shared logic for Create + Refine ───────────────── */
  function initTagFilter(viewKey) {
    function setup() {
      var grid    = document.getElementById('cs-sub-grid-' + viewKey);
      var bar     = document.getElementById('cs-tag-filter-' + viewKey);
      var emptyEl = document.getElementById('cs-tag-filter-empty-' + viewKey);
      var searchInput = document.getElementById('cs-flow-search-' + viewKey);
      if (!grid || !bar) return;

      // .cs-card--presets-hub cards (Presets + one per template pack) carry
      // a "N looks" tag that's just their own item count, not a real
      // category — meaningless (and unlabeled, since the pack name is
      // already the card's own title, not repeated in the tag) once it
      // floats alone in this sidebar next to every other pack's own count.
      // Excluded from tag collection entirely, so they're also never
      // hidden by an unrelated filter — they're navigation, not content.
      var cards = Array.prototype.slice.call(grid.querySelectorAll('.cs-card'))
        .filter(function (card) { return !card.classList.contains('cs-card--presets-hub'); });
      if (!cards.length) return;

      // Collect tags + searchable text per card, and tag frequency across
      // all cards (name/desc used by the free-text search box below).
      // Tags are keyed by their English source (data-tag-src) — the filter,
      // icons and counts must not change meaning when the language does.
      // Only the chip label is translated, at render time.
      var I18N = window.NomadI18n;
      function tagLabel(tag) { return I18N && I18N.tField ? I18N.tField(tag) : tag; }
      function uiText(key, fallback) { return I18N && I18N.t ? I18N.t(key, fallback) : fallback; }

      var counts = {};
      var cardTagMap = cards.map(function (card) {
        var tags = Array.prototype.slice.call(card.querySelectorAll('.cs-card-tag-row .cs-tag'))
          .map(function (el) { return (el.getAttribute('data-tag-src') || el.textContent).trim(); })
          .filter(Boolean);
        tags.forEach(function (t) { counts[t] = (counts[t] || 0) + 1; });
        return { card: card, tags: tags };
      });

      // Searches the English and the on-screen (possibly translated) text
      // together, so a query works in either. Read on each keystroke rather
      // than cached, since the language can change after setup.
      function searchTextFor(entry) {
        var card = entry.card;
        var nameEl = card.querySelector('.cs-card-name');
        var descEl = card.querySelector('.cs-card-desc');
        return [
          nameEl ? nameEl.textContent + ' ' + (nameEl.getAttribute('data-i18n-literal') || '') : '',
          descEl ? descEl.textContent + ' ' + (descEl.getAttribute('data-i18n-literal') || '') : '',
          entry.tags.join(' '),
          entry.tags.map(tagLabel).join(' ')
        ].join(' ').toLowerCase();
      }
      var searchQuery = '';

      var allTags = Object.keys(counts).sort(function (a, b) {
        return a.localeCompare(b);
      });
      if (!allTags.length) return;

      var activeTags = new Set();
      var pending = new WeakMap(); // card -> { timeoutId, listener } for in-flight hide transitions

      function clearPending(card) {
        var p = pending.get(card);
        if (!p) return;
        if (p.timeoutId) clearTimeout(p.timeoutId);
        if (p.listener) card.removeEventListener('transitionend', p.listener);
        pending.delete(card);
      }

      var clearBtnId = 'cs-tag-filter-clear-' + viewKey;

      function renderChips() {
        // Same nav-item/nav-model-left/models-ready-text classes as the
        // app's own WORKSPACE/MODELS sidebar and Build's category nav —
        // reused as-is so this reads as the same list style everywhere.
        var html = allTags.map(function (tag) {
          var active = activeTags.has(tag);
          return '<button type="button" class="nav-item nav-item-btn nav-item-model' + (active ? ' active' : '') +
            '" data-tag="' + escHtml(tag) + '" aria-pressed="' + active + '">' +
            '<span class="nav-model-left">' + tagIconSvg(tag) + '<span>' + escHtml(tagLabel(tag)) + '</span></span>' +
            '<span class="models-ready-text">' + counts[tag] + '</span></button>';
        }).join('');
        if (activeTags.size) {
          html += '<button type="button" class="cs-tag-filter-clear" id="' + clearBtnId + '">' +
            escHtml(uiText('hub.sections.clearFilter', 'Clear ×')) + '</button>';
        }
        bar.innerHTML = '<p class="group-label">' + escHtml(uiText('hub.sections.filters', 'Filters')) +
          '</p><nav class="nav-block">' + html + '</nav>';
        if (window.lucide) window.lucide.createIcons();
        bar.hidden = false;
        // The left-hand collapse toggle only shows itself when a filter bar
        // is actually on screen, and this is the moment one appears —
        // csSyncThemeBtn can run before this on a view change, which would
        // otherwise leave the button hidden until the next view switch.
        if (typeof csSyncThemeBtn === 'function') csSyncThemeBtn();
      }

      function updateGroupBlocks() {
        var groupBlocks = grid.querySelectorAll('.cs-group-block');
        var firstVisible = true;
        groupBlocks.forEach(function (block) {
          // A card in this group is visible if it doesn't have cs-card--tag-out or cs-card--tag-hidden
          var hasVisible = false;
          var groupCards = block.querySelectorAll('.cs-card');
          for (var i = 0; i < groupCards.length; i++) {
            var c = groupCards[i];
            if (!c.classList.contains('cs-card--tag-out') && !c.classList.contains('cs-card--tag-hidden')) {
              hasVisible = true;
              break;
            }
          }
          block.hidden = !hasVisible;
          if (hasVisible) {
            block.style.marginTop = firstVisible ? '0' : '';
            firstVisible = false;
          }
        });
      }

      function applyFilter() {
        var visibleCount = 0;
        cardTagMap.forEach(function (entry) {
          var tagMatch = activeTags.size === 0 || entry.tags.some(function (t) { return activeTags.has(t); });
          var searchMatch = !searchQuery || searchTextFor(entry).indexOf(searchQuery) !== -1;
          var match = tagMatch && searchMatch;
          var card = entry.card;
          // Cancel any leftover listener/timeout from a previous, interrupted
          // hide-or-show pass — otherwise a stale transitionend can re-hide a
          // card right after it fades back in.
          clearPending(card);
          if (match) {
            visibleCount++;
            card.classList.remove('cs-card--tag-hidden');
            // Force reflow so the fade-in transition replays.
            void card.offsetWidth;
            card.classList.remove('cs-card--tag-out');
          } else {
            card.classList.add('cs-card--tag-out');
            var listener = function (ev) {
              if (ev && ev.target !== card) return;
              card.classList.add('cs-card--tag-hidden');
              clearPending(card);
            };
            var timeoutId = setTimeout(function () {
              // Fallback in case transitionend doesn't fire (e.g. reduced motion).
              if (card.classList.contains('cs-card--tag-out')) card.classList.add('cs-card--tag-hidden');
              clearPending(card);
            }, 220);
            card.addEventListener('transitionend', listener);
            pending.set(card, { timeoutId: timeoutId, listener: listener });
          }
        });
        updateGroupBlocks();
        if (emptyEl) emptyEl.hidden = visibleCount !== 0;
      }

      bar.addEventListener('click', function (e) {
        var clearBtn = e.target.closest('#' + clearBtnId);
        if (clearBtn) {
          activeTags.clear();
          renderChips();
          applyFilter();
          return;
        }
        var chip = e.target.closest('[data-tag]');
        if (!chip) return;
        var tag = chip.dataset.tag;
        // Exclusive: picking a tag replaces whatever was selected before —
        // clicking the already-active one just clears the filter.
        var wasActive = activeTags.has(tag);
        activeTags.clear();
        if (!wasActive) activeTags.add(tag);
        renderChips();
        applyFilter();
      });

      if (searchInput) {
        searchInput.addEventListener('input', function () {
          searchQuery = searchInput.value.trim().toLowerCase();
          applyFilter();
        });
      }

      // The dictionary loads asynchronously and can change later from the
      // Language panel — re-render the chips whenever one is applied.
      document.addEventListener('nomad-i18n-applied', renderChips);

      renderChips();
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', setup);
    } else {
      setup();
    }
  }

  initTagFilter('create');
  initTagFilter('refine');
  initTagFilter('mix');

  /* ── Subtle per-card gradient tint, grouped by primary tag (tag[0]) ─────
     Same logic across Create / Refine / Mix: every card's first tag (the
     "main" tag — model family for Refine/Edit flows, e.g. Flux2/Qwen, or
     the leading category tag elsewhere) is hashed to a fixed hue from a
     curated palette, so cards sharing a primary tag always share the same
     faint gradient — a lightweight visual grouping cue, independent of
     whatever grouping/filter mode is active. */
  (function initCardTint() {
    var PALETTE = [210, 16, 150, 265, 40, 285, 190, 340, 95, 55, 235, 5];
    var cache = {};

    function hueFor(key) {
      if (cache[key] !== undefined) return cache[key];
      var hash = 0;
      for (var i = 0; i < key.length; i++) {
        hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
      }
      var hue = PALETTE[hash % PALETTE.length];
      cache[key] = hue;
      return hue;
    }

    function setup() {
      var grids = ['cs-sub-grid-create', 'cs-sub-grid-refine', 'cs-sub-grid-mix']
        .map(function (id) { return document.getElementById(id); })
        .filter(Boolean);
      if (!grids.length) return;

      grids.forEach(function (grid) {
        var cards = Array.prototype.slice.call(grid.querySelectorAll('.cs-card'));
        cards.forEach(function (card) {
          var firstTag = card.querySelector('.cs-card-tag-row .cs-tag');
          // English source, so a card keeps its hue in every language.
          var key = firstTag ? (firstTag.getAttribute('data-tag-src') || firstTag.textContent).trim() : '';
          if (!key) return;
          card.style.setProperty('--cs-card-tint-h', hueFor(key));
          card.dataset.tintGroup = key;
        });
      });
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', setup);
    } else {
      setup();
    }
  })();

  /* ── Cinematic title: fade in "Nomad Studio" letter by letter ───────────
     Walks #cs-title's child nodes (plain "Nomad" text + the accent-colored
     <span>&nbsp;Studio</span>) and rewraps every character in its own
     inline-block span with a --i index, so nomad_studio.css can stagger
     each letter's fade-in via animation-delay: calc(var(--i) * Ns). Keeps
     the existing <span> (and its color-mix accent styling in CSS) intact —
     only the text nodes inside get split, the wrapping elements don't. */
  (function splitTitleIntoLetters() {
    var title = document.getElementById('cs-title');
    if (!title || title.dataset.csLettered) return;
    title.dataset.csLettered = '1';

    var counter = 0;

    function wrapTextNode(node) {
      var frag = document.createDocumentFragment();
      var text = node.textContent;
      for (var i = 0; i < text.length; i++) {
        var ch = text[i];
        var span = document.createElement('span');
        span.className = 'cs-letter';
        span.style.setProperty('--i', counter++);
        // Preserve spaces visually (a bare space in an inline-block span
        // can collapse) using a non-breaking space for whitespace chars.
        span.textContent = ch === ' ' ? ' ' : ch;
        frag.appendChild(span);
      }
      node.parentNode.replaceChild(frag, node);
    }

    function walk(el) {
      Array.prototype.slice.call(el.childNodes).forEach(function (node) {
        if (node.nodeType === Node.TEXT_NODE) {
          wrapTextNode(node);
        } else if (node.nodeType === Node.ELEMENT_NODE) {
          walk(node);
        }
      });
    }

    walk(title);
  })();

})();
