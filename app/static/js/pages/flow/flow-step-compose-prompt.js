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

function _openComposePromptModal(onSelect) {
  _loadComposePrompts(function () {
    var modal   = document.getElementById('ncf-compose-prompt-modal');
    var listEl  = document.getElementById('ncf-compose-prompt-modal-list');
    var closeEl = document.getElementById('ncf-compose-prompt-modal-close');
    if (!modal || !listEl) return;

    listEl.innerHTML = '';

    // "Default" option
    var items = [{ id: '', label: 'Default', text: _composePromptState.baseText || _composePromptState.defaultText }]
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
      nameEl.textContent = item.label;
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
        modal.hidden = true;
        if (onSelect) onSelect(item.label, _getActiveComposePromptText());
      }

      row.addEventListener('click', select);
      row.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); } });
      listEl.appendChild(row);
    });

    modal.hidden = false;

    function closeModal() { modal.hidden = true; closeEl.removeEventListener('click', closeModal); modal.removeEventListener('click', backdropClose); }
    function backdropClose(e) { if (e.target === modal) closeModal(); }
    closeEl.addEventListener('click', closeModal);
    modal.addEventListener('click', backdropClose);
  });
}

function renderComposePromptChip(stepDef, el) {
  var chipBlock = document.createElement('div');
  chipBlock.className = 'nse-control-block';

  var chipLabel = document.createElement('p');
  chipLabel.className = 'nsc-param-title';
  chipLabel.textContent = 'Prompt';
  chipBlock.appendChild(chipLabel);

  var chip = document.createElement('button');
  chip.type = 'button';
  chip.className = 'ncf-compose-prompt-chip';
  chip.setAttribute('aria-haspopup', 'dialog');

  var chipIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  chipIcon.setAttribute('viewBox', '0 0 16 16');
  chipIcon.setAttribute('aria-hidden', 'true');
  chipIcon.setAttribute('class', 'ncf-compose-chip-icon');
  chipIcon.innerHTML = '<path d="M2 4h12M2 8h8M2 12h5"/>';
  chip.appendChild(chipIcon);

  var chipNameEl = document.createElement('span');
  chipNameEl.className = 'ncf-compose-chip-name';
  chipNameEl.textContent = '…';
  chip.appendChild(chipNameEl);

  var chipChevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  chipChevron.setAttribute('viewBox', '0 0 16 16');
  chipChevron.setAttribute('aria-hidden', 'true');
  chipChevron.setAttribute('class', 'nse-model-hint-chevron');
  chipChevron.innerHTML = '<path d="M4 6l4 4 4-4"/>';
  chip.appendChild(chipChevron);

  // Load and set initial label
  _loadComposePrompts(function () {
    chipNameEl.textContent = _getActiveComposePromptLabel();
  });

  chip.addEventListener('click', function () {
    _openComposePromptModal(function (label) {
      chipNameEl.textContent = label;
    });
  });

  chipBlock.appendChild(chip);
  el.appendChild(chipBlock);
}

// ── llm_transform ──────────────────────────────────────────────────────────
