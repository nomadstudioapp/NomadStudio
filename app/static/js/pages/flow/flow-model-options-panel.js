'use strict';
// LLM ("Assist" model) picker rendered into the shared options panel.
// Reuses the pure data helpers still in flow-model-picker.js (_pickerSettings,
// _loadModelScores, _sortModelsByScore, _appendModelBadges) but builds its
// own DOM here, since the old model-picker modal (and its DOM-specific
// render/apply logic) was removed once nothing else used it.
//
// No separate "Apply" step — clicking a model saves immediately; whichever one
// you clicked last is the one that stays.
//
// Favorites reuse the same `lmStudioFavoriteModels` list the Models > Chat
// settings page already reads/writes (see static/js/pages/models_chat.js) —
// right-click a model here to add/remove it; favorites sort first and get a
// star to the left of their score badge.

async function _saveModelSettings(model) {
  var reqBody = { lmStudioPromptModel: model };
  try {
    var res = await fetch('/api/models/chat/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody),
    });
    var data = await res.json();
    _pickerSettings = data.settings || _pickerSettings;
    // Repaint the chips that name the writing model. Updating _pickerSettings
    // alone left every one of them showing the previous model until the step
    // re-rendered, so picking a new model looked like it had not applied — the
    // call really did use the new one, the label just lied about it.
    //
    // _saveVisionModelSetting in flow-model-picker.js has the same loop for the
    // vision chips, and for a long time it did nothing: it selects
    // .ncf-vision-model-btn, which only makeVisionModelBtn() sets and nothing
    // calls, while the three real chips built their own buttons without it.
    // They carry the class now, so both sides actually repaint.
    if (typeof _updateVisionHintLabel === 'function') {
      document.querySelectorAll('.ncf-llm-model-btn').forEach(function (b) {
        _updateVisionHintLabel(b, b.querySelector('.ncf-model-icon-name'), model);
      });
    }
  } catch (err) {
    console.error('[FlowEngine] saveModelSettings:', err);
    showErrorToast('Could not save model settings');
  }
}

async function _toggleModelFavorite(m) {
  var favs = (_pickerSettings.lmStudioFavoriteModels || []).slice();
  var idx = favs.indexOf(m);
  if (idx >= 0) favs.splice(idx, 1); else favs.unshift(m);
  try {
    var res = await fetch('/api/models/chat/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lmStudioFavoriteModels: favs }),
    });
    var data = await res.json();
    _pickerSettings = data.settings || _pickerSettings;
  } catch (err) {
    console.error('[FlowEngine] toggleModelFavorite:', err);
    showErrorToast('Could not update favorites');
  }
}

// ── Tiny right-click menu (currently just the one "favorite" toggle) ───────
var _modelCtxMenuEl = null;
function _showModelContextMenu(x, y, label, onPick) {
  _hideModelContextMenu();
  _modelCtxMenuEl = document.createElement('div');
  _modelCtxMenuEl.className = 'ncf-model-ctx-menu nsc-options-exempt';
  var item = document.createElement('button');
  item.type = 'button';
  item.className = 'ncf-model-ctx-item';
  item.textContent = label;
  item.addEventListener('click', function () {
    onPick();
    _hideModelContextMenu();
  });
  _modelCtxMenuEl.appendChild(item);
  document.body.appendChild(_modelCtxMenuEl);
  var rect = _modelCtxMenuEl.getBoundingClientRect();
  _modelCtxMenuEl.style.left = Math.min(x, window.innerWidth - rect.width - 8) + 'px';
  _modelCtxMenuEl.style.top  = Math.min(y, window.innerHeight - rect.height - 8) + 'px';
}
function _hideModelContextMenu() {
  if (_modelCtxMenuEl) { _modelCtxMenuEl.remove(); _modelCtxMenuEl = null; }
}
document.addEventListener('mousedown', function (e) {
  if (_modelCtxMenuEl && !_modelCtxMenuEl.contains(e.target)) _hideModelContextMenu();
});
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') _hideModelContextMenu(); });

