'use strict';
// Quality presets: buildPresetsFromWorkflow, buildQualityList

function buildPresetsFromWorkflow(record) {
  var adv = Array.isArray(record && record.analysis && record.analysis.advancedParameters)
    ? record.analysis.advancedParameters : [];
  var sp = adv.find(function (p) { return String(p.inputKey || '').toLowerCase() === 'steps'; });
  if (!sp) return null;
  var key = String(sp.key || '');
  var def = Math.max(1, Math.round(Number(sp.value) || 20));
  // Half / double the workflow's own default steps — so a workflow whose
  // baked-in steps value is itself a clean power-of-2-friendly number
  // (e.g. 8) gets exactly Fast=4/Balanced=8/Max=16 instead of the old
  // 0.55x/1.5x ratios, which never landed on round numbers even when the
  // base was already round (8 -> Fast=4 still worked, but Max=12, not 16).
  var fast = Math.max(1, Math.round(def * 0.5));
  var qual = Math.round(def * 2);

  // CFG stays fixed across all three tiers (only steps scale) — shown in the
  // sub-label so the user sees the real numbers the workflow will run with,
  // not just a vague "draft/default/best" — same "N steps · CFG X" format
  // used elsewhere in the app for applied-values summaries.
  var cp = adv.find(function (p) { return String(p.inputKey || '').toLowerCase() === 'cfg'; });
  var cfgVal = cp ? Number(cp.value) : null;
  var cfgSuffix = (cfgVal !== null && !isNaN(cfgVal)) ? (' · CFG ' + cfgVal) : '';

  function v(s) { var o = {}; if (key) o[key] = s; return o; }
  return [
    { id: 'fast',     label: 'Fast',     sub: fast + ' steps' + cfgSuffix,   values: v(fast) },
    { id: 'balanced', label: 'Balanced', sub: def  + ' steps' + cfgSuffix,   values: v(def)  },
    { id: 'quality',  label: 'Max',      sub: qual + ' steps' + cfgSuffix,   values: v(qual) },
  ];
}

function resolveQualityPresets(record) {
  var wfPresets = Array.isArray(record && record.analysis && record.analysis.qualityPresets)
    ? record.analysis.qualityPresets : [];
  return wfPresets.length
    ? wfPresets.map(function (p) {
        return { id: String(p.id || ''), label: String(p.label || p.id || ''), sub: '', values: p.values || null };
      })
    : (buildPresetsFromWorkflow(record) || FALLBACK_QUALITY);
}

function buildQualityList(record, listEl) {
  if (!listEl) return;
  var presets = resolveQualityPresets(record);

  var savedQualityId = (loadSavedParams() || {}).qualityId;
  // Default to Balanced (not the first preset, which is always Fast) when
  // the user has no saved preference yet for this flow — Fast trades away
  // quality for speed, which shouldn't be the unasked-for default.
  var defaultPreset = presets.find(function (p) { return p.id === 'balanced'; }) || presets[0];
  var initialId = (savedQualityId && presets.some(function (p) { return p.id === savedQualityId; }))
    ? savedQualityId : (defaultPreset ? defaultPreset.id : null);
  selectedQualityId     = initialId;
  selectedQualityValues = (presets.find(function (p) { return p.id === initialId; }) || presets[0] || {}).values || null;

  listEl.innerHTML = '';
  presets.forEach(function (p) {
    var btn = document.createElement('button');
    btn.className = 'nsc-quality-btn' + (p.id === selectedQualityId ? ' is-active' : '');
    btn.type = 'button';
    btn.setAttribute('role', 'radio');
    btn.setAttribute('data-quality-id', p.id);
    btn.setAttribute('aria-checked', p.id === selectedQualityId ? 'true' : 'false');
    // The pill row is deliberately compact (.nsc-quality-copy small is
    // display:none app-wide) — the steps/CFG detail lives in a native hover
    // tooltip instead, so it's still there for anyone who wants to check
    // exactly what a preset runs with without cluttering the pills.
    if (p.sub) btn.title = p.sub;
    btn.innerHTML =
      '<span class="nsc-quality-dot"></span>' +
      '<span class="nsc-quality-copy"><strong>' + escHtml(p.label) + '</strong>' +
      (p.sub ? '<small>' + escHtml(p.sub) + '</small>' : '') + '</span>';
    (function (preset) {
      btn.addEventListener('click', function () {
        selectedQualityId = preset.id; selectedQualityValues = preset.values;
        listEl.querySelectorAll('.nsc-quality-btn').forEach(function (b) {
          var a = b === btn; b.classList.toggle('is-active', a); b.setAttribute('aria-checked', a ? 'true' : 'false');
        });
        saveParams();
      });
    }(p));
    listEl.appendChild(btn);
  });
}

// ── Enum picker modal ──────────────────────────────────────────────────────
