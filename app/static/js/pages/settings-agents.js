'use strict';
// Settings › Agents: connect Claude Desktop, ChatGPT (Codex / Work modes),
// Antigravity and Bionic to this installation's MCP server. /api/agents/setup
// (app/services/agent_setup.py) gives this installation's own launch values
// (Python, PYTHONPATH, port) and reads each program's config to say whether
// it already points here. Phase 1: steps + values to copy; nothing is
// written into other programs' files.
(function settingsAgents() {
  var clientsEl = document.getElementById('agents-clients');
  var connectedEl = document.getElementById('agents-connected');
  if (!clientsEl) return;

  function t(key, fallback, vars) {
    var text = window.NomadI18n ? window.NomadI18n.t('settings.agents.' + key, fallback) : fallback;
    if (typeof text === 'string' && vars) {
      Object.keys(vars).forEach(function (k) { text = text.split('{' + k + '}').join(String(vars[k])); });
    }
    return text;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var CLIENTS = [
    { id: 'claude', title: 'Claude Desktop', snippet: 'claude', fields: false,
      steps: ['Open Settings → Developer → Edit Config.',
              'Add the "nomad-studio" block inside "mcpServers" (paste all of it if the file is empty).',
              'Quit Claude completely (also from the icon next to the clock) and open it again.'] },
    { id: 'codex', title: 'ChatGPT Desktop', snippet: 'codex', fields: true,
      note: 'Only in the desktop app\'s Codex and ChatGPT Work modes: regular ChatGPT chat accepts remote servers only.',
      steps: ['Press Ctrl + , → Integrations → Plugins → Add → Add MCP Server. Type STDIO, name nomad_studio, and fill in the command, arguments and variables below.',
              'Or, with the app closed, add this block to the config file (it also gives long generations 10 minutes).',
              'Open the app again. It asks before generating or editing; lookups don\'t need it.'] },
    { id: 'antigravity', title: 'Antigravity (Gemini)', snippet: 'antigravity', fields: false,
      steps: ['In the Agent panel, open the … menu → MCP Servers → Manage MCP Servers → View raw config.',
              'Add the "nomad-studio" block inside "mcpServers" (paste all of it if the file is empty).',
              'Go back to Manage MCP Servers and press Refresh, or close Antigravity and open it again.'] },
    { id: 'bionic', title: 'Bionic (LM Studio)', snippet: 'bionic', fields: true,
      steps: ['Open Bionic\'s MCP servers settings and add one: name Nomad Studio, type stdio, and the command, arguments and variables below.',
              'Or, with Bionic closed, add this entry to the "servers" list of the config file.',
              'Restart Bionic and load a model with tool use (best in our tests: Ornith 1.5 9B).'] },
  ];
  var STATE_TEXT = {
    connected: ['stateConnected', 'Connected to this installation'],
    other: ['stateOther', 'Points to another installation'],
    missing: ['stateMissing', 'Not configured yet'],
    not_installed: ['stateNotInstalled', 'Not installed on this computer'],
  };
  var MISMATCH = {
    python: ['mismatchPython', 'Python: {is} — should be {shouldBe}'],
    folder: ['mismatchFolder', 'Folder: {is} — should be {shouldBe}'],
    port: ['mismatchPort', 'Port: {is} — should be {shouldBe}'],
  };

  function copyRow(label, value) {
    return '<div class="agents-copy-row">' +
      '<span class="agents-copy-label">' + esc(label) + '</span>' +
      '<code class="agents-copy-value">' + esc(value) + '</code>' +
      '<button type="button" class="btn settings-btn-secondary agents-copy-btn" data-copy="' + esc(value) + '">' +
      esc(t('copy', 'Copy')) + '</button></div>';
  }

  function card(client, info, data) {
    var status = info.clients[client.id] || {};
    var state = STATE_TEXT[status.state] || STATE_TEXT.missing;
    var launch = data.launch;
    var steps = t(client.id + 'Steps', client.steps);
    if (!Array.isArray(steps)) steps = client.steps;
    var html = '<section class="settings-field-block agents-client" data-state="' + esc(status.state) + '">' +
      '<div class="agents-client-head"><p class="settings-field-label">' + esc(client.title) + '</p>' +
      '<span class="agents-state agents-state--' + esc(status.state) + '">' + esc(t(state[0], state[1])) + '</span></div>';
    if (status.state === 'other') {
      html += '<ul class="agents-mismatches">' + (status.mismatches || []).map(function (m) {
        var msg = MISMATCH[m.what] || MISMATCH.folder;
        return '<li>' + esc(t(msg[0], msg[1], { is: m.is, shouldBe: m.shouldBe })) + '</li>';
      }).join('') + '</ul>';
    }
    // Connect / Fix (phase 2): Nomad Studio writes its own entry into that
    // program's file — confirmed inline first, never on a single click.
    if (status.installed && (status.state === 'missing' || status.state === 'other')) {
      var fix = status.state === 'other';
      html += '<div class="agents-action"><button type="button" class="btn settings-btn-secondary agents-connect-btn" data-client="' +
        esc(client.id) + '">' + esc(fix ? t('fix', 'Fix') : t('connect', 'Connect')) + '</button></div>';
    }
    html += '<div class="agents-result" data-result-for="' + esc(client.id) + '"></div>';
    if (client.note) html += '<p class="settings-field-hint agents-note">' + esc(t('codexNote', client.note)) + '</p>';
    html += '<ol class="agents-steps">' + steps.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ol>';
    if (client.fields) {
      html += '<div class="agents-copy-list">' +
        copyRow(t('command', 'Command'), launch.command) +
        copyRow(t('args', 'Arguments'), launch.args.join(' ')) +
        Object.keys(launch.env).map(function (k) { return copyRow(t('env', 'Variables') + ' · ' + k, launch.env[k]); }).join('') +
        '</div>';
    }
    html += '<div class="agents-snippet"><div class="agents-snippet-head">' +
      '<span class="settings-field-hint">' + esc(t('configFile', 'Config file')) + ': <code>' + esc(status.configPath || '') + '</code></span>' +
      '<button type="button" class="btn settings-btn-secondary agents-copy-btn" data-copy="' + esc(data.snippets[client.snippet]) + '">' +
      esc(t('copy', 'Copy')) + '</button></div>' +
      '<pre class="agents-snippet-code">' + esc(data.snippets[client.snippet]) + '</pre></div>';
    html += '</section>';
    return html;
  }

  function renderConnected(agents) {
    if (!connectedEl) return;
    if (!agents.length) {
      connectedEl.innerHTML = '<li class="settings-backup-empty">' + esc(t('noAgents', 'No assistant has connected yet.')) + '</li>';
      return;
    }
    connectedEl.innerHTML = agents.map(function (a) {
      var slug = a.slug || a.id;
      return '<li class="settings-backup-item"><div class="settings-backup-info">' +
        '<span class="settings-backup-date">' + esc(a.name || slug) + '</span></div>' +
        '<div class="settings-backup-actions"><a class="btn settings-btn-secondary" target="_blank" rel="noopener" href="/agents/' +
        encodeURIComponent(slug) + '/album">' + esc(t('album', 'Album')) + '</a></div></li>';
    }).join('');
  }

  var RESTART = {
    claude: ['restartClaude', 'Quit Claude completely and open it again.'],
    codex: ['restartCodex', 'Close the ChatGPT app and open it again.'],
    antigravity: ['restartAntigravity', 'In Antigravity, press Refresh in Manage MCP Servers, or open it again.'],
    bionic: ['restartBionic', 'Open Bionic again.'],
  };
  var lastData = null;
  var results = {};   // client → message shown after a write, kept across re-renders

  function resultArea(client) {
    return clientsEl.querySelector('[data-result-for="' + client + '"]');
  }

  function askConnect(client) {
    var area = resultArea(client);
    var status = lastData && lastData.clients[client];
    if (!area || !status) return;
    area.innerHTML = '<div class="settings-backup-confirm">' +
      '<span>' + esc(t('confirmWrite', 'Nomad Studio will write its entry into {path}. A copy of the file is saved first, and nothing else in it changes.', { path: status.configPath })) +
      (client === 'bionic' ? ' ' + esc(t('bionicCloseFirst', 'Close Bionic first: it rewrites this file when it quits.')) : '') + '</span>' +
      '<button type="button" class="btn settings-btn-secondary agents-confirm-btn" data-client="' + esc(client) + '">' + esc(t('confirm', 'Write')) + '</button>' +
      '<button type="button" class="btn settings-btn-secondary agents-cancel-btn" data-client="' + esc(client) + '">' + esc(t('cancel', 'Cancel')) + '</button>' +
      '</div>';
  }

  function doConnect(client, btn) {
    btn.disabled = true;
    fetch('/api/agents/setup/' + encodeURIComponent(client) + '/connect', { method: 'POST' })
      .then(function (r) { return r.json().catch(function () { return { ok: false, error: r.status }; }); })
      .then(function (res) {
        if (res && res.ok) {
          var restart = RESTART[client] || RESTART.claude;
          results[client] = '<p class="settings-field-hint status-ok">' + esc(t('done', 'Done.')) + ' ' + esc(t(restart[0], restart[1])) + '</p>' +
            (res.backupPath ? '<p class="settings-field-hint">' + esc(t('backupSaved', 'Previous file saved in {path}', { path: res.backupPath })) + '</p>' : '');
        } else {
          results[client] = '<p class="settings-field-hint status-error">' +
            esc(t('writeError', 'Couldn\'t write the file: {error}', { error: (res && res.error) || '?' })) + '</p>';
        }
        load();
      })
      .catch(function (err) {
        results[client] = '<p class="settings-field-hint status-error">' +
          esc(t('writeError', 'Couldn\'t write the file: {error}', { error: err && err.message })) + '</p>';
        load();
      });
  }

  clientsEl.addEventListener('click', function (e) {
    var connectBtn = e.target.closest('.agents-connect-btn');
    if (connectBtn) { askConnect(connectBtn.getAttribute('data-client')); return; }
    var confirmBtn = e.target.closest('.agents-confirm-btn');
    if (confirmBtn) { doConnect(confirmBtn.getAttribute('data-client'), confirmBtn); return; }
    var cancelBtn = e.target.closest('.agents-cancel-btn');
    if (cancelBtn) { var area = resultArea(cancelBtn.getAttribute('data-client')); if (area) area.innerHTML = ''; return; }
    var btn = e.target.closest('.agents-copy-btn');
    if (!btn) return;
    var value = btn.getAttribute('data-copy') || '';
    var done = function () {
      var label = btn.textContent;
      btn.textContent = t('copied', 'Copied');
      setTimeout(function () { btn.textContent = label; }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done, function () {});
    } else {
      var ta = document.createElement('textarea');
      ta.value = value; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); done(); } catch (_) {}
      ta.remove();
    }
  });

  function load() {
    return Promise.all([
      fetch('/api/agents/setup').then(function (r) { return r.ok ? r.json() : null; }),
      fetch('/api/agents').then(function (r) { return r.ok ? r.json() : { agents: [] }; }).catch(function () { return { agents: [] }; }),
    ]).then(function (res) {
      var data = res[0];
      if (!data) {
        clientsEl.innerHTML = '<p class="settings-field-hint status-error">' + esc(t('loadError', 'Couldn\'t read this computer\'s setup.')) + '</p>';
        return;
      }
      lastData = data;
      clientsEl.innerHTML = CLIENTS.map(function (c) { return card(c, data, data); }).join('') +
        '<p class="settings-field-hint">' + esc(t('tryIt', 'Try it: ask "Which models do I have in Nomad Studio?"')) + '</p>';
      Object.keys(results).forEach(function (client) {
        var area = resultArea(client);
        if (area) area.innerHTML = results[client];
      });
      renderConnected((res[1] && res[1].agents) || []);
    }).catch(function () {
      clientsEl.innerHTML = '<p class="settings-field-hint status-error">' + esc(t('loadError', 'Couldn\'t read this computer\'s setup.')) + '</p>';
    });
  }

  load();
})();
