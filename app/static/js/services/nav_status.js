// ── Output-dir first-run gate ──────────────────────────────────────────────
// An install that never finished the setup wizard is sent there instead of
// getting the old "Setup required" banner (docs/SETUP_WIZARD.md W1). The
// banner below stays as the fallback for an install whose wizard is done but
// whose output folder was cleared later in Settings.
(async function outputDirGate() {
  const isSettingsPage = window.location.pathname === '/settings';
  if (isSettingsPage || window.location.pathname === '/setup') return;

  try {
    const st = await fetch('/api/setup/state').then((r) => (r.ok ? r.json() : null));
    if (st && st.setupCompleted === false) {
      window.location.href = '/setup';
      return;
    }
  } catch {
    // setup state unavailable — fall through to the output-dir check
  }

  let outputDir = '';
  try {
    const res = await fetch('/api/models/settings');
    if (res.ok) {
      const json = await res.json();
      outputDir = String(json?.settings?.outputDir || '').trim();
    }
  } catch {
    // network failure — don't block
    return;
  }

  if (outputDir) return;

  // Build and inject banner
  const banner = document.createElement('div');
  banner.id = 'output-dir-gate-banner';
  banner.className = 'output-dir-gate-banner';
  banner.innerHTML = `
    <div class="output-dir-gate-inner">
      <strong>Setup required</strong>
      <span>You must configure an Output Folder before using OpenHiker. All generated images will be saved there.</span>
      <a href="/settings" class="btn primary">Go to Settings</a>
    </div>
  `;
  document.body.appendChild(banner);
})();

