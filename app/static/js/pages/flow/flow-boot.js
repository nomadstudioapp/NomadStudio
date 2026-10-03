'use strict';
// Boot: fetch flow definition and render



// ── Boot: fetch flow definition and render ─────────────────────────────────
// Extracted from the old auto-invoking IIFE into a named function so
// FlowEngine.reset() (below) can call it again for a different flow_id
// without reloading the page. Behavior for the very first call (standalone
// page load) is unchanged — same fetch, same rendering, same restore logic.
function flowBootLoad(id) {
  if (!id) return;

  // The server translates the flow with the text its package carries.
  var lang = (window.NomadI18n && window.NomadI18n.getLanguage && window.NomadI18n.getLanguage()) || 'en';
  // The engine's own texts go through tF(), which needs the dictionary: wait
  // for it (loaded in parallel with the flow), but never more than 3 s.
  var dictReady = (window.NomadI18n && window.NomadI18n.ready)
    ? Promise.race([window.NomadI18n.ready, new Promise(function (r) { setTimeout(r, 3000); })])
    : Promise.resolve();
  return Promise.all([
    fetch('/api/flows/' + id + '?lang=' + encodeURIComponent(lang)).then(function (r) { return r.json(); }),
    dictReady,
  ])
    .then(function (results) { return results[0]; })
    .then(function (data) {
      var flow = data && data.flow;
      if (!flow || !flow.definition) {
        console.error('[FlowEngine] Flow not found or missing definition:', id);
        flowBootShowError(id);
        return;
      }
      flowDef = flow.definition;
      allSteps = Array.isArray(flowDef.steps) ? flowDef.steps : [];

      // Set breadcrumb
      var bc = document.getElementById('nsc-flow-breadcrumb');
      if (bc) bc.textContent = flowDef.label || id;

      // Tab title — lets you tell multiple flow tabs apart at a glance
      // (e.g. "NomadStudio - Remove Background - #dgmmbkyf").
      document.title = 'NomadStudio - ' + (flowDef.label || id) +
        (typeof flowInstanceId !== 'undefined' && flowInstanceId ? ' - #' + flowInstanceId : '');

      // Instance-id badge — lets you reference/confirm which running history
      // entry this page is currently updating (see flowInstanceId in flow-state.js).
      var existingBadge = document.getElementById('nsc-flow-instance-badge');
      if (existingBadge) existingBadge.remove(); // stale id from a previous flow in this same page (session-native switch)
      if (bc && bc.parentElement && typeof flowInstanceId !== 'undefined' && flowInstanceId) {
        var instBadge = document.createElement('span');
        instBadge.id = 'nsc-flow-instance-badge';
        instBadge.className = 'nsc-flow-instance-badge';
        instBadge.title = tF('Flow instance id — generations made without leaving this page update the same history entry');
        instBadge.textContent = '#' + flowInstanceId;
        bc.parentElement.appendChild(instBadge);
      }

      // Save-to-Build button — sits at the top of the results rail (Refine /
      // Zoom in / Zoom out below it), not next to the instance-id badge
      // anymore: same widget family as its new neighbors instead of its own
      // one-off chip floating near the breadcrumb.
      var _saveBtnRail = document.querySelector('.ncf-results-toolbar--rail');
      if (_saveBtnRail && !document.getElementById('nsc-flow-save-btn')) {
        var saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.id = 'nsc-flow-save-btn';
        // nsc-options-trigger: it opens the side panel, so clicking it again
        // mustn't count as the "outside" click that closes that panel.
        saveBtn.className = 'btn create-action-btn nsc-options-trigger';
        saveBtn.setAttribute('aria-label', tF('Send flow to Build'));
        var saveBtnTip = document.createElement('span');
        saveBtnTip.className = 'action-tip';
        saveBtnTip.textContent = tF('Send flow to Build');
        saveBtn.innerHTML =
          // A cube — the Depot's own icon (topbar badge). The thin prism it
          // replaced, drawn in a 100×160 box, barely showed at the rail's size.
          '<svg class="explore-zoom-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>' +
          '<path d="M3.3 7 12 12l8.7-5M12 22V12"/>' +
          '</svg>';
        saveBtn.appendChild(saveBtnTip);
        // A panel, not a direct save: Build › Flows (this flow with its
        // settings) or the Depot its results are filed into as they're made
        // (flow-gallery.js _openSendFlowToBuildPanel).
        saveBtn.addEventListener('click', function () {
          if (typeof saveFlowInstanceToLibrary !== 'function') return;
          _openSendFlowToBuildPanel(saveFlowInstanceToLibrary);
        });
        _saveBtnRail.insertBefore(saveBtn, _saveBtnRail.firstChild);
      }

      // Apply the persisted Guided/Custom mode now so the toggle button and
      // body[data-ns-mode] reflect it on first paint instead of only after a click.
      applyMode(getMode());

      renderAllSteps();

      // Restore from a Session "Open" (oj-load-session, parsed once into
      // _pendingSession by flow-state): re-apply the saved parameters and
      // replay the previous outputs into the results feed.
      try {
        if (typeof _pendingSession !== 'undefined' && _pendingSession && _pendingSession.data) {
          var _d = _pendingSession.data;
          if (_d.params && typeof applyParamsSnapshot === 'function') {
            applyParamsSnapshot(_d.params);
          }
          if (Array.isArray(_d.images) && _d.images.length && typeof addToFeed === 'function') {
            // Each image keeps its OWN prompt (data.imagePrompts, index-aligned
            // with data.images) — reusing _d.params alone for every card would
            // show the same (last) prompt under every restored image.
            _d.images.forEach(function (u, i) {
              if (!u) return;
              generatedCount++;
              var _imgPrompt = Array.isArray(_d.imagePrompts) ? _d.imagePrompts[i] : '';
              // Per-image quantization (and — if ever saved — duration) beats
              // the snapshot's single _d.params.quantizationId, which only
              // reflects whatever was selected in the UI at save time and is
              // wrong for every image but the last one generated.
              var _imgQuant = Array.isArray(_d.imageQuantizations) ? _d.imageQuantizations[i] : '';
              var _imgGenSeconds = Array.isArray(_d.imageGenSeconds) ? _d.imageGenSeconds[i] : null;
              var _imgParams = Object.assign({}, _d.params || {});
              if (_imgPrompt) _imgParams.prompt = _imgPrompt;
              if (_imgQuant) _imgParams.quantizationId = _imgQuant;
              if (typeof _imgGenSeconds === 'number') _imgParams.genSeconds = _imgGenSeconds;
              addToFeed(u, generatedCount, null, _imgParams);
            });
          }
        }
      } catch (e) {
        if (window.console) console.error('[FlowEngine] restore on open:', e);
      }

      // If any images were already restored into the feed — either from a
      // Session "Open" (_pendingSession, just above) or from a Nomad Studio
      // history entry (oj-load-session, restored synchronously by
      // flow-gallery.js before this fetch resolved) — show the chat bar /
      // story actions now that allSteps is populated. Both restore paths
      // only call addToFeed() and never reveal ncf-chat-bar on their own.
      try {
        if (resultsGrid && resultsGrid.children.length && typeof showResultActions === 'function') {
          var _restoredActionStep = allSteps.find(function (s) { return s.type === 'action'; });
          if (_restoredActionStep) showResultActions(_restoredActionStep);
        }
      } catch (e) {
        if (window.console) console.error('[FlowEngine] restore chat bar:', e);
      }
    })
    .catch(function (err) {
      console.error('[FlowEngine] Failed to load flow:', id, err);
      flowBootShowError(id);
    });
}

