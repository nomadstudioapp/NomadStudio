(async function modelsUpscaleImportPage() {
  const importNameEl = document.getElementById('upscale-import-name');
  const importFileEl = document.getElementById('upscale-workflow-file');
  const importFileTriggerEl = document.getElementById('upscale-workflow-file-trigger');
  const importAnalyzeBtn = document.getElementById('upscale-analyze-workflow-btn');
  const importSaveBtn = document.getElementById('upscale-save-workflow-btn');
  const importStatusEl = document.getElementById('upscale-import-status');
  const importAnalysisEl = document.getElementById('upscale-analysis-output');
  const savedImportsEl = document.getElementById('upscale-saved-imports');

  const comfyUriEl = document.getElementById('upscale-import-comfy-uri');
  const testConnectionBtn = document.getElementById('upscale-import-test-connection');
  const comfyStatusEl = document.getElementById('upscale-import-comfy-status');
  const availabilityChipEl = document.getElementById('upscale-import-availability-chip');
  const availabilityTextEl = document.getElementById('upscale-import-availability-text');

  if (!importFileEl || !importAnalyzeBtn || !importSaveBtn || !importStatusEl || !comfyUriEl) {
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
    const summary = document.createElement('article');
    summary.className = 'analysis-card';
    summary.innerHTML = `
      <h3>Detected</h3>
      <p class="muted-note">Sampler: ${detect.samplerNodeId || 'not found'}</p>
      <p class="muted-note">SaveImage nodes: ${detect.saveImageCount || 0}</p>
      <p class="muted-note">Scale node: ${detect.scaleNodeId || 'not found'}</p>
      <p class="muted-note">Scale input: ${detect.scaleInputKey || 'not found'}</p>
      <p class="muted-note">Prompt node: ${detect.positiveNodeId || 'not found'}</p>
    `;
    importAnalysisEl.appendChild(summary);

    const promptCard = document.createElement('article');
    promptCard.className = 'analysis-card';
    const positivePrompt = String(basicValues.positive || '').trim();
    promptCard.innerHTML = `
      <h3>Detected Prompt</h3>
      <p class="muted-note">${positivePrompt || 'No positive prompt detected.'}</p>
    `;
    importAnalysisEl.appendChild(promptCard);

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
    const advancedParams = analysis?.advancedParameters || [];
    if (!advancedParams.length) {
      advancedList.innerHTML = '<p class="muted-note">No advanced parameters detected.</p>';
    } else {
      advancedParams.forEach((item) => {
        const row = document.createElement('p');
        row.className = 'muted-note';
        row.textContent = `${item.label} (${item.nodeClass}:${item.nodeId}) = ${item.value}`;
        advancedList.appendChild(row);
      });
    }
    advancedCard.appendChild(advancedList);
    importAnalysisEl.appendChild(advancedCard);
  }

  function renderSavedUpscaleImports(models, selectedModelId) {
    if (!savedImportsEl) return;
    savedImportsEl.innerHTML = '';

    const catalog = Array.isArray(models) ? models : [];
    if (!catalog.length) {
      savedImportsEl.innerHTML = '<p class="muted-note">No saved upscale imports yet.</p>';
      return;
    }

    catalog.forEach((model) => {
      const row = document.createElement('article');
      row.className = 'import-item import-item-stacked';

      const modelId = String(model.id || '');
      const safeUri = escapeAttr(model.comfyApiUrl || '');
      const isActive = modelId && modelId === String(selectedModelId || '');
      const mode = String(model.scaleMode || 'fixed');
      let modeText = 'Fixed scale';
      if (mode === 'selectable') {
        modeText = `Selectable ${model.minScale || 0.25}x-${model.maxScale || 8}x`;
      } else {
        modeText = `Fixed x${model.fixedScale || 2}`;
      }

      row.innerHTML = `
        <div>
          <strong>${model.name || 'Upscale Workflow'}</strong>
          <p class="muted-note">${modeText}</p>
          <label>
            <span class="muted-note">ComfyUI URI</span>
            <input type="text" value="${safeUri}" data-upscale-import-uri-id="${modelId}" />
          </label>
          <div class="btn-row" style="margin-top:8px;">
            <button type="button" class="btn ${isActive ? 'primary' : ''}" data-upscale-activate="${modelId}">${isActive ? 'Active' : 'Activate'}</button>
            <button type="button" class="btn" data-upscale-save-uri="${modelId}">Save URI</button>
            <button type="button" class="btn" data-upscale-delete="${modelId}">Delete</button>
          </div>
        </div>
      `;
      savedImportsEl.appendChild(row);
    });

    savedImportsEl.querySelectorAll('[data-upscale-activate]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const modelId = btn.getAttribute('data-upscale-activate');
        if (!modelId) return;
        try {
          await window.openJourneyApi.updateUpscaleSettings({
            modelId,
            comfyApiUrl: String(comfyUriEl.value || '').trim(),
          });
          setImportStatus('Upscale import activated.');
          await loadUpscaleSettings();
        } catch (error) {
          setImportStatus(error.message || 'Failed to activate upscale import.', true);
        }
      });
    });

    savedImportsEl.querySelectorAll('[data-upscale-save-uri]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const modelId = btn.getAttribute('data-upscale-save-uri');
        if (!modelId) return;

        const input = savedImportsEl.querySelector(`[data-upscale-import-uri-id="${modelId}"]`);
        const comfyApiUrl = input ? String(input.value || '').trim() : '';
        if (!comfyApiUrl) {
          setImportStatus('ComfyUI URI is required.', true);
          return;
        }

        try {
          await window.openJourneyApi.updateImportValues(modelId, { comfyApiUrl });
          const activeModelId = String(selectedModelId || '').trim();
          if (activeModelId && activeModelId === modelId) {
            await window.openJourneyApi.updateUpscaleSettings({
              modelId,
              comfyApiUrl,
            });
            comfyUriEl.value = comfyApiUrl;
          }
          setComfyStatus('Checking saved URI...');
          await probeComfyAvailability(comfyApiUrl);
          setComfyStatus('Saved URI checked.');
          setImportStatus('Upscale import URI updated.');
          await loadUpscaleSettings();
        } catch (error) {
          setImportStatus(error.message || 'Failed to update import URI.', true);
        }
      });
    });

    savedImportsEl.querySelectorAll('[data-upscale-delete]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const modelId = btn.getAttribute('data-upscale-delete');
        if (!modelId) return;

        const ok = window.confirm('Delete this import? This cannot be undone.');
        if (!ok) return;

        try {
          await window.openJourneyApi.deleteImport(modelId);

          // Clean up per-model advanced cache (CFG/Steps) for the deleted import
          try {
            const cacheKey = 'openjourney_model_advanced_cache_v1';
            const raw = localStorage.getItem(cacheKey);
            if (raw) {
              const cache = JSON.parse(raw);
              if (cache && typeof cache === 'object' && cache[modelId]) {
                delete cache[modelId];
                localStorage.setItem(cacheKey, JSON.stringify(cache));
              }
            }
          } catch (_) {}

          setImportStatus('Upscale import deleted.');
          await loadUpscaleSettings();
          if (typeof window.refreshNavUpscaleLed === 'function') {
            window.refreshNavUpscaleLed();
          }
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

  async function loadUpscaleSettings() {
    try {
      const response = await window.openJourneyApi.getUpscaleSettings();
      const settings = response.settings || {};
      const models = response.models || [];
      comfyUriEl.value = String(settings.comfyApiUrl || '');
      renderSavedUpscaleImports(models, settings.modelId);
      setComfyStatus('Settings loaded.');
      // Render saved imports immediately; availability checks can complete asynchronously.
      probeComfyAvailability(comfyUriEl.value);
      return response;
    } catch {
      setComfyStatus('Failed to load settings.', true);
      setComfyAvailability(false, 'ComfyUI unavailable');
      renderSavedUpscaleImports([], '');
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
      importAnalyzeBtn.disabled = true;
      importSaveBtn.disabled = true;
      if (importAnalysisEl) importAnalysisEl.innerHTML = '';
      setImportStatus('No file loaded.');
      return;
    }

    const text = await file.text();
    try {
      rawWorkflow = JSON.parse(text);
      lastAnalysis = null;
      importAnalyzeBtn.disabled = false;
      importSaveBtn.disabled = true;
      if (importAnalysisEl) importAnalysisEl.innerHTML = '';
      if (importNameEl && !String(importNameEl.value || '').trim()) {
        importNameEl.value = file.name.replace(/\.json$/i, '');
      }
      setImportStatus(`Loaded ${file.name}`);
    } catch {
      rawWorkflow = null;
      lastAnalysis = null;
      importAnalyzeBtn.disabled = true;
      importSaveBtn.disabled = true;
      if (importAnalysisEl) importAnalysisEl.innerHTML = '';
      setImportStatus('Invalid JSON file.', true);
    }
  });

  importAnalyzeBtn.addEventListener('click', async () => {
    if (!rawWorkflow) {
      setImportStatus('Load a valid workflow JSON first.', true);
      return;
    }

    try {
      const response = await window.openJourneyApi.analyzeWorkflow(rawWorkflow);
      lastAnalysis = response.analysis || null;
      renderImportAnalysis(lastAnalysis);
      importSaveBtn.disabled = !lastAnalysis;
      setImportStatus('Analysis completed.');
    } catch (error) {
      setImportStatus(error.message || 'Analysis failed.', true);
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
        name: (importNameEl && String(importNameEl.value || '').trim()) || 'Imported Upscale Workflow',
        category: 'upscale',
        workflow: rawWorkflow,
        comfyApiUrl,
      });

      const importId = String(created?.import?.id || '').trim();
      if (importId) {
        await window.openJourneyApi.updateUpscaleSettings({
          comfyApiUrl,
          modelId: importId,
        });
      }

      setImportStatus('Upscale import saved. Open Upscale page under Create to run it.');
      if (typeof window.refreshNavUpscaleLed === 'function') {
        window.refreshNavUpscaleLed();
      }
      await loadUpscaleSettings();
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

  await loadUpscaleSettings();
})();
