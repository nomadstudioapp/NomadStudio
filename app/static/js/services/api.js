// Shared "reasoning-only" retry flow for LM Studio chat endpoints: a model
// can spend its whole token budget on chain-of-thought and return no content
// at all (see issue #1 — the model ignores /no_think and never gets to the
// real answer). The affected endpoints detect this server-side and respond
// with {emptyWithReasoning:true, currentMaxTokens} instead of a plain error,
// so the UI can offer a real fix (more budget) instead of a dead end.
function _lmStudioReasoningError(data, fallbackMessage) {
  const err = new Error((data && data.error) || fallbackMessage);
  if (data && data.emptyWithReasoning) {
    err.emptyWithReasoning = true;
    err.currentMaxTokens = data.currentMaxTokens || 0;
  }
  return err;
}

// Call with the caught error (or the raw parsed response body, for call
// sites that fetch() directly instead of going through this module) — both
// shapes carry the same emptyWithReasoning/currentMaxTokens fields. Returns
// the suggested maxTokens to retry with if the user accepts, or null if this
// wasn't that kind of error or the user declined.
function _confirmRetryWithMoreTokens(errOrData) {
  if (!errOrData || !errOrData.emptyWithReasoning) return null;
  const current = errOrData.currentMaxTokens || 0;
  const suggested = current ? current * 2 : 8000;
  return window.confirm(
    'The model used all its tokens on reasoning and produced no output.\n\n' +
    (current ? `Current max tokens: ${current}\nRetry with: ${suggested}\n\n` : '') +
    'Press OK to retry with more tokens, or Cancel to abort.'
  ) ? suggested : null;
}

// Reads the persisted Think Compatibility verdict for a model out of the
// settings blob (settings.lmStudioThinkCompat, {modelId: {state, checkedAt}}
// — written by POST /api/models/chat/check-think-compatibility). A model with
// no entry (never checked, or newly added since the last check) reads as
// 'unchecked', not 'supported' — the app should never assume a model is fine
// on thinking control just because nobody has tested it yet.
//
// Three checked states, from two real tests against the model (see
// check_think_compatibility, chat_routes.py):
//   'supported'   — reasons, and respects "don't think" when asked off. The
//                    only state where the think toggle should be enabled.
//   'unsupported' — reasons but ignores "don't think" — can burn its whole
//                    token budget without ever answering. The dangerous case.
//   'no_thinking' — never produces reasoning_content even when explicitly
//                    asked to think — no reasoning capability at all. Not
//                    dangerous, just nothing for the toggle to do.
function _thinkCompatState(settings, modelId) {
  const compat = (settings && settings.lmStudioThinkCompat) || {};
  const entry = modelId ? compat[modelId] : null;
  if (!entry) return 'unchecked';
  if (entry.state) return entry.state;
  // Back-compat with the earlier {supported: bool} shape (pre no_thinking split).
  return entry.supported ? 'supported' : 'unsupported';
}

// Disables a "think" toggle element (button/checkbox/chip — anything with a
// .disabled property) and sets its tooltip according to the model's Think
// Compatibility state. Leaves it enabled with no tooltip override when the
// model is known to support thinking control.
function _applyThinkCompatToToggle(el, state) {
  if (!el) return;
  if (state === 'unsupported') {
    el.disabled = true;
    el.title = 'This model does not support disabling thinking.';
  } else if (state === 'no_thinking') {
    el.disabled = true;
    el.title = 'This model has no thinking/reasoning capability — nothing for this toggle to do.';
  } else if (state === 'unchecked') {
    el.disabled = true;
    el.title = 'Check this model’s think compatibility in Settings > Prompts.';
  } else {
    el.disabled = false;
    el.removeAttribute('title');
  }
}