// Surfaces a "this flow no longer exists" state instead of leaving the panel
// silently blank — hit when a Session step's stored flow_id was renamed or
// removed since the step was created (e.g. old test steps from before a
// flow got consolidated/renamed). Reuses the steps scroll area + breadcrumb
// rather than a modal, since those are the only elements guaranteed to
// exist at this point (renderAllSteps() never ran).
function flowBootShowError(id) {
  var bc = document.getElementById('nsc-flow-breadcrumb');
  if (bc) bc.textContent = tF('Flow not found');
  var scroll = document.getElementById('ncf-steps-scroll');
  if (scroll) {
    scroll.innerHTML =
      '<div class="nsc-flow-boot-error">' +
      '<p class="nsc-flow-boot-error-title">' + escHtml(tF('This flow could not be opened')) + '</p>' +
      '<p class="nsc-flow-boot-error-sub">"' + id + '" no longer exists — it was likely renamed or removed since this step was created.</p>' +
      '</div>';
  }
}

// Session-native pages (ns_session_workspace.html) declare this flag before
// loading the engine scripts — they mount/unmount flows explicitly via
// FlowEngine.reset() (sessionMountFlow, nomad_studio.js) instead of booting
// automatically on script load. Standalone pages never set this flag, so
// their behavior is completely unchanged.
if (!window.__nomadSessionNative) {
  flowBootLoad(flowId);
}

// ── FlowEngine.reset() — mount a different flow in place, no page reload ───
// Cancels whatever the previously-mounted flow had in flight, wipes its
// state (flow-state.js's flowResetState), re-points the DOM ref cache at
// `containerEl` if given, and re-runs flowBootLoad() for the new flow_id.
// Not wired into any real UI path yet (see nomad_studio.js sessionMountFlow,
// added in a later phase) — exposed on window.FlowEngine so it can be
// exercised by hand from devtools first.
function flowCancelPending() {
  if (typeof activeES !== 'undefined' && activeES) {
    try { activeES.close(); } catch (_) {}
    activeES = null;
  }
  if (typeof _genQueue !== 'undefined') _genQueue = [];
  if (typeof isGenerating !== 'undefined') isGenerating = false;
  // Per-card ETA setInterval handles and vision-describe's _pollInterval are
  // scoped inside their own render closures and already self-clear once
  // their owning DOM node is detached (isConnected checks) — enforced by
  // whoever swaps the container's content before calling FlowEngineReset.
}

