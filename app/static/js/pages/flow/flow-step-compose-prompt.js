'use strict';
// Step: compose-prompt → _loadComposePrompts, renderComposePromptChip

function _loadComposePrompts(cb) {
  if (_composePromptState.loaded) { cb(); return; }
  fetch('/api/models/settings/compose-prompts')
    .then(function (r) { return r.json(); })
    .then(function (json) {
      _composePromptState.defaultText = (json.defaults && json.defaults.main) || '';
      var saved = (json.prompts && json.prompts.main) || '';
      _composePromptState.baseText = saved || _composePromptState.defaultText;
      _composePromptState.variants = Array.isArray(json.promptVariants && json.promptVariants.main)
        ? json.promptVariants.main : [];
      _composePromptState.activeId  = (json.promptActiveVariants && json.promptActiveVariants.main) || '';
      _composePromptState.loaded = true;
      cb();
    })
    .catch(function () { _composePromptState.loaded = true; cb(); });
}

function _getActiveComposePromptText() {
  if (_composePromptState.activeId) {
    var v = _composePromptState.variants.find(function (v) { return v.id === _composePromptState.activeId; });
    if (v) return v.text;
  }
  return _composePromptState.baseText || _composePromptState.defaultText;
}

function _getActiveComposePromptLabel() {
  if (_composePromptState.activeId) {
    var v = _composePromptState.variants.find(function (v) { return v.id === _composePromptState.activeId; });
    if (v) return v.label;
  }
  return 'Default';
}

// Side panel (never a modal) listing Default + the variants saved in Settings.
function _openComposePromptPanel(onSelect) {
  _loadComposePrompts(function () {
    openOptionsPanel(tF('Prompt'), function (panelBody) {
      var listEl = document.createElement('div');
      listEl.className = 'nse-model-list';
      listEl.setAttribute('role', 'listbox');
      panelBody.appendChild(listEl);
      _fillComposePromptList(listEl, onSelect);
    });
  });
}

function _fillComposePromptList(listEl, onSelect) {
    // "Default" option
    var items = [{ id: '', label: tF('Default'), text: _composePromptState.baseText || _composePromptState.defaultText }]
      .concat(_composePromptState.variants);

    items.forEach(function (item) {
      var isActive = item.id === _composePromptState.activeId;
      var row = document.createElement('div');
      row.className = 'nse-model-item' + (isActive ? ' is-active' : '');
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(isActive));
      row.tabIndex = 0;

      var nameEl = document.createElement('span');
      nameEl.className = 'nse-model-name';
      nameEl.textContent = item.id ? item.label : tF(item.label);
      row.appendChild(nameEl);

      if (isActive) {
        var checkEl = document.createElement('span');
        checkEl.className = 'nse-model-check';
        checkEl.setAttribute('aria-hidden', 'true');
        checkEl.innerHTML = '<svg viewBox="0 0 16 16"><path d="M3 8l4 4 6-8"/></svg>';
        row.appendChild(checkEl);
      }

      function select() {
        _composePromptState.activeId = item.id;
        // Persist active variant choice
        fetch('/api/models/settings/compose-prompts', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ promptActiveVariants: { main: item.id } }),
        }).catch(function () {});
        closeOptionsPanel();
        if (onSelect) onSelect(item.id ? item.label : tF(item.label), _getActiveComposePromptText());
      }

      row.addEventListener('click', select);
      row.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); } });
      listEl.appendChild(row);
    });
}

// Settings' compose prompt ("Default" or a saved variant) is only a fallback:
// flow-render-all.js sends the step's own system_prompts when it has them, so
// on those steps the chip would change nothing — it isn't shown at all.
// Same title-row pattern as Genre (flow-step-llm-transform.js).
function renderComposePromptChip(stepDef, el) {
  var sys = stepDef && stepDef.system_prompts;
  if (sys && typeof sys === 'object' && Object.keys(sys).length) return;

  var chipBlock = document.createElement('div');
  chipBlock.className = 'nse-control-block';
  chipBlock.innerHTML =
    '<p class="nsc-param-title nsc-param-title--flex"><span class="ncf-compose-chip-title"></span> ' +
    '<span class="nsc-param-value"></span>' +
    '<button type="button" class="nsc-history-btn nsc-options-trigger"></button>' +
    '</p>';
  chipBlock.querySelector('.ncf-compose-chip-title').textContent = tF('Prompt');
  var valueEl = chipBlock.querySelector('.nsc-param-value');
  var btn = chipBlock.querySelector('.nsc-options-trigger');
  btn.setAttribute('aria-label', tF('Choose prompt'));
  btn.innerHTML =
    '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">' +
      '<path d="M3 5h12M3 9h9M3 13h6"/>' +
    '</svg>';
  valueEl.textContent = '…';

  _loadComposePrompts(function () {
    var label = _getActiveComposePromptLabel();
    valueEl.textContent = _composePromptState.activeId ? label : tF(label);
  });

  btn.addEventListener('click', function () {
    _openComposePromptPanel(function (label) { valueEl.textContent = label; });
  });

  el.appendChild(chipBlock);
}

// ── llm_transform ──────────────────────────────────────────────────────────
