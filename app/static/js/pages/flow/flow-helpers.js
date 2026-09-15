'use strict';
// Generic helpers: escHtml, sleep, getMode, saveParams, getDims, setVal, getVal, resolveTpl, parseCivitAI, applyEffects

function escHtml(s) {
  return String(s || '').replace(/[&<>"']/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
  });
}
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function getMode() { return localStorage.getItem(NS_MODE_KEY) || 'basic'; }

var GLOBAL_WORKFLOWS_KEY = 'ns-global-workflows';
function getGlobalWorkflows() { try { return JSON.parse(localStorage.getItem(GLOBAL_WORKFLOWS_KEY) || '[]'); } catch(_){ return []; } }
function setGlobalWorkflows(ids) { try { localStorage.setItem(GLOBAL_WORKFLOWS_KEY, JSON.stringify(ids)); } catch(_){} }
function saveParams() {
  try {
    // Merge over whatever is already stored instead of replacing it: the
    // options_groups selectors (renderWorkflowParams) keep their pick under
    // their own `optgrp_<id>` key in this same blob, and a wholesale
    // overwrite here erased it on the next aspect/seed/quality change — so a
    // poster type chosen in the panel silently reverted to its default the
    // moment anything else was touched, and never survived a reload.
    var _prev = loadSavedParams() || {};
    localStorage.setItem(PARAMS_KEY, JSON.stringify(Object.assign(_prev, {
      aspectIdx:  selectedAspectIdx,
      resolution: selectedResolution,
      customResDims: customResDims,
      qualityId:  selectedQualityId,
      quantizationId: selectedQuantizationId,
      similarity: similarityOn,
      negativePrompt: selectedNegativePrompt,
      disabledSubgraphs: selectedDisabledSubgraphs,
      seed:       selectedSeed,
      wfAdvOverrides: _wfAdvOverrides,
      wfActivePreset: _wfActivePreset,
    })));
  } catch (_) {}
}
function loadSavedParams() {
  try { return JSON.parse(localStorage.getItem(PARAMS_KEY) || 'null'); } catch (_) { return null; }
}
function getDims() {
  if (customResDims && customResDims.w && customResDims.h) return customResDims;
  var a = ASPECT_PRESETS[selectedAspectIdx];
  if (a && a[selectedResolution]) return a[selectedResolution];
  var square = ASPECT_PRESETS.find(function (p) { return p.key === 'r1x1'; });
  return (square && square.md) || ASPECT_PRESETS[0].md;
}

// ── Step value store ───────────────────────────────────────────────────────
function setVal(stepId, field, value) {
  if (!stepValues[stepId]) stepValues[stepId] = {};
  stepValues[stepId][field] = value;
  if (generateBtn) updateGenerateBtn();
}
function getVal(stepId, field) {
  return stepValues[stepId] && stepValues[stepId][field];
}

function resolveTpl(tpl, vars) {
  if (!tpl) return '';
  return tpl.replace(/\{\{(\w+)\}\}/g, function (_, k) {
    return Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : '';
  });
}

// resolveRef: "steps.X.output.Y" and "session.X" with || fallback
function resolveRef(ref) {
  if (!ref) return undefined;
  var parts = String(ref).split('||').map(function (s) { return s.trim(); });
  for (var i = 0; i < parts.length; i++) {
    var v = _resolveOne(parts[i]);
    if (v !== undefined && v !== null && v !== '') return v;
  }
  return undefined;
}
function _resolveOne(ref) {
  var segs = ref.split('.');
  if (segs[0] === 'steps' && segs.length >= 4) {
    return getVal(segs[1], segs.slice(3).join('.'));
  }
  if (segs[0] === 'session') {
    return sessionState[segs.slice(1).join('.')];
  }
  return undefined;
}

