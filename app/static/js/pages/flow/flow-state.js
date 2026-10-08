'use strict';
// Shared state: constants, DOM refs, flow/step/generation state

// Translates a literal English string sourced from a flow-JSON definition
// (app/instructions/flows/**/*.json — step `label`, field `label`/
// `placeholder`/`hint`) via window.NomadI18n.tField. Global (not a module),
// like everything else in this file — every flow-step-*.js/flow-render-*.js
// file loaded after this one can call tF(text) directly. Falls back to the
// original text unchanged (both if NomadI18n isn't loaded, and if the exact
// string isn't yet in the flowLabels table) — safe to wrap any render call.
function tF(text) {
  return window.NomadI18n ? window.NomadI18n.tField(text) : text;
}

// Parse a pending session from the history click (nomad_studio.js stores it
// in sessionStorage before navigating). Consumed once here so all step renderers
// can reference the same object without fighting over sessionStorage removal.
// Factored into a function (not just an IIFE) so FlowEngine.reset() can
// re-read a freshly-set 'oj-load-session' key when switching flows in place
// (session-native mount) — the original IIFE-only version could only ever
// consume this once, at the very first script load.
function _readPendingSession() {
  try {
    var raw = sessionStorage.getItem('oj-load-session');
    if (raw) {
      var sess = JSON.parse(raw);
      sessionStorage.removeItem('oj-load-session');
      if (sess && sess.data) return sess;
    }
  } catch (_) {
    // fall through to the reload-resume check below
  }

  // No fresh "Open from history" handoff — but if this exact tab already
  // resumed this flow from history earlier (its instanceId persisted in
  // sessionStorage by _resolveFlowInstanceId, which — unlike the one-shot
  // 'oj-load-session' key above — survives a reload), a plain F5 should
  // behave the same as reopening it from History, not silently drop back
  // to a blank instance. Re-synthesize an equivalent pending-session object
  // straight from the same localStorage history entry the History panel
  // itself reads, so every downstream consumer (prompt/image-picker/params
  // restore — see grep for _pendingSession) works unchanged.
  try {
    if (!_isPageReload()) return null;
    var rootEl = document.getElementById('nsc-flow-root');
    var currentFlowId = rootEl && rootEl.getAttribute ? rootEl.getAttribute('data-flow-id') : '';
    if (!currentFlowId) return null;
    var existingInstanceId = sessionStorage.getItem('ns-flow-instance-' + currentFlowId);
    if (!existingInstanceId) return null;
    var histRaw = localStorage.getItem('oj-create-sessions-history-v1');
    var histList = histRaw ? JSON.parse(histRaw) : [];
    var entry = Array.isArray(histList)
      ? histList.find(function (e) { return e && e.instanceId === existingInstanceId; })
      : null;
    if (!entry || !entry.data) return null;
    return { type: entry.type, label: entry.label, prompt: entry.prompt, data: entry.data, instanceId: entry.instanceId };
  } catch (_) {
    return null;
  }
}
var _pendingSession = _readPendingSession();

