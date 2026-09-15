'use strict';
// Sidebar "Active Depot" indicator (see layout/base.html's #sidebar-depot-panel)
// — shown on every page, not just Build, since a Depot gets activated on the
// Build > Depot detail page but generations happen on Create/Refine/Mix/
// Upscale. Server-side state only (session["active_depot_id"]); this just
// mirrors it on load and lets you deactivate from anywhere.
(function () {
  var panel = document.getElementById('sidebar-depot-panel');
  var nameEl = document.getElementById('sidebar-depot-name');
  var deactivateBtn = document.getElementById('sidebar-depot-deactivate-btn');
  // Flow pages (Create/Refine/Mix/Upscale/Session) also show a badge in the
  // topbar, centered next to the viewer name — see _flow_body.html /
  // ns_session_workspace.html's #nsc-topbar-depot. Not every page has it
  // (only flow pages do), so this half of the indicator is optional.
  var topbarBadge = document.getElementById('nsc-topbar-depot');
  var topbarNameEl = document.getElementById('nsc-topbar-depot-name');
  if (!panel && !topbarBadge) return;

  function refresh() {
    fetch('/api/depots/active')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var depot = data && data.depot;
        if (panel) panel.hidden = !depot;
        if (depot && nameEl) nameEl.textContent = depot.name;
        if (topbarBadge) topbarBadge.hidden = !depot;
        if (depot && topbarNameEl) topbarNameEl.textContent = depot.name;
      })
      .catch(function () {
        if (panel) panel.hidden = true;
        if (topbarBadge) topbarBadge.hidden = true;
      });
  }

  if (deactivateBtn) {
    deactivateBtn.addEventListener('click', function () {
      deactivateBtn.disabled = true;
      fetch('/api/depots/deactivate', { method: 'POST' })
        .then(refresh)
        .catch(function (err) { console.error('[DepotIndicator] Deactivate failed:', err); })
        .finally(function () { deactivateBtn.disabled = false; });
    });
  }

  refresh();
})();