(async function navStatusService() {
  const imagesLed = document.getElementById('nav-led-images');
  const upscaleLed = document.getElementById('nav-led-upscale');
  const chatLed = document.getElementById('nav-led-chat');
  const visionLed = document.getElementById('nav-led-vision');
  const sidebarQueuePanelEl = document.getElementById('sidebar-queue-panel');
  const sidebarQueueCountEl = document.getElementById('sidebar-queue-count');
  const sidebarQueueProgressEl = document.getElementById('sidebar-queue-progress');
  const sidebarQueueProgressBarEl = document.getElementById('sidebar-queue-progress-bar');
  const sidebarQueueListEl = document.getElementById('sidebar-queue-list');
  const sidebarQueueClearBtn = document.getElementById('sidebar-queue-clear-btn');
  const CREATE_TASK_QUEUE_KEY = 'oj-create-task-queue-v1';
  const GLOBAL_QUEUE_REFRESH_MS = 1500;

  if (!imagesLed && !upscaleLed && !chatLed && !visionLed && !sidebarQueuePanelEl) {
    return;
  }

  // Polling timers — only active while service is unavailable
  let imagesTimer = null;
  let upscaleTimer = null;
  let chatTimer   = null;

  const POLL_INTERVAL = 30000;

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function readPersistedQueueTasks() {
    try {
      const raw = localStorage.getItem(CREATE_TASK_QUEUE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((task) => task && typeof task === 'object');
    } catch {
      return [];
    }
  }

  function getQueueTaskTypeLabel(task) {
    return String(task?.type || '').toLowerCase() === 'describe' ? 'Describe' : 'Generate';
  }

  function getQueueTaskStatusLabel(task) {
    const value = String(task?.status || 'pending').toLowerCase();
    if (value === 'running') return 'Running';
    if (value === 'done') return 'Done';
    if (value === 'failed') return 'Failed';
    return 'Pending';
  }

  function clearPersistedQueueTasks() {
    try {
      localStorage.setItem(CREATE_TASK_QUEUE_KEY, JSON.stringify([]));
    } catch {
      // Ignore localStorage failures.
    }
    renderGlobalSidebarQueue();
  }

  function renderGlobalSidebarQueue() {
    if (!sidebarQueuePanelEl || !sidebarQueueListEl || !sidebarQueueCountEl || !sidebarQueueProgressEl || !sidebarQueueProgressBarEl) {
      return;
    }
    if (document.body.classList.contains('create-page')) {
      // Studio page has richer real-time renderer in create.js.
      return;
    }

    const tasks = readPersistedQueueTasks();
    const runningTask = tasks.find((task) => String(task?.status || '').toLowerCase() === 'running') || null;
    const pendingTasks = tasks.filter((task) => String(task?.status || 'pending').toLowerCase() === 'pending');
    const total = (runningTask ? 1 : 0) + pendingTasks.length;
    sidebarQueueCountEl.textContent = String(total);

    if (!total) {
      sidebarQueueProgressEl.textContent = tF('Idle');
      sidebarQueueProgressBarEl.style.width = '0%';
      sidebarQueueListEl.innerHTML = '<p class="sidebar-queue-empty">' + tH('No pending tasks.') + '</p>';
      return;
    }

    if (runningTask) {
      const typeLabel = getQueueTaskTypeLabel(runningTask);
      const isGenerate = typeLabel.toLowerCase() === 'generate';
      const storedPct = Number(runningTask?.progress ?? -1);
      const pct = storedPct >= 1 ? Math.min(99, Math.round(storedPct)) : 15;
      sidebarQueueProgressEl.textContent = isGenerate
        ? `ComfyUI ${pct}%`
        : `LMStudio ${pct}%`;
      sidebarQueueProgressBarEl.style.width = `${pct}%`;
    } else {
      sidebarQueueProgressEl.textContent = `${pendingTasks.length} pending`;
      sidebarQueueProgressBarEl.style.width = '0%';
    }

    const items = [];
    if (runningTask) {
      items.push(runningTask);
    }
    pendingTasks.forEach((task) => {
      if (runningTask && String(task.id || '') === String(runningTask.id || '')) return;
      items.push(task);
    });

    sidebarQueueListEl.innerHTML = items.slice(0, 6).map((task) => {
      const isActive = runningTask && String(runningTask.id || '') === String(task.id || '');
      const status = getQueueTaskStatusLabel(task);
      const label = String(task?.queuedMessage || task?.payload?.queuedMessage || '').trim() || 'Queued task';
      return `
        <article class="sidebar-queue-item ${isActive ? 'active' : ''}">
          <div class="sidebar-queue-item-head">
            <span class="sidebar-queue-item-type">${escapeHtml(getQueueTaskTypeLabel(task))}</span>
            <span class="sidebar-queue-item-status">${escapeHtml(status)}</span>
          </div>
          <p class="sidebar-queue-item-label">${escapeHtml(label)}</p>
        </article>
      `;
    }).join('');

    if (!items.length) {
      sidebarQueueListEl.innerHTML = '<p class="sidebar-queue-empty">' + tH('No pending tasks.') + '</p>';
    }
  }

  function setLedState(el, state, titleText) {
    if (!el) return;
    el.classList.toggle('available', state === 'available');
    el.classList.toggle('unavailable', state === 'unavailable');
    el.title = titleText || '';
  }

  function startPolling(timerRef, fn, setRef) {
    if (timerRef) return timerRef; // already running
    return setInterval(fn, POLL_INTERVAL);
  }

  function stopPolling(timerId) {
    if (timerId) clearInterval(timerId);
    return null;
  }

  async function refreshImagesAvailability() {
    if (!imagesLed || !window.openJourneyApi) return;
    setLedState(imagesLed, 'checking', 'Checking Images service');
    try {
      const settingsResponse = await window.openJourneyApi.getModelsSettings();
      const comfyApiUrl = String(settingsResponse?.settings?.comfyApiUrl || '').trim();
      if (!comfyApiUrl) {
        setLedState(imagesLed, 'unavailable', 'Images service unavailable: no ComfyUI URI');
        imagesTimer = startPolling(imagesTimer, refreshImagesAvailability);
        return;
      }
      const result = await window.openJourneyApi.testModelsConnection({ comfyApiUrl });
      setLedState(imagesLed, 'available', `Images service available (${result.endpoint || 'system_stats'})`);
      imagesTimer = stopPolling(imagesTimer);
    } catch {
      setLedState(imagesLed, 'unavailable', 'Images service unavailable');
      imagesTimer = startPolling(imagesTimer, refreshImagesAvailability);
    }
  }

  async function refreshChatAvailability(force = false) {
    if ((!chatLed && !visionLed) || !window.openJourneyApi) return;
    setLedState(chatLed, 'checking', 'Checking Prompts service');
    setLedState(visionLed, 'checking', 'Checking Vision service');
    try {
      await window.openJourneyApi.pingChatService(`nav-led:${window.location.pathname}${window.location.hash}`, force);
      setLedState(chatLed, 'available', 'Prompts service available');
      setLedState(visionLed, 'available', 'Vision service available');
      chatTimer = stopPolling(chatTimer);
    } catch {
      setLedState(chatLed, 'unavailable', 'Prompts service unavailable');
      setLedState(visionLed, 'unavailable', 'Vision service unavailable');
      chatTimer = startPolling(chatTimer, () => refreshChatAvailability(true));
    }
  }

  async function refreshUpscaleAvailability() {
    if (!upscaleLed || !window.openJourneyApi) return;
    setLedState(upscaleLed, 'checking', 'Checking Upscale service');
    try {
      const response = await window.openJourneyApi.getUpscaleSettings();
      const comfyApiUrl = String(response?.settings?.comfyApiUrl || '').trim();
      if (!comfyApiUrl) {
        setLedState(upscaleLed, 'unavailable', 'Upscale service unavailable: no ComfyUI URI');
        upscaleTimer = startPolling(upscaleTimer, refreshUpscaleAvailability);
        return;
      }
      const result = await window.openJourneyApi.testModelsConnection({ comfyApiUrl });
      setLedState(upscaleLed, 'available', `Upscale service available (${result.endpoint || 'system_stats'})`);
      upscaleTimer = stopPolling(upscaleTimer);
    } catch {
      setLedState(upscaleLed, 'unavailable', 'Upscale service unavailable');
      upscaleTimer = startPolling(upscaleTimer, refreshUpscaleAvailability);
    }
  }

  window.refreshNavImagesLed = refreshImagesAvailability;
  window.refreshNavUpscaleLed = refreshUpscaleAvailability;

  // Make LEDs clickable for manual re-check
  if (imagesLed) {
    imagesLed.style.cursor = 'pointer';
    imagesLed.addEventListener('click', () => refreshImagesAvailability());
  }
  if (chatLed) {
    chatLed.style.cursor = 'pointer';
    chatLed.addEventListener('click', () => refreshChatAvailability(true));
  }
  if (visionLed) {
    visionLed.style.cursor = 'pointer';
    visionLed.addEventListener('click', () => refreshChatAvailability(true));
  }
  if (upscaleLed) {
    upscaleLed.style.cursor = 'pointer';
    upscaleLed.addEventListener('click', () => refreshUpscaleAvailability());
  }
  if (sidebarQueueClearBtn) {
    sidebarQueueClearBtn.addEventListener('click', clearPersistedQueueTasks);
  }

  // Initial check — polling starts automatically only for unavailable services
  await Promise.all([refreshImagesAvailability(), refreshUpscaleAvailability(), refreshChatAvailability()]);

  // Keep queue visible across non-Studio pages while tasks are persisted in localStorage.
  renderGlobalSidebarQueue();
  window.addEventListener('storage', (event) => {
    if (event.key === CREATE_TASK_QUEUE_KEY) {
      renderGlobalSidebarQueue();
    }
  });
  setInterval(renderGlobalSidebarQueue, GLOBAL_QUEUE_REFRESH_MS);
})();
