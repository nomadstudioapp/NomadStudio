(function attachAlbumPagingHelpers() {
  async function fetchPage(api, options = {}) {
    if (!api || typeof api.listImages !== 'function') {
      return {
        images: [],
        paging: { hasMore: false, nextCursor: null },
      };
    }

    const limitValue = Number(options.limit);
    const limit = Number.isFinite(limitValue) && limitValue > 0
      ? Math.max(1, Math.min(1000, Math.trunc(limitValue)))
      : 200;

    const request = { limit };
    const cursor = String(options.cursor || '').trim();
    const snapshot = String(options.snapshot || '').trim();
    if (cursor) {
      request.cursor = cursor;
    }
    if (snapshot) {
      request.snapshot = snapshot;
    }

    const response = await api.listImages(request);
    const images = Array.isArray(response && response.images) ? response.images : [];
    const paging = (response && response.paging && typeof response.paging === 'object')
      ? response.paging
      : { hasMore: false, nextCursor: null };

    return {
      images,
      paging: {
        hasMore: !!paging.hasMore,
        nextCursor: paging.nextCursor ? String(paging.nextCursor) : null,
        snapshotCursor: paging.snapshotCursor ? String(paging.snapshotCursor) : null,
        total: typeof paging.total === 'number' ? paging.total : null,
      },
    };
  }

  window.openJourneyAlbumPaging = {
    fetchPage,
  };
})();