// Collect { type, label, prompt, data, instanceId } for the current flow
// instance — the same snapshot shape used both for the localStorage "recent
// sessions" list (saveSessionSnapshot, below) and for explicitly saving to
// Library (saveFlowInstanceToLibrary, further down).
function _collectFlowSnapshot() {
    // ── type: use the flow id directly (e.g. 'refine.upscale', 'mix.blend') ──
    var type = typeof fid !== 'undefined' ? fid : (
      (document.getElementById('nsc-flow-root') || {}).getAttribute
        ? (document.getElementById('nsc-flow-root').getAttribute('data-flow-id') || 'flow')
        : 'flow'
    );

    // ── images: grab from the sessionImages array populated by flow-generation ──
    // Each sessionImages entry carries its OWN prompt (set per-card in
    // addToFeed) — keep that alongside the flat url list, index-aligned, so
    // restoring from history can show each image's real prompt instead of
    // falling back to one shared prompt for every card.
    var _imgEntries = (typeof sessionImages !== 'undefined' ? sessionImages : [])
      .filter(function (e) { return e && (typeof e === 'string' || e.url); });
    var images = _imgEntries.map(function (e) { return typeof e === 'string' ? e : e.url; });
    var imagePrompts = _imgEntries.map(function (e) { return (e && typeof e === 'object' && e.prompt) || ''; });
    // Same idea for quantization + generation time: each image keeps its OWN
    // values (set at generation time in addToFeed) — using the single
    // "current UI selection" for every restored image is wrong the moment
    // more than one image in the session used a different quantization.
    var imageQuantizations = _imgEntries.map(function (e) { return (e && typeof e === 'object' && e.quantizationId) || ''; });
    var imageGenSeconds = _imgEntries.map(function (e) {
      return (e && typeof e === 'object' && typeof e.genSeconds === 'number') ? e.genSeconds : null;
    });

    // ── prompt: first non-empty text/textarea in the steps panel ──
    var prompt = '';
    if (typeof stepValues === 'object' && stepValues) {
      Object.keys(stepValues).some(function (sid) {
        var sv = stepValues[sid] || {};
        var p = sv.positive_prompt || sv.prompt || sv.prompt_text || sv.text || '';
        if (p) { prompt = String(p); return true; }
        return false;
      });
    }
    if (!prompt && typeof stepsEl !== 'undefined' && stepsEl) {
      var ta = stepsEl.querySelector('textarea');
      if (ta && ta.value) prompt = ta.value;
    }

    // ── label: breadcrumb or flowDef title ──
    var label = '';
    if (typeof breadcrumbEl !== 'undefined' && breadcrumbEl) {
      var last = breadcrumbEl.querySelector('li:last-child, .active, span:last-child');
      if (last) label = last.textContent.trim();
    }
    if (!label && typeof flowDef !== 'undefined' && flowDef) {
      label = flowDef.title || flowDef.label || '';
    }

    // Collect input images and subject so the session can be fully restored
    var data = { images: images, imagePrompts: imagePrompts, imageQuantizations: imageQuantizations, imageGenSeconds: imageGenSeconds };
    if (typeof stepValues === 'object' && stepValues) {
      var _sv1 = stepValues['image']   || {};
      var _sv2 = stepValues['image_2'] || {};
      if (_sv1.image_server_url || _sv1.image_data_url) data.image1 = _sv1.image_server_url || _sv1.image_data_url;
      if (_sv2.image_server_url || _sv2.image_data_url) data.image2 = _sv2.image_server_url || _sv2.image_data_url;
      if (_sv1.subject)        data.subject  = _sv1.subject;
      // Capture prompt text for restore (top-level prompt already set above,
      // but also store inside data for explicitness)
      if (prompt) data.prompt = prompt.trim();
    }

    // Capture aspect ratio / resolution / quality / seed / advanced overrides
    // so reopening this instance from history restores the exact generation
    // params (otherwise it silently falls back to defaults).
    //
    // Flows built on an ideogram_composer step (e.g. Ideogram Lettering) don't
    // have a plain prompt_input textarea holding the "real" prompt — the
    // composed JSON lives in that step's own state (ideogram_json /
    // transformed_text), set via its _fillFn. buildParamsSnapshot()'s generic
    // prompt-collection only looks at prompt_input steps and workflow_params
    // compose fields, so it never sees this — without surfacing it here,
    // reopening from history shows no prompt under the image (addToFeed has
    // nothing prompt-like in params) and "Apply parameters" has nothing to
    // feed back into the composer canvas either.
    var _composerExtra = null;
    if (typeof allSteps !== 'undefined' && Array.isArray(allSteps) && typeof getVal === 'function') {
      var _composerStep = allSteps.find(function (s) { return s && s.type === 'ideogram_composer'; });
      if (_composerStep) {
        var _composition = getVal(_composerStep.id, 'ideogram_json');
        var _transformed  = getVal(_composerStep.id, 'transformed_text');
        if (_composition || _transformed) {
          _composerExtra = {
            positive: _transformed || JSON.stringify(_composition),
            ideogramComposition: _composition || null,
          };
        }
      }
    }
    if (typeof buildParamsSnapshot === 'function') {
      data.params = buildParamsSnapshot(_composerExtra);
    }

    var instanceId = typeof flowInstanceId !== 'undefined' ? flowInstanceId : null;

    return { type: type, label: label || type, prompt: prompt.trim(), data: data, instanceId: instanceId };
}

