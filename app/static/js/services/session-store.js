/* Nomad Studio — Session store (shared across all pages)
 * Single source of truth for Sessions in localStorage + auto-capture of
 * generated images back into the session that launched a flow.
 *
 * Migration note: this used to be the "Vault" feature, then "Bundle".
 * Existing users may still have data under the old ns-vault- and
 * ns-bundle- prefixed localStorage keys — migrateLegacy() copies it over
 * once, on first load, so nothing gets lost.
 */
(function () {
  'use strict';

  var KEY     = 'ns-sessions';   // [{ id, name, createdAt, steps:[] }]
  var PENDING = 'ns-session-pending';   // { sessionId, flowLabel, flowCategory, parentId, ts }
  var ACTIVE  = 'ns-session-active';    // last-opened session id
  var RETURN  = 'ns-session-return';    // '1' → hub should jump back into Session

  // One-time migration from older-era localStorage keys, so sessions saved
  // before a rename don't silently disappear under the new keys.
  // Vault → Bundle (original rename) → Session (this rename).
  (function migrateLegacy() {
    try {
      // Pending is deliberately NOT migrated (see getPending/setPending
      // below — it now lives in sessionStorage, tab-scoped on purpose) —
      // carrying forward a leftover "pending" flag from a previous era
      // would just reintroduce the exact same stale-flag bug across an
      // app update instead of within a session.
      var pairs = [
        // Vault-era → Bundle-era
        ['ns-vault-bundles', 'ns-bundles'],
        ['ns-vault-active', 'ns-bundle-active'],
        ['ns-vault-return', 'ns-bundle-return'],
        // Bundle-era → Session-era (current)
        ['ns-bundles', KEY],
        ['ns-bundle-active', ACTIVE],
        ['ns-bundle-return', RETURN]
      ];
      pairs.forEach(function (pair) {
        var oldKey = pair[0], newKey = pair[1];
        if (localStorage.getItem(newKey) === null) {
          var oldVal = localStorage.getItem(oldKey);
          if (oldVal !== null) localStorage.setItem(newKey, oldVal);
        }
      });
    } catch (_) {}
  })();

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (_) { return []; }
  }
  function save(sessions) {
    try { localStorage.setItem(KEY, JSON.stringify(sessions)); } catch (_) {}
  }
  function find(id) {
    return load().find(function (b) { return b.id === id; }) || null;
  }
  function upsert(session) {
    if (!session || !session.id) return;
    var sessions = load();
    var i = sessions.findIndex(function (b) { return b.id === session.id; });
    if (i === -1) sessions.push(session); else sessions[i] = session;
    save(sessions);
  }

  function slugify(name) {
    return String(name || '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'session';
  }

  function create(name) {
    var session = {
      id: 'session-' + Date.now(),
      name: name || 'Untitled Session',
      folder: slugify(name) + '-' + Math.floor(Date.now() / 1000),
      createdAt: new Date().toISOString(),
      steps: []
    };
    upsert(session);
    return session;
  }

  // The per-session folder name, derived & persisted lazily for older sessions.
  function folderOf(session) {
    if (!session) return 'session';
    if (!session.folder) {
      var t = session.createdAt ? Math.floor(new Date(session.createdAt).getTime() / 1000)
                               : Math.floor(Date.now() / 1000);
      session.folder = slugify(session.name) + '-' + (t || Math.floor(Date.now() / 1000));
      upsert(session);
    }
    return session.folder;
  }

  // Server output subdir for this session's images, e.g. "session/cologne-171890".
  function subdirOf(session) { return 'session/' + folderOf(session); }

  // Shared by addStep/addStepRemote below — mutates the local cache and
  // returns the updated session (or null if sessionId doesn't exist), but
  // doesn't push to the server itself so callers can choose fire-and-forget
  // (addStep) or await-the-PUT (addStepRemote).
  function _addStepLocal(sessionId, step) {
    var sessions = load();
    var i = sessions.findIndex(function (b) { return b.id === sessionId; });
    if (i === -1) return null;
    var b = sessions[i];
    b.steps = b.steps || [];
    b.steps.forEach(function (s) { s.selected = false; });
    step.selected = true;
    b.steps.push(step);
    sessions[i] = b;
    save(sessions);
    return b;
  }

  function addStep(sessionId, step) {
    var b = _addStepLocal(sessionId, step);
    if (!b) return false;
    pushUpdate(b);
    return true;
  }

  // Same as addStep, but returns a Promise that only resolves once the PUT
  // has actually landed (or failed — pushUpdate swallows errors either way,
  // same as addStep's fire-and-forget). For a caller about to navigate to a
  // *different* page that re-GETs this same session right after (e.g.
  // flow-gallery.js's "Create Session" toggle, landing on the session
  // workspace page): without waiting here, that GET can beat this PUT, and
  // syncFromServer's merge — server always wins — would overwrite the local
  // copy with a still-stale one, silently dropping the step just added.
  function addStepRemote(sessionId, step) {
    var b = _addStepLocal(sessionId, step);
    if (!b) return Promise.resolve(false);
    return pushUpdate(b).then(function () { return true; });
  }

  /* ── Pending / active / return flags ─────────────────────────────────── */
  // Pending uses sessionStorage (tab-scoped), NOT localStorage (shared by
  // every tab/window on the origin) — it marks "the flow open in THIS tab
  // right now is attached to a session", and only ever needs to be read by
  // that same tab (captureImages() below, sessionContextChrome() in
  // flow-boot.js). With localStorage, opening an unrelated standalone flow
  // in a brand new window/tab while some OTHER tab still had an active
  // session pending (normal — pending is cleared on "return to session",
  // not right after use) made that new tab inherit the stale flag and
  // wrongly render itself as "inside" that other tab's session (reported:
  // a fresh Refine tab showing "BACK TO SESSION" + the wrong session name).
  // sessionStorage still survives the same-tab `window.location.href`
  // navigation sessionReopenStep() falls back to when no native container
  // is available, so that path is unaffected.
  function getPending() { try { return JSON.parse(sessionStorage.getItem(PENDING) || 'null'); } catch (_) { return null; } }
  function setPending(p) { try { sessionStorage.setItem(PENDING, JSON.stringify(p)); } catch (_) {} }
  function clearPending() { try { sessionStorage.removeItem(PENDING); } catch (_) {} }

  function getActive() { try { return localStorage.getItem(ACTIVE) || ''; } catch (_) { return ''; } }
  function setActive(id) { try { localStorage.setItem(ACTIVE, id || ''); } catch (_) {} }

  function wantsReturn() { try { return localStorage.getItem(RETURN) === '1'; } catch (_) { return false; } }
  function setReturn(v) { try { v ? localStorage.setItem(RETURN, '1') : localStorage.removeItem(RETURN); } catch (_) {} }

  /* ── Capture generated images into the pending session ────────────────── */
  // All images produced during one flow session (the pending context) are
  // gathered into a SINGLE history entry. The first capture creates the step
  // and records its id on the pending context; later captures append to it.
  // Pending is NOT cleared here — it is cleared when the user returns to the
  // session view (see nomad_studio.sessionInit), so multi-image flows aren't
  // truncated to their first output.
  // The flow's input images at capture time — {image picker step id: server
  // URL} — so reopening the step restores every input (a Mix step has up to
  // four), not just its parent's output. Only server URLs (image_server_url,
  // set once the picker's upload is persisted): data URLs would bloat
  // sessions.json.
  function collectFlowInputs() {
    var out = {};
    try {
      if (typeof stepValues !== 'object' || !stepValues || typeof allSteps === 'undefined' || !Array.isArray(allSteps)) return out;
      allSteps.forEach(function (s) {
        if (!s || s.type !== 'image_picker') return;
        var url = stepValues[s.id] && stepValues[s.id].image_server_url;
        if (url) out[s.id] = url;
      });
    } catch (_) {}
    return out;
  }

  function captureImages(urls) {
    var p = getPending();
    if (!p || !p.sessionId || !urls || !urls.length) return false;
    var clean = urls.filter(Boolean);
    if (!clean.length) return false;

    var sessions = load();
    var bi = sessions.findIndex(function (b) { return b.id === p.sessionId; });
    if (bi === -1) return false;
    var b = sessions[bi];
    b.steps = b.steps || [];

    var step = p.stepId ? b.steps.find(function (s) { return s.id === p.stepId; }) : null;
    if (step) {
      // Append the new outputs to this flow session's existing entry.
      var existing = Array.isArray(step.images) ? step.images : [];
      step.images = existing.concat(clean.filter(function (u) { return existing.indexOf(u) === -1; }));
      if (!step.imageUrl) step.imageUrl = step.images[0];
      if (p.flowParams && !step.params) step.params = p.flowParams;
      if (!step.inputs) {
        var laterInputs = collectFlowInputs();
        if (Object.keys(laterInputs).length) step.inputs = laterInputs;
      }
    } else {
      var inputs = collectFlowInputs();
      step = {
        id: 'step-' + Date.now() + '-' + Math.floor(Math.random() * 1e4),
        flowLabel: p.flowLabel || 'Flow',
        flowCategory: p.flowCategory || 'create',
        flowAction: p.flowAction || null,
        params: p.flowParams || null,
        imageUrl: clean[0],
        images: clean.slice(),
        parentId: p.parentId || null,
        createdAt: new Date().toISOString()
      };
      if (Object.keys(inputs).length) step.inputs = inputs;
      b.steps.forEach(function (s) { s.selected = false; });
      step.selected = true;
      b.steps.push(step);
      p.stepId = step.id;          // subsequent captures append to this entry
      setPending(p);
    }
    sessions[bi] = b;
    save(sessions);
    pushUpdate(b);
    setReturn(true);

    // Tell the session page's own tree to refresh right now — it used to
    // rely on the native `storage` event firing on the *other* window when
    // the flow ran in a separate <iframe> document; now that the flow is
    // mounted natively in the same document as the session tree, that event
    // never fires here (browsers don't deliver `storage` back to the
    // document that wrote it), so this direct call is what replaces it.
    // Absent entirely on standalone flow pages (no session tree to refresh).
    if (typeof window.__nomadOnSessionStepCaptured === 'function') {
      try { window.__nomadOnSessionStepCaptured(); } catch (_) {}
    }

    return true;
  }

  // Generate/Queue pressed in a flow opened from a Session: the step shows
  // up in the Steps panel right away, empty and marked `generating`, instead
  // of only once the first image lands. captureImages() then fills this same
  // step (p.stepId), and settleStep() clears the mark when the flow's queue
  // runs dry — or drops the step if nothing came out of it (an error, a
  // cancel). An empty `generating` step older than half an hour is a run
  // that never settled (tab closed mid-run) and is cleared here too.
  var STALE_GENERATING_MS = 30 * 60 * 1000;

  function _notifyStepChange() {
    if (typeof window.__nomadOnSessionStepCaptured === 'function') {
      try { window.__nomadOnSessionStepCaptured(); } catch (_) {}
    }
  }

  function _isEmptyStep(s) {
    return !(Array.isArray(s.images) && s.images.length) && !s.imageUrl;
  }

  function beginStep() {
    var p = getPending();
    if (!p || !p.sessionId) return false;
    var sessions = load();
    var bi = sessions.findIndex(function (b) { return b.id === p.sessionId; });
    if (bi === -1) return false;
    var b = sessions[bi];
    b.steps = (b.steps || []).filter(function (s) {
      return !(s.generating && _isEmptyStep(s) && s.id !== p.stepId &&
               Date.now() - Date.parse(s.createdAt || 0) > STALE_GENERATING_MS);
    });

    var step = p.stepId ? b.steps.find(function (s) { return s.id === p.stepId; }) : null;
    if (step) {
      step.generating = true;
    } else {
      step = {
        id: 'step-' + Date.now() + '-' + Math.floor(Math.random() * 1e4),
        flowLabel: p.flowLabel || 'Flow',
        flowCategory: p.flowCategory || 'create',
        flowAction: p.flowAction || null,
        params: p.flowParams || null,
        imageUrl: '',
        images: [],
        parentId: p.parentId || null,
        createdAt: new Date().toISOString(),
        generating: true
      };
      var inputs = collectFlowInputs();
      if (Object.keys(inputs).length) step.inputs = inputs;
      b.steps.forEach(function (s) { s.selected = false; });
      step.selected = true;
      b.steps.push(step);
      p.stepId = step.id;
      setPending(p);
    }
    sessions[bi] = b;
    save(sessions);
    pushUpdate(b);
    _notifyStepChange();
    return true;
  }

  function settleStep() {
    var p = getPending();
    if (!p || !p.sessionId || !p.stepId) return false;
    var sessions = load();
    var bi = sessions.findIndex(function (b) { return b.id === p.sessionId; });
    if (bi === -1) return false;
    var b = sessions[bi];
    var si = (b.steps || []).findIndex(function (s) { return s.id === p.stepId; });
    if (si === -1 || !b.steps[si].generating) return false;
    var step = b.steps[si];
    if (_isEmptyStep(step)) {
      b.steps.splice(si, 1);
      p.stepId = null;
      setPending(p);
    } else {
      delete step.generating;
    }
    sessions[bi] = b;
    save(sessions);
    pushUpdate(b);
    _notifyStepChange();
    return true;
  }

  // The mirror of captureImages: an image deleted from a flow's result feed
  // has to leave the session step too, or the Steps panel keeps showing a
  // thumbnail of something the user just threw away (and, once the file is
  // gone from the output dir, a broken one). Looks in the pending session
  // first, then anywhere — an image can be deleted after switching steps.
  // A step whose last image goes is removed entirely, same rule the flow's
  // own history snapshot uses ("the feed ended up empty" ⇒ no entry).
  function removeImages(urls) {
    var clean = (urls || []).filter(Boolean);
    if (!clean.length) return false;

    var sessions = load();
    var p = getPending();
    var order = [];
    if (p && p.sessionId) {
      var pi = sessions.findIndex(function (b) { return b.id === p.sessionId; });
      if (pi !== -1) order.push(pi);
    }
    sessions.forEach(function (_, i) { if (order.indexOf(i) === -1) order.push(i); });

    var touched = null;
    for (var oi = 0; oi < order.length && !touched; oi++) {
      var b = sessions[order[oi]];
      if (!b || !Array.isArray(b.steps)) continue;
      var changed = false;
      for (var si = b.steps.length - 1; si >= 0; si--) {
        var s = b.steps[si];
        var imgs = Array.isArray(s.images) ? s.images : (s.imageUrl ? [s.imageUrl] : []);
        var kept = imgs.filter(function (u) { return clean.indexOf(u) === -1; });
        if (kept.length === imgs.length) continue;
        changed = true;
        if (kept.length) {
          s.images = kept;
          if (clean.indexOf(s.imageUrl) !== -1) s.imageUrl = kept[0];
        } else {
          // Nothing left in this step — drop it, re-parenting its children
          // exactly like the workspace's own delete does.
          var removedId = s.id, removedParent = s.parentId || null;
          b.steps.forEach(function (c) { if (c.parentId === removedId) c.parentId = removedParent; });
          b.steps.splice(si, 1);
          if (p && p.stepId === removedId) { p.stepId = null; setPending(p); }
        }
      }
      if (changed) { touched = b; sessions[order[oi]] = b; }
    }
    if (!touched) return false;

    save(sessions);
    pushUpdate(touched);
    if (typeof window.__nomadOnSessionStepCaptured === 'function') {
      try { window.__nomadOnSessionStepCaptured(); } catch (_) {}
    }
    return true;
  }

  /* ── Server persistence ───────────────────────────────────────────────
   * Sessions are cached locally (above) for instant rendering, but the
   * server (data/sessions.json, keyed by viewer) is the source of truth
   * across browsers/devices. Every mutating action also pushes to the
   * server; on page load we pull the server list and merge it into the
   * local cache so switching browsers shows the same Sessions again.
   */
  var SCOPE_ALL = 'all';
  var SCOPE_USER = 'user';

  function _api(path, opts) {
    return fetch('/api/sessions' + path, Object.assign({
      headers: { 'Content-Type': 'application/json' }
    }, opts || {})).then(function (r) { return r.json(); });
  }

  // Pull the viewer's visible sessions (own + shared-with-all) from the
  // server and merge them into the local cache. Server sessions win on id
  // conflicts; purely-local sessions (not yet synced, e.g. offline) are kept.
  // Server time ({session id: ms}) of the freshest copy of each session this
  // browser holds. Sent as syncedAt on every PUT: a step the server got after
  // that moment (added by an agent through the MCP, NomadStudio#24) is one
  // this cache never saw, so the server keeps it instead of reading its
  // absence from the list as a delete.
  var SYNCED_KEY = 'ns-sessions-synced';
  function _syncedMap() {
    try { return JSON.parse(localStorage.getItem(SYNCED_KEY) || '{}') || {}; } catch (_) { return {}; }
  }
  function _markSynced(ids, serverTime) {
    if (!serverTime || !ids.length) return;
    var map = _syncedMap();
    ids.forEach(function (id) { if (!map[id] || map[id] < serverTime) map[id] = serverTime; });
    try { localStorage.setItem(SYNCED_KEY, JSON.stringify(map)); } catch (_) {}
  }

  // Take the steps of a server copy that the local one lacks and that were
  // added after this cache's last sync — additive only, so a response racing
  // a local edit can never undo it.
  function _absorb(serverSession, serverTime) {
    if (!serverSession || !serverSession.id) return false;
    var sessions = load();
    var i = sessions.findIndex(function (b) { return b.id === serverSession.id; });
    if (i === -1) return false;
    var local = sessions[i];
    var since = _syncedMap()[local.id] || 0;
    var known = {};
    (local.steps || []).forEach(function (s) { if (s && s.id) known[s.id] = true; });
    var extra = (serverSession.steps || []).filter(function (s) {
      return s && s.id && !known[s.id] && (s.addedAt || 0) > since;
    });
    if (extra.length) {
      local.steps = local.steps || [];
      if (extra.some(function (s) { return s.selected; })) {
        local.steps.forEach(function (s) { s.selected = false; });
      }
      local.steps = local.steps.concat(extra);
      sessions[i] = local;
      save(sessions);
    }
    _markSynced([local.id], serverTime);
    if (extra.length) _notifyStepChange();
    return extra.length > 0;
  }

  // Re-read one session (the workspace calls it when the window gets focus
  // back) and pick up steps added from outside meanwhile.
  function refreshSession(sessionId) {
    if (!sessionId) return Promise.resolve(false);
    return _api('/' + encodeURIComponent(sessionId), { method: 'GET' })
      .then(function (data) { return data && data.ok ? _absorb(data.session, data.serverTime) : false; })
      .catch(function () { return false; });
  }

  function syncFromServer() {
    return _api('', { method: 'GET' }).then(function (data) {
      var serverSessions = Array.isArray(data.sessions) ? data.sessions : [];
      var serverIds = {};
      serverSessions.forEach(function (b) { if (b && b.id) serverIds[b.id] = true; });
      _markSynced(Object.keys(serverIds), data.serverTime);

      // Anything deleted locally stays deleted, whichever copy this response
      // happens to carry (see the tombstone comment on deleteRemote). Once the
      // server agrees it's gone, the tombstone has done its job and is dropped
      // so the list can't grow without bound.
      var tombs = _tombstones();
      var stillPending = tombs.filter(function (id) { return serverIds[id]; });
      if (stillPending.length !== tombs.length) _saveTombstones(stillPending);
      var deleted = {};
      tombs.forEach(function (id) { deleted[id] = true; });

      var byId = {};
      load().forEach(function (b) { if (b && !deleted[b.id]) byId[b.id] = b; });
      serverSessions.forEach(function (b) { if (b && !deleted[b.id]) byId[b.id] = b; });
      var merged = Object.keys(byId).map(function (id) { return byId[id]; });
      save(merged);
      return merged;
    }).catch(function () { return load(); });
  }

  // Create a session on the server with an explicit scope, then cache it
  // locally. Falls back to a local-only session if the server is unreachable.
  function createRemote(name, scope) {
    return _api('', {
      method: 'POST',
      body: JSON.stringify({ name: name, scope: scope || SCOPE_USER })
    }).then(function (data) {
      if (data && data.ok && data.session) { upsert(data.session); return data.session; }
      return create(name);
    }).catch(function () { return create(name); });
  }

  function importRemote(sessionData, scope) {
    return _api('/import', {
      method: 'POST',
      body: JSON.stringify({ session: sessionData, scope: scope || SCOPE_USER })
    }).then(function (data) {
      if (data && data.ok && data.session) { upsert(data.session); return data.session; }
      var b = sessionData; if (!b.id) b.id = 'session-' + Date.now(); upsert(b); return b;
    }).catch(function () {
      var b = sessionData; if (!b.id) b.id = 'session-' + Date.now(); upsert(b); return b;
    });
  }

  // Duplicating never asks "all vs user" — a copy is always private to
  // whoever made it.
  function duplicateRemote(sessionId) {
    return _api('/' + encodeURIComponent(sessionId) + '/duplicate', { method: 'POST' })
      .then(function (data) {
        if (data && data.ok && data.session) { upsert(data.session); return data.session; }
        return null;
      }).catch(function () { return null; });
  }

  // Push local mutations (addStep/captureImages/rename) up to the server.
  // Every existing caller treats this as fire-and-forget (local cache
  // already has the change, this just keeps the server copy in sync for
  // other browsers/devices) and ignores the return value — but it IS a
  // promise (resolves either way, errors swallowed) for the rare caller that
  // needs to know the PUT actually landed before doing something else, e.g.
  // addStepRemote below.
  function pushUpdate(session) {
    if (!session || !session.id) return Promise.resolve();
    var body = { name: session.name, steps: session.steps, folder: session.folder };
    var syncedAt = _syncedMap()[session.id];
    if (syncedAt) body.syncedAt = syncedAt;
    return _api('/' + encodeURIComponent(session.id), {
      method: 'PUT',
      body: JSON.stringify(body)
    }).then(function (data) {
      if (data && data.ok) _absorb(data.session, data.serverTime);
      return data;
    }).catch(function () {});
  }

  // Ids deleted here, kept until the server stops returning them. syncFromServer
  // merges the server's list over the local cache, so a GET that was already in
  // flight when the DELETE landed (or one issued right after it, which is what
  // the hub does: delete, then re-init) can answer with the session still in it
  // and write it straight back into localStorage. From then on it was there for
  // good — the merge only ever adds — so a session you deleted kept showing up
  // while the server no longer had it. The tombstone is what makes the delete
  // stick regardless of which request wins the race, or of the DELETE failing
  // outright (offline, 500).
  var TOMB_KEY = 'ns-sessions-deleted';
  function _tombstones() {
    try { return JSON.parse(localStorage.getItem(TOMB_KEY) || '[]') || []; }
    catch (_) { return []; }
  }
  function _saveTombstones(ids) {
    try { localStorage.setItem(TOMB_KEY, JSON.stringify(ids)); } catch (_) {}
  }
  function tombstone(sessionId) {
    if (!sessionId) return;
    var ids = _tombstones();
    if (ids.indexOf(sessionId) === -1) { ids.push(sessionId); _saveTombstones(ids); }
  }

  // Returns the promise so callers can wait for the server to actually be done
  // before re-reading the list.
  function deleteRemote(sessionId) {
    tombstone(sessionId);
    return _api('/' + encodeURIComponent(sessionId), { method: 'DELETE' })
      .catch(function () { return null; });
  }

  // Persist a session that was already fully built client-side (e.g. the
  // locally re-id'd duplicate) — always forced to scope=user, so a copy is
  // never accidentally shared with everyone.
  function persistAsUser(session) {
    if (!session || !session.id) return;
    _api('', {
      method: 'POST',
      body: JSON.stringify(Object.assign({}, session, { scope: SCOPE_USER }))
    }).catch(function () {});
  }

  window.NomadSession = {
    KEY: KEY,
    load: load, save: save, find: find, upsert: upsert, create: create, addStep: addStep,
    addStepRemote: addStepRemote,
    getPending: getPending, setPending: setPending, clearPending: clearPending,
    getActive: getActive, setActive: setActive,
    wantsReturn: wantsReturn, setReturn: setReturn,
    captureImages: captureImages, removeImages: removeImages,
    beginStep: beginStep, settleStep: settleStep,
    slugify: slugify, folderOf: folderOf, subdirOf: subdirOf,
    SCOPE_ALL: SCOPE_ALL, SCOPE_USER: SCOPE_USER,
    syncFromServer: syncFromServer, refreshSession: refreshSession,
    createRemote: createRemote, importRemote: importRemote,
    duplicateRemote: duplicateRemote, pushUpdate: pushUpdate, deleteRemote: deleteRemote,
    persistAsUser: persistAsUser
  };

  /* ── Auto-capture: wrap openJourneyApi.saveComfyImages once ──────────── */
  function wrap() {
    var api = window.openJourneyApi;
    if (!api || api.__sessionWrapped || typeof api.saveComfyImages !== 'function') return;
    var orig = api.saveComfyImages;
    api.__sessionWrapped = true;
    api.saveComfyImages = async function (payload) {
      // Redirect session generations into the session's session subfolder.
      try {
        var p0 = getPending();
        if (p0 && p0.subdir && payload && typeof payload === 'object' && !payload.subdir) {
          payload.subdir = p0.subdir;
        }
      } catch (_) {}
      var data = await orig.call(this, payload);
      try {
        if (getPending() && data) {
          // Carry the flow parameters (stored in metadata.params) onto the
          // pending context so the captured step remembers how it was made.
          try {
            var meta = payload && payload.metadata;
            if (meta && meta.params) {
              var parsed = typeof meta.params === 'string' ? JSON.parse(meta.params) : meta.params;
              if (parsed) { var pp = getPending(); if (pp) { pp.flowParams = parsed; setPending(pp); } }
            }
          } catch (_) {}
          var urls = Array.isArray(data.savedUrls)
            ? data.savedUrls.filter(Boolean)
            : (Array.isArray(data.savedFilenames)
                ? data.savedFilenames.filter(Boolean).map(function (f) { return '/api/images/' + f; })
                : []);
          if (urls.length) captureImages(urls);
        }
      } catch (_) {}
      return data;
    };
  }

  if (window.openJourneyApi) wrap();
  else document.addEventListener('DOMContentLoaded', wrap);

  /* ── "Back to session" button on flow/refine pages launched from the Session ── */
  function initSessionReturnButton() {
    var pending = getPending();
    if (!pending || !pending.sessionId) return;  // not launched from a session
    var onFlowPage = document.getElementById('nsc-flow-root') ||
      /\/nomad-studio\/(create|refine)\//.test(window.location.pathname);
    if (!onFlowPage) return;
    if (document.getElementById('ns-session-return-btn')) return;

    var btn = document.createElement('button');
    btn.id = 'ns-session-return-btn';
    btn.type = 'button';
    btn.textContent = '\u2190 Back to session';
    btn.style.cssText = [
      'position:fixed', 'left:50%', 'bottom:22px', 'transform:translateX(-50%)',
      'z-index:9999', 'display:inline-flex', 'align-items:center', 'gap:8px',
      'padding:11px 20px', 'border-radius:999px', 'border:1px solid rgba(240,192,96,0.5)',
      'background:#1a1200', 'color:#f0c060', 'font:600 14px/1 inherit',
      'cursor:pointer', 'box-shadow:0 6px 24px rgba(0,0,0,0.45)',
      'transition:background 0.15s, color 0.15s, transform 0.12s'
    ].join(';');
    btn.addEventListener('mouseenter', function () { btn.style.transform = 'translateX(-50%) translateY(-1px)'; });
    btn.addEventListener('mouseleave', function () { btn.style.transform = 'translateX(-50%)'; });
    btn.addEventListener('click', function () {
      // Mounted natively inside the session workspace (same document) →
      // unmount instead of navigating. window.parent is checked too, purely
      // as a defensive fallback in case a flow page is ever nested some
      // other way again — the real path today is always the same-window one.
      try {
        if (typeof window.__nomadCloseSessionFlowPanel === 'function') {
          window.__nomadCloseSessionFlowPanel();
          return;
        }
        if (window.parent && window.parent !== window && typeof window.parent.__nomadCloseSessionFlowPanel === 'function') {
          window.parent.__nomadCloseSessionFlowPanel();
          return;
        }
      } catch (_) {}
      window.location.href = '/nomad-studio/session/' + encodeURIComponent(pending.sessionId);
    });
    document.body.appendChild(btn);

    // Once an image has been captured (pending cleared + return flagged),
    // promote the button to a positive "Done" state.
    var iv = setInterval(function () {
      if (!getPending() && wantsReturn()) {
        btn.textContent = '\u2713 Done \u2014 back to session';
        btn.style.background = '#f0c060';
        btn.style.color = '#1a1200';
        btn.style.borderColor = '#f0c060';
        clearInterval(iv);
      }
    }, 800);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSessionReturnButton);
  } else {
    initSessionReturnButton();
  }
})();
