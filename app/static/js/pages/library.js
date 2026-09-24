/* Library page — browse reference Characters, Backgrounds, Styles and saved
   flow instances. Each category is a completely different data source, so
   this is a single-select category nav (not the multi-select OR-filter tag
   sidebar Create/Refine use), reusing the same visual treatment. */
(function () {
  'use strict';

  var nav     = document.getElementById('lib-category-nav');
  var grid    = document.getElementById('lib-grid');
  var empty   = document.getElementById('lib-empty');
  var createMain = document.querySelector('.cs-create-main');
  // #lib-styles-aside replaced the old horizontal #lib-styles-toolbar — same
  // show/hide-on-tab-switch role, now a vertical .nsc-inputs panel (model +
  // Advanced + generate/create + zoom) sitting left of the grid instead of
  // a bar above it.
  var toolbar = document.getElementById('lib-styles-aside');
  var templatesToolbar = document.getElementById('lib-templates-toolbar');
  var valuesPanel = document.getElementById('lib-template-values-panel');
  var valuesPanelTitle = document.getElementById('lib-template-values-panel-title');
  var valuesPanelHint = document.getElementById('lib-template-values-panel-hint');
  var valuesPanelBody = document.getElementById('lib-template-values-panel-body');
  var valuesPanelClose = document.getElementById('lib-template-values-panel-close');
  var searchInput = document.getElementById('lib-search');
  var templatesCount = document.getElementById('lib-templates-count');
  var depotToolbar = document.getElementById('lib-depot-toolbar');
  var depotDetailEl = document.getElementById('lib-depot-detail');
  var depotDetailId = null;
  // Depot detail's secondary panel (issue #57) — see library.html's
  // #lib-depot-aside. Populated by renderDepotDetail/selectDepotItem below.
  var depotAside = document.getElementById('lib-depot-aside');
  var depotAsideName = document.getElementById('lib-depot-aside-name');
  var depotAsideDesc = document.getElementById('lib-depot-aside-desc');
  var depotCountersEl = document.getElementById('lib-depot-counters');
  var depotItemDetailEl = document.getElementById('lib-depot-item-detail');
  var depotItemDetailMedia = document.getElementById('lib-depot-item-detail-media');
  var depotItemDetailCategory = document.getElementById('lib-depot-item-detail-category');
  var depotItemDetailCaption = document.getElementById('lib-depot-item-detail-caption');
  var depotItemDetailDate = document.getElementById('lib-depot-item-detail-date');
  var depotItemDetailOpen = document.getElementById('lib-depot-item-detail-open');
  // Floating round-button zoom widget (Album/Create's own .cs-card-zoom) —
  // visible whenever #lib-grid itself is the visible content, regardless of
  // which tab; hidden during Depot's own detail sub-view where the grid
  // isn't shown at all. See loadCategory/showDepotDetail/showDepotList.
  var gridZoomToolbar = document.getElementById('lib-grid-zoom-toolbar');
  var modelSelect = document.getElementById('lib-model-select');
  var breadcrumbCurrent = document.getElementById('lib-breadcrumb-current');
  // Extra "Depots >" crumb, shown only inside a depot's detail view — see
  // showDepotDetail/showDepotList. Doubles as the "back to list" affordance
  // instead of a separate button inside the aside.
  var breadcrumbDepots = document.getElementById('lib-breadcrumb-depots');
  var breadcrumbDepotsArrow = document.getElementById('lib-breadcrumb-depots-arrow');
  if (!nav || !grid) return;

  /* ── Advanced: quantization + resolution ──────────────────────────────────
     Same widgets/CSS the real Create flow uses (flow-quantization.js's
     buildQuantizationList, flow-step-workflow-params.js's SD/MD/HD resolution
     picker) but reimplemented standalone here instead of importing those
     files directly — they read/write page-owning globals (selectedSeed,
     loadSavedParams(), etc.) declared in flow-state.js, which this page
     doesn't load. Kept deliberately simple: no aspect-ratio picker, just a
     fixed 2:3 portrait (matches the app's existing r2x3 preset) scaled by
     SD/MD/HD, since that's the only ratio this page's preview shots ever
     used (previously hardcoded to 640×960, i.e. r2x3's own "sd" tier). */
  var RES_PRESETS = {
    sd: { w: 640, h:  960 },
    md: { w: 832, h: 1216 },
    hd: { w: 960, h: 1408 },
  };
  var selectedResolution = 'md';
  var selectedQuantizationId = null;
  var selectedQuantizationValues = null;
  // Only true once the user actually clicks a quantization pill — until
  // then, generateStyleImageForModel sends no advancedValues override at
  // all, same as before this panel existed, so the workflow's own baked-in
  // default quantization is used. Auto-selecting options[0] as "selected"
  // for the pill UI's own highlight state is fine; silently including it in
  // every generation call is not — that would swap every style's quality
  // preset out from under the user without them ever opening Advanced.
  var quantizationTouched = false;
  var advancedToggle = document.getElementById('lib-advanced-toggle');
  var advancedPanel  = document.getElementById('lib-advanced-panel');
  var quantBlock = document.getElementById('lib-quant-block');
  var quantList  = document.getElementById('lib-quant-list');
  var resBtns    = document.querySelectorAll('#lib-res-btns .nsc-res-btn');

  if (advancedToggle && advancedPanel) {
    advancedToggle.addEventListener('click', function () {
      var open = advancedPanel.hidden;
      advancedPanel.hidden = !open;
      advancedToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  function updateResSubs() {
    ['sd', 'md', 'hd'].forEach(function (r) {
      var sub = document.getElementById('lib-res-sub-' + r);
      if (sub) sub.textContent = RES_PRESETS[r].w + '×' + RES_PRESETS[r].h;
    });
  }
  updateResSubs();

  resBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      selectedResolution = btn.dataset.res;
      resBtns.forEach(function (b) {
        var a = b === btn;
        b.classList.toggle('is-active', a);
        b.setAttribute('aria-pressed', a ? 'true' : 'false');
      });
    });
  });

  /* ── Image format + output copy ──────────────────────────────────────────
     Every image saved for a style (Generate images, or an uploaded one) is
     stored per model in PNG or WebP. With an output subfolder set, a copy is
     also written to <output>/<subfolder>/<model>/<style-key>.<ext> — stable
     names a style pack's images can be collected from (styles_routes.py
     update_style_model_image). Remembered per browser. */
  var FORMAT_KEY = 'nomad-build-style-image-format';
  var EXPORT_KEY = 'nomad-build-style-export-subfolder';
  var formatBtns = document.querySelectorAll('#lib-format-btns .nsc-res-btn');
  var exportInput = document.getElementById('lib-export-subfolder');
  var selectedFormat = 'png';
  try { selectedFormat = localStorage.getItem(FORMAT_KEY) === 'webp' ? 'webp' : 'png'; } catch (_) {}
  try { if (exportInput) exportInput.value = localStorage.getItem(EXPORT_KEY) || ''; } catch (_) {}

  function syncFormatBtns() {
    formatBtns.forEach(function (b) {
      var a = b.dataset.format === selectedFormat;
      b.classList.toggle('is-active', a);
      b.setAttribute('aria-pressed', a ? 'true' : 'false');
    });
  }
  syncFormatBtns();
  formatBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      selectedFormat = btn.dataset.format === 'webp' ? 'webp' : 'png';
      try { localStorage.setItem(FORMAT_KEY, selectedFormat); } catch (_) {}
      syncFormatBtns();
    });
  });
  if (exportInput) {
    exportInput.addEventListener('input', function () {
      try { localStorage.setItem(EXPORT_KEY, exportInput.value.trim()); } catch (_) {}
    });
  }

  function imageSaveOptions() {
    return {
      format: selectedFormat,
      exportSubfolder: exportInput ? exportInput.value.trim() : '',
    };
  }

  function renderQuantizationOptions(quant) {
    var options = (quant && Array.isArray(quant.options)) ? quant.options : [];
    var targetKey = quant ? String(quant.targetKey || '') : '';
    var clipTargetKey = quant ? String(quant.clipTargetKey || '') : '';
    // Fresh model — any previous pick pointed at a different workflow's
    // node keys and would silently no-op (or worse, mismatch) if reused.
    quantizationTouched = false;

    if (!quantList) return;
    if (!options.length || !targetKey) {
      selectedQuantizationId = null;
      selectedQuantizationValues = null;
      quantList.innerHTML = '';
      if (quantBlock) quantBlock.style.display = 'none';
      return;
    }
    if (quantBlock) quantBlock.style.display = '';

    function valuesFor(option) {
      var values = {};
      values[targetKey] = option.unet_name;
      if (clipTargetKey && option.clip_name) values[clipTargetKey] = option.clip_name;
      return values;
    }

    var initialOpt = options[0];
    selectedQuantizationId = initialOpt.id;
    selectedQuantizationValues = valuesFor(initialOpt);

    quantList.innerHTML = '';
    options.forEach(function (opt) {
      var btn = document.createElement('button');
      btn.className = 'nsc-quality-btn' + (opt.id === selectedQuantizationId ? ' is-active' : '');
      btn.type = 'button';
      btn.setAttribute('role', 'radio');
      btn.setAttribute('data-quantization-id', opt.id);
      btn.setAttribute('aria-checked', opt.id === selectedQuantizationId ? 'true' : 'false');
      btn.innerHTML =
        '<span class="nsc-quality-dot"></span>' +
        '<span class="nsc-quality-copy"><strong>' + escHtml(opt.label) + '</strong></span>';
      (function (option) {
        btn.addEventListener('click', function () {
          selectedQuantizationId = option.id;
          selectedQuantizationValues = valuesFor(option);
          quantizationTouched = true;
          quantList.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
            var a = b === btn;
            b.classList.toggle('is-active', a);
            b.setAttribute('aria-checked', a ? 'true' : 'false');
          });
        });
      }(opt));
      quantList.appendChild(btn);
    });
  }

  function loadModelAnalysis(modelId) {
    if (!modelId) { renderQuantizationOptions(null); return; }
    fetch('/api/models/imports/' + encodeURIComponent(modelId))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var record = (data && data.import) || {};
        var analysis = record.analysis || {};
        renderQuantizationOptions(analysis.quantization || null);
      })
      .catch(function (err) {
        console.error('[Library] Failed to load model analysis:', err);
        renderQuantizationOptions(null);
      });
  }

  // Style images are served full-res by default; request a small resized
  // JPEG for the grid thumbnail instead (see styles_routes.py's `?w=`
  // support) — the full-res version is only needed in the edit modal.
  function styleThumbUrl(url) {
    if (!url || url.indexOf('/api/styles/image/') !== 0) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'w=300';
  }

  function escHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  // Same indeterminate spinner used on generating cards elsewhere in the app
  // (flow-generation.js's addGeneratingCard) — reused as-is so this reads as
  // the same "generating" state everywhere, not a one-off Library spinner.
  var RING_SVG =
    '<svg class="nsc-ring nsc-ring--indeterminate" viewBox="0 0 44 44" aria-hidden="true">' +
    '<circle class="nsc-ring-bg" cx="22" cy="22" r="18"/>' +
    '<circle class="nsc-ring-fill" cx="22" cy="22" r="18"/>' +
    '</svg>';

  // Tin-can icon for Depot — no matching Lucide icon, drawn by hand instead.
  var CAN_ICON_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ' +
    'stroke-linecap="round" stroke-linejoin="round" class="nav-icon" aria-hidden="true">' +
    '<ellipse cx="12" cy="5" rx="7" ry="2.5"/>' +
    '<path d="M5 5v14"/>' +
    '<path d="M19 5v14"/>' +
    '<path d="M5 19a7 2.5 0 0 0 14 0"/>' +
    '<path d="M5 11a7 2.5 0 0 0 14 0"/>' +
    '</svg>';

  var CATEGORIES = [
    {
      id: 'characters', label: 'Characters', icon: 'user',
      endpoint: '/api/characters', dataKey: 'characters',
      imageUrl: function (it) { return '/static/images/characters/' + encodeURIComponent(it.keyword) + '.png'; },
      name: function (it) { return it.keyword || it.description || 'Untitled'; },
      note: function (it) { return it.description || ''; },
      // Click-to-edit/delete (see openItemEditModal) — apiBase names the
      // singular resource path (/api/characters/<keyword>).
      editable: true, apiBase: '/api/characters', itemKey: 'character',
    },
    {
      id: 'backgrounds', label: 'Backgrounds', icon: 'image',
      endpoint: '/api/backgrounds', dataKey: 'backgrounds',
      imageUrl: function (it) { return '/static/images/backgrounds/' + encodeURIComponent(it.keyword) + '.png'; },
      name: function (it) { return it.keyword || it.description || 'Untitled'; },
      note: function (it) { return it.description || ''; },
      editable: true, apiBase: '/api/backgrounds', itemKey: 'background',
    },
    {
      id: 'styles', label: 'Styles', icon: 'palette',
      endpoint: function () { return '/api/styles' + (selectedModelId ? '?model=' + encodeURIComponent(selectedModelId) : ''); },
      dataKey: 'styles',
      imageUrl: function (it) { return it.has_image ? it.image_url : ''; },
      name: function (it) { return it.name || 'Untitled'; },
      note: function (it) { return it.prompt || ''; },
    },
    {
      // Templates has no card grid — the sidebar tree (Pack -> Template)
      // *is* the picker; selecting a leaf opens Edit Template directly.
      id: 'templates', label: 'Templates', icon: 'layout-template',
      endpoint: '/api/template-packs', dataKey: 'templatePacks',
    },
    {
      id: 'flows', label: 'Flows', icon: 'workflow',
      endpoint: '/api/library/flows', dataKey: 'flows',
      imageUrl: function (it) {
        var url = it.data && Array.isArray(it.data.images) && it.data.images[0];
        if (!url) return '';
        return url.indexOf('/api/images/') === 0 ? url + '/thumb?w=300' : url;
      },
      name: function (it) { return it.label || it.type || 'Untitled'; },
      note: function (it) { return it.prompt || ''; },
    },
    {
      // Depot: a named set of backgrounds, characters, images and flows
      // tied to one story/idea — always private to whoever created it (see
      // depot_service.py's visible_to: no shared/global scope, unlike
      // Sessions). Creation-only for now (name + description); associating
      // actual content comes later.
      id: 'depot', label: 'Depots', icon: 'archive', iconSvg: CAN_ICON_SVG,
      endpoint: '/api/depots', dataKey: 'depots',
      imageUrl: function () { return ''; },
      name: function (it) { return it.name || 'Untitled Depot'; },
      note: function (it) { return it.description || ''; },
    },
  ];

  var counts = {};

  var LIB_ACTIVE_TAB_KEY = 'oj-library-active-tab-v1';
  function getStoredActiveId() {
    try {
      var stored = localStorage.getItem(LIB_ACTIVE_TAB_KEY);
      if (stored && CATEGORIES.some(function (c) { return c.id === stored; })) return stored;
    } catch (_) {}
    return CATEGORIES[0].id;
  }
  var activeId = getStoredActiveId();

  // Style categories are free text, often "Group/Sub" (e.g. "Comic/Dark",
  // "Comic/Marvel") — grouped here by the part before the first "/" so the
  // sidebar tree shows one "Comic" node with its variants nested under it,
  // instead of a long flat list repeating "Comic/" over and over. Categories
  // with no "/" (e.g. "anime") have no group and list as plain leaves.
  // Not persisted across reload (only the active tab is, see item 3 above).
  var styleCategoryTree = { flatNames: [], groups: [] };
  var selectedStyleCategory = ''; // '' = All; a group name; or a full "Group/Sub" string
  var expandedStyleGroups = {};
  var allStyleItems = [];
  // Re-clicking the "Styles" nav item while it's already the active tab
  // collapses the category tree instead of doing nothing — same
  // click-to-close affordance an accordion header gets. Reset to open
  // whenever Styles becomes active from a different tab (loadCategory).
  var stylesTreeOpen = true;

  // Templates group by "theme" (e.g. "90s Smalltown") exactly like Styles
  // group by category — same free-text "Group/Sub" convention, though in
  // practice theme names are flat. Selecting a theme filters the grid to
  // that theme's templates (cards); clicking a card opens Edit Template.
  var templateThemeTree = { flatNames: [], groups: [] };
  // Build-wide search (#lib-search) — applies to whichever category is
  // open, on top of the Styles category / Templates theme selection.
  var searchQuery = '';
  var activeItems = []; // every item of the open category, unfiltered
  var selectedTemplateTheme = ''; // '' = All; a group name; or a full "Group/Sub" string
  var expandedTemplateThemeGroups = {};
  // Same click-to-close accordion behavior as stylesTreeOpen above.
  var templatesTreeOpen = true;
  var allTemplateItems = [];

  function deriveTemplateThemeTree(items) {
    var flatSet = {};
    var groupMap = {};
    items.forEach(function (it) {
      var c = (it.theme || '').trim();
      if (!c) return;
      var slash = c.indexOf('/');
      if (slash === -1) {
        flatSet[c] = true;
      } else {
        var group = c.slice(0, slash);
        var sub = c.slice(slash + 1);
        if (!groupMap[group]) groupMap[group] = {};
        groupMap[group][sub] = c;
      }
    });
    var groupNames = Object.keys(groupMap).sort(function (a, b) { return a.localeCompare(b); });
    var groups = groupNames.map(function (g) {
      var subNames = Object.keys(groupMap[g]).sort(function (a, b) { return a.localeCompare(b); });
      return {
        name: g,
        subs: subNames.map(function (s) { return { label: s, full: groupMap[g][s] }; }),
      };
    });
    var flatNames = Object.keys(flatSet).sort(function (a, b) { return a.localeCompare(b); });
    return { flatNames: flatNames, groups: groups };
  }

  function deriveStyleCategoryTree(items) {
    var flatSet = {};
    var groupMap = {};
    items.forEach(function (it) {
      var c = (it.category || '').trim();
      if (!c) return;
      var slash = c.indexOf('/');
      if (slash === -1) {
        flatSet[c] = true;
      } else {
        var group = c.slice(0, slash);
        var sub = c.slice(slash + 1);
        if (!groupMap[group]) groupMap[group] = {};
        groupMap[group][sub] = c;
      }
    });
    var groupNames = Object.keys(groupMap).sort(function (a, b) { return a.localeCompare(b); });
    var groups = groupNames.map(function (g) {
      var subNames = Object.keys(groupMap[g]).sort(function (a, b) { return a.localeCompare(b); });
      return {
        name: g,
        subs: subNames.map(function (s) { return { label: s, full: groupMap[g][s] }; }),
      };
    });
    var flatNames = Object.keys(flatSet).sort(function (a, b) { return a.localeCompare(b); });
    return { flatNames: flatNames, groups: groups };
  }

  // A selection can be a flat leaf, a group name (matches the group itself
  // plus every "Group/..." under it), or one exact "Group/Sub" string.
  function filterItemsForDisplay(id, items) {
    if (id === 'styles' && selectedStyleCategory) {
      var sel = selectedStyleCategory;
      return items.filter(function (it) {
        var c = (it.category || '').trim();
        return c === sel || c.indexOf(sel + '/') === 0;
      });
    }
    if (id === 'templates') {
      var out = items;
      if (selectedTemplateTheme) {
        var selTheme = selectedTemplateTheme;
        out = out.filter(function (it) {
          var c = (it.theme || '').trim();
          return c === selTheme || c.indexOf(selTheme + '/') === 0;
        });
      }
      return filterBySearch(id, out);
    }
    return filterBySearch(id, items);
  }

  // Text a card can be found by: its own name/description plus whatever
  // prompt-ish fields the category carries, in English AND as shown on
  // screen (style-pack names/categories translate via tField) — same
  // "either language works" rule as the hubs' .cs-flow-search.
  var SEARCH_FIELDS = ['keyword', 'name', 'label', 'type', 'description', 'category', 'theme', 'pack',
                       'template', 'prompt', 'prefix', 'suffix'];
  function searchTextFor(id, it) {
    var cat = CATEGORIES.find(function (c) { return c.id === id; });
    var parts = SEARCH_FIELDS.map(function (k) { return typeof it[k] === 'string' ? it[k] : ''; });
    if (cat && cat.name) parts.push(cat.name(it));
    if (cat && cat.note) parts.push(cat.note(it));
    var tf = window.NomadI18n && window.NomadI18n.tField;
    if (tf) {
      if (it.name) parts.push(tf(it.name));
      if (it.category) {
        parts.push(tf(it.category));
        it.category.split('/').forEach(function (seg) { parts.push(tf(seg)); });
      }
    }
    return parts.join(' ').toLowerCase();
  }

  // Every word must match somewhere ("anime retro" finds "Retro VHS Anime").
  function filterBySearch(id, items) {
    var words = searchQuery.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return items;
    return items.filter(function (it) {
      var hay = searchTextFor(id, it);
      return words.every(function (w) { return hay.indexOf(w) !== -1; });
    });
  }

  // Typing re-filters the already-loaded list in place; nothing is
  // re-fetched. Cheap enough (2274 templates, a few hundred styles) to run
  // on every keystroke.
  if (searchInput) {
    searchInput.addEventListener('input', function () {
      searchQuery = searchInput.value || '';
      var cat = CATEGORIES.find(function (c) { return c.id === activeId; });
      if (cat && !depotDetailId) renderGrid(cat, filterItemsForDisplay(activeId, activeItems));
    });
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && searchInput.value) {
        searchInput.value = '';
        searchInput.dispatchEvent(new Event('input'));
      }
    });
  }

  function renderNav() {
    var items = CATEGORIES.map(function (cat) {
      var active = cat.id === activeId;
      var count = counts[cat.id];
      // Same nav-item/nav-model-left/models-ready-text classes as the app's
      // own WORKSPACE/MODELS sidebar (layout/base.html) — reused as-is so
      // this reads as the same list style, not a lookalike.
      var chip = '<button type="button" class="nav-item nav-item-btn nav-item-model' + (active ? ' active' : '') +
        '" data-cat="' + cat.id + '" role="tab" aria-selected="' + active + '">' +
        '<span class="nav-model-left">' +
        (cat.iconSvg || '<i data-lucide="' + cat.icon + '" class="nav-icon" aria-hidden="true"></i>') +
        '<span>' + escHtml(cat.label) + '</span>' +
        '</span>' +
        (typeof count === 'number' ? '<span class="models-ready-text">' + count + '</span>' : '') +
        '</button>';
      if (cat.id === 'styles' && active && stylesTreeOpen && (styleCategoryTree.flatNames.length || styleCategoryTree.groups.length)) {
        chip += '<div class="lib-style-cat-tree" role="group" aria-label="Style categories">' +
          '<button type="button" class="lib-style-cat-tree-item' + (selectedStyleCategory === '' ? ' is-active' : '') + '" data-style-cat="">All</button>' +
          styleCategoryTree.flatNames.map(function (name) {
            return '<button type="button" class="lib-style-cat-tree-item' + (selectedStyleCategory === name ? ' is-active' : '') + '" data-style-cat="' + escHtml(name) + '">' + trLit(name) + '</button>';
          }).join('') +
          styleCategoryTree.groups.map(function (g) {
            var expanded = !!expandedStyleGroups[g.name];
            return '<div class="lib-style-cat-group' + (expanded ? ' is-expanded' : '') + '">' +
              '<button type="button" class="lib-style-cat-group-toggle' + (selectedStyleCategory === g.name ? ' is-active' : '') + '" data-style-group="' + escHtml(g.name) + '">' +
                '<svg class="lib-style-cat-group-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>' +
                trLit(g.name) +
              '</button>' +
              (expanded ? '<div class="lib-style-cat-group-children">' +
                g.subs.map(function (s) {
                  return '<button type="button" class="lib-style-cat-tree-item' + (selectedStyleCategory === s.full ? ' is-active' : '') + '" data-style-cat="' + escHtml(s.full) + '">' + trLit(s.label) + '</button>';
                }).join('') +
              '</div>' : '') +
            '</div>';
          }).join('') +
        '</div>';
      }
      if (cat.id === 'templates' && active && templatesTreeOpen && (templateThemeTree.flatNames.length || templateThemeTree.groups.length)) {
        chip += '<div class="lib-template-cat-tree" role="group" aria-label="Template themes">' +
          '<button type="button" class="lib-template-cat-tree-item' + (selectedTemplateTheme === '' ? ' is-active' : '') + '" data-template-theme="">All</button>' +
          templateThemeTree.flatNames.map(function (name) {
            return '<button type="button" class="lib-template-cat-tree-item' + (selectedTemplateTheme === name ? ' is-active' : '') + '" data-template-theme="' + escHtml(name) + '">' + escHtml(name) + '</button>';
          }).join('') +
          templateThemeTree.groups.map(function (g) {
            var expanded = !!expandedTemplateThemeGroups[g.name];
            return '<div class="lib-template-cat-group' + (expanded ? ' is-expanded' : '') + '">' +
              '<button type="button" class="lib-template-cat-group-toggle' + (selectedTemplateTheme === g.name ? ' is-active' : '') + '" data-template-theme-group="' + escHtml(g.name) + '">' +
                '<svg class="lib-style-cat-group-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>' +
                '<span>' + escHtml(g.name) + '</span>' +
              '</button>' +
              (expanded ? '<div class="lib-template-cat-group-children">' +
                g.subs.map(function (s) {
                  return '<button type="button" class="lib-template-cat-tree-item' + (selectedTemplateTheme === s.full ? ' is-active' : '') + '" data-template-theme="' + escHtml(s.full) + '">' + escHtml(s.label) + '</button>';
                }).join('') +
              '</div>' : '') +
            '</div>';
          }).join('') +
        '</div>';
      }
      return chip;
    }).join('');
    nav.innerHTML = '<p class="group-label">Build</p><nav class="nav-block">' + items + '</nav>';
    if (window.lucide) window.lucide.createIcons();
  }

  // Style cards use the same full-bleed photo treatment as the Refine
  // Presets/Pack cards (.rp-card: photo + bottom scrim with name/desc) —
  // see the CSS comment above .lib-style-card-outer in nomad_studio.css for
  // why some old class names (.lib-style-card-img-wrap etc.) are kept
  // alongside the new .rp-card* ones (existing JS queries by those names).
  // Style names and categories that come from an installed style pack are
  // translated by the package's own texts (package_service.texts_for →
  // flowLabels). data-i18n-literal keeps the English original so a later
  // language switch (i18n.js applyStrings) re-translates in place.
  function tr(key, fallback) {
    return (window.NomadI18n && window.NomadI18n.t) ? window.NomadI18n.t(key, fallback) : fallback;
  }

  function trLit(text) {
    var shown = (window.NomadI18n && window.NomadI18n.tField) ? window.NomadI18n.tField(text) : text;
    return '<span data-i18n-literal="' + escHtml(text) + '">' + escHtml(shown) + '</span>';
  }

  function styleCardHtml(item) {
    var img = item.has_image ? styleThumbUrl(item.image_url) : '';
    var name = item.name || 'Untitled';
    var category = item.category || '';
    var prompt = item.prompt || '';
    var imgBlock = img
      ? '<img src="' + escHtml(img) + '" alt="" loading="lazy" decoding="async" onerror="this.closest(\'.lib-style-card-img-wrap\').classList.add(\'lib-style-card-img-wrap--fallback\')">'
      : '';
    return (
      '<div class="lib-style-card-outer">' +
        '<div class="rp-card lib-style-card lib-card--editable" data-lib-edit-id="' + escHtml(String(item.id)) + '">' +
          '<div class="rp-card-media lib-style-card-img-wrap' + (img ? '' : ' lib-style-card-img-wrap--fallback') + '">' +
            imgBlock +
            '<i data-lucide="palette" class="lib-style-card-fallback-icon" aria-hidden="true"></i>' +
          '</div>' +
          '<div class="rp-card-body">' +
            '<p class="rp-card-name">' + trLit(name) + '</p>' +
            (category ? '<p class="lib-style-card-category">' + trLit(category) + '</p>' : '') +
            (prompt ? '<p class="rp-card-desc">' + escHtml(prompt) + '</p>' : '') +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  // Template cards show one template's derived reference still — a click
  // opens Edit Template directly, same as Style cards do. Same .rp-card
  // structure as styleCardHtml (image on top, name/theme/desc below in a
  // real card body) instead of the old .nss-card "numbered comparison
  // strip" look, which read as a raw photo with a title bar slapped on
  // top — no card chrome, no description, inconsistent with every other
  // Build grid (Backgrounds/Characters/Styles all use .rp-card or .cs-card).
  function templateCardHtml(item) {
    var first = item.images && item.images[0];
    var img = first && first.filename ? '/static/images/' + first.filename : '';
    var name = item.name || 'Untitled';
    var theme = item.theme || '';
    var prompt = (first && first.prompt) || item.template || '';
    var imgBlock = img
      ? '<img src="' + escHtml(img) + '" alt="" loading="lazy" decoding="async" onerror="this.closest(\'.lib-style-card-img-wrap\').classList.add(\'lib-style-card-img-wrap--fallback\')">'
      : '';
    return (
      '<div class="lib-style-card-outer">' +
        '<div class="rp-card lib-style-card lib-card--template-editable" data-lib-template-edit-id="' + escHtml(String(item.id)) + '">' +
          '<div class="rp-card-media lib-style-card-img-wrap' + (img ? '' : ' lib-style-card-img-wrap--fallback') + '">' +
            imgBlock +
            '<i data-lucide="layout-template" class="lib-style-card-fallback-icon" aria-hidden="true"></i>' +
          '</div>' +
          '<div class="rp-card-body">' +
            '<p class="rp-card-name">' + escHtml(name) + '</p>' +
            (theme ? '<p class="lib-style-card-category">' + escHtml(theme) + '</p>' : '') +
            (prompt ? '<p class="rp-card-desc">' + escHtml(prompt) + '</p>' : '') +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  // Same full-bleed .rp-card treatment as Style/Template/Album cards (see
  // styleCardHtml's comment) — shows the depot's most-recently-added item
  // image if it has one, so a Depot with content reads exactly like an
  // Album card, not like a plain icon tile. No animation/cycling: a static
  // single image (or the archive-icon fallback if the depot is empty).
  function depotListCardHtml(depot) {
    var items = Array.isArray(depot.items) ? depot.items : [];
    var thumb = items.length ? items[items.length - 1] : null;
    var img = thumb && thumb.url ? thumb.url : '';
    var imgBlock = img
      ? '<img src="' + escHtml(img) + '" alt="" loading="lazy" decoding="async" onerror="this.closest(\'.lib-style-card-img-wrap\').classList.add(\'lib-style-card-img-wrap--fallback\')">'
      : '';
    return (
      '<div class="lib-style-card-outer">' +
        '<div class="rp-card lib-style-card lib-card--depot-open" data-lib-depot-open-id="' + escHtml(String(depot.id)) + '">' +
          '<button type="button" class="lib-depot-card-edit-btn" data-lib-depot-edit-id="' + escHtml(String(depot.id)) + '" aria-label="Edit Depot">' +
            '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>' +
          '</button>' +
          '<div class="rp-card-media lib-style-card-img-wrap' + (img ? '' : ' lib-style-card-img-wrap--fallback') + '">' +
            imgBlock +
            '<i data-lucide="archive" class="lib-style-card-fallback-icon" aria-hidden="true"></i>' +
          '</div>' +
          '<div class="rp-card-body">' +
            '<p class="rp-card-name">' + escHtml(depot.name || 'Untitled Depot') + '</p>' +
            (depot.description ? '<p class="rp-card-desc">' + escHtml(depot.description) + '</p>' : '') +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  // Same full-bleed .rp-card treatment as Style/Template/Depot cards (see
  // styleCardHtml's comment) — replaces the old .cs-card "family/category"
  // tile look (small square icon top-left, plain text block below) that
  // Characters/Backgrounds/Flows still had, the last holdouts of that
  // older style in this page's grids.
  function photoCardHtml(cat, item) {
    var img = cat.imageUrl(item);
    var name = cat.name(item);
    var note = cat.note(item);
    var imgBlock = img
      ? '<img src="' + escHtml(img) + '" alt="" loading="lazy" decoding="async" onerror="this.closest(\'.lib-style-card-img-wrap\').classList.add(\'lib-style-card-img-wrap--fallback\')">'
      : '';
    // Distinct class from Style's own .lib-card--editable (that one opens
    // the Style edit modal by numeric id, not a keyword — reusing it here
    // would misroute the click) — see openItemEditModal's click delegate.
    var cardClass = 'rp-card lib-style-card' + (cat.editable ? ' lib-card--item-editable' : '');
    var cardAttrs = cat.editable
      ? ' data-lib-item-edit-keyword="' + escHtml(String(item.keyword || '')) + '" data-lib-item-edit-cat="' + escHtml(cat.id) + '"'
      : '';
    return (
      '<div class="lib-style-card-outer">' +
        '<div class="' + cardClass + '"' + cardAttrs + '>' +
          '<div class="rp-card-media lib-style-card-img-wrap' + (img ? '' : ' lib-style-card-img-wrap--fallback') + '">' +
            imgBlock +
            '<i data-lucide="' + cat.icon + '" class="lib-style-card-fallback-icon" aria-hidden="true"></i>' +
          '</div>' +
          '<div class="rp-card-body">' +
            '<p class="rp-card-name">' + escHtml(name) + '</p>' +
            (note ? '<p class="rp-card-desc">' + escHtml(note) + '</p>' : '') +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function cardHtml(cat, item) {
    if (cat.id === 'styles') return styleCardHtml(item);
    if (cat.id === 'templates') return templateCardHtml(item);
    if (cat.id === 'depot') return depotListCardHtml(item);
    return photoCardHtml(cat, item);
  }

  var currentItems = [];

  // Cards are appended a page at a time as the sentinel below the grid comes
  // into view. Building all of them up front was fine for 131 characters and
  // ruinous for 2274 templates: 28k DOM nodes, 3.3MB of HTML, and — because
  // no card image was lazy — the browser fetching every full-size thumbnail.
  // Measured on the Templates tab before this: 97.6MB pulled down while seven
  // images were actually on screen, the slowest single one taking 7.5s.
  var GRID_PAGE = 60;
  var _gridCat = null;
  var _gridPending = [];
  var _gridObserver = null;
  var _gridSentinel = null;

  function _gridAppendPage() {
    if (!_gridPending.length) {
      if (_gridSentinel) _gridSentinel.hidden = true;
      return;
    }
    var page = _gridPending.splice(0, GRID_PAGE);
    grid.insertAdjacentHTML('beforeend', page.map(function (it) {
      return cardHtml(_gridCat, it);
    }).join(''));
    if (window.lucide) window.lucide.createIcons();
    if (_gridSentinel) {
      grid.appendChild(_gridSentinel);          // keep it last
      _gridSentinel.hidden = !_gridPending.length;
    }
  }

  function _ensureGridSentinel() {
    if (_gridSentinel) return;
    _gridSentinel = document.createElement('div');
    _gridSentinel.className = 'lib-grid-sentinel';
    _gridSentinel.setAttribute('aria-hidden', 'true');
    if (typeof IntersectionObserver === 'function') {
      _gridObserver = new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; })) _gridAppendPage();
      // #lib-grid is itself the scrolling element (overflow-y: auto), not the
      // page — observing against the viewport never fired, so the grid stayed
      // stuck on its first page no matter how far you scrolled.
      }, { root: grid, rootMargin: '600px' });
      _gridObserver.observe(_gridSentinel);
    }
  }

  function renderGrid(cat, items) {
    currentItems = items;
    if (!items.length) {
      grid.style.display = 'none';
      empty.hidden = false;
      empty.textContent = searchQuery.trim()
        ? tr('build.noMatch', 'Nothing matches your search.')
        : 'No ' + cat.label.toLowerCase() + ' saved yet.';
      return;
    }
    empty.hidden = true;
    grid.style.display = '';
    grid.innerHTML = '';
    if (templatesCount) {
      templatesCount.textContent = cat.id === 'templates'
        ? items.length + (items.length === 1 ? ' template' : ' templates')
        : '';
    }
    _gridCat = cat;
    _gridPending = items.slice();
    _ensureGridSentinel();
    _gridAppendPage();
    // Without an IntersectionObserver there is nothing to trigger the rest,
    // so fall back to rendering everything.
    if (!_gridObserver) while (_gridPending.length) _gridAppendPage();
  }

  /* ── Reference image viewer ───────────────────────────────────────────────
     Full-size look at one of the selected template's reference stills, with
     its own prompt text and prev/next between the whole set — same idea as
     a "create"-style image lightbox, scoped to this page's own markup. */
  var templateLightbox         = document.getElementById('lib-template-lightbox');
  var templateLightboxBackdrop = document.getElementById('lib-template-lightbox-backdrop');
  var templateLightboxClose    = document.getElementById('lib-template-lightbox-close');
  var templateLightboxPrev     = document.getElementById('lib-template-lightbox-prev');
  var templateLightboxNext     = document.getElementById('lib-template-lightbox-next');
  var templateLightboxImg      = document.getElementById('lib-template-lightbox-img');
  var templateLightboxCounter  = document.getElementById('lib-template-lightbox-counter');
  var templateLightboxPrompt   = document.getElementById('lib-template-lightbox-prompt');
  var templateLightboxImages = [];
  var templateLightboxIndex = 0;

  function renderTemplateLightbox() {
    var img = templateLightboxImages[templateLightboxIndex];
    if (!img) return;
    templateLightboxImg.src = img.filename ? '/static/images/' + img.filename : '';
    templateLightboxImg.alt = '';
    templateLightboxCounter.textContent = (templateLightboxIndex + 1) + ' / ' + templateLightboxImages.length;
    templateLightboxPrompt.textContent = img.prompt || '';
  }

  function openTemplateLightbox(index) {
    if (!templateLightbox || !editingTemplateId) return;
    var item = currentItems.find(function (it) { return String(it.id) === String(editingTemplateId); });
    var images = item && Array.isArray(item.images) ? item.images : [];
    if (!images.length) return;
    templateLightboxImages = images;
    templateLightboxIndex = Math.max(0, Math.min(index, images.length - 1));
    renderTemplateLightbox();
    templateLightbox.classList.remove('is-closed');
    templateLightbox.setAttribute('aria-hidden', 'false');
  }

  function closeTemplateLightbox() {
    if (!templateLightbox) return;
    templateLightbox.classList.add('is-closed');
    templateLightbox.setAttribute('aria-hidden', 'true');
  }

  function stepTemplateLightbox(delta) {
    if (!templateLightboxImages.length) return;
    templateLightboxIndex = (templateLightboxIndex + delta + templateLightboxImages.length) % templateLightboxImages.length;
    renderTemplateLightbox();
  }

  if (templateLightboxClose) templateLightboxClose.addEventListener('click', closeTemplateLightbox);
  if (templateLightboxBackdrop) templateLightboxBackdrop.addEventListener('click', closeTemplateLightbox);
  if (templateLightboxPrev) templateLightboxPrev.addEventListener('click', function () { stepTemplateLightbox(-1); });
  if (templateLightboxNext) templateLightboxNext.addEventListener('click', function () { stepTemplateLightbox(1); });

  document.addEventListener('keydown', function (e) {
    if (!templateLightbox || templateLightbox.classList.contains('is-closed')) return;
    if (e.key === 'Escape') closeTemplateLightbox();
    else if (e.key === 'ArrowLeft') stepTemplateLightbox(-1);
    else if (e.key === 'ArrowRight') stepTemplateLightbox(1);
  });

  function fetchItems(cat) {
    if (cat.comingSoon) {
      counts[cat.id] = 0;
      return Promise.resolve([]);
    }
    var url = typeof cat.endpoint === 'function' ? cat.endpoint() : cat.endpoint;
    return fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var items = Array.isArray(data[cat.dataKey]) ? data[cat.dataKey] : [];
        counts[cat.id] = items.length;
        if (cat.id === 'styles') styleCategoryTree = deriveStyleCategoryTree(items);
        if (cat.id === 'templates') templateThemeTree = deriveTemplateThemeTree(items);
        renderNav();
        return items;
      });
  }

  function loadCategory(id) {
    var cat = CATEGORIES.find(function (c) { return c.id === id; });
    if (!cat) return;
    activeId = id;
    try { localStorage.setItem(LIB_ACTIVE_TAB_KEY, id); } catch (_) {}
    if (breadcrumbCurrent) breadcrumbCurrent.textContent = cat.label;
    renderNav();
    grid.innerHTML = '';
    grid.style.display = '';
    empty.hidden = true;
    if (gridZoomToolbar) gridZoomToolbar.hidden = false;
    if (toolbar) toolbar.hidden = id !== 'styles';
    if (templatesToolbar) templatesToolbar.hidden = id !== 'templates';
    if (templatesCount && id !== 'templates') templatesCount.textContent = '';
    // A new category starts unfiltered — the query was about the old one.
    searchQuery = '';
    activeItems = [];
    if (searchInput) { searchInput.value = ''; searchInput.hidden = false; }
    if (depotToolbar) depotToolbar.hidden = id !== 'depot';
    // Every category grid renders .rp-card photo cards now (see photoCardHtml)
    // except Templates, whose grid isn't even shown (sidebar tree picker
    // instead) — the compact 150px column min matches those cards' own
    // narrower max-width (256px) better than the old 200px default.
    grid.classList.toggle('lib-grid--compact', id !== 'templates');
    if (createMain) createMain.classList.toggle('cs-create-main--depot', id === 'depot');
    // Any tab switch (including re-clicking Depot from within its own
    // detail view) always lands back on the Depot list, not mid-detail.
    depotDetailId = null;
    if (depotDetailEl) { depotDetailEl.hidden = true; depotDetailEl.innerHTML = ''; }
    if (depotAside) depotAside.hidden = true;
    if (breadcrumbDepots) breadcrumbDepots.hidden = true;
    if (breadcrumbDepotsArrow) breadcrumbDepotsArrow.hidden = true;

    fetchItems(cat).then(function (items) {
      if (activeId !== id) return;
      activeItems = items;
      if (id === 'styles') { allStyleItems = items; renderGrid(cat, filterItemsForDisplay(id, items)); return; }
      if (id === 'templates') { allTemplateItems = items; renderGrid(cat, filterItemsForDisplay(id, items)); return; }
      renderGrid(cat, filterItemsForDisplay(id, items));
    }).catch(function (err) {
      console.error('[Library] Failed to load', cat.id, err);
      if (activeId === id) {
        grid.style.display = 'none';
        empty.hidden = false;
        empty.textContent = 'Could not load ' + cat.label.toLowerCase() + '.';
      }
    });
  }

  nav.addEventListener('click', function (e) {
    var groupToggle = e.target.closest('.lib-style-cat-group-toggle');
    if (groupToggle) {
      var g = groupToggle.dataset.styleGroup;
      expandedStyleGroups[g] = !expandedStyleGroups[g];
      selectedStyleCategory = g;
      renderNav();
      var stylesCatGroup = CATEGORIES.find(function (c) { return c.id === 'styles'; });
      renderGrid(stylesCatGroup, filterItemsForDisplay('styles', allStyleItems));
      // Switching the style category filter changes which cards are on
      // screen — the open panel might be editing a style that's no longer
      // even visible, so close it rather than leave it pointing at nothing.
      closeEditModal();
      return;
    }
    var treeBtn = e.target.closest('.lib-style-cat-tree-item');
    if (treeBtn) {
      selectedStyleCategory = treeBtn.dataset.styleCat || '';
      renderNav();
      var stylesCat = CATEGORIES.find(function (c) { return c.id === 'styles'; });
      renderGrid(stylesCat, filterItemsForDisplay('styles', allStyleItems));
      closeEditModal();
      return;
    }
    var templateGroupToggle = e.target.closest('.lib-template-cat-group-toggle');
    if (templateGroupToggle) {
      var tg = templateGroupToggle.dataset.templateThemeGroup;
      expandedTemplateThemeGroups[tg] = !expandedTemplateThemeGroups[tg];
      selectedTemplateTheme = tg;
      renderNav();
      var templatesCatGroup = CATEGORIES.find(function (c) { return c.id === 'templates'; });
      renderGrid(templatesCatGroup, filterItemsForDisplay('templates', allTemplateItems));
      return;
    }
    var templateTreeBtn = e.target.closest('.lib-template-cat-tree-item');
    if (templateTreeBtn) {
      selectedTemplateTheme = templateTreeBtn.dataset.templateTheme || '';
      renderNav();
      var templatesCat = CATEGORIES.find(function (c) { return c.id === 'templates'; });
      renderGrid(templatesCat, filterItemsForDisplay('templates', allTemplateItems));
      return;
    }
    var btn = e.target.closest('[data-cat]');
    if (!btn) return;
    if (btn.dataset.cat === 'styles' && activeId === 'styles') {
      // Already on Styles — toggle the category tree open/closed instead of
      // re-loading (which would also reset selectedStyleCategory, losing
      // whatever filter was picked).
      stylesTreeOpen = !stylesTreeOpen;
      renderNav();
      return;
    }
    if (btn.dataset.cat === 'templates' && activeId === 'templates') {
      templatesTreeOpen = !templatesTreeOpen;
      renderNav();
      return;
    }
    selectedStyleCategory = '';
    selectedTemplateTheme = '';
    stylesTreeOpen = true;
    templatesTreeOpen = true;
    loadCategory(btn.dataset.cat);
  });

  /* ── Edit / Create Style modal ───────────────────────────────────────────
     Same panel serves both modes — editMode picks the save/delete/image
     behavior since a not-yet-saved style has no id to attach an image to. */
  var editModal      = document.getElementById('lib-style-edit-modal');
  var editClose      = document.getElementById('lib-style-edit-close');
  var editTitle      = document.getElementById('lib-style-edit-title');
  var editSaveBtn    = document.getElementById('lib-style-edit-save');
  var editDelBtn     = document.getElementById('lib-style-edit-delete');
  var editStatus     = document.getElementById('lib-style-edit-status');
  var editImageStep  = document.getElementById('lib-style-edit-image-step');
  var editImageWrap  = document.getElementById('lib-style-edit-image-wrap');
  var editImageEl    = document.getElementById('lib-style-edit-image');
  var editImageInput = document.getElementById('lib-style-edit-image-input');
  var editImageBtn   = document.getElementById('lib-style-edit-image-btn');
  var createStyleBtn = document.getElementById('lib-create-style-btn');
  var editFields   = {
    name:     document.getElementById('lib-style-edit-name'),
    category: document.getElementById('lib-style-edit-category'),
    prompt:   document.getElementById('lib-style-edit-prompt'),
    prefix:   document.getElementById('lib-style-edit-prefix'),
    suffix:   document.getElementById('lib-style-edit-suffix'),
  };
  var editingStyleId = null;
  var editMode = 'edit'; // 'edit' | 'create'

  // Any edit-panel preview (Style / Template / Item) whose file fails to
  // load falls back to the icon instead of a broken-image box. Image error
  // events don't bubble, hence the capture phase.
  document.addEventListener('error', function (e) {
    var img = e.target;
    if (!img || img.tagName !== 'IMG' || !img.classList.contains('lib-style-edit-image')) return;
    img.hidden = true;
    var wrap = img.closest('.lib-style-edit-image-wrap');
    if (wrap) wrap.classList.add('lib-style-edit-image-wrap--fallback');
  }, true);

  function setEditImage(url) {
    if (!editImageWrap || !editImageEl) return;
    if (url) {
      editImageEl.src = url;
      editImageEl.hidden = false;
      editImageWrap.classList.remove('lib-style-edit-image-wrap--fallback');
    } else {
      editImageEl.hidden = true;
      editImageEl.src = '';
      editImageWrap.classList.add('lib-style-edit-image-wrap--fallback');
    }
    if (window.lucide) window.lucide.createIcons();
  }

  function openEditModal(styleId) {
    var item = currentItems.find(function (it) { return String(it.id) === String(styleId); });
    if (!item || !editModal) return;
    editingStyleId = styleId;
    editMode = 'edit';
    if (editTitle) editTitle.textContent = 'Edit Style';
    if (editDelBtn) editDelBtn.hidden = false;
    if (editImageStep) editImageStep.hidden = false;
    setEditImage(item.has_image ? item.image_url : '');
    editFields.name.value     = item.name || '';
    editFields.category.value = item.category || '';
    editFields.prompt.value   = item.prompt || '';
    editFields.prefix.value   = item.prefix || '';
    editFields.suffix.value   = item.suffix || '';
    editStatus.textContent = '';
    editModal.classList.remove('is-closed');
    editModal.setAttribute('aria-hidden', 'false');
  }

  function openCreateModal() {
    if (!editModal) return;
    editingStyleId = null;
    editMode = 'create';
    if (editTitle) editTitle.textContent = 'Create Style';
    if (editDelBtn) editDelBtn.hidden = true;
    // A style needs to exist before an image can be attached to it.
    if (editImageStep) editImageStep.hidden = true;
    editFields.name.value = '';
    editFields.category.value = '';
    editFields.prompt.value = '';
    editFields.prefix.value = '';
    editFields.suffix.value = '';
    editStatus.textContent = '';
    editModal.classList.remove('is-closed');
    editModal.setAttribute('aria-hidden', 'false');
    editFields.name.focus();
  }

  function closeEditModal() {
    if (editModal) {
      editModal.classList.add('is-closed');
      editModal.setAttribute('aria-hidden', 'true');
    }
    editingStyleId = null;
  }

  if (grid) {
    grid.addEventListener('click', function (e) {
      var card = e.target.closest('.lib-card--editable');
      if (!card) return;
      openEditModal(card.dataset.libEditId);
    });
  }

  if (createStyleBtn) createStyleBtn.addEventListener('click', openCreateModal);

  /* ── Export / Import styles ───────────────────────────────────────────────
     Export is a plain link (GET /api/styles/export downloads a .zip — no JS
     needed). Import posts that .zip to /styles/import-zip, which matches
     styles by name and only fills in images this install doesn't already
     have for the resolved local model — see styles_routes.py for the full
     name-matching rationale. */
  var stylesImportBtn    = document.getElementById('lib-styles-import-btn');
  var stylesImportInput  = document.getElementById('lib-styles-import-input');
  var stylesImportStatus = document.getElementById('lib-styles-import-status');

  if (stylesImportBtn && stylesImportInput) {
    stylesImportBtn.addEventListener('click', function () { stylesImportInput.click(); });
    stylesImportInput.addEventListener('change', function () {
      var file = stylesImportInput.files && stylesImportInput.files[0];
      stylesImportInput.value = '';
      if (!file) return;

      var formData = new FormData();
      formData.append('file', file);
      stylesImportBtn.disabled = true;
      if (stylesImportStatus) { stylesImportStatus.hidden = false; stylesImportStatus.textContent = 'Importing…'; }

      fetch('/api/styles/import-zip', { method: 'POST', body: formData })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error((res.data && res.data.error) || 'Import failed');
          var d = res.data;
          if (stylesImportStatus) {
            stylesImportStatus.textContent =
              d.added + ' new, ' + d.updated + ' updated, ' + d.imagesWritten + ' images added' +
              (d.imagesSkippedNoLocalModel ? ' (' + d.imagesSkippedNoLocalModel + ' skipped — model not found on this install)' : '');
          }
          if (activeId === 'styles') loadCategory('styles');
        })
        .catch(function (err) {
          console.error('[Library] Styles import failed:', err);
          if (stylesImportStatus) stylesImportStatus.textContent = (err && err.message) || 'Import failed.';
        })
        .finally(function () {
          stylesImportBtn.disabled = false;
        });
    });
  }

  if (editClose) editClose.addEventListener('click', closeEditModal);

  if (editImageBtn) {
    editImageBtn.addEventListener('click', function () {
      if (editImageInput) editImageInput.click();
    });
  }

  if (editImageInput) {
    editImageInput.addEventListener('change', function () {
      var file = editImageInput.files && editImageInput.files[0];
      editImageInput.value = '';
      if (!file || !editingStyleId) return;
      if (!selectedModelId) {
        editStatus.textContent = 'Select a model first.';
        return;
      }
      var reader = new FileReader();
      reader.onload = function () {
        editImageBtn.disabled = true;
        editStatus.textContent = 'Uploading…';
        fetch('/api/styles/' + encodeURIComponent(editingStyleId) + '/model-image', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.assign({ modelId: selectedModelId, imageUrl: reader.result }, imageSaveOptions())),
        }).then(function (r) {
          if (!r.ok) throw new Error('Image upload failed (' + r.status + ')');
          return r.json();
        }).then(function (data) {
          var url = data && data.image_url;
          if (url) {
            setEditImage(url);
            setCardImage(editingStyleId, url);
          }
          editStatus.textContent = '';
        }).catch(function (err) {
          console.error('[Library] Style image upload failed:', err);
          editStatus.textContent = 'Image upload failed.';
        }).finally(function () {
          editImageBtn.disabled = false;
        });
      };
      reader.readAsDataURL(file);
    });
  }

  if (editSaveBtn) {
    editSaveBtn.addEventListener('click', function () {
      if (editMode === 'create') {
        var name = editFields.name.value.trim();
        if (!name) { editStatus.textContent = 'Name is required.'; return; }
        editSaveBtn.disabled = true;
        editStatus.textContent = 'Creating…';
        fetch('/api/styles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: name,
            category: editFields.category.value.trim(),
            prompt: editFields.prompt.value.trim(),
            prefix: editFields.prefix.value.trim(),
            suffix: editFields.suffix.value.trim(),
          }),
        }).then(function (r) {
          if (!r.ok) throw new Error('Create failed (' + r.status + ')');
          return r.json();
        }).then(function () {
          closeEditModal();
          loadCategory('styles');
        }).catch(function (err) {
          console.error('[Library] Style create failed:', err);
          editStatus.textContent = 'Create failed.';
        }).finally(function () {
          editSaveBtn.disabled = false;
        });
        return;
      }

      if (!editingStyleId) return;
      editSaveBtn.disabled = true;
      editStatus.textContent = 'Saving…';
      fetch('/api/styles/' + encodeURIComponent(editingStyleId), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: editFields.name.value.trim(),
          category: editFields.category.value.trim(),
          prompt: editFields.prompt.value.trim(),
          prefix: editFields.prefix.value.trim(),
          suffix: editFields.suffix.value.trim(),
        }),
      }).then(function (r) {
        if (!r.ok) throw new Error('Save failed (' + r.status + ')');
        return r.json();
      }).then(function () {
        closeEditModal();
        loadCategory('styles');
      }).catch(function (err) {
        console.error('[Library] Style save failed:', err);
        editStatus.textContent = 'Save failed.';
      }).finally(function () {
        editSaveBtn.disabled = false;
      });
    });
  }

  if (editDelBtn) {
    editDelBtn.addEventListener('click', function () {
      if (!editingStyleId) return;
      if (!window.confirm('Delete this style? This cannot be undone.')) return;
      editDelBtn.disabled = true;
      fetch('/api/styles/' + encodeURIComponent(editingStyleId), { method: 'DELETE' })
        .then(function (r) {
          if (!r.ok) throw new Error('Delete failed (' + r.status + ')');
          closeEditModal();
          loadCategory('styles');
        })
        .catch(function (err) {
          console.error('[Library] Style delete failed:', err);
          editStatus.textContent = 'Delete failed.';
        })
        .finally(function () {
          editDelBtn.disabled = false;
        });
    });
  }

  /* ── Edit / Create Template modal ────────────────────────────────────────
     Reached by clicking a template card in the grid (see templateCardHtml
     above) — the tree only picks the Theme now, the card picks the actual
     template. Image handling mirrors the Style panel: one image, a
     "Change image" button, click the preview to open the lightbox. */
  var templateEditModal      = document.getElementById('lib-template-edit-modal');
  var templateEditClose      = document.getElementById('lib-template-edit-close');
  var templateEditTitle      = document.getElementById('lib-template-edit-title');
  var templateEditSaveBtn    = document.getElementById('lib-template-edit-save');
  var templateEditDelBtn     = document.getElementById('lib-template-edit-delete');
  var templateEditStatus     = document.getElementById('lib-template-edit-status');
  var templateEditImageStep  = document.getElementById('lib-template-edit-image-step');
  var templateEditImageWrap  = document.getElementById('lib-template-edit-image-wrap');
  var templateEditImageEl    = document.getElementById('lib-template-edit-image');
  var templateEditImageInput = document.getElementById('lib-template-edit-image-input');
  var templateEditImageBtn   = document.getElementById('lib-template-edit-image-btn');
  var createTemplateBtn      = document.getElementById('lib-create-template-btn');
  var templateEditFields = {
    name:     document.getElementById('lib-template-edit-name'),
    theme:    document.getElementById('lib-template-edit-theme'),
    pack:     document.getElementById('lib-template-edit-pack'),
    template: document.getElementById('lib-template-edit-template'),
  };
  var editingTemplateId = null;
  var templateEditMode = 'edit'; // 'edit' | 'create'

  function setTemplateEditImage(url) {
    if (!templateEditImageWrap || !templateEditImageEl) return;
    if (url) {
      templateEditImageEl.src = url;
      templateEditImageEl.hidden = false;
      templateEditImageWrap.classList.remove('lib-style-edit-image-wrap--fallback');
    } else {
      templateEditImageEl.hidden = true;
      templateEditImageEl.src = '';
      templateEditImageWrap.classList.add('lib-style-edit-image-wrap--fallback');
    }
    if (window.lucide) window.lucide.createIcons();
  }

  function findTemplateCard(templateId) {
    return grid.querySelector('.lib-card--template-editable[data-lib-template-edit-id="' + String(templateId).replace(/"/g, '') + '"]');
  }

  function setTemplateCardImage(templateId, imageUrl) {
    var card = findTemplateCard(templateId);
    var wrap = card && card.querySelector('.lib-style-card-img-wrap');
    if (!wrap) return;
    wrap.classList.remove('lib-style-card-img-wrap--fallback');
    wrap.innerHTML = '<img src="' + escHtml(imageUrl) + '" alt="">';
  }

  if (templateEditImageEl) {
    templateEditImageEl.addEventListener('click', function () {
      if (editingTemplateId) openTemplateLightbox(0);
    });
  }

  if (templateEditImageBtn) {
    templateEditImageBtn.addEventListener('click', function () {
      if (templateEditImageInput) templateEditImageInput.click();
    });
  }

  if (templateEditImageInput) {
    templateEditImageInput.addEventListener('change', function () {
      var file = templateEditImageInput.files && templateEditImageInput.files[0];
      templateEditImageInput.value = '';
      if (!file || !editingTemplateId) return;
      var reader = new FileReader();
      reader.onload = function () {
        templateEditImageBtn.disabled = true;
        templateEditStatus.textContent = 'Uploading…';
        var item = currentItems.find(function (it) { return String(it.id) === String(editingTemplateId); });
        var hasExisting = !!(item && item.images && item.images.length);
        var removeExisting = hasExisting
          ? window.openJourneyApi.deleteTemplatePackImage(editingTemplateId, 0)
          : Promise.resolve();
        removeExisting.then(function () {
          return window.openJourneyApi.addTemplatePackImage(editingTemplateId, { imageDataUrl: reader.result, prompt: '' });
        }).then(function (data) {
          var updated = data && data.templatePack;
          if (updated) {
            if (item) item.images = updated.images;
            var firstImg = updated.images && updated.images[0];
            var url = firstImg && firstImg.filename ? '/static/images/' + firstImg.filename : '';
            setTemplateEditImage(url);
            if (url) setTemplateCardImage(editingTemplateId, url);
          }
          templateEditStatus.textContent = '';
        }).catch(function (err) {
          console.error('[Library] Template image upload failed:', err);
          templateEditStatus.textContent = 'Image upload failed.';
        }).finally(function () {
          templateEditImageBtn.disabled = false;
        });
      };
      reader.readAsDataURL(file);
    });
  }

  if (grid) {
    grid.addEventListener('click', function (e) {
      var tcard = e.target.closest('.lib-card--template-editable');
      if (!tcard) return;
      openTemplateEditModal(tcard.dataset.libTemplateEditId);
    });
  }

  /* ── Field Values (step 4) ────────────────────────────────────────────────
     Preset options for each {placeholder} used in the Template text — shared
     across the templates in one Theme (e.g. all "90s Smalltown" templates
     reuse the same {character_focus}), not the whole Pack — otherwise every
     theme's unrelated vocabulary shows up together. Fetched/saved by
     pack+theme rather than by this template's own id. */
  var templateEditValuesStep = document.getElementById('lib-template-edit-values-step');
  var templateEditValues     = document.getElementById('lib-template-edit-values');
  var templateFieldValues = {}; // { placeholderKey: ["value", ...] }

  function parseTemplatePlaceholders(text) {
    var re = /\{([^}]+)\}/g;
    var seen = {};
    var out = [];
    var m;
    while ((m = re.exec(text || ''))) {
      if (!seen[m[1]]) { seen[m[1]] = true; out.push(m[1]); }
    }
    return out;
  }

  function fieldValueGroupHtml(key, values) {
    var chips = values.map(function (v, idx) {
      return '<span class="lib-template-value-chip"><span class="lib-template-value-text">' + escHtml(v) + '</span>' +
        '<button type="button" class="lib-template-value-remove" data-field-key="' + escHtml(key) + '" data-field-idx="' + idx + '" aria-label="Remove value">&times;</button>' +
      '</span>';
    }).join('');
    return (
      '<div class="lib-template-value-group">' +
        '<p class="lib-template-value-label">' + escHtml(key) + '</p>' +
        '<div class="lib-template-value-chips">' + chips + '</div>' +
        '<div class="lib-template-value-add-row">' +
          '<input type="text" class="nsc-input lib-template-value-input" data-field-key="' + escHtml(key) + '" placeholder="Add a value…">' +
          '<button type="button" class="lib-style-edit-panel-secondary lib-template-value-add-btn" data-field-key="' + escHtml(key) + '">Add</button>' +
        '</div>' +
      '</div>'
    );
  }

  // Which placeholder is open. '' = the list of fields; a key = that field's
  // values. Showing every field's values at once meant a template with six
  // placeholders and ten-odd values each — some of them whole sentences —
  // rendered as one column you could only scroll. A list first, then one
  // field at a time, is the same information you can actually navigate.
  var templateEditActiveField = '';

  function fieldListRowHtml(key, count) {
    return (
      '<button type="button" class="lib-template-field-row" data-open-field="' + escHtml(key) + '">' +
        '<span class="lib-template-field-name">' + escHtml(key) + '</span>' +
        '<span class="lib-template-field-count">' + count +
          (count === 1 ? ' value' : ' values') + '</span>' +
        '<svg class="lib-template-field-chevron" viewBox="0 0 24 24" aria-hidden="true" ' +
          'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">' +
          '<path d="M9 6l6 6-6 6"/></svg>' +
      '</button>'
    );
  }

  function closeTemplateValuesPanel() {
    templateEditActiveField = '';
    if (valuesPanel) {
      valuesPanel.classList.add('is-closed');
      valuesPanel.setAttribute('aria-hidden', 'true');
    }
    if (templateEditValues) {
      templateEditValues.querySelectorAll('.lib-template-field-row.is-active')
        .forEach(function (r) { r.classList.remove('is-active'); });
    }
  }

  function renderTemplateValuesPanel() {
    if (!valuesPanel || !valuesPanelBody) return;
    if (!templateEditActiveField) { closeTemplateValuesPanel(); return; }
    var key = templateEditActiveField;
    var values = templateFieldValues[key] || [];
    valuesPanelTitle.textContent = key;
    valuesPanelHint.textContent = values.length
      ? values.length + (values.length === 1 ? ' preset value' : ' preset values') +
        ' — shared by every template in this pack.'
      : 'No preset values yet. Add the first one below.';
    valuesPanelBody.innerHTML = fieldValueGroupHtml(key, values);
    valuesPanel.classList.remove('is-closed');
    valuesPanel.setAttribute('aria-hidden', 'false');
    if (templateEditValues) {
      templateEditValues.querySelectorAll('.lib-template-field-row').forEach(function (r) {
        r.classList.toggle('is-active', r.dataset.openField === key);
      });
    }
  }

  function renderTemplateFieldValues() {
    if (!templateEditValues || !templateEditValuesStep) return;
    var keys = templateEditMode === 'edit' ? parseTemplatePlaceholders(templateEditFields.template.value) : [];
    if (!keys.length) {
      templateEditValuesStep.hidden = true;
      templateEditValues.innerHTML = '';
      closeTemplateValuesPanel();
      return;
    }
    templateEditValuesStep.hidden = false;

    // A field that vanished from the template text while its panel was open.
    if (templateEditActiveField && keys.indexOf(templateEditActiveField) === -1) {
      closeTemplateValuesPanel();
    }

    templateEditValues.innerHTML =
      '<div class="lib-template-field-list">' +
      keys.map(function (key) {
        return fieldListRowHtml(key, (templateFieldValues[key] || []).length);
      }).join('') +
      '</div>';

    if (templateEditActiveField) renderTemplateValuesPanel();
  }

  function loadTemplateFieldValuesForTheme(pack, theme) {
    if (!pack || !theme) { templateFieldValues = {}; renderTemplateFieldValues(); return; }
    window.openJourneyApi.getTemplatePackFieldValues(pack, theme).then(function (data) {
      templateFieldValues = (data && data.values) || {};
      renderTemplateFieldValues();
    }).catch(function (err) {
      console.error('[Library] Failed to load field values:', err);
      templateFieldValues = {};
      renderTemplateFieldValues();
    });
  }

  function addTemplateFieldValue(key, value) {
    var val = String(value || '').trim();
    if (!key || !val) return;
    if (!templateFieldValues[key]) templateFieldValues[key] = [];
    templateFieldValues[key].push(val);
    renderTemplateFieldValues();
    // Re-rendered markup means a new input element; put the caret back so you
    // can type several values in a row without reaching for the mouse.
    var box = valuesPanelBody &&
      valuesPanelBody.querySelector('.lib-template-value-input[data-field-key="' + key + '"]');
    if (box) { box.value = ''; box.focus(); }
  }

  if (templateEditFields.template) {
    templateEditFields.template.addEventListener('input', function () {
      if (templateEditMode === 'edit') renderTemplateFieldValues();
    });
  }

  // The field list lives in the editor; a field's values live in the second
  // panel. Two surfaces, so two delegated listeners.
  if (templateEditValues) {
    templateEditValues.addEventListener('click', function (e) {
      var openBtn = e.target.closest('[data-open-field]');
      if (!openBtn) return;
      var key = openBtn.dataset.openField || '';
      // Clicking the field that is already open closes it, so the same row
      // both opens and dismisses — no hunting for the panel's × .
      templateEditActiveField = (templateEditActiveField === key) ? '' : key;
      if (templateEditActiveField) {
        renderTemplateValuesPanel();
        var firstInput = valuesPanelBody && valuesPanelBody.querySelector('.lib-template-value-input');
        if (firstInput) firstInput.focus();
      } else {
        closeTemplateValuesPanel();
      }
    });
  }

  if (valuesPanelBody) {
    valuesPanelBody.addEventListener('click', function (e) {
      var removeBtn = e.target.closest('.lib-template-value-remove');
      if (removeBtn) {
        var key = removeBtn.dataset.fieldKey;
        var idx = Number(removeBtn.dataset.fieldIdx);
        if (templateFieldValues[key]) {
          templateFieldValues[key].splice(idx, 1);
          renderTemplateFieldValues();     // refreshes the count in the list too
        }
        return;
      }
      var addBtn = e.target.closest('.lib-template-value-add-btn');
      if (addBtn) {
        var input = valuesPanelBody.querySelector('.lib-template-value-input[data-field-key="' + addBtn.dataset.fieldKey + '"]');
        addTemplateFieldValue(addBtn.dataset.fieldKey, input && input.value);
      }
    });
    valuesPanelBody.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target.classList.contains('lib-template-value-input')) {
        e.preventDefault();
        addTemplateFieldValue(e.target.dataset.fieldKey, e.target.value);
      }
    });
  }

  if (valuesPanelClose) valuesPanelClose.addEventListener('click', closeTemplateValuesPanel);

  function openTemplateEditModal(templateId) {
    var item = currentItems.find(function (it) { return String(it.id) === String(templateId); });
    if (!item || !templateEditModal) return;
    // Always land on the field list, never inside whichever field was open the
    // last time the panel was used.
    templateEditActiveField = '';
    editingTemplateId = templateId;
    templateEditMode = 'edit';
    if (templateEditTitle) templateEditTitle.textContent = 'Edit Template';
    if (templateEditDelBtn) templateEditDelBtn.hidden = false;
    if (templateEditImageStep) templateEditImageStep.hidden = false;
    var firstImg = item.images && item.images[0];
    setTemplateEditImage(firstImg && firstImg.filename ? '/static/images/' + firstImg.filename : '');
    templateEditFields.name.value = item.name || '';
    templateEditFields.theme.value = item.theme || '';
    templateEditFields.pack.value = item.pack || '';
    templateEditFields.template.value = item.template || '';
    templateEditStatus.textContent = '';
    templateEditModal.classList.remove('is-closed');
    templateEditModal.setAttribute('aria-hidden', 'false');
    loadTemplateFieldValuesForTheme(item.pack, item.theme);
  }

  function openCreateTemplateModal() {
    if (!templateEditModal) return;
    editingTemplateId = null;
    templateEditMode = 'create';
    if (templateEditTitle) templateEditTitle.textContent = 'Create Template';
    if (templateEditDelBtn) templateEditDelBtn.hidden = true;
    // No id yet to attach an image to — same reasoning as the Style panel
    // hiding its image step until the entity's been saved once.
    if (templateEditImageStep) templateEditImageStep.hidden = true;
    setTemplateEditImage('');
    templateEditFields.name.value = '';
    templateEditFields.theme.value = selectedTemplateTheme || '';
    templateEditFields.pack.value = '';
    templateEditFields.template.value = '';
    templateEditStatus.textContent = '';
    templateFieldValues = {};
    renderTemplateFieldValues();
    templateEditModal.classList.remove('is-closed');
    templateEditModal.setAttribute('aria-hidden', 'false');
    templateEditFields.name.focus();
  }

  function closeTemplateEditModal() {
    if (templateEditModal) {
      templateEditModal.classList.add('is-closed');
      templateEditModal.setAttribute('aria-hidden', 'true');
    }
    // The values panel hangs off this one; leaving it open would strand it
    // beside a closed editor with no way back to the field it belongs to.
    closeTemplateValuesPanel();
    editingTemplateId = null;
  }

  if (createTemplateBtn) createTemplateBtn.addEventListener('click', openCreateTemplateModal);

  if (templateEditClose) templateEditClose.addEventListener('click', closeTemplateEditModal);

  if (templateEditSaveBtn) {
    templateEditSaveBtn.addEventListener('click', function () {
      var payload = {
        name: templateEditFields.name.value.trim(),
        theme: templateEditFields.theme.value.trim(),
        pack: templateEditFields.pack.value.trim(),
        template: templateEditFields.template.value.trim(),
      };
      if (templateEditMode === 'create') {
        if (!payload.name) { templateEditStatus.textContent = 'Name is required.'; return; }
        templateEditSaveBtn.disabled = true;
        templateEditStatus.textContent = 'Creating…';
        window.openJourneyApi.createTemplatePack(payload).then(function () {
          closeTemplateEditModal();
          loadCategory('templates');
        }).catch(function (err) {
          console.error('[Library] Template create failed:', err);
          templateEditStatus.textContent = 'Create failed.';
        }).finally(function () {
          templateEditSaveBtn.disabled = false;
        });
        return;
      }

      if (!editingTemplateId) return;
      templateEditSaveBtn.disabled = true;
      templateEditStatus.textContent = 'Saving…';
      var saveOps = [window.openJourneyApi.updateTemplatePack(editingTemplateId, payload)];
      // Field values are shared by the whole pack, not this one template —
      // saved alongside it (same button) whenever the panel has a values
      // step showing (i.e. the template text has at least one {placeholder}).
      if (payload.pack && payload.theme && Object.keys(templateFieldValues).length) {
        saveOps.push(window.openJourneyApi.updateTemplatePackFieldValues(payload.pack, payload.theme, templateFieldValues));
      }
      Promise.all(saveOps).then(function () {
        closeTemplateEditModal();
        loadCategory('templates');
      }).catch(function (err) {
        console.error('[Library] Template save failed:', err);
        templateEditStatus.textContent = 'Save failed.';
      }).finally(function () {
        templateEditSaveBtn.disabled = false;
      });
    });
  }

  if (templateEditDelBtn) {
    templateEditDelBtn.addEventListener('click', function () {
      if (!editingTemplateId) return;
      if (!window.confirm('Delete this template? This cannot be undone.')) return;
      templateEditDelBtn.disabled = true;
      window.openJourneyApi.deleteTemplatePack(editingTemplateId).then(function () {
        closeTemplateEditModal();
        loadCategory('templates');
      }).catch(function (err) {
        console.error('[Library] Template delete failed:', err);
        templateEditStatus.textContent = 'Delete failed.';
      }).finally(function () {
        templateEditDelBtn.disabled = false;
      });
    });
  }

  /* ── Create / Edit Depot modal ───────────────────────────────────────────
     Same panel serves both modes, same convention as the Style/Template
     panels above — editingDepotId is null in create mode. The server
     derives a new depot's id as a slug of the name (depot_service.py's
     _slugify); editing never changes the id. */
  var depotEditModal   = document.getElementById('lib-depot-edit-modal');
  var depotEditClose   = document.getElementById('lib-depot-edit-close');
  var depotEditTitle   = document.getElementById('lib-depot-edit-title');
  var depotEditSaveBtn = document.getElementById('lib-depot-edit-save');
  var depotEditDelBtn  = document.getElementById('lib-depot-edit-delete');
  var depotEditStatus  = document.getElementById('lib-depot-edit-status');
  var depotEditName    = document.getElementById('lib-depot-edit-name');
  var depotEditDesc    = document.getElementById('lib-depot-edit-description');
  var createDepotBtn   = document.getElementById('lib-create-depot-btn');
  var editingDepotId   = null;

  function openCreateDepotModal() {
    if (!depotEditModal) return;
    editingDepotId = null;
    if (depotEditTitle) depotEditTitle.textContent = 'Create Depot';
    if (depotEditDelBtn) depotEditDelBtn.hidden = true;
    if (depotEditSaveBtn) depotEditSaveBtn.querySelector('.lib-btn-label').textContent = 'Create';
    depotEditName.value = '';
    depotEditDesc.value = '';
    depotEditStatus.textContent = '';
    depotEditModal.classList.remove('is-closed');
    depotEditModal.setAttribute('aria-hidden', 'false');
    depotEditName.focus();
  }

  function openEditDepotModal(depotId) {
    if (!depotEditModal) return;
    // Fetched fresh rather than read from currentItems — the edit pencil is
    // reachable from both the Depot list AND the Depot detail view (which
    // doesn't populate currentItems), so this has to work from either.
    fetch('/api/depots/' + encodeURIComponent(depotId)).then(function (r) { return r.json(); }).then(function (data) {
      var item = data && data.depot;
      if (!item) return;
      editingDepotId = depotId;
      if (depotEditTitle) depotEditTitle.textContent = 'Edit Depot';
      if (depotEditDelBtn) depotEditDelBtn.hidden = false;
      if (depotEditSaveBtn) depotEditSaveBtn.querySelector('.lib-btn-label').textContent = 'Save';
      depotEditName.value = item.name || '';
      depotEditDesc.value = item.description || '';
      depotEditStatus.textContent = '';
      depotEditModal.classList.remove('is-closed');
      depotEditModal.setAttribute('aria-hidden', 'false');
      depotEditName.focus();
    }).catch(function (err) {
      console.error('[Library] Failed to load depot for editing:', err);
    });
  }

  // Re-renders whatever's currently on screen for the Depot tab — the
  // detail view (if a depot is open) or the list — after a create/edit/
  // delete/activate action, instead of always bouncing back to the list.
  function refreshDepotView() {
    if (depotDetailId) showDepotDetail(depotDetailId);
    else loadCategory('depot');
  }

  function closeDepotEditModal() {
    if (depotEditModal) {
      depotEditModal.classList.add('is-closed');
      depotEditModal.setAttribute('aria-hidden', 'true');
    }
    editingDepotId = null;
  }

  if (createDepotBtn) createDepotBtn.addEventListener('click', openCreateDepotModal);
  if (depotEditClose) depotEditClose.addEventListener('click', closeDepotEditModal);

  if (grid) {
    grid.addEventListener('click', function (e) {
      var editBtn = e.target.closest('.lib-depot-card-edit-btn');
      if (editBtn) {
        e.stopPropagation();
        openEditDepotModal(editBtn.dataset.libDepotEditId);
        return;
      }
      var card = e.target.closest('.lib-card--depot-open');
      if (!card) return;
      showDepotDetail(card.dataset.libDepotOpenId);
    });
  }

  if (depotEditSaveBtn) {
    depotEditSaveBtn.addEventListener('click', function () {
      var name = depotEditName.value.trim();
      if (!name) { depotEditStatus.textContent = 'Name is required.'; return; }
      var description = depotEditDesc.value.trim();
      depotEditSaveBtn.disabled = true;
      depotEditStatus.textContent = editingDepotId ? 'Saving…' : 'Creating…';
      var url = editingDepotId ? '/api/depots/' + encodeURIComponent(editingDepotId) : '/api/depots';
      var method = editingDepotId ? 'PATCH' : 'POST';
      fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, description: description }),
      }).then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      }).then(function (res) {
        if (!res.ok) throw new Error((res.data && res.data.error) || (editingDepotId ? 'Save failed' : 'Create failed'));
        closeDepotEditModal();
        refreshDepotView();
      }).catch(function (err) {
        console.error('[Library] Depot save failed:', err);
        depotEditStatus.textContent = (err && err.message) || 'Save failed.';
      }).finally(function () {
        depotEditSaveBtn.disabled = false;
      });
    });
  }

  if (depotEditDelBtn) {
    depotEditDelBtn.addEventListener('click', function () {
      if (!editingDepotId) return;
      if (!window.confirm('Delete this depot? This cannot be undone.')) return;
      var deletingOpenDetail = editingDepotId === depotDetailId;
      depotEditDelBtn.disabled = true;
      fetch('/api/depots/' + encodeURIComponent(editingDepotId), { method: 'DELETE' })
        .then(function (r) {
          if (!r.ok) throw new Error('Delete failed (' + r.status + ')');
          closeDepotEditModal();
          // Its own detail view can't be "refreshed" once it's gone.
          if (deletingOpenDetail) showDepotList();
          else refreshDepotView();
        })
        .catch(function (err) {
          console.error('[Library] Depot delete failed:', err);
          depotEditStatus.textContent = 'Delete failed.';
        })
        .finally(function () {
          depotEditDelBtn.disabled = false;
        });
    });
  }

  /* ── Character / Background edit + delete ─────────────────────────────────
     Clicking a card in either grid (see photoCardHtml's cat.editable branch)
     opens this shared panel — same field shape (identifier/description/
     prompt/neutral_prompt/image) either way, just pointed at
     /api/characters/<keyword> or /api/backgrounds/<keyword> depending on
     which category was open.

     "Identifier" (not "keyword") because it's now an editable slug, not
     just a label — the field also doubles as the reference image's filename
     on disk, so the rename path on the backend (update_character/
     update_background) renames that file to match. Validated as a slug
     (lowercase, -/_ separators, no spaces/symbols) server-side; the pattern
     attribute here is just a live typing hint, not real validation. */
  var itemEditModal       = document.getElementById('lib-item-edit-modal');
  var itemEditTitle       = document.getElementById('lib-item-edit-title');
  var itemEditClose       = document.getElementById('lib-item-edit-close');
  var itemEditImageWrap   = document.getElementById('lib-item-edit-image-wrap');
  var itemEditImageEl     = document.getElementById('lib-item-edit-image');
  var itemEditImageInput  = document.getElementById('lib-item-edit-image-input');
  var itemEditImageBtn    = document.getElementById('lib-item-edit-image-btn');
  var itemEditKeywordInput = document.getElementById('lib-item-edit-keyword');
  var itemEditDescription = document.getElementById('lib-item-edit-description');
  var itemEditPrompt      = document.getElementById('lib-item-edit-prompt');
  var itemEditNeutral     = document.getElementById('lib-item-edit-neutral-prompt');
  var itemEditStatus      = document.getElementById('lib-item-edit-status');
  var itemEditSaveBtn     = document.getElementById('lib-item-edit-save');
  var itemEditDelBtn      = document.getElementById('lib-item-edit-delete');

  var editingItemCat = null;     // CATEGORIES entry (characters or backgrounds)
  var editingItemKeyword = null; // current identifier — image uploads target this; may go stale the instant a rename Save succeeds, but the modal closes right after, so nothing re-reads it post-rename

  // Unlike Style (which tracks has_image explicitly), cat.imageUrl() for
  // Characters/Backgrounds always builds a guessed <keyword>.png path
  // whether or not that file actually exists — same reason photoCardHtml's
  // <img> needs its own onerror fallback. Wire the same thing here once,
  // since this is a static DOM element (not rebuilt per open like a card).
  if (itemEditImageEl && itemEditImageWrap) {
    itemEditImageEl.addEventListener('error', function () {
      if (!itemEditImageEl.src) return; // our own `src = ''` reset below also fires 'error' — ignore that one
      itemEditImageEl.hidden = true;
      itemEditImageWrap.classList.add('lib-style-edit-image-wrap--fallback');
    });
  }

  function setItemEditImage(url) {
    if (!itemEditImageWrap || !itemEditImageEl) return;
    if (url) {
      itemEditImageEl.src = url;
      itemEditImageEl.hidden = false;
      itemEditImageWrap.classList.remove('lib-style-edit-image-wrap--fallback');
    } else {
      itemEditImageEl.hidden = true;
      itemEditImageEl.src = '';
      itemEditImageWrap.classList.add('lib-style-edit-image-wrap--fallback');
    }
    if (window.lucide) window.lucide.createIcons();
  }

  function openItemEditModal(catId, keyword) {
    if (!itemEditModal) return;
    var cat = CATEGORIES.find(function (c) { return c.id === catId; });
    if (!cat) return;
    // Read from the already-loaded grid data instead of a fresh fetch — both
    // categories' full list is already in currentItems from the last
    // loadCategory() call (same source cardHtml itself read from).
    var item = currentItems.find(function (it) { return it && it.keyword === keyword; });
    if (!item) return;
    editingItemCat = cat;
    editingItemKeyword = keyword;
    if (itemEditTitle) itemEditTitle.textContent = 'Edit ' + (cat.itemKey === 'character' ? 'Character' : 'Background');
    if (itemEditKeywordInput) itemEditKeywordInput.value = keyword;
    setItemEditImage(cat.imageUrl(item));
    itemEditDescription.value = item.description || '';
    itemEditPrompt.value = item.prompt || '';
    itemEditNeutral.value = item.neutral_prompt || '';
    itemEditStatus.textContent = '';
    itemEditModal.classList.remove('is-closed');
    itemEditModal.setAttribute('aria-hidden', 'false');
    itemEditDescription.focus();
  }

  function closeItemEditModal() {
    if (itemEditModal) {
      itemEditModal.classList.add('is-closed');
      itemEditModal.setAttribute('aria-hidden', 'true');
    }
    editingItemCat = null;
    editingItemKeyword = null;
  }

  if (grid) {
    grid.addEventListener('click', function (e) {
      var card = e.target.closest('.lib-card--item-editable');
      if (!card) return;
      openItemEditModal(card.dataset.libItemEditCat, card.dataset.libItemEditKeyword);
    });
  }

  if (itemEditClose) itemEditClose.addEventListener('click', closeItemEditModal);

  // Same immediate-upload-on-pick flow as Style's own "Change image"
  // (editImageInput above) — uploads under whatever identifier is current
  // right now. If the identifier is *also* renamed in this same session, the
  // Save handler's server-side rename carries this image forward to the new
  // filename, so upload-then-rename and rename-then-upload both end up
  // consistent regardless of which the user does first.
  if (itemEditImageBtn) {
    itemEditImageBtn.addEventListener('click', function () {
      if (itemEditImageInput) itemEditImageInput.click();
    });
  }

  if (itemEditImageInput) {
    itemEditImageInput.addEventListener('change', function () {
      var file = itemEditImageInput.files && itemEditImageInput.files[0];
      itemEditImageInput.value = '';
      if (!file || !editingItemCat || !editingItemKeyword) return;
      var reader = new FileReader();
      reader.onload = function () {
        itemEditImageBtn.disabled = true;
        itemEditStatus.textContent = 'Uploading…';
        fetch(editingItemCat.apiBase + '/' + encodeURIComponent(editingItemKeyword) + '/image', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ imageUrl: reader.result }),
        }).then(function (r) {
          if (!r.ok) throw new Error('Image upload failed (' + r.status + ')');
          return r.json();
        }).then(function () {
          // Cache-bust: the filename is unchanged (still <keyword>.png), so
          // a plain reload of the same URL would hit the browser cache and
          // keep showing the old image.
          setItemEditImage(editingItemCat.imageUrl({ keyword: editingItemKeyword }) + '?v=' + Date.now());
          itemEditStatus.textContent = '';
        }).catch(function (err) {
          console.error('[Library] Item image upload failed:', err);
          itemEditStatus.textContent = 'Image upload failed.';
        }).finally(function () {
          itemEditImageBtn.disabled = false;
        });
      };
      reader.readAsDataURL(file);
    });
  }

  if (itemEditSaveBtn) {
    itemEditSaveBtn.addEventListener('click', function () {
      if (!editingItemCat || !editingItemKeyword) return;
      var newKeyword = (itemEditKeywordInput.value || '').trim().toLowerCase();
      if (!newKeyword) {
        itemEditStatus.textContent = 'Identifier is required.';
        return;
      }
      itemEditSaveBtn.disabled = true;
      itemEditStatus.textContent = 'Saving…';
      fetch(editingItemCat.apiBase + '/' + encodeURIComponent(editingItemKeyword), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keyword: newKeyword,
          description: itemEditDescription.value.trim(),
          prompt: itemEditPrompt.value.trim(),
          neutral_prompt: itemEditNeutral.value.trim(),
        }),
      }).then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      }).then(function (res) {
        if (!res.ok) throw new Error((res.data && res.data.error) || 'Save failed');
        closeItemEditModal();
        loadCategory(activeId);
      }).catch(function (err) {
        console.error('[Library] Item save failed:', err);
        itemEditStatus.textContent = (err && err.message) || 'Save failed.';
      }).finally(function () {
        itemEditSaveBtn.disabled = false;
      });
    });
  }

  if (itemEditDelBtn) {
    itemEditDelBtn.addEventListener('click', function () {
      if (!editingItemCat || !editingItemKeyword) return;
      if (!window.confirm('Delete "' + editingItemKeyword + '"? This cannot be undone.')) return;
      itemEditDelBtn.disabled = true;
      fetch(editingItemCat.apiBase + '/' + encodeURIComponent(editingItemKeyword), { method: 'DELETE' })
        .then(function (r) {
          if (!r.ok) throw new Error('Delete failed (' + r.status + ')');
          closeItemEditModal();
          loadCategory(activeId);
        })
        .catch(function (err) {
          console.error('[Library] Item delete failed:', err);
          itemEditStatus.textContent = 'Delete failed.';
        })
        .finally(function () {
          itemEditDelBtn.disabled = false;
        });
    });
  }

  /* ── Depot detail view ────────────────────────────────────────────────────
     Clicking a Depot card (see the 'depot' cardHtml branch's
     .lib-card--depot-open) drills into this instead of opening the edit
     modal — the edit pencil on the card does that instead.

     Issue #57: the depot's own fixed info (name, description, Activate,
     per-category counters) lives in the secondary panel (#lib-depot-aside,
     same .nsc-inputs shape every other Build tab's params panel uses)
     instead of sharing a column with the item grid. The main area
     (#lib-depot-detail) holds only the items, grouped into sections same as
     before; clicking one selects it, which fills in the aside's "Selected"
     block (#lib-depot-item-detail) with that item's own info + an "Open
     flow" link back to wherever it was sent from — kept separate from the
     depot's constant info above it rather than replacing the panel. */
  var DEPOT_SECTIONS = [
    { key: 'character', label: 'Characters' },
    { key: 'background', label: 'Backgrounds' },
    { key: 'asset', label: 'Assets' },
    { key: 'styles', label: 'Styles', disabled: true },
    // key is 'flow' (singular) to match the item category written by
    // flow-gallery.js's addToFeed auto-save — not user-picked like the
    // other three, every generation while a depot is active lands here.
    { key: 'flow', label: 'Flows' },
  ];

  var depotItemsById = {}; // populated per-render by renderDepotDetail, read by selectDepotItem
  var selectedDepotItemId = null;

  // Same .rp-card full-bleed-photo treatment as Style/Template/Album cards
  // (see styleCardHtml's comment above) — kept visually identical so a
  // Depot's items read as the same "card" everywhere in the app.
  function depotItemCardHtml(item) {
    var img = item.url || '';
    var imgBlock = img
      ? '<img src="' + escHtml(img) + '" alt="" loading="lazy" decoding="async" onerror="this.closest(\'.lib-style-card-img-wrap\').classList.add(\'lib-style-card-img-wrap--fallback\')">'
      : '';
    return (
      '<div class="lib-style-card-outer">' +
        '<div class="rp-card lib-style-card lib-depot-item-card' + (item.id === selectedDepotItemId ? ' is-selected' : '') + '" data-depot-item-id="' + escHtml(String(item.id)) + '">' +
          '<div class="rp-card-media lib-style-card-img-wrap' + (img ? '' : ' lib-style-card-img-wrap--fallback') + '">' +
            imgBlock +
            '<i data-lucide="image" class="lib-style-card-fallback-icon" aria-hidden="true"></i>' +
          '</div>' +
          (item.caption ? '<div class="rp-card-body"><p class="rp-card-desc">' + escHtml(item.caption) + '</p></div>' : '') +
        '</div>' +
      '</div>'
    );
  }

  function depotDetailSectionHtml(section, items) {
    var body;
    if (section.disabled) {
      body = '<p class="lib-depot-section-empty muted-note">Coming soon.</p>';
    } else if (!items.length) {
      body = '<p class="lib-depot-section-empty muted-note">Nothing sent yet.</p>';
    } else {
      body = '<div class="lib-depot-section-grid">' + items.map(depotItemCardHtml).join('') + '</div>';
    }
    return (
      '<div class="lib-depot-section">' +
        '<p class="lib-depot-section-title">' + escHtml(section.label) + '<span class="lib-depot-section-count">' + items.length + '</span></p>' +
        body +
      '</div>'
    );
  }

  function formatDepotDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }

  var DEPOT_SECTION_LABEL = {};
  DEPOT_SECTIONS.forEach(function (s) { DEPOT_SECTION_LABEL[s.key] = s.label; });

  // Fills #lib-depot-item-detail with the clicked item's own info — kept
  // separate from renderDepotDetail so re-selecting doesn't refetch/rerender
  // the whole depot (and the grid's own scroll position) each click.
  function selectDepotItem(itemId) {
    var item = depotItemsById[itemId];
    selectedDepotItemId = itemId;
    if (depotDetailEl) {
      depotDetailEl.querySelectorAll('.lib-depot-item-card.is-selected').forEach(function (el) {
        el.classList.remove('is-selected');
      });
      var picked = depotDetailEl.querySelector('.lib-depot-item-card[data-depot-item-id="' + String(itemId).replace(/"/g, '') + '"]');
      if (picked) picked.classList.add('is-selected');
    }
    if (!item || !depotItemDetailEl) return;
    depotItemDetailEl.hidden = false;
    if (depotItemDetailMedia) {
      depotItemDetailMedia.innerHTML = item.url
        ? '<img src="' + escHtml(item.url) + '" alt="">'
        : '';
    }
    if (depotItemDetailCategory) depotItemDetailCategory.textContent = DEPOT_SECTION_LABEL[item.category] || item.category || '';
    if (depotItemDetailCaption) {
      depotItemDetailCaption.hidden = !item.caption;
      depotItemDetailCaption.textContent = item.caption || '';
    }
    if (depotItemDetailDate) depotItemDetailDate.textContent = formatDepotDate(item.addedAt);
    if (depotItemDetailOpen) {
      if (item.sourceUrl) {
        depotItemDetailOpen.href = item.sourceUrl;
        depotItemDetailOpen.classList.remove('is-disabled');
        depotItemDetailOpen.removeAttribute('aria-disabled');
      } else {
        depotItemDetailOpen.href = '#';
        depotItemDetailOpen.classList.add('is-disabled');
        depotItemDetailOpen.setAttribute('aria-disabled', 'true');
      }
    }
  }

  function renderDepotDetail(depot, isActive) {
    var itemsByCategory = {};
    depotItemsById = {};
    (depot.items || []).forEach(function (it) {
      if (!itemsByCategory[it.category]) itemsByCategory[it.category] = [];
      itemsByCategory[it.category].push(it);
      depotItemsById[it.id] = it;
    });
    selectedDepotItemId = null;
    if (depotItemDetailEl) depotItemDetailEl.hidden = true;

    if (depotAsideName) depotAsideName.textContent = depot.name;
    if (depotAsideDesc) {
      depotAsideDesc.hidden = !depot.description;
      depotAsideDesc.textContent = depot.description || '';
    }
    // Breadcrumb shows the depot's own name as the current page, with
    // "Depots" (the tab label, see CATEGORIES) as a clickable crumb back to
    // the list — replaces the aside's old dedicated back button.
    if (breadcrumbCurrent) breadcrumbCurrent.textContent = depot.name;
    if (breadcrumbDepots) breadcrumbDepots.hidden = false;
    if (breadcrumbDepotsArrow) breadcrumbDepotsArrow.hidden = false;
    var activateBtn = document.getElementById('lib-depot-activate-btn');
    if (activateBtn) {
      activateBtn.dataset.depotId = String(depot.id);
      activateBtn.classList.toggle('is-active', isActive);
      activateBtn.classList.toggle('nsc-generate-btn--ghost', !isActive);
      var activateLabel = activateBtn.querySelector('span');
      if (activateLabel) activateLabel.textContent = isActive ? 'Active — click to deactivate' : 'Activate';
    }
    if (depotCountersEl) {
      depotCountersEl.innerHTML = DEPOT_SECTIONS.filter(function (s) { return !s.disabled; }).map(function (s) {
        return (
          '<div class="lib-depot-counter">' +
            '<span class="lib-depot-counter-count">' + (itemsByCategory[s.key] || []).length + '</span>' +
            '<span class="lib-depot-counter-label">' + escHtml(s.label) + '</span>' +
          '</div>'
        );
      }).join('');
    }
    if (depotAside) depotAside.hidden = false;

    var sections = DEPOT_SECTIONS.map(function (s) {
      return depotDetailSectionHtml(s, itemsByCategory[s.key] || []);
    }).join('');

    grid.style.display = 'none';
    empty.hidden = true;
    if (gridZoomToolbar) gridZoomToolbar.hidden = true;
    if (depotDetailEl) {
      depotDetailEl.innerHTML = sections;
      depotDetailEl.hidden = false;
    }
    if (window.lucide) window.lucide.createIcons();
  }

  function showDepotDetail(depotId) {
    depotDetailId = depotId;
    if (depotToolbar) depotToolbar.hidden = true;
    if (searchInput) searchInput.hidden = true;  // the detail view isn't a grid
    Promise.all([
      fetch('/api/depots/' + encodeURIComponent(depotId)).then(function (r) { return r.json(); }),
      fetch('/api/depots/active').then(function (r) { return r.json(); }),
    ]).then(function (results) {
      if (depotDetailId !== depotId) return; // navigated away while this was in flight
      var depot = results[0] && results[0].depot;
      var activeDepot = results[1] && results[1].depot;
      if (!depot) { showDepotList(); return; }
      renderDepotDetail(depot, !!(activeDepot && activeDepot.id === depot.id));
    }).catch(function (err) {
      console.error('[Library] Failed to load depot detail:', err);
    });
  }

  function showDepotList() {
    if (depotDetailEl) { depotDetailEl.hidden = true; depotDetailEl.innerHTML = ''; }
    if (depotAside) depotAside.hidden = true;
    loadCategory('depot');
  }

  if (breadcrumbDepots) {
    breadcrumbDepots.addEventListener('click', function (e) {
      e.preventDefault(); // stays client-side (showDepotList), href is just a no-JS fallback
      showDepotList();
    });
  }

  if (depotAside) {
    depotAside.addEventListener('click', function (e) {
      if (e.target.closest('#lib-depot-aside-edit-btn')) {
        if (depotDetailId) openEditDepotModal(depotDetailId);
        return;
      }
      var activateBtn = e.target.closest('#lib-depot-activate-btn');
      if (activateBtn) {
        var id = activateBtn.dataset.depotId;
        var isActive = activateBtn.classList.contains('is-active');
        activateBtn.disabled = true;
        var req = isActive
          ? fetch('/api/depots/deactivate', { method: 'POST' })
          : fetch('/api/depots/' + encodeURIComponent(id) + '/activate', { method: 'POST' });
        req.then(function () { showDepotDetail(id); })
          .catch(function (err) { console.error('[Library] Depot activate toggle failed:', err); })
          .finally(function () { activateBtn.disabled = false; });
        return;
      }
      var openBtn = e.target.closest('#lib-depot-item-detail-open');
      if (openBtn && openBtn.classList.contains('is-disabled')) { e.preventDefault(); }
    });
  }

  // Clicking an asset card in the main grid selects it (see selectDepotItem)
  // instead of opening a lightbox — the aside's "Open flow" link is the only
  // way out of the card, mirroring how Depot cards themselves drill in.
  if (depotDetailEl) {
    depotDetailEl.addEventListener('click', function (e) {
      var card = e.target.closest('.lib-depot-item-card');
      if (!card) return;
      selectDepotItem(card.dataset.depotItemId);
    });
  }

  /* ── Model toolbar (Styles only) ─────────────────────────────────────────
     Which model is selected doesn't change what's fetched yet — this just
     surfaces the real imported-model list at the top, ready for the
     per-model "generate"/"associate image" actions to hook into next. */
  var selectedModelId = '';

  function loadModelOptions() {
    if (!modelSelect) return Promise.resolve();
    return fetch('/api/models/imports')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var imports = Array.isArray(data.imports) ? data.imports : [];
        if (!imports.length) {
          modelSelect.innerHTML = '<option value="">No models imported</option>';
          return;
        }
        modelSelect.innerHTML = imports.map(function (imp) {
          return '<option value="' + escHtml(String(imp.id)) + '">' + escHtml(imp.name || imp.id) + '</option>';
        }).join('');
        selectedModelId = imports[0].id;
        modelSelect.value = selectedModelId;
        loadModelAnalysis(selectedModelId);
      })
      .catch(function (err) {
        console.error('[Library] Failed to load models:', err);
        modelSelect.innerHTML = '<option value="">Could not load models</option>';
      });
  }

  if (modelSelect) {
    modelSelect.addEventListener('change', function () {
      selectedModelId = modelSelect.value;
      loadModelAnalysis(selectedModelId);
      if (activeId === 'styles') loadCategory('styles');
    });
  }

  /* ── Generate missing style images for the selected model ────────────────
     Replicates the same prepare → submit-to-ComfyUI → wait-for-image dance
     the flow engine uses (flow-generation.js), since ComfyUI submission has
     to happen from the browser — then re-saves the result into the app's
     managed output dir and associates it with this style+model. */
  var lastComfyApiUrl = null; // set right after prepare-queue, used by Stop to call /interrupt
  var cancelRequested = false;

  function findStyleCard(styleId) {
    return grid.querySelector('.lib-style-card[data-lib-edit-id="' + String(styleId).replace(/"/g, '') + '"]');
  }

  function setCardGenerating(styleId, on) {
    var card = findStyleCard(styleId);
    var wrap = card && card.querySelector('.lib-style-card-img-wrap');
    if (!wrap) return;
    if (on) {
      if (wrap.dataset.savedHtml === undefined) wrap.dataset.savedHtml = wrap.innerHTML;
      // Same ring + ETA / % / steps slots as Create's generating card
      // (flow-generation.js _markCardGenerating), filled by
      // updateStyleCardProgress from the ComfyUI progress stream.
      wrap.innerHTML = RING_SVG +
        '<span class="nsc-ring-pct"></span><span class="nsc-ring-steps">' +
        escHtml(tr('build.queued', 'Queued…')) + '</span><span class="nsc-ring-eta"></span>';
      wrap.classList.add('lib-style-card-img-wrap--generating');
      wrap._genStartTime = Date.now();
    } else {
      if (wrap._etaInterval) { clearInterval(wrap._etaInterval); wrap._etaInterval = null; }
      wrap.classList.remove('lib-style-card-img-wrap--generating');
      if (wrap.dataset.savedHtml !== undefined) {
        wrap.innerHTML = wrap.dataset.savedHtml;
        delete wrap.dataset.savedHtml;
      }
    }
  }

  var RING_CIRC = 113.1; // 2π × r=18, same ring as flow-generation.js

  function fmtEta(secs) {
    if (secs <= 0) return '';
    if (secs < 60) return secs + 's';
    return Math.floor(secs / 60) + ':' + String(Math.round(secs % 60)).padStart(2, '0');
  }

  // Mirrors flow-generation.js updateCardProgress for a Build style card:
  // determinate ring, "NN%", "step / steps" and a live ETA countdown
  // estimated from the time elapsed so far.
  function updateStyleCardProgress(styleId, value, max) {
    if (!max || max <= 0) return;
    var card = findStyleCard(styleId);
    var wrap = card && card.querySelector('.lib-style-card-img-wrap');
    if (!wrap || !wrap.classList.contains('lib-style-card-img-wrap--generating')) return;
    var pct = Math.min(100, Math.round((value / max) * 100));
    var ring = wrap.querySelector('.nsc-ring');
    var fill = wrap.querySelector('.nsc-ring-fill');
    var pctEl = wrap.querySelector('.nsc-ring-pct');
    var stepsEl = wrap.querySelector('.nsc-ring-steps');
    var etaEl = wrap.querySelector('.nsc-ring-eta');
    if (ring) ring.classList.remove('nsc-ring--indeterminate');
    if (fill) fill.style.strokeDashoffset = RING_CIRC * (1 - pct / 100);
    if (pctEl) pctEl.textContent = pct + '%';
    if (stepsEl) stepsEl.textContent = value + ' / ' + max;
    if (wrap._etaInterval) { clearInterval(wrap._etaInterval); wrap._etaInterval = null; }
    if (etaEl && wrap._genStartTime && pct > 0 && pct < 100) {
      var remaining = Math.round(((Date.now() - wrap._genStartTime) / 1000) * (100 - pct) / pct);
      etaEl.textContent = fmtEta(remaining);
      wrap._etaInterval = setInterval(function () {
        remaining = Math.max(0, remaining - 1);
        etaEl.textContent = fmtEta(remaining);
      }, 1000);
    } else if (etaEl) {
      etaEl.textContent = '';
    }
  }

  function setCardImage(styleId, imageUrl) {
    var card = findStyleCard(styleId);
    var wrap = card && card.querySelector('.lib-style-card-img-wrap');
    if (!wrap) return;
    delete wrap.dataset.savedHtml;
    wrap.classList.remove('lib-style-card-img-wrap--fallback', 'lib-style-card-img-wrap--generating');
    wrap.innerHTML = '<img src="' + escHtml(imageUrl) + '" alt="">';
    var item = currentItems.find(function (it) { return String(it.id) === String(styleId); });
    if (item) { item.has_image = true; item.image_url = imageUrl; }
  }

  function buildStylePrompt(style) {
    return [style.prefix, style.prompt, style.suffix]
      .map(function (s) { return String(s || '').trim(); })
      .filter(Boolean)
      .join(', ');
  }

  // Fallback for when the progress stream reports "done" (or drops) without
  // ever having relayed an image_ready event — poll ComfyUI's own history
  // API directly, same as flow-generation.js's pollComfy.
  async function pollComfyHistory(promptId, comfyUrl) {
    var failures = 0;
    for (var i = 0; i < 600; i++) {
      var res, data;
      try {
        res = await fetch(comfyUrl + '/history/' + promptId, { cache: 'no-store' });
        data = await res.json();
        failures = 0;
      } catch (err) {
        if (++failures >= 10) throw err;
        await new Promise(function (r) { setTimeout(r, 1000); });
        continue;
      }

      var entry = data && data[promptId];
      if (entry && entry.status && entry.status.completed) {
        var filename = null, subfolder = '', type = 'output';
        Object.keys(entry.outputs || {}).some(function (nId) {
          var n = entry.outputs[nId];
          if (Array.isArray(n.images) && n.images.length && n.images[0].filename) {
            filename = n.images[0].filename;
            subfolder = n.images[0].subfolder || '';
            type = n.images[0].type || 'output';
            return true;
          }
          return false;
        });
        if (!filename) throw new Error('ComfyUI finished but returned no image.');
        return comfyUrl + '/view?filename=' + encodeURIComponent(filename) +
          '&subfolder=' + encodeURIComponent(subfolder) + '&type=' + encodeURIComponent(type);
      }
      // Terminal-but-unsuccessful states (interrupted via /interrupt, or a
      // real execution error) — fail fast instead of retrying for up to a
      // minute, so Stop feels instant. Deliberately outside the try/catch
      // above so it isn't treated as a transient network hiccup and retried.
      if (entry && entry.status && entry.status.status_str === 'error' && !entry.status.completed) {
        var interrupted = (entry.status.messages || []).some(function (m) { return m[0] === 'execution_interrupted'; });
        throw new Error(interrupted ? 'Generation interrupted' : 'ComfyUI reported an execution error');
      }
      await new Promise(function (r) { setTimeout(r, 1000); });
    }
    throw new Error('Generation timed out.');
  }

  // The SSE progress stream only relays events the *server* is connected in
  // time to see — if ComfyUI finishes before that websocket handshake lands
  // (e.g. a fully node-cached run, near-instant), its "done"/"image_ready"
  // never arrives and the stream just hangs forever. Polling ComfyUI's own
  // /history endpoint directly is reliable regardless of that race, so it
  // runs immediately and unconditionally; the SSE stream is raced alongside
  // it purely as a (usually faster) shortcut, not a required signal.
  function waitForComfyImage(comfyUrl, clientId, promptId, onProgress) {
    return new Promise(function (resolve, reject) {
      var settled = false;
      var es = null;
      try {
        var params = new URLSearchParams({ comfyApiUrl: comfyUrl, clientId: clientId });
        es = new EventSource('/api/images/comfy/progress-stream?' + params);
      } catch (_) { /* fall through to polling only */ }

      function settle(fn, val) {
        if (settled) return;
        settled = true;
        if (es) { try { es.close(); } catch (_) {} }
        fn(val);
      }

      if (es) {
        var imgUrl = null;
        es.onmessage = function (e) {
          try {
            var msg = JSON.parse(e.data);
            var t = String(msg.type || '').toLowerCase();
            if (t === 'image_ready') imgUrl = msg.url || msg.image_url;
            else if (t === 'progress' && msg.max > 0 && onProgress) onProgress(msg.value, msg.max);
            else if (t === 'executing' && onProgress) onProgress(0, 0);
            else if (t === 'done' && imgUrl) settle(resolve, imgUrl);
          } catch (_) {}
        };
      }

      pollComfyHistory(promptId, comfyUrl).then(function (url) {
        settle(resolve, url);
      }).catch(function (err) {
        settle(reject, err);
      });
    });
  }

  async function generateStyleImageForModel(style, modelId) {
    // 2:3 portrait (matches ASPECT_PRESETS' r2x3 elsewhere in the app),
    // scaled by the Advanced panel's SD/MD/HD pick instead of the previous
    // fixed 640×960 ("sd") — plus whichever quantization pill is selected
    // there, merged into advancedValues the same way the real flow does
    // (see flow-generation.js's submitWorkflowAndWait).
    var dims = RES_PRESETS[selectedResolution] || RES_PRESETS.md;
    var prepRes = await fetch('/api/models/imports/prepare-queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        basicValues: { positive: buildStylePrompt(style), width: dims.w, height: dims.h },
        advancedValues: (quantizationTouched && selectedQuantizationValues) || {},
        numImages: 1,
        targetImportId: modelId,
      }),
    });
    var prepData = await prepRes.json();
    if (!prepRes.ok || prepData.error) throw new Error(prepData.error || 'Prepare failed');
    lastComfyApiUrl = prepData.comfyApiUrl;

    var submitRes = await fetch(prepData.comfyApiUrl + '/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: prepData.workflow, client_id: prepData.clientId }),
    });
    var submitData = await submitRes.json();
    if (!submitRes.ok || submitData.error) throw new Error('ComfyUI queue rejected the job');
    if (!submitData.prompt_id) throw new Error('ComfyUI did not return a prompt_id');

    var rawUrl = await waitForComfyImage(prepData.comfyApiUrl, prepData.clientId, submitData.prompt_id,
      function (value, max) {
        if (max > 0) { updateStyleCardProgress(style.id, value, max); return; }
        // First "executing" event: our prompt left the queue.
        var card = findStyleCard(style.id);
        var stepsEl = card && card.querySelector('.lib-style-card-img-wrap--generating .nsc-ring-steps');
        if (stepsEl && !/\//.test(stepsEl.textContent)) stepsEl.textContent = tr('build.starting', 'Starting…');
      });
    if (!rawUrl) throw new Error('No image returned');

    var u = new URL(rawUrl);
    var filename = u.searchParams.get('filename');
    if (!filename) throw new Error('Could not read the generated filename');

    var saveRes = await window.openJourneyApi.saveComfyImages({
      comfyApiUrl: prepData.comfyApiUrl,
      importId: modelId,
      filenamePrefix: 'style-preview',
      images: [{ filename: filename, subfolder: u.searchParams.get('subfolder') || '', type: u.searchParams.get('type') || 'output' }],
      metadata: { source: 'library-style-preview', style_id: String(style.id), model_id: modelId },
    });
    var savedFilename = saveRes && Array.isArray(saveRes.savedFilenames) && saveRes.savedFilenames[0];
    if (!savedFilename) throw new Error('Saving the generated image failed');
    var imageUrl = window.openJourneyApi.getImageUrl(savedFilename);

    var patchRes = await fetch('/api/styles/' + encodeURIComponent(style.id) + '/model-image', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ modelId: modelId, imageUrl: imageUrl }, imageSaveOptions())),
    });
    if (!patchRes.ok) {
      var patchErr = await patchRes.json().catch(function () { return {}; });
      throw new Error(patchErr.error || 'Failed to associate the image with the style');
    }
    return imageUrl;
  }

  var generateBtn = document.getElementById('lib-generate-images-btn');
  var isBulkGenerating = false;

  function stopBulkGeneration() {
    cancelRequested = true;
    if (lastComfyApiUrl) {
      fetch(lastComfyApiUrl + '/interrupt', { method: 'POST' }).catch(function () {});
    }
  }

  var generateBtnIcon = generateBtn && generateBtn.querySelector('.lib-toolbar-generate-btn-icon');
  var generateBtnIdleIcon = generateBtnIcon ? generateBtnIcon.innerHTML : '';

  if (generateBtn) {
    generateBtn.addEventListener('click', function () {
      if (isBulkGenerating) { stopBulkGeneration(); return; }
      if (activeId !== 'styles' || !selectedModelId) return;

      var labelSpan = generateBtn.querySelector('.lib-toolbar-generate-btn-label');
      var missing = currentItems.filter(function (it) { return !it.has_image; });
      if (!missing.length) {
        labelSpan.textContent = 'Nothing missing';
        setTimeout(function () { labelSpan.textContent = tr('build.generate', 'Generate'); }, 1500);
        return;
      }

      isBulkGenerating = true;
      cancelRequested = false;
      generateBtn.classList.add('lib-toolbar-generate-btn--stop');
      if (generateBtnIcon) generateBtnIcon.innerHTML = RING_SVG;
      var total = missing.length;
      var done = 0;
      var failed = 0;
      var currentStyleId = null;
      var errorEl = document.getElementById('lib-generate-error');
      if (errorEl) { errorEl.hidden = true; errorEl.textContent = ''; }

      function finish(stopped) {
        isBulkGenerating = false;
        generateBtn.classList.remove('lib-toolbar-generate-btn--stop');
        if (generateBtnIcon) generateBtnIcon.innerHTML = generateBtnIdleIcon;
        if (currentStyleId != null) setCardGenerating(currentStyleId, false);
        labelSpan.textContent = stopped ? 'Stopped' : (failed ? (failed + '/' + total + ' failed') : tr('build.generate', 'Generate'));
        if (stopped || failed) setTimeout(function () { labelSpan.textContent = tr('build.generate', 'Generate'); }, 2500);
      }

      function next() {
        if (cancelRequested) { finish(true); return; }
        if (done >= total) { finish(false); return; }
        var style = missing[done];
        currentStyleId = style.id;
        labelSpan.textContent = 'Stop (' + (done + 1) + '/' + total + ')';
        setCardGenerating(style.id, true);
        generateStyleImageForModel(style, selectedModelId)
          .then(function (url) { setCardImage(style.id, url); })
          .catch(function (err) {
            failed++;
            setCardGenerating(style.id, false);
            console.error('[Library] Generate failed for style', style.id, err);
            if (errorEl) {
              errorEl.hidden = false;
              errorEl.textContent = '"' + (style.name || style.id) + '": ' + ((err && err.message) || 'Unknown error');
            }
          })
          .then(function () { done++; next(); });
      }
      next();
    });
  }

  /* ── Grid zoom ────────────────────────────────────────────────────────────
     Same idea as the flow engine's results-grid zoom (--ncf-grid-min driving
     minmax(var,1fr)) — here it drives --lib-grid-min on #lib-grid. */
  var LIB_GRID_ZOOM_KEY     = 'oj-library-grid-zoom-v1';
  var LIB_GRID_ZOOM_MIN     = 110;
  var LIB_GRID_ZOOM_MAX     = 320;
  var LIB_GRID_ZOOM_STEP    = 30;
  var LIB_GRID_ZOOM_DEFAULT = 200;
  var libGridZoomResetBtn = document.getElementById('lib-grid-zoom-reset');
  var libGridZoomInBtn    = document.getElementById('lib-grid-zoom-in');
  var libGridZoomOutBtn   = document.getElementById('lib-grid-zoom-out');
  var libGridZoom = LIB_GRID_ZOOM_DEFAULT;

  function applyLibGridZoom() {
    var bounded = Math.max(LIB_GRID_ZOOM_MIN, Math.min(LIB_GRID_ZOOM_MAX, libGridZoom));
    libGridZoom = bounded;
    // No forced reflow here (a `void grid.offsetWidth` used to sit right
    // after this set) — issue #55: that synchronous layout read was
    // collapsing whatever picked up --lib-grid-min to an instant jump
    // instead of letting it animate. #lib-grid itself is now flex-wrap, not
    // CSS Grid (nomad_studio.css) — each card's own `width` (a plain,
    // already-animatable property) is what actually transitions, driven by
    // this var; the switch away from Grid's auto-fill also fixed a second,
    // separate issue: Grid recomputes column COUNT as a step function of
    // container width vs track min-size, so cards near a row boundary used
    // to teleport to a new row in one frame in the middle of a zoom even
    // when the track-size itself was transitioning fine — verified by
    // sampling card positions frame-by-frame. Same mechanism Album's own
    // card-zoom already uses (.album-grid/.album-rp-card, album_gallery.js).
    grid.style.setProperty('--lib-grid-min', bounded + 'px');
    if (libGridZoomInBtn)  libGridZoomInBtn.disabled  = bounded >= LIB_GRID_ZOOM_MAX;
    if (libGridZoomOutBtn) libGridZoomOutBtn.disabled = bounded <= LIB_GRID_ZOOM_MIN;
  }

  function persistLibGridZoom() {
    try { localStorage.setItem(LIB_GRID_ZOOM_KEY, String(libGridZoom)); } catch (_) { /* ignore */ }
  }

  (function restoreLibGridZoom() {
    try {
      var raw = Number(localStorage.getItem(LIB_GRID_ZOOM_KEY));
      if (raw) libGridZoom = raw;
    } catch (_) { /* ignore */ }
    applyLibGridZoom();
  })();

  if (libGridZoomResetBtn) libGridZoomResetBtn.addEventListener('click', function () {
    libGridZoom = LIB_GRID_ZOOM_DEFAULT; applyLibGridZoom(); persistLibGridZoom();
  });
  if (libGridZoomInBtn) libGridZoomInBtn.addEventListener('click', function () {
    libGridZoom += LIB_GRID_ZOOM_STEP; applyLibGridZoom(); persistLibGridZoom();
  });
  if (libGridZoomOutBtn) libGridZoomOutBtn.addEventListener('click', function () {
    libGridZoom -= LIB_GRID_ZOOM_STEP; applyLibGridZoom(); persistLibGridZoom();
  });

  // Prefetch counts for every tab (so the sidebar shows numbers up front),
  // then load the first category's grid. Styles' endpoint needs
  // selectedModelId, set asynchronously by loadModelOptions() — load the
  // active category only after that resolves, or a Styles-first page load
  // races it and every card comes back with has_image:false.
  renderNav();
  var modelOptionsReady = loadModelOptions();
  CATEGORIES.forEach(function (cat) {
    if (cat.id !== activeId) fetchItems(cat).catch(function () {});
  });
  modelOptionsReady.then(function () { loadCategory(activeId); }, function () { loadCategory(activeId); });
})();