// Save a session snapshot to localStorage so it shows up in the Nomad Studio
// history list. Works standalone on flow/refine/mix pages (no create/index.js needed).
function saveSessionSnapshot() {
  try {
    var snap = _collectFlowSnapshot();

    var SESS_KEY = typeof SESSIONS_KEY !== 'undefined' ? SESSIONS_KEY : 'oj-create-sessions-history-v1';
    var raw  = localStorage.getItem(SESS_KEY);
    var list = [];
    try { list = raw ? JSON.parse(raw) : []; } catch (_) { list = []; }

    // Every generation made without leaving this flow instance shares the same
    // instanceId — update that entry in place (refreshed prompt/params, images
    // merged so far) instead of piling up one history row per image.
    var existingIdx = snap.instanceId
      ? list.findIndex(function (e) { return e && e.instanceId === snap.instanceId; })
      : -1;

    // If every image in this session got deleted from the live feed, there's
    // nothing left to show — drop the entry entirely instead of keeping an
    // empty husk around (matches Album/History: they mirror the live feed,
    // including "the feed ended up empty").
    var _isEmpty = !Array.isArray(snap.data.images) || snap.data.images.length === 0;

    // A flow mounted inside a Session is recorded with that session's id, so
    // the History panel can fold all of its flows into one Session row
    // instead of listing each one loose (renderSessionsHistory in
    // nomad_studio.js).
    var _pending = (window.NomadSession && typeof window.NomadSession.getPending === 'function')
      ? window.NomadSession.getPending() : null;
    var _sessionId = (_pending && _pending.sessionId) || null;

    if (existingIdx !== -1) {
      if (_isEmpty) {
        list.splice(existingIdx, 1);
      } else {
        var prev = list[existingIdx];
        // snap.data.images already comes from the live sessionImages array,
        // which accumulates everything generated (or restored) in this tab and
        // correctly drops anything the user deleted from the feed (tombstoned
        // to null and filtered out by _collectFlowSnapshot). Previously this
        // merged in prev.data.images on top, which meant a deleted image kept
        // coming back forever — the old saved copy never got removed just
        // because the live list no longer had it. Trust the live list.
        var entry = Object.assign({}, prev, {
          label:  snap.label || prev.label,
          prompt: snap.prompt || prev.prompt,
          ts:     Date.now(),
          data:   snap.data,
          sessionId: _sessionId || prev.sessionId || null,
        });
        list.splice(existingIdx, 1);
        list.unshift(entry);
      }
    } else if (!_isEmpty) {
      var entry = {
        id:         Date.now(),
        instanceId: snap.instanceId,
        type:       snap.type,
        label:      snap.label,
        prompt:     snap.prompt,
        ts:         Date.now(),
        data:       snap.data,
        sessionId:  _sessionId
      };
      list.unshift(entry);
    }

    // No cap — History (recent panel) and Album (full archive) both read
    // this same list; History just slices to the most recent N for display,
    // it never truncates the underlying storage.
    localStorage.setItem(SESS_KEY, JSON.stringify(list));
  } catch (_) {}
}

