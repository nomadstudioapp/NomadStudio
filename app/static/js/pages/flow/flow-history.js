'use strict';
// Prompt history: getPromptHistory, pushPromptHistory, openHistoryModal (renders into the shared options panel)

function getPromptHistory(stepId) {
  try { return JSON.parse(localStorage.getItem(HISTORY_PFX + stepId) || '[]'); } catch (_) { return []; }
}

// Favorites — a separate, uncapped list from the rotating history above (see
// HISTORY_MAX), so pinning an entry keeps it around after it would otherwise
// have aged out. Own key so favoriting doesn't disturb history's own order.
var HISTORY_FAV_MAX = 100;
function _favKey(stepId) { return HISTORY_PFX + 'fav-' + stepId; }
function getFavoritePrompts(stepId) {
  try { return JSON.parse(localStorage.getItem(_favKey(stepId)) || '[]'); } catch (_) { return []; }
}
function isFavoritePrompt(stepId, text) {
  return getFavoritePrompts(stepId).indexOf(text) !== -1;
}
function toggleFavoritePrompt(stepId, text) {
  var t = (text || '').trim();
  if (!t) return;
  var favs = getFavoritePrompts(stepId);
  var idx = favs.indexOf(t);
  if (idx >= 0) {
    favs.splice(idx, 1);
  } else {
    favs.unshift(t);
    if (favs.length > HISTORY_FAV_MAX) favs.length = HISTORY_FAV_MAX;
  }
  try { localStorage.setItem(_favKey(stepId), JSON.stringify(favs)); } catch (_) { /* ignore */ }
}
function pushPromptHistory(stepId, text) {
  // Some steps (e.g. story-bar batch generation) can momentarily hold an
  // array of prompts instead of a single string — push each individually.
  if (Array.isArray(text)) {
    text.forEach(function (t) { pushPromptHistory(stepId, t); });
    return;
  }
  var t = (text || '').trim();
  if (!t) return;
  var hist = getPromptHistory(stepId);
  hist = hist.filter(function (h) { return h !== t; });
  hist.unshift(t);
  if (hist.length > HISTORY_MAX) hist.length = HISTORY_MAX;
  try {
    localStorage.setItem(HISTORY_PFX + stepId, JSON.stringify(hist));
  } catch (_) {
    // localStorage quota exceeded — try with just the latest entry
    try { localStorage.setItem(HISTORY_PFX + stepId, JSON.stringify([t])); } catch (_2) { /* give up */ }
  }
}

// Rendered into the shared options panel (flow-options-panel.js) instead of
// its own modal — same pattern as Aspect ratio / Assist options / Model.
function openHistoryModal(stepId, onSelect) {
  openOptionsPanel(tF('History'), function (body) {
    _renderHistoryList(stepId, body, onSelect);
  });
}

var _HISTORY_STAR_SVG_OUTLINE =
  '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M12 3.5l2.7 5.7 6.1.8-4.5 4.4 1.1 6.2L12 17.6l-5.4 2.9 1.1-6.2-4.5-4.4 6.1-.8z"/>' +
  '</svg>';
var _HISTORY_STAR_SVG_FILLED =
  '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M12 3.5l2.7 5.7 6.1.8-4.5 4.4 1.1 6.2L12 17.6l-5.4 2.9 1.1-6.2-4.5-4.4 6.1-.8z"/>' +
  '</svg>';

function _historyRowEl(stepId, text, onSelect, isFav, onToggleFav) {
  var row = document.createElement('div');
  row.className = 'nse-model-item ncf-history-row';

  var textBtn = document.createElement('button');
  textBtn.type = 'button';
  textBtn.className = 'ncf-history-item';
  textBtn.textContent = text.length > 100 ? text.slice(0, 100) + '…' : text;
  textBtn.title = text;
  textBtn.addEventListener('click', function () {
    if (onSelect) onSelect(text);
    closeOptionsPanel();
  });

  var starBtn = document.createElement('button');
  starBtn.type = 'button';
  starBtn.className = 'ncf-history-star' + (isFav ? ' is-favorite' : '');
  starBtn.setAttribute('aria-label', tF(isFav ? 'Remove from favorites' : 'Add to favorites'));
  starBtn.title = tF(isFav ? 'Remove from favorites' : 'Add to favorites');
  starBtn.innerHTML = isFav ? _HISTORY_STAR_SVG_FILLED : _HISTORY_STAR_SVG_OUTLINE;
  starBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    onToggleFav(text);
  });

  row.appendChild(textBtn);
  row.appendChild(starBtn);
  return row;
}

function _renderHistoryList(stepId, body, onSelect) {
  var hist = getPromptHistory(stepId);
  var favs = getFavoritePrompts(stepId);
  if (!hist.length && !favs.length) {
    body.innerHTML = '<p class="nse-model-empty">' + escHtml(tF('No history yet.')) + '</p>';
    setOptionsPanelAction(null);
    return;
  }

  function rerender() { _renderHistoryList(stepId, body, onSelect); }
  function toggleFav(text) { toggleFavoritePrompt(stepId, text); rerender(); }

  body.innerHTML = '';

  if (favs.length) {
    var favLabel = document.createElement('p');
    favLabel.className = 'nse-modal-section-label';
    favLabel.textContent = tF('Favorites');
    body.appendChild(favLabel);
    var favListEl = document.createElement('div');
    favListEl.className = 'nse-model-list';
    favs.forEach(function (text) {
      favListEl.appendChild(_historyRowEl(stepId, text, onSelect, true, toggleFav));
    });
    body.appendChild(favListEl);
  }

  if (hist.length) {
    if (favs.length) {
      var histLabel = document.createElement('p');
      histLabel.className = 'nse-modal-section-label';
      histLabel.textContent = tF('History');
      body.appendChild(histLabel);
    }
    var listEl = document.createElement('div');
    listEl.className = 'nse-model-list';
    hist.forEach(function (text) {
      listEl.appendChild(_historyRowEl(stepId, text, onSelect, favs.indexOf(text) !== -1, toggleFav));
    });
    body.appendChild(listEl);
  }

  setOptionsPanelAction('Clear', function () {
    try { localStorage.removeItem(HISTORY_PFX + stepId); } catch (_) {}
    rerender();
  });
}

// ── Mode toggle ────────────────────────────────────────────────────────────
var modeBtns = document.querySelectorAll('[data-ncf-mode]');
