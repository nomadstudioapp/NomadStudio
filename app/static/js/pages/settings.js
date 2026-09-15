document.body.classList.add('settings-page');

// i18n.js loads earlier in base.html and exposes window.NomadI18n.t(key,
// fallback) — this file only builds DOM dynamically (tabs, variant panels,
// status toasts), which data-i18n in the HTML can't reach. `vars` is an
// optional {token: value} map for simple `{token}` interpolation in the
// translated string (used for messages like `Variant "{label}" deleted.`).
function t(key, fallback, vars) {
  var text = window.NomadI18n ? window.NomadI18n.t(key, fallback) : fallback;
  if (vars) {
    Object.keys(vars).forEach(function (k) {
      text = text.replace('{' + k + '}', vars[k]);
    });
  }
  return text;
}

// ---------------------------------------------------------------------------
// Output directory section
// ---------------------------------------------------------------------------
(async function outputSection() {
  const inputEl = document.getElementById('output-dir-input');
  const browseBtn = document.getElementById('browse-output-dir-btn');
  const testBtn = document.getElementById('test-output-dir-btn');
  const clearBtn = document.getElementById('clear-output-dir-btn');
  const statusEl = document.getElementById('output-dir-status');
  const statusRowEl = document.getElementById('output-dir-status-row');

  if (!inputEl || !browseBtn || !testBtn || !clearBtn || !statusEl || !statusRowEl) return;

  let saveTimer = null;
  let lastSavedDir = '';

  function setStatus(message, level = 'neutral') {
    statusEl.textContent = message;
    statusRowEl.classList.remove('is-success', 'is-warning', 'is-error');
    if (level === 'success') statusRowEl.classList.add('is-success');
    if (level === 'warning') statusRowEl.classList.add('is-warning');
    if (level === 'error') statusRowEl.classList.add('is-error');
  }

  // Set synchronously (not via data-i18n in the HTML) — i18n.js applies its
  // own dict to any element still carrying data-i18n whenever its async
  // fetch resolves, which can race AFTER this section's fetch already
  // replaced the placeholder with the real status, stomping it back to
  // "Loading...". Since this element's content is 100% JS-owned from here
  // on, translating it once here (not tagging it in the HTML) avoids that.
  setStatus(t('settings.common.loading', 'Loading...'));

  async function saveOutputDir(dir, source = 'manual') {
    try {
      const res = await fetch('/api/models/settings/output-dir', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outputDir: dir }),
      });
      const json = await res.json();
      if (!res.ok) {
        setStatus(json.error || t('settings.output.saveFailed', 'Failed to save output folder.', { reason: '' }), 'error');
        return false;
      }

      lastSavedDir = dir;
      if (!dir) {
        setStatus(t('settings.output.noConfig', 'No output folder configured.'), 'warning');
      } else if (source === 'browse') {
        setStatus(t('settings.folderStatus.selectedAndSaved', 'Folder selected and saved.'), 'success');
      } else {
        setStatus(t('settings.folderStatus.pathSavedAuto', 'Path saved automatically.'), 'success');
      }

      const gateBanner = document.getElementById('output-dir-gate-banner');
      if (gateBanner) gateBanner.remove();
      return true;
    } catch (error) {
      setStatus(t('settings.output.saveFailed', 'Failed to save output folder: ' + error.message, { reason: error.message }), 'error');
      return false;
    }
  }

  function scheduleAutosave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const dir = inputEl.value.trim();
      if (dir === lastSavedDir) return;
      await saveOutputDir(dir, 'autosave');
    }, 550);
  }

  try {
    const res = await fetch('/api/models/settings');
    if (!res.ok) throw new Error('Failed to load settings');
    const json = await res.json();
    const dir = String(json?.settings?.outputDir || '').trim();
    inputEl.value = dir;
    lastSavedDir = dir;
    if (!dir) {
      setStatus(t('settings.output.noConfigHint', 'No output folder configured. Add one to enable file output.'), 'warning');
      inputEl.focus();
    } else {
      setStatus(t('settings.folderStatus.pathLoaded', 'Path loaded from current settings.'), 'success');
    }
  } catch (error) {
    setStatus(t('settings.folderStatus.loadFailed', 'Failed to load current settings.'), 'error');
  }

  browseBtn.addEventListener('click', async () => {
    browseBtn.disabled = true;
    setStatus(t('settings.folderStatus.openingPicker', 'Opening folder picker...'), 'neutral');
    try {
      const res = await fetch('/api/models/settings/output-dir/browse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current: inputEl.value.trim() }),
      });
      const json = await res.json();
      if (res.ok && json.ok && json.outputDir) {
        inputEl.value = String(json.outputDir).trim();
        await saveOutputDir(inputEl.value.trim(), 'browse');
      } else if (json.cancelled) {
        setStatus(t('settings.folderStatus.pickerCanceled', 'Folder picker canceled.'), 'warning');
      } else {
        setStatus(json.error || t('settings.folderStatus.pickerFailed', 'Folder picker failed.', { reason: '' }), 'error');
      }
    } catch (error) {
      setStatus(t('settings.folderStatus.pickerFailed', 'Folder picker failed: ' + error.message, { reason: error.message }), 'error');
    } finally {
      browseBtn.disabled = false;
    }
  });

  inputEl.addEventListener('input', scheduleAutosave);
  inputEl.addEventListener('blur', async () => {
    if (saveTimer) clearTimeout(saveTimer);
    const dir = inputEl.value.trim();
    if (dir !== lastSavedDir) await saveOutputDir(dir, 'blur');
  });

  testBtn.addEventListener('click', async () => {
    const dir = inputEl.value.trim();
    if (!dir) {
      setStatus(t('settings.folderStatus.enterPathFirst', 'Enter a path before testing.'), 'warning');
      return;
    }
    testBtn.disabled = true;
    try {
      const res = await fetch('/api/models/settings/output-dir/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outputDir: dir }),
      });
      const json = await res.json();
      if (res.ok && json.ok) {
        setStatus(t('settings.output.verified', 'Path verified and writable.'), 'success');
      } else {
        setStatus(json.error || t('settings.output.testFailed', 'Path test failed.', { reason: '' }), 'error');
      }
    } catch (error) {
      setStatus(t('settings.output.testFailed', 'Path test failed: ' + error.message, { reason: error.message }), 'error');
    } finally {
      testBtn.disabled = false;
    }
  });

  clearBtn.addEventListener('click', async () => {
    inputEl.value = '';
    if (saveTimer) clearTimeout(saveTimer);
    await saveOutputDir('', 'clear');
  });
})();

// ---------------------------------------------------------------------------
// ComfyUI models folder section
// ---------------------------------------------------------------------------
(async function comfyModelsFolderSection() {
  const inputEl = document.getElementById('comfy-models-folder-input');
  const browseBtn = document.getElementById('browse-comfy-models-folder-btn');
  const testBtn = document.getElementById('test-comfy-models-folder-btn');
  const clearBtn = document.getElementById('clear-comfy-models-folder-btn');
  const statusEl = document.getElementById('comfy-models-folder-status');
  const statusRowEl = document.getElementById('comfy-models-folder-status-row');

  if (!inputEl || !browseBtn || !testBtn || !clearBtn || !statusEl || !statusRowEl) return;

  let saveTimer = null;
  let lastSavedFolder = '';

  function setStatus(message, level = 'neutral') {
    statusEl.textContent = message;
    statusRowEl.classList.remove('is-success', 'is-warning', 'is-error');
    if (level === 'success') statusRowEl.classList.add('is-success');
    if (level === 'warning') statusRowEl.classList.add('is-warning');
    if (level === 'error') statusRowEl.classList.add('is-error');
  }

  // See the matching comment in outputSection() above — same race with
  // i18n.js's async data-i18n pass, same fix (JS-owned from here on).
  setStatus(t('settings.common.loading', 'Loading...'));

  async function saveModelsFolder(folder, source = 'manual') {
    try {
      const res = await fetch('/api/models/settings/models-folder', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comfyModelsFolder: folder }),
      });
      const json = await res.json();
      if (!res.ok) {
        setStatus(json.error || t('settings.comfy.saveFailed', 'Failed to save models folder.', { reason: '' }), 'error');
        return false;
      }

      lastSavedFolder = folder;
      if (!folder) {
        setStatus(t('settings.comfy.noConfig', 'No ComfyUI models folder configured.'), 'warning');
      } else if (source === 'browse') {
        setStatus(t('settings.folderStatus.selectedAndSaved', 'Folder selected and saved.'), 'success');
      } else {
        setStatus(t('settings.folderStatus.pathSavedAuto', 'Path saved automatically.'), 'success');
      }
      return true;
    } catch (error) {
      setStatus(t('settings.comfy.saveFailed', 'Failed to save models folder: ' + error.message, { reason: error.message }), 'error');
      return false;
    }
  }

  function scheduleAutosave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const folder = inputEl.value.trim();
      if (folder === lastSavedFolder) return;
      await saveModelsFolder(folder, 'autosave');
    }, 550);
  }

  try {
    const res = await fetch('/api/models/settings');
    if (!res.ok) throw new Error('Failed to load settings');
    const json = await res.json();
    const folder = String(json?.settings?.comfyModelsFolder || '').trim();
    inputEl.value = folder;
    lastSavedFolder = folder;
    if (!folder) {
      setStatus(t('settings.comfy.noConfigHint', 'No ComfyUI models folder configured. Add one to see file status and enable auto-download.'), 'warning');
    } else {
      setStatus(t('settings.folderStatus.pathLoaded', 'Path loaded from current settings.'), 'success');
    }
  } catch (error) {
    setStatus(t('settings.folderStatus.loadFailed', 'Failed to load current settings.'), 'error');
  }

  browseBtn.addEventListener('click', async () => {
    browseBtn.disabled = true;
    setStatus(t('settings.folderStatus.openingPicker', 'Opening folder picker...'), 'neutral');
    try {
      const res = await fetch('/api/models/settings/models-folder/browse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current: inputEl.value.trim() }),
      });
      const json = await res.json();
      if (res.ok && json.ok && json.comfyModelsFolder) {
        inputEl.value = String(json.comfyModelsFolder).trim();
        await saveModelsFolder(inputEl.value.trim(), 'browse');
      } else if (json.cancelled) {
        setStatus(t('settings.folderStatus.pickerCanceled', 'Folder picker canceled.'), 'warning');
      } else {
        setStatus(json.error || t('settings.folderStatus.pickerFailed', 'Folder picker failed.', { reason: '' }), 'error');
      }
    } catch (error) {
      setStatus(t('settings.folderStatus.pickerFailed', 'Folder picker failed: ' + error.message, { reason: error.message }), 'error');
    } finally {
      browseBtn.disabled = false;
    }
  });

  inputEl.addEventListener('input', scheduleAutosave);
  inputEl.addEventListener('blur', async () => {
    if (saveTimer) clearTimeout(saveTimer);
    const folder = inputEl.value.trim();
    if (folder !== lastSavedFolder) await saveModelsFolder(folder, 'blur');
  });

  testBtn.addEventListener('click', async () => {
    const folder = inputEl.value.trim();
    if (!folder) {
      setStatus(t('settings.folderStatus.enterPathFirst', 'Enter a path before testing.'), 'warning');
      return;
    }
    testBtn.disabled = true;
    try {
      const res = await fetch('/api/models/settings/models-folder/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comfyModelsFolder: folder }),
      });
      const json = await res.json();
      if (res.ok && json.ok) {
        setStatus(t('settings.comfy.verified', 'Folder found and readable.'), 'success');
      } else {
        setStatus(json.error || t('settings.comfy.testFailed', 'Folder test failed.', { reason: '' }), 'error');
      }
    } catch (error) {
      setStatus(t('settings.comfy.testFailed', 'Folder test failed: ' + error.message, { reason: error.message }), 'error');
    } finally {
      testBtn.disabled = false;
    }
  });

  clearBtn.addEventListener('click', async () => {
    inputEl.value = '';
    if (saveTimer) clearTimeout(saveTimer);
    await saveModelsFolder('', 'clear');
  });
})();

