'use strict';
// Step: upscale_picker → renderUpscalePicker

function renderUpscalePicker(stepDef, el) {
  var wrapper = document.createElement('div');
  wrapper.className = 'nsc-select-wrapper';
  var select = document.createElement('select');
  select.className = 'nsc-select';
  select.id = 'ncf-upscale-select-' + stepDef.id;
  select.innerHTML = '<option value="">' + escHtml(tF('Loading upscale workflows…')) + '</option>';
  wrapper.appendChild(select);
  wrapper.insertAdjacentHTML('beforeend',
    '<svg class="nsc-select-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>');
  el.appendChild(wrapper);
  var hint = mkHint('');
  el.appendChild(hint);

  select.addEventListener('change', function () {
    setVal(stepDef.id, 'model_id', select.value);
    var chosen = select.options[select.selectedIndex];
    hint.textContent = chosen ? (chosen.dataset.hint || '') : '';
    updateGenerateBtn();
  });

  fetch('/api/models/upscale/settings')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var models = Array.isArray(data.models) ? data.models : [];
      if (!models.length) {
        select.innerHTML = '<option value="">' + escHtml(tF('No upscale workflows — import one first')) + '</option>';
        hint.textContent = tF('Import an upscale ComfyUI workflow from Models › Import.');
        return;
      }
      select.innerHTML = '';
      if (models.length > 1) {
        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = tF('Select upscale workflow…');
        select.appendChild(blank);
      }
      models.forEach(function (m) {
        var opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.name || m.id;
        var scale = m.fixedScale || m.defaultScale || '';
        if (scale) opt.dataset.hint = tF('Scale:') + ' ' + scale + '×';
        select.appendChild(opt);
      });

      var nameHint = (stepDef.name_hint || '').toLowerCase();
      var toSelect = null;
      if (models.length === 1 || (stepDef.auto_select_if_single && models.length === 1)) {
        toSelect = models[0];
      } else if (nameHint) {
        toSelect = models.find(function (m) {
          return (m.name || '').toLowerCase().includes(nameHint);
        }) || null;
      }
      if (!toSelect && models.length === 1) toSelect = models[0];

      if (toSelect) {
        select.value = toSelect.id;
        setVal(stepDef.id, 'model_id', toSelect.id);
        var scale = toSelect.fixedScale || toSelect.defaultScale || '';
        if (scale) hint.textContent = tF('Scale:') + ' ' + scale + '×';
        updateGenerateBtn();
      }
    })
    .catch(function () {
      select.innerHTML = '<option value="">' + escHtml(tF('Failed to load upscale workflows')) + '</option>';
    });
}

// ── workflow_params ────────────────────────────────────────────────────────