// Explicitly save the current flow instance to the Library (persisted
// server-side, unlike the auto-tracked localStorage "recent sessions" list
// above — this only happens when the user clicks the Save button).
function saveFlowInstanceToLibrary() {
  var snap;
  try {
    snap = _collectFlowSnapshot();
  } catch (_) {
    return Promise.reject(new Error(tF('Could not read flow state')));
  }
  return fetch('/api/library/flows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type: snap.type, label: snap.label, prompt: snap.prompt, data: snap.data }),
  }).then(function (r) {
    if (!r.ok) throw new Error(tF('Save failed') + ' (' + r.status + ')');
    return r.json();
  });
}

var NS_MODE_KEY  = 'ns-ui-mode';
var SESSIONS_KEY = 'oj-create-sessions-history-v1';
var HISTORY_MAX  = 20;
// WORKFLOW_KEY/PARAMS_KEY/HISTORY_PFX depend on flowId — set inside
// flowResetState() below, not here (avoids computing them before flowId
// is known, and lets them update cleanly on FlowEngine.reset()).
var WORKFLOW_KEY, PARAMS_KEY, HISTORY_PFX;

// uhd targets ~2.36MP per ratio (vs. hd's ~1.3MP) — same "square the tier's
// round number, solve for the ratio, snap to /16" derivation as sd/md/hd
// (hd 1152² -> uhd's natural next step, 1536²), computed once and pasted in
// rather than derived at runtime since these never change.
var ASPECT_PRESETS = [
  { key: 'r1x2',  label: '1:2',  hint: 'Tall banners · phone lock screens',            sd: { w:  544, h: 1088 }, md: { w:  720, h: 1456 }, hd: { w:  816, h: 1632 }, uhd: { w: 1088, h: 2176 } },
  { key: 'r6x11', label: '6:11', hint: 'Near-full-height mobile wallpapers',           sd: { w:  560, h: 1040 }, md: { w:  752, h: 1392 }, hd: { w:  848, h: 1552 }, uhd: { w: 1136, h: 2080 } },
  { key: 'r9x16', label: '9:16', hint: 'TikTok · Instagram Stories/Reels · YouTube Shorts', sd: { w:  576, h: 1024 }, md: { w:  768, h: 1344 }, hd: { w:  864, h: 1536 }, uhd: { w: 1152, h: 2048 } },
  { key: 'r2x3',  label: '2:3',  hint: 'Pinterest pins · book covers',                sd: { w:  640, h:  960  }, md: { w:  832, h: 1216 }, hd: { w:  960, h: 1408 }, uhd: { w: 1248, h: 1888 } },
  { key: 'r3x4',  label: '3:4',  hint: 'Portrait prints · classic photo frame',        sd: { w:  672, h:  880  }, md: { w:  880, h: 1184 }, hd: { w:  992, h: 1328 }, uhd: { w: 1328, h: 1776 } },
  { key: 'r4x5',  label: '4:5',  hint: 'Instagram feed vertical · the current default for feed posts', sd: { w:  688, h:  864  }, md: { w:  912, h: 1152 }, hd: { w: 1024, h: 1280 }, uhd: { w: 1376, h: 1712 } },
  { key: 'r5x6',  label: '5:6',  hint: 'Slightly-tall portrait, close to square',      sd: { w:  704, h:  848  }, md: { w:  928, h: 1120 }, hd: { w: 1056, h: 1264 }, uhd: { w: 1408, h: 1680 } },
  { key: 'r1x1',  label: '1:1',  hint: 'Instagram feed classic · profile/avatar art',  sd: { w:  768, h:  768  }, md: { w: 1024, h: 1024 }, hd: { w: 1152, h: 1152 }, uhd: { w: 1536, h: 1536 } },
  { key: 'r6x5',  label: '6:5',  hint: 'Slightly-wide landscape, close to square',     sd: { w:  848, h:  704  }, md: { w: 1120, h:  928  }, hd: { w: 1264, h: 1056 }, uhd: { w: 1680, h: 1408 } },
  { key: 'r5x4',  label: '5:4',  hint: 'Classic print / monitor ratio',                sd: { w:  864, h:  688  }, md: { w: 1152, h:  912  }, hd: { w: 1280, h: 1024 }, uhd: { w: 1712, h: 1376 } },
  { key: 'r4x3',  label: '4:3',  hint: 'Facebook feed · standard photo/print ratio',   sd: { w:  880, h:  672  }, md: { w: 1184, h:  880  }, hd: { w: 1328, h:  992  }, uhd: { w: 1776, h: 1328 } },
  { key: 'r3x2',  label: '3:2',  hint: 'Twitter/X · LinkedIn · classic DSLR photos',   sd: { w:  960, h:  640  }, md: { w: 1216, h:  832  }, hd: { w: 1408, h:  960  }, uhd: { w: 1888, h: 1248 } },
  { key: 'r16x9', label: '16:9', hint: 'YouTube · Twitter/X landscape · widescreen video', sd: { w: 1024, h:  576  }, md: { w: 1344, h:  768  }, hd: { w: 1536, h:  864  }, uhd: { w: 2048, h: 1152 } },
  { key: 'r2x1',  label: '2:1',  hint: 'Wide banners · Twitter/X header images',       sd: { w: 1088, h:  544  }, md: { w: 1456, h:  720  }, hd: { w: 1632, h:  816  }, uhd: { w: 2176, h: 1088 } },
  { key: 'r21x9', label: '21:9', hint: 'Cinematic ultrawide · Scope/Cinemascope look', sd: { w: 1168, h:  496  }, md: { w: 1568, h:  672  }, hd: { w: 1760, h:  752  }, uhd: { w: 2352, h: 1008 } },
  // Appended (not inserted by ratio): Create stores its choice as an index
  // into this list, so existing entries must keep their positions.
  { key: 'r239x100', label: '2.39:1', hint: 'Scope · Cinemascope · anamorphic look', sd: { w:  960, h:  384  }, md: { w: 1216, h:  512  }, hd: { w: 1536, h:  640  }, uhd: { w: 2064, h:  864 } },
];

