(function shellRouterService() {
  const mainWrap = document.querySelector('.main-wrap');

  if (!mainWrap) {
    return;
  }

  const runtime = window.openJourneyPageRuntime;
  if (!runtime) {
    return;
  }

  runtime.activateScope(`initial-${window.location.pathname}`);

  let navigationInFlight = false;

  function sameOrigin(url) {
    try {
      const target = new URL(url, window.location.href);
      return target.origin === window.location.origin;
    } catch {
      return false;
    }
  }

  function isBypassClick(event, anchor) {
    if (!anchor) return true;
    if (anchor.target && anchor.target !== '_self') return true;
    if (anchor.hasAttribute('download')) return true;
    if (event.defaultPrevented) return true;
    if (event.button !== 0) return true;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return true;
    return false;
  }

  function collectPageScriptSources(doc) {
    const scripts = Array.from(doc.querySelectorAll('script[src]:not([data-shell-script])'));
    return scripts
      .map((el) => ({
        src: new URL(el.getAttribute('src'), window.location.href).toString(),
        type: el.getAttribute('type') || '',
      }))
      .filter((item) => Boolean(item.src));
  }

  function normalizePathname(pathname) {
    if (!pathname) return '/';
    if (pathname.length > 1 && pathname.endsWith('/')) {
      return pathname.slice(0, -1);
    }
    return pathname;
  }

  function applyIncomingDocument(doc) {
    const incomingMain = doc.querySelector('.main-wrap');
    if (!incomingMain) {
      throw new Error(tF('Incoming page has no main container'));
    }

    mainWrap.innerHTML = incomingMain.innerHTML;
    document.title = doc.title || document.title;

    const incomingBodyClass = (doc.body && typeof doc.body.className === 'string') ? doc.body.className : '';
    document.body.className = incomingBodyClass;
  }

  async function navigateTo(url, options = {}) {
    if (navigationInFlight) return;
    navigationInFlight = true;

    try {
      try {
        window.dispatchEvent(new CustomEvent('oj:shell:navigate-start', {
          detail: {
            from: window.location.href,
            to: url,
          },
        }));
      } catch {
        // Best effort only.
      }

      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'X-Requested-With': 'OpenJourneyShellRouter',
        },
        credentials: 'same-origin',
      });

      if (!response.ok) {
        window.location.href = url;
        return;
      }

      const html = await response.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const scriptSources = collectPageScriptSources(doc);

      const scopeId = `page-${Date.now()}`;
      runtime.activateScope(scopeId);
      applyIncomingDocument(doc);

      await runtime.runPageScripts(scriptSources, scopeId);

      if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
      }

      if (!options.fromPopState) {
        history.pushState({ url }, '', url);
      }

      try {
        window.dispatchEvent(new CustomEvent('oj:shell:navigate-end', {
          detail: {
            to: url,
          },
        }));
      } catch {
        // Best effort only.
      }
    } catch {
      window.location.href = url;
    } finally {
      navigationInFlight = false;
    }
  }

  // Nomad Studio's own sub-views (/nomad-studio(/create|refine|mix)) are
  // pure client-side view toggles — nomad_studio.js pushes those history
  // entries itself and has its own popstate listener to swap the visible
  // view instantly. If we also AJAX-refetch here, the resulting DOM swap
  // re-triggers nomad_studio.js's own <script>, whose `__nomadStudioLoaded`
  // guard then skips re-binding click handlers on the fresh markup — every
  // card silently degrades to its bare `href="#"` with nothing wired up.
  const NOMAD_STUDIO_SUBVIEW_RE = /^\/nomad-studio(\/(create|refine|mix))?$/;

  window.addEventListener('popstate', () => {
    if (window.__nomadStudioLoaded && NOMAD_STUDIO_SUBVIEW_RE.test(window.location.pathname)) {
      return;
    }
    void navigateTo(window.location.href, { fromPopState: true });
  });
})();
