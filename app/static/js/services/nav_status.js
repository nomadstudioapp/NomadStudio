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
  function fill() {
    var h = window.tH || function (s) { return s; };
    banner.innerHTML = `
    <div class="output-dir-gate-inner">
      <strong>${h('Setup required')}</strong>
      <span>${h('You must configure an Output Folder before using Nomad Studio. All generated images will be saved there.')}</span>
      <a href="/settings" class="btn primary">${h('Go to Settings')}</a>
    </div>
  `;
  }
  fill();
  // i18n.js loads after this script: refill once its dictionary is in.
  function refillWhenReady() {
    if (window.NomadI18n && window.NomadI18n.ready) window.NomadI18n.ready.then(fill);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', refillWhenReady, { once: true });
  else refillWhenReady();
  document.body.appendChild(banner);
})();

// ── Service status LEDs ───────────────────────────────────────────────────
// Paints the model-service LEDs of the Nomad Studio settings panel
// ([data-cs-led] = images | chat | vision); nomad_studio.js reads their
// state to open the panel by itself when a service goes down. Elements are
// looked up on every update: shell_router.js swaps pages in without a reload.
(async function navStatusService() {
  const POLL_INTERVAL = 30000;
  let imagesTimer = null;
  let chatTimer = null;

  function leds(name) {
    return document.querySelectorAll(`[data-cs-led="${name}"]`);
  }

  function setLedState(name, state, titleText) {
    leds(name).forEach((el) => {
      el.classList.toggle('available', state === 'available');
      el.classList.toggle('unavailable', state === 'unavailable');
      el.title = titleText || '';
    });
  }

  function startPolling(timerId, fn) {
    if (timerId) return timerId; // already running
    return setInterval(fn, POLL_INTERVAL);
  }

  function stopPolling(timerId) {
    if (timerId) clearInterval(timerId);
    return null;
  }

  async function refreshImagesAvailability() {
    if (!window.openJourneyApi) return;
    setLedState('images', 'checking', 'Checking Images service');
    try {
      const settingsResponse = await window.openJourneyApi.getModelsSettings();
      const comfyApiUrl = String(settingsResponse?.settings?.comfyApiUrl || '').trim();
      if (!comfyApiUrl) {
        setLedState('images', 'unavailable', 'Images service unavailable: no ComfyUI URI');
        imagesTimer = startPolling(imagesTimer, refreshImagesAvailability);
        return;
      }
      const result = await window.openJourneyApi.testModelsConnection({ comfyApiUrl });
      setLedState('images', 'available', `Images service available (${result.endpoint || 'system_stats'})`);
      imagesTimer = stopPolling(imagesTimer);
    } catch {
      setLedState('images', 'unavailable', 'Images service unavailable');
      imagesTimer = startPolling(imagesTimer, refreshImagesAvailability);
    }
  }

  async function refreshChatAvailability(force = false) {
    if (!window.openJourneyApi) return;
    setLedState('chat', 'checking', 'Checking Prompts service');
    setLedState('vision', 'checking', 'Checking Vision service');
    try {
      await window.openJourneyApi.pingChatService(`nav-led:${window.location.pathname}${window.location.hash}`, force);
      setLedState('chat', 'available', 'Prompts service available');
      setLedState('vision', 'available', 'Vision service available');
      chatTimer = stopPolling(chatTimer);
    } catch {
      setLedState('chat', 'unavailable', 'Prompts service unavailable');
      setLedState('vision', 'unavailable', 'Vision service unavailable');
      chatTimer = startPolling(chatTimer, () => refreshChatAvailability(true));
    }
  }

  window.refreshNavImagesLed = refreshImagesAvailability;

  function refreshAll() {
    return Promise.all([refreshImagesAvailability(), refreshChatAvailability()]);
  }

  // Polling starts automatically only for unavailable services.
  await refreshAll();
  window.addEventListener('oj:shell:navigate-end', refreshAll);
})();
