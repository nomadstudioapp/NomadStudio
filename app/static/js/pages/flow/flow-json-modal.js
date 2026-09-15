'use strict';
// JSON editor: openJsonModal, closeJsonModal, _jsonTemplate, _buildPromptFromJson, _renderJsonRows, _applyJsonModal, _updateJsonPreview
// Rendered into the shared lateral options panel (flow-options-panel.js)
// instead of its own centered modal — same pattern as Aspect ratio / Advanced.

var _jsonActiveStep = null;
var _jsonPanelRowsEl = null;

function openJsonModal(stepDef) {
  _jsonActiveStep = stepDef;
  openOptionsPanel(stepDef.label || 'JSON Prompt', function (body) {
    _renderJsonRows(stepDef, body);
  });
}

function closeJsonModal() {
  closeOptionsPanel();
  _jsonActiveStep = null;
  _jsonPanelRowsEl = null;
}

// Returns the active template: dynamically parsed > static from flow JSON > empty
function _jsonTemplate(stepDef) {
  return stepDef._jsonCurrentTemplate || stepDef.template || {};
}

// Build the positive prompt from a JSON object:
// uses 'positive' key directly if present, otherwise concatenates all string values
// (skipping known technical/non-prompt keys like negative, seed, steps, cfg…)
var _JSON_SKIP = { negative: 1, seed: 1, steps: 1, cfg: 1, width: 1, height: 1, num_images: 1, denoise: 1 };
// The JSON block of a json_input step is sent to the engine verbatim as the
// POSITIVE prompt — braces, keys and all (`basicValues.positive` maps straight
// to `steps.vars.output._json_text`). So a "negative" key inside it does the
// opposite of what it says: it asks the model for exactly what the user wanted
// excluded. Confirmed by reading the ComfyUI graph embedded in a generated
// image, where the positive contained
//   "negative":"text, watermark, harsh flash, oversaturated colour"
//
// The negative always belongs in the negative. These two helpers take it out of
// the block and put it where it goes.
var _jsonNegApplied = '';

function _splitJsonNegative(obj) {
  var clean = {};
  var negative = '';
  Object.keys(obj || {}).forEach(function (k) {
    if (String(k).toLowerCase() === 'negative') {
      var v = obj[k];
      if (typeof v === 'string') negative = v.trim();
      else if (Array.isArray(v)) {
        negative = v.filter(function (x) { return typeof x === 'string' && x; }).join(', ');
      }
      return;
    }
    clean[k] = obj[k];
  });
  return { clean: clean, negative: negative };
}

// Recorded, never written into `selectedNegativePrompt`. That global is reset
// from several places (flow-state.js clears it, the workflow picker refills it
// from the import's own tuned negative), so mutating it from here raced with
// those resets and the workflow's negative ended up wiped. Keeping the
// JSON-derived part separate and merging it once, at submit, has no such race
// and cannot stack on repeated edits.
function _applyJsonNegative(negative) {
  _jsonNegApplied = negative || '';
}

// The negative actually sent: the workflow's own, plus whatever the JSON block
// declared. Used by the generation path instead of `selectedNegativePrompt`
// alone.
function effectiveNegativePrompt() {
  var base = (typeof selectedNegativePrompt === 'string' ? selectedNegativePrompt : '') || '';
  var extra = _jsonNegApplied || '';
  if (!extra) return base;
  if (base.indexOf(extra) >= 0) return base;
  return base ? base.replace(/\s*,\s*$/, '') + ', ' + extra : extra;
}

function _buildPromptFromJson(obj) {
  if (!obj || typeof obj !== 'object') return '';
  if (typeof obj.positive === 'string' && obj.positive) return obj.positive;
  var parts = [];
  Object.keys(obj).forEach(function (k) {
    if (_JSON_SKIP[k]) return;
    var v = obj[k];
    if (typeof v === 'string' && v) parts.push(v);
    else if (Array.isArray(v)) {
      var strs = v.filter(function (x) { return typeof x === 'string' && x; });
      if (strs.length) parts.push(strs.join(', '));
    }
  });
  return parts.join(', ');
}

