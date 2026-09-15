'use strict';
// Step: template_picker → renderTemplatePicker
// Browse the Build-page "Templates" catalog (pack -> theme -> template, each
// with a {placeholder} prompt string and a reference image) and fill in the
// placeholders to build a plain prompt string. Output field is 'prompt_text'
// — same convention as prompt_input — so the action step's input_map can
// reference it identically (steps.<id>.output.prompt_text).
//
// Both halves are right-side panels now, not a centered modal and not a wall
// of inline selects:
//
//   Choose a template  — search + theme tree + Nomad cards, the same shape as
//     "Choose a Style" (_openStylePickerPanel). The modal it replaces used a
//     fixed-width column for themes: with ~200 theme names the list overflowed
//     its own box and the labels overlapped each other into an unreadable
//     stack, and its cards were bare images with a caption bar rather than the
//     product's own card.
//   Fill template — one combobox per placeholder. The old form offered a
//     <select> plus a "Custom…" option that revealed a second input, so typing
//     your own value took two controls and a discovery step. Here every field
//     is a text box you can just type in, with its catalogue values one click
//     away in the same control.

// How many cards one view of the grid shows before it asks you to filter.
var _TPL_GRID_LIMIT = 120;

var _templatePacksCache = null;
var _templateFieldValuesCache = {};

function _tplParsePlaceholders(text) {
  var re = /\{([^}]+)\}/g;
  var seen = {};
  var out = [];
  var m;
  while ((m = re.exec(text || ''))) {
    if (!seen[m[1]]) { seen[m[1]] = true; out.push(m[1]); }
  }
  return out;
}

function _tplImageUrl(item) {
  var first = item && item.images && item.images[0];
  return first && first.filename ? '/static/images/' + first.filename : '';
}

function _tplThemeList(items) {
  var seen = {};
  var out = [];
  items.forEach(function (it) {
    var t = (it.theme || '').trim();
    if (t && !seen[t]) { seen[t] = true; out.push(t); }
  });
  out.sort(function (a, b) { return a.localeCompare(b); });
  return out;
}