// ── CivitAI paste helpers ──────────────────────────────────────────────────
function parseCivitAI(text) {
  var r = { positive: '', negative: '', loras: [], lorasText: '',
             model: '', sampler: '', seed: null, steps: null,
             cfg: null, width: null, height: null, clipSkip: null };
  if (!text || !text.trim()) return r;
  var t = text.trim();
  var negIdx     = t.search(/(?:^|\n)Negative prompt:/i);
  var paramsIdx  = t.search(/(?:^|\n)Steps:/i);
  var positiveRaw = t, negRaw = '', paramsStr = '';
  if (negIdx >= 0 && paramsIdx >= 0) {
    positiveRaw = t.substring(0, negIdx).trim();
    // `negIdx` comes from /(?:^|\n)Negative prompt:/, so unless the negative is
    // on the very first line it points at the newline, not at the label. The
    // previous version stripped "the first line, minus the label" — but with
    // the index one character early that first line *was* just the newline, so
    // the label was never removed and every parsed negative began with
    // "Negative prompt: ". Anchoring on optional whitespace plus the label
    // handles both positions.
    negRaw      = t.substring(negIdx).replace(/^\s*Negative prompt:\s*/i, '');
    var pOff = negRaw.search(/(?:^|\n)Steps:/i);
    if (pOff >= 0) { paramsStr = negRaw.substring(pOff).replace(/^\n/, ''); negRaw = negRaw.substring(0, pOff).trim(); }
  } else if (paramsIdx >= 0) {
    positiveRaw = t.substring(0, paramsIdx).trim();
    paramsStr   = t.substring(paramsIdx).replace(/^\n/, '');
  } else if (negIdx >= 0) {
    positiveRaw = t.substring(0, negIdx).trim();
    negRaw      = t.substring(negIdx).replace(/Negative prompt:\s*/i, '').trim();
  }
  r.negative = negRaw.trim();
  if (paramsStr) {
    var m;
    m = paramsStr.match(/Steps:\s*(\d+)/i);          if (m) r.steps    = parseInt(m[1], 10);
    m = paramsStr.match(/CFG scale:\s*([\d.]+)/i);   if (m) r.cfg      = parseFloat(m[1]);
    m = paramsStr.match(/Sampler:\s*([^,\n]+)/i);    if (m) r.sampler  = m[1].trim();
    m = paramsStr.match(/Seed:\s*(\d+)/i);           if (m) r.seed     = parseInt(m[1], 10);
    m = paramsStr.match(/Size:\s*(\d+)x(\d+)/i);     if (m) { r.width = parseInt(m[1], 10); r.height = parseInt(m[2], 10); }
    m = paramsStr.match(/(?:^|,\s*)Model:\s*([^,\n]+)/i); if (m) r.model = m[1].trim();
    m = paramsStr.match(/Clip skip:\s*(\d+)/i);      if (m) r.clipSkip = parseInt(m[1], 10);
  }
  var loraRe = /<lora:([^:>]+):([\d.]+)>/g, lm, tags = [];
  while ((lm = loraRe.exec(positiveRaw)) !== null) {
    r.loras.push({ name: lm[1], weight: parseFloat(lm[2]) });
    tags.push(lm[0]);
  }
  r.lorasText = tags.join(', ');
  r.positive  = positiveRaw.replace(/<lora:[^>]+>/g, '').replace(/,\s*,/g, ',').replace(/^[\s,]+|[\s,]+$/g, '').trim();
  return r;
}

function _civitaiFuzzyMatch(a, b) {
  function norm(s) {
    return String(s || '').toLowerCase().replace(/\.(safetensors|ckpt|pt|bin|pth)$/i, '').replace(/[-_.\s]/g, '');
  }
  var na = norm(a), nb = norm(b);
  return !!(na && nb && (na === nb || na.includes(nb) || nb.includes(na)));
}

function applyEffects(effects) {
  if (!effects) return;
  var set = effects.set_session;
  if (set) Object.keys(set).forEach(function (k) { sessionState[k] = resolveRef(set[k]); });
  var app = effects.append_to_session;
  if (app) Object.keys(app).forEach(function (k) {
    var val = resolveRef(app[k]);
    if (val == null) return;
    if (!Array.isArray(sessionState[k])) sessionState[k] = [];
    sessionState[k].push(val);
  });
  var inc = effects.increment_session;
  if (inc) sessionState[inc] = (Number(sessionState[inc]) || 0) + 1;
}

// ── Toast (error / info) ────────────────────────────────────────────────────
// Lightweight replacement for the inline "✗ ..." status text under LLM/write
// buttons — those lines got removed to cut visual clutter, so failures now
// surface here instead of silently vanishing. showErrorToast is the original,
// error-only entry point kept for every existing call site; showToast adds an
// optional 'info' variant (e.g. confirming a value was auto-applied) without
// touching any of them.
var _ncfToastStack = null;
function showToast(message, type) {
  if (!_ncfToastStack) {
    _ncfToastStack = document.createElement('div');
    _ncfToastStack.className = 'ncf-toast-stack';
    document.body.appendChild(_ncfToastStack);
  }
  var isError = type !== 'info';
  var toast = document.createElement('div');
  toast.className = 'ncf-toast ' + (isError ? 'ncf-toast--error' : 'ncf-toast--info');
  toast.setAttribute('role', isError ? 'alert' : 'status');
  var icon = isError
    ? '<circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="16.5" x2="12" y2="16.51"/>'
    : '<circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5 5-5"/>';
  toast.innerHTML =
    '<svg class="ncf-toast-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      icon +
    '</svg>' +
    '<span class="ncf-toast-msg"></span>' +
    '<button type="button" class="ncf-toast-close" aria-label="Dismiss">&times;</button>';
  toast.querySelector('.ncf-toast-msg').textContent = String(message || (isError ? 'Something went wrong' : ''));
  var timer = setTimeout(remove, 7000);
  function remove() {
    clearTimeout(timer);
    toast.classList.remove('is-visible');
    setTimeout(function () { toast.remove(); }, 200);
  }
  toast.querySelector('.ncf-toast-close').addEventListener('click', remove);
  _ncfToastStack.appendChild(toast);
  requestAnimationFrame(function () { toast.classList.add('is-visible'); });
}
function showErrorToast(message) {
  showToast(message, 'error');
}

// ── Prompt history ─────────────────────────────────────────────────────────