// bodyEl: the panel body passed by openOptionsPanel's fillFn.
// ── Nested section editor ──────────────────────────────────────────────────
// The panel used to render one row per TOP-LEVEL key and stringify whatever it
// found there. With a flat template that worked. With the Ideogram structure
// this flow now ships it did not merely fall short — it corrupted the JSON:
// `style_description` and `compositional_deconstruction` rendered as the
// literal text "[object Object]", and pressing Apply wrote that string back
// over the real object.
//
// So the editor walks the structure instead, one predefined section at a time:
//
//   scalar at the top          -> a row
//   object at the top          -> a titled section of rows
//   array of scalars           -> one row, comma separated (color_palette)
//   array of objects           -> a numbered sub-section each (elements[])
//
// Anything deeper is left alone on purpose: the working copy is a full clone of
// the real object and Apply only writes the paths it rendered, so a structure
// the editor doesn't understand survives untouched rather than being flattened.
//
// Editing a value is not enough on its own. Blanking `color_palette` leaves
// `"color_palette": []` in the block, which still tells the engine something —
// removing the key is a different instruction from emptying it. Hence the ×
// per row and per array element, working against the same clone.

var _jsonWorking = null;     // the object being edited, committed on Apply
var _jsonPanelBodyEl = null; // kept so a delete can re-render in place

function _jsonCurrentObject(stepDef) {
  var live = getVal(stepDef.id, 'json_data');
  if (live && typeof live === 'object' && !Array.isArray(live)) return live;
  return _jsonTemplate(stepDef);
}

function _jsonClone(value) {
  return JSON.parse(JSON.stringify(value === undefined ? null : value));
}

function _jsonSetAtPath(root, path, value) {
  var parts = path.split('.');
  var node = root;
  for (var i = 0; i < parts.length - 1; i++) {
    var key = parts[i];
    var nextIsIndex = /^\d+$/.test(parts[i + 1]);
    if (node[key] === undefined || node[key] === null || typeof node[key] !== 'object') {
      node[key] = nextIsIndex ? [] : {};
    }
    node = node[key];
  }
  node[parts[parts.length - 1]] = value;
}

// Removing a key is not the same as emptying it, and removing an array element
// must close the gap rather than leave a hole — splice, not delete.
function _jsonDeleteAtPath(root, path) {
  var parts = path.split('.');
  var node = root;
  for (var i = 0; i < parts.length - 1; i++) {
    if (!node || typeof node !== 'object') return;
    node = node[parts[i]];
  }
  if (!node || typeof node !== 'object') return;
  var last = parts[parts.length - 1];
  if (Array.isArray(node) && /^\d+$/.test(last)) node.splice(Number(last), 1);
  else delete node[last];
}

function _jsonKindOf(value) {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (Array.isArray(value) && value.every(function (v) { return typeof v !== 'object' || v === null; })) return 'list';
  return 'string';
}

var _JSON_X_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" ' +
  'stroke-width="1.6" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
var _JSON_DICE_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" ' +
  'stroke-width="1.4" stroke-linejoin="round"><rect x="2.5" y="2.5" width="11" height="11" rx="2.5"/>' +
  '<circle cx="6" cy="6" r="0.9" fill="currentColor" stroke="none"/>' +
  '<circle cx="10" cy="10" r="0.9" fill="currentColor" stroke="none"/></svg>';

function _jsonIconBtn(cls, label, svg) {
  var b = document.createElement('button');
  b.type = 'button';
  b.className = 'ncf-json-row-btn ' + cls;
  b.setAttribute('aria-label', label);
  b.title = label;
  b.innerHTML = svg;
  return b;
}

