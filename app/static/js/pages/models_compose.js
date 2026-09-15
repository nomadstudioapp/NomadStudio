(async function modelsComposeImportPage() {
  const importNameEl = document.getElementById('compose-import-name');
  const importFileEl = document.getElementById('compose-workflow-file');
  const importFileTriggerEl = document.getElementById('compose-workflow-file-trigger');
  const importSaveBtn = document.getElementById('compose-save-workflow-btn');
  const importStatusEl = document.getElementById('compose-import-status');
  const importAnalysisEl = document.getElementById('compose-analysis-output');
  const savedImportsEl = document.getElementById('compose-saved-imports');

  const comfyUriEl = document.getElementById('compose-import-comfy-uri');
  const testConnectionBtn = document.getElementById('compose-import-test-connection');
  const comfyStatusEl = document.getElementById('compose-import-comfy-status');
  const availabilityChipEl = document.getElementById('compose-import-availability-chip');
  const availabilityTextEl = document.getElementById('compose-import-availability-text');

  if (!importFileEl || !importSaveBtn || !importStatusEl || !comfyUriEl) {
    return;
  }

  let rawWorkflow = null;
  let lastAnalysis = null;

  function escapeAttr(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function setComfyStatus(message, isError = false) {
    if (!comfyStatusEl) return;
    comfyStatusEl.textContent = message;
    comfyStatusEl.classList.toggle('status-error', isError);
  }

  function setImportStatus(message, isError = false) {
    importStatusEl.textContent = message;
    importStatusEl.classList.toggle('status-error', isError);
  }

  function setComfyAvailability(available, message) {
    if (!availabilityChipEl || !availabilityTextEl) return;
    availabilityChipEl.classList.toggle('available', !!available);
    availabilityChipEl.classList.toggle('unavailable', available === false);
    availabilityTextEl.textContent = String(message || 'Checking ComfyUI...');
  }

  function renderImportAnalysis(analysis) {
    if (!importAnalysisEl) return;
    importAnalysisEl.innerHTML = '';

    const detect = analysis?.detected || {};
    const basicValues = analysis?.basicValues || {};
    const advancedParams = analysis?.advancedParameters || [];

    // Detect LoRA presence from advanced params
    const loraParams = advancedParams.filter(
      (p) => p.optionsSource === 'lora' || String(p.key || '').endsWith('.lora_name'),
    );
    const hasLora = loraParams.length > 0;

    const summary = document.createElement('article');
    summary.className = 'analysis-card';
    summary.innerHTML = `
      <h3>Detected</h3>
      <p class="muted-note">Sampler: ${detect.samplerNodeId || 'not found'}</p>
      <p class="muted-note">SaveImage nodes: ${detect.saveImageCount || 0}</p>
      <p class="muted-note">Input image: ${detect.hasImageInput ? 'yes' : 'no'}</p>
      <p class="muted-note">Negative prompt: ${detect.hasNegativePrompt ? 'yes' : 'no'}</p>
      <p class="muted-note">LoRA: ${hasLora ? `yes (${loraParams.length} node${loraParams.length > 1 ? 's' : ''})` : 'no'}</p>
      <p class="muted-note">Latent size: ${detect.latentNodeId ? 'yes' : 'no'}</p>
      <p class="muted-note">Prompt node: ${detect.positiveNodeId || 'not found'}</p>
    `;
    importAnalysisEl.appendChild(summary);

    const basicCard = document.createElement('article');
    basicCard.className = 'analysis-card';
    basicCard.innerHTML = '<h3>Basic Parameters</h3>';
    const basicGrid = document.createElement('div');
    basicGrid.className = 'param-grid';
    (analysis?.basicParameters || []).forEach((item) => {
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
    basicCard.appendChild(basicGrid);
    importAnalysisEl.appendChild(basicCard);

    const advancedCard = document.createElement('details');
    advancedCard.className = 'analysis-card';
    advancedCard.innerHTML = '<summary>Advanced Parameters</summary>';
    const advancedList = document.createElement('div');
    advancedList.className = 'stack';
    if (!advancedParams.length) {
      advancedList.innerHTML = '<p class="muted-note">No advanced parameters detected.</p>';
    } else {
      advancedParams.forEach((item) => {
        const row = document.createElement('p');
        row.className = 'muted-note';
        const source = item.optionsSource ? ` [${item.optionsSource}]` : '';
        row.textContent = `${item.label} (${item.nodeClass}:${item.nodeId})${source} = ${item.value}`;
        advancedList.appendChild(row);
      });
    }
    advancedCard.appendChild(advancedList);
    importAnalysisEl.appendChild(advancedCard);
  }

  function renderSavedComposeImports(models, selectedModelId) {
    if (!savedImportsEl) return;
    savedImportsEl.innerHTML = '';

    const catalog = Array.isArray(models) ? models : [];
    if (!catalog.length) {
      savedImportsEl.innerHTML = '<p class="muted-note">No saved compose imports yet.</p>';
      return;
    }

    catalog.forEach((model) => {
      const row = document.createElement('article');
      row.className = 'import-item import-item-stacked';

      const modelId = String(model.id || '');
      const safeUri = escapeAttr(model.comfyApiUrl || '');
      const isActive = modelId && modelId === String(selectedModelId || '');

      const features = [];
      if (model.hasImageInput) features.push('input image');
      if (model.hasNegativePrompt) features.push('negative prompt');
      if (model.hasLora) features.push('LoRA');
      if (model.hasLatent) features.push('latent size');
      const featuresText = features.length ? features.join(', ') : 'basic workflow';

      row.innerHTML = `
        <div>
          <strong>${model.name || 'Compose Workflow'}</strong>
          <p class="muted-note">${featuresText}</p>
          <label>
            <span class="muted-note">ComfyUI URI</span>
            <input type="text" value="${safeUri}" data-compose-import-uri-id="${modelId}" />
          </label>
          <div class="btn-row" style="margin-top:8px;">
            <button type="button" class="btn ${isActive ? 'primary' : ''}" data-compose-activate="${modelId}">${isActive ? 'Active' : 'Activate'}</button>
            <button type="button" class="btn" data-compose-save-uri="${modelId}">Save URI</button>
            <button type="button" class="btn" data-compose-delete="${modelId}">Delete</button>
          </div>
        </div>
      `;
      savedImportsEl.appendChild(row);
    });

    savedImportsEl.querySelectorAll('[data-compose-activate]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const modelId = btn.getAttribute('data-compose-activate');
        if (!modelId) return;
        try {
          await window.openJourneyApi.updateComposeSettings({
            modelId,
            comfyApiUrl: String(comfyUriEl.value || '').trim(),
          });
          setImportStatus('Compose import activated.');
          await loadComposeSettings();
        } catch (error) {
          setImportStatus(error.message || 'Failed to activate compose import.', true);
        }
      });
    });

    savedImportsEl.querySelectorAll('[data-compose-save-uri]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const modelId = btn.getAttribute('data-compose-save-uri');
        if (!modelId) return;

        const input = savedImportsEl.querySelector(`[data-compose-import-uri-id="${modelId}"]`);
        const comfyApiUrl = input ? String(input.value || '').trim() : '';
        if (!comfyApiUrl) {
          setImportStatus('ComfyUI URI is required.', true);
          return;
        }

        try {
          await window.openJourneyApi.updateImportValues(modelId, { comfyApiUrl });
          const activeModelId = String(selectedModelId || '').trim();
          if (activeModelId && activeModelId === modelId) {
            await window.openJourneyApi.updateComposeSettings({ modelId, comfyApiUrl });
            comfyUriEl.value = comfyApiUrl;
          }
          setComfyStatus('Checking saved URI...');
          await probeComfyAvailability(comfyApiUrl);
          setComfyStatus('Saved URI checked.');
          setImportStatus('Compose import URI updated.');
          await loadComposeSettings();
        } catch (error) {
          setImportStatus(error.message || 'Failed to update import URI.', true);
        }
      });
    });

    savedImportsEl.querySelectorAll('[data-compose-delete]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const modelId = btn.getAttribute('data-compose-delete');
        if (!modelId) return;

        const ok = window.confirm('Delete this import? This cannot be undone.');
        if (!ok) return;

        try {
          await window.openJourneyApi.deleteImport(modelId);
          setImportStatus('Compose import deleted.');
          await loadComposeSettings();
        } catch (error) {
          setImportStatus(error.message || 'Failed to delete import.', true);
        }
      });
    });
  }

  async function probeComfyAvailability(uri) {
    const comfyApiUrl = String(uri || '').trim();
    if (!comfyApiUrl) {
      setComfyAvailability(false, 'ComfyUI unavailable');
      return;
    }

    setComfyAvailability(null, 'Checking ComfyUI...');
    try {
      const result = await window.openJourneyApi.testModelsConnection({ comfyApiUrl });
      setComfyAvailability(true, `ComfyUI available (${result.endpoint || 'system_stats'})`);
    } catch {
      setComfyAvailability(false, 'ComfyUI unavailable');
    }
  }

  async function loadComposeSettings() {
    try {
      const response = await window.openJourneyApi.getComposeSettings();
      const settings = response.settings || {};
      const models = response.models || [];
      comfyUriEl.value = String(settings.comfyApiUrl || '');
      renderSavedComposeImports(models, settings.modelId);
      setComfyStatus('Settings loaded.');
      probeComfyAvailability(comfyUriEl.value);
      return response;
    } catch {
      setComfyStatus('Failed to load settings.', true);
      setComfyAvailability(false, 'ComfyUI unavailable');
      renderSavedComposeImports([], '');
      return null;
    }
  }

  if (importFileTriggerEl) {
    importFileTriggerEl.addEventListener('click', () => {
      importFileEl.click();
    });
  }

  importFileEl.addEventListener('change', async () => {
    const file = importFileEl.files && importFileEl.files[0];
    if (!file) {
      rawWorkflow = null;
      lastAnalysis = null;
      importSaveBtn.disabled = true;
      if (importAnalysisEl) importAnalysisEl.innerHTML = '';
      setImportStatus('No file loaded.');
      return;
    }

    const text = await file.text();
    try {
      rawWorkflow = JSON.parse(text);
      lastAnalysis = null;
      importSaveBtn.disabled = true;
      if (importAnalysisEl) importAnalysisEl.innerHTML = '';
      if (importNameEl && !String(importNameEl.value || '').trim()) {
        importNameEl.value = file.name.replace(/\.json$/i, '');
      }
      setImportStatus(`Analyzing ${file.name}...`);
      try {
        const response = await window.openJourneyApi.analyzeWorkflow(rawWorkflow);
        lastAnalysis = response.analysis || null;
        renderImportAnalysis(lastAnalysis);
        importSaveBtn.disabled = !lastAnalysis;
        setImportStatus(`Loaded ${file.name}`);
      } catch (error) {
        setImportStatus(error.message || 'Analysis failed.', true);
      }
    } catch {
      rawWorkflow = null;
      lastAnalysis = null;
      importSaveBtn.disabled = true;
      if (importAnalysisEl) importAnalysisEl.innerHTML = '';
      setImportStatus('Invalid JSON file.', true);
    }
  });

  importSaveBtn.addEventListener('click', async () => {
    if (!rawWorkflow || !lastAnalysis) {
      setImportStatus('Analyze workflow before saving.', true);
      return;
    }

    const comfyApiUrl = String(comfyUriEl.value || '').trim();
    if (!comfyApiUrl) {
      setImportStatus('ComfyUI URI is required.', true);
      return;
    }

    try {
      const created = await window.openJourneyApi.createImport({
        name: (importNameEl && String(importNameEl.value || '').trim()) || 'Imported Compose Workflow',
        category: 'compose',
        workflow: rawWorkflow,
        comfyApiUrl,
      });

      const importId = String(created?.import?.id || '').trim();
      if (importId) {
        await window.openJourneyApi.updateComposeSettings({ comfyApiUrl, modelId: importId });
      }

      setImportStatus('Compose import saved.');
      await loadComposeSettings();
    } catch (error) {
      setImportStatus(error.message || 'Failed to save import.', true);
    }
  });

  if (testConnectionBtn) {
    testConnectionBtn.addEventListener('click', async () => {
      const comfyApiUrl = String(comfyUriEl.value || '').trim();
      if (!comfyApiUrl) {
        setComfyStatus('ComfyUI URI is required.', true);
        setComfyAvailability(false, 'ComfyUI unavailable');
        return;
      }

      setComfyStatus('Testing connection...');
      await probeComfyAvailability(comfyApiUrl);
      setComfyStatus('Connection test finished.');
    });
  }

  await loadComposeSettings();
})();
