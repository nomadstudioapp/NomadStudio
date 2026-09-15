/* Video caption overlay — dev tool for recording tutorial videos.
   The overlay itself is click-through (pointer-events: none) so the
   presenter can still interact with the real UI underneath while it's
   showing. Text + visibility persist in localStorage so switching pages
   mid-recording doesn't lose the caption. Toggle with the small tab
   (bottom-right) or Ctrl+Shift+T. */
(function () {
  'use strict';

  var STORE_KEY = 'ns-video-caption-v1';

  var overlay   = document.getElementById('ns-caption-overlay');
  var textEl    = document.getElementById('ns-caption-text');
  var editor    = document.getElementById('ns-caption-editor');
  var input     = document.getElementById('ns-caption-editor-input');
  var visibleCb = document.getElementById('ns-caption-editor-visible');
  var tab       = document.getElementById('ns-caption-tab');
  if (!overlay || !tab) return;

  function load() {
    try {
      var raw = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
      return { text: raw.text || '', visible: !!raw.visible };
    } catch (_) {
      return { text: '', visible: false };
    }
  }

  function save(state) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) {}
  }

  function render(state) {
    textEl.textContent = state.text;
    overlay.hidden = !state.visible || !state.text;
  }

  var state = load();
  input.value = state.text;
  visibleCb.checked = state.visible;
  render(state);

  function update(patch) {
    state = Object.assign({}, state, patch);
    save(state);
    render(state);
  }

  input.addEventListener('input', function () { update({ text: input.value }); });
  visibleCb.addEventListener('change', function () { update({ visible: visibleCb.checked }); });

  function toggleEditor(force) {
    var show = typeof force === 'boolean' ? force : editor.hidden;
    editor.hidden = !show;
    if (show) input.focus();
  }

  tab.addEventListener('click', function () { toggleEditor(); });

  document.addEventListener('click', function (e) {
    if (editor.hidden) return;
    if (editor.contains(e.target) || tab.contains(e.target)) return;
    toggleEditor(false);
  });
})();
