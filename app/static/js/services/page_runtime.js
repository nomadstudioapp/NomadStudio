(function pageRuntimeService() {
  const scopes = new Map();
  let activeScopeId = null;
  let patched = false;

  const native = {
    setInterval: null,
    clearInterval: null,
    setTimeout: null,
    clearTimeout: null,
    windowAddEventListener: null,
    windowRemoveEventListener: null,
    documentAddEventListener: null,
    documentRemoveEventListener: null,
  };

  function getScope(id) {
    if (!id) return null;
    return scopes.get(id) || null;
  }

  function ensureScope(id) {
    const existing = getScope(id);
    if (existing) return existing;
    const created = {
      id,
      intervals: new Set(),
      timeouts: new Set(),
      listeners: [],
      scripts: [],
    };
    scopes.set(id, created);
    return created;
  }

  function patchGlobals() {
    if (patched) return;
    patched = true;

    native.setInterval = window.setInterval.bind(window);
    native.clearInterval = window.clearInterval.bind(window);
    native.setTimeout = window.setTimeout.bind(window);
    native.clearTimeout = window.clearTimeout.bind(window);

    native.windowAddEventListener = window.addEventListener.bind(window);
    native.windowRemoveEventListener = window.removeEventListener.bind(window);
    native.documentAddEventListener = document.addEventListener.bind(document);
    native.documentRemoveEventListener = document.removeEventListener.bind(document);

    window.setInterval = function patchedSetInterval(callback, delay, ...args) {
      const id = native.setInterval(callback, delay, ...args);
      const scope = getScope(activeScopeId);
      if (scope) {
        scope.intervals.add(id);
      }
      return id;
    };

    window.clearInterval = function patchedClearInterval(id) {
      const scope = getScope(activeScopeId);
      if (scope) {
        scope.intervals.delete(id);
      }
      return native.clearInterval(id);
    };

    window.setTimeout = function patchedSetTimeout(callback, delay, ...args) {
      const id = native.setTimeout(callback, delay, ...args);
      const scope = getScope(activeScopeId);
      if (scope) {
        scope.timeouts.add(id);
      }
      return id;
    };

    window.clearTimeout = function patchedClearTimeout(id) {
      const scope = getScope(activeScopeId);
      if (scope) {
        scope.timeouts.delete(id);
      }
      return native.clearTimeout(id);
    };

    window.addEventListener = function patchedWindowAddEventListener(type, listener, options) {
      const scope = getScope(activeScopeId);
      if (scope && listener) {
        scope.listeners.push({ target: window, type, listener, options });
      }
      return native.windowAddEventListener(type, listener, options);
    };

    window.removeEventListener = function patchedWindowRemoveEventListener(type, listener, options) {
      const scope = getScope(activeScopeId);
      if (scope && listener) {
        scope.listeners = scope.listeners.filter((item) => !(item.target === window && item.type === type && item.listener === listener));
      }
      return native.windowRemoveEventListener(type, listener, options);
    };

    document.addEventListener = function patchedDocumentAddEventListener(type, listener, options) {
      const scope = getScope(activeScopeId);
      if (scope && listener) {
        scope.listeners.push({ target: document, type, listener, options });
      }
      return native.documentAddEventListener(type, listener, options);
    };

    document.removeEventListener = function patchedDocumentRemoveEventListener(type, listener, options) {
      const scope = getScope(activeScopeId);
      if (scope && listener) {
        scope.listeners = scope.listeners.filter((item) => !(item.target === document && item.type === type && item.listener === listener));
      }
      return native.documentRemoveEventListener(type, listener, options);
    };
  }

  function cleanupScope(scopeId) {
    const scope = getScope(scopeId);
    if (!scope) return;

    scope.intervals.forEach((id) => {
      try {
        native.clearInterval(id);
      } catch {
        // ignore
      }
    });
    scope.timeouts.forEach((id) => {
      try {
        native.clearTimeout(id);
      } catch {
        // ignore
      }
    });

    scope.listeners.forEach((item) => {
      try {
        item.target.removeEventListener(item.type, item.listener, item.options);
      } catch {
        // ignore
      }
    });

    scope.scripts.forEach((scriptEl) => {
      try {
        scriptEl.remove();
      } catch {
        // ignore
      }
    });

    scopes.delete(scopeId);
  }

  function activateScope(scopeId) {
    patchGlobals();
    if (activeScopeId && activeScopeId !== scopeId) {
      cleanupScope(activeScopeId);
    }
    activeScopeId = scopeId;
    ensureScope(scopeId);
  }

  function loadExternalScript(src, type) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      if (type) script.type = type;
      script.async = false;
      script.dataset.pageRuntime = '1';
      script.onload = () => resolve(script);
      script.onerror = () => reject(new Error(`Failed loading script: ${src}`));
      document.body.appendChild(script);
    });
  }

  async function runPageScripts(sources, scopeId) {
    const scope = ensureScope(scopeId);
    for (const item of sources) {
      const src = typeof item === 'string' ? item : item.src;
      const type = typeof item === 'string' ? '' : (item.type || '');
      const scriptEl = await loadExternalScript(src, type);
      scope.scripts.push(scriptEl);
    }
  }

  window.openJourneyPageRuntime = {
    activateScope,
    cleanupScope,
    runPageScripts,
    getActiveScopeId() {
      return activeScopeId;
    },
  };
})();