// Re-roll one value with the local model. The endpoint and its api.js helper
// both survived the deletion of the old editor — only the button was lost, so
// this is a rewire, not a rebuild. It gets the whole current object as context
// so the new value fits the rest of the block instead of being generated blind.
async function _jsonRerollField(stepDef, path, kind, control, btn) {
  if (!window.openJourneyApi || !window.openJourneyApi.regenerateJsonFieldWithLmStudio) return;
  btn.disabled = true;
  btn.classList.add('is-busy');
  try {
    var res = await window.openJourneyApi.regenerateJsonFieldWithLmStudio({
      path: path,
      fieldType: kind === 'list' ? 'array' : kind,
      currentValue: _jsonReadControl(control),
      currentJson: _jsonWorking,
    });
    var value = res && res.value;
    control.value = (kind === 'list' && Array.isArray(value))
      ? value.join(', ')
      : (value == null ? '' : String(value));
    _jsonSetAtPath(_jsonWorking, path, _jsonReadControl(control));
  } catch (err) {
    if (typeof showErrorToast === 'function') {
      showErrorToast('Could not regenerate ' + path + ': ' + (err.message || 'LM Studio error'));
    }
  } finally {
    btn.disabled = false;
    btn.classList.remove('is-busy');
  }
}

function _jsonFieldRow(stepDef, label, path, value, kind) {
  var row = document.createElement('div');
  row.className = 'ncf-json-row';

  var lbl = document.createElement('label');
  lbl.className = 'ncf-json-row-label';
  lbl.setAttribute('for', 'ncf-jf-' + path);
  lbl.textContent = label;
  row.appendChild(lbl);

  var control;
  if (kind === 'boolean') {
    control = document.createElement('select');
    ['true', 'false'].forEach(function (v) {
      var o = document.createElement('option');
      o.value = v; o.textContent = v;
      control.appendChild(o);
    });
    control.value = value ? 'true' : 'false';
  } else {
    var text = kind === 'list'
      ? (Array.isArray(value) ? value.join(', ') : String(value == null ? '' : value))
      : String(value == null ? '' : value);
    if (kind !== 'number' && text.length > 90) {
      control = document.createElement('textarea');
      control.rows = 3;
      control.className = 'ncf-json-row-textarea';
    } else {
      control = document.createElement('input');
      control.type = kind === 'number' ? 'number' : 'text';
      control.step = (kind === 'number' && Number.isInteger(value)) ? '1' : 'any';
      if (kind !== 'number') control.removeAttribute('step');
    }
    control.value = text;
  }
  control.classList.add('nsc-input', 'ncf-json-row-input');
  control.id = 'ncf-jf-' + path;
  control.dataset.path = path;
  control.dataset.kind = kind;
  // Keep the working copy current as you type, so a re-roll elsewhere sees the
  // block as it stands rather than as it was when the panel opened.
  control.addEventListener('input', function () {
    _jsonSetAtPath(_jsonWorking, path, _jsonReadControl(control));
  });
  row.appendChild(control);

  var actions = document.createElement('span');
  actions.className = 'ncf-json-row-actions';

  var dice = _jsonIconBtn('ncf-json-row-reroll', 'Regenerate ' + path + ' with AI', _JSON_DICE_SVG);
  dice.addEventListener('click', function () { _jsonRerollField(stepDef, path, kind, control, dice); });
  actions.appendChild(dice);

  var del = _jsonIconBtn('ncf-json-row-delete', 'Remove ' + path, _JSON_X_SVG);
  del.addEventListener('click', function () {
    _jsonDeleteAtPath(_jsonWorking, path);
    _jsonRerender(stepDef);
  });
  actions.appendChild(del);

  row.appendChild(actions);
  return row;
}