// ASPECT_PRESETS is the one source of aspect ratios. A flow that offers fewer
// picks a SUBSET of it by key (and may cap the resolution tiers) — never a
// parallel list: the old separate OUTPAINT_ASPECT_PRESETS had its own order
// and sizes, and the shared panels indexed it as if it were this list
// (NomadStudio#28: 16:9 did nothing in Outpaint, other picks applied a
// different ratio than the one previewed).
var ASPECT_PRESET_SUBSETS = {
  outpaint: { keys: ['r9x16', 'r2x3', 'r4x5', 'r1x1', 'r4x3', 'r3x2', 'r16x9', 'r239x100'], tiers: ['sd', 'md', 'hd'] },
};

// Small ratio glyph for preset buttons (crop panel), derived from the ratio
// so no entry has to carry hand-made icon numbers.
function _aspectIcon(label) {
  var parts = String(label).split(':');
  var r = (parseFloat(parts[0]) || 1) / (parseFloat(parts[1]) || 1);
  var vw = r >= 1 ? 18 : Math.max(6, Math.round(18 * r));
  var vh = r >= 1 ? Math.max(6, Math.round(18 / r)) : 18;
  return { vw: vw, vh: vh, rw: vw - 1.5, rh: vh - 1.5 };
}

function aspectPresetsFor(subsetId) {
  var sub = subsetId && ASPECT_PRESET_SUBSETS[subsetId];
  if (!sub) return ASPECT_PRESETS;
  return sub.keys.map(function (k) {
    var p = ASPECT_PRESETS.filter(function (q) { return q.key === k; })[0];
    if (!p) return null;
    var copy = { key: p.key, label: p.label, hint: p.hint, icon: _aspectIcon(p.label) };
    (sub.tiers || ['sd', 'md', 'hd', 'uhd']).forEach(function (t) { if (p[t]) copy[t] = p[t]; });
    return copy;
  }).filter(Boolean);
}

