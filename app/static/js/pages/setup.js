/* Nomad Studio — first-run setup wizard (docs/SETUP_WIZARD.md).
   Steps: language → ComfyUI → engines → LM Studio → language models → data
   folder → image folder → image format → first profile → summary.

   Every visible string goes through t() with an English fallback, and the
   whole wizard re-renders when a language dictionary is applied, so the
   language picked in step 1 takes effect immediately.

   Preview mode (?preview=1, from Settings) runs every check and detection but
   never saves, never downloads and never creates a profile. */
(function () {
  'use strict';

  var root = document.getElementById('su-screen');
  if (!root) return;

  var PREVIEW = root.dataset.preview === 'true';
  var AVATARS = [];
  try { AVATARS = JSON.parse(root.dataset.avatars || '[]'); } catch (e) { AVATARS = []; }
  var AVATAR_BASE = root.dataset.avatarsBase || '/static/images/avatars/';

  var bodyEl = document.getElementById('su-body');
  var stepsEl = document.getElementById('su-steps');
  var backBtn = document.getElementById('su-back');
  var nextBtn = document.getElementById('su-next');
  var skipBtn = document.getElementById('su-skip');

  var STEPS = [
    { id: 'language', key: 'setup.steps.language', fb: 'Language' },
    { id: 'comfy', key: 'setup.steps.comfy', fb: 'ComfyUI', optional: true },
    { id: 'engines', key: 'setup.steps.engines', fb: 'Engines', optional: true },
    { id: 'lmstudio', key: 'setup.steps.lmstudio', fb: 'LM Studio', optional: true },
    { id: 'models', key: 'setup.steps.models', fb: 'Models', optional: true },
    { id: 'data', key: 'setup.steps.data', fb: 'Data folder' },
    { id: 'output', key: 'setup.steps.output', fb: 'Image folder' },
    { id: 'format', key: 'setup.steps.format', fb: 'Image format' },
    { id: 'profile', key: 'setup.steps.profile', fb: 'First profile' },
    { id: 'done', key: 'setup.steps.done', fb: 'Ready' }
  ];

  var S = {
    step: 1,
    maxReached: 1,
    settings: {},
    viewers: 0,
    dataDir: {},
    comfy: null,          // result of /api/setup/check/comfy
    comfyBusy: false,
    lms: null,
    lmsBusy: false,
    discovery: null,      // result of /api/setup/discover (ComfyUI + LM Studio on the network)
    discoveryBusy: false,
    discoveryAuto: false, // searched automatically once after a failed check
    manual: {},           // kind -> the user asked to type the address
    apps: null,           // /api/setup/local-apps: what this computer already has
    appsBusy: false,
    appsStarting: null,   // 'comfy' | 'lmstudio' while it boots
    installJob: null,     // ComfyUI portable download
    comfyListen: false,   // start ComfyUI so other computers can reach it
    engines: null,        // result of /api/setup/engines
    enginesBusy: false,
    enginesError: '',
    openEngine: null,
    choice: {},           // engineId -> option key
    sizes: {},            // url -> bytes
    folderCheck: null,    // result of models-folder validation
    downloads: {},        // "sub/file" -> { pct, state, error }
    downloading: false,
    llm: null,            // result of /api/setup/llm-models
    llmBusy: false,
    llmError: '',
    llmJobs: {},          // model id -> { jobId, status, pct, error }
    outputCheck: null,
    outputWarning: null,
    profile: { name: '', avatar: '', pinOn: false, pin: '', error: '' },
    error: ''
  };

  // ── Helpers ───────────────────────────────────────────────────────────────
  function t(key, fb, vars) {
    var s = window.NomadI18n && window.NomadI18n.t ? window.NomadI18n.t(key, fb) : fb;
    if (vars) Object.keys(vars).forEach(function (k) { s = s.split('{' + k + '}').join(vars[k]); });
    return s;
  }
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function bytes(n) {
    if (n == null || isNaN(n)) return '';
    var gb = n / Math.pow(1024, 3);
    if (gb >= 1) return gb.toFixed(gb >= 10 ? 0 : 1) + ' GB';
    return Math.max(1, Math.round(n / Math.pow(1024, 2))) + ' MB';
  }
  function api(method, url, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok && j && !j.error) j.error = 'HTTP ' + r.status;
        return j;
      });
    });
  }
  function save(patch) {
    Object.keys(patch).forEach(function (k) { S.settings[k] = patch[k]; });
    if (PREVIEW) return Promise.resolve({ ok: true });
    return api('PATCH', '/api/setup/state', patch).then(function (res) {
      if (res && res.settings) S.settings = res.settings;
      return res;
    });
  }
  function current() { return STEPS[S.step - 1]; }

  // ── Checks ────────────────────────────────────────────────────────────────
  function checkComfy() {
    var url = (document.getElementById('su-comfy-url') || {}).value || S.settings.comfyApiUrl || 'http://127.0.0.1:8188';
    S.comfyBusy = true; S.comfy = null; S.engines = null; render();
    return api('POST', '/api/setup/check/comfy', { comfyApiUrl: url }).then(function (res) {
      S.comfyBusy = false; S.comfy = res;
      if (res.ok && res.comfyApiUrl) return save({ comfyApiUrl: res.comfyApiUrl }).then(render);
      autoDiscover();
      render();
    });
  }
  // Look for ComfyUI and LM Studio on this computer and the local network.
  // Runs by itself once, the first time a check fails; then on request.
  function runDiscovery() {
    if (S.discoveryBusy) return;
    S.discoveryBusy = true; render();
    return api('POST', '/api/setup/discover', {}).then(function (res) {
      S.discoveryBusy = false;
      S.discovery = res.ok ? res : { comfy: [], lmstudio: [], error: res.error || 'error' };
      render();
      // Only one server of the kind this step is about, and nothing connected:
      // use it. Otherwise the user has to pick the single option on the list.
      var kind = current().id === 'comfy' ? 'comfy' : current().id === 'lmstudio' ? 'lmstudio' : null;
      var found = kind ? (S.discovery[kind] || []) : [];
      var check = kind === 'comfy' ? S.comfy : S.lms;
      if (kind && found.length === 1 && !(check && check.ok)) useFound(kind, found[0].url);
    });
  }
  function useFound(kind, url) {
    S.manual[kind] = false;
    if (kind === 'comfy') { S.settings.comfyApiUrl = url; render(); return checkComfy(); }
    S.settings.lmStudioApiUrl = url; render(); return checkLms();
  }
  function autoDiscover() {
    if (S.discoveryAuto || S.discovery) return;
    S.discoveryAuto = true;
    runDiscovery();
  }
  function checkLms() {
    var url = (document.getElementById('su-lms-url') || {}).value || S.settings.lmStudioApiUrl || 'http://127.0.0.1:1234';
    S.lmsBusy = true; S.lms = null; S.llm = null; render();
    return api('POST', '/api/setup/check/lmstudio', { lmStudioApiUrl: url }).then(function (res) {
      S.lmsBusy = false; S.lms = res;
      if (res.ok && res.lmStudioApiUrl) return save({ lmStudioApiUrl: res.lmStudioApiUrl }).then(render);
      autoDiscover();
      render();
    });
  }
  // ── Language models (LM Studio) ───────────────────────────────────────────
  function detectLlm() {
    S.llmBusy = true; S.llmError = ''; render();
    return api('POST', '/api/setup/llm-models', { lmStudioApiUrl: S.settings.lmStudioApiUrl, save: !PREVIEW }).then(function (res) {
      S.llmBusy = false;
      if (!res.ok) { S.llmError = res.error || 'error'; S.llm = null; return render(); }
      S.llm = res;
      // Nothing chosen yet: use the first recommended model already installed.
      var first = (res.models || []).filter(function (m) { return m.installedKey; })[0];
      var patch = {};
      if (first && !S.settings.lmStudioPromptModel) patch.lmStudioPromptModel = first.installedKey;
      if (first && !S.settings.lmStudioVisionModel && first.vision !== false) patch.lmStudioVisionModel = first.installedKey;
      if (Object.keys(patch).length) return save(patch).then(render);
      render();
    });
  }

  // Model we suggest when none is installed: the 12B QAT on cards with room
  // for it, the 9B on smaller ones (same advice as the website's Engines page).
  function recommendedLlmId() {
    var gpu = S.comfy && S.comfy.gpus && S.comfy.gpus[0];
    if (gpu && gpu.vramTotal && gpu.vramTotal < 11.5 * Math.pow(1024, 3)) return 'qwythos-9b';
    return 'gemma-4-12b';
  }

  function installLlm(id) {
    if (PREVIEW || S.llmJobs[id] && S.llmJobs[id].status === 'downloading') return;
    S.llmJobs[id] = { status: 'starting', pct: 0 };
    render();
    api('POST', '/api/setup/llm-models/download', { id: id, lmStudioApiUrl: S.settings.lmStudioApiUrl }).then(function (res) {
      if (!res.ok) { S.llmJobs[id] = { status: 'failed', error: res.error || 'error' }; return render(); }
      if (res.status === 'already_downloaded' || res.status === 'completed' || !res.jobId) {
        S.llmJobs[id] = { status: 'completed', pct: 100 };
        return detectLlm();
      }
      S.llmJobs[id] = { jobId: res.jobId, status: 'downloading', pct: 0 };
      render();
      pollLlm(id);
    });
  }

  function pollLlm(id) {
    var job = S.llmJobs[id];
    if (!job || !job.jobId) return;
    api('GET', '/api/setup/llm-models/download/' + encodeURIComponent(job.jobId)).then(function (res) {
      if (!res.ok) { job.status = 'failed'; job.error = res.error || 'error'; return render(); }
      job.status = res.status;
      if (res.totalBytes) job.pct = Math.min(100, Math.round((res.downloadedBytes || 0) * 100 / res.totalBytes));
      if (res.status === 'completed') { job.pct = 100; render(); return detectLlm(); }
      if (res.status === 'failed') { job.error = t('setup.models.dlFailed', 'LM Studio could not download it.'); return render(); }
      render();
      setTimeout(function () { pollLlm(id); }, 1500);
    });
  }

  function detectEngines() {
    S.enginesBusy = true; S.enginesError = ''; render();
    return api('POST', '/api/setup/engines', { comfyApiUrl: S.settings.comfyApiUrl }).then(function (res) {
      S.enginesBusy = false;
      if (!res.ok) { S.enginesError = res.error || 'error'; S.engines = null; render(); return; }
      S.engines = res;
      res.engines.forEach(function (e) {
        if (!S.choice[e.id]) S.choice[e.id] = e.recommendedOption || null;
      });
      render();
    });
  }

  // Files an engine still needs for the chosen option (plus shared files).
  function neededFiles(engine) {
    var files = engine.common.slice();
    if (engine.options.length) {
      var opt = engine.options.filter(function (o) { return o.key === S.choice[engine.id]; })[0] || engine.options[0];
      files = files.concat(opt.files);
    }
    var seen = {};
    return files.filter(function (f) {
      var k = f.filename.toLowerCase();
      if (seen[k]) return false;
      seen[k] = true;
      return true;
    });
  }

  function fetchSizes(files) {
    var urls = files.filter(function (f) { return f.url && S.sizes[f.url] === undefined; }).map(function (f) { return f.url; });
    if (!urls.length) return;
    urls.forEach(function (u) { S.sizes[u] = null; });
    api('POST', '/api/setup/downloads/sizes', { urls: urls }).then(function (res) {
      Object.keys(res.sizes || {}).forEach(function (u) { S.sizes[u] = res.sizes[u]; });
      if (res.freeBytes != null) S.freeBytes = res.freeBytes;
      render();
    });
  }

  // A portable ComfyUI on this computer (often the one the wizard just
  // installed) has a known models folder: fill it in and check it, instead of
  // asking a new user for a path they have never seen.
  function suggestModelsFolder() {
    if (S.settings.comfyModelsFolder || S.folderSuggested || S.draftModelsFolder != null) return;
    S.folderSuggested = true;
    api('GET', '/api/setup/local-apps').then(function (res) {
      var dir = res && res.ok && res.comfyModelsDir;
      if (!dir || S.settings.comfyModelsFolder) return;
      S.draftModelsFolder = dir;
      render();
      validateFolder();
    });
  }

  function validateFolder() {
    var path = (document.getElementById('su-models-folder') || {}).value || '';
    S.folderCheck = { busy: true }; render();
    return api('POST', '/api/setup/models-folder/validate', { path: path.trim(), comfyApiUrl: S.settings.comfyApiUrl }).then(function (res) {
      S.folderCheck = res;
      if (res.ok) {
        S.draftModelsFolder = null;
        return save({ comfyModelsFolder: path.trim() }).then(render);
      }
      render();
    });
  }

  function installEngine(engine) {
    if (PREVIEW || S.downloading) return;
    var queue = neededFiles(engine).filter(function (f) { return !f.present && f.url; });
    if (!queue.length) return;
    S.downloading = true;
    var run = function (i) {
      if (i >= queue.length) {
        S.downloading = false;
        return detectEngines();
      }
      var f = queue[i];
      var id = f.subfolder + '/' + f.filename;
      S.downloads[id] = { pct: 0, state: 'running' };
      render();
      return fetch('/api/models/imports/download-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: f.url, subfolder: f.subfolder, filename: f.filename, force: true })
      }).then(function (resp) {
        if (!resp.ok || !resp.body) {
          return resp.json().catch(function () { return {}; }).then(function (j) {
            throw new Error(j.error || ('HTTP ' + resp.status));
          });
        }
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buf = '';
        var failed = null;
        var pump = function () {
          return reader.read().then(function (chunk) {
            if (chunk.done) return;
            buf += decoder.decode(chunk.value, { stream: true });
            var lines = buf.split('\n');
            buf = lines.pop();
            lines.forEach(function (line) {
              if (!line.trim()) return;
              try {
                var msg = JSON.parse(line);
                if (msg.error) failed = msg.error;
                if (typeof msg.progress === 'number') S.downloads[id].pct = msg.progress;
              } catch (e) { /* partial line */ }
            });
            render();
            return pump();
          });
        };
        return pump().then(function () { if (failed) throw new Error(failed); });
      }).then(function () {
        S.downloads[id] = { pct: 100, state: 'done' };
        return run(i + 1);
      }).catch(function (err) {
        S.downloads[id] = { pct: 0, state: 'error', error: String(err && err.message || err) };
        S.downloading = false;
        render();
      });
    };
    run(0);
  }

  // ── Step bodies ───────────────────────────────────────────────────────────
  function statusBox(kind, html) {
    return '<div class="su-status is-' + kind + '"><span class="su-status-icon" aria-hidden="true"></span><div>' + html + '</div></div>';
  }

  function viewLanguage() {
    var I = window.NomadI18n;
    var active = I ? I.getLanguage() : 'en';
    var langs = I && I.LANGUAGES ? I.LANGUAGES : [{ id: 'en', label: 'English', ready: true }];
    return '<h2 class="su-h2">' + esc(t('setup.language.title', 'Choose your language')) + '</h2>' +
      '<p class="su-lead">' + esc(t('setup.language.lead', 'You can change it later from the language button in the corner of any screen.')) + '</p>' +
      '<div class="su-langs">' + langs.map(function (l) {
        return '<button type="button" class="su-lang' + (l.id === active ? ' is-selected' : '') + '" data-lang="' + esc(l.id) + '"' + (l.ready ? '' : ' disabled') + '>' +
          esc(l.label) + '<small>' + esc(l.id.toUpperCase()) + '</small></button>';
      }).join('') + '</div>';
  }

  // ── ComfyUI / LM Studio: one list, one message ────────────────────────────
  // What we found leads the step; the address box is an option, not the first
  // thing on screen, and the "on another computer?" help stays folded. Never
  // an error, a warning and an open help block stacked on top of each other.

  function serverName(kind) { return kind === 'comfy' ? 'ComfyUI' : 'LM Studio'; }

  function serverDetail(kind, f) {
    if (kind !== 'comfy') return f.models != null ? t('setup.lms.models', '{n} models available', { n: f.models }) : '';
    return [f.gpu || f.gpuName, f.vramTotal ? bytes(f.vramTotal) : '', f.version ? 'v' + f.version : ''].filter(Boolean).join(' · ');
  }

  // Servers to offer: what the search found, plus the address in use when it
  // works and the search did not list it (e.g. typed by hand).
  function serverList(kind) {
    var found = (S.discovery && S.discovery[kind]) || [];
    var check = kind === 'comfy' ? S.comfy : S.lms;
    var url = kind === 'comfy' ? S.settings.comfyApiUrl : S.settings.lmStudioApiUrl;
    var list = found.map(function (f) { return f; });
    if (check && check.ok && url && !list.some(function (f) { return f.url === url; })) {
      list.unshift({ url: url, isLocal: check.isLocal !== false, gpu: (check.gpus || [])[0] && check.gpus[0].name,
                     vramTotal: (check.gpus || [])[0] && check.gpus[0].vramTotal, version: check.version, models: check.models });
    }
    return list;
  }

  function serverRows(kind, list, currentUrl) {
    return '<div class="su-servers">' + list.map(function (f) {
      var selected = f.url === currentUrl;
      var where = f.isLocal ? t('setup.network.thisComputer', 'this computer') : t('setup.network.otherComputer', 'another computer');
      var detail = serverDetail(kind, f);
      return '<button type="button" class="su-server' + (selected ? ' is-selected' : '') + '" data-use-found="' + kind + '" data-url="' + esc(f.url) + '">' +
        '<span class="su-server-main"><span class="su-server-url">' + esc(f.url) + '</span>' +
        '<span class="su-server-meta">' + esc(where + (detail ? ' · ' + detail : '')) + '</span></span>' +
        (selected ? '<span class="su-server-badge">' + esc(t('setup.network.connected', 'connected')) + '</span>' : '') +
        '</button>';
    }).join('') + '</div>';
  }

  // Nothing found: the user may simply not have it. What this computer
  // already has (and whether we can install it) comes from /local-apps.
  function loadApps() {
    if (S.apps || S.appsBusy) return;
    S.appsBusy = true;
    api('GET', '/api/setup/local-apps').then(function (res) {
      S.appsBusy = false;
      S.apps = res && res.ok ? res : { comfy: null, lmstudio: null };
      render();
    });
  }

  function startApp(kind) {
    S.appsStarting = kind;
    S.appsNoAnswer = null;
    render();
    api('POST', '/api/setup/local-apps/start', { app: kind === 'comfy' ? 'comfy' : 'lmstudio', listen: kind === 'comfy' && S.comfyListen }).then(function (res) {
      // A fresh Windows lacks the Visual C++ runtime: reload what this
      // computer has so the install button for it shows up.
      if (res && res.needsVcRuntime) { S.appsStarting = null; S.apps = null; return loadApps(); }
      if (!res.ok) { S.appsStarting = null; S.error = res.error || ''; return render(); }
      // ComfyUI takes a while to come up: keep checking instead of asking again.
      // Its first start on a new install took 3-5 minutes on a clean Windows
      // VM (loading PyTorch cold), so it gets 6 minutes; LM Studio 80 s.
      var tries = 0;
      var maxTries = kind === 'comfy' ? 90 : 20;
      (function poll() {
        var check = kind === 'comfy' ? checkComfy : checkLms;
        check().then(function () {
          var ok = kind === 'comfy' ? (S.comfy && S.comfy.ok) : (S.lms && S.lms.ok);
          if (ok || ++tries > maxTries) {
            S.appsStarting = null;
            // Not silently back to "not found": its console says why.
            if (!ok) S.appsNoAnswer = kind;
            return render();
          }
          setTimeout(poll, 4000);
        });
      })();
    });
  }

  function installApp(app) {
    var input = document.getElementById(app === 'comfyui' ? 'su-comfy-dir' : 'su-lms-dir');
    var dir = (input && input.value.trim()) || (S.apps && S.apps.suggestedDir) || '';
    api('POST', '/api/setup/install/' + app, { dir: dir }).then(function (res) {
      if (!res.ok) { S.error = res.error || ''; return render(); }
      S.installJob = res.job;
      render();
      (function poll() {
        api('GET', '/api/setup/install/job').then(function (r) {
          S.installJob = (r && r.job) || null;
          render();
          if (S.installJob && S.installJob.state === 'running') return setTimeout(poll, 1000);
          if (S.installJob && S.installJob.state === 'done') {
            S.apps = null;
            loadApps();
            // ComfyUI is unpacked (or has its runtime now) and ready to start;
            // LM Studio opened its own installer, so we wait for the user to
            // finish it.
            if (app === 'comfyui' || app === 'vcredist') startApp('comfy');
            else waitForLmStudio(0);
          }
        });
      })();
    });
  }

  function waitForLmStudio(tries) {
    api('GET', '/api/setup/local-apps').then(function (res) {
      S.apps = res && res.ok ? res : S.apps;
      render();
      if (S.apps && S.apps.lmstudio) return startApp('lmstudio');
      if (tries < 60) setTimeout(function () { waitForLmStudio(tries + 1); }, 5000);
    });
  }

  // One short block, only when there is nothing to connect to.
  function installBlock(kind) {
    var apps = S.apps;
    var isComfy = kind === 'comfy';
    var found = apps && (isComfy ? apps.comfy : apps.lmstudio);
    var name = serverName(kind);
    if (S.appsStarting === kind) {
      return statusBox('busy', esc(t('setup.apps.starting', 'Starting {name}… this can take a minute.', { name: name })));
    }
    var job = S.installJob && (isComfy ? S.installJob.app === 'comfy' || S.installJob.app === 'vcredist'
      : S.installJob.app === 'lmstudio') ? S.installJob : null;
    var isVc = !!job && job.app === 'vcredist';
    if (!isComfy && S.apps && !S.apps.lmstudio && S.installJob && S.installJob.state === 'done'
        && S.installJob.app === 'lmstudio') {
      return statusBox('busy', esc(t('setup.apps.installerOpen', 'Finish the installation in the window that just opened.')));
    }
    if (job && job.state === 'running') {
      var pct = job.total ? Math.round(job.done * 100 / job.total) : 0;
      return statusBox('busy', esc(job.phase === 'extract'
        ? t('setup.apps.extracting', 'Unpacking ComfyUI…')
        : job.phase === 'installer' ? (isVc
          ? t('setup.apps.vcInstalling', 'Installing the Visual C++ Runtime… if Windows asks for permission, answer Yes.')
          : t('setup.apps.installerOpen', 'Finish the installation in the window that just opened.'))
        : t('setup.apps.downloadingApp', 'Downloading {name}… {pct}%', { name: isVc ? 'Visual C++ Runtime' : name, pct: pct })));
    }
    if (job && job.state === 'error' && !(isVc && apps && apps.vcRuntime === false)) return statusBox('bad', esc(job.error || ''));
    if (!apps || !apps.local) return '';
    // Portable ComfyUI on a fresh Windows: it would close as soon as it
    // starts, so the runtime comes first (app/services/local_apps.py).
    if (isComfy && found && found.kind === 'portable' && apps.vcRuntime === false) {
      return (job && job.state === 'error' ? statusBox('bad', esc(job.error || '')) : '') +
        statusBox('warn', '<strong>' + esc(t('setup.apps.vcTitle', 'ComfyUI needs the Microsoft Visual C++ Runtime')) + '</strong><br>' +
          esc(t('setup.apps.vcText', 'This computer does not have it yet, and without it ComfyUI closes as soon as it starts.'))) +
        '<div class="su-row"><button type="button" class="su-btn su-btn-install" id="su-install-vc">' +
          esc(t('setup.apps.installVc', 'Install Visual C++ Runtime')) + '</button></div>' +
        '<p class="su-hint">' + esc(t('setup.apps.vcNote', 'About 25 MB from Microsoft. Windows will ask for your permission once.')) + '</p>';
    }
    var noAnswer = S.appsNoAnswer === kind
      ? statusBox('bad', esc(t('setup.apps.noAnswer', '{name} did not answer. If its window closed or shows an error, that error says why.', { name: name })))
      : '';
    if (found && found.launcher) {
      var kindLabel = found.kind === 'desktop' ? t('setup.apps.desktop', 'desktop app')
        : found.kind === 'portable' ? t('setup.apps.portable', 'portable build') : '';
      var startRow = '<div class="su-servers"><button type="button" class="su-server" data-start-app="' + kind + '">' +
        '<span class="su-server-main"><span class="su-server-url">' +
        esc(t('setup.apps.start', 'Start {name}', { name: name })) + '</span>' +
        '<span class="su-server-meta">' + esc((kindLabel ? kindLabel + ' · ' : '') + found.path) + '</span></span></button></div>';
      // Only the desktop app: the portable build is the one this works best
      // with, so offer it too instead of leaving it as the only option.
      if (isComfy && apps.comfyCanListen) {
        startRow += '<label class="su-check"><input type="checkbox" id="su-comfy-listen"' + (S.comfyListen ? ' checked' : '') + '>' +
          '<span>' + esc(t('setup.apps.listen', 'Let other computers on my network use it')) + '</span></label>';
      }
      if (isComfy && found.kind === 'desktop' && apps.canInstallComfy) {
        return noAnswer + startRow + '<p class="su-hint">' + esc(t('setup.apps.preferPortable',
          'The portable build is the one Nomad Studio works best with.')) + '</p>' + comfyInstallForm(apps, true);
      }
      return noAnswer + startRow;
    }
    if (!isComfy) {
      return '<label class="su-label" for="su-lms-dir">' + esc(t('setup.apps.downloadTo', 'Download LM Studio to')) + '</label>' +
        '<div class="su-row"><input class="su-input" id="su-lms-dir" value="' + esc(apps.suggestedDir || '') + '" spellcheck="false">' +
        '<button type="button" class="su-btn su-btn-install" id="su-install-lms">' + esc(t('setup.apps.installLms', 'Install LM Studio')) + '</button></div>' +
        '<p class="su-hint">' + esc(t('setup.apps.lmsNote', 'Its installer opens by itself; we wait for you here.')) + '</p>';
    }
    if (!apps.canInstallComfy) return '';
    return comfyInstallForm(apps, false);
  }

  function comfyInstallForm(apps, compact) {
    var noGpu = apps.gpuVendor !== 'nvidia' && apps.gpuVendor !== 'amd';
    return (noGpu && !compact ? '<p class="su-hint">' + esc(t('setup.apps.noGpu', 'No NVIDIA or AMD card found here: generating on this computer would be slow.')) + '</p>' : '') +
      '<label class="su-label" for="su-comfy-dir">' + esc(t('setup.apps.installIn', 'Install ComfyUI in')) + '</label>' +
      '<div class="su-row"><input class="su-input" id="su-comfy-dir" value="' + esc(apps.suggestedDir || '') + '" spellcheck="false">' +
      '<button type="button" class="su-btn su-btn-install" id="su-install-comfy">' + esc(t('setup.apps.installComfy', 'Install ComfyUI')) + '</button></div>' +
      '<p class="su-hint">' + esc(t('setup.apps.installNote', 'About 2 GB from the official ComfyUI release.')) + '</p>';
  }

  function serverHelp(kind) {
    var isComfy = kind === 'comfy';
    var steps = isComfy
      ? [t('setup.network.sameNetwork', 'Both computers must be on the same network.'),
         t('setup.network.comfyListen', 'On that computer, start ComfyUI with --listen 0.0.0.0 (in ComfyUI Desktop, set the server listen address to 0.0.0.0).'),
         t('setup.network.privateFirewall', 'In Windows on that computer, set the network as Private and allow the program in the firewall when asked.'),
         t('setup.network.typeAddress', 'Type its address here, e.g. http://192.168.1.20:{port}, or search your network again.', { port: 8188 })]
      : [t('setup.network.sameNetwork', 'Both computers must be on the same network.'),
         t('setup.network.lmsServe', 'On that computer, open LM Studio › Developer and turn on "Serve on Local Network".'),
         t('setup.network.privateFirewall', 'In Windows on that computer, set the network as Private and allow the program in the firewall when asked.'),
         t('setup.network.typeAddress', 'Type its address here, e.g. http://192.168.1.20:{port}, or search your network again.', { port: 1234 })];
    return '<details class="su-details su-details-inline"><summary>' +
      esc(isComfy ? t('setup.network.remoteComfy', 'Is ComfyUI on another computer?') : t('setup.network.remoteLms', 'Is LM Studio on another computer?')) +
      '</summary><ol>' + steps.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ol></details>';
  }

  function serverStep(kind) {
    var isComfy = kind === 'comfy';
    var idk = isComfy ? 'comfy' : 'lms';  // element ids: su-comfy-url, su-lms-url
    var check = isComfy ? S.comfy : S.lms;
    var checking = isComfy ? S.comfyBusy : S.lmsBusy;
    var url = (isComfy ? S.settings.comfyApiUrl : S.settings.lmStudioApiUrl) || (isComfy ? 'http://127.0.0.1:8188' : 'http://127.0.0.1:1234');
    var connected = !!(check && check.ok);
    var name = serverName(kind);
    var list = serverList(kind);
    var html = '';
    var showInstall = false;

    if (checking || (S.discoveryBusy && !connected)) {
      html += statusBox('busy', esc(checking
        ? t('setup.network.checking', 'Checking {name} at {url}…', { name: name, url: url })
        : t('setup.network.searchingFor', 'Looking for {name} on this computer and on your network…', { name: name })));
    } else if (connected) {
      var gpu = isComfy ? (check.gpus || [])[0] : null;
      html += statusBox('ok', '<strong>' + esc(t('setup.network.connectedTo', 'Connected to {name}', { name: name })) + '</strong> · ' + esc(url) +
        (isComfy && check.version ? '<br>' + esc(t('setup.comfy.version', 'version {v}', { v: check.version })) : '') +
        (gpu ? '<br>' + esc(t('setup.comfy.gpu', 'GPU: {name} · {vram} of video memory', { name: gpu.name, vram: bytes(gpu.vramTotal) })) : '') +
        (!isComfy && check.models != null ? ' · ' + esc(t('setup.lms.models', '{n} models available', { n: check.models })) : '') +
        (check.isLocal === false ? '<br>' + esc(t('setup.network.otherComputerNote', 'It runs on another computer on your network.')) : ''));
    } else if (check && !list.length) {
      showInstall = true;
      html += statusBox('warn', '<strong>' + esc(t('setup.network.notFound', '{name} was not found', { name: name })) + '</strong><br>' +
        esc(isComfy
          ? t('setup.comfy.noneHelp', 'Start ComfyUI and search again, or type its address. You can continue without it: the engines are installed anyway, and you can connect later in Settings.')
          : t('setup.lms.noneHelp', 'It is optional: without it you can still generate images, but the flows that write prompts or describe images will not work.')));
    }

    if (list.length && !checking) {
      var others = connected ? list.filter(function (f) { return f.url !== url; }) : list;
      if (others.length) {
        html += '<div class="su-label">' + esc(connected
          ? t('setup.network.alsoFound', 'Also found')
          : t('setup.network.choose', 'Choose your {name}', { name: name })) + '</div>' + serverRows(kind, connected ? others : list, url);
      }
    }

    // Address box: only when asked for, or when there is nothing to choose.
    var manual = S.manual[kind] || (!!check && !connected && !list.length && !checking);
    if (manual) {
      html += '<label class="su-label" for="su-' + idk + '-url">' + esc(isComfy ? t('setup.comfy.urlLabel', 'ComfyUI address') : t('setup.lms.urlLabel', 'LM Studio address')) + '</label>' +
        '<div class="su-row"><input class="su-input" id="su-' + idk + '-url" value="' + esc(url) + '" spellcheck="false">' +
        '<button type="button" class="su-btn su-btn-ghost" id="su-' + idk + '-check"' + (checking ? ' disabled' : '') + '>' +
        esc(t('setup.common.check', 'Check')) + '</button></div>';
    }

    if (showInstall) html += installBlock(kind);
    html += '<div class="su-actions-row">' +
      '<button type="button" class="su-linkbtn" id="su-discover"' + (S.discoveryBusy ? ' disabled' : '') + '>' +
      esc(t('setup.network.searchAgain', 'Search again')) + '</button>' +
      (manual ? '' : '<button type="button" class="su-linkbtn" data-manual="' + kind + '">' + esc(t('setup.network.manual', 'Enter another address')) + '</button>') +
      serverHelp(kind) + '</div>';
    return html;
  }

  function viewComfy() {
    return '<h2 class="su-h2">' + esc(t('setup.comfy.title', 'Connect to ComfyUI')) + '</h2>' +
      '<p class="su-lead">' + esc(t('setup.comfy.lead', 'ComfyUI is the engine that generates the images.')) + '</p>' +
      serverStep('comfy');
  }

  function viewLms() {
    return '<h2 class="su-h2">' + esc(t('setup.lms.title', 'Connect to LM Studio')) + ' <span class="su-tag">' + esc(t('setup.common.optional', 'Optional')) + '</span></h2>' +
      '<p class="su-lead">' + esc(t('setup.lms.lead', 'LM Studio runs local language and vision models. Some flows use it to improve prompts or describe images.')) + '</p>' +
      serverStep('lmstudio');
  }

  function viewModels() {
    var head = '<h2 class="su-h2">' + esc(t('setup.models.title', 'Language models')) + ' <span class="su-tag">' + esc(t('setup.common.optional', 'Optional')) + '</span></h2>' +
      '<p class="su-lead">' + esc(t('setup.models.lead', 'Some flows use a model in LM Studio to write prompts and describe images. None is required, but we recommend having at least one. These are the four we measured.')) + '</p>';
    if (!S.lms || !S.lms.ok) {
      return head + statusBox('warn', esc(t('setup.models.needLms', 'LM Studio has to be running to check and install models. Go back to the LM Studio step, or skip this for now.')));
    }
    if (S.llmBusy && !S.llm) return head + statusBox('busy', esc(t('setup.models.detecting', 'Looking for models in LM Studio…')));
    if (S.llmError) return head + statusBox('bad', esc(S.llmError)) + '<div class="su-engine-actions"><button type="button" class="su-btn su-btn-ghost" id="su-llm-retry">' + esc(t('setup.common.retry', 'Retry')) + '</button></div>';
    if (!S.llm) return head;

    var models = S.llm.models || [];
    var installed = models.filter(function (m) { return m.installedKey; }).length;
    var recId = recommendedLlmId();
    var summary = installed
      ? statusBox('ok', esc(t('setup.models.summary', '{n} of {total} recommended models installed.', { n: installed, total: models.length })))
      : statusBox('warn', esc(t('setup.models.none', 'None of the recommended models is installed. We recommend installing at least one.')));

    var cards = models.map(function (m) {
      var job = S.llmJobs[m.id];
      var isPrompt = m.installedKey && S.settings.lmStudioPromptModel === m.installedKey;
      var isVision = m.installedKey && S.settings.lmStudioVisionModel === m.installedKey;
      var badge = m.installedKey
        ? '<span class="su-badge su-badge-ready">' + esc(t('setup.engines.present', 'installed')) + '</span>'
        : (m.id === recId ? '<span class="su-rec">' + esc(t('setup.engines.recommended', 'Recommended')) + '</span>' : '');
      var actions = '';
      if (m.installedKey) {
        // Which model does what is chosen in the pill toggles above; the card
        // only shows it.
        actions = (isPrompt ? '<span class="su-tag su-tag-use">' + esc(t('setup.models.inUsePrompt', 'Writing prompts')) + '</span>' : '') +
          (isVision ? '<span class="su-tag su-tag-use">' + esc(t('setup.models.inUseVision', 'Describing images')) + '</span>' : '');
      } else if (job && (job.status === 'downloading' || job.status === 'starting' || job.status === 'paused')) {
        actions = '<span class="su-engine-note">' + esc(job.status === 'paused' ? t('setup.models.paused', 'Paused in LM Studio') : t('setup.models.downloading', 'Downloading… {pct}%', { pct: job.pct || 0 })) + '</span>' +
          '<span class="su-progress"><span style="width:' + (job.pct || 0) + '%"></span></span>';
      } else {
        actions = '<button type="button" class="su-btn su-btn-primary su-btn-small" data-llm-install="' + esc(m.id) + '"' + (PREVIEW ? ' disabled' : '') + '>' +
            esc(t('setup.models.install', 'Install ({size} GB)', { size: m.sizeGb })) + '</button>' +
          (PREVIEW ? '<span class="su-engine-note">' + esc(t('setup.preview.noDownloads', 'Downloads are disabled in preview.')) + '</span>' : '') +
          (job && job.status === 'failed' ? '<span class="su-engine-note">' + esc(job.error || '') + '</span>' : '');
      }
      return '<div class="su-engine su-llm is-open">' +
        '<div class="su-engine-head">' +
        '<span class="su-engine-name">' + esc(m.name) + ' <small>' + esc(m.quant) + '</small>' +
        '<br><span class="su-engine-sub">' + esc(t('setup.models.desc.' + m.id, '')) + '</span>' +
        '<br><span class="su-engine-sub">' + esc(t('setup.models.meta', '{size} GB on disk · comfortable on {vram} GB of video memory', { size: m.sizeGb, vram: m.vramGb })) + '</span></span>' +
        badge + '</div>' +
        (actions ? '<div class="su-engine-body"><div class="su-engine-actions">' + actions + '</div></div>' : '') + '</div>';
    }).join('');

    // Pill toggles (same look as Simple / Guided / Custom in the app) to pick
    // the writing and the vision model among the installed ones. A model set
    // earlier that is not one of the four recommended still shows up.
    function picker(role, label, eligible) {
      var key = role === 'vision' ? 'lmStudioVisionModel' : 'lmStudioPromptModel';
      var current = S.settings[key] || '';
      var options = eligible.map(function (m) { return { key: m.installedKey, label: m.name }; });
      if (current && !options.some(function (o) { return o.key === current; })) options.push({ key: current, label: current });
      if (!options.length) return '';
      return '<div class="su-picker"><div class="su-label">' + esc(label) + '</div>' +
        '<div class="su-mode-toggle" role="radiogroup" aria-label="' + esc(label) + '">' + options.map(function (o) {
          var on = o.key === current;
          return '<button type="button" class="su-mode-btn' + (on ? ' is-active' : '') + '" role="radio" aria-checked="' + on + '"' +
            ' data-llm-use="' + role + '" data-llm-key="' + esc(o.key) + '" title="' + esc(o.key) + '">' + esc(o.label) + '</button>';
        }).join('') + '</div></div>';
    }
    var installedModels = models.filter(function (m) { return m.installedKey; });
    var pickers = installedModels.length
      ? '<div class="su-pickers">' +
          picker('prompt', t('setup.models.pickPrompt', 'Model that writes the prompts'), installedModels) +
          picker('vision', t('setup.models.pickVision', 'Model that describes images'), installedModels.filter(function (m) { return m.vision !== false; })) +
        '</div>'
      : '';

    return head + summary + pickers + '<div class="su-engines">' + cards + '</div>' +
      '<p class="su-hint">' + esc(t('setup.models.bgHint', 'Downloads run inside LM Studio and keep going even if you close this page.')) + '</p>';
  }

  function engineFileRow(f) {
    var id = f.subfolder + '/' + f.filename;
    var dl = S.downloads[id];
    var size = f.url ? bytes(S.sizes[f.url]) : '';
    var right = f.present ? t('setup.engines.present', 'installed')
      : dl && dl.state === 'running' ? dl.pct + '%'
      : dl && dl.state === 'error' ? t('setup.engines.dlError', 'error')
      : f.url ? size : t('setup.engines.manual', 'manual');
    return '<li class="su-file' + (f.present || (dl && dl.state === 'done') ? ' is-present' : '') + '" title="' + esc(dl && dl.error || f.foundAt || id) + '">' +
      '<span class="su-file-mark" aria-hidden="true"></span>' +
      '<span class="su-file-name">' + esc(f.filename) + ' <small>' + esc(f.foundAt ? f.foundAt : id) + '</small></span>' +
      '<span class="su-file-size">' + esc(right) + '</span>' +
      (dl && dl.state === 'running' ? '<span class="su-progress"><span style="width:' + dl.pct + '%"></span></span>' : '') +
      '</li>';
  }

  function viewEngines() {
    var head = '<h2 class="su-h2">' + esc(t('setup.engines.title', 'Your image engines')) + '</h2>' +
      '<p class="su-lead">' + esc(t('setup.engines.lead', 'Each engine needs a few model files inside ComfyUI. We check which ones ComfyUI can already see, and you can install what is missing.')) + '</p>';
    if (!S.comfy || !S.comfy.ok) {
      return head + statusBox('warn', esc(t('setup.engines.needComfy', 'ComfyUI has to be running to check the engines. Go back to the ComfyUI step, or skip this for now.')));
    }
    if (S.enginesBusy) return head + statusBox('busy', esc(t('setup.engines.detecting', 'Looking for model files in ComfyUI…')));
    if (S.enginesError) return head + statusBox('bad', esc(S.enginesError)) + '<div class="su-engine-actions"><button type="button" class="su-btn su-btn-ghost" id="su-engines-retry">' + esc(t('setup.common.retry', 'Retry')) + '</button></div>';
    if (!S.engines) return head;

    var engines = S.engines.engines || [];
    // Empty install: engines come as packages, none installed yet.
    if (!engines.length) {
      return head + statusBox('ok', '<strong>' + esc(t('setup.engines.noneTitle', 'No engines installed yet')) + '</strong><br>' +
        esc(t('setup.engines.noneText', 'Engines are installed as packages. When you install one, this step checks whether ComfyUI already has its model files and installs what is missing.')));
    }
    var ready = engines.filter(function (e) { return e.status === 'ready'; }).length;
    // ComfyUI on another machine: its engines are detected and used through
    // the API, but model files can only be installed on that machine.
    var remote = S.engines.isLocal === false;

    var cards = engines.map(function (e) {
      var open = S.openEngine === e.id;
      var badge = { ready: t('setup.engines.ready', 'Ready'), incomplete: t('setup.engines.incomplete', 'Something missing'), not_installed: t('setup.engines.notInstalled', 'Not installed') }[e.status];
      var sub = e.installedOption
        ? t('setup.engines.variant', 'Variant: {v}', { v: (e.options.filter(function (o) { return o.key === e.installedOption; })[0] || {}).label || e.installedOption })
        : '';
      var body = '';
      if (open) {
        var files = neededFiles(e);
        var missing = files.filter(function (f) { return !f.present; });
        fetchSizes(missing);
        var opts = e.options.length ? '<div class="su-label">' + esc(t('setup.engines.chooseVariant', 'Variant')) + '</div><div class="su-options">' + e.options.map(function (o) {
          return '<button type="button" class="su-option' + (S.choice[e.id] === o.key ? ' is-selected' : '') + '" data-engine="' + esc(e.id) + '" data-option="' + esc(o.key) + '">' +
            (o.installed ? '<span class="su-dot-ok" aria-hidden="true"></span>' : '') + esc(o.label) +
            (o.key === e.recommendedOption && !e.installedOption ? ' <span class="su-rec">' + esc(t('setup.engines.recommended', 'Recommended')) + '</span>' : '') +
            '</button>';
        }).join('') + '</div>' +
          (!e.installedOption && S.comfy.gpus && S.comfy.gpus[0] ? '<p class="su-hint">' + esc(t('setup.engines.recHint', 'Recommended for your {gpu} ({vram}). Lighter variants use less video memory; heavier ones keep more quality.', { gpu: S.comfy.gpus[0].name, vram: bytes(S.comfy.gpus[0].vramTotal) })) + '</p>' : '') : '';
        var total = missing.reduce(function (acc, f) { return acc + (f.url && S.sizes[f.url] ? S.sizes[f.url] : 0); }, 0);
        var manual = missing.filter(function (f) { return !f.url; });
        var canInstall = missing.some(function (f) { return f.url; });
        var folderOk = !!S.settings.comfyModelsFolder && !(S.folderCheck && S.folderCheck.ok === false);
        body = '<div class="su-engine-body">' + opts +
          '<div class="su-label">' + esc(t('setup.engines.files', 'Files')) + '</div><ul class="su-files">' + files.map(engineFileRow).join('') + '</ul>' +
          (manual.length ? '<p class="su-hint">' + esc(t('setup.engines.manualHint', 'Files marked "manual" have no download address yet: place them yourself in the folder shown next to each one.')) + '</p>' : '') +
          (canInstall && remote ? '<p class="su-hint">' + esc(t('setup.engines.remoteInstall', 'Install the missing files on the computer where ComfyUI runs, then check again.')) + '</p>' : '') +
          (canInstall && !remote ? '<div class="su-engine-actions">' +
            '<button type="button" class="su-btn su-btn-primary su-btn-small" data-install="' + esc(e.id) + '"' + (PREVIEW || S.downloading || !folderOk ? ' disabled' : '') + '>' +
            esc(total ? t('setup.engines.installSize', 'Install ({size})', { size: bytes(total) }) : t('setup.engines.install', 'Install')) + '</button>' +
            (PREVIEW ? '<span class="su-engine-note">' + esc(t('setup.preview.noDownloads', 'Downloads are disabled in preview.')) + '</span>'
              : !folderOk ? '<span class="su-engine-note">' + esc(t('setup.engines.needFolder', 'Set the ComfyUI models folder below first.')) + '</span>'
              : S.freeBytes != null && total > S.freeBytes ? '<span class="su-engine-note">' + esc(t('setup.engines.noSpace', 'Not enough free space ({free} free).', { free: bytes(S.freeBytes) })) + '</span>' : '') +
            '</div>' : '') +
          '</div>';
      }
      return '<div class="su-engine' + (open ? ' is-open' : '') + '">' +
        '<button type="button" class="su-engine-head" data-toggle-engine="' + esc(e.id) + '" aria-expanded="' + open + '">' +
        '<span class="su-engine-name">' + esc(e.name) + (sub ? '<br><span class="su-engine-sub">' + esc(sub) + '</span>' : '') + '</span>' +
        '<span class="su-badge su-badge-' + e.status + '">' + esc(badge) + '</span>' +
        '<span class="su-engine-chevron" aria-hidden="true">›</span></button>' + body + '</div>';
    }).join('');

    var anyMissing = engines.some(function (e) { return e.status !== 'ready'; });
    var folderBox = '';
    if (!remote && anyMissing) suggestModelsFolder();
    if (!remote && (anyMissing || S.openEngine)) {
      var fc = S.folderCheck;
      var fstatus = !fc ? '' : fc.busy ? statusBox('busy', esc(t('setup.common.checking', 'Checking…')))
        : fc.ok ? statusBox('ok', esc(fc.reason === 'comfy_has_no_models'
            ? t('setup.folder.okEmpty', 'Downloads go to this folder of your ComfyUI.')
            : t('setup.folder.ok', 'This is the folder ComfyUI uses ({n} of {m} files found).', { n: fc.matched, m: fc.checked })) + (fc.freeBytes != null ? ' · ' + esc(t('setup.folder.free', '{free} free', { free: bytes(fc.freeBytes) })) : ''))
        : statusBox('bad', esc(t('setup.folder.bad', 'ComfyUI does not read its models from this folder. Choose the "models" folder inside your ComfyUI installation.')));
      folderBox = '<div class="su-folder-box"><label class="su-label" for="su-models-folder">' + esc(t('setup.folder.label', 'ComfyUI models folder (only needed to download)')) + '</label>' +
        '<div class="su-row"><input class="su-input" id="su-models-folder" value="' + esc(S.draftModelsFolder != null ? S.draftModelsFolder : (S.settings.comfyModelsFolder || '')) + '" placeholder="C:\\ComfyUI\\models" spellcheck="false">' +
        '<button type="button" class="su-btn su-btn-ghost" id="su-models-browse"' + (PREVIEW ? ' disabled' : '') + '>' + esc(t('setup.common.browse', 'Browse')) + '</button>' +
        '<button type="button" class="su-btn su-btn-ghost" id="su-models-validate">' + esc(t('setup.common.check', 'Check')) + '</button></div>' + fstatus + '</div>';
    }

    var remoteBox = remote
      ? statusBox('ok', esc(t('setup.engines.remote', 'ComfyUI runs on another computer ({host}). Nomad Studio uses its engines from here; files are installed on that computer.', { host: S.engines.comfyHost || S.settings.comfyApiUrl || '' })))
      : '';
    return head + statusBox(ready === engines.length ? 'ok' : 'warn',
      esc(t('setup.engines.summary', '{ready} of {total} engines ready to use.', { ready: ready, total: engines.length }))) +
      remoteBox + '<div class="su-engines">' + cards + '</div>' + folderBox + (remote && anyMissing ? '<div class="su-engine-actions"><button type="button" class="su-btn su-btn-ghost" id="su-engines-retry">' + esc(t('setup.engines.checkAgain', 'Check again')) + '</button></div>' : '');
  }

  function viewData() {
    return '<h2 class="su-h2">' + esc(t('setup.data.title', 'Where your data lives')) + '</h2>' +
      '<p class="su-lead">' + esc(t('setup.data.lead', 'Profiles, Sessions, settings and installed packages are kept in one folder of your own, outside the program.')) + '</p>' +
      '<label class="su-label">' + esc(t('setup.data.label', 'Data folder')) + '</label>' +
      '<div class="su-status"><span class="su-status-icon" aria-hidden="true"></span><div><span class="su-code">' + esc(S.dataDir.path || '') + '</span></div></div>' +
      '<p class="su-hint">' + esc(t('setup.data.outsideNote', 'Because it is outside the program folder, you can delete or replace Nomad Studio — when you update it, for instance — without losing anything. You can also copy this folder to back it up.')) + '</p>';
  }

  function viewOutput() {
    var box = '';
    var oc = S.outputCheck;
    if (oc && oc.busy) box = statusBox('busy', esc(t('setup.common.checking', 'Checking…')));
    else if (oc && oc.ok) box = statusBox('ok', esc(t('setup.output.ok', 'Folder ready: Nomad Studio can write to it.')));
    else if (oc) box = statusBox('bad', esc(t('setup.output.bad', 'Nomad Studio cannot write to this folder: {error}', { error: oc.error || '' })));
    var warn = '';
    if (S.outputWarning) {
      var msg = S.outputWarning === 'protected'
        ? t('setup.output.warnProtected', 'This looks like a Documents, Pictures or Desktop folder. Some antivirus protection blocks programs from writing there; if generations fail to save, choose another folder.')
        : t('setup.output.warnSync', 'This folder is synced to the cloud. Every image will be uploaded, which uses bandwidth and can lock files while they sync. A local folder is recommended.');
      warn = statusBox('warn', esc(msg));
    }
    return '<h2 class="su-h2">' + esc(t('setup.output.title', 'Where to save your images')) + '</h2>' +
      '<p class="su-lead">' + esc(t('setup.output.lead', 'Every image you generate is saved here, in a sub-folder per profile.')) + '</p>' +
      '<label class="su-label" for="su-output">' + esc(t('setup.output.label', 'Image folder')) + '</label>' +
      '<div class="su-row"><input class="su-input" id="su-output" value="' + esc(S.settings.outputDir || '') + '" placeholder="' + esc(S.suggestedOutputDir || '') + '" spellcheck="false">' +
      '<button type="button" class="su-btn su-btn-ghost" id="su-output-browse">' + esc(t('setup.common.browse', 'Browse')) + '</button>' +
      '<button type="button" class="su-btn su-btn-ghost" id="su-output-check">' + esc(t('setup.common.check', 'Check')) + '</button></div>' +
      box + warn;
  }

  function viewFormat() {
    var fmt = S.settings.imageFormat || 'png';
    function choice(value, title, text) {
      return '<label class="su-choice' + (fmt === value ? ' is-selected' : '') + '"><input type="radio" name="su-format" value="' + value + '"' + (fmt === value ? ' checked' : '') + '>' +
        '<span><span class="su-choice-title">' + title + '</span><span class="su-choice-text">' + text + '</span></span></label>';
    }
    return '<h2 class="su-h2">' + esc(t('setup.format.title', 'How should we save your images?')) + ' <span class="su-tag su-tag-soon">' + esc(t('setup.common.soon', 'Coming soon')) + '</span></h2>' +
      '<p class="su-lead">' + esc(t('setup.format.soonNote', 'Your choice is saved now. Images keep being saved as PNG until WebP support is finished.')) + '</p>' +
      '<div class="su-choices">' +
      choice('png', esc(t('setup.format.pngTitle', 'PNG')), esc(t('setup.format.pngText', 'Keeps every pixel exactly, with no loss.'))) +
      choice('webp', esc(t('setup.format.webpTitle', 'WebP')), esc(t('setup.format.webpText', 'If you need to save space, use this option.'))) +
      '</div>' +
      '<details class="su-details"><summary>' + esc(t('setup.format.lossTitle', 'What does "loss" mean?')) + '</summary><ul>' +
      '<li>' + esc(t('setup.format.loss1', 'Very smooth gradients (skies, plain backgrounds) can show slight bands.')) + '</li>' +
      '<li>' + esc(t('setup.format.loss2', 'Sharp edges and fine detail (text, thin lines, pixel art) can look a little softer.')) + '</li>' +
      '<li>' + esc(t('setup.format.loss3', 'Film grain and noise can get smoothed out.')) + '</li>' +
      '<li>' + esc(t('setup.format.loss4', 'Loss cannot be undone, and it adds up if the same image is retouched and saved many times. You can choose PNG for a single generation in Advanced.')) + '</li>' +
      '</ul></details>' +
      '<p class="su-hint">' + esc(t('setup.format.changeLater', 'You can change this in Settings at any time. Images already saved are not converted.')) + '</p>' +
      '<label class="su-check"><input type="checkbox" id="su-skip-copy"' + (S.settings.skipComfyOutputCopy === true ? ' checked' : '') + '>' +
      '<span><strong>' + esc(t('setup.format.saveSpace', 'Save space: do not keep a copy in the ComfyUI folder')) + '</strong>' +
      '<br><span class="su-hint">' + esc(t('setup.format.saveSpaceHint', 'Nomad Studio already saves every image in your own user folder, so ComfyUI does not need to keep a second copy in its output folder.')) + '</span></span></label>';
  }

  function viewProfile() {
    var p = S.profile;
    var existing = S.viewers > 0
      ? statusBox('ok', esc(t('setup.profile.existing', 'You already have {n} profile(s). You can create another one or continue.', { n: S.viewers })))
      : '';
    return '<h2 class="su-h2">' + esc(t('setup.profile.title', 'Create your profile')) + '</h2>' +
      '<p class="su-lead">' + esc(t('setup.profile.lead', 'Each profile has its own images, history and Sessions.')) + '</p>' + existing +
      (PREVIEW ? statusBox('warn', esc(t('setup.preview.noProfile', 'Profiles are not created in preview.'))) : '') +
      '<label class="su-label" for="su-profile-name">' + esc(t('setup.profile.name', 'Name')) + '</label>' +
      '<input class="su-input" id="su-profile-name" maxlength="20" value="' + esc(p.name) + '">' +
      '<div class="su-label">' + esc(t('setup.profile.avatar', 'Avatar')) + '</div>' +
      '<div class="su-avatars">' + AVATARS.map(function (a) {
        return '<button type="button" class="su-avatar' + (p.avatar === a ? ' is-selected' : '') + '" data-avatar="' + esc(a) + '" aria-label="' + esc(a) + '"><img src="' + esc(AVATAR_BASE + a) + '" alt="" loading="lazy"></button>';
      }).join('') + '</div>' +
      '<label class="su-check"><input type="checkbox" id="su-pin-on"' + (p.pinOn ? ' checked' : '') + '><span>' + esc(t('setup.profile.pin', 'Protect with a 4-digit PIN')) + '</span></label>' +
      (p.pinOn ? '<input class="su-input" id="su-pin" type="password" inputmode="numeric" maxlength="4" value="' + esc(p.pin) + '" style="margin-top:10px;max-width:180px">' : '') +
      (p.error ? statusBox('bad', esc(p.error)) : '');
  }

  function viewDone() {
    var engines = S.engines ? S.engines.engines : null;
    var ready = engines ? engines.filter(function (e) { return e.status === 'ready'; }).length : null;
    function row(label, value) { return '<li><span>' + esc(label) + '</span><span>' + value + '</span></li>'; }
    var fmt = S.settings.imageFormat === 'webp' ? 'WebP' : 'PNG';
    return '<h2 class="su-h2">' + esc(t('setup.done.title', 'All set')) + '</h2>' +
      '<p class="su-lead">' + esc(PREVIEW ? t('setup.done.previewLead', 'This is the end of the preview. Nothing was saved.') : t('setup.done.lead', 'Here is a summary. You can change any of it later in Settings.')) + '</p>' +
      '<ul class="su-summary">' +
      row(t('setup.steps.comfy', 'ComfyUI'), S.comfy && S.comfy.ok ? esc(t('setup.done.connected', 'Connected')) + ' · ' + esc(S.settings.comfyApiUrl || '') : esc(t('setup.done.notConnected', 'Not connected'))) +
      row(t('setup.steps.engines', 'Engines'), ready == null ? esc(t('setup.done.notChecked', 'Not checked'))
        : !engines.length ? esc(t('setup.engines.noneTitle', 'No engines installed yet'))
        : esc(t('setup.engines.summary', '{ready} of {total} engines ready to use.', { ready: ready, total: engines.length }))) +
      row(t('setup.steps.lmstudio', 'LM Studio'), S.lms && S.lms.ok ? esc(t('setup.done.connected', 'Connected')) : esc(t('setup.done.notConnected', 'Not connected'))) +
      row(t('setup.steps.models', 'Models'), !S.llm ? esc(t('setup.done.notChecked', 'Not checked'))
        : esc(t('setup.models.summary', '{n} of {total} recommended models installed.', { n: S.llm.models.filter(function (m) { return m.installedKey; }).length, total: S.llm.models.length }))) +
      row(t('setup.steps.output', 'Image folder'), '<span class="su-code">' + esc(S.settings.outputDir || '—') + '</span>') +
      row(t('setup.steps.format', 'Image format'), esc(fmt)) +
      '</ul>' +
      (S.downloading ? statusBox('busy', esc(t('setup.done.downloading', 'Downloads are still running. Keep this page open until they finish.'))) : '');
  }

  var VIEWS = { language: viewLanguage, comfy: viewComfy, lmstudio: viewLms, models: viewModels, engines: viewEngines, data: viewData, output: viewOutput, format: viewFormat, profile: viewProfile, done: viewDone };

  // ── Render & events ───────────────────────────────────────────────────────
  function render() {
    stepsEl.innerHTML = STEPS.map(function (s, i) {
      var n = i + 1;
      var cls = 'su-step' + (n === S.step ? ' is-current' : '') + (n < S.maxReached || (n < S.step) ? ' is-done' : '') + (n <= S.maxReached ? ' is-reachable' : '');
      return '<button type="button" class="' + cls + '" data-goto="' + n + '"' + (n <= S.maxReached ? '' : ' tabindex="-1"') + '>' +
        '<span class="su-step-num">' + n + '</span><span class="su-step-label">' + esc(t(s.key, s.fb)) + '</span></button>';
    }).join('');

    var step = current();
    // Keep what the user is typing: re-render replaces the inputs.
    var focusId = document.activeElement && document.activeElement.id;
    var caret = document.activeElement && typeof document.activeElement.selectionStart === 'number' ? document.activeElement.selectionStart : null;
    bodyEl.innerHTML = VIEWS[step.id]();
    if (focusId) {
      var el = document.getElementById(focusId);
      if (el && typeof el.focus === 'function' && bodyEl.contains(el)) {
        el.focus();
        if (caret != null && typeof el.setSelectionRange === 'function') { try { el.setSelectionRange(caret, caret); } catch (e) { /* not text */ } }
      }
    }

    backBtn.hidden = S.step === 1;
    skipBtn.hidden = !step.optional;
    nextBtn.textContent = step.id === 'done'
      ? (PREVIEW ? t('setup.preview.close', 'Close preview') : t('setup.nav.start', 'Start'))
      : t('setup.nav.next', 'Next');
    nextBtn.disabled = step.id === 'done' && S.downloading;
    backBtn.textContent = t('setup.nav.back', 'Back');
    skipBtn.textContent = t('setup.nav.skip', 'Skip');
  }

  function readInputs() {
    var step = current().id;
    if (step === 'comfy') {
      var c = document.getElementById('su-comfy-url');
      if (c) S.settings.comfyApiUrl = c.value.trim();
    } else if (step === 'lmstudio') {
      var l = document.getElementById('su-lms-url');
      if (l) S.settings.lmStudioApiUrl = l.value.trim();
    } else if (step === 'output') {
      var o = document.getElementById('su-output');
      if (o) S.settings.outputDir = o.value.trim();
    } else if (step === 'profile') {
      var n = document.getElementById('su-profile-name');
      var pin = document.getElementById('su-pin');
      if (n) S.profile.name = n.value;
      if (pin) S.profile.pin = pin.value;
    }
  }

  function enter(n) {
    S.step = Math.max(1, Math.min(STEPS.length, n));
    S.maxReached = Math.max(S.maxReached, S.step);
    if (!PREVIEW && current().id !== 'done') save({ wizardStep: S.step });
    var id = current().id;
    // The saved address is checked and, if it does not answer, the network is
    // searched right away (checkComfy/checkLms call autoDiscover on failure).
    if (id === 'comfy' || id === 'lmstudio') loadApps();
    if (id === 'comfy' && !S.comfy && !S.comfyBusy) checkComfy();
    if (id === 'lmstudio' && !S.lms && !S.lmsBusy) checkLms();
    // Engines and the summary need ComfyUI checked first: after a reload in
    // the middle of the wizard nothing is checked yet, and the summary said
    // "Not connected" with ComfyUI running (found on a clean Windows VM).
    if ((id === 'engines' || id === 'done') && !S.engines && !S.enginesBusy) {
      if (S.comfy && S.comfy.ok) detectEngines();
      else if (!S.comfy && !S.comfyBusy) checkComfy().then(function () { if (S.comfy && S.comfy.ok) detectEngines(); });
    }
    if (id === 'done' && !S.lms && !S.lmsBusy) checkLms().then(function () { if (S.lms && S.lms.ok && !S.llm) detectLlm(); });
    else if (id === 'done' && S.lms && S.lms.ok && !S.llm && !S.llmBusy) detectLlm();
    // Pre-fill the proposed image folder (checked and saved on Next, as usual).
    if (id === 'output' && !S.settings.outputDir && S.suggestedOutputDir) S.settings.outputDir = S.suggestedOutputDir;
    if (id === 'models' && !S.llm && !S.llmBusy) {
      if (S.lms && S.lms.ok) detectLlm();
      else if (!S.lms && !S.lmsBusy) checkLms().then(function () { if (S.lms && S.lms.ok) detectLlm(); });
    }
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function checkOutput() {
    var input = document.getElementById('su-output');
    var dir = (input ? input.value : S.settings.outputDir || '').trim();
    S.settings.outputDir = dir;
    if (!dir) { S.outputCheck = { ok: false, error: t('setup.output.empty', 'choose a folder first') }; render(); return Promise.resolve(false); }
    S.outputCheck = { busy: true }; render();
    return Promise.all([
      api('POST', '/api/models/settings/output-dir/test', { outputDir: dir }),
      api('POST', '/api/setup/check/output-dir', { outputDir: dir })
    ]).then(function (res) {
      S.outputCheck = res[0];
      S.outputWarning = res[1] && res[1].warning;
      render();
      return !!res[0].ok;
    });
  }

  function next() {
    readInputs();
    var id = current().id;
    if (id === 'output') {
      return checkOutput().then(function (ok) {
        if (!ok && !PREVIEW) return;
        return save({ outputDir: S.settings.outputDir }).then(function () { enter(S.step + 1); });
      });
    }
    if (id === 'profile') {
      var p = S.profile;
      if (PREVIEW || (!p.name.trim() && S.viewers > 0)) return enter(S.step + 1);
      if (!p.name.trim() || !p.avatar) { p.error = t('setup.profile.needNameAvatar', 'Write a name and choose an avatar.'); return render(); }
      if (p.pinOn && !/^\d{4}$/.test(p.pin)) { p.error = t('setup.profile.badPin', 'The PIN must be 4 digits.'); return render(); }
      p.error = '';
      return api('POST', '/api/viewers', { name: p.name.trim(), avatar: p.avatar, pin: p.pinOn ? p.pin : null }).then(function (res) {
        if (!res.ok) { p.error = res.error || 'error'; return render(); }
        S.viewers += 1;
        S.profile = { name: '', avatar: '', pinOn: false, pin: '', error: '' };
        enter(S.step + 1);
      });
    }
    if (id === 'done') {
      if (PREVIEW) { window.location.href = root.dataset.settingsUrl || '/settings'; return; }
      return save({ setupCompleted: true, wizardStep: 1 }).then(function () {
        window.location.href = root.dataset.nextUrl || '/who';
      });
    }
    enter(S.step + 1);
  }

  nextBtn.addEventListener('click', next);
  backBtn.addEventListener('click', function () { readInputs(); enter(S.step - 1); });
  skipBtn.addEventListener('click', function () { readInputs(); enter(S.step + 1); });

  stepsEl.addEventListener('click', function (e) {
    var b = e.target.closest('[data-goto]');
    if (!b) return;
    var n = parseInt(b.dataset.goto, 10);
    if (n <= S.maxReached) { readInputs(); enter(n); }
  });

  bodyEl.addEventListener('click', function (e) {
    var el;
    if ((el = e.target.closest('[data-lang]'))) {
      if (window.NomadI18n) window.NomadI18n.setLanguage(el.dataset.lang);
      return render();
    }
    if (e.target.closest('#su-discover')) return runDiscovery();
    if ((el = e.target.closest('[data-use-found]'))) return useFound(el.dataset.useFound, el.dataset.url);
    if ((el = e.target.closest('[data-manual]'))) {
      S.manual[el.dataset.manual] = true;
      render();
      var input = document.getElementById(el.dataset.manual === 'comfy' ? 'su-comfy-url' : 'su-lms-url');
      if (input) input.focus();
      return;
    }
    if ((el = e.target.closest('[data-start-app]'))) return startApp(el.dataset.startApp);
    if (e.target.closest('#su-install-comfy')) return installApp('comfyui');
    if (e.target.closest('#su-install-lms')) return installApp('lmstudio');
    if (e.target.closest('#su-install-vc')) return installApp('vcredist');
    if (e.target.closest('#su-comfy-check')) return checkComfy();
    if (e.target.closest('#su-lms-check')) return checkLms();
    if (e.target.closest('#su-engines-retry')) return detectEngines();
    if (e.target.closest('#su-llm-retry')) return detectLlm();
    if ((el = e.target.closest('[data-llm-install]'))) return installLlm(el.dataset.llmInstall);
    if ((el = e.target.closest('[data-llm-use]'))) {
      var patch = {};
      patch[el.dataset.llmUse === 'vision' ? 'lmStudioVisionModel' : 'lmStudioPromptModel'] = el.dataset.llmKey;
      return save(patch).then(render);
    }
    if ((el = e.target.closest('[data-toggle-engine]'))) {
      S.openEngine = S.openEngine === el.dataset.toggleEngine ? null : el.dataset.toggleEngine;
      return render();
    }
    if ((el = e.target.closest('[data-option]'))) {
      S.choice[el.dataset.engine] = el.dataset.option;
      return render();
    }
    if ((el = e.target.closest('[data-install]'))) {
      var engine = (S.engines.engines || []).filter(function (x) { return x.id === el.dataset.install; })[0];
      if (engine) installEngine(engine);
      return;
    }
    if (e.target.closest('#su-models-validate')) return validateFolder();
    if (e.target.closest('#su-models-browse')) {
      return api('POST', '/api/models/settings/models-folder/browse', { current: S.settings.comfyModelsFolder || '' }).then(function (res) {
        if (res.ok && res.comfyModelsFolder) {
          S.settings.comfyModelsFolder = res.comfyModelsFolder;
          render();
          validateFolder();
        }
      });
    }
    if (e.target.closest('#su-output-browse')) {
      return api('POST', '/api/models/settings/output-dir/browse', { current: S.settings.outputDir || '' }).then(function (res) {
        if (res.ok && res.outputDir) { S.settings.outputDir = res.outputDir; render(); checkOutput(); }
      });
    }
    if (e.target.closest('#su-output-check')) return checkOutput();
    if ((el = e.target.closest('[data-avatar]'))) {
      readInputs();
      S.profile.avatar = el.dataset.avatar;
      return render();
    }
  });

  bodyEl.addEventListener('change', function (e) {
    if (e.target.id === 'su-comfy-listen') { S.comfyListen = e.target.checked; return; }
    if (e.target.id === 'su-skip-copy') return save({ skipComfyOutputCopy: e.target.checked });
    if (e.target.name === 'su-format') return save({ imageFormat: e.target.value }).then(render);
    if (e.target.id === 'su-pin-on') { readInputs(); S.profile.pinOn = e.target.checked; return render(); }
  });

  bodyEl.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    if (e.target.id === 'su-comfy-url') { e.preventDefault(); checkComfy(); }
    else if (e.target.id === 'su-lms-url') { e.preventDefault(); checkLms(); }
    else if (e.target.id === 'su-output') { e.preventDefault(); checkOutput(); }
    else if (e.target.id === 'su-models-folder') { e.preventDefault(); validateFolder(); }
  });

  // Keep typed values in state on every keystroke: the body is re-rendered
  // often (download progress, sizes arriving, language change) and would
  // otherwise reset a field to its last saved value mid-typing.
  bodyEl.addEventListener('input', function (e) {
    var id = e.target.id;
    if (id === 'su-profile-name') S.profile.name = e.target.value;
    else if (id === 'su-pin') S.profile.pin = e.target.value;
    else if (id === 'su-comfy-url') S.settings.comfyApiUrl = e.target.value;
    else if (id === 'su-lms-url') S.settings.lmStudioApiUrl = e.target.value;
    else if (id === 'su-output') S.settings.outputDir = e.target.value;
    else if (id === 'su-models-folder') S.draftModelsFolder = e.target.value;
  });

  // Strings arrive asynchronously (and again when the language changes).
  document.addEventListener('nomad-i18n-applied', render);

  window.addEventListener('beforeunload', function (e) {
    if (S.downloading) { e.preventDefault(); e.returnValue = ''; }
  });

  // ── Boot ──────────────────────────────────────────────────────────────────
  api('GET', '/api/setup/state').then(function (st) {
    S.settings = st.settings || {};
    S.viewers = st.viewers || 0;
    S.dataDir = st.dataDir || {};
    S.suggestedOutputDir = st.suggestedOutputDir || '';
    var startAt = (!PREVIEW && !st.setupCompleted && S.settings.wizardStep) ? S.settings.wizardStep : 1;
    S.maxReached = startAt;
    enter(startAt);
  }).catch(function () {
    bodyEl.innerHTML = statusBox('bad', esc(t('setup.loadError', 'Could not load the setup state. Is the Nomad Studio server running?')));
  });
})();