async function openModelOptionsPanel() {
  try {
    var res  = await fetch('/api/models/chat/settings');
    var data = await res.json();
    _pickerSettings = data.settings || _pickerSettings;
  } catch (e) { /* fall through with whatever _pickerSettings already had */ }

  openOptionsPanel('Model', function (body) {
    // This panel used to carry a "Context size" section in its advanced block —
    // 4K/8K/16K/32K presets plus a free-form number. It is gone along with the
    // Assist panel's slider: the window is derived from the text being sent
    // (_auto_context_size in workflow_service.py), so there is no number left
    // for anyone to pick, and picking one only ever risked truncating the
    // prompt. The panel is the model list now, nothing else.
    body.innerHTML = '<div class="nse-model-list" id="ncf-model-panel-list"></div>';

    var listEl     = body.querySelector('#ncf-model-panel-list');
    var panelModel = (_pickerSettings.lmStudioPromptModel || _pickerSettings.lmStudioModel) || '';

    var models = _pickerSettings.lmStudioModels || [];

    // Model list is a snapshot saved server-side the last time someone hit
    // "Load models" on the Settings > Models > Chat page — a model you just
    // downloaded/loaded directly in LM Studio won't show up here until that
    // snapshot is refreshed. Small circular button next to the panel title
    // re-runs the same scan without leaving the flow page.
    var _refreshIconHtml =
      '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M3 12a9 9 0 0115.4-6.4M21 12a9 9 0 01-15.4 6.4"/><path d="M3 3v6h6"/><path d="M21 21v-6h-6"/></svg>';
    setOptionsPanelAction(_refreshIconHtml, function () {
      var actionEl = document.getElementById('ncf-options-panel-action');
      if (actionEl && actionEl.classList.contains('is-spinning')) return;
      if (actionEl) actionEl.classList.add('is-spinning');
      fetch('/api/models/chat/models/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lmStudioApiUrl: _pickerSettings.lmStudioApiUrl || '' }),
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error((res.data && res.data.error) || 'Failed to refresh models');
          _pickerSettings = res.data.settings || _pickerSettings;
          models = _pickerSettings.lmStudioModels || [];
          renderModelList();
          if (typeof showToast === 'function') showToast('Model list refreshed (' + models.length + ')', 'info');
        })
        .catch(function (err) {
          if (typeof showErrorToast === 'function') showErrorToast(err.message || 'Could not refresh models');
        })
        .finally(function () {
          var el = document.getElementById('ncf-options-panel-action');
          if (el) el.classList.remove('is-spinning');
        });
    }, { icon: true, label: 'Refresh model list from LM Studio' });

    function renderModelList() {
      if (!models.length) {
        listEl.innerHTML = '<p class="nse-model-empty">No models found — is LM Studio running?</p>';
        return;
      }
      _loadModelScores().then(function (scoreData) {
        listEl.innerHTML = '';
        var favs = _pickerSettings.lmStudioFavoriteModels || [];
        var ordered = _sortModelsByScore(models, scoreData).sort(function (a, b) {
          var fa = favs.indexOf(a) >= 0 ? 1 : 0;
          var fb = favs.indexOf(b) >= 0 ? 1 : 0;
          return fb - fa; // favorites first, stable within each group
        });
        ordered.forEach(function (m) {
          var isFav = favs.indexOf(m) >= 0;
          var btn = document.createElement('button');
          btn.className = 'nse-model-item' + (m === panelModel ? ' is-selected' : '');
          btn.type = 'button';
          btn.setAttribute('role', 'option');
          btn.setAttribute('aria-selected', m === panelModel ? 'true' : 'false');
          btn.dataset.model = m;
          var name = document.createElement('span'); name.className = 'nse-model-name';
          name.textContent = m.split('/').pop().split('\\').pop() || m;
          name.title = m;
          btn.appendChild(name);
          if (isFav) {
            var star = document.createElement('span');
            star.className = 'ncf-model-fav-star';
            star.textContent = '★';
            star.setAttribute('aria-label', 'Favorite');
            btn.appendChild(star);
          }
          _appendModelBadges(btn, m, scoreData);
          btn.addEventListener('click', function () {
            panelModel = m;
            listEl.querySelectorAll('.nse-model-item').forEach(function (el) {
              var sel = el.dataset.model === m;
              el.classList.toggle('is-selected', sel);
              el.setAttribute('aria-selected', sel ? 'true' : 'false');
            });
            _saveModelSettings(panelModel);
          });
          btn.addEventListener('contextmenu', function (e) {
            e.preventDefault();
            var nowFav = (_pickerSettings.lmStudioFavoriteModels || []).indexOf(m) >= 0;
            _showModelContextMenu(e.clientX, e.clientY, nowFav ? 'Remove from favorites' : 'Add to favorite', function () {
              _toggleModelFavorite(m).then(renderModelList);
            });
          });
          listEl.appendChild(btn);
        });
      });
    }
    renderModelList();
  }, { wide: true, flexBody: true });
}
