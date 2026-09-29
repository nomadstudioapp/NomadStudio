'use strict';
// Album view-mode controller — toggles between "Flows" (session-history
// cards, album_gallery.js) and "Images" (full server-backed gallery,
// album_images.js) via the round button prepended above the card-zoom
// stack (#album-card-zoom). Owns body.explore-page-body: only true while
// Images mode is actually visible, never left on permanently, since several
// shared .explore-* CSS rules key off it page-wide (see issue #78).

(function albumViewMode() {
  var KEY = 'ns-album-view-mode'; // 'flows' | 'images'

  var flowsView = document.getElementById('album-flows-view');
  var imagesView = document.getElementById('album-images-view');
  var toggleBtn = document.getElementById('album-view-toggle');
  var iconEl = document.getElementById('album-view-toggle-icon');
  var tipEl = document.getElementById('album-view-toggle-tip');
  if (!flowsView || !imagesView || !toggleBtn) return;

  var imagesInitialized = false;

  // Flows mode's own icon (shown on the button while Images is active, as
  // the destination the click leads back to) — a simple 3-node flow diagram,
  // matching the plain-stroke SVG convention every other button here uses.
  var ICON_IMAGES = '<rect x="3" y="7" width="14" height="14" rx="2"/><path d="M7 7V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-2"/>';
  var ICON_FLOWS = '<circle cx="6" cy="6" r="2.2"/><circle cx="18" cy="6" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="M6 8.2v2.3a3 3 0 0 0 3 3h1.5M18 8.2v2.3a3 3 0 0 0-3 3h-1.5"/>';

  function apply(mode) {
    var isImages = mode === 'images';
    flowsView.hidden = isImages;
    imagesView.hidden = !isImages;
    document.body.classList.toggle('explore-page-body', isImages);
    toggleBtn.setAttribute('aria-pressed', String(isImages));
    toggleBtn.setAttribute('aria-label', tF(isImages ? 'Switch to Flows view' : 'Switch to Images view'));
    if (tipEl) tipEl.textContent = tF(isImages ? 'Flows view' : 'Images view');
    if (iconEl) iconEl.innerHTML = isImages ? ICON_FLOWS : ICON_IMAGES;
    if (isImages && !imagesInitialized && window.albumImagesPage) {
      imagesInitialized = true;
      window.albumImagesPage.init();
    }
    // The shared round zoom buttons (#album-card-zoom) and the count badge
    // (#album-count) are written by whichever mode is active — resync both
    // to the mode we just switched TO, since the other mode's data may have
    // left them showing something stale.
    if (isImages && window.albumImagesPage) {
      window.albumImagesPage.refresh();
      window.albumImagesPage.syncZoom();
    } else if (!isImages && window.albumGalleryPage) {
      window.albumGalleryPage.refresh();
      window.albumGalleryPage.syncZoom();
    }
    if (!isImages) {
      // The Images viewer modal lives at document.body level (see
      // ensureViewerModal in album_images.js — moved there to escape
      // .album-layout's own stacking context). Since it's no longer inside
      // #album-images-view, hiding that container alone wouldn't close it.
      var viewerModal = document.getElementById('album-images-viewer-modal');
      if (viewerModal) {
        viewerModal.classList.remove('open');
        document.body.classList.remove('viewer-open');
      }
    }
  }

  toggleBtn.addEventListener('click', function () {
    var next = flowsView.hidden ? 'flows' : 'images';
    try { localStorage.setItem(KEY, next); } catch (_) {}
    apply(next);
  });

  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (_) {}
  apply(saved === 'images' ? 'images' : 'flows');
})();