// ---------------------------------------------------------------------------
// Prompts section
// ---------------------------------------------------------------------------
(async function promptsSection() {
  const tabsEl = document.getElementById('prompts-tabs');
  const summaryEl = document.getElementById('prompts-summary');
  const saveBtn = document.getElementById('save-prompts-btn');
  const resetBtn = document.getElementById('reset-prompts-btn');
  const statusEl = document.getElementById('prompts-status');
  const titleEl = document.getElementById('active-prompt-title');
  const badgeEl = document.getElementById('active-prompt-badge');
  const resetActiveBtn = document.getElementById('reset-active-prompt-btn');
  const textareaEl = document.getElementById('active-prompt-textarea');
  const variantsSlotEl = document.getElementById('describe-full-variants-slot');

  if (!tabsEl || !summaryEl || !saveBtn || !resetBtn || !statusEl || !titleEl || !badgeEl || !resetActiveBtn || !textareaEl || !variantsSlotEl) {
    return;
  }

  const state = {
    defaults: {},
    labels: {},
    values: {},
    keys: [],
    activeKey: '',
    isDirty: false,
    promptVariants: {},
    promptActiveVariants: {},
  };

  function getVariantsState(key) {
    const variants = Array.isArray(state.promptVariants[key]) ? state.promptVariants[key] : [];
    const activeId = String(state.promptActiveVariants[key] || '');
    return { variants, activeId };
  }
  function setVariantsState(key, variants, activeId) {
    if (variants !== undefined) state.promptVariants[key] = variants;
    if (activeId !== undefined) state.promptActiveVariants[key] = activeId;
  }

  function normalizePrompt(value) {
    return String(value || '').trim();
  }

  function setPromptsStatus(message, isError = false) {
    statusEl.textContent = message;
    statusEl.classList.toggle('status-error', isError);
  }

  function markDirty() {
    state.isDirty = true;
    saveBtn.style.display = '';
  }

  function clearDirty() {
    state.isDirty = false;
    saveBtn.style.display = 'none';
  }

  function isPromptCustomized(key) {
    return normalizePrompt(state.values[key]) !== normalizePrompt(state.defaults[key]);
  }

  const PROMPT_GROUPS = [
    { label: 'Describe — Text', keys: ['describeFull', 'describeScene', 'describeStyle'] },
    { label: 'Describe — JSON', keys: ['describeFullJson', 'describeSceneJson', 'describeStyleJson'] },
    { label: 'Edit', keys: ['editSingle', 'editVariants'] },
    { label: 'Convert & Other', keys: ['convertToJson', 'convertToJsonEnhanced', 'blendPrompts', 'referencePrompt'] },
  ];

  function getPromptIcon(key) {
    if (key === 'editSingle') return 'message-circle';
    if (key === 'editVariants') return 'brain';
    if (key === 'describeStyle') return 'sparkles';
    if (key === 'describeStyleJson') return 'sparkles';
    if (key === 'describeScene') return 'scan-search';
    if (key === 'describeSceneJson') return 'scan-search';
    if (key === 'describeFull') return 'feather';
    if (key === 'describeFullJson') return 'feather';
    if (key === 'convertToJson') return 'braces';
    if (key === 'convertToJsonEnhanced') return 'file-json-2';
    if (key === 'blendPrompts') return 'shuffle';
    return 'pen-line';
  }

  function getTabLabel(key) {
    const label = state.labels[key] || key;
    return label
      .replace(/Describe Image\s+[—-]\s+/g, '')
      .replace(/Edit Prompt\s+[—-]\s+/g, '')
      .replace('Convert to JSON', 'JSON')
      .replace(/\s*\(JSON\)\s*$/, ' ↗')
      .trim();
  }

  function updateSummary() {
    const total = state.keys.length;
    const customized = state.keys.filter(isPromptCustomized).length;
    summaryEl.textContent = `${total} prompts - ${customized} customized`;
  }

  function updateActivePromptPanel() {
    if (!state.activeKey) return;

    const key = state.activeKey;
    const isCustomized = isPromptCustomized(key);
    titleEl.textContent = state.labels[key] || key;
    badgeEl.textContent = isCustomized ? 'CUSTOMIZED' : 'DEFAULT';
    badgeEl.classList.toggle('is-customized', isCustomized);
    badgeEl.classList.toggle('is-default', !isCustomized);

    resetActiveBtn.style.display = isCustomized ? '' : 'none';
    textareaEl.value = state.values[key] || '';
    textareaEl.dataset.key = key;

    renderVariantsPanel(key);
  }

  function makeTabBtn(key) {
    const tabBtn = document.createElement('button');
    tabBtn.type = 'button';
    tabBtn.className = 'settings-prompt-tab';
    tabBtn.setAttribute('role', 'tab');
    tabBtn.setAttribute('aria-selected', String(state.activeKey === key));
    tabBtn.classList.toggle('is-active', state.activeKey === key);
    tabBtn.dataset.key = key;

    const iconEl = document.createElement('i');
    iconEl.setAttribute('data-lucide', getPromptIcon(key));
    iconEl.setAttribute('aria-hidden', 'true');
    tabBtn.appendChild(iconEl);

    const textEl = document.createElement('span');
    textEl.textContent = getTabLabel(key);
    tabBtn.appendChild(textEl);

    tabBtn.addEventListener('click', () => {
      if (state.activeKey === key) return;
      state.activeKey = key;
      renderTabs();
      updateActivePromptPanel();
    });
    return tabBtn;
  }

  let _activeGroupIndex = 0;

  function renderTabs() {
    tabsEl.innerHTML = '';
    const keySet = new Set(state.keys);
    const renderedKeys = new Set();

    // Build groups array
    const groups = [];
    for (const group of PROMPT_GROUPS) {
      const groupKeys = group.keys.filter((k) => keySet.has(k));
      if (!groupKeys.length) continue;
      groups.push({ label: group.label, keys: groupKeys });
    }
    const ungrouped = state.keys.filter((k) => !renderedKeys.has(k));
    if (ungrouped.length) groups.push({ label: 'Other', keys: ungrouped });

    if (!groups.length) return;
    if (_activeGroupIndex >= groups.length) _activeGroupIndex = 0;

    // ── Group switcher bar ──
    if (groups.length > 1) {
      const switcherEl = document.createElement('div');
      switcherEl.className = 'settings-prompt-group-switcher';
      groups.forEach((g, i) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'settings-prompt-group-btn' + (i === _activeGroupIndex ? ' is-active' : '');
        btn.textContent = g.label;
        btn.addEventListener('click', () => { _activeGroupIndex = i; renderTabs(); });
        switcherEl.appendChild(btn);
      });
      tabsEl.appendChild(switcherEl);
    }

    // ── Active group tabs ──
    const activeGroup = groups[_activeGroupIndex];
    const groupEl = document.createElement('div');
    groupEl.className = 'settings-prompt-tab-group';
    for (const key of activeGroup.keys) {
      groupEl.appendChild(makeTabBtn(key));
      renderedKeys.add(key);
    }
    tabsEl.appendChild(groupEl);

    if (window.lucide) window.lucide.createIcons({ nodes: tabsEl.querySelectorAll('i[data-lucide]') });
  }

  async function saveVariantsNow() {
    const payload = {
      promptVariants: state.promptVariants,
      promptActiveVariants: state.promptActiveVariants,
    };
    try {
      await fetch('/api/models/settings/prompts', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch {
      // Non-fatal save for variants metadata.
    }
  }

  function renderVariantsPanel(key) {
    variantsSlotEl.innerHTML = '';

    const { variants, activeId } = getVariantsState(key);

    const panel = document.createElement('div');
    panel.className = 'settings-variants-panel';

    const header = document.createElement('div');
    header.className = 'settings-variants-header';

    const title = document.createElement('span');
    title.className = 'settings-variants-title';
    title.textContent = t('settings.promptEditor.variants', 'Variants');
    header.appendChild(title);

    const activeVariant = variants.find((item) => item.id === activeId);
    const activeLabel = document.createElement('span');
    activeLabel.className = 'settings-variants-active';
    activeLabel.textContent = activeVariant
      ? t('settings.promptEditor.activeVariant', `Active: ${activeVariant.label}`, { label: activeVariant.label })
      : t('settings.promptEditor.activeDefault', 'Active: Default');
    header.appendChild(activeLabel);

    panel.appendChild(header);

    const list = document.createElement('div');
    list.className = 'settings-variants-list';

    if (!variants.length) {
      const empty = document.createElement('p');
      empty.className = 'muted-note settings-variants-empty';
      empty.textContent = t('settings.promptEditor.noVariants', 'No variants saved yet.');
      list.appendChild(empty);
    }

    for (const variant of variants) {
      const isActive = variant.id === activeId;
      const row = document.createElement('div');
      row.className = 'settings-variant-row';
      row.classList.toggle('is-active', isActive);

      const name = document.createElement('span');
      name.className = 'settings-variant-name';
      name.textContent = variant.label;
      row.appendChild(name);

      const actionBtn = document.createElement('button');
      actionBtn.type = 'button';
      actionBtn.className = 'btn settings-btn-ghost settings-btn-sm';
      actionBtn.textContent = isActive
        ? t('settings.promptEditor.useDefault', 'Use Default')
        : t('settings.promptEditor.activate', 'Activate');
      actionBtn.addEventListener('click', async () => {
        if (isActive) {
          setVariantsState(key, undefined, '');
          await saveVariantsNow();
          renderVariantsPanel(key);
          setPromptsStatus(t('settings.promptEditor.switchedToDefault', 'Switched to default prompt.'));
          return;
        }

        setVariantsState(key, undefined, variant.id);
        state.values[key] = String(variant.text || '');
        textareaEl.value = state.values[key];
        markDirty();
        updateSummary();
        updateActivePromptPanel();
        await saveVariantsNow();
        setPromptsStatus(t('settings.promptEditor.variantActivated', `Variant "${variant.label}" activated.`, { label: variant.label }));
      });
      row.appendChild(actionBtn);

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'btn settings-btn-ghost settings-btn-sm';
      deleteBtn.textContent = t('settings.promptEditor.delete', 'Delete');
      deleteBtn.addEventListener('click', async () => {
        const label = variant.label;
        const { variants: currentVariants, activeId: currentActiveId } = getVariantsState(key);
        const newActiveId = isActive ? '' : currentActiveId;
        const newVariants = currentVariants.filter((item) => item.id !== variant.id);
        setVariantsState(key, newVariants, newActiveId);
        await saveVariantsNow();
        renderVariantsPanel(key);
        setPromptsStatus(t('settings.promptEditor.variantDeleted', `Variant "${label}" deleted.`, { label: label }));
      });
      row.appendChild(deleteBtn);

      list.appendChild(row);
    }

    panel.appendChild(list);

    const addRow = document.createElement('div');
    addRow.className = 'settings-variants-add-row';

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.placeholder = t('settings.promptEditor.variantNamePlaceholder', 'Variant name');
    nameInput.maxLength = 60;
    nameInput.className = 'settings-variant-input';
    addRow.appendChild(nameInput);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn settings-btn-secondary settings-btn-sm';
    addBtn.textContent = t('settings.promptEditor.saveVariant', 'Save variant');
    addBtn.addEventListener('click', async () => {
      const label = nameInput.value.trim();
      const text = textareaEl.value.trim();
      if (!label) {
        nameInput.focus();
        return;
      }
      if (!text) {
        setPromptsStatus(t('settings.promptEditor.enterTextFirst', 'Enter prompt text before saving a variant.'), true);
        return;
      }

      const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
      const { variants: currentVariants } = getVariantsState(key);
      setVariantsState(key, [...currentVariants, { id, label, text }], undefined);
      nameInput.value = '';
      await saveVariantsNow();
      renderVariantsPanel(key);
      setPromptsStatus(t('settings.promptEditor.variantSaved', `Variant "${label}" saved.`, { label: label }));
    });
    addRow.appendChild(addBtn);

    nameInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        addBtn.click();
      }
    });

    panel.appendChild(addRow);
    variantsSlotEl.appendChild(panel);
  }

  // Keep old name as alias for backward compat
  function renderDescribeVariantsPanel() { renderVariantsPanel('describeFull'); }

  function collectPromptPayload() {
    const prompts = {};
    for (const key of state.keys) {
      prompts[key] = normalizePrompt(state.values[key]);
    }
    return prompts;
  }

  textareaEl.addEventListener('input', () => {
    if (!state.activeKey) return;
    state.values[state.activeKey] = textareaEl.value;
    markDirty();
    updateSummary();
    updateActivePromptPanel();
  });

  resetActiveBtn.addEventListener('click', () => {
    if (!state.activeKey) return;
    state.values[state.activeKey] = state.defaults[state.activeKey] || '';
    textareaEl.value = state.values[state.activeKey];
    markDirty();
    updateSummary();
    updateActivePromptPanel();
    setPromptsStatus(t('settings.promptEditor.resetToDefault', 'Prompt reset to default. Click Save to confirm.'));
  });

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    setPromptsStatus(t('settings.promptEditor.savingPrompts', 'Saving prompts...'));
    try {
      const res = await fetch('/api/models/settings/prompts', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompts: collectPromptPayload(),
          promptVariants: state.promptVariants,
          promptActiveVariants: state.promptActiveVariants,
        }),
      });
      const json = await res.json();
      if (res.ok && json.ok) {
        clearDirty();
        updateSummary();
        updateActivePromptPanel();
        setPromptsStatus(t('settings.promptEditor.promptsSaved', 'Prompts saved.'));
      } else {
        setPromptsStatus(json.error || 'Failed to save prompts.', true);
      }
    } catch (error) {
      setPromptsStatus(t('settings.promptEditor.saveFailed', 'Failed to save prompts: ' + error.message, { reason: error.message }), true);
    } finally {
      saveBtn.disabled = false;
    }
  });

  resetBtn.addEventListener('click', () => {
    if (!state.keys.length) return;
    for (const key of state.keys) {
      state.values[key] = state.defaults[key] || '';
    }
    markDirty();
    updateSummary();
    updateActivePromptPanel();
    setPromptsStatus(t('settings.promptEditor.allResetToDefaults', 'All prompts reset to defaults. Click Save to confirm.'));
  });

  try {
    const res = await fetch('/api/models/settings/prompts');
    if (!res.ok) throw new Error('Failed to load prompts.');

    const json = await res.json();
    state.defaults = json.defaults || {};
    state.labels = json.labels || {};
    state.values = { ...(json.prompts || {}) };
    state.keys = Object.keys(state.values);
    state.promptVariants = (json.promptVariants && typeof json.promptVariants === 'object') ? { ...json.promptVariants } : {};
    state.promptActiveVariants = (json.promptActiveVariants && typeof json.promptActiveVariants === 'object') ? { ...json.promptActiveVariants } : {};

    // Backward compatibility: hydrate from legacy fields when generic maps are missing.
    if (!Array.isArray(state.promptVariants.describeFull) && Array.isArray(json.describeFullVariants)) {
      state.promptVariants.describeFull = json.describeFullVariants;
    }
    if (!state.promptActiveVariants.describeFull && json.describeFullActiveId) {
      state.promptActiveVariants.describeFull = String(json.describeFullActiveId || '');
    }
    if (!Array.isArray(state.promptVariants.editVariants) && Array.isArray(json.editVariantsVariants)) {
      state.promptVariants.editVariants = json.editVariantsVariants;
    }
    if (!state.promptActiveVariants.editVariants && json.editVariantsActiveId) {
      state.promptActiveVariants.editVariants = String(json.editVariantsActiveId || '');
    }

    // Ensure every prompt key has entries.
    for (const key of state.keys) {
      if (!Array.isArray(state.promptVariants[key])) state.promptVariants[key] = [];
      if (typeof state.promptActiveVariants[key] !== 'string') state.promptActiveVariants[key] = '';
    }

    if (!state.keys.length) {
      setPromptsStatus('No prompts available.', true);
      return;
    }

    state.activeKey = state.keys[0];
    updateSummary();
    renderTabs();
    updateActivePromptPanel();
    setPromptsStatus('');
  } catch (error) {
    setPromptsStatus('Failed to load prompts: ' + error.message, true);
  }
})();

