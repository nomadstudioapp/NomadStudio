'use strict';
// "Active Depot" indicator — while a Depot is active, everything generated
// goes into it, so the user should see that on every page, not only in
// Build. Server-side state only (session["active_depot_id"]); this mirrors it.
//
// Two places show it:
//   - a badge in each page's top bar (.nsc-topbar-depot): the flow pages,
//     Session and Build carry it in their templates; every other page with a
//     .cs-sub-header (Create/Refine/Mix hubs, Album, Settings…) gets one
//     added here, placed right of the top bar's search slot;
//   - next to the home page's "What do you want to create today?".
// The badge opens Build in a new tab, so an open flow and its running job
// are not lost. Elements are looked up on every refresh: shell_router.js
// swaps pages in without a reload.
(function () {
  var BADGE_SVG =
    '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>' +
    '<path d="M3.3 7 12 12l8.7-5M12 22V12"/></svg>';

  function tipText() {
    var fallback = 'Active Depot — everything you generate is saved here. Opens Build in a new tab.';
    return (window.NomadI18n && window.NomadI18n.t) ? window.NomadI18n.t('depot.badgeTip', fallback) : fallback;
  }

  function makeBadge(extraClass) {
    var a = document.createElement('a');
    a.className = 'nsc-topbar-depot ' + extraClass;
    a.hidden = true;
    a.innerHTML = BADGE_SVG + '<span class="nsc-topbar-depot-name"></span>';
    return a;
  }

  // Same look and behaviour for badges from templates and from here: new
  // tab, the app's tooltip instead of the browser's plain title.
  function normalize(badge) {
    badge.href = '/build';
    badge.target = '_blank';
    badge.rel = 'noopener';
    badge.removeAttribute('title');
    var tip = badge.querySelector('.cs-mode-tip');
    if (!tip) {
      tip = document.createElement('span');
      tip.className = 'cs-mode-tip';
      badge.appendChild(tip);
    }
    tip.textContent = tipText();
  }

  function ensureBadges() {
    document.querySelectorAll('.cs-sub-header').forEach(function (header) {
      if (!header.querySelector('.nsc-topbar-depot')) header.appendChild(makeBadge('nsc-depot-badge--auto'));
    });
    var subtitle = document.getElementById('cs-subtitle');
    if (subtitle && !document.getElementById('cs-hero-depot')) {
      var row = document.createElement('div');
      row.className = 'cs-subtitle-row';
      subtitle.parentNode.insertBefore(row, subtitle);
      row.appendChild(subtitle);
      var badge = makeBadge('nsc-depot-badge--hero');
      badge.id = 'cs-hero-depot';
      row.appendChild(badge);
    }
    var badges = document.querySelectorAll('.nsc-topbar-depot');
    badges.forEach(normalize);
    return badges;
  }

  function refresh() {
    var badges = ensureBadges();
    if (!badges.length) return Promise.resolve();
    return fetch('/api/depots/active')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var depot = data && data.depot;
        badges.forEach(function (b) {
          b.hidden = !depot;
          var nameEl = b.querySelector('.nsc-topbar-depot-name, #nsc-topbar-depot-name');
          if (depot && nameEl) nameEl.textContent = depot.name;
        });
      })
      .catch(function () {
        badges.forEach(function (b) { b.hidden = true; });
      });
  }

  // Build's Activate button changes the state without a page load, and
  // shell_router.js swaps pages in without one either.
  window.NomadDepotIndicator = { refresh: refresh };
  window.addEventListener('oj:shell:navigate-end', refresh);
  document.addEventListener('nomad-i18n-applied', function () {
    document.querySelectorAll('.nsc-topbar-depot .cs-mode-tip').forEach(function (t) { t.textContent = tipText(); });
  });
  refresh();
})();