function _tplLabel(key) {
  var s = String(key || '').replace(/_/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function _loadTemplatePacksOnce() {
  if (_templatePacksCache) return Promise.resolve(_templatePacksCache);
  var p = (window.openJourneyApi && typeof window.openJourneyApi.getTemplatePacks === 'function')
    ? window.openJourneyApi.getTemplatePacks()
    : fetch('/api/template-packs').then(function (r) { return r.json(); });
  return p.then(function (data) {
    _templatePacksCache = (data && data.templatePacks) || [];
    return _templatePacksCache;
  }).catch(function (err) {
    console.error('[FlowEngine] Failed to load template packs:', err);
    _templatePacksCache = [];
    return _templatePacksCache;
  });
}

function _loadTemplateFieldValues(pack, theme) {
  var key = String(pack || '') + '::' + String(theme || '');
  if (_templateFieldValuesCache[key]) return Promise.resolve(_templateFieldValuesCache[key]);
  var p = (window.openJourneyApi && typeof window.openJourneyApi.getTemplatePackFieldValues === 'function')
    ? window.openJourneyApi.getTemplatePackFieldValues(pack, theme)
    : fetch('/api/template-packs/field-values/' + encodeURIComponent(pack) + '/' + encodeURIComponent(theme)).then(function (r) { return r.json(); });
  return p.then(function (data) {
    var values = (data && data.values) || {};
    _templateFieldValuesCache[key] = values;
    return values;
  }).catch(function (err) {
    console.error('[FlowEngine] Failed to load template field values:', err);
    _templateFieldValuesCache[key] = {};
    return {};
  });
}

// ── Panel 1: Choose a template ───────────────────────────────────────────────

function _tplCardHtml(item) {
  var img = _tplImageUrl(item);
  var imgBlock = img
    ? '<img src="' + escHtml(img) + '" alt="" loading="lazy" onerror="this.closest(\'.lib-style-card-img-wrap\').classList.add(\'lib-style-card-img-wrap--fallback\')">'
    : '';
  return (
    '<div class="lib-style-card-outer">' +
      '<button type="button" class="rp-card lib-style-card ncf-template-card" ' +
        'data-template-id="' + escHtml(String(item.id)) + '">' +
        '<div class="rp-card-media lib-style-card-img-wrap' + (img ? '' : ' lib-style-card-img-wrap--fallback') + '">' +
          imgBlock +
          '<i data-lucide="layout-template" class="lib-style-card-fallback-icon" aria-hidden="true"></i>' +
        '</div>' +
        '<div class="rp-card-body">' +
          '<p class="rp-card-name">' + escHtml(item.name || 'Untitled') + '</p>' +
          (item.theme ? '<p class="lib-style-card-category">' + escHtml(item.theme) + '</p>' : '') +
        '</div>' +
      '</button>' +
    '</div>'
  );
}

// `lock` ({pack, theme}) comes from Refine > Presets > <Pack> > <Theme>: the
// same panel, but only that theme's cards — no theme list, no search, since
// there is nothing to navigate between. The panel title names the theme.
function _openTemplatePickerPanel(onPick, lock) {
  openOptionsPanel(lock ? lock.theme : 'Choose a template', function (body) {
    body.innerHTML = lock
      ? '<div class="ncf-style-picker-layout">' +
          '<div class="ncf-style-picker-grid ncf-style-picker-grid--tpl"></div>' +
        '</div>'
      : '<div class="ncf-style-picker-search-row">' +
          '<input type="text" class="nsc-input ncf-style-picker-search" placeholder="Search templates…" aria-label="Search templates">' +
        '</div>' +
        '<div class="ncf-style-picker-layout">' +
          '<nav class="ncf-style-picker-tree ncf-style-picker-tree--wide" aria-label="Template themes"></nav>' +
          '<div class="ncf-style-picker-grid ncf-style-picker-grid--tpl"></div>' +
        '</div>';

    var searchInput = body.querySelector('.ncf-style-picker-search');
    var treeEl = body.querySelector('.ncf-style-picker-tree');
    var gridEl = body.querySelector('.ncf-style-picker-grid');

    var allItems = [];
    var selectedTheme = '';
    var query = '';

    function renderTree() {
      if (!treeEl) return;
      var themes = _tplThemeList(allItems);
      var html = '<button type="button" class="lib-style-cat-tree-item' +
        (selectedTheme === '' ? ' is-active' : '') + '" data-theme="">All</button>';
      html += themes.map(function (t) {
        return '<button type="button" class="lib-style-cat-tree-item' +
          (selectedTheme === t ? ' is-active' : '') + '" data-theme="' + escHtml(t) + '">' +
          escHtml(t) + '</button>';
      }).join('');
      treeEl.innerHTML = html;
    }

    function renderGrid() {
      var q = query.trim().toLowerCase();
      var filtered = allItems.filter(function (it) {
        if (lock && ((it.pack || '').trim() !== lock.pack || (it.theme || '').trim() !== lock.theme)) return false;
        if (selectedTheme && (it.theme || '').trim() !== selectedTheme) return false;
        if (q) {
          var hay = [it.name, it.theme, it.pack, it.template].join(' ').toLowerCase();
          if (hay.indexOf(q) === -1) return false;
        }
        return true;
      });
      if (!filtered.length) {
        gridEl.innerHTML = '<p class="ncf-style-picker-empty muted-note">' +
          (allItems.length ? 'No templates match.' : 'No templates found.') + '</p>';
        return;
      }
      // The catalogue is 2274 templates. Rendering them all built a 2.3MB,
      // 26k-node grid and, worse, handed the user a wall to scroll rather
      // than something to choose from. Show a page of it and say so — the
      // search box and the theme list are the way through, and now the empty
      // state points at them.
      var shown = filtered.slice(0, _TPL_GRID_LIMIT);
      gridEl.innerHTML = shown.map(_tplCardHtml).join('') +
        (filtered.length > shown.length
          ? '<p class="ncf-tpl-grid-more muted-note">Showing ' + shown.length +
            ' of ' + filtered.length + '. Search above, or pick a theme, to narrow it down.</p>'
          : '');
      if (window.lucide) window.lucide.createIcons();
    }

    if (treeEl) treeEl.addEventListener('click', function (e) {
      var item = e.target.closest('.lib-style-cat-tree-item');
      if (!item) return;
      selectedTheme = item.dataset.theme || '';
      renderTree();
      renderGrid();
    });

    if (searchInput) searchInput.addEventListener('input', function () {
      query = searchInput.value;
      renderGrid();
    });

    gridEl.addEventListener('click', function (e) {
      var card = e.target.closest('.ncf-template-card');
      if (!card) return;
      var item = allItems.find(function (x) { return String(x.id) === card.dataset.templateId; });
      if (!item) return;
      onPick(item);
      closeOptionsPanel();
    });

    gridEl.innerHTML = '<p class="ncf-style-picker-empty muted-note">Loading…</p>';
    _loadTemplatePacksOnce().then(function (items) {
      allItems = items;
      renderTree();
      renderGrid();
    });
  }, { wide: 'xl', flexBody: true });
}

// ── Panel 2: Fill template ───────────────────────────────────────────────────
//
// One row per placeholder. The control is a text input the user can type into
// directly; its catalogue values live behind the chevron beside it, and the
// dice picks one at random. Typing filters that list, so the same control
// serves "I know what I want" and "show me what there is".

function _tplFillRowHtml(key) {
  return (
    '<div class="ncf-tplfill-row" data-field-key="' + escHtml(key) + '">' +
      '<label class="ncf-tplfill-label" for="ncf-tplfill-' + escHtml(key) + '">' +
        escHtml(_tplLabel(key)) + '</label>' +
      '<div class="ncf-tplfill-control">' +
        '<input type="text" class="nsc-input ncf-tplfill-input" id="ncf-tplfill-' + escHtml(key) + '" ' +
          'data-field-key="' + escHtml(key) + '" autocomplete="off" ' +
          'placeholder="Type anything, or pick one →">' +
        '<button type="button" class="ncf-tplfill-btn ncf-tplfill-dice" data-field-key="' + escHtml(key) + '" ' +
          'aria-label="Random value">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">' +
            '<rect x="3" y="3" width="18" height="18" rx="3"/>' +
            '<circle cx="8.5" cy="8.5" r="1.2" fill="currentColor" stroke="none"/>' +
            '<circle cx="15.5" cy="15.5" r="1.2" fill="currentColor" stroke="none"/>' +
            '<circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/>' +
          '</svg>' +
        '</button>' +
        '<button type="button" class="ncf-tplfill-btn ncf-tplfill-toggle" data-field-key="' + escHtml(key) + '" ' +
          'aria-label="Show suggestions" aria-expanded="false">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">' +
            '<path d="M6 9l6 6 6-6"/></svg>' +
        '</button>' +
      '</div>' +
      // The list is a sibling of the control, not a child of it, so it takes
      // part in the flow and pushes the fields below down. Floating it over
      // them hid the last two of four fields the moment you opened the second.
      '<div class="ncf-tplfill-menu" data-field-key="' + escHtml(key) + '" hidden></div>' +
    '</div>'
  );
}

function _openTemplateFillPanel(state, onApply) {
  openOptionsPanel('Fill template', function (body) {
    var placeholders = _tplParsePlaceholders(state.selected && state.selected.template);

    if (!placeholders.length) {
      body.innerHTML =
        '<p class="ncf-tplfill-empty muted-note">This template has no blanks to fill — ' +
        'its prompt is ready as it is, and you can still edit it in the step below.</p>';
      return;
    }

    body.innerHTML =
      '<div class="ncf-tplfill-head">' +
        '<p class="ncf-tplfill-hint">Every field is yours to type in. The chevron ' +
        'shows what the pack suggests; the dice picks one for you.</p>' +
        '<button type="button" class="nse-modal-secondary ncf-tplfill-randomize">Randomize all</button>' +
      '</div>' +
      '<div class="ncf-tplfill-rows">' + placeholders.map(_tplFillRowHtml).join('') + '</div>' +
      '<div class="ncf-json-panel-footer">' +
        '<button type="button" class="nse-modal-apply ncf-tplfill-apply">Apply</button>' +
      '</div>';

    var rowsEl = body.querySelector('.ncf-tplfill-rows');

    function inputFor(key) {
      return rowsEl.querySelector('.ncf-tplfill-input[data-field-key="' + key + '"]');
    }
    function menuFor(key) {
      return rowsEl.querySelector('.ncf-tplfill-menu[data-field-key="' + key + '"]');
    }
    function optionsFor(key) {
      return state.fieldValues[key] || [];
    }

    function closeAllMenus(except) {
      rowsEl.querySelectorAll('.ncf-tplfill-menu').forEach(function (m) {
        if (m !== except) m.hidden = true;
      });
      rowsEl.querySelectorAll('.ncf-tplfill-toggle').forEach(function (b) {
        var m = menuFor(b.dataset.fieldKey);
        b.setAttribute('aria-expanded', m && !m.hidden ? 'true' : 'false');
      });
    }

    // `filter` is off when the chevron opens the list and on while typing.
    // Filtering on open was wrong and the first test caught it: the field
    // arrives prefilled with a catalogue value, so "show me the options"
    // matched only the option already in the box — one item, every time.
    function renderMenu(key, filter) {
      var menu = menuFor(key);
      if (!menu) return;
      var typed = filter ? (inputFor(key).value || '').trim().toLowerCase() : '';
      var opts = optionsFor(key).filter(function (v) {
        return !typed || String(v).toLowerCase().indexOf(typed) !== -1;
      });
      if (!opts.length) {
        menu.innerHTML = '<p class="ncf-tplfill-menu-empty muted-note">' +
          (optionsFor(key).length ? 'Nothing matches — what you typed is used as is.'
                                  : 'This field has no suggestions. Type your own.') + '</p>';
        return;
      }
      menu.innerHTML = opts.map(function (v) {
        return '<button type="button" class="ncf-tplfill-opt" data-value="' + escHtml(v) + '">' +
          escHtml(v) + '</button>';
      }).join('');
    }

    function setValue(key, value, opts) {
      state.choices[key] = value;
      var inp = inputFor(key);
      if (inp && (!opts || !opts.skipInput)) inp.value = value;
      onApply(false);
    }

    rowsEl.addEventListener('input', function (e) {
      var inp = e.target.closest('.ncf-tplfill-input');
      if (!inp) return;
      setValue(inp.dataset.fieldKey, inp.value, { skipInput: true });
      var typingMenu = menuFor(inp.dataset.fieldKey);
      if (typingMenu && !typingMenu.hidden) renderMenu(inp.dataset.fieldKey, true);
    });

    rowsEl.addEventListener('click', function (e) {
      var toggle = e.target.closest('.ncf-tplfill-toggle');
      if (toggle) {
        var key = toggle.dataset.fieldKey;
        var menu = menuFor(key);
        var willOpen = menu.hidden;
        closeAllMenus(willOpen ? menu : null);
        if (willOpen) { renderMenu(key, false); menu.hidden = false; }
        else menu.hidden = true;
        toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        return;
      }

      var dice = e.target.closest('.ncf-tplfill-dice');
      if (dice) {
        var dkey = dice.dataset.fieldKey;
        var dopts = optionsFor(dkey);
        if (dopts.length) setValue(dkey, dopts[Math.floor(Math.random() * dopts.length)]);
        return;
      }

      var opt = e.target.closest('.ncf-tplfill-opt');
      if (opt) {
        var okey = opt.closest('.ncf-tplfill-menu').dataset.fieldKey;
        setValue(okey, opt.dataset.value);
        closeAllMenus();
        return;
      }
    });

    body.querySelector('.ncf-tplfill-randomize').addEventListener('click', function () {
      placeholders.forEach(function (key) {
        var opts = optionsFor(key);
        if (opts.length) setValue(key, opts[Math.floor(Math.random() * opts.length)]);
      });
      closeAllMenus();
    });

    body.querySelector('.ncf-tplfill-apply').addEventListener('click', function () {
      onApply(true);
      closeOptionsPanel();
    });

    // Values already chosen (including a Refine hand-off) show up filled in.
    _loadTemplateFieldValues(state.selected.pack, state.selected.theme).then(function (values) {
      state.fieldValues = values || {};
      placeholders.forEach(function (key) {
        if (state.choices[key] == null || state.choices[key] === '') {
          var opts = optionsFor(key);
          state.choices[key] = opts.length ? opts[0] : '';
        }
        var inp = inputFor(key);
        if (inp) inp.value = state.choices[key];
      });
      onApply(false);
    });
  }, { wide: true });
}

// ── Step body ────────────────────────────────────────────────────────────────

function renderTemplatePicker(stepDef, el) {
  var wrap = document.createElement('div');
  wrap.className = 'ncf-template-picker';
  el.appendChild(wrap);

  var state = { selected: null, fieldValues: {}, choices: {} };

  // ?pack=&theme= — arriving from a theme in Refine > Presets. Every open of
  // the picker on this page stays inside that theme.
  var lock = null;
  try {
    var qs = new URLSearchParams(window.location.search);
    if (qs.get('pack') && qs.get('theme')) lock = { pack: qs.get('pack').trim(), theme: qs.get('theme').trim() };
  } catch (err) { lock = null; }

  function openChooser() { _openTemplatePickerPanel(selectTemplate, lock); }
  function openFill() { _openTemplateFillPanel(state, function () { recomputePrompt(); }); }

  // The summary card is itself the "choose / change template" control — same
  // idea as the engine select above it: the thing you picked is what you
  // click to pick again. Nothing picked yet, it says so.
  var summaryEl = document.createElement('button');
  summaryEl.type = 'button';
  summaryEl.className = 'ncf-template-summary-card nsc-options-trigger';
  summaryEl.addEventListener('click', openChooser);
  wrap.appendChild(summaryEl);

  // Panel openers live on the step label as icon buttons, like Resolution and
  // Advanced do on every flow page — not as a row of text buttons.
  var stepLabel = el.querySelector('.nsc-step-label') ||
                  (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));

  function labelIconBtn(ariaLabel, svgInner, onClick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'nsc-history-btn nsc-options-trigger';
    b.setAttribute('aria-label', ariaLabel);
    b.title = ariaLabel;
    b.innerHTML =
      '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        svgInner + '</svg>';
    b.addEventListener('click', onClick);
    if (stepLabel) {
      var chevron = stepLabel.querySelector('.nsc-step-chevron');
      if (chevron) stepLabel.insertBefore(b, chevron);
      else stepLabel.appendChild(b);
    } else {
      wrap.insertBefore(b, summaryEl);
    }
    return b;
  }

  labelIconBtn('Choose template',
    '<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/>' +
    '<rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>',
    openChooser);

  var fillBtn = labelIconBtn('Fill template',
    '<path d="M11 2l3 3-8 8-3.5 1 1-3.5z"/>',
    openFill);
  fillBtn.hidden = true;

  var promptTa = document.createElement('textarea');
  promptTa.className = 'nsc-textarea ncf-template-prompt-preview';
  promptTa.rows = 4;
  promptTa.placeholder = 'Pick a template and its prompt appears here — editable, as always.';
  promptTa.addEventListener('input', function () {
    setVal(stepDef.id, 'prompt_text', promptTa.value);
  });
  wrap.appendChild(promptTa);

  function renderSummary() {
    if (!state.selected) {
      summaryEl.classList.add('is-empty');
      summaryEl.innerHTML =
        '<span class="ncf-template-summary-text">' +
          '<span class="ncf-template-summary-name">Choose template</span>' +
        '</span>';
      return;
    }
    summaryEl.classList.remove('is-empty');
    var img = _tplImageUrl(state.selected);
    var blanks = _tplParsePlaceholders(state.selected.template).length;
    summaryEl.innerHTML =
      (img ? '<img src="' + escHtml(img) + '" alt="" class="ncf-template-summary-thumb">' : '') +
      '<span class="ncf-template-summary-text">' +
        '<span class="ncf-template-summary-name">' + escHtml(state.selected.name || 'Untitled') + '</span>' +
        '<span class="ncf-template-summary-theme">' + escHtml(state.selected.theme || '') +
          (blanks ? ' · ' + blanks + (blanks === 1 ? ' blank' : ' blanks') : '') + '</span>' +
      '</span>';
  }
  renderSummary();

  function resolvePrompt() {
    var tpl = (state.selected && state.selected.template) || '';
    return tpl.replace(/\{([^}]+)\}/g, function (_, key) {
      var v = state.choices[key];
      return (v == null || v === '') ? ('{' + key + '}') : v;
    });
  }

  function recomputePrompt() {
    var resolved = resolvePrompt();
    promptTa.value = resolved;
    setVal(stepDef.id, 'prompt_text', resolved);
  }

  function selectTemplate(item) {
    state.selected = item;
    state.choices = {};
    state.fieldValues = {};
    setVal(stepDef.id, 'template_id', item.id);
    setVal(stepDef.id, 'template_image_url', _tplImageUrl(item));
    renderSummary();

    var placeholders = _tplParsePlaceholders(item.template);
    fillBtn.hidden = !placeholders.length;
    recomputePrompt();

    // Prefill from the pack so the prompt is generatable the moment a template
    // is picked — opening "Fill template" is then an edit, not a chore.
    if (placeholders.length) {
      _loadTemplateFieldValues(item.pack, item.theme).then(function (values) {
        state.fieldValues = values || {};
        placeholders.forEach(function (key) {
          var opts = state.fieldValues[key] || [];
          if (opts.length && !state.choices[key]) state.choices[key] = opts[0];
        });
        recomputePrompt();
      });
    }
  }

  // ── Deep-link auto-apply ──────────────────────────────────────────────
  // "Apply Template" from Refine > Presets > <Pack> > <Theme> (see
  // ns_refine_pack_composer.js) hands off here via sessionStorage instead
  // of a URL — avoids fighting query-string encoding for a whole choices
  // object, and self-clears so a page refresh doesn't re-apply it. Consumed
  // once, on the first template_picker step mounted after the handoff.
  (function tryAutoApplyFromHandoff() {
    var raw;
    try { raw = sessionStorage.getItem('ns_pending_template_apply'); } catch (err) { raw = null; }
    if (!raw) {
      // Coming in from a theme with nothing picked yet: its cards are the
      // first thing to see. Deferred a tick so the click that navigated here
      // can't count as an outside click and close the panel straight away.
      if (lock) setTimeout(function () { _openTemplatePickerPanel(selectTemplate, lock); }, 0);
      return;
    }
    try { sessionStorage.removeItem('ns_pending_template_apply'); } catch (err) { /* ignore */ }

    var pending;
    try { pending = JSON.parse(raw); } catch (err) { pending = null; }
    if (!pending || pending.templateId == null) return;

    _loadTemplatePacksOnce().then(function (items) {
      var item = items.find(function (it) { return String(it.id) === String(pending.templateId); });
      if (!item) return;
      selectTemplate(item);
      var choices = pending.choices || null;
      if (!choices) return;
      // Land the handed-over values after selectTemplate's own prefill resolves,
      // or that prefill overwrites them with the pack's first option.
      _loadTemplateFieldValues(item.pack, item.theme).then(function () {
        Object.keys(choices).forEach(function (key) { state.choices[key] = choices[key]; });
        recomputePrompt();
      });
    });
  })();
}