// ---------------------------------------------------------------------------
// Studio Prompts section
// ---------------------------------------------------------------------------
(async function studioPromptsSection() {
  const tabsEl = document.getElementById('studio-prompts-tabs');
  const summaryEl = document.getElementById('studio-prompts-summary');
  const saveBtn = document.getElementById('studio-save-prompts-btn');
  const resetBtn = document.getElementById('studio-reset-prompts-btn');
  const statusEl = document.getElementById('studio-prompts-status');
  const titleEl = document.getElementById('studio-active-prompt-title');
  const badgeEl = document.getElementById('studio-active-prompt-badge');
  const resetActiveBtn = document.getElementById('studio-reset-active-prompt-btn');
  const textareaEl = document.getElementById('studio-active-prompt-textarea');
  const variantsSlotEl = document.getElementById('studio-variants-slot');

  if (!tabsEl || !summaryEl || !saveBtn || !resetBtn || !statusEl || !titleEl || !badgeEl || !resetActiveBtn || !textareaEl || !variantsSlotEl) {
    return;
  }

  const state = {
    defaults: {},
    labels: {},
    values: {},
    keys: [],
    activeKey: '',
    isDirty: false,
    promptVariants: {},
    promptActiveVariants: {},
  };

  function getVariantsState(key) {
    const variants = Array.isArray(state.promptVariants[key]) ? state.promptVariants[key] : [];
    const activeId = String(state.promptActiveVariants[key] || '');
    return { variants, activeId };
  }
  function setVariantsState(key, variants, activeId) {
    if (variants !== undefined) state.promptVariants[key] = variants;
    if (activeId !== undefined) state.promptActiveVariants[key] = activeId;
  }

  function normalizePrompt(v) { return String(v || '').trim(); }

  function setStatus(message, isError = false) {
    statusEl.textContent = message;
    statusEl.classList.toggle('status-error', isError);
  }

  function markDirty() { state.isDirty = true; saveBtn.style.display = ''; }
  function clearDirty() { state.isDirty = false; saveBtn.style.display = 'none'; }

  function isCustomized(key) {
    return normalizePrompt(state.values[key]) !== normalizePrompt(state.defaults[key]);
  }

  function getStudioIcon(key) {
    if (key === 'studioQuick') return 'zap';
    if (key === 'studioStyle') return 'palette';
    if (key === 'studioScene') return 'layers';
    if (key === 'studioMaster') return 'crown';
    return 'sparkles';
  }

  function updateSummary() {
    const total = state.keys.length;
    const customized = state.keys.filter(isCustomized).length;
    summaryEl.textContent = `${total} prompts - ${customized} customized`;
  }

  function updateActivePromptPanel() {
    if (!state.activeKey) return;
    const key = state.activeKey;
    const custom = isCustomized(key);
    titleEl.textContent = state.labels[key] || key;
    badgeEl.textContent = custom ? 'CUSTOMIZED' : 'DEFAULT';
    badgeEl.classList.toggle('is-customized', custom);
    badgeEl.classList.toggle('is-default', !custom);
    resetActiveBtn.style.display = custom ? '' : 'none';
    textareaEl.value = state.values[key] || '';
    textareaEl.dataset.key = key;
    renderVariantsPanel(key);
  }

  function renderTabs() {
    tabsEl.innerHTML = '';
    const groupEl = document.createElement('div');
    groupEl.className = 'settings-prompt-tab-group';
    for (const key of state.keys) {
      const tabBtn = document.createElement('button');
      tabBtn.type = 'button';
      tabBtn.className = 'settings-prompt-tab';
      tabBtn.setAttribute('role', 'tab');
      tabBtn.setAttribute('aria-selected', String(state.activeKey === key));
      tabBtn.classList.toggle('is-active', state.activeKey === key);
      tabBtn.dataset.key = key;

      const iconEl = document.createElement('i');
      iconEl.setAttribute('data-lucide', getStudioIcon(key));
      iconEl.setAttribute('aria-hidden', 'true');
      tabBtn.appendChild(iconEl);

      const textEl = document.createElement('span');
      textEl.textContent = state.labels[key] || key;
      tabBtn.appendChild(textEl);

      tabBtn.addEventListener('click', () => {
        if (state.activeKey === key) return;
        state.activeKey = key;
        renderTabs();
        updateActivePromptPanel();
      });

      groupEl.appendChild(tabBtn);
    }
    tabsEl.appendChild(groupEl);
    if (window.lucide) window.lucide.createIcons({ nodes: tabsEl.querySelectorAll('i[data-lucide]') });
  }

  async function saveVariantsNow() {
    const payload = {
      promptVariants: state.promptVariants,
      promptActiveVariants: state.promptActiveVariants,
    };
    try {
      await fetch('/api/models/settings/studio-prompts', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch { /* Non-fatal */ }
  }

  function renderVariantsPanel(key) {
    variantsSlotEl.innerHTML = '';
    const { variants, activeId } = getVariantsState(key);

    const panel = document.createElement('div');
    panel.className = 'settings-variants-panel';

    const header = document.createElement('div');
    header.className = 'settings-variants-header';
    const title = document.createElement('span');
    title.className = 'settings-variants-title';
    title.textContent = t('settings.promptEditor.variants', 'Variants');
    header.appendChild(title);
    const activeVariant = variants.find((item) => item.id === activeId);
    const activeLabel = document.createElement('span');
    activeLabel.className = 'settings-variants-active';
    activeLabel.textContent = activeVariant
      ? t('settings.promptEditor.activeVariant', `Active: ${activeVariant.label}`, { label: activeVariant.label })
      : t('settings.promptEditor.activeDefault', 'Active: Default');
    header.appendChild(activeLabel);
    panel.appendChild(header);

    const list = document.createElement('div');
    list.className = 'settings-variants-list';

    if (!variants.length) {
      const empty = document.createElement('p');
      empty.className = 'muted-note settings-variants-empty';
      empty.textContent = t('settings.promptEditor.noVariants', 'No variants saved yet.');
      list.appendChild(empty);
    }

    for (const variant of variants) {
      const isActive = variant.id === activeId;
      const row = document.createElement('div');
      row.className = 'settings-variant-row';
      row.classList.toggle('is-active', isActive);

      const name = document.createElement('span');
      name.className = 'settings-variant-name';
      name.textContent = variant.label;
      row.appendChild(name);

      const actionBtn = document.createElement('button');
      actionBtn.type = 'button';
      actionBtn.className = 'btn settings-btn-ghost settings-btn-sm';
      actionBtn.textContent = isActive
        ? t('settings.promptEditor.useDefault', 'Use Default')
        : t('settings.promptEditor.activate', 'Activate');
      actionBtn.addEventListener('click', async () => {
        if (isActive) {
          setVariantsState(key, undefined, '');
          await saveVariantsNow();
          renderVariantsPanel(key);
          setStatus(t('settings.promptEditor.switchedToDefault', 'Switched to default prompt.'));
          return;
        }
        setVariantsState(key, undefined, variant.id);
        state.values[key] = String(variant.text || '');
        textareaEl.value = state.values[key];
        markDirty();
        updateSummary();
        updateActivePromptPanel();
        await saveVariantsNow();
        setStatus(t('settings.promptEditor.variantActivated', `Variant "${variant.label}" activated.`, { label: variant.label }));
      });
      row.appendChild(actionBtn);

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'btn settings-btn-ghost settings-btn-sm';
      deleteBtn.textContent = t('settings.promptEditor.delete', 'Delete');
      deleteBtn.addEventListener('click', async () => {
        const label = variant.label;
        const { variants: cv, activeId: cai } = getVariantsState(key);
        const newVariants = cv.filter((item) => item.id !== variant.id);
        const newActiveId = isActive ? '' : cai;
        setVariantsState(key, newVariants, newActiveId);
        await saveVariantsNow();
        renderVariantsPanel(key);
        setStatus(t('settings.promptEditor.variantDeleted', `Variant "${label}" deleted.`, { label: label }));
      });
      row.appendChild(deleteBtn);

      list.appendChild(row);
    }

    panel.appendChild(list);

    const addRow = document.createElement('div');
    addRow.className = 'settings-variants-add-row';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.placeholder = t('settings.promptEditor.variantNamePlaceholder', 'Variant name');
    nameInput.maxLength = 60;
    nameInput.className = 'settings-variant-input';
    addRow.appendChild(nameInput);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn settings-btn-secondary settings-btn-sm';
    addBtn.textContent = t('settings.promptEditor.saveVariant', 'Save variant');
    addBtn.addEventListener('click', async () => {
      const label = nameInput.value.trim();
      const text = textareaEl.value.trim();
      if (!label) { nameInput.focus(); return; }
      if (!text) { setStatus(t('settings.promptEditor.enterTextFirst', 'Enter prompt text before saving a variant.'), true); return; }
      const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
      const { variants: cv } = getVariantsState(key);
      setVariantsState(key, [...cv, { id, label, text }], undefined);
      nameInput.value = '';
      await saveVariantsNow();
      renderVariantsPanel(key);
      setStatus(t('settings.promptEditor.variantSaved', `Variant "${label}" saved.`, { label: label }));
    });
    addRow.appendChild(addBtn);

    nameInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); addBtn.click(); }
    });

    panel.appendChild(addRow);
    variantsSlotEl.appendChild(panel);
  }

  textareaEl.addEventListener('input', () => {
    if (!state.activeKey) return;
    state.values[state.activeKey] = textareaEl.value;
    markDirty();
    updateSummary();
    updateActivePromptPanel();
  });

  resetActiveBtn.addEventListener('click', () => {
    if (!state.activeKey) return;
    state.values[state.activeKey] = state.defaults[state.activeKey] || '';
    textareaEl.value = state.values[state.activeKey];
    markDirty();
    updateSummary();
    updateActivePromptPanel();
    setStatus(t('settings.promptEditor.resetToDefault', 'Prompt reset to default. Click Save to confirm.'));
  });

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    setStatus(t('settings.promptEditor.savingPrompts', 'Saving prompts...'));
    try {
      const prompts = {};
      for (const key of state.keys) {
        prompts[key] = normalizePrompt(state.values[key]);
      }
      const res = await fetch('/api/models/settings/studio-prompts', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompts,
          promptVariants: state.promptVariants,
          promptActiveVariants: state.promptActiveVariants,
        }),
      });
      const json = await res.json();
      if (res.ok && json.ok) {
        clearDirty();
        updateSummary();
        updateActivePromptPanel();
        setStatus(t('settings.promptEditor.promptsSaved', 'Prompts saved.'));
      } else {
        setStatus(json.error || 'Failed to save prompts.', true);
      }
    } catch (error) {
      setStatus(t('settings.promptEditor.saveFailed', 'Failed to save prompts: ' + error.message, { reason: error.message }), true);
    } finally {
      saveBtn.disabled = false;
    }
  });

  resetBtn.addEventListener('click', () => {
    if (!state.keys.length) return;
    for (const key of state.keys) {
      state.values[key] = state.defaults[key] || '';
    }
    markDirty();
    updateSummary();
    updateActivePromptPanel();
    setStatus(t('settings.promptEditor.allResetToDefaults', 'All prompts reset to defaults. Click Save to confirm.'));
  });

  try {
    const res = await fetch('/api/models/settings/studio-prompts');
    if (!res.ok) throw new Error('Failed to load studio prompts.');
    const json = await res.json();
    state.defaults = json.defaults || {};
    state.labels = json.labels || {};
    state.values = { ...(json.prompts || {}) };
    state.keys = Object.keys(state.defaults);
    state.promptVariants = (json.promptVariants && typeof json.promptVariants === 'object') ? { ...json.promptVariants } : {};
    state.promptActiveVariants = (json.promptActiveVariants && typeof json.promptActiveVariants === 'object') ? { ...json.promptActiveVariants } : {};
    for (const key of state.keys) {
      if (!Array.isArray(state.promptVariants[key])) state.promptVariants[key] = [];
      if (typeof state.promptActiveVariants[key] !== 'string') state.promptActiveVariants[key] = '';
      if (!(key in state.values)) state.values[key] = '';
    }
    if (!state.keys.length) { setStatus('No studio prompts available.', true); return; }
    state.activeKey = state.keys[0];
    updateSummary();
    renderTabs();
    updateActivePromptPanel();
    setStatus('');
  } catch (error) {
    setStatus('Failed to load studio prompts: ' + error.message, true);
  }
})();

