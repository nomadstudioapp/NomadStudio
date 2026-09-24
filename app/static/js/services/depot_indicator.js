'use strict';
// Sidebar "Active Depot" indicator (see layout/base.html's #sidebar-depot-panel)
// — shown on every page, not just Build, since a Depot gets activated on the
// Build > Depot detail page but generations happen on Create/Refine/Mix/
// Upscale. Server-side state only (session["active_depot_id"]); this just
// mirrors it on load and lets you deactivate from anywhere.
(function () {
  // Flow pages (Create/Refine/Mix/Upscale/Session) and Build also show a badge
  // in the topbar — see _flow_body.html / ns_session_workspace.html /
  // library.html's #nsc-topbar-depot. Not every page has it, so this half of
  // the indicator is optional. The elements are looked up on every refresh,
  // not once at startup: shell_router.js swaps pages in without a reload, so
  // the badge of the page you land on may not have existed when this ran.
  function els() {
    return {
      panel: document.getElementById('sidebar-depot-panel'),
      nameEl: document.getElementById('sidebar-depot-name'),
      topbarBadge: document.getElementById('nsc-topbar-depot'),
      topbarNameEl: document.getElementById('nsc-topbar-depot-name'),
    };
  }

  function refresh() {
    var e = els();
    if (!e.panel && !e.topbarBadge) return Promise.resolve();
    return fetch('/api/depots/active')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var depot = data && data.depot;
        if (e.panel) e.panel.hidden = !depot;
        if (depot && e.nameEl) e.nameEl.textContent = depot.name;
        if (e.topbarBadge) e.topbarBadge.hidden = !depot;
        if (depot && e.topbarNameEl) e.topbarNameEl.textContent = depot.name;
      })
      .catch(function () {
        if (e.panel) e.panel.hidden = true;
        if (e.topbarBadge) e.topbarBadge.hidden = true;
      });
  }

  var deactivateBtn = document.getElementById('sidebar-depot-deactivate-btn');
  if (deactivateBtn) {
    deactivateBtn.addEventListener('click', function () {
      deactivateBtn.disabled = true;
      fetch('/api/depots/deactivate', { method: 'POST' })
        .then(refresh)
        .catch(function (err) { console.error('[DepotIndicator] Deactivate failed:', err); })
        .finally(function () { deactivateBtn.disabled = false; });
    });
  }

  // Build's Activate button changes the state without a page load, and
  // shell_router.js swaps pages in without one either.
  window.NomadDepotIndicator = { refresh: refresh };
  window.addEventListener('oj:shell:navigate-end', refresh);
  refresh();
})();