var OUTPAINT_ASPECT_PRESETS = aspectPresetsFor('outpaint');   // kept for existing callers (crop panel)
var ASPECT_PRESET_SETS = { 'default': ASPECT_PRESETS, 'outpaint': OUTPAINT_ASPECT_PRESETS };

// Set by renderParamGroup (flow-step-workflow-params.js) so other modules
// (e.g. the llm_transform set_aspect_ratio hook) can change the guided
// aspect-ratio selection without reaching into that closure's DOM directly.
var _ncfSetAspectFn = null;

var FALLBACK_QUALITY = [
  { id: 'fast',     get label() { return tF('Fast'); },     get sub() { return tF('fewer steps'); }, values: null },
  { id: 'balanced', get label() { return tF('Balanced'); }, get sub() { return tF('recommended'); }, values: null },
  { id: 'quality',  get label() { return tF('Max'); },      get sub() { return tF('more steps'); },  values: null },
];

// True only for an actual browser reload (F5 / refresh button) of the
// current document — false for a plain link click/navigation, even to this
// exact same URL. Distinguishes "resume what was here" (reload) from
// "start fresh" (navigating in from the hub, e.g. clicking Create > Simple
// again) — both land on the same URL and share the same tab's
// sessionStorage, so without this check they're indistinguishable to
// _resolveFlowInstanceId/_readPendingSession below, and a fresh visit would
// silently inherit — and then silently overwrite — whatever was left over
// from the last time this flow was open in this tab.
function _isPageReload() {
  try {
    var navEntries = performance.getEntriesByType && performance.getEntriesByType('navigation');
    if (navEntries && navEntries.length) return navEntries[0].type === 'reload';
    if (performance.navigation && typeof performance.navigation.type === 'number') {
      return performance.navigation.type === 1; // legacy TYPE_RELOAD
    }
  } catch (_) {}
  return false;
}

// ── Flow instance id ─────────────────────────────────────────────────────────
// Identifies "this visit to this flow" so multiple generations made without
// leaving the page collapse into ONE Nomad Studio history entry instead of a
// new entry per image (saveSessionSnapshot, further down, matches on this).
// Persisted in sessionStorage (survives an in-tab reload, resets on a fresh
// tab/session) so an accidental F5 doesn't fork off a second history entry —
// but only reused on an actual reload (_isPageReload), never on a plain
// fresh navigation to the same URL (see that function's comment).
function _genFlowInstanceId() {
  return Math.random().toString(36).slice(2, 10);
}
function _resolveFlowInstanceId(forFlowId) {
  var key = 'ns-flow-instance-' + forFlowId;
  try {
    // Reopening a saved session from history takes over ITS instanceId, so
    // anything generated from here on keeps updating that same entry instead
    // of starting a new one.
    if (_pendingSession && _pendingSession.instanceId) {
      sessionStorage.setItem(key, _pendingSession.instanceId);
      return _pendingSession.instanceId;
    }
    var existing = _isPageReload() ? sessionStorage.getItem(key) : null;
    if (existing) return existing;
    var fresh = _genFlowInstanceId();
    sessionStorage.setItem(key, fresh);
    return fresh;
  } catch (_) {
    return _genFlowInstanceId();
  }
}

// ── DOM refs ───────────────────────────────────────────────────────────────
// Queries every fixed-id element the engine caches. Re-run by
// FlowEngine.reset() (flow-boot.js) whenever a different flow is mounted
// into `scopeEl` — the ids repeat per mount (only one flow is ever "live"
// at a time, see flow-boot.js), so a plain re-query is enough; no need to
// namespace them. `scopeEl` defaults to `document` so the very first,
// standalone-page boot below behaves exactly as it always has.
var root, stepsEl, resultsEmpty, resultsGrid, breadcrumbEl, ncfZoomInBtn, ncfZoomOutBtn;
var lightboxEl, lightboxImgEl, lightboxPrevBtn, lightboxNextBtn, lightboxCloseBtn, lightboxCounter, lightboxPromptEl, lightboxBboxCanvas;
var flowId;