// ---------------------------------------------------------------------------
// Compose Prompts section
// ---------------------------------------------------------------------------
(async function composePromptsSection() {
  const summaryEl    = document.getElementById('compose-prompts-summary');
  const saveBtn      = document.getElementById('compose-save-prompts-btn');
  const resetBtn     = document.getElementById('compose-reset-prompts-btn');
  const statusEl     = document.getElementById('compose-prompts-status');
  const titleEl      = document.getElementById('compose-active-prompt-title');
  const badgeEl      = document.getElementById('compose-active-prompt-badge');
  const resetActiveBtn = document.getElementById('compose-reset-active-prompt-btn');
  const textareaEl   = document.getElementById('compose-active-prompt-textarea');
  const variantsSlotEl = document.getElementById('compose-variants-slot');

  if (!summaryEl || !saveBtn || !resetBtn || !statusEl || !titleEl || !badgeEl || !resetActiveBtn || !textareaEl || !variantsSlotEl) return;

  const KEY = 'main';

  const state = {
    defaultText: '',
    label: 'Compose Prompt',
    value: '',
    isDirty: false,
    variants: [],
    activeVariantId: '',
  };

  function setStatus(message, isError = false) {
    statusEl.textContent = message;
    statusEl.classList.toggle('status-error', isError);
  }

  function markDirty() { state.isDirty = true; saveBtn.style.display = ''; }
  function clearDirty() { state.isDirty = false; saveBtn.style.display = 'none'; }

  function isCustomized() {
    return (state.value || '').trim() !== (state.defaultText || '').trim();
  }

  function updateSummary() {
    summaryEl.textContent = isCustomized() ? '1 customized' : '1 prompt — default';
  }

  function updatePanel() {
    titleEl.textContent = state.label;
    const custom = isCustomized();
    badgeEl.textContent = custom ? 'CUSTOMIZED' : 'DEFAULT';
    badgeEl.classList.toggle('is-customized', custom);
    badgeEl.classList.toggle('is-default', !custom);
    resetActiveBtn.style.display = custom ? '' : 'none';
    textareaEl.value = state.value || '';
    renderVariantsPanel();
  }

  async function saveVariantsNow() {
    try {
      await fetch('/api/models/settings/compose-prompts', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          promptVariants: { [KEY]: state.variants },
          promptActiveVariants: { [KEY]: state.activeVariantId },
        }),
      });
    } catch { /* non-fatal */ }
  }

  function renderVariantsPanel() {
    variantsSlotEl.innerHTML = '';

    const panel = document.createElement('div');
    panel.className = 'settings-variants-panel';

    const header = document.createElement('div');
    header.className = 'settings-variants-header';
    const title = document.createElement('span');
    title.className = 'settings-variants-title';
    title.textContent = t('settings.promptEditor.variants', 'Variants');
    header.appendChild(title);
    const activeVariant = state.variants.find((v) => v.id === state.activeVariantId);
    const activeLabel = document.createElement('span');
    activeLabel.className = 'settings-variants-active';
    activeLabel.textContent = activeVariant
      ? t('settings.promptEditor.activeVariant', `Active: ${activeVariant.label}`, { label: activeVariant.label })
      : t('settings.promptEditor.activeDefault', 'Active: Default');
    header.appendChild(activeLabel);
    panel.appendChild(header);

    const list = document.createElement('div');
    list.className = 'settings-variants-list';

    if (!state.variants.length) {
      const empty = document.createElement('p');
      empty.className = 'muted-note settings-variants-empty';
      empty.textContent = t('settings.promptEditor.noVariants', 'No variants saved yet.');
      list.appendChild(empty);
    }

    for (const variant of state.variants) {
      const isActive = variant.id === state.activeVariantId;
      const row = document.createElement('div');
      row.className = 'settings-variant-row';
      row.classList.toggle('is-active', isActive);

      const name = document.createElement('span');
      name.className = 'settings-variant-name';
      name.textContent = variant.label;
      row.appendChild(name);

      const actionBtn = document.createElement('button');
      actionBtn.type = 'button';
      actionBtn.className = 'btn settings-btn-ghost settings-btn-sm';
      actionBtn.textContent = isActive
        ? t('settings.promptEditor.useDefault', 'Use Default')
        : t('settings.promptEditor.activate', 'Activate');
      actionBtn.addEventListener('click', async () => {
        if (isActive) {
          state.activeVariantId = '';
          await saveVariantsNow();
          renderVariantsPanel();
          setStatus(t('settings.promptEditor.switchedToDefault', 'Switched to default prompt.'));
          return;
        }
        state.activeVariantId = variant.id;
        state.value = String(variant.text || '');
        markDirty();
        updateSummary();
        updatePanel();
        await saveVariantsNow();
        setStatus(t('settings.promptEditor.variantActivated', `Variant "${variant.label}" activated.`, { label: variant.label }));
      });
      row.appendChild(actionBtn);

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'btn settings-btn-ghost settings-btn-sm';
      deleteBtn.textContent = t('settings.promptEditor.delete', 'Delete');
      deleteBtn.addEventListener('click', async () => {
        const label = variant.label;
        state.variants = state.variants.filter((v) => v.id !== variant.id);
        if (isActive) state.activeVariantId = '';
        await saveVariantsNow();
        renderVariantsPanel();
        setStatus(t('settings.promptEditor.variantDeleted', `Variant "${label}" deleted.`, { label: label }));
      });
      row.appendChild(deleteBtn);

      list.appendChild(row);
    }
    panel.appendChild(list);

    const addRow = document.createElement('div');
    addRow.className = 'settings-variants-add-row';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.placeholder = t('settings.promptEditor.variantNamePlaceholder', 'Variant name');
    nameInput.maxLength = 60;
    nameInput.className = 'settings-variant-input';
    addRow.appendChild(nameInput);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn settings-btn-secondary settings-btn-sm';
    addBtn.textContent = t('settings.promptEditor.saveVariant', 'Save variant');
    addBtn.addEventListener('click', async () => {
      const label = nameInput.value.trim();
      const text = textareaEl.value.trim();
      if (!label) { nameInput.focus(); return; }
      if (!text) { setStatus(t('settings.promptEditor.enterTextFirst', 'Enter prompt text before saving a variant.'), true); return; }
      const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
      state.variants = [...state.variants, { id, label, text }];
      nameInput.value = '';
      await saveVariantsNow();
      renderVariantsPanel();
      setStatus(t('settings.promptEditor.variantSaved', `Variant "${label}" saved.`, { label: label }));
    });
    addRow.appendChild(addBtn);
    nameInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addBtn.click(); } });
    panel.appendChild(addRow);
    variantsSlotEl.appendChild(panel);
  }

  textareaEl.addEventListener('input', () => {
    state.value = textareaEl.value;
    markDirty();
    updateSummary();
    updatePanel();
  });

  resetActiveBtn.addEventListener('click', () => {
    state.value = state.defaultText;
    markDirty();
    updateSummary();
    updatePanel();
    setStatus(t('settings.promptEditor.resetToDefault', 'Prompt reset to default. Click Save to confirm.'));
  });

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    setStatus(t('settings.common.saving', 'Saving...'));
    try {
      const res = await fetch('/api/models/settings/compose-prompts', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompts: { [KEY]: state.value.trim() },
          promptVariants: { [KEY]: state.variants },
          promptActiveVariants: { [KEY]: state.activeVariantId },
        }),
      });
      const json = await res.json();
      if (res.ok && json.ok) {
        clearDirty();
        updateSummary();
        updatePanel();
        setStatus(t('settings.promptEditor.composeSaved', 'Compose prompt saved.'));
      } else {
        setStatus(json.error || 'Failed to save.', true);
      }
    } catch (err) {
      setStatus(t('settings.promptEditor.composeSaveFailed', 'Failed to save: ' + err.message, { reason: err.message }), true);
    } finally {
      saveBtn.disabled = false;
    }
  });

  resetBtn.addEventListener('click', () => {
    state.value = state.defaultText;
    markDirty();
    updateSummary();
    updatePanel();
    setStatus(t('settings.promptEditor.resetToDefault', 'Prompt reset to default. Click Save to confirm.'));
  });

  try {
    const res = await fetch('/api/models/settings/compose-prompts');
    if (!res.ok) throw new Error('Failed to load compose prompts.');
    const json = await res.json();
    state.defaultText = (json.defaults && json.defaults[KEY]) || '';
    state.label = (json.labels && json.labels[KEY]) || 'Compose Prompt';
    state.value = (json.prompts && json.prompts[KEY]) || '';
    state.variants = Array.isArray(json.promptVariants && json.promptVariants[KEY]) ? json.promptVariants[KEY] : [];
    state.activeVariantId = (json.promptActiveVariants && json.promptActiveVariants[KEY]) || '';
    updateSummary();
    updatePanel();
    setStatus('');
  } catch (err) {
    setStatus('Failed to load compose prompts: ' + err.message, true);
  }
})();

