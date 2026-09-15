(async function createPage() {
  document.body.classList.add('create-page');

  const importedPanel = document.getElementById('imported-workflow-panel');
  const importNameEl = document.getElementById('active-import-name');
  const importedFieldsEl = document.getElementById('imported-workflow-fields');
  const saveImportValuesBtn = document.getElementById('save-import-values');


  const generationProgressBarEl = document.getElementById('generation-progress-bar');
  const generationStatusTextEl = document.getElementById('generation-status-text');
  const clearClientGalleryBtn = document.getElementById('clear-client-gallery');
  const createRightSidebarToggleBtn = document.getElementById('create-right-sidebar-toggle');
  const createDiamondToggleBtn = document.getElementById('create-diamond-toggle');
  const createGalleryZoomInBtn = document.getElementById('create-gallery-zoom-in');
  const createGalleryZoomOutBtn = document.getElementById('create-gallery-zoom-out');
  const createTagMagnifierToggleBtn = document.getElementById('create-tag-magnifier-toggle');
  const clientGalleryEl = document.getElementById('client-gallery');
  const createLayoutEl = document.querySelector('.create-layout');
  const groupFeedEl = document.querySelector('.group-feed');
  const aspectRatioValueEl = document.getElementById('aspect-ratio-value');
  const aspectRatioVisualInnerEl = document.getElementById('aspect-ratio-visual-inner');
  const resolutionWidthInputEl = document.getElementById('resolution-width-input');
  const resolutionHeightInputEl = document.getElementById('resolution-height-input');
  const aspectRatioSliderEl = document.getElementById('aspect-ratio-slider');
  const imagesCountInputEl = document.getElementById('images-count-input');
  const imagesCountDecreaseBtn = document.getElementById('images-count-decrease');
  const imagesCountIncreaseBtn = document.getElementById('images-count-increase');
  const ratioModeButtons = Array.from(document.querySelectorAll('.ratio-mode'));
  const resolutionButtons = Array.from(document.querySelectorAll('.resolution-tag'));
  const topbarPositiveInputEl = document.getElementById('prompt-positive-input');
  const topbarNegativeInputEl = document.getElementById('prompt-negative-input');
  const topbarChatInputEl = document.getElementById('prompt-chat-input');
  const toggleChatInputBtn = document.getElementById('toggle-chat-input-btn');
  const openNewModalBtn = document.getElementById('open-new-modal-btn');
  const openDescribeModalBtn = document.getElementById('open-describe-modal-btn');
  const openBrainModalBtn = document.getElementById('open-brain-modal-btn');
  const createSessionInputEl = document.getElementById('create-session-input');
  const newModalEl = document.getElementById('new-modal');
  const promptInlinePickerEl = document.getElementById('prompt-inline-picker');
  const newPromptLibraryListEl = document.getElementById('new-prompt-library-list');
  const newModalSendBtn = document.getElementById('new-modal-send-btn');
  const newModalConvertJsonBtn = document.getElementById('new-modal-convert-json-btn');
  const newConvertJsonThinkEl = document.getElementById('new-convert-json-think-checkbox');
  const newEnhanceToggleBtn = document.getElementById('new-enhance-toggle-btn');
  const newModalPastePositiveBtn = document.getElementById('new-modal-paste-positive-btn');
  const newModalPasteNegativeBtn = document.getElementById('new-modal-paste-negative-btn');
  const newJsonToggleBtn = document.getElementById('new-json-toggle-btn');
  const newModalImageToggleBtn = document.getElementById('new-modal-image-toggle-btn');
  const newModalImageWrapEl = document.getElementById('new-modal-image-wrap');
  const newModalImageDropEl = document.getElementById('new-modal-image-drop');
  const newModalImageFileInputEl = document.getElementById('new-modal-image-file-input');
  const newModalImagePreviewWrapEl = document.getElementById('new-modal-image-preview-wrap');
  const newModalImagePreviewEl = document.getElementById('new-modal-image-preview');
  const newModalImageDropPlaceholderEl = document.getElementById('new-modal-image-drop-placeholder');
  const newModalImageClearBtn = document.getElementById('new-modal-image-clear-btn');
  const newModalImageVisionStatusEl = document.getElementById('new-modal-image-vision-status');
  const newJsonEditorWrapEl = document.getElementById('new-json-editor-wrap');
  const newJsonEditorFieldsEl = document.getElementById('new-json-editor-fields');
  const newJsonEditorMessageEl = document.getElementById('new-json-editor-message');
  const newJsonEditorProgressEl = document.getElementById('new-json-editor-progress');
  const describeModalEl = document.getElementById('describe-modal');
  const describeImageFileInputEl = document.getElementById('describe-image-file-input');
  const describeDropZoneEl = document.getElementById('describe-drop-zone');
  const describePreviewWrapEl = document.getElementById('describe-preview-wrap');
  const describePreviewImageEl = document.getElementById('describe-preview-image');
  const describeProgressTextEl = document.getElementById('describe-progress-text');
  const describeLineProgressEl = document.getElementById('describe-line-progress');
  const newConvertProgressEl = document.getElementById('new-convert-progress');
  const describeOutputInputEl = document.getElementById('describe-output-input');
  const describeBlendOutputInputEl = document.getElementById('describe-blend-output-input');
  const describeStyleOutputInputEl = document.getElementById('describe-style-output-input');
  const describeRunBtn = document.getElementById('describe-run-btn');
  const describeStyleRunBtn = document.getElementById('describe-style-run-btn');
  const describeBlendRunBtn = document.getElementById('describe-blend-run-btn');
  const describeStyleCopyBtn = document.getElementById('describe-style-copy-btn');
  const describeSendBtn = document.getElementById('describe-send-btn');
  const describeSendBlendBtn = document.getElementById('describe-send-blend-btn');
  const describeClearBtn = document.getElementById('describe-clear-btn');
  const describeFreeMemoryBtn = document.getElementById('describe-free-memory-btn');
  const describeMatchAspectBtn = document.getElementById('describe-match-aspect-btn');
  const describePasteBtn = document.getElementById('describe-paste-btn');
  const describeThinkToggleBtn = document.getElementById('describe-think-toggle-btn');
  const describeScopeToggleBtn = document.getElementById('describe-scope-toggle-btn');
  const describeFormatToggleBtn = document.getElementById('describe-format-toggle-btn');
  const describeJsonToggleBtn = document.getElementById('describe-json-toggle-btn');
  const describeJsonEditorWrapEl = document.getElementById('describe-json-editor-wrap');
  const describeJsonEditorFieldsEl = document.getElementById('describe-json-editor-fields');
  const describeJsonEditorMessageEl = document.getElementById('describe-json-editor-message');
  const brainModalEl = document.getElementById('brain-modal');
  const brainCurrentPromptInputEl = document.getElementById('brain-current-prompt-input');
  const brainInstructionInputEl = document.getElementById('brain-instruction-input');
  const brainGenerationsSliderEl = document.getElementById('brain-generations-slider');
  const brainGenerationsValueEl = document.getElementById('brain-generations-value');
  const brainProgressTextEl = document.getElementById('brain-progress-text');
  const brainRunBtn = document.getElementById('brain-run-btn');
  const brainThinkCheckboxEl = document.getElementById('brain-think-checkbox');
  const brainClearBtn = document.getElementById('brain-clear-btn');
  const brainFreeMemoryBtn = document.getElementById('brain-free-memory-btn');
  const brainJsonToggleBtn = document.getElementById('brain-json-toggle-btn');
  const brainJsonEditorWrapEl = document.getElementById('brain-json-editor-wrap');
  const brainJsonEditorFieldsEl = document.getElementById('brain-json-editor-fields');
  const brainJsonEditorMessageEl = document.getElementById('brain-json-editor-message');
  const chatModalEl = document.getElementById('chat-modal');
  const chatModalSendBtn = document.getElementById('chat-modal-send-btn');
  const chatClearBtn = document.getElementById('chat-clear-btn');
  const chatFreeMemoryBtn = document.getElementById('chat-free-memory-btn');
  const chatJsonToggleBtn = document.getElementById('chat-json-toggle-btn');
  const chatJsonEditorWrapEl = document.getElementById('chat-json-editor-wrap');
  const chatJsonEditorFieldsEl = document.getElementById('chat-json-editor-fields');
  const chatJsonEditorMessageEl = document.getElementById('chat-json-editor-message');
  const chatInitialPromptEl = document.getElementById('chat-initial-prompt');
  const chatInitialPromptTextEl = document.getElementById('chat-initial-prompt-text');
  const chatTimelineWrapEl = document.getElementById('chat-timeline-wrap');
  const chatTimelineTrackEl = document.getElementById('chat-timeline-track');
  const chatTimelineStatusEl = document.getElementById('chat-timeline-status');
  const chatThinkCheckboxEl = document.getElementById('chat-think-checkbox');
  const chatTimelineResetBtn = document.getElementById('chat-timeline-reset-btn');
  const seedModeSelectEl = document.getElementById('seed-mode-select');
  const modelCheckpointWrapEl = document.getElementById('model-checkpoint-wrap');
  const modelCheckpointSelectEl = document.getElementById('model-checkpoint-select');
  const seedFixedInputEl = document.getElementById('seed-fixed-input');
  const modelAdvancedDetailsEl = document.getElementById('model-advanced-details');
  const modelCfgInputEl = document.getElementById('model-cfg-input');
  const modelStepsInputEl = document.getElementById('model-steps-input');
  const modelAdvancedStatusEl = document.getElementById('model-advanced-status');
  const modelBooleanFieldsEl = document.getElementById('model-boolean-fields');
  const modelDynamicAdvancedFieldsEl = document.getElementById('model-dynamic-advanced-fields');
  const sidebarQueuePanelEl = document.getElementById('sidebar-queue-panel');
  const sidebarQueueCountEl = document.getElementById('sidebar-queue-count');
  const sidebarQueueProgressEl = document.getElementById('sidebar-queue-progress');
  const sidebarQueueProgressBarEl = document.getElementById('sidebar-queue-progress-bar');
  const sidebarQueueListEl = document.getElementById('sidebar-queue-list');
  const sidebarQueueClearBtn = document.getElementById('sidebar-queue-clear-btn');
  const lockResolutionBtn = document.getElementById('lock-resolution-btn');
  const lockAspectBtn = document.getElementById('lock-aspect-btn');
  const lockSeedModeBtn = document.getElementById('lock-seed-mode-btn');
  const lockModelAdvancedBtn = document.getElementById('lock-model-advanced-btn');
  const rightPanelEl = document.querySelector('.panel-right');
  const stylizationRangeEl = document.getElementById('stylization-range');
  const weirdnessRangeEl = document.getElementById('weirdness-range');
  const varietyRangeEl = document.getElementById('variety-range');
  const uiGroupButtons = Array.from(document.querySelectorAll('[data-ui-group]'));

  const fieldsContainer = document.getElementById('template-fields');
  const previewEl = document.getElementById('render-preview');
  const loadBtn = document.getElementById('load-default-template');
  const generateBtn = document.getElementById('generate-button');

  const folderAccessService = window.openJourneyFolderAccess;

  let viewerState = {
    items: [],
    index: 0,
  };
  let viewerElements = null;
  let hasNegativePrompt = false;
  let incrementSeedCursor = null;
  let chatTimeline = [];
  let chatTimelineCursor = -1;
  let chatOriginalPrompt = '';
  let chatInitialText = '';
  let chatAutoDisconnectEnabled = false;
  let checkpointAdvancedKeys = [];

  // Add this after variable declarations and before main init functions
  function prefillFromExploreFull() {
    try {
      const fullRaw = sessionStorage.getItem('oj-prefill-full');
      if (!fullRaw) return false;
      const fullData = JSON.parse(fullRaw);
      sessionStorage.removeItem('oj-prefill-full');

      const openNewRaw = sessionStorage.getItem('oj-open-new-modal');
      const shouldOpenNew = openNewRaw === 'true';
      sessionStorage.removeItem('oj-open-new-modal');

      if (!fullData || typeof fullData !== 'object') return false;

      // Prefill positive prompt
      if (topbarPositiveInputEl && fullData.positive) {
        topbarPositiveInputEl.value = fullData.positive;
      }

      // Prefill negative prompt
      if (topbarNegativeInputEl && fullData.negative) {
        topbarNegativeInputEl.value = fullData.negative;
      }

      // Set resolution
      if (resolutionWidthInputEl && Number.isFinite(fullData.width)) {
        resolutionWidthInputEl.value = String(fullData.width);
      }
      if (resolutionHeightInputEl && Number.isFinite(fullData.height)) {
        resolutionHeightInputEl.value = String(fullData.height);
      }

      // Set seed to fixed mode
      if (seedModeSelectEl) {
        seedModeSelectEl.value = 'fixed';
      }
      if (seedFixedInputEl && fullData.seed) {
        setSeedInputValue(fullData.seed);
      }
      incrementSeedCursor = null;

      // Set checkpoint if possible
      if (modelCheckpointSelectEl && fullData.checkpoint) {
        const option = Array.from(modelCheckpointSelectEl.options).find(opt => opt.textContent.includes(fullData.checkpoint));
        if (option) {
          modelCheckpointSelectEl.value = option.value;
        }
      }

      // Set workflow/import if possible (assuming workflow select exists)
      // Note: Adjust selector if workflow select ID is different
      const workflowSelect = document.getElementById('workflow-select') || document.querySelector('[name="workflow"]');
      if (workflowSelect && fullData.workflow) {
        const option = Array.from(workflowSelect.options).find(opt => opt.textContent.includes(fullData.workflow));
        if (option) {
          workflowSelect.value = option.value;
        }
      }

      // Set CFG and steps
      if (modelCfgInputEl && fullData.cfg) {
        modelCfgInputEl.value = String(fullData.cfg);
      }
      if (modelStepsInputEl && fullData.steps) {
        modelStepsInputEl.value = String(fullData.steps);
      }

      // For LoRAs: Would need specific logic to set LoRA chain based on metadata
      // Placeholder: if fullData.loras is array, set them in LoRA picker or inputs

      saveRightPanelSettings();
      updateSendButtonState();
      setGenerationStatus('Full settings loaded from Explore image (fixed seed mode).');

      if (shouldOpenNew && newModalEl) {
        newModalEl.classList.add('open');
        newModalEl.setAttribute('aria-hidden', 'false');
        // Trigger any open modal events if needed
      }

      return true;
    } catch (error) {
      console.error('Error prefilling from Explore full:', error);
      return false;
    }
  }

  const templates = [];
  let selected = null;
  let galleryCache = [];
  let activeImportRecordsCache = [];

  const GALLERY_DB_NAME = 'openjourney-client-db';
  const GALLERY_DB_VERSION = 1;
  const GALLERY_STORE_NAME = 'gallery';
  const GALLERY_KEY = 'oj-client-images';
  const CLIENT_GALLERY_INITIAL_BATCHES = 6;
  const CLIENT_GALLERY_LOAD_STEP = 4;
  const RIGHT_PANEL_SETTINGS_KEY = 'oj-create-right-panel-v1';
  const CHAT_TIMELINE_STORAGE_KEY = 'oj-create-chat-timeline-v1';
  const CREATE_GALLERY_ZOOM_KEY = 'oj-create-gallery-zoom-v1';
  const CREATE_TAG_MAGNIFIER_ENABLED_KEY = 'oj-create-tag-magnifier-enabled-v1';
  const CREATE_RIGHT_PANEL_COLLAPSED_KEY = 'oj-create-right-panel-collapsed-v1';
  const CREATE_LEFT_PANEL_COLLAPSED_KEY = 'oj-create-left-panel-collapsed-v1';
  const SHOW_DIAMOND_IMAGES_KEY = 'oj-image-diamond-mode-v2';
  const CREATE_BRAIN_SETTINGS_KEY = 'oj-create-brain-settings-v1';
  const CREATE_NEW_ENHANCE_KEY = 'oj-create-new-enhance-v1';
  const CREATE_SESSION_STORAGE_KEY = 'oj-create-session-v1';
  const CREATE_NEW_MODAL_DRAFT_KEY = 'oj-create-new-modal-draft-v1';
  const CREATE_TASK_QUEUE_KEY = 'oj-create-task-queue-v1';
  const UPSCALE_SOURCE_IMAGE_KEY = 'oj-upscale-source-image-v1';
  let clientGalleryRenderLimit = CLIENT_GALLERY_INITIAL_BATCHES;
  let clientGallerySentinelEl = null;
  let clientGalleryObserver = null;
  let createGalleryZoomLevel = 75;
  let rightSidebarCollapsed = false;
  let leftSidebarCollapsed = false;
  let showDiamondMarkedImages = true;
  let promptMagnifierEnabled = true;
  let brainRunning = false;
  let newConvertJsonRunning = false;
  let newEnhanceEnabled = false;
  let describeRunning = false;
  let promptInlinePickerResolver = null;
  let promptInlinePickerOptions = [];
  let promptInlinePickerOutsideClickHandler = null;
  let sendQueue = [];
  let sendQueueRunning = false;
  let sendQueueCurrentIndex = 0;
  let sendQueueTotal = 0;
  let sendQueueNextId = Date.now();
  let sendQueueActiveTaskId = null;
  let sendQueueActiveTask = null;
  let sendQueueAbortRequested = false;
  let comfyStepValue = 0;
  let comfyStepMax = 0;
  let describeImageDataUrl = '';
  let describeScopeMode = 'full';
  let describeOutputFormat = 'paragraph';
  let describeThinkEnabled = false;
  const modalJsonEditors = new Map();
  const describeResultsCache = new Map();
  let promptMagnifierEl = null;
  let promptMagnifierContentEl = null;
  let modelAdvancedKeys = { cfg: null, steps: null };
  let modelBooleanKeys = {};
  let modelDynamicAdvancedMeta = {};
  let loraChainConfig = null;
  let loraCatalogItems = [];
  let loraCatalogByFile = new Map();
  let loraPickerModalEl = null;
  let loraPickerListEl = null;
  let loraPickerSearchInputEl = null;
  let loraPickerHeroNameEl = null;
  let loraPickerHeroTriggerEl = null;
  let loraPickerDetailImageEl = null;
  let loraPickerDetailNameEl = null;
  let loraPickerDetailFileEl = null;
  let loraPickerDetailKindEl = null;
  let loraPickerDetailTriggerEl = null;
  let loraPickerDetailUriEl = null;
  let loraPickerApplyBtnEl = null;
  let loraPickerCurrentSelection = '';
  let loraPickerContext = null;
  let loraDetailRequests = new Map();
  let modelAdvancedImportId = '';
  let sendBatchLocks = {
    resolution: false,
    aspectRatio: false,
    seedMode: false,
    modelAdvanced: false,
  };
  let modelAdvancedLockSnapshot = null;
  let activeSubmitModelAdvancedLockSnapshot = null;
  let pendingSendBatchLockSnapshot = null;

  const PROMPT_MAGNIFIER_SIZE = 180;
  const PROMPT_MAGNIFIER_ZOOM = 1.9;

  const RATIO_GROUPS = {
    portrait: ['1:2', '3:11', '6:11', '9:16', '2:3', '3:4', '4:5', '5:6', '1:1'],
    square: ['1:1'],
    landscape: ['2:1', '11:3', '11:6', '16:9', '3:2', '4:3', '5:4', '6:5', '1:1'],
  };
  const RESOLUTIONS = {
    MD: 512,
    SD: 1024,
    HD: 1280,
    FHD: 1920,
    '4K': 3840,
    '8K': 7680,
  };
  const LORA_CHAIN_MAX_ITEMS = 4;

  function dispatchNumericInputEvents(inputEl) {
    if (!inputEl) return;
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    inputEl.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function readNumericStep(inputEl) {
    const stepAttr = String(inputEl?.getAttribute('step') || '').trim();
    if (!stepAttr || stepAttr.toLowerCase() === 'any') {
      return 1;
    }
    const parsed = Number(stepAttr);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
  }

  function roundWithStepPrecision(value, step) {
    const decimals = String(step).includes('.') ? String(step).split('.')[1].length : 0;
    return Number(value.toFixed(Math.min(Math.max(decimals, 0), 6)));
  }

  function nudgeNumericInput(inputEl, direction) {
    if (!inputEl || inputEl.disabled) return;
    const step = readNumericStep(inputEl);
    const current = Number(inputEl.value);
    const base = Number.isFinite(current) ? current : 0;
    let next = base + (direction * step);

    const minRaw = inputEl.getAttribute('min');
    const maxRaw = inputEl.getAttribute('max');
    const minAttr = minRaw !== null && minRaw !== '' ? Number(minRaw) : NaN;
    const maxAttr = maxRaw !== null && maxRaw !== '' ? Number(maxRaw) : NaN;
    if (Number.isFinite(minAttr)) {
      next = Math.max(minAttr, next);
    }
    if (Number.isFinite(maxAttr)) {
      next = Math.min(maxAttr, next);
    }

    next = roundWithStepPrecision(next, step);
    inputEl.value = String(next);
    dispatchNumericInputEvents(inputEl);
  }

  function bindNumericHold(buttonEl, inputEl, direction) {
    if (!buttonEl || !inputEl) return;
    let holdTimer = null;
    let repeatTimer = null;

    const stopHold = () => {
      if (holdTimer) {
        window.clearTimeout(holdTimer);
        holdTimer = null;
      }
      if (repeatTimer) {
        window.clearInterval(repeatTimer);
        repeatTimer = null;
      }
    };

    const startHold = () => {
      stopHold();
      holdTimer = window.setTimeout(() => {
        repeatTimer = window.setInterval(() => {
          nudgeNumericInput(inputEl, direction);
        }, 85);
      }, 260);
    };

    buttonEl.addEventListener('mousedown', (event) => {
      event.preventDefault();
      startHold();
    });
    buttonEl.addEventListener('touchstart', () => {
      startHold();
    }, { passive: true });
    ['mouseup', 'mouseleave', 'touchend', 'touchcancel', 'blur'].forEach((eventName) => {
      buttonEl.addEventListener(eventName, stopHold);
    });
  }

  function applyNumericStepperToInput(inputEl) {
    if (!inputEl || inputEl.dataset.stepperReady === '1') return;
    if (inputEl.closest('.numeric-stepper')) {
      inputEl.dataset.stepperReady = '1';
      return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'numeric-stepper';

    const leftBtn = document.createElement('button');
    leftBtn.type = 'button';
    leftBtn.className = 'btn numeric-stepper-btn numeric-stepper-btn-left';
    leftBtn.setAttribute('aria-label', 'Decrease value');
    leftBtn.innerHTML = '<span aria-hidden="true">&#9664;</span>';

    const rightBtn = document.createElement('button');
    rightBtn.type = 'button';
    rightBtn.className = 'btn numeric-stepper-btn numeric-stepper-btn-right';
    rightBtn.setAttribute('aria-label', 'Increase value');
    rightBtn.innerHTML = '<span aria-hidden="true">&#9654;</span>';

    const parent = inputEl.parentNode;
    if (!parent) return;

    parent.insertBefore(wrapper, inputEl);
    wrapper.appendChild(leftBtn);
    wrapper.appendChild(inputEl);
    wrapper.appendChild(rightBtn);

    inputEl.dataset.stepperReady = '1';

    leftBtn.addEventListener('click', () => nudgeNumericInput(inputEl, -1));
    rightBtn.addEventListener('click', () => nudgeNumericInput(inputEl, 1));
    bindNumericHold(leftBtn, inputEl, -1);
    bindNumericHold(rightBtn, inputEl, 1);

    inputEl.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        nudgeNumericInput(inputEl, -1);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        nudgeNumericInput(inputEl, 1);
      }
    });
  }

  function ensureRightPanelNumericSteppers() {
    if (!rightPanelEl) return;
    const numericInputs = Array.from(rightPanelEl.querySelectorAll('input[type="number"]'));
    numericInputs.forEach((inputEl) => {
      const labelEl = inputEl.closest('label');
      if (labelEl && !labelEl.classList.contains('model-boolean-field')) {
        labelEl.classList.add('numeric-stepper-label');
      }
      applyNumericStepperToInput(inputEl);
    });
  }
  const TAG_STOP_WORDS = new Set([
    'the', 'and', 'with', 'for', 'this', 'that', 'from', 'into', 'very', 'best', 'highly',
    'image', 'prompt', 'style', 'quality', 'detail', 'detailed', 'lighting', 'scene', 'view',
    'a', 'an', 'to', 'of', 'in', 'on', 'by', 'at', 'is', 'are', 'be', 'as', 'it', 'its', 'or'
  ]);

  const aspectState = {
    mode: 'landscape',
    ratioIndex: 7,
    resolution: 'SD',
  };
  let generationStatusBaseText = 'Ready to generate';
  let generationProgressValue = 0;
  let lastGenerationErrorMessage = '';

  const IMAGES_MODEL_WAIT_INTERVAL_MS = 8000;
  const SUBMIT_QUEUE_RETRY_MAX_DELAY_MS = 30000;
  const SIDEBAR_QUEUE_MODEL_NAME_MAX_LEN = 24;

  function compactSidebarModelName(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    if (text.length <= SIDEBAR_QUEUE_MODEL_NAME_MAX_LEN) return text;
    return `${text.slice(0, SIDEBAR_QUEUE_MODEL_NAME_MAX_LEN - 1)}…`;
  }

  function formatModelArtifactLabel(value) {
    return String(value || '').trim().replace(/\.safetensors$/i, '');
  }



  if (topbarPositiveInputEl) {
    topbarPositiveInputEl.addEventListener('keydown', async (event) => {
      if (event.key !== 'Enter') return;
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      if (newModalSendBtn && newModalSendBtn.disabled) return;
      setNewModalOpen(false);
      await enqueueGenerationSend({
        queuedMessage: 'Generating image from prompt...',
      });
    });
  }

  if (createSessionInputEl) {
    createSessionInputEl.addEventListener('input', persistCurrentSessionValue);
    createSessionInputEl.addEventListener('blur', persistCurrentSessionValue);
  }

  if (clearClientGalleryBtn) {
    clearClientGalleryBtn.addEventListener('click', () => {
      galleryCache = [];
      persistGallery([]).catch(() => {
        setGenerationStatus('Could not clear gallery storage.', true);
      });
      renderClientGallery(true);
    });
  }

  await initializeGalleryStorage();
  restoreTaskQueue();
  setupClientGalleryInfiniteScroll();
  await loadActiveImport();
  restoreNewModalDraft();
  await recoverPendingBatches();
  restoreChatTimeline();
  // Prompt expand removed — prompts now live in the New modal.
  restoreCreateGalleryZoom();
  restoreRightSidebarCollapsed();
  restoreImageDiamondMode();
  applyImageDiamondModeUi();
  restorePromptMagnifierToggle();
  restoreBrainSettings();
  restoreNewEnhanceToggle();
  restoreCurrentSessionValue();
  setChatInputVisible(false);
  updateSendButtonLabel();
  restoreRightPanelSettings();
  ensureRightPanelNumericSteppers();
  updateTopbarPromptVisibility();
  updateSendButtonState();

  // Prefill from Explore full data if present
  prefillFromExploreFull();

  if (sidebarQueueClearBtn) {
    sidebarQueueClearBtn.addEventListener('click', clearPendingQueueTasks);
  }
  renderChatTimeline();
  renderAspectControls();
  ensureRightPanelNumericSteppers();
  saveRightPanelSettings();
  renderSidebarQueue();
  if (sendQueue.length) {
    void processSendQueue();
  }
  renderClientGallery(true);
  if (fieldsContainer) renderFields();

  // Pre-fill prompt when navigated from Explore "Send Prompt".
  try {
    const raw = sessionStorage.getItem('oj-prefill-prompt');
    if (raw) {
      sessionStorage.removeItem('oj-prefill-prompt');
      const prefill = JSON.parse(raw);
      const positive = String(prefill.positive || '').trim();
      if (positive && topbarPositiveInputEl) {
        topbarPositiveInputEl.value = positive;
        updateSendButtonState();
      }
    }
  } catch { /* ignore */ }

  // Focus button listener
  if (focusModeBtn) {
    focusModeBtn.addEventListener('click', () => {
      focusModeActive = !focusModeActive;
      document.body.classList.toggle('focus-mode', focusModeActive);
      applyRightSidebarCollapsedUi(focusModeActive);
      const promptBar = document.querySelector('.create-prompt-bar');
      if (promptBar) promptBar.style.display = focusModeActive ? 'none' : '';
      const metaPromptCols = document.querySelectorAll('.client-meta-prompt-col');
      metaPromptCols.forEach(col => col.style.display = focusModeActive ? 'none' : '');
      focusModeBtn.setAttribute('aria-pressed', focusModeActive ? 'true' : 'false');
      focusModeBtn.classList.toggle('active', focusModeActive);
      copyModalContentToPanels();
      switchToPanels(null);
      try {
        localStorage.setItem(FOCUS_MODE_KEY, focusModeActive ? '1' : '0');
      } catch { /* ignore */ }
    });
  }
  if (openNewModalBtn) {
    openNewModalBtn.addEventListener('click', () => {
      if (focusModeActive) {
        switchToPanels('new');
      } else {
        setNewModalOpen(true);
      }
    });
  }
  if (openBrainModalBtn) {
  openBrainModalBtn.addEventListener('click', () => {
    if (focusModeActive) {
      switchToPanels('brain');
    } else {
      setBrainModalOpen(true);
    }
  });
}

})();