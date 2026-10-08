'use strict';
// "Does ComfyUI have what this flow needs?" — model files and custom nodes.
//
// A flow from a package ships its ComfyUI graphs but not the model files or
// custom nodes they use; before this, a missing one only showed up as ComfyUI
// rejecting the job ("Queue rejected"). Each time a flow's steps render (and
// when its engine changes) the graphs it would run are checked against
// ComfyUI (/api/models/flows/requirements, app/services/flow_requirements.py).
// Anything missing puts a notice at the top of the steps; the notice opens a
// side panel (persistent — it stays open while files download) listing:
//   · model files, each with Download (into the ComfyUI models folder set in
//     Settings, same /api/models/imports/download-file the Setup wizard
//     uses) or, without a known address, a search link;
//   · quantization variants when none is complete — downloading one is enough;
//   · custom-node packs, with their repository and install command (they need
//     a ComfyUI restart, so the app can't install them itself).
// Downloads keep running (and keep their progress) if the panel is closed or
// replaced by another one; reopening it shows where they are.

var NcfRequirements = (function () {
  var _last = null;          // last check result
  var _lastFiles = [];       // workflow files it was for
  var _seq = 0;
  var _sizes = {};           // url → bytes
  var _free = null;          // free bytes in the models folder
  var _dl = {};              // filename(lower) → {progress, status: 'running'|'done'|'error', error}
  var _panelOpen = false;
  var _pickedVariant = {};   // quant group index → option key

  function _t(s) { return typeof tF === 'function' ? tF(s) : s; }
  function _fmt(template, vars) {
    return String(template).replace(/\{(\w+)\}/g, function (_, k) { return vars[k] != null ? vars[k] : ''; });
  }
  function _gb(bytes) {
    if (!bytes) return '';
    return bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + ' GB' : Math.max(1, Math.round(bytes / 1e6)) + ' MB';
  }
  function _el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // Graphs this flow would run right now: each step's current workflow_file
  // (an engine picker swaps it — only the selected engine is checked).
  function _workflowFiles() {
    if (typeof allSteps === 'undefined' || !Array.isArray(allSteps)) return [];
    var files = [];
    allSteps.forEach(function (s) {
      var f = (typeof getVal === 'function' && getVal(s.id, 'workflow_file')) || s.workflow_file;
      if (f && files.indexOf(f) === -1) files.push(f);
    });
    return files;
  }

  // The Upscale output pill (2xFast/4xFast/4xSharp/2x/4x, flow-render-all.js)
  // runs one more graph after the flow's own, with its model swapped in
  // (_maybeUpscaleOutput, flow-step-workflow-params.js). It is checked too,
  // with the same values, so a missing upscale model is offered for download
  // like any other file instead of failing after the image is made (#34).
  function _extraWorkflows() {
    var mode = typeof upscaleOutputMode !== 'undefined' ? upscaleOutputMode : 'none';
    if (!mode || mode === 'none') return [];
    var seedvr2 = typeof UPSCALE_OUTPUT_SEEDVR2 !== 'undefined' ? UPSCALE_OUTPUT_SEEDVR2[mode] : null;
    if (seedvr2) {
      return [{ file: 'nomad.core-refine/workflows/refine_upscale_seedvr2.json',
                values: { '66:52.unet_name': seedvr2.unetName } }];
    }
    var model = typeof UPSCALE_OUTPUT_MODELS !== 'undefined' ? UPSCALE_OUTPUT_MODELS[mode] : null;
    if (!model) return [];
    return [{ file: 'nomad.core-refine/workflows/upscale_2026/refine_upscale_model.json',
              values: { '8.model_name': model } }];
  }

  function _missingCount(r) {
    if (!r) return { files: 0, packs: 0 };
    return {
      files: (r.missingModels || 0) + (r.quantizationMissing || 0),
      packs: (r.nodePacks || []).length + ((r.unknownNodes || []).length ? 1 : 0),
    };
  }

  // ── Notice at the top of the steps ──────────────────────────────────────
  function _renderBanner() {
    var scroll = document.getElementById('ncf-steps-scroll');
    var old = document.getElementById('ncf-req-banner');
    if (old) old.remove();
    if (!scroll || !_last || _last.ok !== false || _last.comfyUnreachable) return;
    var n = _missingCount(_last);
    if (!n.files && !n.packs) return;
    var parts = [];
    if (n.files) parts.push(_fmt(_t(n.files === 1 ? '{n} model file' : '{n} model files'), { n: n.files }));
    if (n.packs) parts.push(_fmt(_t(n.packs === 1 ? '{n} custom node pack' : '{n} custom node packs'), { n: n.packs }));

    var banner = _el('div', 'ncf-req-banner');
    banner.id = 'ncf-req-banner';
    banner.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 19h16"/></svg>';
    var copy = _el('div', 'ncf-req-banner-copy');
    copy.appendChild(_el('strong', null, _t('This flow needs files ComfyUI doesn\'t have yet')));
    copy.appendChild(_el('span', null, parts.join(' · ')));
    banner.appendChild(copy);
    var btn = _el('button', 'ncf-ep-pill ncf-ep-pill--small nsc-options-trigger', null);
    btn.type = 'button';
    btn.innerHTML = '<span></span>';
    btn.querySelector('span').textContent = _t('Review');
    btn.addEventListener('click', openPanel);
    banner.appendChild(btn);
    scroll.insertBefore(banner, scroll.firstChild);
  }

  // ── Check ────────────────────────────────────────────────────────────────
  function check(opts) {
    opts = opts || {};
    var files = _workflowFiles();
    var extra = _extraWorkflows();
    var seq = ++_seq;
    if (!files.length && !extra.length) { _last = null; _lastFiles = []; _renderBanner(); return Promise.resolve(null); }
    return fetch('/api/models/flows/requirements', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflowFiles: files, extraWorkflows: extra, refresh: !!opts.refresh }),
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) {
        if (seq !== _seq || !res) return res;
        _last = res;
        _lastFiles = files;
        _renderBanner();
        _loadSizes();
        if (_panelOpen) _renderPanel();
        else if (opts.open && res.ok === false && !res.comfyUnreachable) openPanel();
        return res;
      })
      .catch(function () { return null; });
  }

  function _allDownloadable() {
    var out = [];
    if (!_last) return out;
    (_last.models || []).forEach(function (m) { if (!m.present && m.url) out.push(m); });
    (_last.quantization || []).forEach(function (g, gi) {
      if (g.installed) return;
      var opt = _variant(g, gi);
      if (opt) opt.files.forEach(function (f) { if (!f.present && f.url) out.push(f); });
    });
    return out;
  }

  function _loadSizes() {
    var urls = [];
    (_last && _last.models || []).forEach(function (m) { if (!m.present && m.url && !(m.url in _sizes)) urls.push(m.url); });
    (_last && _last.quantization || []).forEach(function (g) {
      g.options.forEach(function (o) { o.files.forEach(function (f) { if (!f.present && f.url && !(f.url in _sizes)) urls.push(f.url); }); });
    });
    if (!urls.length) return;
    urls.forEach(function (u) { _sizes[u] = null; });
    fetch('/api/setup/downloads/sizes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ urls: urls }),
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        Object.keys(res.sizes || {}).forEach(function (u) { _sizes[u] = res.sizes[u]; });
        if (res.freeBytes != null) _free = res.freeBytes;
        if (_panelOpen) _renderPanel();
      })
      .catch(function () {});
  }

  // A quant group with no complete variant: the user's pick, else the first
  // variant that can be fully downloaded.
  function _variant(group, gi) {
    var key = _pickedVariant[gi];
    var opt = group.options.filter(function (o) { return o.key === key; })[0];
    if (opt) return opt;
    return group.options.filter(function (o) { return o.files.every(function (f) { return f.present || f.url; }); })[0]
      || group.options[0];
  }

  // ── Downloads ────────────────────────────────────────────────────────────
  // One address after another (file.sources, from the models catalog — see
  // PACKAGE_FORMAT.md §8.2): a dead mirror or a file that fails the size /
  // SHA-256 check moves on to the next one. A gated model (licence to accept
  // on Hugging Face) stops right there: another mirror won't change that.
  function _downloadFrom(file, url) {
    var key = file.filename.toLowerCase();
    return fetch('/api/models/imports/download-file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: url, subfolder: file.subfolder, filename: file.filename, force: true,
        sha256: file.sha256 || null, size: file.size || null, licenseUrl: file.licenseUrl || '',
      }),
    }).then(function (resp) {
      if (!resp.ok || !resp.body) {
        return resp.json().then(function (d) { var e = new Error(d.error || ('HTTP ' + resp.status)); e.fatal = true; throw e; });
      }
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buf = '';
      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) return;
          buf += decoder.decode(chunk.value, { stream: true });
          var lines = buf.split('\n');
          buf = lines.pop();
          lines.forEach(function (line) {
            if (!line.trim()) return;
            var msg; try { msg = JSON.parse(line); } catch (_) { return; }
            if (msg.error) { var e = new Error(msg.error); e.gated = !!msg.gated; throw e; }
            if (msg.progress != null) _dl[key].progress = msg.progress;
            if (msg.ok) { _dl[key].status = 'done'; _dl[key].verified = !!msg.verified; }
          });
          _refreshRow(file);
          return pump();
        });
      }
      return pump();
    }).then(function () {
      if (_dl[key].status !== 'done') throw new Error(_t('The download stopped before the end.'));
    });
  }

  function _download(file) {
    var key = file.filename.toLowerCase();
    if (_dl[key] && _dl[key].status === 'running') return Promise.resolve();
    var urls = (file.sources && file.sources.length ? file.sources.map(function (s) { return s.url; }) : [file.url])
      .filter(Boolean);
    _dl[key] = { progress: 0, status: 'running' };
    _refreshRow(file);
    var i = 0;
    function attempt(lastErr) {
      if (i >= urls.length) return Promise.reject(lastErr || new Error(_t('No download address for this file')));
      var url = urls[i++];
      _dl[key].progress = 0;
      return _downloadFrom(file, url).catch(function (err) {
        if (err.gated || err.fatal) throw err;
        return attempt(err);
      });
    }
    return attempt().then(function () {
      _refreshRow(file);
    }).catch(function (err) {
      _dl[key] = { progress: 0, status: 'error', error: err.message || String(err), gated: !!err.gated };
      _refreshRow(file);
    });
  }

  function _downloadMany(files) {
    // One at a time: several multi-GB files in parallel only split the
    // bandwidth and make every bar crawl.
    var chain = Promise.resolve();
    files.forEach(function (f) { chain = chain.then(function () { return _download(f); }); });
    return chain.then(function () { return check({ refresh: true }); });
  }

  // ── Panel ────────────────────────────────────────────────────────────────
  function openPanel() {
    if (typeof openOptionsPanel !== 'function') return;
    openOptionsPanel(_t('Missing files'), function (body) {
      // Own wrapper: the panel body is shared, and another panel opening
      // empties it — which is how this one knows it is no longer shown.
      _panelBody = _el('div', 'ncf-req-panel');
      body.appendChild(_panelBody);
      _renderPanelInto(_panelBody);
    }, { persistent: true });
    _panelOpen = true;
  }
  var _panelBody = null;

  function _renderPanel() {
    if (!_panelBody || !_panelBody.isConnected || _panelBody.closest('[hidden]')) {
      _panelOpen = false;
      return;
    }
    _panelBody.innerHTML = '';
    _renderPanelInto(_panelBody);
  }

  function _fileRow(file) {
    var key = file.filename.toLowerCase();
    var row = _el('div', 'ncf-req-row');
    row.setAttribute('data-req-file', key);
    var copy = _el('div', 'ncf-req-copy');
    var name = _el('strong', 'ncf-req-name', file.filename);
    name.title = file.value || file.filename;
    copy.appendChild(name);
    var meta = [file.subfolder || ''];
    var bytes = file.size || (file.url && _sizes[file.url]);
    if (bytes) meta.push(_gb(bytes));
    copy.appendChild(_el('small', 'ncf-req-meta', meta.filter(Boolean).join(' · ')));
    // Licence to accept on Hugging Face first (FLUX.2 Klein 9B…): say so up
    // front instead of letting the download fail.
    if (file.gated && !file.present) {
      var lic = _el('small', 'ncf-req-gated');
      lic.appendChild(document.createTextNode(_t('Needs its licence accepted and your Hugging Face token (Settings).') + ' '));
      if (file.licenseUrl) {
        var licLink = _el('a', 'ncf-req-link', _t('Licence page'));
        licLink.href = file.licenseUrl;
        licLink.target = '_blank';
        licLink.rel = 'noopener';
        lic.appendChild(licLink);
      }
      copy.appendChild(lic);
    }
    // Non-commercial weights (Ideogram 4, FLUX.2 Klein 9B…): whoever
    // downloads the file accepts its license, so show it at that moment.
    if (file.license && file.license.non_commercial && !file.present) {
      var nc = _el('small', 'ncf-req-gated');
      nc.appendChild(document.createTextNode(
        _fmt(_t('Non-commercial licence ({name}): check what it allows before using it for paid work.'),
             { name: file.license.name || '' }) + ' '));
      if (file.license.url) {
        var ncLink = _el('a', 'ncf-req-link', _t('Licence page'));
        ncLink.href = file.license.url;
        ncLink.target = '_blank';
        ncLink.rel = 'noopener';
        nc.appendChild(ncLink);
      }
      copy.appendChild(nc);
    }
    row.appendChild(copy);

    var state = _dl[key];
    var side = _el('div', 'ncf-req-side');
    if (file.present || (state && state.status === 'done')) {
      var okLabel = '✓ ' + _t('Installed');
      if (state && state.status === 'done') okLabel = state.verified ? '✓ ' + _t('Verified') : '✓ ' + _t('Not verified');
      side.appendChild(_el('span', 'ncf-req-ok', okLabel));
    } else if (state && state.status === 'running') {
      var bar = _el('div', 'ncf-req-bar');
      var fill = _el('span');
      fill.style.width = (state.progress || 0) + '%';
      bar.appendChild(fill);
      side.appendChild(bar);
      side.appendChild(_el('small', 'ncf-req-pct', (state.progress || 0) + '%'));
    } else if (file.url) {
      var dl = _el('button', 'ncf-ep-pill ncf-ep-pill--small');
      dl.type = 'button';
      dl.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg><span></span>';
      dl.querySelector('span').textContent = state && state.status === 'error' ? _t('Retry') : _t('Download');
      dl.disabled = !(_last && _last.modelsFolderSet);
      dl.addEventListener('click', function () { _downloadMany([file]); });
      side.appendChild(dl);
    } else {
      var search = _el('a', 'ncf-req-link', _t('Search'));
      search.href = 'https://huggingface.co/models?search=' + encodeURIComponent(file.filename.replace(/\.[^.]+$/, ''));
      search.target = '_blank';
      search.rel = 'noopener';
      search.title = _t('No download address for this file — search for it on Hugging Face');
      side.appendChild(search);
    }
    row.appendChild(side);
    if (state && state.status === 'error') {
      row.appendChild(_el('p', 'ncf-req-error', state.error));
    }
    return row;
  }

  function _refreshRow(file) {
    if (!_panelOpen || !_panelBody || !_panelBody.isConnected) return;
    var key = file.filename.toLowerCase();
    var old = _panelBody.querySelector('[data-req-file="' + key.replace(/"/g, '') + '"]');
    if (old) old.replaceWith(_fileRow(file));
  }

  function _section(body, title) {
    var h = _el('p', 'nsc-param-title', title);
    body.appendChild(h);
    var list = _el('div', 'ncf-req-list');
    body.appendChild(list);
    return list;
  }

  function _renderPanelInto(body) {
    var r = _last;
    if (!r) { body.appendChild(_el('p', 'ncf-ep-hint', _t('Checking…'))); return; }
    if (r.comfyUnreachable) {
      body.appendChild(_el('p', 'ncf-req-note', _t('ComfyUI is not answering, so this flow can\'t be checked.')));
      return;
    }
    if (r.ok) {
      body.appendChild(_el('p', 'ncf-req-note ncf-req-note--ok', _t('ComfyUI has everything this flow needs.')));
      return;
    }

    body.appendChild(_el('p', 'ncf-ep-hint', _t('This flow runs on ComfyUI. Download what is missing here; it goes into your ComfyUI models folder.')));

    if (!r.modelsFolderSet) {
      var warn = _el('div', 'ncf-req-note ncf-req-note--warn');
      warn.appendChild(document.createTextNode(_t('Set your ComfyUI models folder in Settings to download files from here.') + ' '));
      var link = _el('a', 'ncf-req-link', _t('Open Settings'));
      link.href = '/settings';
      warn.appendChild(link);
      body.appendChild(warn);
    } else if (r.comfyIsLocal === false) {
      body.appendChild(_el('p', 'ncf-req-note', _t('ComfyUI runs on another computer: files are saved into the models folder set in Settings, which must be that computer\'s folder.')));
    }

    // Model files
    var missing = (r.models || []).filter(function (m) { return !m.present; });
    if (missing.length) {
      var list = _section(body, _t('Model files'));
      missing.forEach(function (m) { list.appendChild(_fileRow(m)); });
    }

    // Quantization variants — one is enough
    (r.quantization || []).forEach(function (g, gi) {
      if (g.installed) return;
      var vlist = _section(body, _t('Model version — one is enough'));
      var chosen = _variant(g, gi);
      var radios = _el('div', 'nsc-quality-list ncf-req-variants');
      radios.setAttribute('role', 'radiogroup');
      g.options.forEach(function (o) {
        var total = o.files.reduce(function (acc, f) { return acc + (!f.present && f.url && _sizes[f.url] ? _sizes[f.url] : 0); }, 0);
        var b = _el('button', 'nsc-quality-btn' + (o === chosen ? ' is-active' : ''));
        b.type = 'button';
        b.setAttribute('role', 'radio');
        b.setAttribute('aria-checked', o === chosen ? 'true' : 'false');
        b.innerHTML = '<span class="nsc-quality-dot"></span><span class="nsc-quality-copy"><strong></strong><small></small></span>';
        b.querySelector('strong').textContent = o.label;
        b.querySelector('small').textContent = total ? _gb(total) : '';
        b.addEventListener('click', function () { _pickedVariant[gi] = o.key; _renderPanel(); });
        radios.appendChild(b);
      });
      vlist.appendChild(radios);
      chosen.files.forEach(function (f) { if (!f.present) vlist.appendChild(_fileRow(f)); });
    });

    // Download all
    var all = _allDownloadable().filter(function (f) {
      var s = _dl[f.filename.toLowerCase()];
      return !s || s.status === 'error';
    });
    if (all.length > 1 && r.modelsFolderSet) {
      var total = all.reduce(function (acc, f) { return acc + (_sizes[f.url] || 0); }, 0);
      var allBtn = _el('button', 'nsc-generate-btn ncf-req-all');
      allBtn.type = 'button';
      allBtn.textContent = _fmt(_t('Download all ({size})'), { size: total ? _gb(total) : all.length });
      allBtn.addEventListener('click', function () { _downloadMany(all); });
      body.appendChild(allBtn);
      if (_free != null && total && total > _free) {
        body.appendChild(_el('p', 'ncf-req-error', _fmt(_t('Only {free} free in the models folder.'), { free: _gb(_free) })));
      }
    }

    // Custom nodes
    var packs = r.nodePacks || [];
    if (packs.length || (r.unknownNodes || []).length) {
      var plist = _section(body, _t('Custom nodes'));
      packs.forEach(function (p) {
        var card = _el('div', 'ncf-req-pack');
        card.appendChild(_el('strong', 'ncf-req-name', p.name));
        card.appendChild(_el('small', 'ncf-req-meta', p.classes.join(', ')));
        var actions = _el('div', 'ncf-req-pack-actions');
        if (p.repo) {
          var repo = _el('a', 'ncf-ep-pill ncf-ep-pill--small');
          repo.href = p.repo;
          repo.target = '_blank';
          repo.rel = 'noopener';
          repo.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5H5V6h5"/></svg><span></span>';
          repo.querySelector('span').textContent = _t('Repository');
          actions.appendChild(repo);
          if (/github\.com\/[^/]+\/[^/]+$/.test(p.repo)) {
            var cmd = 'git clone ' + p.repo;
            var copyBtn = _el('button', 'ncf-ep-pill ncf-ep-pill--small');
            copyBtn.type = 'button';
            copyBtn.title = cmd;
            copyBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg><span></span>';
            copyBtn.querySelector('span').textContent = _t('Copy install command');
            copyBtn.addEventListener('click', function () {
              var span = copyBtn.querySelector('span');
              var done = function () { span.textContent = _t('Copied'); setTimeout(function () { span.textContent = _t('Copy install command'); }, 1500); };
              if (navigator.clipboard) navigator.clipboard.writeText(cmd).then(done, function () {});
            });
            actions.appendChild(copyBtn);
          }
        }
        card.appendChild(actions);
        plist.appendChild(card);
      });
      if ((r.unknownNodes || []).length) {
        var unk = _el('div', 'ncf-req-pack');
        unk.appendChild(_el('strong', 'ncf-req-name', _t('Other nodes')));
        unk.appendChild(_el('small', 'ncf-req-meta', r.unknownNodes.join(', ')));
        plist.appendChild(unk);
      }
      body.appendChild(_el('p', 'ncf-ep-hint', _t('Install them from ComfyUI Manager (Custom Nodes Manager) or with the command in ComfyUI/custom_nodes, then restart ComfyUI.')));
    }

    var again = _el('button', 'nsc-generate-btn nsc-generate-btn--ghost ncf-req-again');
    again.type = 'button';
    again.textContent = _t('Check again');
    again.addEventListener('click', function () {
      again.disabled = true;
      again.textContent = _t('Checking…');
      check({ refresh: true }).then(function () { again.disabled = false; again.textContent = _t('Check again'); });
    });
    body.appendChild(again);
  }

  // Engine switch → different graph → check again (debounced: the engine
  // step fires once per render too).
  var _engineTimer = null;
  document.addEventListener('ncf-engine-changed', function () {
    clearTimeout(_engineTimer);
    _engineTimer = setTimeout(function () { check(); }, 150);
  });

  return {
    check: check,
    openPanel: openPanel,
    // After ComfyUI refused a job: re-check without the cache and, if
    // something is missing, open the panel straight away.
    afterRejected: function () { return check({ refresh: true, open: true }); },
  };
})();