// ---------------------------------------------------------------------------
// Advanced toggles — GPU sharing (ComfyUI/LM Studio)
// ---------------------------------------------------------------------------
(async function advancedTogglesSection() {
  const allowConcurrentGpuToggleEl = document.getElementById('allow-concurrent-gpu-toggle');
  const allowConcurrentGpuStatusEl = document.getElementById('allow-concurrent-gpu-status');
  const commonQueueGpuToggleEl = document.getElementById('common-queue-gpu-toggle');
  const commonQueueGpuStatusEl = document.getElementById('common-queue-gpu-status');

  if (!allowConcurrentGpuToggleEl || !allowConcurrentGpuStatusEl
    || !commonQueueGpuToggleEl || !commonQueueGpuStatusEl) {
    return;
  }

  function setInlineStatus(el, message, isError = false) {
    el.textContent = message;
    el.classList.toggle('status-error', isError);
  }

  try {
    const response = await window.openJourneyApi.getModelsSettings();
    const settings = response && response.settings && typeof response.settings === 'object' ? response.settings : {};
    allowConcurrentGpuToggleEl.checked = Boolean(settings.allowConcurrentComfyLmstudio);
    commonQueueGpuToggleEl.checked = Boolean(settings.commonQueueComfyLmstudio);
  } catch (error) {
    setInlineStatus(allowConcurrentGpuStatusEl, t('settings.common.toggleLoadFailed', 'Failed to load toggle settings: ' + error.message, { reason: error.message }), true);
  }

  allowConcurrentGpuToggleEl.addEventListener('change', async () => {
    setInlineStatus(allowConcurrentGpuStatusEl, t('settings.common.saving', 'Saving...'));
    try {
      await window.openJourneyApi.updateModelsSettings({
        allowConcurrentComfyLmstudio: allowConcurrentGpuToggleEl.checked,
      });
      setInlineStatus(allowConcurrentGpuStatusEl, t('settings.common.saved', 'Saved.'));
    } catch (error) {
      allowConcurrentGpuToggleEl.checked = !allowConcurrentGpuToggleEl.checked;
      setInlineStatus(allowConcurrentGpuStatusEl, error.message || t('settings.common.toggleSaveFailed', 'Failed to save toggle.'), true);
    }
  });

  commonQueueGpuToggleEl.addEventListener('change', async () => {
    setInlineStatus(commonQueueGpuStatusEl, t('settings.common.saving', 'Saving...'));
    try {
      await window.openJourneyApi.updateModelsSettings({
        commonQueueComfyLmstudio: commonQueueGpuToggleEl.checked,
      });
      setInlineStatus(commonQueueGpuStatusEl, t('settings.common.saved', 'Saved.'));
    } catch (error) {
      commonQueueGpuToggleEl.checked = !commonQueueGpuToggleEl.checked;
      setInlineStatus(commonQueueGpuStatusEl, error.message || t('settings.common.toggleSaveFailed', 'Failed to save toggle.'), true);
    }
  });
})();