// Wipes the visible results feed back to its just-loaded-the-page look.
// renderAllSteps() (flow-render-all.js) only ever clears the STEPS panel —
// by design, since toggling Simple/Guided/Custom mode on an already-running
// flow must NOT lose the images you already generated. That design is
// wrong for a flow *switch*, though: without this, a card left over from
// the previous flow stays orphaned in the DOM (found by hand-testing a
// session-native mount — flowResetState() correctly zeroes generatedCount/
// sessionImages, but nothing had ever needed to clear the grid itself
// before, since every standalone page load already starts from an empty
// one straight out of the server-rendered HTML).
function flowResetResultsFeed() {
  if (resultsGrid) { resultsGrid.innerHTML = ''; resultsGrid.style.display = 'none'; }
  if (resultsEmpty) resultsEmpty.style.display = '';
  ['ncf-chat-bar', 'ncf-story-bar', 'ncf-refine-only-bar'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.hidden = true;
  });
  // The shared right-side options panel (Advanced/History/Model/the
  // image-picker's Crop-Inputs-Tray-History buttons, …) is a singleton
  // (#ncf-options-panel) — nothing ever closed it on a flow switch, so a
  // panel left open while reopening a different Session step stayed open,
  // still bound to the previous flow's now-gone step. Closing it here,
  // alongside the rest of this "wipe back to just-loaded" cleanup, covers
  // every caller for free.
  if (typeof closeOptionsPanel === 'function') closeOptionsPanel();
}

function FlowEngineReset(newFlowId, containerEl) {
  flowCancelPending();
  // Re-read whatever sessionMountFlow()/sessionReopenStep() just wrote to
  // 'oj-load-session' — the top-level _readPendingSession() call in
  // flow-state.js only ever fires once, at the very first script load, so
  // without this a step reopened after that (any session-native flow
  // switch) sees a stale/already-consumed _pendingSession and silently
  // skips restoring params + previous outputs. flowResetState() itself
  // deliberately does NOT do this (see its NOTE) — it's the caller's job.
  _pendingSession = _readPendingSession();
  flowResetState(newFlowId);
  if (containerEl) flowQueryRefs(containerEl);
  flowResetResultsFeed();
  return flowBootLoad(newFlowId);
}

window.FlowEngine = {
  reset: FlowEngineReset,
  cancelPending: flowCancelPending,
};

// ── Session-aware breadcrumb / back button ──────────────────────────────────
// When this flow was opened from a Session, the top bar should make that
// context obvious and send the user back INTO the session (not the generic
// section), so the working process isn't lost.
(function sessionContextChrome() {
  try {
    // Session-native mounts (ns_session_workspace.html) never render this
    // partial's own topbar (embedded=true skips it — see
    // layout/_flow_body.html) — the session page's own topbar already IS
    // the "in session" chrome, kept in sync by nomad_studio.js's
    // sessionMountFlow()/sessionUnmountFlow(). This retrofit (relabeling a
    // standalone page's default topbar into "BACK TO SESSION") only makes
    // sense for the standalone-tab case.
    if (window.__nomadSessionNative) return;
    var V = window.NomadSession;
    if (!V || !V.getPending) return;
    var p = V.getPending();
    if (!p || !p.sessionId) return;   // normal mode → leave the default chrome

    var sessionEntry = V.find ? V.find(p.sessionId) : null;
    var name = (sessionEntry && sessionEntry.name) || 'Session';

    var root = document.getElementById('nsc-flow-root');
    if (root) root.classList.add('nsc-flow--in-session');

    function returnToSession(e) {
      if (e) e.preventDefault();
      // Mounted natively inside the session workspace (same document) →
      // unmount instead of navigating. The window.parent branch is a
      // defensive fallback only — every real path today is same-window
      // (see nomad_studio.js window.__nomadCloseSessionFlowPanel).
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
      // Standalone tab (opened directly, or panel fallback) — go to the
      // workspace's own URL.
      window.location.href = '/nomad-studio/session/' + encodeURIComponent(p.sessionId);
    }

    var back = document.querySelector('.nsc-topbar .cs-back-btn');
    if (back) {
      back.setAttribute('href', '/nomad-studio');
      var backLbl = back.querySelector('span');
      if (backLbl) backLbl.textContent = tF('BACK TO SESSION');
      back.addEventListener('click', returnToSession);
    }

    var bc = document.querySelector('.nsc-topbar .cs-breadcrumb');
    if (bc) {
      var links = bc.querySelectorAll('a');
      // links[1] is the section link (Refine/Create) — repurpose it as the session.
      var seg = links[1];
      if (seg) {
        seg.textContent = name;
        seg.setAttribute('href', '/nomad-studio');
        seg.classList.add('cs-breadcrumb-session');
        seg.addEventListener('click', returnToSession);
      }
    }
  } catch (_) {}
})();

