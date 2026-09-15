'use strict';
// Step: scene_builder → renderSceneBuilder

function renderSceneBuilder(stepDef, el) {
  var CHAR_COLORS = ['#6aa9ff','#4ade80','#fbbf24','#f87171','#c084fc',
                     '#34d399','#fb923c','#a78bfa','#38bdf8','#f472b6'];
  var ORIENT_PRESETS = [
    { id: 'frontal',   label: 'Frontal',      desc: 'facing the camera directly, frontal pose' },
    { id: 'q3_left',   label: '3/4 L',        desc: 'three-quarter view from the left' },
    { id: 'q3_right',  label: '3/4 R',        desc: 'three-quarter view from the right' },
    { id: 'prof_left', label: 'Profile L',    desc: 'side profile facing left' },
    { id: 'prof_right',label: 'Profile R',    desc: 'side profile facing right' },
    { id: 'back',      label: 'Back',         desc: 'seen from behind, back to camera' },
    { id: 'free',      label: 'Custom…',      desc: '' },
  ];

  // ── local state ──────────────────────────────────────────────────────────
  var sceneData = { highlevel: '', imageDataUrl: null, imageDesc: '' };
  var characters = [];
  var charIdSeq  = 0;
  var includeCharacterPose = true; // "Include pose" toggle in the Characters panel
  var _debounce  = null;

  // ── vision model button — one per step, affects both Scene and Character
  // image descriptions (same global lmStudioVisionModel setting). Same
  // compact-icon-only recipe as flow-step-vision-describe.js. ──────────────
  var sceneStepLabel = el.querySelector('.nsc-step-label') ||
                        (el.closest('.nsc-step') && el.closest('.nsc-step').querySelector('.nsc-step-label'));
  if (sceneStepLabel && typeof makeVisionModelBtn === 'function') {
    var sceneVisionBtn = makeVisionModelBtn();
    sceneVisionBtn.className = 'nsc-history-btn nsc-options-trigger ncf-vision-model-btn';
    sceneVisionBtn.setAttribute('aria-label', 'Change vision model');
    var sceneVisionName = sceneVisionBtn.querySelector('.ncf-model-icon-name');
    if (sceneVisionName) sceneVisionName.remove();
    var sceneVisionIcon = sceneVisionBtn.querySelector('svg');
    if (sceneVisionIcon) {
      sceneVisionIcon.setAttribute('fill', 'none');
      sceneVisionIcon.setAttribute('stroke', 'currentColor');
      sceneVisionIcon.setAttribute('stroke-width', '1.5');
      sceneVisionIcon.setAttribute('stroke-linecap', 'round');
      sceneVisionIcon.setAttribute('stroke-linejoin', 'round');
    }
    var sceneChevron = sceneStepLabel.querySelector('.nsc-step-chevron');
    if (sceneChevron) sceneStepLabel.insertBefore(sceneVisionBtn, sceneChevron);
    else sceneStepLabel.appendChild(sceneVisionBtn);
  }

  // ── root wrap ────────────────────────────────────────────────────────────
  var wrap = document.createElement('div');
  wrap.className = 'nsb-wrap';
  el.appendChild(wrap);

  // ── helpers ──────────────────────────────────────────────────────────────
  function escH(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function mkEl(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html) e.innerHTML = html;
    return e;
  }

  function sectionHeader(title) {
    var h = mkEl('p', 'nsb-section-hdr', escH(title));
    return h;
  }

  var OPTIONS_ICON =
    '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">' +
      '<line x1="3" y1="5" x2="15" y2="5"/><circle cx="11" cy="5" r="1.6" fill="currentColor" stroke="none"/>' +
      '<line x1="3" y1="13" x2="15" y2="13"/><circle cx="7" cy="13" r="1.6" fill="currentColor" stroke="none"/>' +
    '</svg>';

  // Compact "label + status + trigger button" row — same layout as
  // .nsb-chars-hdr (title left, control right), reused for every
  // section that now lives behind a subpanel instead of always-visible.
  function makeTriggerRow(title, ariaLabel, onClick) {
    var row = mkEl('div', 'nsb-chars-hdr');
    var titleWrap = mkEl('div', 'nsb-row-title-wrap');
    titleWrap.appendChild(sectionHeader(title));
    var statusSp = mkEl('span', 'nsb-row-status');
    titleWrap.appendChild(statusSp);
    row.appendChild(titleWrap);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nsc-history-btn nsc-options-trigger';
    btn.setAttribute('aria-label', ariaLabel);
    btn.innerHTML = OPTIONS_ICON;
    btn.addEventListener('click', onClick);
    row.appendChild(btn);
    return { row: row, statusEl: statusSp };
  }

  // ── build Ideogram JSON from current state ───────────────────────────────
  function buildJson() {
    var hlDesc = sceneData.highlevel.trim();
    if (!hlDesc) {
      var parts = [];
      characters.forEach(function (c) { if (c.label) parts.push(c.label); });
      hlDesc = parts.join(', ') || 'A composed scene';
    }
    // Background prefers the background image's own auto-description (never
    // duplicates high_level_description when one exists). Falls back to
    // Scene Idea when there's no image — accepting the duplication there is
    // better than losing detail the user actually typed (e.g. "forest").
    // Only falls back further to a generic phrase when neither exists.
    var bgDesc = sceneData.imageDesc.trim() || sceneData.highlevel.trim() || 'Detailed background environment';

    var elements = characters.map(function (c) {
      var orientDesc = '';
      if (c.orientId && c.orientId !== 'free') {
        var preset = ORIENT_PRESETS.find(function (o) { return o.id === c.orientId; });
        if (preset) orientDesc = preset.desc;
      } else if (c.orientFree.trim()) {
        orientDesc = c.orientFree.trim();
      }
      var descParts = [];
      if (orientDesc) descParts.push(orientDesc);
      // Pose comes from the vision description when "Include pose" is on
      // (already folded into c.desc by the model). When it's off, the model
      // was told to skip pose entirely, so the manually-typed Pose field
      // (if any) is what carries it instead.
      if (!includeCharacterPose && c.manualPose && c.manualPose.trim()) descParts.push(c.manualPose.trim());
      if (c.desc.trim()) descParts.push(c.desc.trim());
      if (!descParts.length) descParts.push(c.label || 'character');
      return {
        type: 'obj',
        bbox: c.bbox.slice(),
        desc: descParts.join(', '),
        color_palette: []
      };
    });

    return {
      high_level_description: hlDesc,
      style_description: {
        aesthetics: 'Cinematic, detailed, high quality',
        lighting: 'Natural cinematic lighting',
        photo: 'Professional photography',
        medium: 'Photography',
        color_palette: []
      },
      compositional_deconstruction: {
        background: bgDesc,
        elements: elements
      }
    };
  }

  // ── push to linked ideogram_composer ─────────────────────────────────────
  function pushJsonToComposer(json) {
    if (!stepDef.output_to) return;
    var targetStep = allSteps.find(function (s) { return s.id === stepDef.output_to; });
    if (!targetStep || typeof targetStep._fillFn !== 'function') return;
    try {
      targetStep._fillFn(JSON.stringify(json));
    } catch (e) {
      console.warn('[SceneBuilder] _fillFn error:', e);
    }
  }

  // Automatic live-sync path (debounced, on every field edit) — mechanical
  // only, never calls the LLM. A merge call on every keystroke would be slow
  // and hammer LM Studio just to keep the preview updated.
  function pushToComposer() {
    pushJsonToComposer(buildJson());
  }

  function schedulePush() {
    if (_debounce) clearTimeout(_debounce);
    _debounce = setTimeout(pushToComposer, 600);
  }

  // Same schema/coordinate/bbox rules already used by Ideogram Assist's
  // "scene" compose level (app/instructions/flows/create/assist_ideogram.json,
  // step "compose", system_prompts.scene) — reused verbatim since it's
  // agnostic to whether the input JSON came from loose fragments or an
  // already-assembled composition like Scene Builder's.
  var SCENE_SYSTEM_PROMPT =
    'You are an Ideogram composition AI and visual art director. Given composition fragments, produce a complete Ideogram JSON with full compositional deconstruction. Use a 1000×1000 normalized canvas.\n\n' +
    'COORDINATE SYSTEM: origin top-left. x increases rightward (0–1000). y increases downward (0–1000). bbox = [y_min, x_min, y_max, x_max] — a JSON array of exactly 4 integers, all within 0–1000, y_min < y_max, x_min < x_max. NEVER write bbox as a string or text description. NEVER create conceptual or abstract elements (no \'negative space\', \'visual tension\', \'overall scene\' — only physical objects, characters, text).\n\n' +
    'Placement examples on a 1000×1000 canvas:\n' +
    '  Upper-left quarter  → [0, 0, 500, 500]\n' +
    '  Upper-right quarter → [0, 500, 500, 1000]\n' +
    '  Lower-left quarter  → [500, 0, 1000, 500]\n' +
    '  Lower-right quarter → [500, 500, 1000, 1000]\n' +
    '  Full canvas         → [0, 0, 1000, 1000]\n' +
    '  Bottom banner       → [870, 0, 1000, 1000]\n' +
    '  Centered subject    → [100, 200, 950, 800]\n\n' +
    'Schema:\n' +
    '{\n' +
    '  "high_level_description": "rich one-paragraph description of the full piece",\n' +
    '  "style_description": {\n' +
    '    "aesthetics": "specific art style, movement, cultural references, visual treatment",\n' +
    '    "lighting": "light source direction, quality (hard/soft/diffuse), color temperature, shadow treatment",\n' +
    '    "photo": "photographic medium, film type, grain, post-processing style",\n' +
    '    "medium": "primary medium and any mixed-media techniques",\n' +
    '    "color_palette": ["#hex", "#hex", "#hex", "#hex", "#hex"]\n' +
    '  },\n' +
    '  "compositional_deconstruction": {\n' +
    '    "background": "complete background description — surface, texture, atmosphere, depth layers",\n' +
    '    "elements": [\n' +
    '      {\n' +
    '        "type": "obj"|"text"|"bg",\n' +
    '        "bbox": [y_min, x_min, y_max, x_max],\n' +
    '        "desc": "detailed description — material, texture, visual treatment, relationship to composition",\n' +
    '        "color_palette": ["#hex", "#hex", "#hex"]\n' +
    '      }\n' +
    '    ]\n' +
    '  }\n' +
    '}\n\n' +
    'Rules:\n' +
    '- Bboxes must form a deliberate, balanced layout — consider visual weight and negative space\n' +
    '- Bboxes must match prose: \'upper left\' → low y_min+x_min; \'horizontal banner\' → narrow y span, wide x span; \'right side\' → x_min > 500\n' +
    '- Each element description should be 1–3 sentences, specific and visual\n' +
    '- Per-element color_palette: 3–5 hex values dominant in that element\n' +
    '- Global color_palette: 5 hex values that define the mood of the whole piece\n' +
    '- Infer complementary elements from context if needed (backgrounds, textures, secondary objects)\n' +
    '- Output ONLY valid JSON. No text before or after. No markdown. No code blocks.';

  var SCENE_MERGE_REQUEST =
    'Merge the scene idea and background description with each character\'s description into one ' +
    'cohesive, unified composition. Rewrite high_level_description as a rich paragraph that ties the ' +
    'whole scene together naturally. Refine each element\'s desc to read as part of the same coherent ' +
    'scene instead of an isolated fragment. Do not change any bbox coordinates and do not remove or ' +
    'add characters.';

  // ── explicit "Build Composition" click — mechanical JSON, then an LLM pass
  // to actually merge scene idea + character descriptions into one coherent
  // whole (buildJson() alone just concatenates strings, no real synthesis).
  async function buildComposition() {
    if (_debounce) clearTimeout(_debounce);
    var mechanicalJson = buildJson();
    buildBtn.disabled = true;
    buildHint.textContent = 'Composing…';
    try {
      var res = await fetch('/api/models/chat/studio-ideogram-refine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          currentJson: mechanicalJson,
          changeRequest: SCENE_MERGE_REQUEST,
          systemPrompt: SCENE_SYSTEM_PROMPT
        })
      });
      var data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || 'Compose failed');
      pushJsonToComposer(data.ideogramJson);
      buildHint.textContent = '✓ Sent to Composition';
    } catch (e) {
      // Fallback: LLM unavailable (model unloaded, etc.) — still push the
      // mechanical JSON rather than leaving the button do nothing.
      pushJsonToComposer(mechanicalJson);
      buildHint.textContent = '⚠ Composed without merge (' + e.message + ')';
    } finally {
      buildBtn.disabled = false;
      setTimeout(function () { buildHint.textContent = 'Pushes to the Composition step below'; }, 3000);
    }
  }

  // ── initial bboxes — evenly spread characters ────────────────────────────
  function defaultBboxForIndex(idx, total) {
    // Spread evenly horizontally; tall portrait bbox per character
    var cols = Math.min(total, 4);
    var colW = Math.floor(1000 / cols);
    var col  = idx % cols;
    var row  = Math.floor(idx / cols);
    var x0 = col * colW + 60;
    var x1 = x0 + colW - 120;
    var rowH = 700;
    var y0 = row * rowH + 100;
    var y1 = y0 + rowH - 60;
    return [
      Math.max(0, y0), Math.max(0, x0),
      Math.min(1000, y1), Math.min(1000, x1)
    ];
  }

  // ── describe image via vision API ─────────────────────────────────────────
  function describeImage(dataUrl, describeType, onDone, onStatus, forceRefresh, includePose) {
    if (onStatus) onStatus('⏳ Describing…');
    fetch('/api/models/chat/describe-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        imageDataUrl: dataUrl,
        describeType: describeType,
        forceRefresh: !!forceRefresh,
        includePose: includePose !== false // only 'character' describes read this; harmless elsewhere
      })
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) throw new Error(d.error);
      if (onStatus) onStatus('');
      onDone(d.description || '');
    })
    .catch(function (err) {
      if (onStatus) onStatus('✗ ' + (err.message || 'Error'));
    });
  }

  // ── compact drop zone helper ──────────────────────────────────────────────
  function makeCompactDrop(opts) {
    // opts: { describeType, onDataUrl, onClear, placeholder, statusEl? }
    var dz = mkEl('div', 'nsb-drop');
    var fileIn = document.createElement('input');
    fileIn.type = 'file'; fileIn.accept = 'image/*'; fileIn.style.display = 'none';
    dz.appendChild(fileIn);

    var inner = mkEl('div', 'nsb-drop-inner',
      '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>' +
      '<span>' + escH(opts.placeholder || 'Drop image') + '</span>');
    dz.appendChild(inner);

    var preview = document.createElement('img');
    preview.className = 'nsb-drop-preview'; preview.style.display = 'none';
    dz.appendChild(preview);

    var actRow = mkEl('div', 'nsb-drop-acts');
    actRow.style.display = 'none';
    var descBtn = mkEl('button', 'nsb-drop-btn nsb-drop-desc', 'Describe again');
    descBtn.type = 'button';
    var clearBtn = mkEl('button', 'nsb-drop-btn nsb-drop-clear', '✕');
    clearBtn.type = 'button';
    actRow.appendChild(descBtn); actRow.appendChild(clearBtn);
    dz.appendChild(actRow);

    var stat = opts.statusEl || mkEl('p', 'nsb-drop-status');
    if (!opts.statusEl) dz.appendChild(stat);

    var _currentDataUrl = null;

    function applyDataUrl(dataUrl) {
      _currentDataUrl = dataUrl;
      preview.src = dataUrl; preview.style.display = 'block';
      inner.style.display = 'none'; actRow.style.display = 'flex';
      dz.classList.add('has-image');
      if (opts.onDataUrl) opts.onDataUrl(dataUrl);
      describeImage(dataUrl, opts.describeType || 'character',
        function (desc) { if (opts.onDesc) opts.onDesc(desc, false); },
        function (msg) { stat.textContent = msg; },
        false,
        includeCharacterPose
      );
    }

    function clearIt() {
      _currentDataUrl = null; preview.src = ''; preview.style.display = 'none';
      inner.style.display = ''; actRow.style.display = 'none'; stat.textContent = '';
      dz.classList.remove('has-image');
      if (opts.onDataUrl) opts.onDataUrl(null);
      if (opts.onClear) opts.onClear();
    }

    function handleFile(file) {
      if (!file || !file.type.startsWith('image/')) return;
      var rd = new FileReader();
      rd.onload = function (e) { applyDataUrl(String(e.target.result || '')); };
      rd.readAsDataURL(file);
    }

    dz.addEventListener('click', function (ev) {
      if (ev.target.closest('.nsb-drop-acts')) return;
      fileIn.click();
    });
    fileIn.addEventListener('change', function () { if (fileIn.files[0]) handleFile(fileIn.files[0]); });
    dz.addEventListener('dragover', function (ev) { ev.preventDefault(); dz.classList.add('is-over'); });
    dz.addEventListener('dragleave', function () { dz.classList.remove('is-over'); });
    dz.addEventListener('drop', function (ev) {
      ev.preventDefault(); dz.classList.remove('is-over');
      if (ev.dataTransfer && ev.dataTransfer.files[0]) handleFile(ev.dataTransfer.files[0]);
    });
    descBtn.addEventListener('click', function (ev) {
      ev.stopPropagation();
      if (_currentDataUrl) describeImage(_currentDataUrl, opts.describeType || 'character',
        function (desc) { if (opts.onDesc) opts.onDesc(desc, true); },
        function (msg) { stat.textContent = msg; },
        true, // forceRefresh — "Describe again" must bypass the hash cache, not just repeat the same cached answer
        includeCharacterPose
      );
    });
    clearBtn.addEventListener('click', function (ev) { ev.stopPropagation(); clearIt(); });

    return dz;
  }

  function previewText(s, max) {
    s = String(s || '').trim();
    if (!s) return '';
    return s.length > max ? s.slice(0, max) + '…' : s;
  }

  // ════════════════════════════════════════════════════════════════════════
  // ── Scene section — 3 rows, each behind its own subpanel ─────────────────
  // ════════════════════════════════════════════════════════════════════════
  var sceneSection = mkEl('div', 'nsb-section');
  wrap.appendChild(sceneSection);

  // Background image drop (unchanged logic — only where it's mounted changes)
  var sceneDrop = makeCompactDrop({
    placeholder: 'Background / scene reference',
    describeType: 'background',
    onDataUrl: function (url) {
      sceneData.imageDataUrl = url || null;
      bgRow.statusEl.textContent = url ? '✓' : '';
      schedulePush();
    },
    onDesc: function (desc, forced) {
      sceneData.imageDesc = desc;
      if (forced || !hlTa.value.trim()) { hlTa.value = desc; sceneData.highlevel = desc; hlRow.statusEl.textContent = previewText(desc, 40); }
      schedulePush();
    }
  });

  var bgRow = makeTriggerRow('Background Image', 'Background image options', function () {
    openOptionsPanel('Background Image', function (body) { body.appendChild(sceneDrop); });
  });
  sceneSection.appendChild(bgRow.row);

  // Scene Idea — merges what used to be two separate fields (Scene
  // Description + High-Level Concept) into one: covers both the overall
  // concept and the background. Leave blank to auto-generate from
  // character labels alone.
  var hlTa = mkEl('textarea', 'nsb-textarea');
  hlTa.rows = 4; hlTa.placeholder = 'Describe scene and background…';
  hlTa.addEventListener('input', function () {
    sceneData.highlevel = hlTa.value;
    hlRow.statusEl.textContent = previewText(hlTa.value, 40);
    schedulePush();
  });

  var hlRow = makeTriggerRow('Scene Idea', 'Scene idea options', function () {
    openOptionsPanel('Scene Idea', function (body) { body.appendChild(hlTa); });
  });
  sceneSection.appendChild(hlRow.row);

  // ════════════════════════════════════════════════════════════════════════
  // ── Characters section — one row, whole section behind one subpanel ──────
  // ════════════════════════════════════════════════════════════════════════
  var charSection = mkEl('div', 'nsb-section');
  wrap.appendChild(charSection);

  var addBtn = mkEl('button', 'nsb-add-btn', '+ Add character');
  addBtn.type = 'button';

  var charList = mkEl('div', 'nsb-chars-list');

  // "Include pose" toggle — controls whether the character describe prompt
  // (backend, vision_routes.py describe_type == 'character') asks the vision
  // model to describe body pose/gesture at all. Same markup/behavior as the
  // app's existing pill-switch pattern (.create-basic-similarity-toggle).
  var poseToggle = document.createElement('button');
  poseToggle.type = 'button';
  poseToggle.className = 'create-basic-similarity-toggle';
  poseToggle.setAttribute('aria-pressed', 'true');
  poseToggle.innerHTML =
    '<span class="create-basic-similarity-label">Include pose</span>' +
    '<div class="create-basic-switch" aria-hidden="true"><div class="create-basic-switch-thumb"></div></div>';
  poseToggle.addEventListener('click', function () {
    includeCharacterPose = !includeCharacterPose;
    poseToggle.classList.toggle('off', !includeCharacterPose);
    poseToggle.setAttribute('aria-pressed', String(includeCharacterPose));
    // Show/hide every existing character card's manual Pose field — it's
    // only relevant while the vision model has been told to skip pose.
    charList.querySelectorAll('.nsb-char-pose-row').forEach(function (row) {
      row.style.display = includeCharacterPose ? 'none' : '';
    });
    schedulePush();
  });

  var charsRow = makeTriggerRow('Characters', 'Characters options', function () {
    openOptionsPanel('Characters', function (body) {
      body.appendChild(poseToggle);
      body.appendChild(addBtn);
      body.appendChild(charList);
    });
  });
  charSection.appendChild(charsRow.row);

  function updateCharsCount() {
    charsRow.statusEl.textContent = characters.length ? String(characters.length) : '';
  }
  updateCharsCount();

  // ── Build button ─────────────────────────────────────────────────────────
  var buildRow = mkEl('div', 'nsb-build-row');
  var buildBtn = mkEl('button', 'nsb-build-btn', '↓ Build Composition');
  buildBtn.type = 'button';
  var buildHint = mkEl('span', 'nsb-build-hint', 'Pushes to the Composition step below');
  buildRow.appendChild(buildBtn);
  buildRow.appendChild(buildHint);
  wrap.appendChild(buildRow);

  buildBtn.addEventListener('click', buildComposition);

  // ── Add / remove characters ───────────────────────────────────────────────
  function addCharacter() {
    var id = 'c' + (++charIdSeq);
    var colorIdx = characters.length % CHAR_COLORS.length;
    var total = characters.length + 1;
    var c = {
      id: id, label: 'Character ' + charIdSeq, color: CHAR_COLORS[colorIdx],
      orientId: '', orientFree: '', desc: '', manualPose: '', imageDataUrl: null, imageDesc: '',
      bbox: defaultBboxForIndex(characters.length, total)
    };
    characters.push(c);
    // Recompute bboxes for all characters
    characters.forEach(function (ch, i) { ch.bbox = defaultBboxForIndex(i, characters.length); });
    renderCharCard(c);
    updateCharsCount();
    schedulePush();
  }

  addBtn.addEventListener('click', addCharacter);

  function removeCharacter(id) {
    characters = characters.filter(function (c) { return c.id !== id; });
    var card = charList.querySelector('[data-char-id="' + id + '"]');
    if (card) card.remove();
    characters.forEach(function (ch, i) { ch.bbox = defaultBboxForIndex(i, characters.length); });
    updateCharsCount();
    schedulePush();
  }

  function renderCharCard(c) {
    var card = mkEl('div', 'nsb-char-card');
    card.dataset.charId = c.id;
    card.style.setProperty('--char-color', c.color);

    // Header
    var cardHdr = mkEl('div', 'nsb-char-hdr');
    var dot = mkEl('span', 'nsb-char-dot');
    dot.style.background = c.color;
    var nameSp = mkEl('span', 'nsb-char-name', escH(c.label));

    var nameInput = document.createElement('input');
    nameInput.type = 'text'; nameInput.className = 'nsb-char-name-input';
    nameInput.value = c.label; nameInput.placeholder = 'Character name';
    nameInput.addEventListener('input', function () {
      c.label = nameInput.value;
      schedulePush();
    });

    var rmBtn = mkEl('button', 'nsb-char-rm', '✕');
    rmBtn.type = 'button'; rmBtn.title = 'Remove character';

    cardHdr.appendChild(dot);
    cardHdr.appendChild(nameInput);
    cardHdr.appendChild(rmBtn);
    card.appendChild(cardHdr);
    rmBtn.addEventListener('click', function () { removeCharacter(c.id); });

    // Body
    var body = mkEl('div', 'nsb-char-body');

    // Image drop
    var charDrop = makeCompactDrop({
      placeholder: 'Character reference image',
      describeType: 'character',
      onDataUrl: function (url) {
        c.imageDataUrl = url || null;
        schedulePush();
      },
      onDesc: function (desc, forced) {
        c.imageDesc = desc;
        if (forced || !descTa.value.trim()) { descTa.value = desc; c.desc = desc; }
        schedulePush();
      }
    });
    body.appendChild(charDrop);

    // Orientation chips
    var orLabel = mkEl('p', 'nsb-field-label', 'Orientation');
    body.appendChild(orLabel);

    var chips = mkEl('div', 'nsb-chips');
    ORIENT_PRESETS.forEach(function (opt) {
      var chip = mkEl('button', 'nsb-chip', escH(opt.label));
      chip.type = 'button';
      chip.dataset.orient = opt.id;
      chip.addEventListener('click', function () {
        chips.querySelectorAll('.nsb-chip').forEach(function (ch) { ch.classList.remove('is-active'); });
        chip.classList.add('is-active');
        c.orientId = opt.id;
        freeRow.style.display = opt.id === 'free' ? 'block' : 'none';
        schedulePush();
      });
      chips.appendChild(chip);
    });
    body.appendChild(chips);

    var freeRow = mkEl('div', '');
    freeRow.style.display = 'none';
    var freeIn = document.createElement('input');
    freeIn.type = 'text'; freeIn.className = 'nsb-free-input';
    freeIn.placeholder = 'e.g. kneeling, looking up at camera';
    freeIn.addEventListener('input', function () { c.orientFree = freeIn.value; schedulePush(); });
    freeRow.appendChild(freeIn);
    body.appendChild(freeRow);

    // Pose — only shown while "Include pose" is off (Characters panel
    // toggle). When pose describing is disabled, the vision model was told
    // to skip it entirely, so this manual field is what carries it into
    // buildJson()'s per-character desc instead.
    var poseRow = mkEl('div', 'nsb-char-pose-row');
    poseRow.style.display = includeCharacterPose ? 'none' : '';
    var poseLabel = mkEl('p', 'nsb-field-label', 'Pose');
    poseRow.appendChild(poseLabel);
    var poseTa = mkEl('textarea', 'nsb-textarea');
    poseTa.rows = 2; poseTa.placeholder = 'e.g. cross-legged, hands resting near her hips…';
    poseTa.addEventListener('input', function () { c.manualPose = poseTa.value; schedulePush(); });
    poseRow.appendChild(poseTa);
    body.appendChild(poseRow);

    // Description
    var descLabel = mkEl('p', 'nsb-field-label', 'Description');
    body.appendChild(descLabel);
    var descTa = mkEl('textarea', 'nsb-textarea');
    descTa.rows = 2; descTa.placeholder = 'Appearance, clothing…';
    descTa.addEventListener('input', function () { c.desc = descTa.value; schedulePush(); });
    body.appendChild(descTa);

    card.appendChild(body);
    charList.appendChild(card);
  }

  // Start with one character by default
  addCharacter();
}

// ── ideogram_composer ──────────────────────────────────────────────────────
