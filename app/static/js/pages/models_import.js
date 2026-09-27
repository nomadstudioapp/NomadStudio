(async function modelsImportPage() {
  document.body.classList.add('models-import-page');

  const fileInput = document.getElementById('workflow-file');
  const fileInputTrigger = document.getElementById('workflow-file-trigger');
  const analyzeBtn = document.getElementById('analyze-workflow-btn');
  const saveBtn = document.getElementById('save-workflow-btn');
  const nameInput = document.getElementById('import-name');
  // Workflow identifier: "--v <slug>" in a prompt picks this engine
  // (app/services/import_slugs.py). Checked here too, with translated
  // messages; the backend refuses the same cases.
  const slugInput = document.getElementById('import-slug');
  const slugHint = document.getElementById('import-slug-hint');
  const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  let knownImports = [];
  function _i18n(key, fallback) {
    return window.NomadI18n ? window.NomadI18n.t(key, fallback) : fallback;
  }
  function slugProblem() {
    const slug = slugInput ? slugInput.value.trim() : '';
    if (!slug) return '';
    if (slug.length > 32 || !SLUG_RE.test(slug)) {
      return _i18n('models.import.slugInvalid', 'Use lowercase letters, numbers and dashes (up to 32).');
    }
    const owner = knownImports.find((imp) => imp.slug === slug && imp.id !== editingImportId);
    if (owner) {
      return _i18n('models.import.slugTaken', 'Already used by {name}.').replace('{name}', owner.name || owner.id);
    }
    return '';
  }
  function refreshSlugHint() {
    if (!slugHint) return;
    const problem = slugProblem();
    slugHint.classList.toggle('is-error', !!problem);
    slugHint.textContent = problem || _i18n('models.import.slugHint',
      'Pick this engine from a prompt with --v and this word. Lowercase letters, numbers and dashes.');
  }
  if (slugInput) {
    slugInput.addEventListener('input', () => {
      const lowered = slugInput.value.toLowerCase().replace(/[\s_]+/g, '-');
      if (lowered !== slugInput.value) slugInput.value = lowered;
      refreshSlugHint();
    });
  }
  const statusEl = document.getElementById('import-status');
  const analysisOutput = document.getElementById('analysis-output');
  const savedImportsEl = document.getElementById('saved-imports');
  const activeImportsQueueEl = document.getElementById('active-imports-queue');
  const queueFreeMemoryToggle = document.getElementById('queue-free-memory-toggle');
  const comfyUriEl = document.getElementById('comfy-uri');
  const testComfyConnectionBtn = document.getElementById('test-comfy-connection');
  const comfyAvailabilityChipEl = document.getElementById('comfy-availability-chip');
  const comfyAvailabilityTextEl = document.getElementById('comfy-availability-text');
  const openModalBtn = document.getElementById('open-import-modal-btn');
  const closeModalBtn = document.getElementById('close-import-modal-btn');
  const modalBackdrop = document.getElementById('import-modal-backdrop');

  if (!fileInput || !analyzeBtn || !saveBtn || !analysisOutput || !savedImportsEl || !comfyUriEl) {
    return;
  }

  // Settings → Models → Images embeds this page's real markup inside the
  // ".cs-settings-detail" flyout, which animates with a CSS `transform` —
  // that makes it the containing block for any `position: fixed`
  // descendant, so this modal (fixed, meant to cover the viewport) was
  // rendering squeezed into the flyout's ~460px width instead of as a
  // proper wide, centered dialog. Move it to <body> so it always resolves
  // against the real viewport, whether this is the standalone page or the
  // embedded flyout.
  if (modalBackdrop && modalBackdrop.parentElement !== document.body) {
    document.body.appendChild(modalBackdrop);
  }

  // Embedded in Settings → Images, Add/Edit is a third panel in the column
  // stack rather than a dialog floating over everything: it is a
  // continuation of the list behind it, not an interruption of it. On the
  // standalone /models/import page there is no panel stack to belong to, so
  // it stays the centred modal it has always been.
  const inSettingsPanel = !!document.getElementById('cs-settings-detail');
  if (modalBackdrop && inSettingsPanel) {
    modalBackdrop.classList.add('is-settings-panel');
  }

  // Modal open/close
  const modalTitleEl = document.getElementById('import-modal-title');
  function openImportModal(title) {
    if (modalBackdrop) {
      if (modalTitleEl) modalTitleEl.textContent = title || 'Add Import';
      modalBackdrop.classList.add('open');
      modalBackdrop.removeAttribute('aria-hidden');
      // Fallback for cases where class-based CSS is overridden by stale runtime styles.
      modalBackdrop.style.display = 'flex';
    }
  }
  function closeImportModal() {
    if (modalBackdrop) {
      modalBackdrop.classList.remove('open');
      modalBackdrop.setAttribute('aria-hidden', 'true');
      modalBackdrop.style.display = '';
    }
    editingImportId = null;
  }
  if (openModalBtn) openModalBtn.addEventListener('click', () => {
    editingImportId = null;
    editingAnnotation = null;
    rawWorkflow = null;
    lastAnalysis = null;
    if (nameInput) nameInput.value = '';
    if (slugInput) { slugInput.value = ''; refreshSlugHint(); }
    if (analysisOutput) analysisOutput.innerHTML = '';
    if (saveBtn) saveBtn.disabled = true;
    if (analyzeBtn) analyzeBtn.disabled = true;
    if (fileInput) fileInput.value = '';
    if (statusEl) statusEl.textContent = 'No file loaded.';
    openImportModal('Add Import');
  });
  if (closeModalBtn) closeModalBtn.addEventListener('click', closeImportModal);
  if (modalBackdrop) {
    modalBackdrop.addEventListener('click', (e) => {
      if (e.target === modalBackdrop) closeImportModal();
    });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeImportModal();
  });

  if (fileInputTrigger) {
    fileInputTrigger.addEventListener('click', () => {
      fileInput.click();
    });
  }

  let rawWorkflow = null;
  let lastAnalysis = null;
  let editingImportId = null;
  // Existing saved annotation, only populated when editing a previously-saved
  // import — carries any Optional-part labels the user already typed in, so
  // reopening for edit doesn't reset them back to "Optional part <id>".
  let editingAnnotation = null;
  // Live editable state for the Optional parts card — rebuilt by renderAnalysis()
  // on every (re)analyze, read by the Save handler.
  let editableOptionalSubgraphs = [];
  // Same pattern for the LoRAs card. A LoRA usually needs its trigger words in
  // the prompt to do anything, and when they're missing it doesn't fail — it
  // just quietly underperforms. Import time is the moment to ask for them,
  // while the workflow and its LoRAs are in front of the user (#102).
  let editableLoras = [];

  // ComfyUI Models Folder is edited in Settings → ComfyUI now (see settings.js).
  // Here we only read the cached value to resolve full paths / check-files for the
  // Downloads panel below.
  let cachedModelsFolder = '';

  function getModelsFolder() {
    return cachedModelsFolder;
  }

  function setStatus(message, isError = false) {
    statusEl.textContent = message;
    statusEl.classList.toggle('status-error', isError);
  }

  function setComfyAvailability(available, message) {
    if (!comfyAvailabilityChipEl || !comfyAvailabilityTextEl) return;
    comfyAvailabilityChipEl.classList.toggle('available', !!available);
    comfyAvailabilityChipEl.classList.toggle('unavailable', available === false);
    if (message) {
      comfyAvailabilityTextEl.textContent = message;
      return;
    }
    if (available === true) {
      comfyAvailabilityTextEl.textContent = 'ComfyUI available';
      return;
    }
    if (available === false) {
      comfyAvailabilityTextEl.textContent = 'ComfyUI unavailable';
      return;
    }
    comfyAvailabilityTextEl.textContent = 'Checking ComfyUI...';
  }

  async function probeComfyAvailability(uri) {
    const comfyApiUrl = String(uri || '').trim();
    if (!comfyApiUrl) {
      setComfyAvailability(false);
      return;
    }
    setComfyAvailability(null, 'Checking ComfyUI...');
    try {
      await window.openJourneyApi.testModelsConnection({ comfyApiUrl });
      setComfyAvailability(true);
    } catch {
      setComfyAvailability(false);
    }
  }

  function escapeAttr(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function normalizeWorkflowImageValue(value) {
    const text = String(value || '').replace(/\r/g, '\n');
    const parts = text.split('\n');
    for (let i = 0; i < parts.length; i += 1) {
      const line = String(parts[i] || '').trim();
      if (line) return line;
    }
    return '';
  }

  function extractAssignedImageFromWorkflow(workflow) {
    if (!workflow || typeof workflow !== 'object' || Array.isArray(workflow)) return '';
    const nodes = Object.values(workflow);
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i];
      if (!node || typeof node !== 'object' || Array.isArray(node)) continue;
      if (String(node.class_type || '').trim() !== 'PrimitiveStringMultiline') continue;
      const meta = node._meta && typeof node._meta === 'object' ? node._meta : {};
      if (String(meta.title || '').trim().toLowerCase() !== 'image') continue;
      const inputs = node.inputs && typeof node.inputs === 'object' ? node.inputs : {};
      return normalizeWorkflowImageValue(inputs.value || '');
    }
    return '';
  }

  function resolveAssignedImagePreviewUrl(rawImageValue) {
    const value = String(rawImageValue || '').trim();
    if (!value) return '';
    if (
      value.startsWith('http://')
      || value.startsWith('https://')
      || value.startsWith('data:image/')
      || value.startsWith('/api/models/workflow-logos/')
      || value.startsWith('/static/')
    ) {
      return value;
    }
    const normalized = value.replace(/\\/g, '/');
    const fileName = normalized.split('/').filter(Boolean).pop() || '';
    if (!fileName) return '';
    return `/api/models/workflow-logos/${encodeURIComponent(fileName)}`;
  }

  function showRenameModal(id, currentName) {
    let modal = document.getElementById('rename-import-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'rename-import-modal';
      modal.className = 'create-modal';
      modal.innerHTML = `
        <div class="create-modal-backdrop" id="rename-import-modal-backdrop"></div>
        <div class="create-modal-shell rename-import-modal-shell">
          <h3 style="margin:0 0 10px;">Rename Import</h3>
          <label>
            Name
            <input type="text" id="rename-import-input" />
          </label>
          <div class="btn-row" style="margin-top:10px; justify-content:flex-end;">
            <button type="button" class="btn" id="rename-import-cancel">Cancel</button>
            <button type="button" class="btn primary" id="rename-import-confirm">Rename</button>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
      document.getElementById('rename-import-modal-backdrop').addEventListener('click', () => {
        modal.classList.remove('open');
      });
      document.getElementById('rename-import-cancel').addEventListener('click', () => {
        modal.classList.remove('open');
      });
    }

    const input = modal.querySelector('#rename-import-input');
    const confirmBtn = modal.querySelector('#rename-import-confirm');

    // Reset: detach old listener by replacing the button clone
    const fresh = confirmBtn.cloneNode(true);
    confirmBtn.replaceWith(fresh);

    input.value = currentName;
    modal.classList.add('open');
    input.focus();
    input.select();

    async function doRename() {
      const newName = input.value.trim();
      if (!newName) return;
      try {
        await window.openJourneyApi.renameImport(id, newName);
        modal.classList.remove('open');
        await refreshImports();
        setStatus('Import renamed.');
      } catch (error) {
        setStatus(error.message || 'Failed to rename import.', true);
      }
    }

    modal.querySelector('#rename-import-confirm').addEventListener('click', doRename);
    input.addEventListener('keydown', function handler(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        doRename();
        input.removeEventListener('keydown', handler);
      } else if (e.key === 'Escape') {
        modal.classList.remove('open');
        input.removeEventListener('keydown', handler);
      }
    });
  }

  function showFreeMemoryConfirmModal(activeName, onFreeAndActivate, onJustActivate) {
    let modal = document.getElementById('free-memory-confirm-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'free-memory-confirm-modal';
      modal.className = 'create-modal';
      modal.innerHTML = `
        <div class="create-modal-backdrop" id="free-memory-confirm-backdrop"></div>
        <div class="create-modal-shell" style="max-width:400px;">
          <h3 style="margin:0 0 8px;">Switch Model</h3>
          <p id="free-memory-confirm-text" class="muted-note" style="margin:0 0 14px;"></p>
          <div class="btn-row" style="justify-content:flex-end; flex-wrap:wrap;">
            <button type="button" class="btn" id="free-memory-confirm-skip">Just Activate</button>
            <button type="button" class="btn primary" id="free-memory-confirm-ok">
              <i data-lucide="cpu" style="width:14px;height:14px;vertical-align:middle;margin-right:4px;"></i>
              Clean GPU &amp; Activate
            </button>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
      document.getElementById('free-memory-confirm-backdrop').addEventListener('click', () => {
        modal.classList.remove('open');
      });
    }

    modal.querySelector('#free-memory-confirm-text').textContent =
      `Activating "${activeName}". Do you want to free the previous model from GPU memory first?`;

    // Replace buttons to detach old listeners
    const okBtn = modal.querySelector('#free-memory-confirm-ok');
    const skipBtn = modal.querySelector('#free-memory-confirm-skip');
    const freshOk = okBtn.cloneNode(true);
    const freshSkip = skipBtn.cloneNode(true);
    okBtn.replaceWith(freshOk);
    skipBtn.replaceWith(freshSkip);

    modal.querySelector('#free-memory-confirm-ok').addEventListener('click', () => {
      modal.classList.remove('open');
      onFreeAndActivate();
    });
    modal.querySelector('#free-memory-confirm-skip').addEventListener('click', () => {
      modal.classList.remove('open');
      onJustActivate();
    });

    modal.classList.add('open');
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons({ nodes: [modal] });
    }
  }

  function showRequirementsModal(files) {
    let modal = document.getElementById('requirements-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'requirements-modal';
      modal.className = 'create-modal';
      modal.innerHTML = `
        <div class="create-modal-backdrop" id="requirements-modal-backdrop"></div>
        <div class="create-modal-shell requirements-modal-shell">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
            <h3 style="margin:0;">Requirements</h3>
            <button type="button" class="btn" id="requirements-modal-close">Close</button>
          </div>
          <div id="requirements-modal-list" class="stack"></div>
        </div>
      `;
      document.body.appendChild(modal);

      document.getElementById('requirements-modal-backdrop').addEventListener('click', () => {
        modal.classList.remove('open');
      });
      document.getElementById('requirements-modal-close').addEventListener('click', () => {
        modal.classList.remove('open');
      });
    }

    const listEl = modal.querySelector('#requirements-modal-list');
    listEl.innerHTML = '';

    if (!files.length) {
      listEl.innerHTML = '<p class="muted-note">No model files found in this workflow.</p>';
    } else {
      files.forEach((file) => {
        const row = document.createElement('div');
        row.className = 'requirements-file-row';
        const name = document.createElement('span');
        name.className = 'requirements-file-name';
        name.textContent = file;
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'btn requirements-copy-btn';
        copyBtn.title = 'Copy filename';
        copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
        copyBtn.addEventListener('click', () => {
          navigator.clipboard.writeText(file).then(() => {
            copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
            setTimeout(() => {
              copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
            }, 1500);
          }).catch(() => {});
        });
        row.appendChild(name);
        row.appendChild(copyBtn);
        listEl.appendChild(row);
      });
    }

    modal.classList.add('open');
  }

  function renderSavedImports(data) {
    savedImportsEl.innerHTML = '';
    const imports = data.imports || [];
    knownImports = imports;
    const activeIds = data.activeImportIds || [];

    if (!imports.length) {
      savedImportsEl.innerHTML = '<p class="muted-note">No imports saved yet.</p>';
      return;
    }

    imports.forEach((item) => {
      const safeUri = escapeAttr(item.comfyApiUrl || '');
      const hasImageInput = !!(item.analysis?.detected?.hasImageInput);
      const imageInputBadge = hasImageInput
        ? `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" title="Accepts image input" style="vertical-align:middle;margin-left:4px;opacity:0.7;"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`
        : '';
      const isActive = activeIds.includes(item.id);
      const row = document.createElement('article');
      row.className = 'import-item import-item-stacked';
      row.innerHTML = `
        <div>
          <span class="import-name-row"><strong>${item.name}</strong>${imageInputBadge}${item.slug ? `<code class="import-slug">--v ${escapeAttr(item.slug)}</code>` : ''}</span>
          <p class="muted-note import-item-uri" title="${safeUri}">${safeUri || '—'}</p>
          <div class="btn-row" style="margin-top:8px; flex-wrap:wrap; gap:4px;">
            <button type="button" class="btn sm-btn ${isActive ? 'primary active-queue-btn' : ''}" data-toggle-active-id="${item.id}">
              ${isActive ? '✓ In Queue' : '+ Queue'}
            </button>
            <button type="button" class="btn sm-btn" data-edit-id="${item.id}">Edit</button>
            <button type="button" class="btn sm-btn" data-reimport-id="${item.id}">Reimport</button>
            <button type="button" class="btn sm-btn" data-requirements-id="${item.id}">Files</button>
            <button type="button" class="btn sm-btn" data-export-id="${item.id}">Export</button>
            <button type="button" class="btn sm-btn" data-delete-id="${item.id}">Delete</button>
          </div>
        </div>
      `;
      savedImportsEl.appendChild(row);
    });

    savedImportsEl.querySelectorAll('[data-toggle-active-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-toggle-active-id');
        const currentlyActive = (data.activeImportIds || []).includes(id);
        try {
          if (currentlyActive) {
            await window.openJourneyApi.deactivateImport(id);
            setStatus('Removed from active queue.');
          } else {
            const allImports = data.imports || [];
            const thisItem = allImports.find((i) => i.id === id);
            const thisHasImage = !!(thisItem?.analysis?.detected?.hasImageInput);
            const activeIds = data.activeImportIds || [];
            if (thisHasImage && activeIds.length > 0) {
              setStatus('Models with image input must be alone in the queue. Remove the current models first.', true);
              return;
            }
            if (!thisHasImage && activeIds.length > 0) {
              const activeItems = activeIds.map((aid) => allImports.find((i) => i.id === aid)).filter(Boolean);
              const queueHasImageModel = activeItems.some((i) => !!(i.analysis?.detected?.hasImageInput));
              if (queueHasImageModel) {
                setStatus('Cannot add a text-only model while an image-input model is in the queue. Remove it first.', true);
                return;
              }
            }
            await window.openJourneyApi.activateImport(id);
            setStatus('Added to active queue.');
          }
          await refreshImports();
        } catch (err) {
          setStatus(err.message || 'Failed to update queue.', true);
        }
      });
    });

    savedImportsEl.querySelectorAll('[data-edit-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-edit-id');
        if (!id) return;
        editingImportId = id;
        openImportModal('Edit Import');
        // Clear previous state while loading
        if (nameInput) nameInput.value = '';
    if (slugInput) { slugInput.value = ''; refreshSlugHint(); }
        analysisOutput.innerHTML = '<p class="muted-note">Loading...</p>';
        saveBtn.disabled = true;
        rawWorkflow = null;
        lastAnalysis = null;
        try {
          const res = await fetch(`/api/models/imports/${encodeURIComponent(id)}`);
          const data = await res.json();
          const record = data.import;
          if (!record) throw new Error('Not found');
          if (nameInput) nameInput.value = record.name || '';
          if (slugInput) { slugInput.value = record.slug || ''; refreshSlugHint(); }
          editingAnnotation = record.annotation || null;
          if (record.workflow) {
            rawWorkflow = record.workflow;
            lastAnalysis = record.analysis;
            renderAnalysis(lastAnalysis);
            saveBtn.disabled = false;
          } else {
            analysisOutput.innerHTML = '<p class="muted-note">No workflow data stored.</p>';
          }
        } catch (err) {
          analysisOutput.innerHTML = `<p class="muted-note status-error">Failed to load import: ${err.message}</p>`;
        }
      });
    });

    savedImportsEl.querySelectorAll('[data-requirements-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-requirements-id');
        if (!id) return;
        try {
          const result = await window.openJourneyApi.getImportRequirements(id);
          showRequirementsModal(result.files || []);
        } catch (error) {
          setStatus(error.message || 'Failed to load requirements.', true);
        }
      });
    });

    savedImportsEl.querySelectorAll('[data-reimport-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-reimport-id');
        if (!id) return;

        const record = imports.find((entry) => String(entry?.id || '').trim() === id);
        const modelName = String(record?.name || 'this import').trim();
        const confirmReset = window.confirm(`Reset values to workflow defaults for "${modelName}"?`);
        if (!confirmReset) return;

        try {
          setStatus('Resetting import values to workflow defaults...');
          const detail = await window.openJourneyApi.getImport(id);
          const fullImport = detail && detail.import && typeof detail.import === 'object' ? detail.import : null;
          if (!fullImport || !fullImport.workflow || typeof fullImport.workflow !== 'object') {
            throw new Error('Import workflow not found.');
          }

          const safeName = String(fullImport.name || modelName).trim() || 'Imported Workflow';
          const safeComfyUri = String(fullImport.comfyApiUrl || '').trim();

          await window.openJourneyApi.updateImport(id, {
            name: safeName,
            workflow: fullImport.workflow,
            comfyApiUrl: safeComfyUri,
          });

          // Ensure Studio sidebar uses fresh defaults immediately for this import.
          try {
            const cacheKey = 'openjourney_model_advanced_cache_v1';
            const rawCache = localStorage.getItem(cacheKey);
            if (rawCache) {
              const parsedCache = JSON.parse(rawCache);
              if (parsedCache && typeof parsedCache === 'object' && parsedCache[id]) {
                delete parsedCache[id];
                localStorage.setItem(cacheKey, JSON.stringify(parsedCache));
              }
            }
          } catch (_) {}

          await refreshImports();
          setStatus(`Defaults restored for "${safeName}".`);
        } catch (error) {
          setStatus(error?.message || 'Failed to reset import defaults.', true);
        }
      });
    });

    savedImportsEl.querySelectorAll('[data-export-id]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-export-id');
        if (!id) return;
        window.location.href = `/api/models/imports/${encodeURIComponent(id)}/workflow`;
      });
    });

    savedImportsEl.querySelectorAll('[data-delete-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-delete-id');
        if (!id) return;
        const ok = window.confirm('Delete this import? This cannot be undone.');
        if (!ok) return;
        try {
          await window.openJourneyApi.deleteImport(id);

          // Clean up per-model advanced cache (CFG/Steps) for the deleted import
          try {
            const cacheKey = 'openjourney_model_advanced_cache_v1';
            const raw = localStorage.getItem(cacheKey);
            if (raw) {
              const cache = JSON.parse(raw);
              if (cache && typeof cache === 'object' && cache[id]) {
                delete cache[id];
                localStorage.setItem(cacheKey, JSON.stringify(cache));
              }
            }
          } catch (_) {}

          await refreshImports();
          setStatus('Import deleted.');
        } catch (error) {
          setStatus(error.message || 'Failed to delete import.', true);
        }
      });
    });


  }

  function renderAnalysis(analysis) {
    analysisOutput.innerHTML = '';

    // Defined card — shown when the workflow has a Config node
    const configNode = analysis.configNode || {};
    if (configNode.name || configNode.base_resolution || configNode.recommended_sampler) {
      const definedCard = document.createElement('article');
      definedCard.className = 'analysis-card defined-card';

      let html = '<div class="defined-card-header"><span class="defined-badge">DEFINED</span>';
      if (configNode.name) html += `<strong class="defined-name">${escapeAttr(configNode.name)}</strong>`;
      html += '</div><div class="defined-card-body">';

      // Meta row: base resolution + sampler + scheduler
      const metaParts = [];
      if (configNode.base_resolution) metaParts.push(`Base: ${escapeAttr(configNode.base_resolution)}`);
      if (configNode.recommended_sampler) metaParts.push(`Sampler: ${escapeAttr(configNode.recommended_sampler)}`);
      if (configNode.recommended_scheduler) metaParts.push(`Scheduler: ${escapeAttr(configNode.recommended_scheduler)}`);
      if (metaParts.length) html += `<p class="muted-note defined-meta">${metaParts.join(' &nbsp;·&nbsp; ')}</p>`;

      // Profiles
      const profiles = configNode.profiles || {};
      const profileOrder = ['draft', 'medium', 'high'];
      const profileChips = profileOrder
        .filter((k) => profiles[k])
        .map((k) => {
          const p = profiles[k];
          const parts = [];
          if (p.steps != null) parts.push(`${p.steps} steps`);
          if (p.cfg != null) parts.push(`CFG ${p.cfg}`);
          return `<span class="defined-profile-chip"><span class="defined-profile-label">${k}</span>${parts.length ? ' ' + escapeAttr(parts.join(', ')) : ''}</span>`;
        });
      if (profileChips.length) {
        html += `<div class="defined-profiles">${profileChips.join('')}</div>`;
      }

      // Aspect ratios
      const aspectRatios = Array.isArray(configNode.aspect_ratios) ? configNode.aspect_ratios : [];
      if (aspectRatios.length) {
        html += '<div class="defined-aspect-ratios">';
        aspectRatios.forEach((ar) => {
          const label = escapeAttr(String(ar.label || `${ar.width}×${ar.height}`));
          html += `<span class="defined-ar-chip">${label}</span>`;
        });
        html += '</div>';
      }

      html += '</div>';
      definedCard.innerHTML = html;
      analysisOutput.appendChild(definedCard);
    }

    const detect = analysis.detected || {};
    const assignedImageValue = extractAssignedImageFromWorkflow(rawWorkflow);
    const assignedImageUrl = resolveAssignedImagePreviewUrl(assignedImageValue);
    const summary = document.createElement('article');
    summary.className = 'analysis-card';
    summary.innerHTML = `
      <h3>Detected</h3>
      <div class="analysis-detected-layout">
        <figure class="analysis-assigned-image-wrap" title="${escapeAttr(assignedImageValue || 'No image assigned')}">
          ${assignedImageUrl
    ? `<img class="analysis-assigned-image" src="${escapeAttr(assignedImageUrl)}" alt="Assigned workflow image" />`
    : '<span class="analysis-assigned-image-placeholder">No image</span>'}
        </figure>
        <div class="analysis-detected-copy">
          <p class="muted-note">Sampler: ${detect.samplerNodeId || 'not found'}</p>
          <p class="muted-note">SaveImage nodes: ${detect.saveImageCount || 0}</p>
          <p class="muted-note">Positive node: ${detect.positiveNodeId || 'not found'}</p>
          <p class="muted-note">Negative node: ${detect.negativeNodeId || 'not found'}</p>
          <p class="muted-note">Image input: ${detect.hasImageInput ? `Yes (nodes: ${(detect.loadImageNodeIds || []).join(', ')})` : 'No'}</p>
        </div>
      </div>
    `;
    const assignedImgEl = summary.querySelector('.analysis-assigned-image');
    if (assignedImgEl) {
      assignedImgEl.addEventListener('error', () => {
        const figure = assignedImgEl.closest('.analysis-assigned-image-wrap');
        if (!figure) return;
        figure.innerHTML = '<span class="analysis-assigned-image-placeholder">No image</span>';
      });
    }
    analysisOutput.appendChild(summary);

    const basic = document.createElement('article');
    basic.className = 'analysis-card';
    basic.innerHTML = '<h3>Basic Parameters</h3>';
    const basicGrid = document.createElement('div');
    basicGrid.className = 'param-grid';
    (analysis.basicParameters || []).forEach((item) => {
      const wrap = document.createElement('label');
      wrap.textContent = item.label;
      const input = document.createElement(item.type === 'text' ? 'textarea' : 'input');
      if (item.type !== 'text') {
        input.type = 'number';
      }
      input.disabled = true;
      input.value = item.value ?? '';
      wrap.appendChild(input);
      basicGrid.appendChild(wrap);
    });
    basic.appendChild(basicGrid);
    analysisOutput.appendChild(basic);

    // ── LORAS ───────────────────────────────────────────────────────────────
    // Sits right under Basic Parameters because that is where the eye already
    // is. Pre-filled from CivitAI's trainedWords when the LoRA came from there
    // (imports_civitai.py), and from whatever was typed on a previous edit —
    // so this is a confirmation in the common case, not a chore.
    const savedLoras = Array.isArray(editingAnnotation && editingAnnotation.loras)
      ? editingAnnotation.loras : [];
    // Editing an existing import renders its *stored* analysis, which for
    // anything imported before this feature has no `loras` key — the card
    // would silently never appear. The annotation has carried the catalog all
    // along, so fall back to it.
    const detectedLoras = Array.isArray(analysis.loras) && analysis.loras.length
      ? analysis.loras
      : savedLoras;
    editableLoras = detectedLoras.map((item) => {
      const fileName = String(item.fileName || '');
      const prior = savedLoras.find(
        (s) => String(s.fileName || '').toLowerCase() === fileName.toLowerCase(),
      );
      return Object.assign({}, item, {
        fileName,
        triggerWords: String(
          (prior && prior.triggerWords) || item.triggerWords || '',
        ),
      });
    });

    if (editableLoras.length) {
      const lorasCard = document.createElement('article');
      lorasCard.className = 'analysis-card';
      lorasCard.innerHTML =
        '<h3>LoRAs</h3>'
        + '<p class="muted-note">Trigger words are prepended to the prompt when this '
        + 'workflow generates. Separate several with commas. Leave blank if the LoRA '
        + 'needs none.</p>';
      const lorasGrid = document.createElement('div');
      lorasGrid.className = 'stack';
      const loraInputs = [];
      const loraLinks = [];
      editableLoras.forEach((lora, index) => {
        const wrap = document.createElement('label');
        const nameRow = document.createElement('span');
        nameRow.className = 'lora-name-row';
        nameRow.textContent = lora.fileName;

        // Manual fallback. The lookup can fail for plenty of ordinary
        // reasons — the LoRA isn't on CivitAI, the network is blocked — and
        // when it does the user still needs a way in. Points at the model
        // page once we know it, and at a CivitAI search for the file name
        // until then, which is what you'd type yourself anyway.
        const link = document.createElement('a');
        link.className = 'lora-civitai-link';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'Open on CivitAI ↗';
        const bare = String(lora.fileName || '').replace(/\.[^.]+$/, '');
        link.href = lora.uri && /civitai\.com\/models\//.test(lora.uri)
          ? lora.uri
          : `https://civitai.com/search/models?query=${encodeURIComponent(bare)}`;
        link.title = 'Look this LoRA up by hand and copy its trigger words';
        nameRow.appendChild(link);
        wrap.appendChild(nameRow);

        const input = document.createElement('input');
        input.type = 'text';
        input.placeholder = 'Trigger words, comma separated';
        input.value = lora.triggerWords;
        input.addEventListener('input', () => {
          editableLoras[index].triggerWords = input.value;
        });
        wrap.appendChild(input);
        lorasGrid.appendChild(wrap);
        loraInputs.push(input);
        loraLinks.push(link);
      });
      lorasCard.appendChild(lorasGrid);

      // Identify each LoRA on CivitAI by the SHA-256 of the file itself.
      // Matching on content rather than name is what makes this work for
      // files that were renamed or dropped in by hand — which is exactly the
      // case that has no trigger words recorded anywhere.
      const lookupRow = document.createElement('div');
      lookupRow.className = 'stack';
      const lookupBtn = document.createElement('button');
      lookupBtn.type = 'button';
      lookupBtn.className = 'btn';
      lookupBtn.textContent = 'Look up on CivitAI';
      const lookupNote = document.createElement('p');
      lookupNote.className = 'muted-note';
      lookupRow.appendChild(lookupBtn);
      lookupRow.appendChild(lookupNote);
      lorasCard.appendChild(lookupRow);

      lookupBtn.addEventListener('click', async () => {
        lookupBtn.disabled = true;
        lookupNote.textContent = 'Hashing the files and asking CivitAI…';
        try {
          const res = await fetch('/api/models/imports/loras/civitai-lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ loras: editableLoras.map((l) => l.fileName) }),
          });
          const data = await res.json();
          const results = (data && data.results) || {};
          let filled = 0;
          let noWords = 0;
          const notFound = [];
          editableLoras.forEach((lora, index) => {
            const hit = results[lora.fileName];
            if (!hit || !hit.found) {
              notFound.push(lora.fileName);
              return;
            }
            if (hit.downloadUrl) editableLoras[index].uri = hit.downloadUrl;
            if (hit.modelName) editableLoras[index].name = hit.modelName;
            // Retarget the fallback link at the actual model page now we know it.
            if (hit.modelPage && loraLinks[index]) {
              loraLinks[index].href = hit.modelPage;
              loraLinks[index].title = hit.modelName || 'Open this LoRA on CivitAI';
            }
            if (hit.triggerWords) {
              editableLoras[index].triggerWords = hit.triggerWords;
              loraInputs[index].value = hit.triggerWords;
              filled += 1;
            } else {
              // A real answer, not a failure: this LoRA has none.
              noWords += 1;
              loraInputs[index].placeholder = 'CivitAI lists no trigger words for this one';
            }
          });
          const parts = [];
          if (filled) parts.push(`${filled} filled in`);
          if (noWords) parts.push(`${noWords} with no trigger words on CivitAI`);
          if (notFound.length) parts.push(`${notFound.length} not identified`);
          lookupNote.textContent = parts.length ? parts.join(' · ') : 'Nothing to look up.';
        } catch (err) {
          lookupNote.textContent = `Lookup failed: ${err.message}`;
        } finally {
          lookupBtn.disabled = false;
        }
      });

      analysisOutput.appendChild(lorasCard);
    }

    const advanced = document.createElement('details');
    advanced.className = 'analysis-card';
    advanced.innerHTML = '<summary>Advanced Parameters</summary>';
    const advList = document.createElement('div');
    advList.className = 'stack';
    const params = analysis.advancedParameters || [];
    if (!params.length) {
      advList.innerHTML = '<p class="muted-note">No advanced scalar parameters found.</p>';
    } else {
      params.forEach((item) => {
        const p = document.createElement('p');
        p.className = 'muted-note';
        p.textContent = `${item.label} (${item.nodeClass}:${item.nodeId}) = ${item.value}`;
        advList.appendChild(p);
      });
    }
    advanced.appendChild(advList);
    analysisOutput.appendChild(advanced);

    // Downloads section
    const downloads = analysis.downloads || [];
    if (downloads.length > 0) {
      const modelsFolder = getModelsFolder();
      const dlCard = document.createElement('article');
      dlCard.className = 'analysis-card downloads-card';

      const dlPath = document.createElement('p');
      dlPath.className = 'downloads-example-path';
      dlPath.textContent = modelsFolder
        ? `Models folder: ${modelsFolder}`
        : 'Set your ComfyUI Models Folder above to see full paths. e.g.: C:\\myComfyUI\\ComfyUI\\models';
      dlCard.appendChild(dlPath);

      const dlPanel = document.createElement('div');
      dlPanel.className = 'downloads-panel open';

      // Builds a fresh, fully-wired row for one download entry. Pulled out
      // into a function (rather than built once per `downloads` entry) so a
      // text encoder shared by more than one quantization level — e.g. Flux
      // Klein's 4B FP8 and 4B INT8 both needing qwen_3_4b.safetensors — can
      // get its own row instance in *each* pairing group instead of being
      // "claimed" by whichever group is built first and left out of the rest.
      function buildRow(dl) {
        const row = document.createElement('a');
        row.className = 'downloads-row';
        row.title = dl.url;
        // Subfolder may be nested (e.g. "diffusion_models/krea2") — normalize
        // to backslashes for display so it doesn't mix "/" and "\" mid-path.
        const displaySubfolder = String(dl.subfolder || '').replace(/\//g, '\\');

        if (modelsFolder) {
          // When folder is set, download to that folder via backend
          row.href = '#';
          row.addEventListener('click', async (e) => {
            e.preventDefault();
            if (row.classList.contains('downloading') || row.classList.contains('download-done')) return;
            const origTitle = row.title;

            function setProgress(pct) {
              if (pct >= 0) {
                row.style.background = `linear-gradient(90deg, rgba(39,168,79,0.25) ${pct}%, transparent ${pct}%)`;
                if (!pctSpan.parentNode) row.appendChild(pctSpan);
                pctSpan.textContent = `${pct}%`;
              } else {
                row.style.background = '';
                pctSpan.textContent = '';
              }
            }

            const pctSpan = document.createElement('span');
            pctSpan.className = 'downloads-pct';

            async function doDownload(force = false) {
              // First: check existence (non-streaming)
              if (!force) {
                try {
                  const checkResp = await fetch('/api/models/imports/download-file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: dl.url, subfolder: dl.subfolder, filename: dl.filename }),
                  });
                  // Existence check returns JSON (not ndjson)
                  const ct = checkResp.headers.get('content-type') || '';
                  if (ct.includes('application/json')) {
                    const result = await checkResp.json();
                    if (result.exists) {
                      if (!confirm(`File already exists:\n${result.path}\n\nOverwrite?`)) return;
                      force = true;
                    } else if (result.error) {
                      row.classList.add('download-error');
                      row.title = result.error;
                      setTimeout(() => { row.classList.remove('download-error'); row.title = origTitle; }, 4000);
                      return;
                    }
                  }
                } catch (err) {
                  row.classList.add('download-error');
                  row.title = err.message;
                  setTimeout(() => { row.classList.remove('download-error'); row.title = origTitle; }, 4000);
                  return;
                }
              }

              // Stream download with progress
              row.classList.add('downloading');
              row.title = 'Downloading…';
              setProgress(0);
              try {
                const resp = await fetch('/api/models/imports/download-file', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ url: dl.url, subfolder: dl.subfolder, filename: dl.filename, force: true }),
                });
                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buf = '';
                let lastResult = null;
                while (true) {
                  const { done, value } = await reader.read();
                  if (value) buf += decoder.decode(value, { stream: true });
                  const lines = buf.split('\n');
                  buf = lines.pop() || '';
                  for (const line of lines) {
                    if (!line.trim()) continue;
                    try { lastResult = JSON.parse(line); } catch { continue; }
                    if (lastResult.progress >= 0) setProgress(lastResult.progress);
                  }
                  if (done) break;
                }
                if (lastResult?.ok) {
                  setProgress(100);
                  setTimeout(() => {
                    row.style.background = '';
                    if (pctSpan.parentNode) pctSpan.remove();
                    row.classList.add('download-done');
                    row.title = `Saved to ${lastResult.path}`;
                  }, 600);
                } else if (lastResult?.error) {
                  setProgress(-1);
                  row.classList.add('download-error');
                  row.title = lastResult.error;
                  setTimeout(() => { row.classList.remove('download-error'); row.title = origTitle; }, 4000);
                }
              } catch (err) {
                setProgress(-1);
                row.classList.add('download-error');
                row.title = err.message;
                setTimeout(() => { row.classList.remove('download-error'); row.title = origTitle; }, 4000);
              } finally {
                row.classList.remove('downloading');
              }
            }

            await doDownload();
          });

          const sep = modelsFolder.endsWith('\\') || modelsFolder.endsWith('/') ? '' : '\\';
          const fullPath = `${modelsFolder}${sep}${displaySubfolder}\\${dl.filename}`;
          row.title = fullPath;
          const subfolderSpan = document.createElement('span');
          subfolderSpan.className = 'downloads-subfolder';
          subfolderSpan.textContent = `${displaySubfolder}\\`;
          const filenameSpan = document.createElement('span');
          filenameSpan.className = 'downloads-filename';
          filenameSpan.textContent = dl.filename;
          const existCheck = document.createElement('span');
          existCheck.className = 'downloads-exist-check';
          existCheck.style.display = 'none';
          existCheck.textContent = '\u2713';
          row.appendChild(subfolderSpan);
          row.appendChild(filenameSpan);
          row.appendChild(existCheck);
          row._existCheck = existCheck;
          row._dlKey = `${dl.subfolder}/${dl.filename}`;
        } else {
          // No folder set — open URL in new tab as before
          row.href = dl.url;
          row.target = '_blank';
          row.rel = 'noopener noreferrer';

          const subfolderSpan = document.createElement('span');
          subfolderSpan.className = 'downloads-subfolder';
          subfolderSpan.textContent = displaySubfolder;
          const sepSpan = document.createElement('span');
          sepSpan.className = 'downloads-sep';
          sepSpan.textContent = '\\';
          const filenameSpan = document.createElement('span');
          filenameSpan.className = 'downloads-filename';
          filenameSpan.textContent = dl.filename;
          row.appendChild(subfolderSpan);
          row.appendChild(sepSpan);
          row.appendChild(filenameSpan);
        }

        return row;
      }

      // Diffusion model + text encoder pairs (e.g. Flux Klein's 4B vs 9B
      // needing different-sized CLIPs) render grouped so it's clear both
      // files are needed together for that quantization level, instead of
      // looking like an arbitrary flat file list. A shared encoder (e.g.
      // 4B FP8 and 4B INT8 both using qwen_3_4b.safetensors) gets its own
      // row built fresh for each group it belongs to — see buildRow() above.
      const quantOptions = (analysis.quantization && Array.isArray(analysis.quantization.options))
        ? analysis.quantization.options
        : [];
      const basename = (p) => String(p || '').split(/[\\/]/).pop();
      const findDl = (filename) => downloads.find((d) => d.filename === filename);
      const referencedFilenames = new Set();

      quantOptions.forEach((opt) => {
        if (!opt.clip_name) return;
        const unetDl = findDl(basename(opt.unet_name));
        const clipDl = findDl(basename(opt.clip_name));
        if (!unetDl || !clipDl) return;
        referencedFilenames.add(unetDl.filename);
        referencedFilenames.add(clipDl.filename);

        const group = document.createElement('div');
        group.className = 'downloads-group';
        const groupLabel = document.createElement('p');
        groupLabel.className = 'downloads-group-label';
        groupLabel.textContent = opt.label;
        group.appendChild(groupLabel);
        group.appendChild(buildRow(unetDl));
        group.appendChild(buildRow(clipDl));
        dlPanel.appendChild(group);
      });

      // Anything not part of a pairing group (VAE, or a file some other
      // quantization level doesn't pair with a specific encoder) — plain,
      // ungrouped rows, same as before this feature existed.
      downloads.forEach((dl) => {
        if (referencedFilenames.has(dl.filename)) return;
        dlPanel.appendChild(buildRow(dl));
      });

      // Batch-check which files already exist on disk
      if (modelsFolder && downloads.length) {
        fetch('/api/models/imports/check-files', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: downloads.map(d => ({ subfolder: d.subfolder, filename: d.filename })) }),
        })
          .then(r => r.json())
          .then(result => {
            dlPanel.querySelectorAll('.downloads-row').forEach(r => {
              if (result.exists?.[r._dlKey]) {
                r._existCheck.style.display = 'inline';
                r.classList.add('download-done');
                // Already on disk — make the row genuinely inert, not just visually
                // marked. Relying only on the click-handler's classList check left a
                // window where a click could still slip through to the overwrite
                // confirm dialog.
                r.style.pointerEvents = 'none';
                r.tabIndex = -1;
                r.setAttribute('aria-disabled', 'true');
                r.title = `Already downloaded: ${r.title}`;
              }
            });
          })
          .catch(() => {});
      }

      dlCard.appendChild(dlPanel);
      analysisOutput.appendChild(dlCard);
    }

    // Optional parts — ComfyUI Subgraphs the analysis found and can safely
    // toggle on/off at generation time (see app/services/subgraph_toggles.py).
    // The API format never carries the subgraph's display name (that only
    // exists in the graph/UI format), so there's nothing to show except the
    // node id — the "contains" list of what's actually inside is what lets
    // the user figure out which one is which well enough to give it a real
    // name themselves.
    const optionalSubgraphs = (analysis.optionalSubgraphs || []).filter((sg) => sg.auto);
    const savedSubgraphAnnotations = (editingAnnotation && editingAnnotation.optionalSubgraphs) || [];
    editableOptionalSubgraphs = optionalSubgraphs.map((sg) => {
      const saved = savedSubgraphAnnotations.find((it) => it.id === sg.id);
      const contains = (sg.memberLabels || []).join(', ');
      return {
        id: sg.id,
        label: (saved && saved.label) || `Optional part ${sg.id}`,
        contains: (saved && saved.contains) || contains,
        defaultEnabled: saved ? !!saved.defaultEnabled : true,
      };
    });

    if (optionalSubgraphs.length > 0) {
      const sgCard = document.createElement('article');
      sgCard.className = 'analysis-card';
      sgCard.innerHTML = '<h3>Optional parts</h3><p class="muted-note">Detected ComfyUI Subgraphs that can be switched on/off in Create. Rename them so you remember what each one does.</p>';
      const sgList = document.createElement('div');
      sgList.className = 'stack';

      editableOptionalSubgraphs.forEach((item, index) => {
        const row = document.createElement('div');
        row.className = 'analysis-card downloads-row';
        row.style.flexDirection = 'column';
        row.style.alignItems = 'stretch';
        row.style.gap = '0.35rem';

        const labelInput = document.createElement('input');
        labelInput.type = 'text';
        labelInput.value = item.label;
        labelInput.placeholder = `Optional part ${item.id}`;
        labelInput.addEventListener('input', () => {
          editableOptionalSubgraphs[index].label = labelInput.value.trim() || `Optional part ${item.id}`;
        });

        const containsEl = document.createElement('p');
        containsEl.className = 'muted-note';
        containsEl.textContent = `Contains: ${item.contains || 'unknown nodes'}`;

        const enabledWrap = document.createElement('label');
        enabledWrap.style.display = 'flex';
        enabledWrap.style.alignItems = 'center';
        enabledWrap.style.gap = '0.4rem';
        const enabledCheck = document.createElement('input');
        enabledCheck.type = 'checkbox';
        enabledCheck.checked = item.defaultEnabled;
        enabledCheck.addEventListener('change', () => {
          editableOptionalSubgraphs[index].defaultEnabled = enabledCheck.checked;
        });
        const enabledText = document.createElement('span');
        enabledText.className = 'muted-note';
        enabledText.textContent = 'On by default';
        enabledWrap.appendChild(enabledCheck);
        enabledWrap.appendChild(enabledText);

        row.appendChild(labelInput);
        row.appendChild(containsEl);
        row.appendChild(enabledWrap);
        sgList.appendChild(row);
      });

      sgCard.appendChild(sgList);
      analysisOutput.appendChild(sgCard);
    }
  }

  function renderActiveQueue(data) {
    if (!activeImportsQueueEl) return;
    activeImportsQueueEl.innerHTML = '';
    const activeIds = data.activeImportIds || [];
    const imports = data.imports || [];

    // Update the header badge
    const queueTitleEl = document.querySelector('.import-subtitle-row .page-title');
    if (queueTitleEl) {
      const anyHasImage = activeIds.some((id) => {
        const item = imports.find((imp) => imp.id === id);
        return !!(item?.analysis?.detected?.hasImageInput);
      });
      const existingBadge = queueTitleEl.querySelector('.active-queue-image-badge');
      if (anyHasImage && !existingBadge) {
        const badge = document.createElement('span');
        badge.className = 'active-queue-image-badge';
        badge.title = 'Queue contains a model with image input';
        badge.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-left:6px;opacity:0.75;"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`;
        queueTitleEl.appendChild(badge);
      } else if (!anyHasImage && existingBadge) {
        existingBadge.remove();
      }
    }

    if (!activeIds.length) {
      activeImportsQueueEl.innerHTML = '<p class="muted-note">No active models. Add one from Saved Imports below.</p>';
      return;
    }

    activeIds.forEach((id, index) => {
      const item = imports.find((imp) => imp.id === id);
      if (!item) return;
      const hasImageInput = !!(item.analysis?.detected?.hasImageInput);
      const imageIconHtml = hasImageInput
        ? `<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" title="Accepts image input" style="vertical-align:middle;opacity:0.7;"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`
        : '';
      const row = document.createElement('div');
      row.className = 'active-queue-item';
      row.innerHTML = `
        <span class="active-queue-order">${index + 1}</span>
        <span class="active-queue-name">${escapeAttr(item.name)} ${imageIconHtml}</span>
        <span class="active-queue-url muted-note">${escapeAttr(item.comfyApiUrl || '')}</span>
        <button type="button" class="btn active-queue-remove-btn" data-deactivate-id="${escapeAttr(id)}" title="Remove from queue">Remove</button>
      `;
      activeImportsQueueEl.appendChild(row);
    });

    activeImportsQueueEl.querySelectorAll('[data-deactivate-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-deactivate-id');
        try {
          await window.openJourneyApi.deactivateImport(id);
          await refreshImports();
          setStatus('Removed from active queue.');
        } catch (err) {
          setStatus(err.message || 'Failed to remove from queue.', true);
        }
      });
    });
  }

  async function refreshImports() {
    const data = await window.openJourneyApi.listImports();
    // Sync store
    if (window.openJourneyStore) {
      window.openJourneyStore.activeImportIds = data.activeImportIds || [];
      window.openJourneyStore.queueFreeMemoryBetweenModels = !!data.queueFreeMemoryBetweenModels;
      // Keep activeImport = first in the active list for backward compat
      const firstId = (data.activeImportIds || [])[0];
      const firstRecord = firstId ? (data.imports || []).find((i) => i.id === firstId) : null;
      if (firstRecord) {
        window.openJourneyStore.activeImport = firstRecord;
      }
    }
    if (queueFreeMemoryToggle) {
      queueFreeMemoryToggle.checked = !!data.queueFreeMemoryBetweenModels;
    }
    renderActiveQueue(data);
    renderSavedImports(data);
  }

  async function loadSettings() {
    if (!comfyUriEl) return;
    try {
      const response = await window.openJourneyApi.getModelsSettings();
      comfyUriEl.value = response.settings?.comfyApiUrl || '';
      cachedModelsFolder = response.settings?.comfyModelsFolder || '';
      // Do not block page hydration on availability checks.
      probeComfyAvailability(comfyUriEl.value); 
    } catch {
      setComfyAvailability(false);
    }
  }

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      rawWorkflow = null;
      analyzeBtn.disabled = true;
      saveBtn.disabled = true;
      setStatus('No file loaded.');
      return;
    }

    const text = await file.text();
    try {
      rawWorkflow = JSON.parse(text);
      analyzeBtn.disabled = false;
      saveBtn.disabled = true;
      lastAnalysis = null;
      analysisOutput.innerHTML = '';
      if (!nameInput.value.trim()) {
        nameInput.value = file.name.replace(/\.json$/i, '');
      }
      // Auto-analyze on load
      try {
        setStatus(`Analyzing ${file.name}…`);
        const response = await window.openJourneyApi.analyzeWorkflow(rawWorkflow);
        lastAnalysis = response.analysis;
        // Auto-fill name from config node (preferred over filename)
        const configName = String((lastAnalysis.configNode || {}).name || '').trim();
        if (configName) nameInput.value = configName;
        renderAnalysis(lastAnalysis);
        saveBtn.disabled = false;
        setStatus('Analysis completed.');
      } catch {
        setStatus('Analysis failed.', true);
      }
    } catch {
      rawWorkflow = null;
      analyzeBtn.disabled = true;
      saveBtn.disabled = true;
      setStatus('Invalid JSON file.', true);
    }
  });

  analyzeBtn.addEventListener('click', async () => {
    if (!rawWorkflow) {
      setStatus('Load a valid workflow JSON first.', true);
      return;
    }

    try {
      const response = await window.openJourneyApi.analyzeWorkflow(rawWorkflow);
      lastAnalysis = response.analysis;
      const configName = String((lastAnalysis.configNode || {}).name || '').trim();
      if (configName) nameInput.value = configName;
      renderAnalysis(lastAnalysis);
      saveBtn.disabled = false;
      setStatus('Analysis completed.');
    } catch {
      setStatus('Analysis failed.', true);
    }
  });

  saveBtn.addEventListener('click', async () => {
    if (!rawWorkflow || !lastAnalysis) {
      setStatus('Analyze workflow before saving.', true);
      return;
    }

    try {
      const liveComfyUri = comfyUriEl.value.trim();
      if (!liveComfyUri) {
        setStatus('ComfyUI URI is required.', true);
        return;
      }
      const slugError = slugProblem();
      if (slugError) {
        refreshSlugHint();
        setStatus(slugError, true);
        if (slugInput) slugInput.focus();
        return;
      }
      if (editingImportId) {
        const targetImportId = editingImportId;
        await window.openJourneyApi.updateImport(editingImportId, {
          name: nameInput.value.trim() || 'Imported Workflow',
          slug: slugInput ? slugInput.value.trim() : undefined,
          workflow: rawWorkflow,
          comfyApiUrl: liveComfyUri,
        });
        await window.openJourneyApi.updateImportAnnotations(editingImportId, {
          optionalSubgraphs: editableOptionalSubgraphs,
          loras: editableLoras,
        });

        // Reimport/update should reflect the new workflow defaults in Studio.
        // Clear per-import cached advanced overrides so stale local values do not win.
        try {
          const cacheKey = 'openjourney_model_advanced_cache_v1';
          const rawCache = localStorage.getItem(cacheKey);
          if (rawCache) {
            const parsedCache = JSON.parse(rawCache);
            if (parsedCache && typeof parsedCache === 'object' && parsedCache[targetImportId]) {
              delete parsedCache[targetImportId];
              localStorage.setItem(cacheKey, JSON.stringify(parsedCache));
            }
          }
        } catch (_) {}

        setStatus('Import updated.');
      } else {
        const created = await window.openJourneyApi.createImport({
          name: nameInput.value.trim() || 'Imported Workflow',
          slug: slugInput ? slugInput.value.trim() : '',
          category: 'image',
          workflow: rawWorkflow,
          comfyApiUrl: liveComfyUri,
        });
        const newImportId = created && created.import && created.import.id;
        if (newImportId && (editableOptionalSubgraphs.length || editableLoras.length)) {
          await window.openJourneyApi.updateImportAnnotations(newImportId, {
            optionalSubgraphs: editableOptionalSubgraphs,
            loras: editableLoras,
          });
        }
        setStatus('Import saved and activated.');
      }
      editingImportId = null;
      await refreshImports();
      closeImportModal();
    } catch (err) {
      setStatus((err && err.message) || 'Failed to save import.', true);
    }
  });

  if (testComfyConnectionBtn && comfyUriEl) {
    testComfyConnectionBtn.addEventListener('click', async () => {
      const comfyUri = comfyUriEl.value.trim();
      if (!comfyUri) {
        setComfyAvailability(false);
        return;
      }

      setComfyAvailability(null, 'Checking ComfyUI...');
      try {
        // Cache the URI on every test so users do not need to retype it.
        const saved = await window.openJourneyApi.updateModelsSettings({ comfyApiUrl: comfyUri });
        comfyUriEl.value = saved.settings?.comfyApiUrl || comfyUri;

        // Keep the active workflow import aligned with the currently tested URI.
        let syncedActiveImport = false;
        try {
          const activeResponse = await window.openJourneyApi.getActiveImport();
          const activeImport = activeResponse && activeResponse.active ? activeResponse.active : null;
          if (activeImport && activeImport.id) {
            await window.openJourneyApi.updateImportValues(activeImport.id, { comfyApiUrl: comfyUriEl.value.trim() });
            syncedActiveImport = true;
            await refreshImports();
          }
        } catch {
          // Non-fatal: settings URI is already cached even if active import sync fails.
        }

        if (typeof window.refreshNavImagesLed === 'function') {
          window.refreshNavImagesLed();
        }

        await window.openJourneyApi.testModelsConnection({ comfyApiUrl: comfyUriEl.value.trim() });
        if (syncedActiveImport) {
          setStatus('Active import URI updated.');
        }
        setComfyAvailability(true);
      } catch (error) {
        setComfyAvailability(false);
        setStatus(error.message || 'ComfyUI connection failed.', true);
      }
    });
  }

  if (queueFreeMemoryToggle) {
    queueFreeMemoryToggle.addEventListener('change', async () => {
      const freeMem = queueFreeMemoryToggle.checked;
      try {
        await window.openJourneyApi.setQueueFreeMemory({ freeMem });
      } catch (_) {}
    });
  }

  // Initial page load
  await loadSettings();
  await refreshImports();
})();
