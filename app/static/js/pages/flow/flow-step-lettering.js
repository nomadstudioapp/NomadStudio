'use strict';
// Step: lettering_builder → renderLetteringBuilder

function renderLetteringBuilder(stepDef, el) {
  var attributes = Array.isArray(stepDef.attributes)  ? stepDef.attributes  : [];
  var elementIds = Array.isArray(stepDef.element_ids) ? stepDef.element_ids : ['main_title', 'subtitle', 'tagline'];
  var elementList = [];  // [{ id, text, attrs }]

  var wrap = document.createElement('div');
  wrap.className = 'ncf-lettering-builder';

  // ── build desc string from selected attrs ──────────────────────────────
  function buildDesc(attrs) {
    var parts = [];
    attributes.forEach(function (attrDef) {
      var val = attrs[attrDef.id];
      if (!val || (Array.isArray(val) && !val.length)) return;
      var strVal = Array.isArray(val) ? val.join(' + ') : val;
      var suffix = attrDef.id === 'material'        ? ' texture'
                 : attrDef.id === 'color_treatment' ? ' color treatment'
                 : attrDef.id === 'era'             ? ' aesthetic'
                 : attrDef.id === 'effect'          ? ' effect'
                 : '';
      parts.push(strVal + suffix);
    });
    return parts.join(', ');
  }

  // ── sync all element values to stepValues ──────────────────────────────
  function syncOutput() {
    var out = elementList.map(function (item) {
      var desc = (item.stylePrompt && item.stylePrompt.trim()) ? item.stylePrompt.trim() : buildDesc(item.attrs);
      return { id: item.id, text: item.text, desc: desc, attrs: item.attrs };
    }).filter(function (item) { return item.text.trim(); });
    setVal(stepDef.id, 'lettering_elements', out);
    updateGenerateBtn();
  }

  // ── collapsible section helper ─────────────────────────────────────────
  function makeSection(label, expanded) {
    var sec = document.createElement('div');
    sec.className = 'ncf-lettering-section';
    var hd = document.createElement('button');
    hd.type = 'button';
    hd.className = 'ncf-lettering-section-hd';
    hd.innerHTML =
      '<svg class="ncf-lettering-chevron" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6l4 4 4-4"/></svg>' +
      '<span>' + label + '</span>';
    var body = document.createElement('div');
    body.className = 'ncf-lettering-section-body';
    if (!expanded) { body.style.display = 'none'; hd.classList.add('is-collapsed'); }
    hd.addEventListener('click', function () {
      var open = body.style.display !== 'none';
      body.style.display = open ? 'none' : '';
      hd.classList.toggle('is-collapsed', !open);
    });
    sec.appendChild(hd);
    sec.appendChild(body);
    return { sec: sec, body: body };
  }

  // ── render one element card ────────────────────────────────────────────
  function renderElementCard(item) {
    // Ensure extended fields exist
    if (!('referenceImage' in item)) item.referenceImage = '';
    if (!('referenceDesc'  in item)) item.referenceDesc  = '';
    if (!('stylePrompt'    in item)) item.stylePrompt    = buildDesc(item.attrs);
    if (!('_promptDirty'   in item)) item._promptDirty   = false;

    var card = document.createElement('div');
    card.className = 'ncf-lettering-card';

    // ── Header: role select + text input + remove ──────────────────────
    var header = document.createElement('div');
    header.className = 'ncf-lettering-card-header';

    var roleWrap = document.createElement('div');
    roleWrap.className = 'nsc-select-wrapper ncf-lettering-role-wrap';
    var roleSelect = document.createElement('select');
    roleSelect.className = 'nsc-select';
    elementIds.forEach(function (eid) {
      var opt = document.createElement('option');
      opt.value = eid;
      opt.textContent = eid.replace(/_/g, ' ');
      opt.selected = eid === item.id;
      roleSelect.appendChild(opt);
    });
    roleSelect.addEventListener('change', function () { item.id = roleSelect.value; syncOutput(); });
    roleWrap.appendChild(roleSelect);
    header.appendChild(roleWrap);

    var textInput = document.createElement('input');
    textInput.type = 'text';
    textInput.className = 'ncf-lettering-text-input nsc-input';
    textInput.placeholder = tF('Text content…');
    textInput.value = item.text || '';
    textInput.addEventListener('input', function () { item.text = textInput.value; syncOutput(); });
    header.appendChild(textInput);

    var removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'ncf-lettering-remove-btn';
    removeBtn.title = tF('Remove');
    removeBtn.innerHTML = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    removeBtn.addEventListener('click', function () { elementList = elementList.filter(function (it) { return it !== item; }); card.remove(); syncOutput(); });
    header.appendChild(removeBtn);
    card.appendChild(header);

    // ── Reference section (collapsed by default) ───────────────────────
    var refSection = makeSection('Reference', false);
    card.appendChild(refSection.sec);

    var refZone = document.createElement('div');
    refZone.className = 'ncf-lettering-ref-zone' + (item.referenceImage ? ' has-image' : '');
    var refInput = document.createElement('input');
    refInput.type = 'file';
    refInput.accept = 'image/*';
    refInput.style.display = 'none';
    refZone.appendChild(refInput);

    var refImg = document.createElement('img');
    refImg.className = 'ncf-lettering-ref-img';
    refImg.style.display = item.referenceImage ? 'block' : 'none';
    if (item.referenceImage) refImg.src = item.referenceImage;
    refZone.appendChild(refImg);

    var refPlaceholder = document.createElement('div');
    refPlaceholder.className = 'ncf-lettering-ref-placeholder';
    refPlaceholder.style.display = item.referenceImage ? 'none' : 'flex';
    refPlaceholder.innerHTML =
      '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>' +
      '<span>' + escHtml(tF('Drop or click to add a style reference image')) + '</span>';
    refZone.appendChild(refPlaceholder);

    var refStatus = document.createElement('div');
    refStatus.className = 'ncf-lettering-ref-status';
    refStatus.style.display = 'none';
    refSection.body.appendChild(refZone);
    refSection.body.appendChild(refStatus);

    // analyze reference image via vision model
    function analyzeRefImage(dataUrl) {
      refStatus.style.display = 'block';
      refStatus.textContent = tF('Analyzing style…');
      fetch('/api/models/chat/describe-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ imageDataUrl: dataUrl, describeType: 'typography' }),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.error) { refStatus.textContent = '⚠ ' + d.error; return; }
          var desc = (d.description || '').trim();
          item.referenceDesc = desc;
          if (!item._promptDirty) {
            item.stylePrompt = desc;
            stylePromptTa.value = desc;
          }
          refStatus.textContent = tF('✓ Style analyzed');
          syncOutput();
        })
        .catch(function (err) { refStatus.textContent = tF('⚠ Analysis failed'); });
    }

    function loadRefFile(file) {
      if (!file || !file.type.startsWith('image/')) return;
      var reader = new FileReader();
      reader.onload = function (e) {
        item.referenceImage = e.target.result;
        refImg.src = item.referenceImage;
        refImg.style.display = 'block';
        refPlaceholder.style.display = 'none';
        refZone.classList.add('has-image');
        analyzeRefImage(item.referenceImage);
      };
      reader.readAsDataURL(file);
    }

    refZone.addEventListener('click', function (e) {
      if (e.target === refImg) return; // clicking the image itself doesn't re-open picker
      refInput.click();
    });
    refInput.addEventListener('change', function () { loadRefFile(refInput.files[0]); });
    refZone.addEventListener('dragover', function (e) { e.preventDefault(); refZone.classList.add('drag-over'); });
    refZone.addEventListener('dragleave', function () { refZone.classList.remove('drag-over'); });
    refZone.addEventListener('drop', function (e) {
      e.preventDefault();
      refZone.classList.remove('drag-over');
      loadRefFile(e.dataTransfer.files[0]);
    });

    // clear reference image on right-click
    refImg.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      item.referenceImage = '';
      item.referenceDesc  = '';
      refImg.src = '';
      refImg.style.display = 'none';
      refPlaceholder.style.display = 'flex';
      refZone.classList.remove('has-image');
      refStatus.style.display = 'none';
      syncOutput();
    });

    // ── Properties section (expanded by default) ───────────────────────
    var propSection = makeSection('Properties', true);
    card.appendChild(propSection.sec);

    var attrsGrid = document.createElement('div');
    attrsGrid.className = 'ncf-lettering-attrs-grid';

    attributes.forEach(function (attrDef) {
      var curVal = item.attrs[attrDef.id];
      if (!curVal || Array.isArray(curVal)) {
        item.attrs[attrDef.id] = Array.isArray(curVal) && curVal.length
          ? curVal[0]
          : (attrDef.default || attrDef.options[0]);
      }
      var cell = document.createElement('div');
      cell.className = 'ncf-lettering-attr-cell';
      var lbl = document.createElement('label');
      lbl.className = 'ncf-lettering-attr-label';
      lbl.textContent = attrDef.label;
      cell.appendChild(lbl);
      var selWrap = document.createElement('div');
      selWrap.className = 'nsc-select-wrapper';
      var sel = document.createElement('select');
      sel.className = 'nsc-select';
      attrDef.options.forEach(function (opt) {
        var o = document.createElement('option');
        o.value = opt;
        o.textContent = opt;
        o.selected = item.attrs[attrDef.id] === opt;
        sel.appendChild(o);
      });
      sel.addEventListener('change', function () {
        item.attrs[attrDef.id] = sel.value;
        // If not dirty and no reference, update style prompt from attrs
        if (!item._promptDirty && !item.referenceDesc) {
          item.stylePrompt = buildDesc(item.attrs);
          stylePromptTa.value = item.stylePrompt;
        }
        syncOutput();
      });
      selWrap.appendChild(sel);
      cell.appendChild(selWrap);
      attrsGrid.appendChild(cell);
    });
    propSection.body.appendChild(attrsGrid);

    // ── Style prompt ────────────────────────────────────────────────────
    var styleRow = document.createElement('div');
    styleRow.className = 'ncf-lettering-style-row';
    var styleLbl = document.createElement('span');
    styleLbl.className = 'ncf-lettering-style-lbl';
    styleLbl.textContent = tF('Letter style');
    var resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'ncf-lettering-style-reset';
    resetBtn.textContent = tF('Reset');
    resetBtn.title = tF('Regenerate from reference / properties');
    resetBtn.addEventListener('click', function () {
      item._promptDirty = false;
      item.stylePrompt = item.referenceDesc || buildDesc(item.attrs);
      stylePromptTa.value = item.stylePrompt;
      syncOutput();
    });
    styleRow.appendChild(styleLbl);
    styleRow.appendChild(resetBtn);
    card.appendChild(styleRow);

    var stylePromptTa = document.createElement('textarea');
    stylePromptTa.className = 'ncf-lettering-style-prompt';
    stylePromptTa.rows = 2;
    stylePromptTa.placeholder = tF('Letter style description (auto-filled from reference or properties)…');
    stylePromptTa.value = item.stylePrompt || '';
    stylePromptTa.addEventListener('input', function () {
      item.stylePrompt = stylePromptTa.value;
      item._promptDirty = true;
      syncOutput();
    });
    card.appendChild(stylePromptTa);

    return card;
  }

  // ── add new element ────────────────────────────────────────────────────
  function addElement(id) {
    var attrs = {};
    attributes.forEach(function (attrDef) {
      attrs[attrDef.id] = attrDef.multi
        ? (attrDef.default ? [attrDef.default] : [])
        : (attrDef.default || attrDef.options[0]);
    });
    var item = { id: id || elementIds[0], text: '', attrs: attrs };
    elementList.push(item);
    var card = renderElementCard(item);
    cardsContainer.insertBefore(card, addBtn);
    syncOutput();
    var ti = card.querySelector('.ncf-lettering-text-input');
    if (ti) ti.focus();
  }

  // ── container ──────────────────────────────────────────────────────────
  var cardsContainer = document.createElement('div');
  cardsContainer.className = 'ncf-lettering-cards';

  var addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'ncf-lettering-add-btn';
  addBtn.innerHTML = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> ' + tH('Add text element');
  addBtn.addEventListener('click', function () {
    var usedIds = elementList.map(function (it) { return it.id; });
    var nextId = elementIds.find(function (eid) { return usedIds.indexOf(eid) === -1; }) || elementIds[0];
    addElement(nextId);
  });
  cardsContainer.appendChild(addBtn);
  wrap.appendChild(cardsContainer);
  el.appendChild(wrap);

  addElement(elementIds[0]);
}

// ── upscale_picker ─────────────────────────────────────────────────────────