function flowQueryRefs(scopeEl) {
  scopeEl = scopeEl || document;

  root         = scopeEl.querySelector('#nsc-flow-root');
  stepsEl      = scopeEl.querySelector('#nsc-flow-steps');
  resultsEmpty = scopeEl.querySelector('#ncf-results-empty');
  resultsGrid  = scopeEl.querySelector('#ncf-results-grid');
  breadcrumbEl = scopeEl.querySelector('#nsc-flow-breadcrumb');
  ncfZoomInBtn  = scopeEl.querySelector('#ncf-gallery-zoom-in');
  ncfZoomOutBtn = scopeEl.querySelector('#ncf-gallery-zoom-out');

  // Lightbox
  lightboxEl       = document.getElementById('nsc-lightbox');
  lightboxImgEl    = document.getElementById('nsc-lightbox-img');
  lightboxPrevBtn  = document.getElementById('nsc-lightbox-prev');
  lightboxNextBtn  = document.getElementById('nsc-lightbox-next');
  lightboxCloseBtn = document.getElementById('nsc-lightbox-close');
  lightboxCounter  = document.getElementById('nsc-lightbox-counter');
  lightboxPromptEl = document.getElementById('nsc-lightbox-prompt');
  lightboxBboxCanvas = document.getElementById('nsc-lightbox-bbox-canvas');

  // NOTE: does NOT set flowId — flowId is explicit state (which flow this
  // is), not something to re-derive from the DOM on every re-query. See
  // flowResetState() below, the single source of truth for it. The initial,
  // standalone boot (bottom of this file) reads `data-flow-id` once, before
  // flowResetState exists to consult, which is the one legitimate place a
  // DOM read is still how flowId becomes known in the first place.
}

// ── Flow state ─────────────────────────────────────────────────────────────
var flowInstanceId;
var flowDef, allSteps, stepValues, sessionState;
var selectedImportId, selectedImportRecord, fullRecordCache, allImportsList;
var selectedAspectIdx, selectedResolution, customResDims;
var selectedQualityValues, selectedQualityId, selectedQuantizationValues, selectedQuantizationId, selectedLoraValues;
// Per-LoRA opt-out for trigger-word injection (#102). A LoRA's trigger words
// are prepended to the prompt at generation time; ticking one off here skips
// it for this session without deleting what was typed at import. Keyed by
// lower-cased file name.
var _loraKeywordsOff = {};
var selectedSeed, guidedFixedSeed, similarityOn, selectedNegativePrompt, selectedDisabledSubgraphs;
var currentAdvOverrides, _civitaiAdvancedOverrides, _wfAdvOverrides, _wfActivePreset;
var selectedLevel, flairValue, assistThinkMode, selectedGenre, _optGroupValues, isWritingScene;
var isGenerating, generatedCount, _genQueue;
var upscaleOutputMode;
var generateStatus, activeES;
var _pickerSettings;
var generateBtn = null; // assigned by other modules once the DOM exists, not reset per-flow here

var UPSCALE_OUTPUT_MODELS = {
  '2x_fast': 'RealESRGAN_x2plus.pth',
  '4x_fast': 'RealESRGAN_x4plus.pth',
  '4x_sharp': '4xBHI_realplksr_dysample_multiblur.safetensors',  // CC BY 4.0, Philip Hofmann (#34)
};

// '2x'/'4x' route through the SeedVR2 diffusion upscaler (app/workflows/upscale/refine_upscale_seedvr2.json)
// instead of the classic single-node ESRGAN swap above — higher quality, slower. 2x uses the lighter
// 3B model, 4x the 7B model (heavier scale gets the heavier model).
var UPSCALE_OUTPUT_SEEDVR2 = {
  '2x': { unetName: 'seedvr2_3b_int8_convrot.safetensors', scale: 2 },
  '4x': { unetName: 'seedvr2_7b_int8_convrot.safetensors', scale: 4 },
};
var _genresCache = null; // /api/flows/genres catalog — global, NOT flow-scoped, never reset per-flow