// ---------------------------------------------------------------------------
// Packages — inspect, install, list, uninstall (app/services/package_service.py)
// ---------------------------------------------------------------------------
(function packagesSection() {
  const section = document.getElementById('packages-section');
  if (!section) return;
  const fileInput = document.getElementById('packages-file');
  const chooseBtn = document.getElementById('packages-choose-btn');
  const statusEl = document.getElementById('packages-status');
  const reviewEl = document.getElementById('packages-review');
  const listEl = document.getElementById('packages-list');

  let packages = [];
  let local = true;
  let pending = [];       // [{ file, token, package } | { file, error }] from /inspect — several ZIPs at once
  let confirming = null;  // package id being uninstalled
  let busy = false;

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function lang() {
    return (window.NomadI18n && window.NomadI18n.getLanguage && window.NomadI18n.getLanguage()) || 'en';
  }
  function setStatus(msg, isError = false) {
    statusEl.textContent = msg || '';
    statusEl.classList.toggle('status-error', isError);
  }
  async function api(method, url, body, isForm) {
    const opts = { method, cache: 'no-store' };
    if (isForm) opts.body = body;
    else if (body !== undefined) { opts.headers = { 'Content-Type': 'application/json' }; opts.body = JSON.stringify(body); }
    const res = await fetch(url, opts);
    const json = await res.json().catch(() => ({}));
    if (!res.ok || json.ok === false) throw new Error(json.error || ('HTTP ' + res.status));
    return json;
  }
  function stateLabel(p) {
    if (p.state === 'missing_requirements') return t('settings.packages.stateMissing', 'Needs an image engine');
    if (p.state === 'broken') return t('settings.packages.stateBroken', 'Broken');
    return t('settings.packages.stateActive', 'Active');
  }
  // What a package brings, as visible chips: [ENGINE] Z-Image Turbo [FLOW] Simple.
  function contentsHtml(pkg) {
    const chip = (kind, label, name) =>
      '<span class="settings-package-chip settings-package-chip--' + kind + '"><b>' + esc(label) + '</b>' + esc(name) + '</span>';
    const chips = [];
    (pkg.engines || []).forEach((e) => chips.push(chip('engine', t('settings.packages.kindEngine', 'Engine'), e.name || e.id)));
    (pkg.flows || []).forEach((f) => chips.push(chip('flow', t('settings.packages.kindFlow', 'Flow'), typeof f === 'string' ? f : (f.label || f.id))));
    return chips.length ? '<span class="settings-package-chips">' + chips.join('') + '</span>' : '';
  }

  // Engines first, so a flow that needs an image engine finds the one
  // arriving in the same batch.
  function installOrder(items) {
    return items.slice().sort((a, b) => ((b.package.engines || []).length ? 1 : 0) - ((a.package.engines || []).length ? 1 : 0));
  }

  function renderReview() {
    if (!pending.length) { reviewEl.hidden = true; reviewEl.innerHTML = ''; return; }
    const ok = pending.filter((x) => x.package);
    const batchEngineCats = new Set();
    ok.forEach((x) => (x.package.engines || []).forEach((e) => batchEngineCats.add(e.category)));
    const items = pending.map((x) => {
      if (!x.package) {
        return '<div class="settings-backup-item"><div class="settings-backup-info">' +
          '<span class="settings-backup-date">' + esc(x.file) + '</span>' +
          '<span class="settings-backup-meta status-error">' + esc(x.error) + '</span></div></div>';
      }
      const p = x.package;
      const op = p.operation === 'update'
        ? t('settings.packages.opUpdate', 'Update {from} → {to}', { from: p.installedVersion, to: p.version })
        : p.operation === 'reinstall' ? t('settings.packages.opReinstall', 'Reinstall {version}', { version: p.version })
        : t('settings.packages.opInstall', 'Install {version}', { version: p.version });
      // A missing image engine that another selected package provides is not missing.
      const stillMissing = (p.requiresMissing || []).filter((m) => !(m.engineCategory && batchEngineCats.has(m.engineCategory)));
      return '<div class="settings-backup-item"><div class="settings-backup-info">' +
        '<span class="settings-backup-date">' + esc(p.name) + ' <small>' + esc(p.id) + '</small></span>' +
        (p.summary ? '<span class="settings-backup-meta">' + esc(p.summary) + '</span>' : '') +
        '<span class="settings-backup-meta">' + esc(op) + ' · ' + esc(t('settings.packages.author', 'by {name}', { name: p.author || '—' })) + '</span>' +
        contentsHtml(p) +
        (stillMissing.length ? '<span class="settings-backup-meta">' + esc(t('settings.packages.needsEngine', 'Needs an image engine to work. You can install it now and add an engine package afterwards.')) + '</span>' : '') +
        '</div></div>';
    }).join('');
    reviewEl.hidden = false;
    reviewEl.innerHTML = items +
      '<p class="settings-field-hint settings-package-unsigned">' + esc(t('settings.packages.unsigned', 'Unofficial package: it is not signed by Nomad Studio. Install it only if you trust where it comes from.')) + '</p>' +
      '<div class="settings-backup-actions settings-package-actions">' +
        '<button type="button" class="btn settings-btn-ghost" data-pkg-cancel' + (busy ? ' disabled' : '') + '>' + esc(t('settings.backup.cancel', 'Cancel')) + '</button>' +
        (ok.length ? '<button type="button" class="btn settings-btn-secondary" data-pkg-install' + (busy ? ' disabled' : '') + '>' +
          esc(ok.length > 1 ? t('settings.packages.confirmInstallN', 'Install {n} packages', { n: ok.length }) : t('settings.packages.confirmInstall', 'Install')) + '</button>' : '') +
      '</div>';
  }

  function discardPending() {
    pending.forEach((x) => { if (x.token) api('POST', '/api/packages/discard', { token: x.token }).catch(() => {}); });
    pending = [];
  }

  function renderList() {
    if (!packages.length) {
      listEl.innerHTML = '<li class="settings-backup-empty">' + esc(t('settings.packages.empty', 'No packages installed yet.')) + '</li>';
      return;
    }
    listEl.innerHTML = packages.map((p) => {
      const isConfirm = confirming === p.id;
      return '<li class="settings-backup-item">' +
        '<div class="settings-backup-info">' +
          '<span class="settings-backup-date">' + esc(p.name) + ' <small>' + esc(p.version) + '</small></span>' +
          contentsHtml(p) +
          '<span class="settings-backup-meta">' + esc(stateLabel(p)) + ' · ' + esc(p.id) + '</span>' +
        '</div>' +
        '<div class="settings-backup-actions">' +
          '<button type="button" class="btn settings-btn-ghost" data-pkg-ask="' + esc(p.id) + '"' + (busy || !local ? ' disabled' : '') + '>' + esc(t('settings.packages.uninstall', 'Uninstall')) + '</button>' +
        '</div>' +
        (isConfirm ? '<div class="settings-backup-confirm"><span>' + esc(t('settings.packages.confirmUninstall', 'Its engines and flows are removed. Your images and Sessions are kept.')) + '</span>' +
          '<button type="button" class="btn settings-btn-ghost" data-pkg-no>' + esc(t('settings.backup.cancel', 'Cancel')) + '</button>' +
          '<button type="button" class="btn settings-btn-danger" data-pkg-uninstall="' + esc(p.id) + '">' + esc(t('settings.packages.uninstall', 'Uninstall')) + '</button></div>' : '') +
        '</li>';
    }).join('');
  }

  async function load() {
    try {
      const res = await api('GET', '/api/packages?lang=' + encodeURIComponent(lang()));
      packages = res.packages || [];
      local = res.local !== false;
    } catch (e) {
      setStatus(e.message, true);
    }
    renderList();
  }

  chooseBtn.addEventListener('click', () => { if (!busy) fileInput.click(); });
  fileInput.addEventListener('change', async () => {
    const files = Array.from(fileInput.files || []);
    fileInput.value = '';
    if (!files.length) return;
    discardPending();
    busy = true; setStatus(t('settings.packages.checking', 'Checking the package…')); renderReview();
    for (const file of files) {
      try {
        const form = new FormData();
        form.append('file', file);
        form.append('lang', lang());
        const res = await api('POST', '/api/packages/inspect', form, true);
        pending.push({ file: file.name, token: res.token, package: res.package });
      } catch (e) {
        pending.push({ file: file.name, error: e.message });
      }
    }
    setStatus('');
    busy = false; renderReview();
  });

  reviewEl.addEventListener('click', async (e) => {
    if (!pending.length) return;
    if (e.target.closest('[data-pkg-cancel]')) { discardPending(); renderReview(); return; }
    if (!e.target.closest('[data-pkg-install]')) return;
    busy = true; renderReview(); setStatus(t('settings.packages.installing', 'Installing…'));
    const done = [];
    const failed = [];
    for (const item of installOrder(pending.filter((x) => x.package))) {
      try {
        const res = await api('POST', '/api/packages/install', { token: item.token });
        done.push(res.package.name);
      } catch (err) {
        failed.push(item.package.name + ': ' + err.message);
      }
    }
    pending = [];
    busy = false; renderReview();
    if (failed.length) setStatus(failed.join(' · '), true);
    else setStatus(t('settings.packages.installedOk', 'Installed: {name}', { name: done.join(', ') }));
    load();
  });

  listEl.addEventListener('click', async (e) => {
    const ask = e.target.closest('[data-pkg-ask]');
    if (ask) { confirming = ask.dataset.pkgAsk; return renderList(); }
    if (e.target.closest('[data-pkg-no]')) { confirming = null; return renderList(); }
    const go = e.target.closest('[data-pkg-uninstall]');
    if (!go) return;
    busy = true; confirming = null; renderList();
    try {
      await api('DELETE', '/api/packages/' + encodeURIComponent(go.dataset.pkgUninstall));
      setStatus(t('settings.packages.removed', 'Package uninstalled.'));
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      busy = false; load();
    }
  });

  document.addEventListener('nomad-i18n-applied', () => { renderReview(); renderList(); });
  load();
})();