window.openJourneyApi = {
  confirmRetryWithMoreTokens: _confirmRetryWithMoreTokens,
  thinkCompatState: _thinkCompatState,
  applyThinkCompatToToggle: _applyThinkCompatToToggle,

  async getTemplates() {
    const res = await fetch('/api/templates');
    return res.json();
  },

  async getStyles(pageId) {
    const id = String(pageId || '').trim();
    const query = id ? `?page=${encodeURIComponent(id)}` : '';
    const res = await fetch(`/api/styles${query}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load styles');
    }
    return data;
  },

  async getStylePages() {
    const res = await fetch('/api/styles/pages');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load style pages');
    return data;
  },

  async createStylePage(payload) {
    const res = await fetch('/api/styles/pages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to create style page');
    return data;
  },

  async resetStylePages() {
    const res = await fetch('/api/styles/pages', { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to reset style pages');
    return data;
  },

  async deleteStylePage(pageId) {
    const target = String(pageId || '').trim();
    if (!target) throw new Error('Page id is required');
    const res = await fetch(`/api/styles/pages/${encodeURIComponent(target)}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to delete style page');
    return data;
  },

  async importStyles(stylesArray) {
    const res = await fetch('/api/styles/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ styles: stylesArray }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to import styles');
    return data;
  },

  async getBackgrounds() {
    const res = await fetch('/api/backgrounds');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load backgrounds');
    return data;
  },

  async createBackground(payload) {
    const res = await fetch('/api/backgrounds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to create background');
    return data;
  },

  async updateBackgroundImage(keyword, payload) {
    const res = await fetch(`/api/backgrounds/${encodeURIComponent(String(keyword || '').trim())}/image`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update background image');
    return data;
  },

  async getCharacters() {
    const res = await fetch('/api/characters');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load characters');
    return data;
  },

  async createCharacter(payload) {
    const res = await fetch('/api/characters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to create character');
    return data;
  },

  async updateCharacterImage(keyword, payload) {
    const res = await fetch(`/api/characters/${encodeURIComponent(String(keyword || '').trim())}/image`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update character image');
    return data;
  },

  async updateStyleImage(styleId, payload) {
    const res = await fetch(`/api/styles/${encodeURIComponent(String(styleId))}/image`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to update style image');
    }
    return data;
  },

  async updateStyle(styleId, payload) {
    const res = await fetch(`/api/styles/${encodeURIComponent(String(styleId))}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update style');
    return data;
  },

  async deleteStyle(styleId) {
    const res = await fetch(`/api/styles/${encodeURIComponent(String(styleId))}`, {
      method: 'DELETE',
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to delete style');
    return data;
  },

  async getTemplatePacks() {
    const res = await fetch('/api/template-packs');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load template packs');
    return data;
  },

  async createTemplatePack(payload) {
    const res = await fetch('/api/template-packs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to create template');
    return data;
  },

  async updateTemplatePack(packId, payload) {
    const res = await fetch(`/api/template-packs/${encodeURIComponent(String(packId))}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update template');
    return data;
  },

  async deleteTemplatePack(packId) {
    const res = await fetch(`/api/template-packs/${encodeURIComponent(String(packId))}`, {
      method: 'DELETE',
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to delete template');
    return data;
  },

  async addTemplatePackImage(packId, payload) {
    const res = await fetch(`/api/template-packs/${encodeURIComponent(String(packId))}/images`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to add template image');
    return data;
  },

  async deleteTemplatePackImage(packId, imageIndex) {
    const res = await fetch(`/api/template-packs/${encodeURIComponent(String(packId))}/images/${encodeURIComponent(String(imageIndex))}`, {
      method: 'DELETE',
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to delete template image');
    return data;
  },

  async getTemplatePackFieldValues(pack, theme) {
    const res = await fetch(`/api/template-packs/field-values/${encodeURIComponent(String(pack || ''))}/${encodeURIComponent(String(theme || ''))}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load field values');
    return data;
  },

  async updateTemplatePackFieldValues(pack, theme, values) {
    const res = await fetch(`/api/template-packs/field-values/${encodeURIComponent(String(pack || ''))}/${encodeURIComponent(String(theme || ''))}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values: values || {} }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to save field values');
    return data;
  },


  async createTemplate(payload) {
    const res = await fetch('/api/templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to create template');
    }
    return res.json();
  },

  async renderTemplate(content, values) {
    const res = await fetch('/api/templates/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, values }),
    });
    return res.json();
  },

  async listImports() {
    const res = await fetch('/api/models/imports');
    return res.json();
  },

  async getActiveImport() {
    const res = await fetch('/api/models/imports/active');
    return res.json();
  },

  async analyzeWorkflow(workflow) {
    const res = await fetch('/api/models/imports/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to analyze workflow');
    }
    return res.json();
  },

  async createImport(payload) {
    const res = await fetch('/api/models/imports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to create import');
    }
    return res.json();
  },

  async updateImport(importId, payload) {
    const res = await fetch(`/api/models/imports/${importId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to update import');
    }
    return res.json();
  },

  async getImport(importId) {
    const res = await fetch(`/api/models/imports/${importId}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to fetch import');
    }
    return res.json();
  },

  async activateImport(importId) {
    const res = await fetch(`/api/models/imports/${importId}/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to activate import');
    }
    return res.json();
  },

  async deactivateImport(importId) {
    const res = await fetch(`/api/models/imports/${importId}/activate`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to deactivate import');
    }
    return res.json();
  },

  async deleteImport(importId) {
    const res = await fetch(`/api/models/imports/${importId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to delete import');
    }
    return res.json();
  },

  async updateImportValues(importId, payload) {
    const advancedValues = payload && typeof payload === 'object' && payload.advancedValues && typeof payload.advancedValues === 'object'
      ? payload.advancedValues
      : null;
    const loraAdvanced = {};
    if (advancedValues) {
      Object.entries(advancedValues).forEach(([key, value]) => {
        const normalizedKey = String(key || '');
        if (!normalizedKey.includes('.')) return;
        if (!normalizedKey.includes('lora_name')
          && !normalizedKey.includes('strength_model')
          && !normalizedKey.includes('strength_clip')
          && !normalizedKey.includes('__lora_chain')) {
          return;
        }
        loraAdvanced[normalizedKey] = value;
      });
    }

    if (Object.keys(loraAdvanced).length) {
      console.info('[LoRA][PATCH->values] request', {
        importId,
        loraAdvanced,
      });
    }

    const res = await fetch(`/api/models/imports/${importId}/values`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to update import values');
    }
    const data = await res.json();
    if (Object.keys(loraAdvanced).length) {
      const savedAdvanced = data && data.import && typeof data.import === 'object' && data.import.advancedValues && typeof data.import.advancedValues === 'object'
        ? data.import.advancedValues
        : {};
      const savedLoraAdvanced = {};
      Object.keys(loraAdvanced).forEach((key) => {
        savedLoraAdvanced[key] = Object.prototype.hasOwnProperty.call(savedAdvanced, key)
          ? savedAdvanced[key]
          : null;
      });
      console.info('[LoRA][PATCH->values] response', {
        importId,
        savedLoraAdvanced,
      });
    }
    return data;
  },

  async renameImport(importId, name) {
    const res = await fetch(`/api/models/imports/${importId}/values`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to rename import');
    }
    return data;
  },

  async getImportAnnotations(importId) {
    const res = await fetch(`/api/models/imports/${importId}/annotations`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load import annotations');
    }
    return data;
  },

  async updateImportAnnotations(importId, payload) {
    const res = await fetch(`/api/models/imports/${importId}/annotations`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to update import annotations');
    }
    return data;
  },

  async listWorkflowLogos() {
    const res = await fetch('/api/models/workflow-logos');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load workflow logos');
    }
    return data;
  },

  async uploadWorkflowLogo(file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/api/models/workflow-logos', {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to upload workflow logo');
    }
    return data;
  },

  async getImportRequirements(importId) {
    const res = await fetch(`/api/models/imports/${importId}/requirements`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load requirements');
    }
    return data;
  },

  async getImportParamOptions(importId) {
    const res = await fetch(`/api/models/imports/${importId}/param-options`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load param options');
    }
    return data; // { options: { "key": ["opt1", ...] } }
  },

  async getImportCheckpoints(importId) {
    const res = await fetch(`/api/models/imports/${importId}/checkpoints`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load import checkpoints');
    }
    return data;
  },

  async getImportLoras(importId) {
    const res = await fetch(`/api/models/imports/${importId}/loras`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load import LoRAs');
    }
    return data;
  },

  async getImportLoraDetails(importId, loraName) {
    const encoded = encodeURIComponent(String(loraName || '').trim());
    const res = await fetch(`/api/models/imports/${importId}/loras/details?lora=${encoded}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load LoRA details');
    }
    return data;
  },

  async getModelsSettings() {
    const res = await fetch('/api/models/settings');
    return res.json();
  },

  async updateModelsSettings(payload) {
    const res = await fetch('/api/models/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to update models settings');
    }
    return res.json();
  },

  async getUpscaleSettings() {
    const res = await fetch('/api/models/upscale/settings');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load upscale settings');
    }
    return data;
  },

  async updateUpscaleSettings(payload) {
    const res = await fetch('/api/models/upscale/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to save upscale settings');
    }
    return data;
  },

  async generateUpscaleImage(payload) {
    const res = await fetch('/api/models/upscale/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to upscale image');
    }
    return data;
  },

  async getUpscaleProgress(payload = {}) {
    const params = new URLSearchParams();
    if (payload && payload.modelId) {
      params.set('modelId', String(payload.modelId));
    }
    if (payload && payload.comfyApiUrl) {
      params.set('comfyApiUrl', String(payload.comfyApiUrl));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`/api/models/upscale/progress${suffix}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to read upscale progress');
    }
    return data;
  },

  async getComposeSettings() {
    const res = await fetch('/api/models/compose/settings');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load compose settings');
    }
    return data;
  },

  async updateComposeSettings(payload) {
    const res = await fetch('/api/models/compose/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to save compose settings');
    }
    return data;
  },

  async generateComposeImage(payload) {
    const res = await fetch('/api/models/compose/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to run compose workflow');
    }
    return data;
  },

  async getComposeProgress(payload = {}) {
    const params = new URLSearchParams();
    if (payload && payload.modelId) {
      params.set('modelId', String(payload.modelId));
    }
    if (payload && payload.comfyApiUrl) {
      params.set('comfyApiUrl', String(payload.comfyApiUrl));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`/api/models/compose/progress${suffix}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to read compose progress');
    }
    return data;
  },

  async testModelsConnection(payload) {
    const res = await fetch('/api/models/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    let data = {};
    try {
      data = await res.json();
    } catch {
      data = {};
    }
    if (!res.ok) {
      throw new Error(data.error || 'Connection test failed');
    }
    if (data && data.ok === false) {
      throw new Error(data.error || 'ComfyUI is unavailable');
    }
    return data;
  },

  async pingChatService(source = 'unknown', force = false) {
    const params = new URLSearchParams({ source });
    if (force) params.set('force', '1');
    const res = await fetch(`/api/models/chat/ping?${params.toString()}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Chat service unavailable');
    return data;
  },

  async getModelsChatSettings() {
    const res = await fetch('/api/models/chat/settings');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load chat settings');
    }
    return data;
  },

  async updateModelsChatSettings(payload) {
    const res = await fetch('/api/models/chat/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to update chat settings');
    }
    return data;
  },

  async checkThinkCompatibility(model) {
    const res = await fetch('/api/models/chat/check-think-compatibility', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: model || '' }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to check think compatibility');
    }
    return data;
  },

  async listBenchmarkPendingModels() {
    const res = await fetch('/api/models/chat/benchmark-pending');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to list pending models');
    return data;
  },

  async benchmarkModel(model) {
    const res = await fetch('/api/models/chat/benchmark-model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: model || '' }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to benchmark model');
    return data;
  },

  async loadLmStudioModels(payload) {
    const res = await fetch('/api/models/chat/models/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load LM Studio models');
    }
    return data;
  },

  async editPromptWithLmStudio(payload) {
    const res = await fetch('/api/models/chat/edit-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw _lmStudioReasoningError(data, 'Failed to edit prompt with LM Studio');
    }
    return data;
  },

  async studioEnhancePrompt(payload) {
    const res = await fetch('/api/models/chat/studio-enhance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw _lmStudioReasoningError(data, 'Enhancement failed');
    }
    return data;
  },

  async convertPromptToJsonWithLmStudio(payload) {
    const res = await fetch('/api/models/chat/convert-to-json', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw _lmStudioReasoningError(data, 'Failed to convert prompt to JSON with LM Studio');
    }
    return data;
  },

  async regenerateJsonFieldWithLmStudio(payload) {
    const res = await fetch('/api/models/chat/regenerate-json-field', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw _lmStudioReasoningError(data, 'Failed to regenerate JSON field with LM Studio');
    }
    return data;
  },

  async generateStyleFromImage(payload) {
    const res = await fetch('/api/styles/generate-from-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw _lmStudioReasoningError(data, 'Failed to generate style from image');
    return data;
  },

  async describeImageWithLmStudio(payload) {
    const res = await fetch('/api/models/chat/describe-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw _lmStudioReasoningError(data, 'Failed to describe image with LM Studio');
    }
    return data;
  },

  async describeBenchmarkWithLmStudio(payload) {
    const res = await fetch('/api/models/chat/describe-benchmark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to run describe benchmark with LM Studio');
    }
    return data;
  },

  async listDescribeBenchmarkModels() {
    const res = await fetch('/api/models/chat/describe-benchmark/models');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to list describe benchmark models');
    }
    return data;
  },

  async getDescribeBenchmarkProgress(runId) {
    const encoded = encodeURIComponent(String(runId || '').trim());
    const res = await fetch(`/api/models/chat/describe-benchmark/progress/${encoded}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to read describe benchmark progress');
    }
    return data;
  },

  async stopDescribeBenchmarkWithLmStudio(payload) {
    const res = await fetch('/api/models/chat/describe-benchmark/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to request benchmark stop');
    }
    return data;
  },

  async blendPromptsWithLmStudio(payload) {
    const res = await fetch('/api/models/chat/blend-prompts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) {
      throw _lmStudioReasoningError(data, 'Failed to blend prompts with LM Studio');
    }
    return data;
  },

  async generateImportImage(importId, payload) {
    const res = await fetch(`/api/models/imports/${importId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to generate image from import');
    }
    return res.json();
  },

  async submitImportGeneration(importId, payload) {
    const res = await fetch(`/api/models/imports/${importId}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to submit generation');
    return data;
  },

  async submitQueueGeneration(payload) {
    const res = await fetch('/api/models/imports/submit-queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    // 503 means allUnreachable — return the body rather than throwing so caller can handle it
    if (!res.ok && res.status !== 503) throw new Error(data.error || 'Failed to submit generation');
    return data;
  },

  async updateQueueFreeMemorySetting(value) {
    const res = await fetch('/api/models/settings/queue-free-memory', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ queueFreeMemoryBetweenModels: value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update setting');
    return data;
  },

  async pollImportResult(importId, payload) {
    const res = await fetch(`/api/models/imports/${importId}/result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to poll result');
    return data;
  },

  // ----- Image gallery (server-side saved images) -----

  async listImages(options = {}) {
    const limitValue = Number(options.limit);
    const hasLimit = Number.isFinite(limitValue) && limitValue > 0;
    const limit = hasLimit ? Math.max(1, Math.min(1000, Math.trunc(limitValue))) : null;
    const cursorValue = String(options.cursor || '').trim();
    const hasCursor = cursorValue.length > 0;
    const snapshotValue = String(options.snapshot || '').trim();
    const hasSnapshot = snapshotValue.length > 0;
    const offsetValue = Number(options.offset);
    const hasOffset = Number.isFinite(offsetValue) && offsetValue >= 0;
    const params = new URLSearchParams();
    if (limit) params.set('limit', String(limit));
    if (hasCursor) {
      params.set('cursor', cursorValue);
    } else if (hasOffset) {
      params.set('offset', String(Math.trunc(offsetValue)));
    }
    if (hasSnapshot) {
      params.set('snapshot', snapshotValue);
    }
    // Optional: browse another (agent) viewer's folder without touching the
    // active session — see _active_viewer_id()'s ?viewer= fallback for
    // agents in models_api_shared.py. Never accepted for human viewers.
    const viewerValue = String(options.viewer || '').trim();
    if (viewerValue) params.set('viewer', viewerValue);
    const query = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`/api/images${query}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to list images');
    return data;
  },

  getImageUrl(filename, viewer) {
    // Encode each path segment so sub-folder paths (e.g. "session/foo/bar.png")
    // are not turned into %2F. For plain filenames this is unchanged.
    const path = '/api/images/' + String(filename).split('/').map(encodeURIComponent).join('/');
    return viewer ? `${path}?viewer=${encodeURIComponent(viewer)}` : path;
  },

  getImageThumbUrl(filename, w = 400, viewer) {
    const base = `/api/images/${encodeURIComponent(filename)}/thumb?w=${w}`;
    return viewer ? `${base}&viewer=${encodeURIComponent(viewer)}` : base;
  },

  async updateImageMeta(filename, payload) {
    const res = await fetch(`/api/images/${encodeURIComponent(filename)}/meta`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to update image meta');
    return data;
  },

  async deleteImages(filenames) {
    const res = await fetch('/api/images', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filenames: Array.isArray(filenames) ? filenames : [] }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to delete images');
    return data;
  },

  async freeComfyMemory(payload = {}) {
    const res = await fetch('/api/images/free-memory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ unload_models: true, free_memory: true, ...payload }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to free ComfyUI memory');
    return data;
  },

  async clearComfyQueue(payload = {}) {
    const res = await fetch('/api/images/queue/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to clear ComfyUI queue');
    return data;
  },

  async getComfyServerState(options = {}) {
    const comfyApiUrl = String(options.comfyApiUrl || '').trim();
    if (!comfyApiUrl) {
      throw new Error('comfyApiUrl is required');
    }
    const params = new URLSearchParams({ comfyApiUrl });
    const res = await fetch(`/api/images/comfy/server-state?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to fetch ComfyUI server state');
    return data;
  },

  async saveComfyImages(payload = {}) {
    const res = await fetch('/api/images/save-comfy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to save ComfyUI images');
    return data;
  },
};