function _jsonSection(title, onDelete) {
  var sec = document.createElement('div');
  sec.className = 'ncf-json-section';
  var head = document.createElement('div');
  head.className = 'ncf-json-section-head';
  var h = document.createElement('p');
  h.className = 'ncf-json-section-title';
  h.textContent = title;
  head.appendChild(h);
  if (onDelete) {
    var del = _jsonIconBtn('ncf-json-row-delete', 'Remove ' + title, _JSON_X_SVG);
    del.addEventListener('click', onDelete);
    head.appendChild(del);
  }
  sec.appendChild(head);
  return sec;
}

function _jsonRenderLeaves(stepDef, obj, prefix, host) {
  Object.keys(obj).forEach(function (key) {
    var value = obj[key];
    var path = prefix ? prefix + '.' + key : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) return;
    if (Array.isArray(value) && value.some(function (v) { return v && typeof v === 'object'; })) return;
    host.appendChild(_jsonFieldRow(stepDef, key, path, value, _jsonKindOf(value)));
  });
}

function _jsonRerender(stepDef) {
  if (!_jsonPanelBodyEl) return;
  _jsonPanelBodyEl.innerHTML = '';
  _renderJsonRows(stepDef, _jsonPanelBodyEl, true);
}

function _renderJsonRows(stepDef, bodyEl, keepWorking) {
  _jsonPanelBodyEl = bodyEl;
  if (!keepWorking || !_jsonWorking) _jsonWorking = _jsonClone(_jsonCurrentObject(stepDef));

  var rowsEl = document.createElement('div');
  rowsEl.className = 'ncf-json-rows';
  var current = _jsonWorking;

  if (!current || !Object.keys(current).length) {
    rowsEl.innerHTML = '<p style="padding:0.8rem 1rem;font-size:0.74rem;color:var(--muted)">Paste or load a JSON first.</p>';
    bodyEl.appendChild(rowsEl);
    _jsonPanelRowsEl = rowsEl;
    return;
  }

  _jsonRenderLeaves(stepDef, current, '', rowsEl);

  Object.keys(current).forEach(function (key) {
    var value = current[key];

    if (value && typeof value === 'object' && !Array.isArray(value)) {
      var sec = _jsonSection(key.replace(/_/g, ' '), function () {
        _jsonDeleteAtPath(_jsonWorking, key);
        _jsonRerender(stepDef);
      });
      _jsonRenderLeaves(stepDef, value, key, sec);
      Object.keys(value).forEach(function (sub) {
        var subVal = value[sub];
        if (!Array.isArray(subVal) || !subVal.some(function (v) { return v && typeof v === 'object'; })) return;
        subVal.forEach(function (item, idx) {
          if (!item || typeof item !== 'object') return;
          var itemPath = key + '.' + sub + '.' + idx;
          var itemSec = _jsonSection(sub.replace(/_/g, ' ') + ' ' + (idx + 1), function () {
            _jsonDeleteAtPath(_jsonWorking, itemPath);
            _jsonRerender(stepDef);
          });
          itemSec.classList.add('ncf-json-section--nested');
          _jsonRenderLeaves(stepDef, item, itemPath, itemSec);
          sec.appendChild(itemSec);
        });
      });
      rowsEl.appendChild(sec);
      return;
    }

    if (Array.isArray(value) && value.some(function (v) { return v && typeof v === 'object'; })) {
      var arrSec = _jsonSection(key.replace(/_/g, ' '), function () {
        _jsonDeleteAtPath(_jsonWorking, key);
        _jsonRerender(stepDef);
      });
      value.forEach(function (item, idx) {
        if (!item || typeof item !== 'object') return;
        var p = key + '.' + idx;
        var itemSec = _jsonSection(key.replace(/_/g, ' ') + ' ' + (idx + 1), function () {
          _jsonDeleteAtPath(_jsonWorking, p);
          _jsonRerender(stepDef);
        });
        itemSec.classList.add('ncf-json-section--nested');
        _jsonRenderLeaves(stepDef, item, p, itemSec);
        arrSec.appendChild(itemSec);
      });
      rowsEl.appendChild(arrSec);
    }
  });

  bodyEl.appendChild(rowsEl);
  _jsonPanelRowsEl = rowsEl;

  var footer = document.createElement('div');
  footer.className = 'ncf-json-panel-footer';
  var resetBtn = document.createElement('button');
  resetBtn.type = 'button';
  resetBtn.className = 'nse-modal-secondary';
  resetBtn.textContent = 'Reset';
  resetBtn.addEventListener('click', _resetJsonModal);
  var applyBtn = document.createElement('button');
  applyBtn.type = 'button';
  applyBtn.className = 'nse-modal-apply';
  applyBtn.textContent = 'Apply';
  applyBtn.addEventListener('click', _applyJsonModal);
  footer.appendChild(resetBtn);
  footer.appendChild(applyBtn);
  bodyEl.appendChild(footer);

  var first = rowsEl.querySelector('input, textarea');
  if (first) first.focus();
}

