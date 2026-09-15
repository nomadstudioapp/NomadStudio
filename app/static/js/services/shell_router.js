(function shellRouterService() {
  const mainWrap = document.querySelector('.main-wrap');
  const sidebar = document.querySelector('.sidebar');

  if (!mainWrap || !sidebar) {
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

  function updateSidebarActiveState(pathname) {
    const normalizedCurrent = normalizePathname(pathname);
    const links = Array.from(sidebar.querySelectorAll('a.nav-item[href]'));
    links.forEach((link) => {
      const href = link.getAttribute('href');
      if (!href || href === '#') {
        link.classList.remove('active');
        link.removeAttribute('aria-current');
        return;
      }
      try {
        const target = new URL(href, window.location.href);
        const isActive = normalizePathname(target.pathname) === normalizedCurrent;
        link.classList.toggle('active', isActive);
        if (isActive) {
          link.setAttribute('aria-current', 'page');
        } else {
          link.removeAttribute('aria-current');
        }
      } catch {
        link.classList.remove('active');
        link.removeAttribute('aria-current');
      }
    });
  }

  function applyIncomingDocument(doc, pathnameForActiveState) {
    const incomingMain = doc.querySelector('.main-wrap');
    if (!incomingMain) {
      throw new Error('Incoming page has no main container');
    }

    mainWrap.innerHTML = incomingMain.innerHTML;
    document.title = doc.title || document.title;

    const incomingBodyClass = (doc.body && typeof doc.body.className === 'string') ? doc.body.className : '';
    document.body.className = incomingBodyClass;

    updateSidebarActiveState(pathnameForActiveState || window.location.pathname);
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
      const targetUrl = new URL(url, window.location.href);

      const scopeId = `page-${Date.now()}`;
      runtime.activateScope(scopeId);
      applyIncomingDocument(doc, targetUrl.pathname);

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

  sidebar.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const anchor = target.closest('a.nav-item[href]');
    if (!anchor) return;

    const href = anchor.getAttribute('href');
    if (!href || href === '#') return;
    if (!sameOrigin(href)) return;
    if (isBypassClick(event, anchor)) return;

    const targetUrl = new URL(href, window.location.href);
    if (targetUrl.pathname === window.location.pathname && targetUrl.search === window.location.search) {
      event.preventDefault();
      return;
    }

    event.preventDefault();
    void navigateTo(targetUrl.toString());
  });

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