// ---------------------------------------------------------------------------
// Backups — create / restore / delete (app/services/backup_service.py)
// ---------------------------------------------------------------------------
(function backupSection() {
  const section = document.getElementById('backup-section');
  if (!section) return;
  const dirInput = document.getElementById('backup-dir-input');
  const dirStatus = document.getElementById('backup-dir-status');
  const browseBtn = document.getElementById('backup-browse-btn');
  const openBtn = document.getElementById('backup-open-btn');
  const imagesToggle = document.getElementById('backup-images-toggle');
  const estimateEl = document.getElementById('backup-estimate');
  const createBtn = document.getElementById('backup-create-btn');
  const progressEl = document.getElementById('backup-progress');
  const progressText = document.getElementById('backup-progress-text');
  const progressBar = document.getElementById('backup-progress-bar');
  const statusEl = document.getElementById('backup-status');
  const listEl = document.getElementById('backup-list');

  let state = { backupDir: '', backups: [], estimate: null, busy: false };
  let confirming = null; // { name, action: 'restore' | 'delete' }
  let running = false;

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function size(n) {
    if (!n) return '0 MB';
    const gb = n / 1024 ** 3;
    if (gb >= 1) return gb.toFixed(1) + ' GB';
    return Math.max(1, Math.round(n / 1024 ** 2)) + ' MB';
  }
  function dateText(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return iso || '';
    const lang = (window.NomadI18n && window.NomadI18n.getLanguage && window.NomadI18n.getLanguage()) || undefined;
    return d.toLocaleString(lang, { dateStyle: 'medium', timeStyle: 'short' });
  }
  function setStatus(el, message, isError = false) {
    el.textContent = message || '';
    el.classList.toggle('status-error', isError);
  }
  async function api(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    });
    const json = await res.json().catch(() => ({}));
    if (json.cancelled) return json; // folder picker closed without choosing
    if (!res.ok || json.ok === false) throw new Error(json.error || ('HTTP ' + res.status));
    return json;
  }

  function renderEstimate() {
    const e = state.estimate;
    if (!e) { estimateEl.textContent = ''; return; }
    const bytes = e.dataBytes + (imagesToggle.checked ? e.imageBytes : 0);
    estimateEl.textContent = t('settings.backup.estimate', 'This backup will take about {size}. Images alone: {images}.', { size: size(bytes), images: size(e.imageBytes) });
  }

  function renderList() {
    if (!state.backups.length) {
      listEl.innerHTML = '<li class="settings-backup-empty">' + esc(t('settings.backup.empty', 'No backups in this folder yet.')) + '</li>';
      return;
    }
    listEl.innerHTML = state.backups.map((b) => {
      const kind = b.includesImages ? t('settings.backup.withImages', 'Data and images') : t('settings.backup.dataOnly', 'Data only');
      const reason = b.reason === 'before-restore' ? ' · ' + t('settings.backup.beforeRestore', 'automatic, before a restore')
        : b.reason === 'before-reset' ? ' · ' + t('settings.backup.beforeReset', 'automatic, before a reset') : '';
      const isConfirm = confirming && confirming.name === b.name;
      const disabled = running || !b.valid || !state.local ? ' disabled' : '';
      let confirmHtml = '';
      if (isConfirm && confirming.action === 'restore') {
        confirmHtml = '<div class="settings-backup-confirm"><span>' + esc(t('settings.backup.confirmRestore', 'Your current data will be replaced by this backup. A copy of the current state is saved first.')) + '</span>' +
          '<button type="button" class="btn settings-btn-ghost" data-backup-cancel>' + esc(t('settings.backup.cancel', 'Cancel')) + '</button>' +
          '<button type="button" class="btn settings-btn-danger" data-backup-do="restore" data-name="' + esc(b.name) + '">' + esc(t('settings.backup.restoreNow', 'Restore now')) + '</button></div>';
      } else if (isConfirm && confirming.action === 'delete') {
        confirmHtml = '<div class="settings-backup-confirm"><span>' + esc(t('settings.backup.confirmDelete', 'This backup file will be deleted. This cannot be undone.')) + '</span>' +
          '<button type="button" class="btn settings-btn-ghost" data-backup-cancel>' + esc(t('settings.backup.cancel', 'Cancel')) + '</button>' +
          '<button type="button" class="btn settings-btn-danger" data-backup-do="delete" data-name="' + esc(b.name) + '">' + esc(t('settings.backup.deleteNow', 'Delete')) + '</button></div>';
      }
      return '<li class="settings-backup-item">' +
        '<div class="settings-backup-info">' +
          '<span class="settings-backup-date">' + esc(dateText(b.createdAt)) + '</span>' +
          '<span class="settings-backup-meta" title="' + esc(b.name) + '">' + esc(size(b.sizeBytes) + ' · ' + kind + reason) +
            (b.valid ? '' : ' · ' + esc(t('settings.backup.invalid', 'damaged or not a backup'))) + '</span>' +
        '</div>' +
        '<div class="settings-backup-actions">' +
          '<button type="button" class="btn settings-btn-ghost" data-backup-ask="restore" data-name="' + esc(b.name) + '"' + disabled + '>' + esc(t('settings.backup.restore', 'Restore')) + '</button>' +
          '<button type="button" class="btn settings-btn-ghost" data-backup-ask="delete" data-name="' + esc(b.name) + '"' + (running || !state.local ? ' disabled' : '') + '>' + esc(t('settings.backup.delete', 'Delete')) + '</button>' +
        '</div>' + confirmHtml + '</li>';
    }).join('');
  }

  function render() {
    if (document.activeElement !== dirInput) dirInput.value = state.backupDir;
    createBtn.disabled = running || state.busy;
    // From a browser on another computer: create and list only.
    browseBtn.disabled = running || !state.local;
    openBtn.disabled = !state.local;
    dirInput.disabled = !state.local;
    if (!state.local) setStatus(dirStatus, t('settings.common.localOnly', 'Only available on the computer where Nomad Studio is installed.'));
    renderEstimate();
    renderList();
  }

  async function load() {
    try {
      state = await api('GET', '/api/backup');
      render();
    } catch (error) {
      setStatus(statusEl, error.message, true);
    }
  }

  async function saveDir(value) {
    setStatus(dirStatus, t('settings.common.saving', 'Saving...'));
    try {
      await api('PATCH', '/api/backup/settings', { backupDir: value.trim() });
      setStatus(dirStatus, t('settings.common.saved', 'Saved.'));
      confirming = null;
      await load();
    } catch (error) {
      setStatus(dirStatus, error.message, true);
    }
  }

  function showProgress(job) {
    progressEl.hidden = false;
    const pct = job.total ? Math.min(100, Math.round(job.done * 100 / job.total)) : 0;
    const phase = job.phase === 'safety-backup' ? t('settings.backup.phaseSafety', 'Saving a copy of the current state… {pct}%', { pct })
      : job.phase === 'restoring' ? t('settings.backup.phaseRestore', 'Restoring… {pct}%', { pct })
      : t('settings.backup.phaseCreate', 'Creating backup… {pct}%', { pct });
    progressText.textContent = phase;
    progressBar.style.width = pct + '%';
  }

  async function follow(job) {
    running = true;
    render();
    try {
      for (;;) {
        showProgress(job);
        if (job.state !== 'running') break;
        await new Promise((r) => setTimeout(r, 700));
        job = (await api('GET', '/api/backup/jobs/' + encodeURIComponent(job.id))).job;
      }
      if (job.state === 'error') throw new Error(job.error || 'error');
      return job.result || {};
    } finally {
      running = false;
      progressEl.hidden = true;
    }
  }

  createBtn.addEventListener('click', async () => {
    setStatus(statusEl, '');
    try {
      const { job } = await api('POST', '/api/backup/create', { includeImages: imagesToggle.checked });
      const result = await follow(job);
      setStatus(statusEl, t('settings.backup.created', 'Backup saved ({size}).', { size: size(result.sizeBytes) }));
    } catch (error) {
      setStatus(statusEl, error.message, true);
    }
    load();
  });

  listEl.addEventListener('click', async (e) => {
    const ask = e.target.closest('[data-backup-ask]');
    const cancel = e.target.closest('[data-backup-cancel]');
    const doIt = e.target.closest('[data-backup-do]');
    if (ask) { confirming = { name: ask.dataset.name, action: ask.dataset.backupAsk }; return renderList(); }
    if (cancel) { confirming = null; return renderList(); }
    if (!doIt) return;
    const name = doIt.dataset.name;
    confirming = null;
    setStatus(statusEl, '');
    if (doIt.dataset.backupDo === 'delete') {
      try {
        await api('DELETE', '/api/backup/' + encodeURIComponent(name));
      } catch (error) {
        setStatus(statusEl, error.message, true);
      }
      return load();
    }
    try {
      const { job } = await api('POST', '/api/backup/restore', { name });
      await follow(job);
      setStatus(statusEl, t('settings.backup.restored', 'Backup restored. Reloading…'));
      setTimeout(() => window.location.reload(), 1500);
    } catch (error) {
      setStatus(statusEl, error.message, true);
      load();
    }
  });

  browseBtn.addEventListener('click', async () => {
    try {
      const res = await api('POST', '/api/backup/browse', { current: state.backupDir });
      if (res.backupDir) { dirInput.value = res.backupDir; saveDir(res.backupDir); }
    } catch (error) {
      setStatus(dirStatus, error.message, true);
    }
  });
  openBtn.addEventListener('click', async () => {
    try { await api('POST', '/api/backup/open-folder'); } catch (error) { setStatus(dirStatus, error.message, true); }
  });
  dirInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); dirInput.blur(); } });
  dirInput.addEventListener('change', () => saveDir(dirInput.value));
  imagesToggle.addEventListener('change', renderEstimate);
  document.addEventListener('nomad-i18n-applied', render);

  load();
})();

