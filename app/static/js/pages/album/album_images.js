'use strict';
// Album "Images" mode — the full server-backed gallery, ported from
// explore.js (/generations) into a lazily-initialized module the Flows/Images
// toggle (view_mode.js) activates on first switch. Same logic throughout,
// only the element ids are renamed (explore-* -> album-images-*) and the
// init boundary changed from "runs immediately on script load" to an
// explicit window.albumImagesPage.init() the controller calls once.
//
// document.body.classList.add('explore-page-body') is intentionally NOT
// here — view_mode.js owns that toggle now, since Images is one of two
// sub-views on this page, not the whole page like /generations is.

window.albumImagesPage = (function albumImagesModule() {
  // See settings.js's identical helper for the rationale (window.NomadI18n.t
  // covers text this module builds dynamically — data-i18n in the HTML only
  // reaches server-rendered markup). `vars` does simple `{token}` swaps.
  function t(key, fallback, vars) {
    var text = window.NomadI18n ? window.NomadI18n.t(key, fallback) : fallback;
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        text = text.replace('{' + k + '}', vars[k]);
      });
    }
    return text;
  }

  let inited = false;
  // Set once init() has built its closures, so view_mode.js can ask this
  // (now-active) mode to resync the shared count badge / zoom-button state
  // it doesn't own exclusively — see refresh()/syncZoom() at the bottom.
  let _refreshRef = null;
  let _syncZoomRef = null;

  async function init() {
    if (inited) return;
    inited = true;

    const statusEl = document.getElementById('album-images-status');
    const groupsEl = document.getElementById('album-images-groups');
    const emptyEl = document.getElementById('album-images-empty');
    const searchEl = document.getElementById('album-images-search-input');
    const searchBarEl = searchEl ? searchEl.closest('.explore-searchbar') : null;
    // Shared with Flows mode's own count (.nsc-topbar, always in the DOM
    // regardless of active view) — whichever mode is active writes here.
    const searchCountEl = document.getElementById('album-count');
    const explorePageEl = document.getElementById('album-images-view');
    // Shared round buttons (#album-card-zoom in album.html) — Flows mode's
    // own zoom control, repurposed here too: each mode's click handler
    // below only acts while its own view is the one currently visible (see
    // the explorePageEl.hidden guards), so the two can share the buttons
    // without stepping on each other.
    const zoomInBtn = document.getElementById('album-card-zoom-in');
    const zoomOutBtn = document.getElementById('album-card-zoom-out');
    const zoomResetBtn = document.getElementById('album-card-zoom-reset');
    const favoritesToggleBtn = document.getElementById('album-images-favorites-toggle');
    const diamondToggleBtn = document.getElementById('album-images-diamond-toggle');
    const groupButtons = Array.from(document.querySelectorAll('[data-album-images-group]'));
    const viewerModalEl = document.getElementById('album-images-viewer-modal');

    if (!statusEl || !groupsEl || !emptyEl || !searchEl || !zoomInBtn || !zoomOutBtn || !explorePageEl || !favoritesToggleBtn || !diamondToggleBtn) {
      return;
    }

    const EXPLORE_THUMB_SIZE_KEY = 'oj-explore-thumb-min-v1';
    const SHOW_DIAMOND_IMAGES_KEY = 'oj-image-diamond-mode-v2';
    const UPSCALE_SOURCE_IMAGE_KEY = 'oj-upscale-source-image-v1';

    const THUMB_MIN = 180;
    const THUMB_MAX = 520;
    const THUMB_STEP = 40;
    const THUMB_DEFAULT = 320;

    const STOP_WORDS = new Set([
      'the', 'and', 'with', 'for', 'this', 'that', 'from', 'into', 'very', 'best', 'highly',
      'image', 'prompt', 'style', 'quality', 'detail', 'detailed', 'lighting', 'scene', 'view'
    ]);

    let galleryCache = [];
    let gallerySource = 'store';
    let groupMode = 'day';
    const INITIAL_RENDER_LIMIT = 24;
    const RENDER_STEP = 24;
    const ALBUM_PAGE_FETCH_LIMIT = 200;
    let renderLimit = INITIAL_RENDER_LIMIT;
    let groupedCache = [];
    let totalFilteredCount = 0;
    let isLoadingMore = false;
    let isSearchHydrationLoading = false;
    let searchHydrationToken = 0;
    let searchHydrationPromise = null;
    let backendPagingState = {
      limit: ALBUM_PAGE_FETCH_LIMIT,
      nextCursor: null,
      snapshotCursor: null,
      hasMore: false,
      loading: false,
      total: 0,
    };
    let thumbMinSize = THUMB_DEFAULT;
    let showDiamondMarkedImages = false;
    let favoritesOnly = false;
    let viewerState = {
      items: [],
      index: 0,
    };
    let viewerElements = null;
    const loadSentinelEl = document.createElement('div');
    loadSentinelEl.className = 'explore-load-sentinel';
    loadSentinelEl.textContent = t('album.viewer.scrollToLoadMore', 'Scroll to load more...');
    groupsEl.insertAdjacentElement('afterend', loadSentinelEl);

    function usesContainerScroll() {
      const overflowY = window.getComputedStyle(explorePageEl).overflowY;
      return overflowY === 'auto' || overflowY === 'scroll';
    }

    function normalizeTagSlug(raw) {
      return String(raw || '')
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9\s-]+/g, '')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-+|-+$/g, '');
    }

    function uniqueTagSlugs(values) {
      const seen = new Set();
      const out = [];
      (Array.isArray(values) ? values : []).forEach((value) => {
        const slug = normalizeTagSlug(value);
        if (!slug || seen.has(slug)) return;
        seen.add(slug);
        out.push(slug);
      });
      return out;
    }

    function normalizeSessionValue(raw) {
      const compact = String(raw || '').replace(/\s+/g, ' ').trim();
      if (!compact) return '';
      return compact.slice(0, 60);
    }

    function isDiamondMarked(value) {
      if (value === true) return true;
      if (typeof value === 'string') {
        const normalized = value.trim().toLowerCase();
        return normalized === 'true' || normalized === '1' || normalized === 'yes' || normalized === 'on';
      }
      if (typeof value === 'number') {
        return value === 1;
      }
      return false;
    }

    function setStatus(message, isError = false) {
      statusEl.innerHTML = message;
      statusEl.classList.toggle('status-error', isError);
    }

    function updateSearchCount(shownCount, totalCount) {
      if (!searchCountEl) return;
      const shown = Math.max(0, Number(shownCount) || 0);
      const localTotal = Math.max(0, Number(totalCount) || 0);
      const total = (backendPagingState && backendPagingState.total > localTotal)
        ? backendPagingState.total
        : localTotal;
      searchCountEl.textContent = `${shown.toLocaleString()} / ${total.toLocaleString()}`;
    }

    function updateSearchLoadingUi() {
      if (!searchBarEl) return;
      const hasQuery = String(searchEl.value || '').trim().length > 0;
      const showLoading = hasQuery && (isSearchHydrationLoading || backendPagingState.loading);
      searchBarEl.classList.toggle('explore-searchbar--loading', showLoading);
      searchBarEl.setAttribute('aria-busy', showLoading ? 'true' : 'false');
    }

    function applyThumbSize() {
      const bounded = Math.max(THUMB_MIN, Math.min(THUMB_MAX, Number(thumbMinSize) || THUMB_DEFAULT));
      thumbMinSize = bounded;
      explorePageEl.style.setProperty('--explore-thumb-min', `${bounded}px`);
      // Only claim the shared round zoom buttons' disabled state while this
      // is actually the visible mode — Flows mode's own zoom (album_gallery.js)
      // sets the same attribute for its own bounds when it's the one showing.
      if (!explorePageEl.hidden) {
        zoomInBtn.disabled = bounded >= THUMB_MAX;
        zoomOutBtn.disabled = bounded <= THUMB_MIN;
      }
    }

    function persistThumbSize() {
      try {
        localStorage.setItem(EXPLORE_THUMB_SIZE_KEY, String(thumbMinSize));
      } catch {
        // Ignore storage failures.
      }
    }

    function restoreThumbSize() {
      try {
        const raw = Number(localStorage.getItem(EXPLORE_THUMB_SIZE_KEY));
        if (Number.isFinite(raw)) {
          thumbMinSize = raw;
        }
      } catch {
        thumbMinSize = THUMB_DEFAULT;
      }
      applyThumbSize();
    }

    function restoreDiamondVisibility() {
      try {
        const raw = localStorage.getItem(SHOW_DIAMOND_IMAGES_KEY);
        if (raw === null) {
          showDiamondMarkedImages = false;
        } else {
          showDiamondMarkedImages = raw === '1';
        }
      } catch {
        showDiamondMarkedImages = false;
      }
    }

    function persistDiamondVisibility() {
      try {
        localStorage.setItem(SHOW_DIAMOND_IMAGES_KEY, showDiamondMarkedImages ? '1' : '0');
      } catch {
        // Ignore storage failures.
      }
    }

    function applyFavoritesToggleUi() {
      if (!favoritesToggleBtn) return;
      favoritesToggleBtn.classList.toggle('active', favoritesOnly);
      favoritesToggleBtn.setAttribute('aria-pressed', favoritesOnly ? 'true' : 'false');
      favoritesToggleBtn.setAttribute('aria-label', favoritesOnly ? 'Show all images' : 'Show favorites only');
    }

    function applyDiamondToggleUi() {
      if (!diamondToggleBtn) return;
      diamondToggleBtn.classList.toggle('active', showDiamondMarkedImages);
      diamondToggleBtn.setAttribute('aria-pressed', showDiamondMarkedImages ? 'true' : 'false');
      diamondToggleBtn.setAttribute('aria-label', showDiamondMarkedImages ? 'Hide diamond images' : 'Show diamond images');
    }

    function resolveWorkflowDisplayName(meta) {
      const workflowName = String((meta && meta.workflow_name) || '').trim();
      if (workflowName) return workflowName;
      const workflowRaw = String((meta && meta.workflow) || '').trim();
      // Avoid showing internal import ids (e.g. imp-xxxx) as workflow names.
      if (/^imp-[a-z0-9]+$/i.test(workflowRaw)) return '';
      return workflowRaw;
    }

    function mapServerItemsToGallery(items, existing = []) {
      const api = window.openJourneyApi;
      if (!api || typeof api.getImageUrl !== 'function') {
        return Array.isArray(existing) ? [...existing] : [];
      }

      const mapper = window.openJourneyAlbumMapper;
      if (mapper && typeof mapper.appendUniqueBatches === 'function') {
        return mapper.appendUniqueBatches(existing, items, api);
      }

      const output = Array.isArray(existing) ? [...existing] : [];
      const seen = new Set(output.map((entry) => String(entry && entry.id || '')));
      (Array.isArray(items) ? items : []).forEach((item) => {
        if (!item || !item.filename) return;
        const batchId = `server-${item.filename}`;
        if (seen.has(batchId)) return;
        seen.add(batchId);
        const meta = item.meta || {};
        const sidecar = item.sidecar || {};
        const workflowDisplayName = resolveWorkflowDisplayName(meta);
        output.push({
          id: batchId,
          createdAt: item.createdAt || new Date().toISOString(),
          status: 'ready',
          source: meta.source || 'server',
          session: meta.session || '',
          width: meta.width ? Number(meta.width) : undefined,
          height: meta.height ? Number(meta.height) : undefined,
          seed: meta.seed || '',
          basicValues: {
            positive: meta.positive || '',
            negative: meta.negative || '',
            checkpoint: meta.checkpoint || '',
          },
          workflowMeta: {
            importId: meta.workflow || '',
            importName: workflowDisplayName,
            checkpoint: meta.checkpoint || '',
          },
          images: [
            {
              imageDataUrl: api.getImageUrl(item.filename),
              filename: item.filename,
              favorite: !!sidecar.favorite,
              diamond: !!sidecar.diamond,
              tags: Array.isArray(sidecar.tags) ? sidecar.tags : [],
            },
          ],
        });
      });
      return output;
    }

    async function initializeGalleryStorage() {
      galleryCache = [];
      backendPagingState = {
        limit: ALBUM_PAGE_FETCH_LIMIT,
        nextCursor: null,
        snapshotCursor: null,
        hasMore: false,
        loading: false,
        total: 0,
      };
      try {
        const api = window.openJourneyApi;
        if (!api || typeof api.listImages !== 'function') return;

        const paging = window.openJourneyAlbumPaging;
        let items = [];
        let pagingMeta = null;

        if (paging && typeof paging.fetchPage === 'function') {
          const firstPage = await paging.fetchPage(api, { limit: backendPagingState.limit });
          items = Array.isArray(firstPage && firstPage.images) ? firstPage.images : [];
          pagingMeta = firstPage && firstPage.paging ? firstPage.paging : null;
        } else {
          const result = await api.listImages({ limit: backendPagingState.limit });
          items = Array.isArray(result && result.images) ? result.images : [];
          pagingMeta = result && result.paging ? result.paging : null;
        }

        galleryCache = mapServerItemsToGallery(items);
        backendPagingState.hasMore = !!(pagingMeta && pagingMeta.hasMore);
        backendPagingState.nextCursor = pagingMeta && pagingMeta.nextCursor ? String(pagingMeta.nextCursor) : null;
        backendPagingState.snapshotCursor = pagingMeta && pagingMeta.snapshotCursor ? String(pagingMeta.snapshotCursor) : null;
        backendPagingState.total = pagingMeta && pagingMeta.total ? Number(pagingMeta.total) : 0;
        gallerySource = 'server';
      } catch (_e) {
        galleryCache = [];
        backendPagingState.hasMore = false;
        gallerySource = 'store';
      } finally {
        updateSearchLoadingUi();
      }
    }

    async function fetchNextGalleryPage() {
      if (gallerySource !== 'server') return false;
      if (!backendPagingState.hasMore || backendPagingState.loading) return false;

      const api = window.openJourneyApi;
      if (!api || typeof api.listImages !== 'function') return false;

      backendPagingState.loading = true;
      updateSearchLoadingUi();
      try {
        const paging = window.openJourneyAlbumPaging;
        let response = null;
        if (paging && typeof paging.fetchPage === 'function') {
          response = await paging.fetchPage(api, {
            limit: backendPagingState.limit,
            cursor: backendPagingState.nextCursor || '',
            snapshot: backendPagingState.snapshotCursor || '',
          });
        } else {
          response = await api.listImages({
            limit: backendPagingState.limit,
            cursor: backendPagingState.nextCursor || '',
            snapshot: backendPagingState.snapshotCursor || '',
          });
        }

        const pageItems = Array.isArray(response && response.images) ? response.images : [];
        const pagingMeta = response && response.paging ? response.paging : null;
        galleryCache = mapServerItemsToGallery(pageItems, galleryCache);
        backendPagingState.hasMore = !!(pagingMeta && pagingMeta.hasMore);
        backendPagingState.nextCursor = pagingMeta && pagingMeta.nextCursor ? String(pagingMeta.nextCursor) : null;
        if (pagingMeta && pagingMeta.snapshotCursor) {
          backendPagingState.snapshotCursor = String(pagingMeta.snapshotCursor);
        }
        if (pagingMeta && pagingMeta.total) {
          backendPagingState.total = Number(pagingMeta.total);
        }
        return pageItems.length > 0;
      } catch (_err) {
        backendPagingState.hasMore = false;
        backendPagingState.nextCursor = null;
        backendPagingState.snapshotCursor = null;
        return false;
      } finally {
        backendPagingState.loading = false;
        updateSearchLoadingUi();
      }
    }

    async function ensureSearchScopeLoaded() {
      if (gallerySource !== 'server') return;
      const queryAtStart = String(searchEl.value || '').trim();
      if (!queryAtStart || !backendPagingState.hasMore) {
        isSearchHydrationLoading = false;
        updateSearchLoadingUi();
        return;
      }
      if (searchHydrationPromise) return searchHydrationPromise;

      const token = ++searchHydrationToken;
      isSearchHydrationLoading = true;
      updateSearchLoadingUi();

      searchHydrationPromise = (async () => {
        while (token === searchHydrationToken && backendPagingState.hasMore) {
          const loaded = await fetchNextGalleryPage();
          if (!loaded) break;
          if (String(searchEl.value || '').trim() !== queryAtStart) break;
          renderGroups(false);
        }
      })();

      try {
        await searchHydrationPromise;
      } finally {
        if (token === searchHydrationToken) {
          isSearchHydrationLoading = false;
        }
        searchHydrationPromise = null;
        updateSearchLoadingUi();
      }
    }

    async function persistGallery(images) {
      galleryCache = Array.isArray(images) ? images : [];
      // Server-backed gallery is read-only from the frontend (saves happen server-side).
    }

    function tokenize(text) {
      return String(text || '')
        .toLowerCase()
        .replace(/[^a-z0-9\s]+/g, ' ')
        .split(/\s+/)
        .map((s) => s.trim())
        .filter((s) => s.length >= 3 && !STOP_WORDS.has(s));
    }

    function escapeHtml(text) {
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function flattenGalleryItems() {
      const items = [];
      galleryCache.forEach((batch) => {
        if (!batch || batch.status === 'pending' || batch.status === 'failed') return;
        const tiles = Array.isArray(batch.images) && batch.images.length
          ? batch.images
          : (batch.imageDataUrl ? [{ imageDataUrl: batch.imageDataUrl }] : []);
        const prompt = String(batch.basicValues?.positive || '').trim();
        const keywords = tokenize(prompt);
        const createdAt = String(batch.createdAt || new Date().toISOString());
        const dayKey = createdAt.slice(0, 10);
        tiles.forEach((tile, index) => {
          if (!tile || !tile.imageDataUrl) return;
          const tags = uniqueTagSlugs(tile.tags);
          const workflowCheckpointRaw = String(
            batch.workflowMeta?.checkpoint || batch.basicValues?.checkpoint || batch.basicValues?.ckpt_name || ''
          ).trim();
          items.push({
            id: `${batch.id}:${index}`,
            batchId: String(batch.id || ''),
            index,
            imageDataUrl: tile.imageDataUrl,
            filename: String(tile.filename || ''),
            favorite: !!tile.favorite,
            diamond: isDiamondMarked(tile.diamond),
            prompt,
            keywords,
            tags,
            session: normalizeSessionValue(batch.session),
            dayKey,
            createdAt,
            width: Number(batch.width) || null,
            height: Number(batch.height) || null,
            seed: batch.seed != null ? String(batch.seed) : '',
            checkpoint: workflowCheckpointRaw.replace(/\.safetensors$/i, ''),
            workflow: String(batch.workflowMeta?.importName || batch.workflowName || ''),
            cfg: batch.workflowMeta?.cfg != null ? String(batch.workflowMeta.cfg).trim() : '',
            steps: batch.workflowMeta?.steps != null ? String(batch.workflowMeta.steps).trim() : '',
            negative: String(batch.basicValues?.negative || '').trim(),
            loras: batch.workflowMeta?.loras || [],
            generationSecs: batch.generationSecs != null ? batch.generationSecs : null,
          });
        });
      });
      return items;
    }

    function groupByDay(items) {
      const map = new Map();
      items.forEach((item) => {
        const key = item.dayKey || 'unknown-day';
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(item);
      });
      return [...map.entries()].sort((a, b) => (a[0] > b[0] ? -1 : 1));
    }

    function groupByWord(items, query) {
      const trimmed = String(query || '').trim().toLowerCase();
      if (trimmed) {
        return [[`Search: ${trimmed}`, items]];
      }

      const scores = new Map();
      items.forEach((item) => {
        item.keywords.forEach((word) => {
          scores.set(word, (scores.get(word) || 0) + 1);
        });
      });

      const topWords = [...scores.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 14)
        .map(([word]) => word);

      return topWords.map((word) => [
        `#${word}`,
        items.filter((item) => item.keywords.includes(word)),
      ]);
    }

    function buildGroups(items, query) {
      if (groupMode === 'favorites') {
        const onlyFavs = items.filter((item) => item.favorite);
        return [['Favorites', onlyFavs]];
      }
      if (groupMode === 'word') {
        return groupByWord(items, query);
      }
      return groupByDay(items);
    }

    function filterItems(items, query) {
      const terms = tokenize(query);
      if (!terms.length) return items;
      return items.filter((item) => {
        const prompt = String(item.prompt || '').toLowerCase();
        return terms.every((term) => prompt.includes(term));
      });
    }

    function filterItemsByDiamondVisibility(items) {
      if (!showDiamondMarkedImages) return items;
      return (Array.isArray(items) ? items : []).filter((item) => !isDiamondMarked(item.diamond));
    }

    function filterItemsByFavoritesToggle(items) {
      if (!favoritesOnly) return items;
      return (Array.isArray(items) ? items : []).filter((item) => !!item.favorite);
    }

    function renderThumb(item) {
      const arStyle = (item.width && item.height) ? ` style="aspect-ratio:${item.width}/${item.height};"` : '';
      const api = window.openJourneyApi;
      const thumbUrl = (item.filename && api && typeof api.getImageThumbUrl === 'function')
        ? api.getImageThumbUrl(item.filename, Math.round(thumbMinSize * 1.5))
        : item.imageDataUrl;
      return `
        <article class="explore-thumb explore-thumb--loading" data-open-item-id="${item.id}"${arStyle}>
          <img src="${thumbUrl}" alt="Generated image" class="explore-thumb-image" loading="lazy"
            onload="this.closest('.explore-thumb').classList.remove('explore-thumb--loading')"
            onerror="if(this.dataset.fallback!='1'){this.dataset.fallback='1';this.src='${item.imageDataUrl}';}else{this.closest('.explore-thumb').classList.remove('explore-thumb--loading');}" />
          <button type="button" class="explore-heart ${item.favorite ? 'active' : ''}" data-fav-batch-id="${item.batchId}" data-fav-index="${item.index}" aria-label="Toggle favorite">${item.favorite ? '♥' : '♡'}</button>
          <button type="button" class="explore-diamond ${item.diamond ? 'active' : ''}" data-diamond-batch-id="${item.batchId}" data-diamond-index="${item.index}" aria-label="Toggle diamond">${item.diamond ? '◆' : '◇'}</button>
        </article>
      `;
    }

    function openImageInNewWindow(imageUrl) {
      const url = String(imageUrl || '').trim();
      if (!url) return;
      const opened = window.open('', '_blank');
      if (!opened) return;
      opened.document.open();
      opened.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Full size</title><style>html,body{margin:0;background:#000;height:100%}body{display:grid;place-items:center}img{max-width:100vw;max-height:100vh;object-fit:contain}</style></head><body><img alt="Full size image"></body></html>`);
      opened.document.close();
      const img = opened.document.querySelector('img');
      if (img) {
        img.src = url;
      }
    }

    async function openUpscaleWithImage(imageUrl) {
      const url = String(imageUrl || '').trim();
      if (!url) return;
      try {
        let dataUrl = url;
        if (!url.startsWith('data:image/') && !url.startsWith('/api/images/')) {
          const res = await fetch(url);
          const blob = await res.blob();
          dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(reader.error);
            reader.onload = () => resolve(String(reader.result));
            reader.readAsDataURL(blob);
          });
        }
        sessionStorage.setItem(UPSCALE_SOURCE_IMAGE_KEY, dataUrl);
        window.open('/nomad-studio/refine/upscale-model', '_blank');
      } catch {
        setStatus('Could not open Upscale with selected image.', true);
      }
    }

    async function openStudioDescribeWithImage(imageUrl) {
      const url = String(imageUrl || '').trim();
      if (!url) return;
      try {
        let source = url;
        if (!url.startsWith('data:image/') && !url.startsWith('/api/images/')) {
          const res = await fetch(url);
          const blob = await res.blob();
          source = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(reader.error);
            reader.onload = () => resolve(String(reader.result));
            reader.readAsDataURL(blob);
          });
        }
        sessionStorage.setItem(UPSCALE_SOURCE_IMAGE_KEY, source);
        window.open('/nomad-studio/create/describe-image', '_blank');
      } catch {
        setStatus('Could not open Describe with selected image.', true);
      }
    }

    function ensureViewerModal() {
      if (!viewerModalEl) return null;
      if (viewerElements) return viewerElements;

      // Move to document.body: .album-layout establishes its own stacking
      // context (position:relative + z-index:1, see nomad_studio.css) so a
      // descendant's z-index — however high — only ranks within that inner
      // context. Left nested, this modal (z-index:150) would render BEHIND
      // .nsc-topbar (z-index:2, a sibling context at the .nsc-page level)
      // regardless of its own z-index. Reparenting escapes that trap —
      // view_mode.js's apply() closes it when switching back to Flows mode,
      // since it's no longer inside #album-images-view to be hidden with it.
      if (viewerModalEl.parentElement !== document.body) {
        document.body.appendChild(viewerModalEl);
      }

      viewerModalEl.innerHTML = `
        <div class="gallery-viewer-backdrop" data-viewer-close="1"></div>
        <div class="gallery-viewer-shell" role="dialog" aria-modal="true" aria-label="Images Viewer">
          <button type="button" class="gallery-viewer-close" data-viewer-close="1" aria-label="Close"><i data-lucide="x" class="nav-icon" aria-hidden="true"></i></button>
          <button type="button" class="gallery-viewer-nav left" id="album-images-viewer-prev" aria-label="Previous image"><i data-lucide="arrow-left" class="nav-icon" aria-hidden="true"></i></button>
          <img id="album-images-viewer-image" class="gallery-viewer-image" alt="Generated image preview" />
          <button type="button" class="gallery-viewer-nav right" id="album-images-viewer-next" aria-label="Next image"><i data-lucide="arrow-right" class="nav-icon" aria-hidden="true"></i></button>
          <div class="gallery-viewer-meta">
            <div class="gallery-viewer-topline">
              <p class="gallery-viewer-caption" id="album-images-viewer-caption"></p>
              <p class="gallery-viewer-size" id="album-images-viewer-size"></p>
              <button type="button" class="btn" id="album-images-viewer-open-full">${t('album.viewer.fullSize', 'Full size')}</button>
              <button type="button" class="btn" id="album-images-viewer-copy-prompt">${t('album.viewer.copyPrompt', 'Copy Prompt')}</button>
              <button type="button" class="btn" id="album-images-viewer-upscale">${t('album.viewer.upscale', 'Upscale')}</button>
              <button type="button" class="btn" id="album-images-viewer-describe">${t('album.viewer.describe', 'Describe')}</button>
            </div>
            <p class="gallery-viewer-prompt" id="album-images-viewer-prompt"></p>
            <div class="gallery-viewer-info" id="album-images-viewer-info"></div>
          </div>
        </div>
      `;
      if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
      }

      const modal = viewerModalEl;
      const shellEl = modal.querySelector('.gallery-viewer-shell');
      const imageEl = modal.querySelector('#album-images-viewer-image');
      const captionEl = modal.querySelector('#album-images-viewer-caption');
      const sizeEl = modal.querySelector('#album-images-viewer-size');
      const promptEl = modal.querySelector('#album-images-viewer-prompt');
      const infoEl = modal.querySelector('#album-images-viewer-info');
      const prevBtn = modal.querySelector('#album-images-viewer-prev');
      const nextBtn = modal.querySelector('#album-images-viewer-next');
      const fullBtn = modal.querySelector('#album-images-viewer-open-full');
      const copyPromptBtn = modal.querySelector('#album-images-viewer-copy-prompt');
      const upscaleBtn = modal.querySelector('#album-images-viewer-upscale');
      const describeBtn = modal.querySelector('#album-images-viewer-describe');

      function closeViewer() {
        shellEl.classList.remove('image-focus-mode');
        modal.classList.remove('open');
        document.body.classList.remove('viewer-open');
      }

      function setViewerImage() {
        if (!viewerState.items.length) return;
        const safeIndex = Math.max(0, Math.min(viewerState.index, viewerState.items.length - 1));
        viewerState.index = safeIndex;
        const item = viewerState.items[safeIndex];
        imageEl.src = item.imageDataUrl;
        captionEl.textContent = t('album.viewer.imageOf', `Image ${safeIndex + 1} of ${viewerState.items.length}`, { current: safeIndex + 1, total: viewerState.items.length });
        sizeEl.textContent = (item.width && item.height) ? `${item.width} × ${item.height}` : '';
        promptEl.textContent = item.prompt
          ? t('album.viewer.promptLabel', `Prompt: ${item.prompt}`, { text: item.prompt })
          : t('album.viewer.promptNotAvailable', 'Prompt: not available');

        const infoRows = [];
        if (item.negative) infoRows.push(`<span class="viewer-info-label">${t('album.viewer.negative', 'Negative:')}</span> <span>${escapeHtml(item.negative)}</span>`);
        if (item.checkpoint) infoRows.push(`<span class="viewer-info-label">${t('album.viewer.checkpoint', 'Checkpoint:')}</span> <span>${escapeHtml(item.checkpoint)}</span>`);
        if (item.workflow) infoRows.push(`<span class="viewer-info-label">${t('album.viewer.workflow', 'Workflow:')}</span> <span>${escapeHtml(item.workflow)}</span>`);
        if (item.cfg || item.steps) {
          const parts = [];
          if (item.cfg) parts.push(`CFG ${escapeHtml(item.cfg)}`);
          if (item.steps) parts.push(`Steps ${escapeHtml(item.steps)}`);
          infoRows.push(`<span class="viewer-info-label">${t('album.viewer.params', 'Params:')}</span> <span>${parts.join(' | ')}</span>`);
        }
        if (item.createdAt) infoRows.push(`<span class="viewer-info-label">${t('album.viewer.date', 'Date:')}</span> <span>${new Date(item.createdAt).toLocaleString()}${item.generationSecs != null ? ` · ${item.generationSecs}s` : ''}</span>`);
        infoEl.innerHTML = infoRows.map((r) => `<p class="muted-note viewer-info-row">${r}</p>`).join('');
      }

      function showPrev() {
        if (!viewerState.items.length) return;
        viewerState.index = (viewerState.index - 1 + viewerState.items.length) % viewerState.items.length;
        setViewerImage();
      }

      function showNext() {
        if (!viewerState.items.length) return;
        viewerState.index = (viewerState.index + 1) % viewerState.items.length;
        setViewerImage();
      }

      modal.querySelectorAll('[data-viewer-close="1"]').forEach((node) => {
        node.addEventListener('click', closeViewer);
      });
      prevBtn.addEventListener('click', showPrev);
      nextBtn.addEventListener('click', showNext);
      imageEl.addEventListener('click', () => {
        shellEl.classList.toggle('image-focus-mode');
      });
      fullBtn.addEventListener('click', () => {
        if (!viewerState.items.length) return;
        const safeIndex = Math.max(0, Math.min(viewerState.index, viewerState.items.length - 1));
        openImageInNewWindow(viewerState.items[safeIndex].imageDataUrl);
      });
      copyPromptBtn.addEventListener('click', async () => {
        if (!viewerState.items.length) return;
        const safeIndex = Math.max(0, Math.min(viewerState.index, viewerState.items.length - 1));
        const item = viewerState.items[safeIndex];
        const prompt = String(item.prompt || '').trim();
        if (!prompt) return;

        const originalLabel = copyPromptBtn.textContent;
        try {
          await navigator.clipboard.writeText(prompt);
          copyPromptBtn.textContent = t('album.viewer.copied', 'Copied');
        } catch {
          copyPromptBtn.textContent = t('album.viewer.copyFailed', 'Copy failed');
        }
        window.setTimeout(() => {
          copyPromptBtn.textContent = originalLabel;
        }, 1200);
      });
      upscaleBtn.addEventListener('click', () => {
        if (!viewerState.items.length) return;
        const safeIndex = Math.max(0, Math.min(viewerState.index, viewerState.items.length - 1));
        openUpscaleWithImage(viewerState.items[safeIndex].imageDataUrl);
      });
      describeBtn.addEventListener('click', () => {
        if (!viewerState.items.length) return;
        const safeIndex = Math.max(0, Math.min(viewerState.index, viewerState.items.length - 1));
        openStudioDescribeWithImage(viewerState.items[safeIndex].imageDataUrl);
      });

      document.addEventListener('keydown', (event) => {
        if (!modal.classList.contains('open')) return;
        if (event.key === 'Escape') closeViewer();
        if (event.key === 'ArrowLeft') showPrev();
        if (event.key === 'ArrowRight') showNext();
      });

      viewerElements = {
        modal,
        setViewerImage,
      };
      return viewerElements;
    }

    function openViewer(items, startIndex) {
      if (!Array.isArray(items) || !items.length) return;
      const modal = ensureViewerModal();
      if (!modal) return;

      viewerState = {
        items,
        index: Number(startIndex) || 0,
      };

      modal.setViewerImage();
      modal.modal.querySelector('.gallery-viewer-shell')?.classList.remove('image-focus-mode');
      modal.modal.classList.add('open');
      document.body.classList.add('viewer-open');
    }

    function computeCurrentGroups() {
      const query = searchEl.value;
      const flat = flattenGalleryItems();
      const filteredByDiamond = filterItemsByDiamondVisibility(flat);
      const filteredByFavorites = filterItemsByFavoritesToggle(filteredByDiamond);
      const filtered = filterItems(filteredByFavorites, query);
      const groups = buildGroups(filtered, query).filter(([, values]) => Array.isArray(values) && values.length);
      return { flat, filtered, groups };
    }

    function hasMoreItems() {
      return renderLimit < totalFilteredCount || backendPagingState.hasMore;
    }

    function renderVisibleGroups() {
      groupsEl.innerHTML = '';

      if (!groupedCache.length || !totalFilteredCount) {
        updateSearchCount(0, 0);
        return;
      }

      let remaining = renderLimit;
      let shownCount = 0;

      groupedCache.forEach(([label, values]) => {
        if (remaining <= 0) return;
        const visible = values.slice(0, remaining);
        if (!visible.length) return;
        remaining -= visible.length;
        shownCount += visible.length;

        const section = document.createElement('section');
        section.className = 'explore-group';
        const h3 = document.createElement('h3');
        h3.className = 'explore-group-title';
        h3.innerHTML = `${label}<span>${visible.length}/${values.length}</span>`;
        const grid = document.createElement('div');
        grid.className = 'explore-thumb-grid';
        visible.forEach((item) => {
          grid.insertAdjacentHTML('beforeend', renderThumb(item));
        });
        section.appendChild(h3);
        section.appendChild(grid);
        groupsEl.appendChild(section);
      });

      if (hasMoreItems()) {
        loadSentinelEl.style.display = '';
        loadSentinelEl.textContent = t('album.viewer.scrollToLoadMore', 'Scroll to load more...');
        setStatus(`<strong>${shownCount}</strong> of <strong>${totalFilteredCount}</strong>`);
      } else {
        loadSentinelEl.style.display = 'none';
        setStatus(`<strong>${shownCount}</strong>`);
      }
      updateSearchCount(shownCount, totalFilteredCount);
    }

    function renderGroups(resetLimit = false) {
      const { flat, filtered, groups } = computeCurrentGroups();

      if (!flat.length) {
        groupedCache = [];
        totalFilteredCount = 0;
        groupsEl.innerHTML = '';
        emptyEl.style.display = '';
        loadSentinelEl.style.display = 'none';
        setStatus('No images available yet.');
        updateSearchCount(0, 0);
        return;
      }

      if (!filtered.length || !groups.length) {
        groupedCache = [];
        totalFilteredCount = 0;
        groupsEl.innerHTML = '';
        emptyEl.style.display = '';
        loadSentinelEl.style.display = 'none';
        setStatus('No results for your current filter.');
        updateSearchCount(0, 0);
        return;
      }

      emptyEl.style.display = 'none';
      groupedCache = groups;
      totalFilteredCount = filtered.length;
      if (resetLimit) {
        renderLimit = INITIAL_RENDER_LIMIT;
      }
      renderVisibleGroups();
    }

    async function toggleFavorite(batchId, index) {
      const gallery = Array.isArray(galleryCache) ? [...galleryCache] : [];
      const batch = gallery.find((entry) => String(entry.id) === String(batchId));
      if (!batch) return;

      const tiles = Array.isArray(batch.images) && batch.images.length
        ? [...batch.images]
        : (batch.imageDataUrl ? [{ imageDataUrl: batch.imageDataUrl }] : []);
      if (!tiles.length || !tiles[index]) return;

      const newFavorite = !tiles[index].favorite;
      tiles[index] = {
        ...tiles[index],
        favorite: newFavorite,
      };
      batch.images = tiles;

      if (gallerySource === 'server' && tiles[index].filename) {
        try {
          const api = window.openJourneyApi;
          if (api && typeof api.updateImageMeta === 'function') {
            await api.updateImageMeta(tiles[index].filename, { favorite: newFavorite });
          }
        } catch (_e) {
          // silently ignore — UI already reflects the toggle
        }
      }

      await persistGallery(gallery);
      renderGroups(false);
    }

    async function toggleDiamond(batchId, index) {
      const gallery = Array.isArray(galleryCache) ? [...galleryCache] : [];
      const batch = gallery.find((entry) => String(entry.id) === String(batchId));
      if (!batch) return;

      const tiles = Array.isArray(batch.images) && batch.images.length
        ? [...batch.images]
        : (batch.imageDataUrl ? [{ imageDataUrl: batch.imageDataUrl }] : []);
      if (!tiles.length || !tiles[index]) return;

      const newDiamond = !isDiamondMarked(tiles[index].diamond);
      tiles[index] = {
        ...tiles[index],
        diamond: newDiamond,
      };
      batch.images = tiles;

      if (gallerySource === 'server' && tiles[index].filename) {
        try {
          const api = window.openJourneyApi;
          if (api && typeof api.updateImageMeta === 'function') {
            await api.updateImageMeta(tiles[index].filename, { diamond: newDiamond });
          }
        } catch (_e) {
          // silently ignore — UI already reflects the toggle
        }
      }

      await persistGallery(gallery);
      renderGroups(false);
    }

    async function loadMore() {
      if (isLoadingMore || !hasMoreItems()) return;
      isLoadingMore = true;
      try {
        if (renderLimit < totalFilteredCount) {
          renderLimit = Math.min(totalFilteredCount, renderLimit + RENDER_STEP);
          renderVisibleGroups();
          return;
        }

        if (backendPagingState.hasMore) {
          const loaded = await fetchNextGalleryPage();
          if (loaded) {
            const { filtered, groups } = computeCurrentGroups();
            if (groups.length) {
              groupedCache = groups;
              totalFilteredCount = filtered.length;
            }
            renderLimit = Math.min(totalFilteredCount, renderLimit + RENDER_STEP);
            renderVisibleGroups();
          }
        }
      } finally {
        isLoadingMore = false;
      }
    }

    groupsEl.addEventListener('click', async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;

      const favBtn = target.closest('[data-fav-batch-id]');
      if (favBtn instanceof HTMLElement) {
        const batchId = favBtn.getAttribute('data-fav-batch-id');
        const indexText = favBtn.getAttribute('data-fav-index');
        if (batchId !== null && indexText !== null) {
          const index = Number(indexText);
          if (Number.isInteger(index) && index >= 0) {
            await toggleFavorite(batchId, index);
            return;
          }
        }
      }

      const diamondBtn = target.closest('[data-diamond-batch-id]');
      if (diamondBtn instanceof HTMLElement) {
        const diamondBatchId = diamondBtn.getAttribute('data-diamond-batch-id');
        const diamondIndexText = diamondBtn.getAttribute('data-diamond-index');
        if (diamondBatchId !== null && diamondIndexText !== null) {
          const index = Number(diamondIndexText);
          if (Number.isInteger(index) && index >= 0) {
            await toggleDiamond(diamondBatchId, index);
            return;
          }
        }
      }

      const cardEl = target.closest('[data-open-item-id]');
      if (!(cardEl instanceof HTMLElement)) return;
      if (target.closest('.explore-heart') || target.closest('.explore-diamond')) return;
      const itemId = cardEl.getAttribute('data-open-item-id');
      if (!itemId) return;

      const { filtered } = computeCurrentGroups();
      const startIndex = Array.isArray(filtered) ? filtered.findIndex((item) => item.id === itemId) : -1;

      if (Array.isArray(filtered) && filtered.length && startIndex >= 0) {
        openViewer(filtered, startIndex);
        return;
      }

      const imgEl = cardEl.querySelector('img');
      if (!imgEl || !imgEl.src) return;
      const fallbackItem = {
        id: itemId,
        imageDataUrl: imgEl.getAttribute('src') || imgEl.src,
        prompt: '',
        keywords: [],
        favorite: false,
        diamond: false,
        tags: [],
        width: null,
        height: null,
      };
      const allItems = flattenGalleryItems();
      const fullItem = allItems.find((it) => it.id === itemId);
      openViewer(fullItem ? [fullItem] : [fallbackItem], 0);
    });

    groupButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const value = btn.getAttribute('data-album-images-group');
        if (!value) return;
        groupMode = value;
        groupButtons.forEach((node) => node.classList.toggle('active', node === btn));
        renderGroups(true);
      });
    });

    favoritesToggleBtn.addEventListener('click', () => {
      favoritesOnly = !favoritesOnly;
      applyFavoritesToggleUi();
      renderGroups(true);
    });

    diamondToggleBtn.addEventListener('click', () => {
      showDiamondMarkedImages = !showDiamondMarkedImages;
      applyDiamondToggleUi();
      persistDiamondVisibility();
      renderGroups(true);
    });

    searchEl.addEventListener('input', () => {
      const hasQuery = String(searchEl.value || '').trim().length > 0;
      if (!hasQuery) {
        searchHydrationToken += 1;
        isSearchHydrationLoading = false;
        updateSearchLoadingUi();
      }
      renderGroups(true);
      if (hasQuery) {
        void ensureSearchScopeLoaded();
      }
    });

    zoomInBtn.addEventListener('click', () => {
      if (explorePageEl.hidden) return; // Flows mode's own click handler owns this press instead
      thumbMinSize = Math.min(THUMB_MAX, thumbMinSize + THUMB_STEP);
      applyThumbSize();
      persistThumbSize();
    });

    zoomOutBtn.addEventListener('click', () => {
      if (explorePageEl.hidden) return;
      thumbMinSize = Math.max(THUMB_MIN, thumbMinSize - THUMB_STEP);
      applyThumbSize();
      persistThumbSize();
    });

    if (zoomResetBtn) {
      zoomResetBtn.addEventListener('click', () => {
        if (explorePageEl.hidden) return;
        thumbMinSize = THUMB_DEFAULT;
        applyThumbSize();
        persistThumbSize();
      });
    }

    const scrollTarget = usesContainerScroll() ? explorePageEl : window;
    let lastScrollTop = 0;

    if (typeof IntersectionObserver !== 'undefined') {
      const observerRoot = usesContainerScroll() ? explorePageEl : null;
      const observer = new IntersectionObserver((entries) => {
        const visible = entries.some((entry) => entry.isIntersecting);
        if (!visible) return;
        const currentScroll = scrollTarget === window
          ? (window.scrollY || document.documentElement.scrollTop)
          : scrollTarget.scrollTop;
        const scrollingDown = currentScroll > lastScrollTop;
        lastScrollTop = currentScroll;
        if (scrollingDown) {
          loadMore();
        }
      }, { root: observerRoot, rootMargin: '300px 0px', threshold: 0.01 });
      observer.observe(loadSentinelEl);
    }

    scrollTarget.addEventListener('scroll', () => {
      if (!hasMoreItems()) return;
      const currentScroll = scrollTarget === window
        ? (window.scrollY || document.documentElement.scrollTop)
        : scrollTarget.scrollTop;
      const scrollingDown = currentScroll > lastScrollTop;
      lastScrollTop = currentScroll;
      if (!scrollingDown) return;
      let nearBottom = false;
      if (scrollTarget === window) {
        nearBottom = window.innerHeight + window.scrollY >= document.body.offsetHeight - 280;
      } else {
        nearBottom = scrollTarget.scrollTop + scrollTarget.clientHeight >= scrollTarget.scrollHeight - 280;
      }
      if (nearBottom) loadMore();
    });

    restoreThumbSize();
    restoreDiamondVisibility();
    applyFavoritesToggleUi();
    applyDiamondToggleUi();
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
    await initializeGalleryStorage();
    renderGroups(true);
    void ensureSearchScopeLoaded();

    // Exposed so view_mode.js can resync the shared count badge and the
    // shared zoom buttons' disabled state right when this mode becomes the
    // active one again (its own data hasn't changed, but the badge/buttons
    // may currently reflect whatever Flows mode last wrote to them).
    _refreshRef = () => renderVisibleGroups();
    _syncZoomRef = () => applyThumbSize();
  }

  return {
    init,
    refresh: () => { if (_refreshRef) _refreshRef(); },
    syncZoom: () => { if (_syncZoomRef) _syncZoomRef(); },
  };
})();
