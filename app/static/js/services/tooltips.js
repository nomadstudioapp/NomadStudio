/* Hover tooltips that never get clipped.

   Every tooltip in Nomad Studio is a <span class="…-tip"> inside the element
   that triggers it, positioned with CSS (top/bottom + left:50%). That breaks
   in two ways seen on screen: a tooltip inside a card with `overflow:hidden`
   is cut by the card, and one near the edge of the window is cut by the
   window — the "Advance", "Smaller cards" and "Show filters" ones.

   While a tooltip is visible this moves it to <body> and positions it with
   fixed coordinates next to its trigger, clamped to the window. Nothing in
   the markup or the existing CSS changes: the tooltip goes back where it was
   as soon as the pointer leaves, so the normal :hover rules keep working (and
   keep working on their own if this script never loads).

   `position: fixed` alone would not be enough: a transformed ancestor (the
   cards scale on hover) makes fixed positioning relative to that ancestor. */
(function () {
  'use strict';

  var CLASSES = ['cs-mode-tip', 'action-tip', 'ncf-chat-tip', 'cs-lang-tip'];
  var CHILD_SELECTOR = CLASSES.map(function (c) { return ':scope > .' + c; }).join(', ');
  var MARGIN = 8;   // never closer than this to the edge of the window
  var GAP = 7;      // between trigger and tooltip, as the CSS uses
  var MAX_DEPTH = 6;

  var open = null;  // { tip, holder, trigger, wasAbove }

  // Where the tooltip goes, in window coordinates. Pure geometry: kept
  // separate (and exported) so it can be tested without a browser.
  function place(trigger, tip, view, prefersAbove) {
    var left = trigger.left + trigger.width / 2 - tip.width / 2;
    left = Math.min(Math.max(left, MARGIN), Math.max(MARGIN, view.width - MARGIN - tip.width));
    var above = prefersAbove;
    if (above && trigger.top - GAP - tip.height < MARGIN) above = false;
    else if (!above && trigger.bottom + GAP + tip.height > view.height - MARGIN) above = true;
    var top = above ? trigger.top - GAP - tip.height : trigger.bottom + GAP;
    top = Math.min(Math.max(top, MARGIN), Math.max(MARGIN, view.height - MARGIN - tip.height));
    return { left: Math.round(left), top: Math.round(top), above: above };
  }

  function findTip(node) {
    for (var i = 0; node && node.nodeType === 1 && i < MAX_DEPTH; i++, node = node.parentElement) {
      var tip = node.querySelector ? node.querySelector(CHILD_SELECTOR) : null;
      if (tip) return { trigger: node, tip: tip };
    }
    return null;
  }

  function hide() {
    if (!open) return;
    var tip = open.tip;
    tip.classList.remove('nt-tip-floating');
    tip.removeAttribute('style');
    if (open.holder.parentNode) open.holder.parentNode.replaceChild(tip, open.holder);
    else if (tip.parentNode) tip.parentNode.removeChild(tip);
    open = null;
  }

  function show(trigger, tip) {
    if (open && open.tip === tip) return;
    hide();
    if (!tip.parentNode || !document.body) return;
    // Which side the CSS wanted: the ones pinned with `bottom` open upward.
    var prefersAbove = window.getComputedStyle(tip).bottom !== 'auto';
    var holder = document.createComment('tip');
    tip.parentNode.insertBefore(holder, tip);
    document.body.appendChild(tip);
    tip.classList.add('nt-tip-floating');
    open = { tip: tip, holder: holder, trigger: trigger };

    var view = { width: window.innerWidth, height: window.innerHeight };
    var size = tip.getBoundingClientRect();
    // A tooltip wider than the window (long single-line labels) has to wrap.
    if (size.width > view.width - 2 * MARGIN) {
      tip.style.whiteSpace = 'normal';
      tip.style.maxWidth = (view.width - 2 * MARGIN) + 'px';
      size = tip.getBoundingClientRect();
    }
    var at = place(trigger.getBoundingClientRect(), { width: size.width, height: size.height }, view, prefersAbove);
    tip.style.left = at.left + 'px';
    tip.style.top = at.top + 'px';
  }

  function onOver(e) {
    var found = findTip(e.target);
    if (!found) return hide();
    if (open && open.trigger === found.trigger) return;
    show(found.trigger, found.tip);
  }

  function onOut(e) {
    if (!open) return;
    var to = e.relatedTarget;
    if (to && (open.trigger.contains(to) || to === open.tip)) return;
    hide();
  }

  document.addEventListener('pointerover', onOver, true);
  document.addEventListener('pointerout', onOut, true);
  document.addEventListener('focusin', function (e) {
    var found = findTip(e.target);
    if (found) show(found.trigger, found.tip);
    else hide();
  }, true);
  document.addEventListener('focusout', hide, true);
  // A click usually changes what is under the pointer (menus, page changes);
  // scrolling would leave the tooltip floating where the trigger no longer is.
  document.addEventListener('click', hide, true);
  document.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
  window.addEventListener('beforeunload', hide);

  window.NomadTooltips = { place: place, hide: hide };
})();
