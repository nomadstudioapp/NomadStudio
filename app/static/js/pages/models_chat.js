(async function modelsChatPage() {
  const rootEl = document.getElementById('models-chat-root');
  const pageRole = String(rootEl?.dataset?.modelRole || 'prompts').toLowerCase() === 'vision' ? 'vision' : 'prompts';
  const roleLabel = pageRole === 'vision' ? 'vision' : 'prompt';
  const uriEl = document.getElementById('lmstudio-uri');
  const promptModelSelectEl = document.getElementById('lmstudio-prompt-model-select');
  const visionModelSelectEl = document.getElementById('lmstudio-vision-model-select');
  const visionFilterNoteEl = document.getElementById('lmstudio-vision-filter-note');
  const loadModelsBtn = document.getElementById('load-lmstudio-models');
  const saveSettingsBtn = document.getElementById('save-lmstudio-settings');
  const autoDisconnectEl = document.getElementById('lmstudio-auto-disconnect');
  const temperatureEl = document.getElementById('lmstudio-temperature');
  const outputLogEl = document.getElementById('lmstudio-output-log');
  const clearLogBtn = document.getElementById('clear-lmstudio-log');
  const statusEl = document.getElementById('lmstudio-chat-status');
  const availabilityChipEl = document.getElementById('lmstudio-availability-chip');
  const availabilityTextEl = document.getElementById('lmstudio-availability-text');
  const promptFavoriteToggleBtn = document.getElementById('lmstudio-prompt-favorite-toggle');
  const promptFavoritesOnlyEl = document.getElementById('lmstudio-prompt-favorites-only');
  const promptFavoritesQuickEl = document.getElementById('lmstudio-prompt-favorites-quick');
  const visionFavoriteToggleBtn = document.getElementById('lmstudio-vision-favorite-toggle');
  const visionFavoritesOnlyEl = document.getElementById('lmstudio-vision-favorites-only');
  const visionFavoritesQuickEl = document.getElementById('lmstudio-vision-favorites-quick');
  const checkThinkCompatBtn = document.getElementById('lmstudio-check-think-compat');
  const thinkCompatStatusEl = document.getElementById('lmstudio-think-compat-status');
  const browseModelsBtn = document.getElementById('lmstudio-browse-models');
  const checkAllPendingBtn = document.getElementById('lmstudio-check-all-pending');
  const benchmarkNewModelsBtn = document.getElementById('lmstudio-benchmark-new-models');
  const benchmarkStatusEl = document.getElementById('lmstudio-benchmark-status');

  if (!uriEl || !promptModelSelectEl || !visionModelSelectEl || !loadModelsBtn || !autoDisconnectEl || !temperatureEl || !outputLogEl || !clearLogBtn || !statusEl) {
    return;
  }

  let loadedModels = [];
  let detectedVisionModels = [];
  let promptFavoriteModels = [];
  let visionFavoriteModels = [];
  let showPromptFavoritesOnly = false;
  let showVisionFavoritesOnly = false;
  let thinkCompat = {};

  // Reflects the persisted Think Compatibility verdict (see issue #1/#76) for
  // whichever model is currently selected in Prompt LLM — never re-runs the
  // check itself, just reads what's already in settings.lmStudioThinkCompat.
  function renderThinkCompatStatus() {
    if (!thinkCompatStatusEl) return;
    const model = String(promptModelSelectEl.value || '').trim();
    const state = window.openJourneyApi.thinkCompatState({ lmStudioThinkCompat: thinkCompat }, model);
    thinkCompatStatusEl.classList.remove(
      'models-chat-think-compat-status--supported',
      'models-chat-think-compat-status--unsupported',
      'models-chat-think-compat-status--no_thinking'
    );
    if (!model) {
      thinkCompatStatusEl.textContent = '';
    } else if (state === 'supported') {
      thinkCompatStatusEl.textContent = '✓ Respects "don\'t think" requests.';
      thinkCompatStatusEl.classList.add('models-chat-think-compat-status--supported');
    } else if (state === 'unsupported') {
      thinkCompatStatusEl.textContent = '⚠ Ignores "don\'t think" — can exhaust its token budget reasoning.';
      thinkCompatStatusEl.classList.add('models-chat-think-compat-status--unsupported');
    } else if (state === 'no_thinking') {
      thinkCompatStatusEl.textContent = '◐ No thinking/reasoning capability — nothing to toggle.';
      thinkCompatStatusEl.classList.add('models-chat-think-compat-status--no_thinking');
    } else {
      thinkCompatStatusEl.textContent = 'Not checked yet.';
    }
  }

  // ── Model browser panel ─────────────────────────────────────────────────
  // A third fixed-position flyout (see .cs-prompt-model-browser, nomad_studio.css)
  // listing every loaded model with the same score/speed/think badges as the
  // flow engine's own "Model" picker (flow-model-picker.js) — that picker
  // isn't available here (only loaded on the flow pages themselves), so this
  // is a small standalone equivalent scoped to this page. Clicking a model
  // selects it as Prompt LLM, same as picking it from the <select>.
  let modelScoresCache = null;
  function loadModelScores() {
    if (modelScoresCache) return Promise.resolve(modelScoresCache);
    return fetch('/static/data/model_scores.json')
      .then((r) => r.json())
      .then((data) => { modelScoresCache = data; return data; })
      .catch(() => null);
  }
  function scoreTierClass(avg) {
    if (avg >= 8) return 'nse-model-score--high';
    if (avg >= 5) return 'nse-model-score--mid';
    return 'nse-model-score--low';
  }
  let modelBrowserPanelEl = null;
  let modelBrowserListEl = null;

  function closeModelBrowserPanel() {
    if (modelBrowserPanelEl) modelBrowserPanelEl.classList.remove('is-open');
  }

  function renderModelBrowserList() {
    if (!modelBrowserListEl) return;
    if (!loadedModels.length) {
      modelBrowserListEl.innerHTML = '<p class="nse-model-empty">No models found — is LM Studio running?</p>';
      return;
    }
    loadModelScores().then((scoreData) => {
      modelBrowserListEl.innerHTML = '';
      const currentModel = String(promptModelSelectEl.value || '').trim();
      const models = scoreData && scoreData.models
        ? loadedModels.slice().sort((a, b) => {
          const sa = scoreData.models[a] ? scoreData.models[a].average : -1;
          const sb = scoreData.models[b] ? scoreData.models[b].average : -1;
          if (sa !== sb) return sb - sa;
          return a.localeCompare(b);
        })
        : loadedModels.slice();
      models.forEach((m) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nse-model-item' + (m === currentModel ? ' is-selected' : '');
        btn.dataset.model = m;
        const name = document.createElement('span');
        name.className = 'nse-model-name';
        name.textContent = m.split('/').pop().split('\\').pop() || m;
        name.title = m;
        btn.appendChild(name);

        const badges = document.createElement('span');
        badges.className = 'nse-model-badges';
        const state = window.openJourneyApi.thinkCompatState({ lmStudioThinkCompat: thinkCompat }, m);
        const think = document.createElement('span');
        think.className = 'nse-model-think nse-model-think--' + state;
        think.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M9.5 3a3 3 0 00-3 3 3 3 0 00-2 5 3.5 3.5 0 002 6.4V19a2 2 0 002 2h1a2 2 0 002-2V6a3 3 0 00-2-3z"/>' +
          '<path d="M14.5 3a3 3 0 013 3 3 3 0 012 5 3.5 3.5 0 01-2 6.4V19a2 2 0 01-2 2h-1a2 2 0 01-2-2V6a3 3 0 012-3z"/>' +
          '</svg>';
        think.title = state === 'supported'
          ? 'Respects "don\'t think" requests.'
          : state === 'unsupported'
            ? 'Does not support disabling thinking — can burn its whole token budget reasoning.'
            : state === 'no_thinking'
              ? 'No thinking/reasoning capability — nothing to toggle.'
              : 'Think compatibility not checked yet.';
        badges.appendChild(think);
        const entry = scoreData && scoreData.models ? scoreData.models[m] : null;
        if (entry) {
          const scoreBadge = document.createElement('span');
          scoreBadge.className = 'nse-model-score ' + scoreTierClass(entry.average);
          scoreBadge.textContent = entry.average.toFixed(1);
          scoreBadge.title = 'Story benchmark score';
          badges.appendChild(scoreBadge);
          if (scoreData.fastestDurationSec && entry.durationSec) {
            // Relative SPEED (fastest / duration) — see flow-model-picker.js
            // for why this replaced the old duration/fastest ratio (that one
            // showed slow models as big numbers like "22.3x", reading as
            // "faster" at a glance when it meant the opposite).
            const rel = scoreData.fastestDurationSec / entry.durationSec;
            const timeBadge = document.createElement('span');
            timeBadge.className = 'nse-model-time';
            timeBadge.textContent = (rel >= 0.1 ? rel.toFixed(1) : rel.toFixed(2)) + 'x';
            timeBadge.title = entry.durationSec.toFixed(1) + 's — relative speed vs. fastest model (1.0x = fastest)';
            badges.appendChild(timeBadge);
          }
        }
        btn.appendChild(badges);

        btn.addEventListener('click', () => {
          promptModelSelectEl.value = m;
          promptModelSelectEl.dispatchEvent(new Event('change'));
          modelBrowserListEl.querySelectorAll('.nse-model-item').forEach((el) => {
            el.classList.toggle('is-selected', el.dataset.model === m);
          });
        });
        modelBrowserListEl.appendChild(btn);
      });
    });
  }

  function ensureModelBrowserPanel() {
    if (modelBrowserPanelEl) return modelBrowserPanelEl;
    modelBrowserPanelEl = document.createElement('div');
    modelBrowserPanelEl.className = 'cs-prompt-model-browser';
    // Anchored at left:840px by default (right of the embedded Settings
    // flyout, see nomad_studio.css) — but this page also renders standalone
    // at /models/chat with no Settings panel to its left, so pin it to the
    // right edge of the viewport instead when there's no flyout to sit next to.
    if (!document.getElementById('cs-settings-detail')) {
      modelBrowserPanelEl.style.left = 'auto';
      modelBrowserPanelEl.style.right = '0';
      modelBrowserPanelEl.style.maxWidth = 'calc(100vw - 1rem)';
    }
    modelBrowserPanelEl.innerHTML =
      '<div class="cs-prompt-model-browser-header">' +
        '<h3>Model</h3>' +
        '<button type="button" class="cs-prompt-model-browser-close" aria-label="Close">' +
          '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="cs-prompt-model-browser-body"><div class="nse-model-list" id="prompt-model-browser-list"></div></div>';
    document.body.appendChild(modelBrowserPanelEl);
    modelBrowserListEl = modelBrowserPanelEl.querySelector('#prompt-model-browser-list');
    modelBrowserPanelEl.querySelector('.cs-prompt-model-browser-close').addEventListener('click', closeModelBrowserPanel);

    // Cleanup: if this page was embedded in the Settings flyout and that
    // flyout's content gets replaced/closed (rootEl removed from the DOM),
    // this floating panel would otherwise be orphaned on screen.
    const observer = new MutationObserver(() => {
      if (!document.body.contains(rootEl)) {
        modelBrowserPanelEl.remove();
        modelBrowserPanelEl = null;
        modelBrowserListEl = null;
        observer.disconnect();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    return modelBrowserPanelEl;
  }

  if (browseModelsBtn) {
    browseModelsBtn.addEventListener('click', () => {
      const panel = ensureModelBrowserPanel();
      renderModelBrowserList();
      panel.classList.add('is-open');
    });
  }

  if (checkAllPendingBtn) {
    let bulkCheckRunning = false;
    let bulkCheckCancelled = false;
    const bulkCheckOriginalLabel = checkAllPendingBtn.textContent;

    checkAllPendingBtn.addEventListener('click', async () => {
      // Each check is a real load+generate+unload cycle against LM Studio —
      // with dozens of loaded models this can run for a very long time, so
      // the same button doubles as a cancel control once a run is in
      // progress (stops before starting the *next* model; can't abort a
      // request already in flight without an AbortController, which isn't
      // worth the plumbing here — worst case it finishes one extra model).
      if (bulkCheckRunning) {
        bulkCheckCancelled = true;
        checkAllPendingBtn.textContent = 'Stopping…';
        checkAllPendingBtn.disabled = true;
        return;
      }

      const pending = loadedModels.filter((m) => !thinkCompat[m]);
      if (!pending.length) {
        setStatus('No pending models — every loaded model has already been checked.');
        return;
      }
      bulkCheckRunning = true;
      bulkCheckCancelled = false;
      checkThinkCompatBtn.disabled = true;
      for (let i = 0; i < pending.length; i += 1) {
        if (bulkCheckCancelled) break;
        const model = pending[i];
        checkAllPendingBtn.textContent = `Stop (${i + 1}/${pending.length})`;
        checkAllPendingBtn.disabled = false;
        if (thinkCompatStatusEl) thinkCompatStatusEl.textContent = `Checking ${model} (${i + 1}/${pending.length})…`;
        try {
          const result = await window.openJourneyApi.checkThinkCompatibility(model);
          thinkCompat = { ...thinkCompat, [result.model]: { state: result.state, checkedAt: result.checkedAt } };
        } catch (error) {
          setStatus(`Failed to check ${model}: ${error.message || 'unknown error'}`, true);
        }
        renderThinkCompatStatus();
        renderModelBrowserList();
      }
      const wasCancelled = bulkCheckCancelled;
      const checkedCount = pending.filter((m) => thinkCompat[m]).length;
      bulkCheckRunning = false;
      bulkCheckCancelled = false;
      checkThinkCompatBtn.disabled = false;
      checkAllPendingBtn.disabled = false;
      checkAllPendingBtn.textContent = bulkCheckOriginalLabel;
      setStatus(wasCancelled
        ? `Stopped — checked ${checkedCount}/${pending.length} pending model(s).`
        : `Checked ${checkedCount} pending model(s).`);
    });
  }

  if (benchmarkNewModelsBtn) {
    let benchmarkRunning = false;
    let benchmarkCancelled = false;
    const benchmarkOriginalLabel = benchmarkNewModelsBtn.textContent;

    benchmarkNewModelsBtn.addEventListener('click', async () => {
      // Same cancellable, one-model-per-request pattern as Check All Pending
      // (see its own comment above) — each model here is a real story-scene
      // generation call PLUS a second LLM-judge call, so this can run even
      // longer per model.
      if (benchmarkRunning) {
        benchmarkCancelled = true;
        benchmarkNewModelsBtn.textContent = 'Stopping…';
        benchmarkNewModelsBtn.disabled = true;
        return;
      }

      let pending;
      try {
        const result = await window.openJourneyApi.listBenchmarkPendingModels();
        pending = result.pending || [];
      } catch (error) {
        setStatus(error.message || 'Failed to list pending models.', true);
        return;
      }
      if (!pending.length) {
        if (benchmarkStatusEl) benchmarkStatusEl.textContent = 'No new models to benchmark.';
        return;
      }

      benchmarkRunning = true;
      benchmarkCancelled = false;
      let benchmarked = 0;
      let failed = 0;
      let engineDown = false;
      for (let i = 0; i < pending.length; i += 1) {
        if (benchmarkCancelled) break;
        const model = pending[i];
        benchmarkNewModelsBtn.textContent = `Stop (${i + 1}/${pending.length})`;
        benchmarkNewModelsBtn.disabled = false;
        if (benchmarkStatusEl) benchmarkStatusEl.textContent = `Benchmarking ${model} (${i + 1}/${pending.length})…`;
        try {
          const result = await window.openJourneyApi.benchmarkModel(model);
          if (result.ok) {
            benchmarked += 1;
            modelScoresCache = null; // force a fresh fetch — this model just got a new entry
          } else {
            failed += 1;
            setStatus(`${model}: ${result.error || 'benchmark failed'}`, true);
            // LM Studio's engine died and didn't come back (the server
            // already waited for it): every remaining model would fail in
            // under a second, so stop the run instead (NomadStudio#12).
            if (result.engineDown) {
              engineDown = true;
              renderModelBrowserList();
              break;
            }
          }
        } catch (error) {
          failed += 1;
          setStatus(`Failed to benchmark ${model}: ${error.message || 'unknown error'}`, true);
        }
        renderModelBrowserList();
      }
      const wasCancelled = benchmarkCancelled;
      benchmarkRunning = false;
      benchmarkCancelled = false;
      benchmarkNewModelsBtn.disabled = false;
      benchmarkNewModelsBtn.textContent = benchmarkOriginalLabel;
      if (benchmarkStatusEl) {
        benchmarkStatusEl.textContent = engineDown
          ? `Stopped — LM Studio stopped responding. Scored ${benchmarked} model(s), ${failed} failed. Restart LM Studio and run it again.`
          : wasCancelled
          ? `Stopped — scored ${benchmarked} model(s), ${failed} failed.`
          : `Scored ${benchmarked} model(s), ${failed} failed.`;
      }
    });
  }

  function setStatus(message, isError = false) {
    statusEl.textContent = message;
    statusEl.classList.toggle('status-error', isError);
  }

  function setLmStudioAvailability(available, message) {
    if (!availabilityChipEl || !availabilityTextEl) return;
    availabilityChipEl.classList.toggle('available', !!available);
    availabilityChipEl.classList.toggle('unavailable', available === false);
    availabilityTextEl.textContent = message;
  }

  async function probeLmStudioAvailability(uri) {
    const lmStudioApiUrl = String(uri || '').trim();
    if (!lmStudioApiUrl) {
      setLmStudioAvailability(false, 'LM Studio unavailable');
      return;
    }
    setLmStudioAvailability(null, 'Checking LM Studio...');
    try {
      await window.openJourneyApi.pingChatService(`models-chat-page:${pageRole}`);
      setLmStudioAvailability(true, 'LM Studio available');
    } catch {
      setLmStudioAvailability(false, 'LM Studio unavailable');
    }
  }

  function sanitizeFavoriteModels(values, availableModels) {
    const list = Array.isArray(values) ? values : [];
    const allowed = new Set((Array.isArray(availableModels) ? availableModels : []).map((item) => String(item || '').trim()).filter(Boolean));
    const seen = new Set();
    return list
      .map((item) => String(item || '').trim())
      .filter((item) => item && (!allowed.size || allowed.has(item)) && !seen.has(item) && seen.add(item));
  }

  function isPromptFavoriteModel(name) {
    return promptFavoriteModels.includes(String(name || '').trim());
  }

  function isVisionFavoriteModel(name) {
    return visionFavoriteModels.includes(String(name || '').trim());
  }

  function setPromptFavoriteButtonState() {
    if (!promptFavoriteToggleBtn) return;
    const selected = String(promptModelSelectEl.value || '').trim();
    if (!selected) {
      promptFavoriteToggleBtn.disabled = true;
      promptFavoriteToggleBtn.textContent = 'Add to favorites';
      return;
    }
    promptFavoriteToggleBtn.disabled = false;
    promptFavoriteToggleBtn.textContent = isPromptFavoriteModel(selected) ? 'In favorites' : 'Add to favorites';
  }

  function setVisionFavoriteButtonState() {
    if (!visionFavoriteToggleBtn) return;
    const selected = String(visionModelSelectEl.value || '').trim();
    if (!selected) {
      visionFavoriteToggleBtn.disabled = true;
      visionFavoriteToggleBtn.textContent = 'Add to favorites';
      return;
    }
    visionFavoriteToggleBtn.disabled = false;
    visionFavoriteToggleBtn.textContent = isVisionFavoriteModel(selected) ? 'In favorites' : 'Add to favorites';
  }

  async function persistFavoriteSettings() {
    return window.openJourneyApi.updateModelsChatSettings({
      lmStudioApiUrl: uriEl.value.trim(),
      lmStudioPromptModel: promptModelSelectEl.value,
      lmStudioVisionModel: visionModelSelectEl.value,
      lmStudioFavoriteModels: promptFavoriteModels,
      lmStudioVisionFavoriteModels: visionFavoriteModels,
      lmStudioShowFavoritesOnly: showPromptFavoritesOnly,
      lmStudioVisionShowFavoritesOnly: showVisionFavoritesOnly,
      lmStudioAutoDisconnect: !!autoDisconnectEl.checked,
      lmStudioTemperature: coerceTemperature(temperatureEl.value),
    });
  }

  function renderPromptFavoritesQuick(models, selected) {
    if (!promptFavoritesQuickEl) return;
    promptFavoritesQuickEl.innerHTML = '';
    const list = Array.isArray(models) ? models : [];
    const available = new Set(list);
    const favorites = promptFavoriteModels.filter((name) => available.has(name));
    if (!favorites.length) {
      promptFavoritesQuickEl.innerHTML = '<p class="muted-note">No prompt favorites yet.</p>';
      return;
    }

    favorites.forEach((name) => {
      const row = document.createElement('div');
      row.className = 'models-chat-favorite-row';
      row.classList.toggle('is-active', name === selected);
      row.addEventListener('click', async () => {
        promptModelSelectEl.value = name;
        setPromptFavoriteButtonState();
        renderPromptFavoritesQuick(loadedModels, name);
        try {
          await window.openJourneyApi.updateModelsChatSettings({
            lmStudioPromptModel: name,
          });
        } catch {
          // Non-fatal: selection is applied locally.
        }
      });

      // Decorative only — favoriting/unfavoriting happens through the
      // explicit "Add to favorites"/"In favorites" button above the select,
      // or the × button below. The star used to double as that remove
      // button too, but nothing about a plain star signals "clickable, this
      // removes the row" — it read as just a favorite marker (found live:
      // user expected a dedicated remove control and drew one in).
      const starEl = document.createElement('span');
      starEl.className = 'models-chat-favorite-star';
      starEl.textContent = '★';
      starEl.setAttribute('aria-hidden', 'true');
      row.appendChild(starEl);

      const nameEl = document.createElement('span');
      nameEl.className = 'models-chat-favorite-name';
      nameEl.textContent = name;
      row.appendChild(nameEl);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'models-chat-favorite-remove';
      removeBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
      removeBtn.setAttribute('aria-label', 'Remove from favorites');
      removeBtn.title = 'Remove from favorites';
      removeBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        promptFavoriteModels = promptFavoriteModels.filter((item) => item !== name);
        try {
          const response = await persistFavoriteSettings();
          hydrateFromSettings(response.settings || {}, loadedModels, detectedVisionModels);
          setStatus('Favorite removed.');
        } catch (error) {
          setStatus(error.message || 'Failed to update favorites.', true);
        }
      });
      row.appendChild(removeBtn);

      promptFavoritesQuickEl.appendChild(row);
    });
  }

  function renderVisionFavoritesQuick(models, selected) {
    if (!visionFavoritesQuickEl) return;
    visionFavoritesQuickEl.innerHTML = '';
    const list = Array.isArray(models) ? models : [];
    const available = new Set(list);
    const favorites = visionFavoriteModels.filter((name) => available.has(name));
    if (!favorites.length) {
      visionFavoritesQuickEl.innerHTML = '<p class="muted-note">No vision favorites yet.</p>';
      return;
    }

    favorites.forEach((name) => {
      const row = document.createElement('div');
      row.className = 'models-chat-favorite-row';
      row.classList.toggle('is-active', name === selected);
      row.addEventListener('click', async () => {
        visionModelSelectEl.value = name;
        setVisionFavoriteButtonState();
        renderVisionFavoritesQuick(list, name);
        try {
          await window.openJourneyApi.updateModelsChatSettings({
            lmStudioVisionModel: name,
          });
        } catch {
          // Non-fatal.
        }
      });

      const starEl = document.createElement('span');
      starEl.className = 'models-chat-favorite-star';
      starEl.textContent = '★';
      starEl.setAttribute('aria-hidden', 'true');
      row.appendChild(starEl);

      const nameEl = document.createElement('span');
      nameEl.className = 'models-chat-favorite-name';
      nameEl.textContent = name;
      row.appendChild(nameEl);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'models-chat-favorite-remove';
      removeBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
      removeBtn.setAttribute('aria-label', 'Remove from favorites');
      removeBtn.title = 'Remove from favorites';
      removeBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        visionFavoriteModels = visionFavoriteModels.filter((item) => item !== name);
        try {
          const response = await persistFavoriteSettings();
          hydrateFromSettings(response.settings || {}, loadedModels, detectedVisionModels);
          setStatus('Favorite removed.');
        } catch (error) {
          setStatus(error.message || 'Failed to update vision favorites.', true);
        }
      });
      row.appendChild(removeBtn);

      visionFavoritesQuickEl.appendChild(row);
    });
  }

  function renderPromptModelOptions(models, selected) {
    promptModelSelectEl.innerHTML = '';
    const list = Array.isArray(models) ? models : [];
    loadedModels = list;
    promptFavoriteModels = sanitizeFavoriteModels(promptFavoriteModels, list);

    const sorted = [...list].sort((a, b) => {
      const aFav = isPromptFavoriteModel(a) ? 1 : 0;
      const bFav = isPromptFavoriteModel(b) ? 1 : 0;
      if (aFav !== bFav) return bFav - aFav;
      return a.localeCompare(b);
    });

    const visible = showPromptFavoritesOnly ? sorted.filter((name) => isPromptFavoriteModel(name)) : sorted;
    const displayList = showPromptFavoritesOnly ? visible : sorted;

    if (!displayList.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = showPromptFavoritesOnly ? 'No prompt favorites selected' : 'No models loaded';
      promptModelSelectEl.appendChild(option);
      promptModelSelectEl.value = '';
      renderPromptFavoritesQuick([], '');
      setPromptFavoriteButtonState();
      return;
    }

    displayList.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      promptModelSelectEl.appendChild(option);
    });

    if (selected && displayList.includes(selected)) {
      promptModelSelectEl.value = selected;
    } else {
      promptModelSelectEl.value = displayList[0];
    }

    renderPromptFavoritesQuick(list, promptModelSelectEl.value);
    setPromptFavoriteButtonState();
  }

  function renderVisionModelOptions(allModels, visionModels, selected) {
    visionModelSelectEl.innerHTML = '';
    const allList = Array.isArray(allModels) ? allModels : [];
    const detectedList = Array.isArray(visionModels) ? visionModels.filter((name) => allList.includes(name)) : [];
    detectedVisionModels = detectedList;
    visionFavoriteModels = sanitizeFavoriteModels(visionFavoriteModels, allList);

    const baseList = detectedList.length ? detectedList : allList;
    const sorted = [...baseList].sort((a, b) => {
      const aFav = isVisionFavoriteModel(a) ? 1 : 0;
      const bFav = isVisionFavoriteModel(b) ? 1 : 0;
      if (aFav !== bFav) return bFav - aFav;
      return a.localeCompare(b);
    });

    const visible = showVisionFavoritesOnly ? sorted.filter((name) => isVisionFavoriteModel(name)) : sorted;
    const displayList = showVisionFavoritesOnly ? visible : sorted;

    if (visionFilterNoteEl) {
      if (!allList.length) {
        visionFilterNoteEl.textContent = 'Load LM Studio models first.';
      } else if (detectedList.length) {
        visionFilterNoteEl.textContent = `Showing ${detectedList.length} detected vision-capable model(s).`;
      } else {
        visionFilterNoteEl.textContent = 'LM Studio did not expose vision metadata. Showing all models as fallback.';
      }
    }

    if (!displayList.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = showVisionFavoritesOnly ? 'No vision favorites selected' : 'No vision models loaded';
      visionModelSelectEl.appendChild(option);
      visionModelSelectEl.value = '';
      renderVisionFavoritesQuick(baseList, '');
      setVisionFavoriteButtonState();
      return;
    }

    displayList.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      visionModelSelectEl.appendChild(option);
    });

    const preferred = String(selected || '').trim();
    if (preferred && displayList.includes(preferred)) {
      visionModelSelectEl.value = preferred;
      renderVisionFavoritesQuick(baseList, visionModelSelectEl.value);
      setVisionFavoriteButtonState();
      return;
    }

    const promptSelected = String(promptModelSelectEl.value || '').trim();
    if (promptSelected && displayList.includes(promptSelected)) {
      visionModelSelectEl.value = promptSelected;
      renderVisionFavoritesQuick(baseList, visionModelSelectEl.value);
      setVisionFavoriteButtonState();
      return;
    }

    visionModelSelectEl.value = displayList[0];
    renderVisionFavoritesQuick(baseList, visionModelSelectEl.value);
    setVisionFavoriteButtonState();
  }

  function coerceTemperature(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return 0.2;
    const bounded = Math.max(0, Math.min(2, parsed));
    return Number(bounded.toFixed(2));
  }

  function renderOutputLog(items) {
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      outputLogEl.value = '';
      outputLogEl.placeholder = 'No output log yet';
      return;
    }

    const lines = list.map((entry) => {
      const at = String(entry.at || '').trim() || 'unknown-time';
      const model = String(entry.model || '').trim() || 'unknown-model';
      const ok = entry.ok ? 'OK' : 'ERROR';
      const instruction = String(entry.instruction || '').trim();
      const rawOutput = String(entry.rawOutput || '').trim();
      const editedPrompt = String(entry.editedPrompt || '').trim();
      return [
        `[${at}] ${ok} | ${model}`,
        `Instruction: ${instruction || '(empty)'}`,
        `Raw: ${rawOutput || '(empty)'}`,
        `Edited: ${editedPrompt || '(empty)'}`,
        '---',
      ].join('\n');
    });

    outputLogEl.value = lines.join('\n');
    outputLogEl.scrollTop = 0;
  }

  function hydrateFromSettings(settings, fallbackModels = [], fallbackVisionModels = []) {
    const modelList = Array.isArray(settings.lmStudioModels) ? settings.lmStudioModels : fallbackModels;
    const promptModel = String(settings.lmStudioPromptModel || settings.lmStudioModel || '').trim();
    const visionModels = Array.isArray(settings.lmStudioVisionModels) ? settings.lmStudioVisionModels : fallbackVisionModels;
    const visionModel = String(settings.lmStudioVisionModel || promptModel || '').trim();

    uriEl.value = settings.lmStudioApiUrl || uriEl.value;
    showPromptFavoritesOnly = !!settings.lmStudioShowFavoritesOnly;
    showVisionFavoritesOnly = !!settings.lmStudioVisionShowFavoritesOnly;
    if (promptFavoritesOnlyEl) promptFavoritesOnlyEl.checked = showPromptFavoritesOnly;
    if (visionFavoritesOnlyEl) visionFavoritesOnlyEl.checked = showVisionFavoritesOnly;
    promptFavoriteModels = sanitizeFavoriteModels(settings.lmStudioFavoriteModels || [], modelList);
    visionFavoriteModels = sanitizeFavoriteModels(settings.lmStudioVisionFavoriteModels || [], modelList);
    renderPromptModelOptions(modelList, promptModel);
    renderVisionModelOptions(modelList, visionModels, visionModel);
    thinkCompat = settings.lmStudioThinkCompat || {};
    renderThinkCompatStatus();
    autoDisconnectEl.checked = !!settings.lmStudioAutoDisconnect;
    temperatureEl.value = String(coerceTemperature(settings.lmStudioTemperature));
    renderOutputLog(settings.lmStudioOutputLog || []);
  }

  async function loadSettings() {
    try {
      const response = await window.openJourneyApi.getModelsChatSettings();
      const settings = response.settings || {};
      hydrateFromSettings(settings);
      setStatus(`LM Studio ${roleLabel} settings loaded.`);
      probeLmStudioAvailability(uriEl.value);
    } catch (error) {
      setStatus(error.message || 'Failed to load settings.', true);
      setLmStudioAvailability(false, 'LM Studio unavailable');
    }
  }

  async function persistAllSettings(successMessage = '') {
    const response = await window.openJourneyApi.updateModelsChatSettings({
      lmStudioApiUrl: uriEl.value.trim(),
      lmStudioPromptModel: promptModelSelectEl.value,
      lmStudioVisionModel: visionModelSelectEl.value,
      lmStudioFavoriteModels: promptFavoriteModels,
      lmStudioVisionFavoriteModels: visionFavoriteModels,
      lmStudioShowFavoritesOnly: showPromptFavoritesOnly,
      lmStudioVisionShowFavoritesOnly: showVisionFavoritesOnly,
      lmStudioAutoDisconnect: !!autoDisconnectEl.checked,
      lmStudioTemperature: coerceTemperature(temperatureEl.value),
    });
    const settings = response.settings || {};
    hydrateFromSettings(settings, loadedModels, detectedVisionModels);
    if (successMessage) setStatus(successMessage);
    return response;
  }

  loadModelsBtn.addEventListener('click', async () => {
    setStatus('Loading models from LM Studio...');
    try {
      const response = await window.openJourneyApi.loadLmStudioModels({ lmStudioApiUrl: uriEl.value.trim() });
      const settings = response.settings || {};
      const allModels = settings.lmStudioModels || response.models || [];
      const visionModels = settings.lmStudioVisionModels || response.visionModels || [];
      hydrateFromSettings(settings, allModels, visionModels);
      setStatus(`Loaded ${allModels.length} model(s), ${detectedVisionModels.length || visionModels.length || 0} vision candidate(s).`);
      setLmStudioAvailability(true, 'LM Studio available');
    } catch (error) {
      setStatus(error.message || 'Failed to load models.', true);
      setLmStudioAvailability(false, 'LM Studio unavailable');
    }
  });

  if (checkThinkCompatBtn) {
    checkThinkCompatBtn.addEventListener('click', async () => {
      const model = String(promptModelSelectEl.value || '').trim();
      if (!model) {
        setStatus('Select a Prompt LLM model first.', true);
        return;
      }
      checkThinkCompatBtn.disabled = true;
      const originalLabel = checkThinkCompatBtn.textContent;
      checkThinkCompatBtn.textContent = 'Checking…';
      if (thinkCompatStatusEl) thinkCompatStatusEl.textContent = 'Running a live test against LM Studio…';
      try {
        const result = await window.openJourneyApi.checkThinkCompatibility(model);
        thinkCompat = { ...thinkCompat, [result.model]: { state: result.state, checkedAt: result.checkedAt } };
        renderThinkCompatStatus();
        renderModelBrowserList();
        setStatus(`Think compatibility checked for ${model}.`);
      } catch (error) {
        renderThinkCompatStatus();
        setStatus(error.message || 'Failed to check think compatibility.', true);
      } finally {
        checkThinkCompatBtn.disabled = false;
        checkThinkCompatBtn.textContent = originalLabel;
      }
    });
  }

  if (saveSettingsBtn) {
    saveSettingsBtn.addEventListener('click', async () => {
      try {
        await persistAllSettings(`LM Studio ${roleLabel} settings saved.`);
        probeLmStudioAvailability(uriEl.value);
      } catch (error) {
        setStatus(error.message || 'Failed to save settings.', true);
        setLmStudioAvailability(false, 'LM Studio unavailable');
      }
    });
  }

  autoDisconnectEl.addEventListener('change', async () => {
    try {
      await persistAllSettings('Auto-disconnect setting saved.');
    } catch (error) {
      setStatus(error.message || 'Failed to save auto-disconnect setting.', true);
    }
  });

  uriEl.addEventListener('blur', async () => {
    try {
      await persistAllSettings('Connection settings saved.');
      probeLmStudioAvailability(uriEl.value);
    } catch {
      // Non-fatal: user may continue working locally.
    }
  });

  temperatureEl.addEventListener('change', async () => {
    try {
      await persistAllSettings('Parameters saved.');
    } catch {
      // Non-fatal.
    }
  });

  promptModelSelectEl.addEventListener('change', async () => {
    setPromptFavoriteButtonState();
    renderPromptFavoritesQuick(loadedModels, promptModelSelectEl.value);
    renderThinkCompatStatus();
    if (modelBrowserPanelEl && modelBrowserPanelEl.classList.contains('is-open')) {
      modelBrowserListEl.querySelectorAll('.nse-model-item').forEach((el) => {
        el.classList.toggle('is-selected', el.dataset.model === promptModelSelectEl.value);
      });
    }
    try {
      await window.openJourneyApi.updateModelsChatSettings({
        lmStudioPromptModel: promptModelSelectEl.value,
      });
    } catch {
      // Non-fatal.
    }
  });

  visionModelSelectEl.addEventListener('change', async () => {
    setVisionFavoriteButtonState();
    renderVisionFavoritesQuick(detectedVisionModels.length ? detectedVisionModels : loadedModels, visionModelSelectEl.value);
    try {
      await window.openJourneyApi.updateModelsChatSettings({
        lmStudioVisionModel: visionModelSelectEl.value,
      });
    } catch {
      // Non-fatal.
    }
  });

  if (promptFavoriteToggleBtn) {
    promptFavoriteToggleBtn.addEventListener('click', async () => {
      const selected = String(promptModelSelectEl.value || '').trim();
      if (!selected) {
        setStatus('Select a prompt model first.', true);
        return;
      }

      const wasFavorite = isPromptFavoriteModel(selected);
      if (wasFavorite) {
        setStatus('Model is already in favorites.');
        return;
      }

      promptFavoriteModels = sanitizeFavoriteModels([...promptFavoriteModels, selected], loadedModels);

      try {
        const response = await persistFavoriteSettings();
        hydrateFromSettings(response.settings || {}, loadedModels, detectedVisionModels);
        setStatus('Added to prompt favorites.');
      } catch (error) {
        setStatus(error.message || 'Failed to update favorites.', true);
      }
    });
  }

  if (visionFavoriteToggleBtn) {
    visionFavoriteToggleBtn.addEventListener('click', async () => {
      const selected = String(visionModelSelectEl.value || '').trim();
      if (!selected) {
        setStatus('Select a vision model first.', true);
        return;
      }

      const wasFavorite = isVisionFavoriteModel(selected);
      if (wasFavorite) {
        setStatus('Model is already in favorites.');
        return;
      }

      visionFavoriteModels = sanitizeFavoriteModels([...visionFavoriteModels, selected], loadedModels);

      try {
        const response = await persistFavoriteSettings();
        hydrateFromSettings(response.settings || {}, loadedModels, detectedVisionModels);
        setStatus('Added to vision favorites.');
      } catch (error) {
        setStatus(error.message || 'Failed to update vision favorites.', true);
      }
    });
  }

  if (promptFavoritesOnlyEl) {
    promptFavoritesOnlyEl.addEventListener('change', async () => {
      showPromptFavoritesOnly = !!promptFavoritesOnlyEl.checked;
      renderPromptModelOptions(loadedModels, promptModelSelectEl.value);
      try {
        await window.openJourneyApi.updateModelsChatSettings({
          lmStudioShowFavoritesOnly: showPromptFavoritesOnly,
        });
      } catch {
        // Non-fatal: keep local toggle state for this session.
      }
    });
  }

  if (visionFavoritesOnlyEl) {
    visionFavoritesOnlyEl.addEventListener('change', async () => {
      showVisionFavoritesOnly = !!visionFavoritesOnlyEl.checked;
      renderVisionModelOptions(loadedModels, detectedVisionModels, visionModelSelectEl.value);
      try {
        await window.openJourneyApi.updateModelsChatSettings({
          lmStudioVisionShowFavoritesOnly: showVisionFavoritesOnly,
        });
      } catch {
        // Non-fatal: keep local toggle state for this session.
      }
    });
  }

  clearLogBtn.addEventListener('click', async () => {
    try {
      const response = await window.openJourneyApi.updateModelsChatSettings({
        clearLmStudioOutputLog: true,
      });
      const settings = response.settings || {};
      renderOutputLog(settings.lmStudioOutputLog || []);
      setStatus('LM Studio output log cleared.');
    } catch (error) {
      setStatus(error.message || 'Failed to clear output log.', true);
    }
  });

  await loadSettings();
})();