// ---------------------------------------------------------------------------
// Total reset — SIMULATION ONLY (app/services/reset_service.py)
// Step 1: what gets removed / kept + options. Step 2: type RESET. Result:
// the simulated plan. Nothing is deleted; there is no execute endpoint yet.
// ---------------------------------------------------------------------------
(function resetSection() {
  const openBtn = document.getElementById('reset-open-btn');
  const modal = document.getElementById('reset-modal');
  if (!openBtn || !modal) return;
  const bodyEl = document.getElementById('reset-modal-body');
  const footerEl = document.getElementById('reset-modal-footer');
  const closeBtn = document.getElementById('reset-close-btn');
  const WORD = 'RESET';

  let step = 1;
  let opts = { includeBuild: false, includeGenerated: false };
  let plan = null;
  let loading = false;
  let error = '';
  let typed = '';

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function size(n) {
    if (!n) return '';
    const gb = n / 1024 ** 3;
    if (gb >= 1) return gb.toFixed(1) + ' GB';
    const mb = n / 1024 ** 2;
    return mb >= 1 ? Math.round(mb) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
  }

  const LABELS = {
    profiles: ['settings.reset.item.profiles', 'Profiles ({n})'],
    sessions: ['settings.reset.item.sessions', 'Sessions ({n})'],
    depots: ['settings.reset.item.depots', 'Depots and bundles ({n})'],
    stories: ['settings.reset.item.stories', 'Stories ({n})'],
    benchmarks: ['settings.reset.item.benchmarks', 'Model benchmark results'],
    settings: ['settings.reset.item.settings', 'Settings (the setup wizard opens again)'],
    browser: ['settings.reset.item.browser', 'Data cached in this browser'],
    styles: ['settings.reset.item.styles', 'Styles ({n}) and their images'],
    characters: ['settings.reset.item.characters', 'Build characters ({n}) and their images'],
    backgrounds: ['settings.reset.item.backgrounds', 'Build backgrounds ({n}) and their images'],
    generated: ['settings.reset.item.generated', 'Generated images in your image folder'],
    engines: ['settings.reset.item.engines', 'Image engines ({n})'],
    packContent: ['settings.reset.item.packContent', 'Template packs, tag catalogs and library flows'],
    models: ['settings.reset.item.models', 'Models in ComfyUI and LM Studio'],
    backups: ['settings.reset.item.backups', 'Your backups'],
  };
  function label(item) {
    const l = LABELS[item.id] || [item.id, item.id];
    return t(l[0], l[1], { n: item.count == null ? '' : item.count });
  }
  function note(item) {
    if (item.note === 'not-packages-yet') return t('settings.reset.notPackagesYet', 'Kept in this version: they are not packages yet.');
    if (item.note === 'engines-kept') return t('settings.reset.enginesKept', 'Installed engines are kept.');
    if (item.id === 'generated' && item.folder) return item.folder;
    if (item.id === 'backups' && item.paths[0]) return item.paths[0];
    return '';
  }
  function row(item) {
    const n = note(item);
    const sz = item.bytes ? size(item.bytes) + (item.truncated ? '+' : '') : '';
    return '<li class="' + (item.group === 'delete' ? 'is-delete' : '') + '"><span>' + esc(label(item)) +
      (n ? '<small>' + esc(n) + '</small>' : '') + '</span><span class="settings-reset-size">' + esc(sz) + '</span></li>';
  }
  function group(title, items) {
    if (!items.length) return '';
    return '<p class="settings-reset-group-title">' + esc(title) + '</p><ul class="settings-reset-list">' + items.map(row).join('') + '</ul>';
  }
  function checkbox(id, key, text, item) {
    return '<label class="settings-chip-toggle" for="' + id + '"><input type="checkbox" id="' + id + '" data-reset-opt="' + key + '"' + (opts[key] ? ' checked' : '') + '>' +
      '<span class="settings-chip-toggle-track"><span class="settings-chip-toggle-thumb"></span></span>' +
      '<span class="settings-chip-toggle-label">' + esc(text) + (item && item.bytes ? ' (' + esc(size(item.bytes)) + ')' : '') + '</span></label>';
  }

  function render() {
    const simNote = '<div class="settings-reset-sim">' + esc(t('settings.reset.simNote', 'Simulation: this shows what the reset would do. Nothing is deleted.')) + '</div>';
    if (error) {
      bodyEl.innerHTML = simNote + '<div class="settings-inline-status status-error">' + esc(error) + '</div>';
      footerEl.innerHTML = '<button type="button" class="btn settings-btn-ghost" data-reset-close>' + esc(t('settings.backup.cancel', 'Cancel')) + '</button>';
      return;
    }
    if (!plan) {
      bodyEl.innerHTML = simNote + '<p>' + esc(t('settings.common.loading', 'Loading...')) + '</p>';
      footerEl.innerHTML = '';
      return;
    }
    const items = plan.items;
    const byId = Object.fromEntries(items.map((i) => [i.id, i]));
    const del = items.filter((i) => i.group === 'delete');
    const keep = items.filter((i) => i.group === 'keep' || i.group === 'optional');
    const backupLine = t('settings.reset.backupFirst', 'First, a backup is saved to {folder} (about {size}).', { folder: plan.backup.folder, size: size(plan.backup.estimateBytes) || '—' });

    if (step === 1) {
      const buildBytes = ['styles', 'characters', 'backgrounds'].reduce((a, k) => a + (byId[k] ? byId[k].bytes : 0), 0);
      bodyEl.innerHTML = simNote +
        '<p>' + esc(t('settings.reset.lead', 'Nomad Studio will be left as if it had just been installed.')) + '</p>' +
        '<p>' + esc(backupLine) + '</p>' +
        '<div class="settings-field-block">' +
          checkbox('reset-opt-build', 'includeBuild', t('settings.reset.optBuild', 'Also delete styles, characters and backgrounds'), { bytes: buildBytes }) +
          checkbox('reset-opt-generated', 'includeGenerated', t('settings.reset.optGenerated', 'Also delete the generated images in my image folder'), byId.generated) +
        '</div>' +
        group(t('settings.reset.willDelete', 'Will be deleted'), del) +
        group(t('settings.reset.willKeep', 'Will be kept'), keep);
      footerEl.innerHTML =
        '<button type="button" class="btn settings-btn-ghost" data-reset-close>' + esc(t('settings.backup.cancel', 'Cancel')) + '</button>' +
        '<button type="button" class="btn settings-btn-danger" data-reset-next' + (loading ? ' disabled' : '') + '>' + esc(t('settings.reset.continue', 'Continue')) + '</button>';
      return;
    }

    if (step === 2) {
      bodyEl.innerHTML = simNote +
        '<p>' + esc(t('settings.reset.confirmLead', 'This cannot be undone except by restoring the backup. {count} items will be deleted ({size}).', { count: del.length, size: size(plan.totals.bytes) || '0 KB' })) + '</p>' +
        '<label class="settings-field-label" for="reset-type-input">' + esc(t('settings.reset.typeLabel', 'Type {word} to confirm', { word: WORD })) + '</label>' +
        '<input type="text" id="reset-type-input" class="settings-input settings-reset-type" autocomplete="off" spellcheck="false" value="' + esc(typed) + '">';
      footerEl.innerHTML =
        '<button type="button" class="btn settings-btn-ghost" data-reset-back>' + esc(t('settings.reset.back', 'Back')) + '</button>' +
        '<button type="button" class="btn settings-btn-danger" data-reset-run' + (typed.trim().toUpperCase() === WORD ? '' : ' disabled') + '>' + esc(t('settings.reset.runSim', 'Simulate reset')) + '</button>';
      const input = document.getElementById('reset-type-input');
      if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
      return;
    }

    // step 3 — simulated result
    const steps = [backupLine]
      .concat(del.map((i) => t('settings.reset.stepDelete', 'Delete: {what}', { what: label(i) })))
      .concat([t('settings.reset.stepWizard', 'Reload Nomad Studio and open the setup wizard.')]);
    bodyEl.innerHTML =
      '<div class="settings-reset-sim">' + esc(t('settings.reset.simDone', 'Simulation finished. Nothing was deleted and no backup was made.')) + '</div>' +
      '<p class="settings-reset-group-title">' + esc(t('settings.reset.wouldHappen', 'What the reset would have done, in order')) + '</p>' +
      '<ol class="settings-reset-list">' + steps.map((s) => '<li><span>' + esc(s) + '</span></li>').join('') + '</ol>';
    footerEl.innerHTML = '<button type="button" class="btn settings-btn-secondary" data-reset-close>' + esc(t('settings.reset.close', 'Close')) + '</button>';
  }

  async function loadPlan() {
    loading = true;
    error = '';
    render();
    try {
      const res = await fetch('/api/reset/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(opts),
        cache: 'no-store',
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json.error || ('HTTP ' + res.status));
      plan = json.plan;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
      render();
    }
  }

  function open() {
    step = 1; typed = ''; plan = null; error = '';
    opts = { includeBuild: false, includeGenerated: false };
    modal.hidden = false;
    loadPlan();
  }
  function close() { modal.hidden = true; }

  openBtn.addEventListener('click', open);
  closeBtn.addEventListener('click', close);
  modal.addEventListener('click', (e) => {
    if (e.target === modal || e.target.closest('[data-reset-close]')) return close();
    if (e.target.closest('[data-reset-next]')) { step = 2; return render(); }
    if (e.target.closest('[data-reset-back]')) { step = 1; return render(); }
    if (e.target.closest('[data-reset-run]')) {
      if (typed.trim().toUpperCase() !== WORD) return;
      step = 3;
      return render();
    }
  });
  modal.addEventListener('change', (e) => {
    const key = e.target.dataset && e.target.dataset.resetOpt;
    if (key) { opts[key] = e.target.checked; loadPlan(); }
  });
  modal.addEventListener('input', (e) => {
    if (e.target.id !== 'reset-type-input') return;
    typed = e.target.value;
    const run = footerEl.querySelector('[data-reset-run]');
    if (run) run.disabled = typed.trim().toUpperCase() !== WORD;
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !modal.hidden) close(); });
  document.addEventListener('nomad-i18n-applied', () => { if (!modal.hidden) render(); });
})();

// ---------------------------------------------------------------------------
// Advanced toggle — save space: SaveImage → PreviewImage (docs/SETUP_WIZARD.md)
// Shares the setup wizard's whitelisted state endpoint.
// ---------------------------------------------------------------------------
(async function skipComfyOutputToggleSection() {
  const toggleEl = document.getElementById('skip-comfy-output-toggle');
  const statusEl = document.getElementById('skip-comfy-output-status');
  if (!toggleEl || !statusEl) return;

  function setInlineStatus(message, isError = false) {
    statusEl.textContent = message;
    statusEl.classList.toggle('status-error', isError);
  }

  try {
    const res = await fetch('/api/setup/state', { cache: 'no-store' });
    const json = res.ok ? await res.json() : null;
    toggleEl.checked = Boolean(json && json.settings && json.settings.skipComfyOutputCopy === true);
  } catch (error) {
    setInlineStatus(t('settings.common.toggleLoadFailed', 'Failed to load toggle settings: ' + error.message, { reason: error.message }), true);
  }

  toggleEl.addEventListener('change', async () => {
    setInlineStatus(t('settings.common.saving', 'Saving...'));
    try {
      const res = await fetch('/api/setup/state', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skipComfyOutputCopy: toggleEl.checked }),
      });
      const json = await res.json().catch(() => null);
      if (!res.ok || !json || json.ok === false) throw new Error((json && json.error) || '');
      setInlineStatus(t('settings.common.saved', 'Saved.'));
    } catch (error) {
      toggleEl.checked = !toggleEl.checked;
      setInlineStatus(error.message || t('settings.common.toggleSaveFailed', 'Failed to save toggle.'), true);
    }
  });
})();

// ---------------------------------------------------------------------------
// Export configuration section
// ---------------------------------------------------------------------------
(function exportSection() {
  const exportBtn = document.getElementById('export-config-btn');
  const statusEl = document.getElementById('export-config-status');

  if (!exportBtn || !statusEl) return;

  function setStatus(msg, isError = false) {
    statusEl.textContent = msg;
    statusEl.classList.toggle('status-error', isError);
  }

  exportBtn.addEventListener('click', async () => {
    exportBtn.disabled = true;
    const origLabel = exportBtn.innerHTML;
    exportBtn.innerHTML = `<i data-lucide="loader-circle" aria-hidden="true"></i><span>${t('settings.export.exporting', 'Exporting...')}</span>`;
    if (window.lucide) window.lucide.createIcons({ nodes: [exportBtn] });
    setStatus('');

    try {
      const res = await fetch('/api/models/settings/export');
      if (!res.ok) {
        const text = await res.text();
        setStatus(t('settings.export.failed', 'Export failed: ' + (text || res.statusText), { reason: text || res.statusText }), true);
        return;
      }

      const disposition = res.headers.get('Content-Disposition') || '';
      const nameMatch = disposition.match(/filename[^;=\n]*=["']?([^"'\n;]+)/);
      const filename = nameMatch ? nameMatch[1].trim() : 'openhiker-config.zip';

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);

      setStatus(t('settings.export.success', `Exported: ${filename}`, { filename: filename }));
    } catch (e) {
      setStatus(t('settings.export.failed', 'Export failed: ' + e.message, { reason: e.message }), true);
    } finally {
      exportBtn.innerHTML = origLabel;
      if (window.lucide) window.lucide.createIcons({ nodes: [exportBtn] });
      exportBtn.disabled = false;
    }
  });
}());

