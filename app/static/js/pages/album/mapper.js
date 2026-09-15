(function attachAlbumMapperHelpers() {
  function resolveWorkflowDisplayName(meta) {
    const workflowName = String((meta && meta.workflow_name) || '').trim();
    if (workflowName) return workflowName;
    const workflowRaw = String((meta && meta.workflow) || '').trim();
    // Avoid showing internal import ids (e.g. imp-xxxx) as workflow names.
    if (/^imp-[a-z0-9]+$/i.test(workflowRaw)) return '';
    return workflowRaw;
  }

  function toGalleryBatch(item, api) {
    const meta = (item && item.meta) || {};
    const sidecar = (item && item.sidecar) || {};
    const workflowDisplayName = resolveWorkflowDisplayName(meta);

    return {
      id: `server-${item.filename}`,
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
    };
  }

  function appendUniqueBatches(existing, incoming, api) {
    const out = Array.isArray(existing) ? [...existing] : [];
    const seen = new Set(out.map((batch) => String(batch && batch.id || '')));
    const sourceItems = Array.isArray(incoming) ? incoming : [];

    sourceItems.forEach((item) => {
      if (!item || !item.filename) return;
      const batchId = `server-${item.filename}`;
      if (seen.has(batchId)) return;
      seen.add(batchId);
      out.push(toGalleryBatch(item, api));
    });

    return out;
  }

  window.openJourneyAlbumMapper = {
    appendUniqueBatches,
  };
})();