function _jsonReadControl(el) {
  var kind = el.dataset.kind;
  if (kind === 'boolean') return el.value === 'true';
  if (kind === 'number') {
    var n = Number(el.value);
    return isNaN(n) ? 0 : n;
  }
  if (kind === 'list') {
    return el.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  }
  return el.value;
}

function _applyJsonModal() {
  if (!_jsonActiveStep || !_jsonPanelRowsEl) { closeJsonModal(); return; }
  var stepDef = _jsonActiveStep;

  var assembled = _jsonClone(_jsonWorking || _jsonCurrentObject(stepDef));
  _jsonPanelRowsEl.querySelectorAll('[data-path]').forEach(function (el) {
    _jsonSetAtPath(assembled, el.dataset.path, _jsonReadControl(el));
  });

  var split = _splitJsonNegative(assembled);
  var jsonText = JSON.stringify(split.clean, null, 2);

  setVal(stepDef.id, 'json_data', split.clean);
  Object.keys(split.clean).forEach(function (k) { setVal(stepDef.id, k, split.clean[k]); });
  setVal(stepDef.id, '_prompt', _buildPromptFromJson(split.clean));
  setVal(stepDef.id, '_json_text', jsonText);
  _applyJsonNegative(split.negative);

  // Put it back in the textarea too, or the panel and the box disagree about
  // what the prompt is — and the box is the one the user believes.
  var ta = document.getElementById('ncf-json-ta-' + stepDef.id);
  if (ta) {
    ta.value = jsonText;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  }

  _jsonWorking = null;
  _updateJsonPreview(stepDef);
  pushPromptHistory(stepDef.id, jsonText);
  closeJsonModal();
}

function _resetJsonModal() {
  if (!_jsonActiveStep) return;
  _jsonWorking = _jsonClone(_jsonTemplate(_jsonActiveStep));
  _jsonRerender(_jsonActiveStep);
}

function _updateJsonPreview(stepDef) {
  var preview = document.getElementById('ncf-json-preview-' + stepDef.id);
  if (!preview) return;
  var template = _jsonTemplate(stepDef);
  var keys = Object.keys(template);
  if (!keys.length) { preview.innerHTML = ''; return; }
  var html = keys.map(function (k) {
    var v = getVal(stepDef.id, k);
    if (v === undefined || v === null) v = template[k];
    var vs = String((v !== null && v !== undefined) ? v : '');
    if (vs.length > 42) vs = vs.slice(0, 40) + '…';
    return '<div class="ncf-json-preview-row">' +
      '<span class="ncf-json-preview-key">' + escHtml(k) + '</span>' +
      '<span class="ncf-json-preview-sep">:</span>' +
      '<span class="ncf-json-preview-val">' + escHtml(vs) + '</span>' +
      '</div>';
  }).join('');
  preview.innerHTML = html;
}

// ══════════════════════════════════════════════════════════════════════════
// QUALITY PRESETS (Scenes pattern)
// ══════════════════════════════════════════════════════════════════════════