// Reinitializes every per-flow state variable above (plus a couple declared
// in sibling script files — see the "cross-file" comment below) to a clean
// slate for `newFlowId`. Called once implicitly for the first, standalone
// boot (see bottom of this file) and again by FlowEngine.reset()
// (flow-boot.js) whenever a session-native mount switches to a different
// flow — the whole point being that "switching flows" behaves like loading
// a fresh page, without actually reloading the document.
function flowResetState(newFlowId) {
  flowId = newFlowId;
  WORKFLOW_KEY = 'ns-workflow-' + newFlowId;
  PARAMS_KEY   = 'ns-params-'   + newFlowId;
  HISTORY_PFX  = 'ns-history-'  + newFlowId + '-';

  // NOTE: this does NOT re-read _pendingSession — that's the caller's job
  // (FlowEngine.reset() in flow-boot.js re-reads it explicitly before
  // calling this, for the "switching flows" case only; the very first,
  // standalone boot must NOT re-read it here, since the top-level
  // `_readPendingSession()` call already consumed/removed the sessionStorage
  // key once — reading again here would just return null and wipe it).
  flowInstanceId = _resolveFlowInstanceId(newFlowId);

  flowDef = null;
  allSteps = [];
  stepValues = {};
  sessionState = {};

  selectedImportId = null;
  selectedImportRecord = null;
  fullRecordCache = {};
  allImportsList = [];

  selectedAspectIdx = 7;   // 1:1
  selectedResolution = 'md';
  customResDims = null;
  selectedQualityValues = null;
  selectedQualityId = null;
  selectedQuantizationValues = null;
  selectedQuantizationId = null;
  selectedLoraValues = {};
  _loraKeywordsOff = {};
  selectedSeed = -1;
  guidedFixedSeed = -1;
  similarityOn = false;
  selectedNegativePrompt = '';
  selectedDisabledSubgraphs = [];
  currentAdvOverrides = {};
  _civitaiAdvancedOverrides = {};
  _wfAdvOverrides = {};
  _wfActivePreset = {};

  selectedLevel = 'scene';
  flairValue = 30;
  assistThinkMode = false;
  selectedGenre = '';
  _optGroupValues = {};
  isWritingScene = false;

  isGenerating = false;
  generatedCount = 0;
  _genQueue = [];
  upscaleOutputMode = 'none';

  generateStatus = null;
  activeES = null;
  _pickerSettings = {};
  _ncfSetAspectFn = null;

  // Cross-file per-flow state (flow-generation.js's lightbox/session-images
  // globals). Safe to touch from here — every engine script shares one
  // `window`, and by the time anything can trigger a reset (user
  // interaction), flow-generation.js has already run its own top-level
  // `var` declarations, so these names already exist.
  if (typeof sessionImages !== 'undefined') sessionImages = [];
  if (typeof lightboxCursor !== 'undefined') lightboxCursor = 0;
  if (typeof _lbBboxes !== 'undefined') _lbBboxes = null;
}

// ── Initial, standalone-page boot ───────────────────────────────────────────
// Runs once, exactly like the old top-level `var` initializers did. Every
// page that includes this script this way (every standalone
// /nomad-studio/create|refine|mix/<slug> page) gets identical behavior to
// before this refactor. Session-native mounts (flow-mount.js, added later)
// call flowQueryRefs()/flowResetState() again themselves when switching flows.
flowQueryRefs(document);
flowResetState(root ? root.getAttribute('data-flow-id') : '');

// ── Helpers ────────────────────────────────────────────────────────────────


// The list form the generation payload carries, so the server knows which
// LoRAs must not contribute their trigger words to this prompt.
function loraKeywordsOffList() {
  if (!_loraKeywordsOff) return [];
  return Object.keys(_loraKeywordsOff).filter(function (k) { return _loraKeywordsOff[k]; });
}
