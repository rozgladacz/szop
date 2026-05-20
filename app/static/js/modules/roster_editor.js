(function initSZOPRosterEditorModule(globalScope) {
  const textParsing = globalScope.SZOPTextParsing || (typeof globalThis !== 'undefined' ? globalThis.SZOPTextParsing : null) || {};
  const rosterRendering = globalScope.SZOPRosterRendering || (typeof globalThis !== 'undefined' ? globalThis.SZOPRosterRendering : null) || {};
  const loadoutStateApi = globalScope.SZOPLoadoutState || (typeof globalThis !== 'undefined' ? globalThis.SZOPLoadoutState : null) || {};
  const editorRenderers = globalScope.SZOPEditorRenderers || (typeof globalThis !== 'undefined' ? globalThis.SZOPEditorRenderers : null) || {};
  const rosterAddersApi = globalScope.SZOPRosterAdders || (typeof globalThis !== 'undefined' ? globalThis.SZOPRosterAdders : null) || {};
  const refreshPriority = globalScope.SZOPRefreshPriority || (typeof globalThis !== 'undefined' ? globalThis.SZOPRefreshPriority : null) || {};

  const splitTraits = textParsing.splitTraits || globalScope.splitTraits;
  const normalizeName = textParsing.normalizeName || globalScope.normalizeName;
  const extractNumber = textParsing.extractNumber || globalScope.extractNumber;
  const abilityIdentifier = textParsing.abilityIdentifier || globalScope.abilityIdentifier;
  const passiveIdentifier = textParsing.passiveIdentifier || globalScope.passiveIdentifier;
  const parseFlagString = textParsing.parseFlagString || globalScope.parseFlagString;
  const normalizeRangeValue = textParsing.normalizeRangeValue || globalScope.normalizeRangeValue;
  const stripOptionalFlagSuffix = textParsing.stripOptionalFlagSuffix || globalScope.stripOptionalFlagSuffix;

  const formatPoints = rosterRendering.formatPoints || globalScope.formatPoints;
  const createRosterItemElement = rosterRendering.createRosterItemElement || globalScope.createRosterItemElement;
  const renderPassiveEditor = rosterRendering.renderPassiveEditor || globalScope.renderPassiveEditor;

  const normalizeLoadoutKey = loadoutStateApi.normalizeLoadoutKey || globalScope.normalizeLoadoutKey;
  const resolveLoadoutEntryKey = loadoutStateApi.resolveLoadoutEntryKey || globalScope.resolveLoadoutEntryKey;
  const createLoadoutState = loadoutStateApi.createLoadoutState || globalScope.createLoadoutState;
  const cloneLoadoutState = loadoutStateApi.cloneLoadoutState || globalScope.cloneLoadoutState;
  const serializeLoadoutState = loadoutStateApi.serializeLoadoutState || globalScope.serializeLoadoutState;
  const ensureStateEntries = loadoutStateApi.ensureStateEntries || globalScope.ensureStateEntries;
  const ensureBaseStateEntries = loadoutStateApi.ensureBaseStateEntries || globalScope.ensureBaseStateEntries;
  const ensureBaseLabelEntries = loadoutStateApi.ensureBaseLabelEntries || globalScope.ensureBaseLabelEntries;
  const ensurePassiveStateEntries = loadoutStateApi.ensurePassiveStateEntries || globalScope.ensurePassiveStateEntries;
  const formatAbilityDisplayLabel = loadoutStateApi.formatAbilityDisplayLabel || globalScope.formatAbilityDisplayLabel;
  const normalizeLoadoutMode = loadoutStateApi.normalizeLoadoutMode || globalScope.normalizeLoadoutMode;
  const formatLoadoutCostLabel = loadoutStateApi.formatLoadoutCostLabel || globalScope.formatLoadoutCostLabel;
  const createModeIndicator = loadoutStateApi.createModeIndicator || globalScope.createModeIndicator;

  const renderAbilityEditor = editorRenderers.renderAbilityEditor || globalScope.renderAbilityEditor;
  const toggleSectionVisibility = editorRenderers.toggleSectionVisibility || globalScope.toggleSectionVisibility;
  const renderWeaponEditor = editorRenderers.renderWeaponEditor || globalScope.renderWeaponEditor;

  const initRosterAdders = rosterAddersApi.initRosterAdders || globalScope.initRosterAdders;

  const normalizeRosterRefreshCycleToken = refreshPriority.normalizeRosterRefreshCycleToken || globalScope.normalizeRosterRefreshCycleToken;
  const resolveRosterRefreshPriority = refreshPriority.resolveRosterRefreshPriority || globalScope.resolveRosterRefreshPriority;

  const payloadAdapters = globalScope.SZOPPayloadAdapters || {
    adaptQuotePayload(payload, requestedRosterUnitId) {
      const selectedTotal = Number(payload?.selected_total);
      const responseRosterUnitId = payload?.roster_unit_id ?? payload?.unit_id ?? requestedRosterUnitId;
      return {
        total: selectedTotal,
        rosterUnitId: responseRosterUnitId !== undefined && responseRosterUnitId !== null
          ? String(responseRosterUnitId)
          : String(requestedRosterUnitId || ''),
        loadout: payload?.loadout && typeof payload.loadout === 'object' ? payload.loadout : null,
        itemCosts: payload?.item_costs && typeof payload.item_costs === 'object' ? payload.item_costs : null,
        selectedRole: typeof payload?.selected_role === 'string' ? payload.selected_role : null,
      };
    },
    adaptItemCosts(itemCosts) {
      return itemCosts && typeof itemCosts === 'object' ? itemCosts : null;
    },
    adaptWeaponOptions(options) {
      return Array.isArray(options) ? options : [];
    },
    adaptAbilityEntries(entries) {
      return Array.isArray(entries) ? entries : [];
    },
  };
// ============================================================
// SECTION: ROSTER EDITOR CLOSURE
// initRosterEditor — wielkie domknięcie (~2000 linii).
// Zawiera ~60 prywatnych funkcji współdzielących stan przez closure-scope:
//   loadoutState, activeItem, refreshRosterCostBadgesInProgress,
//   pendingRefreshOptions, lastQuoteItemCosts, itp.
// Kluczowe podfunkcje:
//   handleStateChange, renderEditors, refreshRosterCostBadges,
//   fetchRosterUnitQuote, applyServerUpdate, selectItem
// UWAGA: include_item_costs=false dla badge-only calls (refreshRosterCostBadges),
//        include_item_costs=true tylko dla quote aktywnego oddziału (handleStateChange).
// ============================================================
function initRosterEditor() {
  const root = document.querySelector('[data-roster-root]');
  if (!root) {
    return;
  }
  initRosterAdders(root);
  const rosterId = root.dataset.rosterId || '';
  const editor = root.querySelector('[data-roster-editor]');
  const emptyState = root.querySelector('[data-roster-editor-empty]');
  const nameEl = root.querySelector('[data-roster-editor-name]');
  const statsEl = root.querySelector('[data-roster-editor-stats]');
  const passiveContainer = root.querySelector('[data-roster-editor-passives]');
  const activeContainer = root.querySelector('[data-roster-editor-actives]');
  const auraContainer = root.querySelector('[data-roster-editor-auras]');
  const loadoutContainer = root.querySelector('[data-roster-editor-loadout]');
  const form = root.querySelector('[data-roster-editor-form]');
  const duplicateForm = root.querySelector('[data-roster-editor-duplicate]');
  const deleteForm = root.querySelector('[data-roster-editor-delete]');
  if (deleteForm) {
    deleteForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!confirm('Usunąć pozycję?')) return;
      const action = deleteForm.getAttribute('action');
      if (!action) return;
      try {
        const response = await fetch(action, {
          method: 'POST',
          headers: { accept: 'application/json' },
        });
        if (!response.ok) {
          window.location.href = action;
          return;
        }
        const data = await response.json();
        const deletedId = String(data.deleted_roster_unit_id || '');
        if (deletedId) {
          const listElement = rosterListEl || root.querySelector('[data-roster-list]');
          if (listElement) {
            const item = listElement.querySelector(`[data-roster-unit-id="${deletedId}"]`);
            if (item) {
              const entry = item.closest('[data-roster-entry]');
              (entry || item).remove();
            }
          }
        }
        if (activeItem && activeItem.getAttribute('data-roster-unit-id') === deletedId) {
          activeItem = null;
          loadoutState = null;
          const editorEl = root.querySelector('[data-roster-editor]');
          const emptyEl = root.querySelector('[data-roster-editor-empty]');
          const actionsEl = root.querySelector('[data-roster-editor-actions]');
          if (editorEl) editorEl.classList.add('d-none');
          if (emptyEl) emptyEl.classList.remove('d-none');
          if (actionsEl) actionsEl.classList.add('d-none');
        }
        if (Number.isFinite(data.total_cost)) {
          updateTotalSummary(data.total_cost);
        }
        refreshRosterCountDisplay();
      } catch (err) {
        console.error('Błąd usuwania oddziału', err);
        window.location.href = action;
      }
    });
  }
  const editorActions = root.querySelector('[data-roster-editor-actions]');
  const countInput = root.querySelector('[data-roster-editor-count]');
  const customNameInput = root.querySelector('[data-roster-editor-custom-name]');
  const customLabel = root.querySelector('[data-roster-editor-custom-label]');
  const roleEl = root.querySelector('[data-roster-editor-role]');
  const loadoutInput = root.querySelector('[data-roster-editor-loadout-input]');
  const costValueEl = root.querySelector('[data-roster-editor-cost]');
  const costBadgeEl = root.querySelector('[data-roster-editor-cost-badge]');
  const saveStateEl = root.querySelector('[data-roster-editor-save-state]');
  const totalContainer = root.querySelector('[data-roster-total-container]');
  const totalValueEl = root.querySelector('[data-roster-total]');
  const isEditable = Boolean(form && countInput && loadoutInput);
  const listWrapper = root.querySelector('[data-roster-items-container]') || null;
  let rosterListEl = root.querySelector('[data-roster-list]');
  const items = [];
  const itemRegistry = new WeakSet();
  const moveFormRegistry = new WeakSet();
  let refreshRosterCostBadgesInProgress = false;
  let pendingRefreshOptions = null;
  let pendingRefreshCycleToken = null;
  let lastRefreshRosterCostCycleToken = null;
  let refreshCycleVersion = 0;
  let latestAppliedRefreshVersion = 0;
  let latestAuthoritativeRefreshVersion = 0;
  let rosterRefreshCycleCounter = 0;
  let quoteRefreshTimer = null;
  let activeQuoteController = null;
  let quoteRequestVersion = 0;
  let lastQuoteItemCosts = null;
  const unitItemCostsCache = new Map();
  let lastSelectedRole = null;
  let skipCostDisplayLoading = false;

  function nextRefreshVersion(seedVersion = null) {
    const seed = Number(seedVersion);
    const next = Number.isFinite(seed)
      ? Math.max(seed, latestEditVersion, refreshCycleVersion + 1)
      : Math.max(latestEditVersion, refreshCycleVersion + 1);
    refreshCycleVersion = next;
    return next;
  }

  function applyRefreshPriority(cycleToken) {
    const decision = resolveRosterRefreshPriority(
      {
        latestAppliedVersion: latestAppliedRefreshVersion,
        latestAuthoritativeVersion: latestAuthoritativeRefreshVersion,
      },
      cycleToken,
    );
    latestAppliedRefreshVersion = decision.state.latestAppliedVersion;
    latestAuthoritativeRefreshVersion = decision.state.latestAuthoritativeVersion;
    return decision;
  }
  function ensureRosterList() {
    if (rosterListEl && rosterListEl.isConnected) {
      return rosterListEl;
    }
    rosterListEl = root.querySelector('[data-roster-list]');
    if (rosterListEl) {
      return rosterListEl;
    }
    if (!listWrapper) {
      return null;
    }
    const listElement = document.createElement('div');
    listElement.className = 'list-group roster-unit-list';
    listElement.setAttribute('data-roster-list', '');
    listWrapper.appendChild(listElement);
    rosterListEl = listElement;
    return rosterListEl;
  }

  function removeEmptyPlaceholder() {
    if (!listWrapper) {
      return;
    }
    const placeholder = listWrapper.querySelector('[data-roster-empty]');
    if (placeholder) {
      placeholder.remove();
    }
  }

  function getEntryElementFromItem(item) {
    return item ? item.closest('.roster-unit-entry') : null;
  }

  function getListItemContainer(entry) {
    if (!entry) {
      return null;
    }
    const rosterContainer = entry.closest('[data-roster-entry]');
    if (rosterContainer) {
      return rosterContainer;
    }
    return entry.closest('.list-group-item');
  }

  function getEntryContainers(listElement = null) {
    const targetList = listElement || rosterListEl || ensureRosterList();
    if (!targetList) {
      return [];
    }
    return Array.from(targetList.querySelectorAll('[data-roster-entry]'));
  }

  function getItemElementFromEntry(entry) {
    return entry ? entry.querySelector('[data-roster-item]') : null;
  }

  function getUnitIdFromEntry(entry) {
    const item = getItemElementFromEntry(entry);
    return item ? item.getAttribute('data-roster-unit-id') || '' : '';
  }

  function getRosterOrder(listElement = null) {
    const containers = getEntryContainers(listElement);
    return containers
      .map((entry) => getUnitIdFromEntry(entry))
      .filter((unitId) => unitId);
  }

  function reorderEntriesFromPayload(orderPayload) {
    const listElement = rosterListEl || ensureRosterList();
    if (!listElement || !Array.isArray(orderPayload)) {
      return null;
    }
    const normalizedOrder = orderPayload
      .map((entry, index) => {
        if (!entry || typeof entry !== 'object') {
          return null;
        }
        const id = normalizeRosterUnitId(entry.id ?? entry.roster_unit_id ?? entry.rosterUnitId);
        if (!id) {
          return null;
        }
        const position =
          typeof entry.position === 'number' && Number.isFinite(entry.position)
            ? entry.position
            : index;
        return { id, position, index };
      })
      .filter(Boolean);
    if (!normalizedOrder.length) {
      return null;
    }
    const orderMap = new Map(
      normalizedOrder.map((entry) => [entry.id, { position: entry.position, index: entry.index }]),
    );
    const entries = getEntryContainers(listElement);
    if (!entries.length) {
      return listElement;
    }
    const sorted = entries
      .map((entry, index) => {
        const unitId = getUnitIdFromEntry(entry);
        const orderEntry = unitId ? orderMap.get(unitId) : null;
        const sortValue = orderEntry
          ? orderEntry.position * 1000 + orderEntry.index
          : Number.MAX_SAFE_INTEGER + index;
        return { entry, sortValue, index };
      })
      .sort((a, b) => a.sortValue - b.sortValue || a.index - b.index);
    sorted.forEach(({ entry }) => listElement.appendChild(entry));
    return listElement;
  }

  async function persistRosterOrder(orderPayload = null) {
    if (!isEditable || !rosterId) {
      return;
    }
    let orderList = null;
    if (Array.isArray(orderPayload)) {
      orderList = orderPayload
        .map((entry) => {
          if (entry && typeof entry === 'object') {
            return (
              entry.id
              ?? entry.roster_unit_id
              ?? entry.rosterUnitId
              ?? entry
            );
          }
          return entry;
        })
        .filter((value) => value !== undefined && value !== null);
    }
    if (!Array.isArray(orderList) || orderList.length === 0) {
      orderList = getRosterOrder();
    }
    if (!Array.isArray(orderList) || orderList.length === 0) {
      return;
    }
    try {
      const response = await fetch(`/rosters/${rosterId}/units/reorder`, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ order: orderList }),
      });
      if (!response.ok) {
        return;
      }
      const contentType = (response.headers.get('content-type') || '').toLowerCase();
      if (!contentType.includes('application/json')) {
        return;
      }
      const data = await response.json();
      if (Array.isArray(data.order)) {
        const listElement = reorderEntriesFromPayload(data.order);
        if (listElement) {
          updateMoveButtonStates(listElement);
        }
      }
    } catch (error) {
      console.warn('Nie udało się zapisać kolejności oddziałów', error);
    }
  }


  function findMoveForm(entry, direction) {
    const normalized = String(direction || '').trim().toLowerCase();
    const forms = entry ? Array.from(entry.querySelectorAll('[data-roster-move-form]')) : [];
    return forms.find((form) => {
      const dirInput = form ? form.querySelector('input[name="direction"]') : null;
      const value = dirInput ? String(dirInput.value || '').trim().toLowerCase() : '';
      return value === normalized;
    });
  }

  async function submitMoveRequest(form, options = {}) {
    const { moveDom = true, preserveSelection = true } = options;
    if (!form) {
      return;
    }
    const action = form.getAttribute('action') || '';
    if (!action) {
      return;
    }
    const payload = new FormData(form);
    const directionInput = form.querySelector('input[name="direction"]');
    const direction = directionInput ? String(directionInput.value || '') : '';
    const entry = form.closest('.roster-unit-entry');
    const headers = new Headers({ Accept: 'application/json' });
    const selectedItem =
      preserveSelection && activeItem
        ? activeItem
        : preserveSelection && entry
          ? entry.querySelector('[data-roster-item]')
          : null;
    const fallback = (reason = null) => {
      console.warn('Nie udało się przesunąć oddziału, wysyłam formularz ponownie.', reason);
      if (form && typeof form.submit === 'function') {
        form.submit();
        return;
      }
      window.location.reload();
    };
    let response;
    try {
      response = await fetch(action, {
        method: 'POST',
        body: payload,
        credentials: 'same-origin',
        headers,
      });
    } catch (err) {
      fallback(err);
      return;
    }
    const isRedirectResponse =
      response.redirected
      || response.type === 'opaqueredirect'
      || (response.status >= 300 && response.status < 400);
    if (!isRedirectResponse && response.status >= 400) {
      fallback(`response status: ${response.status}`);
      return;
    }
    const contentType = (response.headers && response.headers.get('content-type')) || '';
    const isJsonResponse = contentType.toLowerCase().includes('application/json');
    let responseData = null;
    if (isJsonResponse) {
      try {
        responseData = await response.json();
      } catch (err) {
        console.warn('Nie udało się odczytać odpowiedzi JSON', err);
      }
    }
    if (moveDom === false) {
      return;
    }
    if (!entry || (direction !== 'up' && direction !== 'down')) {
      return;
    }
    const preferredSelectionId = normalizeRosterUnitId(
      responseData
        ? responseData.selected ?? responseData.selected_id ?? responseData.selectedId
        : null,
    );
    const listElement =
      reorderEntriesFromPayload(responseData && responseData.order)
      || entry.closest('[data-roster-list]')
      || rosterListEl;
    if (!responseData || !Array.isArray(responseData.order) || responseData.order.length === 0) {
      moveEntryDom(entry, direction);
    }
    if (listElement) {
      updateMoveButtonStates(listElement);
    }
    const currentOrder = Array.isArray(responseData && responseData.order)
      ? responseData.order
      : getRosterOrder(listElement);
    persistRosterOrder(currentOrder);
    if (preserveSelection) {
      const preferredItem = preferredSelectionId
        ? root.querySelector(`[data-roster-item][data-roster-unit-id="${preferredSelectionId}"]`)
        : null;
      const nextSelection =
        preferredItem && preferredItem.isConnected
          ? preferredItem
          : selectedItem && selectedItem.isConnected
            ? selectedItem
            : null;
      if (nextSelection) {
        if (activeItem && activeItem !== nextSelection) {
          activeItem.classList.remove('active');
        }
        activeItem = nextSelection;
        activeItem.classList.add('active');
      }
    }
  }

  function findSiblingEntryContainer(container, direction) {
    if (container && !container.hasAttribute('data-roster-entry')) {
      const entryContainer = container.closest('[data-roster-entry]');
      if (entryContainer) {
        container = entryContainer;
      }
    }
    const step = direction === 'up' ? 'previousElementSibling' : 'nextElementSibling';
    let sibling = container ? container[step] : null;
    while (sibling && !sibling.hasAttribute('data-roster-entry')) {
      sibling = sibling[step];
    }
    return sibling;
  }

  function moveEntryDom(entry, direction) {
    const container = getListItemContainer(entry) || entry && entry.closest('[data-roster-entry]');
    if (!container || !container.parentElement) {
      return false;
    }
    const parent = container.parentElement;
    if (direction === 'up') {
      const previous = findSiblingEntryContainer(container, 'up');
      if (!previous) {
        return false;
      }
      parent.insertBefore(container, previous);
      return true;
    }
    if (direction === 'down') {
      const next = findSiblingEntryContainer(container, 'down');
      if (!next) {
        return false;
      }
      parent.insertBefore(next, container);
      parent.insertBefore(container, next.nextSibling);
      return true;
    }
    return false;
  }

  function updateMoveButtonStates(listElement) {
    if (!isEditable || !listElement) {
      return;
    }
    const entries = Array.from(listElement.querySelectorAll('.roster-unit-entry'));
    const lastIndex = entries.length - 1;
    entries.forEach((entry, index) => {
      entry.querySelectorAll('[data-roster-move-form]').forEach((form) => {
        const directionInput = form.querySelector('input[name="direction"]');
        const button = form.querySelector('[data-roster-move]');
        if (!button) {
          return;
        }
        const direction = directionInput ? String(directionInput.value || '') : '';
        if (direction === 'up') {
          button.disabled = index === 0;
        } else if (direction === 'down') {
          button.disabled = index === lastIndex;
        }
      });
    });
  }

  function registerMoveForm(form) {
    if (!form || moveFormRegistry.has(form)) {
      return;
    }
    moveFormRegistry.add(form);
    let isSubmitting = false;
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (isSubmitting) {
        return;
      }
      isSubmitting = true;
      try {
        await submitMoveRequest(form, { preserveSelection: true });
      } finally {
        isSubmitting = false;
      }
    });
  }

  function initializeMoveForms() {
    root.querySelectorAll('[data-roster-move-form]').forEach((form) => {
      registerMoveForm(form);
    });
  }

  function registerRosterItem(item) {
    if (!item || itemRegistry.has(item)) {
      return;
    }
    itemRegistry.add(item);
    items.push(item);
    item.addEventListener('click', () => {
      selectItem(item);
    });
    item.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectItem(item);
      }
    });
    const entry = item.closest('.roster-unit-entry');
    if (entry) {
      entry.querySelectorAll('[data-roster-move]').forEach((button) => {
        button.addEventListener('click', (event) => {
          event.stopPropagation();
        });
      });
      entry.querySelectorAll('[data-roster-move-form]').forEach((form) => {
        form.addEventListener('click', (event) => {
          event.stopPropagation();
        });
        registerMoveForm(form);
      });
    }
    const listElement = item.closest('[data-roster-list]') || rosterListEl;
    if (listElement) {
      rosterListEl = listElement;
      updateMoveButtonStates(listElement);
    }
  }

  root.addEventListener('roster:add-unit-success', (event) => {
    if (!event || !event.detail) {
      return;
    }
    const { payload } = event.detail;
    if (!payload || typeof payload !== 'object') {
      return;
    }
    const itemData = payload.roster_item || payload.item;
    if (!itemData || typeof itemData !== 'object') {
      return;
    }
    const listElement = ensureRosterList();
    if (!listElement) {
      return;
    }
    removeEmptyPlaceholder();
    const listItemElement = createRosterItemElement(itemData, {
      rosterId,
      isEditable,
    });
    if (!listItemElement) {
      return;
    }
    listElement.appendChild(listItemElement);
    const rosterItemElement = listItemElement.querySelector('[data-roster-item]');
    if (rosterItemElement) {
      registerRosterItem(rosterItemElement);
    }
    applyServerUpdate(payload);
    refreshRosterCountDisplay();
    if (rosterItemElement) {
      selectItem(rosterItemElement);
      if (typeof listItemElement.scrollIntoView === 'function') {
        listItemElement.scrollIntoView({ block: 'nearest' });
      }
    }
    updateMoveButtonStates(listElement);
  });

  let activeItem = null;
  let loadoutState = createLoadoutState({});
  let currentCount = 1;
  let currentWeapons = [];
  let currentActives = [];
  let currentAuras = [];
  let currentPassives = [];
  let currentBaseFlags = {};
  let currentQuality = 4;
  let currentWeaponCostMap = new Map();
  let baseCostPerModel = 0;
  let currentCustomName = '';
  let customEditInput = null;
  let autoSaveEnabled = false;
  let ignoreNextSave = false;
  let suppressNextBadgeRefresh = false;
  let saveTimer = null;
  let isSaving = false;
  let pendingSave = false;
  let pendingSaveVersion = null;
  let latestEditVersion = 0;
  let latestRequestVersion = 0;
  let activeSaveController = null;
  const SAVE_MESSAGES = {
    idle: '',
    dirty: 'Niezapisane zmiany',
    saving: 'Zapisywanie...',
    saved: 'Zapisano',
    error: 'Błąd zapisu',
  };
  let currentSaveStatus = 'idle';
  const customPlaceholder = customLabel ? customLabel.dataset.placeholder || '' : '';
  let rosterDatasetCache = new WeakMap();
  const UNIT_DATASET_KEYS = [
    'weapon_options',
    'passive_items',
    'active_items',
    'aura_items',
    'default_summary',
  ];
  const UNIT_DATASET_ATTRIBUTE_MAP = new Map([
    ['data-weapon-options', 'weapon_options'],
    ['data-passives', 'passive_items'],
    ['data-actives', 'active_items'],
    ['data-auras', 'aura_items'],
    ['data-default-summary', 'default_summary'],
  ]);
  const rosterUnitDatasetRepo = new Map();
  const rosterUnitDatasetCache = new Map();

  function resetRosterCaches() {
    rosterDatasetCache = new WeakMap();
    rosterUnitDatasetCache.clear();
    rosterUnitDatasetRepo.clear();
  }

  function safeParseJson(value, fallback, warningLabel = 'Nie udało się odczytać danych') {
    if (!value) {
      return fallback;
    }
    try {
      return JSON.parse(value);
    } catch (err) {
      console.warn(warningLabel, err);
      return fallback;
    }
  }

  function normalizeRosterUnitId(value) {
    if (value === null || value === undefined) {
      return null;
    }
    const text = String(value).trim();
    return text || null;
  }

  function initializeUnitDatasetRepo() {
    const raw = root.dataset ? root.dataset.rosterUnitDatasets || '' : '';
    if (raw) {
      const parsed = safeParseJson(raw, {}, 'Nie udało się odczytać danych jednostek');
      if (parsed && typeof parsed === 'object') {
        Object.entries(parsed).forEach(([unitId, value]) => {
          if (!unitId || !value || typeof value !== 'object') {
            return;
          }
          const normalizedValue = {};
          UNIT_DATASET_KEYS.forEach((key) => {
            if (Object.prototype.hasOwnProperty.call(value, key)) {
              normalizedValue[key] = adaptUnitDatasetValue(key, value[key], `initial_dataset.${key}`);
            }
          });
          rosterUnitDatasetRepo.set(String(unitId), normalizedValue);
        });
      } else {
        console.warn('Nieprawidłowy format danych jednostek, używam wartości domyślnych.');
      }
    }
    if (root.dataset && Object.prototype.hasOwnProperty.call(root.dataset, 'rosterUnitDatasets')) {
      delete root.dataset.rosterUnitDatasets;
    }
  }

  function setSaveStatus(status) {
    currentSaveStatus = status;
    if (!saveStateEl) {
      return;
    }
    const message = SAVE_MESSAGES[status] ?? '';
    saveStateEl.textContent = message;
    saveStateEl.classList.remove('text-success', 'text-danger');
    if (status === 'saved') {
      saveStateEl.classList.add('text-success');
    } else if (status === 'error') {
      saveStateEl.classList.add('text-danger');
    }
  }

  function cancelPendingSave() {
    if (saveTimer) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
    }
    pendingSave = false;
  }

  function parseList(value) {
    const parsed = safeParseJson(value, [], 'Nie udało się odczytać danych oddziału');
    return Array.isArray(parsed) ? parsed : [];
  }

  function parseLoadout(value) {
    const parsed = safeParseJson(value, {}, 'Nie udało się odczytać konfiguracji oddziału');
    return parsed && typeof parsed === 'object' ? parsed : {};
  }

  function parseJsonValue(value, warningLabel = 'Nie udało się odczytać danych', fallback = null) {
    const parsed = safeParseJson(value, fallback, warningLabel);
    return parsed === undefined ? fallback : parsed;
  }

  function resolveUnitCacheId(source) {
    if (source === null || source === undefined) {
      return '';
    }
    if (typeof source === 'string' || typeof source === 'number') {
      const text = String(source).trim();
      return text ? text : '';
    }
    if (source instanceof Element) {
      return source.getAttribute('data-unit-cache-id') || '';
    }
    return '';
  }

  function getUnitDatasetEntry(source) {
    const cacheId = resolveUnitCacheId(source);
    if (!cacheId) {
      return null;
    }
    let entry = rosterUnitDatasetCache.get(cacheId);
    if (!entry) {
      entry = {
        data: rosterUnitDatasetRepo.get(cacheId) || null,
        values: new Map(),
      };
      rosterUnitDatasetCache.set(cacheId, entry);
    }
    return entry;
  }

  function getUnitDatasetValue(source, datasetKey, fallback = null) {
    const cacheId = resolveUnitCacheId(source);
    if (!cacheId || !datasetKey) {
      return fallback;
    }
    const entry = getUnitDatasetEntry(cacheId);
    if (!entry || !entry.data) {
      return fallback;
    }
    if (entry.values.has(datasetKey)) {
      const cached = entry.values.get(datasetKey);
      return cached === undefined ? fallback : cached;
    }
    const value = entry.data[datasetKey];
    entry.values.set(datasetKey, value);
    return value === undefined ? fallback : value;
  }

  function getUnitDatasetList(source, datasetKey) {
    const value = getUnitDatasetValue(source, datasetKey, []);
    return Array.isArray(value) ? value : [];
  }

  function adaptUnitDatasetValue(datasetKey, value, moduleName) {
    if (datasetKey === 'weapon_options') {
      return payloadAdapters.adaptWeaponOptions(value, moduleName);
    }
    if (datasetKey === 'passive_items') {
      return payloadAdapters.adaptAbilityEntries(value, 'passive', moduleName);
    }
    if (datasetKey === 'active_items') {
      return payloadAdapters.adaptAbilityEntries(value, 'active', moduleName);
    }
    if (datasetKey === 'aura_items') {
      return payloadAdapters.adaptAbilityEntries(value, 'aura', moduleName);
    }
    return value;
  }

  function updateUnitDataset(source, updates) {
    const cacheId = resolveUnitCacheId(source);
    if (!cacheId || !updates || typeof updates !== 'object') {
      return;
    }
    const normalizedUpdates = {};
    UNIT_DATASET_KEYS.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(updates, key)) {
        const value = updates[key];
        if (value !== undefined) {
          normalizedUpdates[key] = adaptUnitDatasetValue(key, value, `unit_dataset.${key}`);
        }
      }
    });
    const updateKeys = Object.keys(normalizedUpdates);
    if (!updateKeys.length) {
      return;
    }
    const previous = rosterUnitDatasetRepo.get(cacheId);
    const next = previous && typeof previous === 'object' ? { ...previous } : {};
    updateKeys.forEach((key) => {
      next[key] = normalizedUpdates[key];
    });
    rosterUnitDatasetRepo.set(cacheId, next);
    rosterUnitDatasetCache.delete(cacheId);
  }

  function getCacheEntry(item, attribute, rawValue) {
    if (!item || !attribute) {
      return null;
    }
    let cache = rosterDatasetCache.get(item);
    if (!cache) {
      cache = new Map();
      rosterDatasetCache.set(item, cache);
    }
    let entry = cache.get(attribute);
    if (!entry || entry.raw !== rawValue) {
      entry = { raw: rawValue, list: undefined, objects: new Map() };
      cache.set(attribute, entry);
    }
    return entry;
  }

  function invalidateCachedAttribute(item, attribute) {
    if (!item || !attribute) {
      return;
    }
    const cache = rosterDatasetCache.get(item);
    if (!cache) {
      return;
    }
    cache.delete(attribute);
    if (cache.size === 0) {
      rosterDatasetCache.delete(item);
    }
  }

  function getParsedList(item, attribute) {
    if (!item || !attribute) {
      return [];
    }
    const datasetKey = UNIT_DATASET_ATTRIBUTE_MAP.get(attribute);
    if (datasetKey) {
      const cacheId = resolveUnitCacheId(item);
      if (cacheId) {
        return getUnitDatasetList(cacheId, datasetKey);
      }
    }
    const rawValue = item.getAttribute(attribute) || '';
    const entry = getCacheEntry(item, attribute, rawValue);
    if (!entry) {
      return parseList(rawValue);
    }
    if (entry.list !== undefined) {
      return entry.list;
    }
    const parsed = parseList(rawValue);
    entry.list = parsed;
    return parsed;
  }

  function getParsedObject(item, attribute, parser = parseJsonValue) {
    if (!item || !attribute) {
      return parser ? parser('') : null;
    }
    const rawValue = item.getAttribute(attribute) || '';
    const entry = getCacheEntry(item, attribute, rawValue);
    if (!entry) {
      return parser ? parser(rawValue) : null;
    }
    const parserKey = parser || '__default__';
    if (entry.objects.has(parserKey)) {
      return entry.objects.get(parserKey);
    }
    const parsed = parser ? parser(rawValue) : null;
    entry.objects.set(parserKey, parsed);
    return parsed;
  }

  function showRosterEditorError(message) {
    if (editor) {
      editor.classList.remove('d-none');
    }
    if (editorActions) {
      editorActions.classList.add('d-none');
    }
    if (!emptyState) {
      return;
    }
    emptyState.classList.remove('d-none');
    let target = emptyState.querySelector('[data-roster-editor-error]');
    if (!target) {
      target = document.createElement('div');
      target.dataset.rosterEditorError = '';
      target.className = 'text-danger mt-2';
      emptyState.appendChild(target);
    }
    target.textContent = message || 'Panel edycji jest obecnie niedostępny.';
  }

  function updateCustomLabelDisplay(value) {
    if (!customLabel) {
      return;
    }
    const text = value ? String(value) : customPlaceholder;
    customLabel.textContent = text;
    if (customPlaceholder) {
      const showPlaceholder = !value;
      customLabel.classList.toggle('text-opacity-50', showPlaceholder);
      customLabel.classList.toggle('fst-italic', showPlaceholder);
    }
  }

  function updateListCustomName(item, value) {
    if (!item) {
      return;
    }
    const customEl = item.querySelector('[data-roster-unit-custom]');
    if (!customEl) {
      return;
    }
    if (value) {
      customEl.textContent = value;
      customEl.classList.remove('d-none');
    } else {
      customEl.textContent = '';
      customEl.classList.add('d-none');
    }
  }

  function setCustomName(rawValue, options = {}) {
    const trimmed = (rawValue || '').trim();
    const previous = currentCustomName;
    currentCustomName = trimmed;
    if (customNameInput) {
      customNameInput.value = trimmed;
    }
    if (!customEditInput) {
      updateCustomLabelDisplay(trimmed);
    }
    if (options.updateActiveItem !== false && activeItem) {
      activeItem.setAttribute('data-unit-custom-name', trimmed);
    }
    if (options.updateList !== false && activeItem) {
      updateListCustomName(activeItem, trimmed);
    }
    if (autoSaveEnabled && options.triggerSave !== false && trimmed !== previous) {
      setSaveStatus('dirty');
      scheduleSave();
    }
  }

  function startCustomInlineEdit() {
    if (!isEditable || !customLabel || customEditInput) {
      return;
    }
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'form-control form-control-sm';
    input.maxLength = 120;
    input.value = currentCustomName;
    customEditInput = input;
    customLabel.textContent = '';
    customLabel.appendChild(input);
    window.setTimeout(() => {
      input.focus();
      input.select();
    }, 0);
    const finish = (commit) => {
      if (!customEditInput) {
        return;
      }
      const nextValue = commit ? customEditInput.value : currentCustomName;
      customEditInput.remove();
      customEditInput = null;
      setCustomName(nextValue, {
        triggerSave: commit,
        updateActiveItem: true,
        updateList: true,
      });
    };
    input.addEventListener('blur', () => finish(true));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        finish(true);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        finish(false);
      }
    });
  }

  function normalizeLoadoutStateTotals(state, count) {
    if (!state || state.mode === 'total') {
      return;
    }
    const multiplier = Math.max(Number(count) || 0, 0);
    const convert = (map) => {
      if (!(map instanceof Map)) {
        return;
      }
      map.forEach((value, key) => {
        const numeric = Number(value);
        if (!Number.isFinite(numeric) || numeric <= 0) {
          map.set(key, 0);
          return;
        }
        map.set(key, numeric * multiplier);
      });
    };
    convert(state.weapons);
    convert(state.active);
    convert(state.aura);
    state.mode = 'total';
  }

  function hydrateLoadoutStateForItem(
    item,
    {
      count,
      weapons,
      activeItems,
      auraItems,
      passiveItems,
    },
  ) {
    const loadoutData = getParsedObject(item, 'data-loadout', parseLoadout);
    const hydratedLoadoutState = createLoadoutState(loadoutData);
    ensureStateEntries(hydratedLoadoutState.weapons, weapons, 'id', 'default_count', { fallbackIdKeys: ['weapon_id'] });
    ensureStateEntries(hydratedLoadoutState.active, activeItems, 'ability_id', 'default_count', { fallbackIdKeys: ['id'] });
    ensureStateEntries(hydratedLoadoutState.aura, auraItems, 'ability_id', 'default_count', { fallbackIdKeys: ['id'] });
    ensureBaseStateEntries(hydratedLoadoutState.baseActive, activeItems, 'ability_id', 'default_count', { fallbackIdKeys: ['id'] });
    ensureBaseStateEntries(hydratedLoadoutState.baseAura, auraItems, 'ability_id', 'default_count', { fallbackIdKeys: ['id'] });
    ensureBaseLabelEntries(hydratedLoadoutState.baseActiveLabels, activeItems, 'ability_id', { fallbackIdKeys: ['id'] });
    ensureBaseLabelEntries(hydratedLoadoutState.baseAuraLabels, auraItems, 'ability_id', { fallbackIdKeys: ['id'] });
    ensurePassiveStateEntries(hydratedLoadoutState.passive, passiveItems);
    normalizeLoadoutStateTotals(hydratedLoadoutState, count);
    return hydratedLoadoutState;
  }

  function syncDefaultEquipment(previousCount, nextCount) {
    if (!loadoutState) {
      return;
    }
    const prev = Math.max(Number(previousCount) || 0, 0);
    const next = Math.max(Number(nextCount) || 0, 0);
    if (prev === next) {
      return;
    }
    const adjust = (map, items, idKey, fallbackIdKeys = []) => {
      if (!(map instanceof Map)) {
        return;
      }
      const safeItems = Array.isArray(items) ? items : [];
      safeItems.forEach((item) => {
        if (!item) {
          return;
        }
        const key = resolveLoadoutEntryKey(item, idKey, fallbackIdKeys);
        if (!key) {
          return;
        }
        const defaultValue = Number(item.default_count ?? 0);
        if (!Number.isFinite(defaultValue) || defaultValue <= 0) {
          return;
        }
        const prevTotal = prev * defaultValue;
        const stored = Number(map.get(key));
        const diff = Number.isFinite(stored) ? stored - prevTotal : 0;
        const nextTotal = Math.max(next * defaultValue + diff, 0);
        map.set(key, nextTotal);
      });
    };
    adjust(loadoutState.weapons, currentWeapons, 'id', ['weapon_id']);
    adjust(loadoutState.active, currentActives, 'ability_id', ['id']);
    adjust(loadoutState.aura, currentAuras, 'ability_id', ['id']);
  }

  function updateTotalSummary(total) {
    if (!totalValueEl) {
      return;
    }
    totalValueEl.textContent = formatPoints(total);
  }

  function refreshRosterCountDisplay() {
    const framesEl = listWrapper && listWrapper.querySelector('[data-roster-frames-count]');
    const heroEl = listWrapper && listWrapper.querySelector('[data-roster-hero-count]');
    if (!framesEl && !heroEl) {
      return;
    }
    const listEl = rosterListEl || root.querySelector('[data-roster-list]');
    const allItems = listEl ? listEl.querySelectorAll('[data-roster-item]') : [];
    let framesCount = 0;
    let heroModelsCount = 0;
    allItems.forEach((item) => {
      const isAttached = item.hasAttribute('data-roster-attached-hero');
      const isHero = item.getAttribute('data-is-hero') === 'true';
      const count = Math.max(parseInt(item.getAttribute('data-unit-count') || '1', 10) || 1, 1);
      if (!isAttached) {
        framesCount += 1;
      }
      if (isHero) {
        heroModelsCount += count;
      }
    });
    if (framesEl) {
      framesEl.textContent = String(framesCount);
    }
    if (heroEl) {
      heroEl.textContent = String(heroModelsCount);
    }
  }

  function scheduleSave(requestVersion) {
    if (!isEditable || !form || !autoSaveEnabled) {
      return;
    }
    const version = typeof requestVersion === 'number' ? requestVersion : ++latestEditVersion;
    latestEditVersion = Math.max(latestEditVersion, version);
    if (saveTimer) {
      window.clearTimeout(saveTimer);
    }
    saveTimer = window.setTimeout(() => {
      saveTimer = null;
      if (isSaving) {
        pendingSave = true;
        pendingSaveVersion = Math.max(pendingSaveVersion ?? 0, version);
        if (activeSaveController) {
          activeSaveController.abort();
        }
        return;
      }
      setSaveStatus('saving');
      isSaving = true;
      latestRequestVersion = version;
      activeSaveController = new AbortController();
      submitChanges(version, activeSaveController.signal)
        .catch((error) => {
          if (error && error.name === 'AbortError') {
            return;
          }
          console.error('Nie udało się zapisać zmian oddziału', error);
          setSaveStatus('error');
        })
        .finally(() => {
          isSaving = false;
          activeSaveController = null;
          if (pendingSave) {
            pendingSave = false;
            const nextVersion =
              pendingSaveVersion && pendingSaveVersion > version ? pendingSaveVersion : latestEditVersion;
            pendingSaveVersion = null;
            scheduleSave(nextVersion);
          }
        });
    }, 400);
  }

  async function submitChanges(requestVersion, signal) {
    if (!form || !activeItem) {
      throw new Error('Brak aktywnego oddziału');
    }
    const action = form.getAttribute('action');
    if (!action) {
      throw new Error('Brak adresu zapisu');
    }
    const payload = new FormData(form);
    payload.set('count', String(currentCount));
    if (customNameInput) {
      payload.set('custom_name', customNameInput.value.trim());
    }
    if (loadoutInput) {
      payload.set('loadout_json', loadoutInput.value || '{}');
    }
    payload.set('request_id', String(requestVersion));
    const response = await fetch(action, {
      method: 'POST',
      body: payload,
      headers: { Accept: 'application/json' },
      signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const parsedRequestId = Number.isFinite(Number(data?.request_id)) ? Number(data.request_id) : requestVersion;
    if (
      parsedRequestId !== requestVersion ||
      parsedRequestId !== latestEditVersion ||
      parsedRequestId !== latestRequestVersion
    ) {
      return;
    }
    applyServerUpdate(data || {}, {
      version: parsedRequestId,
      authoritative: true,
      dedupeKey: `server:${parsedRequestId}`,
    });
    setSaveStatus('saved');
  }

  function setItemListAttribute(element, attribute, list) {
    if (!element) {
      return;
    }
    let safeList = Array.isArray(list) ? list : [];
    if (attribute === 'data-selected-passives') {
      safeList = payloadAdapters.adaptAbilityEntries(safeList, 'passive', 'selected.passive_items');
    } else if (attribute === 'data-selected-actives') {
      safeList = payloadAdapters.adaptAbilityEntries(safeList, 'active', 'selected.active_items');
    } else if (attribute === 'data-selected-auras') {
      safeList = payloadAdapters.adaptAbilityEntries(safeList, 'aura', 'selected.aura_items');
    }
    try {
      element.setAttribute(attribute, JSON.stringify(safeList));
    } catch (error) {
      element.setAttribute(attribute, '[]');
    }
    invalidateCachedAttribute(element, attribute);
  }

  function abilityBadgeLabel(entry) {
    if (!entry) {
      return '';
    }
    const base = entry.label ?? entry.raw ?? entry.slug ?? '';
    const custom = entry.custom_name ?? entry.customName ?? '';
    const trimmedCustom = typeof custom === 'string' ? custom.trim() : '';
    if (trimmedCustom) {
      return base ? `${trimmedCustom} [${base}]` : trimmedCustom;
    }
    return base;
  }

  function updateItemAbilityBadges(item, selections) {
    if (!item) {
      return;
    }
    const container = item.querySelector('[data-roster-unit-abilities]');
    if (!container) {
      return;
    }
    container.innerHTML = '';
    const config = [
      { key: 'passives', className: 'badge text-bg-secondary', showCount: false },
      { key: 'actives', className: 'badge text-bg-info text-dark', showCount: true },
      { key: 'auras', className: 'badge text-bg-warning text-dark', showCount: true },
    ];
    let hasContent = false;
    config.forEach(({ key, className, showCount }) => {
      const list = selections && Array.isArray(selections[key]) ? selections[key] : [];
      list.forEach((entry) => {
        if (!entry) {
          return;
        }
        const label = abilityBadgeLabel(entry);
        if (!label) {
          return;
        }
        const badge = document.createElement('span');
        badge.className = className;
        if (entry.description) {
          badge.title = entry.description;
        }
        let text = String(label);
        if (showCount) {
          const numeric = Number(entry.count);
          if (Number.isFinite(numeric) && numeric > 1) {
            text += ` ×${numeric}`;
          }
        }
        badge.textContent = text;
        container.appendChild(badge);
        hasContent = true;
      });
    });
    if (!hasContent) {
      const empty = document.createElement('span');
      empty.className = 'text-muted small';
      empty.textContent = 'Brak dodatkowych zdolności';
      container.appendChild(empty);
    }
  }

  function syncEditorFromItem(item, options = {}) {
    const {
      preserveAutoSave = false,
      updateFormActions = false,
      ensureEditorVisible = false,
    } = options;
    if (!item || !editor || !emptyState) {
      return;
    }
    if (!preserveAutoSave) {
      autoSaveEnabled = false;
      setSaveStatus('idle');
    } else if (!isEditable) {
      autoSaveEnabled = false;
    }
    if (customEditInput) {
      customEditInput.remove();
      customEditInput = null;
    }

    lastQuoteItemCosts = unitItemCostsCache.get(item.getAttribute('data-roster-unit-id')) || null;
    lastSelectedRole = null;
    currentPassives = payloadAdapters.adaptAbilityEntries(
      getUnitDatasetList(item, 'passive_items'),
      'passive',
      'editor.passive_items',
    );
    currentActives = payloadAdapters.adaptAbilityEntries(
      getUnitDatasetList(item, 'active_items'),
      'active',
      'editor.active_items',
    );
    currentAuras = payloadAdapters.adaptAbilityEntries(
      getUnitDatasetList(item, 'aura_items'),
      'aura',
      'editor.aura_items',
    );
    currentWeapons = payloadAdapters.adaptWeaponOptions(
      getUnitDatasetList(item, 'weapon_options'),
      'editor.weapon_options',
    );
    currentBaseFlags = parseFlagString(item.getAttribute('data-unit-flags'));

    const unitName = item.getAttribute('data-unit-name') || 'Jednostka';
    const quality = item.getAttribute('data-unit-quality') || '-';
    const qualityNumeric = Number(quality);
    currentQuality = Number.isFinite(qualityNumeric) ? qualityNumeric : 4;
    const defense = item.getAttribute('data-unit-defense') || '-';
    const toughness = item.getAttribute('data-unit-toughness') || '-';
    const countValue = Number(item.getAttribute('data-unit-count') || '1');
    const baseCostValue = Number(item.getAttribute('data-base-cost-per-model') || '0');
    const rosterUnitId = item.getAttribute('data-roster-unit-id');
    const customName = item.getAttribute('data-unit-custom-name') || '';
    if (nameEl) {
      nameEl.textContent = unitName;
    }
    if (statsEl) {
      statsEl.textContent = `Jakość ${quality} / Obrona ${defense} / Wytrzymałość ${toughness}`;
    }

    setCustomName(customName, {
      triggerSave: false,
      updateActiveItem: false,
      updateList: false,
    });

    currentCount = Number.isFinite(countValue) && countValue >= 1 ? countValue : 1;
    if (countInput) {
      countInput.value = String(currentCount);
    }

    loadoutState = hydrateLoadoutStateForItem(item, {
      count: currentCount,
      weapons: currentWeapons,
      activeItems: currentActives,
      auraItems: currentAuras,
      passiveItems: currentPassives,
    });

    baseCostPerModel = Number.isFinite(baseCostValue) && baseCostValue >= 0 ? baseCostValue : 0;

    ignoreNextSave = true;
    handleStateChange();

    if (updateFormActions && rosterUnitId) {
      if (form) {
        form.setAttribute('action', `/rosters/${rosterId}/units/${rosterUnitId}/update`);
      }
      if (duplicateForm) {
        duplicateForm.setAttribute(
          'action',
          `/rosters/${rosterId}/units/${rosterUnitId}/duplicate`,
        );
      }
      if (deleteForm) {
        deleteForm.setAttribute('action', `/rosters/${rosterId}/units/${rosterUnitId}/delete`);
      }
    }

    if (ensureEditorVisible) {
      editor.classList.remove('d-none');
      emptyState.classList.add('d-none');
      if (editorActions) {
        editorActions.classList.remove('d-none');
      }
    }

    autoSaveEnabled = isEditable;
    setSaveStatus(currentSaveStatus);
  }

  function applyServerUpdate(payload, refreshToken = null) {
    if (!payload || typeof payload !== 'object') {
      return;
    }
    const applyUnitData = (unitData) => {
      if (!unitData || typeof unitData !== 'object') {
        return;
      }
      const unitId = unitData && unitData.id !== undefined ? String(unitData.id) : '';
      const isActiveMatch = Boolean(
        activeItem && unitId && activeItem.getAttribute('data-roster-unit-id') === unitId,
      );
      const targetItem = isActiveMatch
        ? activeItem
        : unitId
          ? root.querySelector(`[data-roster-item][data-roster-unit-id="${unitId}"]`)
          : null;
      if (!targetItem) {
        return;
      }
      const unitCacheId = resolveUnitCacheId(targetItem);
      if (unitCacheId && !rosterUnitDatasetRepo.has(unitCacheId)) {
        const hydratedDataset = {};
        UNIT_DATASET_ATTRIBUTE_MAP.forEach((datasetKey, attribute) => {
          if (datasetKey === 'default_summary') {
            hydratedDataset[datasetKey] = targetItem.getAttribute(attribute) || '';
            return;
          }
          hydratedDataset[datasetKey] = adaptUnitDatasetValue(
            datasetKey,
            getParsedList(targetItem, attribute),
            `hydrated_dataset.${datasetKey}`,
          );
        });
        rosterUnitDatasetRepo.set(unitCacheId, hydratedDataset);
        rosterUnitDatasetCache.delete(unitCacheId);
      }
      if (unitCacheId) {
        const datasetUpdates = {};
        UNIT_DATASET_KEYS.forEach((key) => {
          if (Object.prototype.hasOwnProperty.call(unitData, key)) {
            datasetUpdates[key] = unitData[key];
          }
        });
        if (Object.keys(datasetUpdates).length) {
          updateUnitDataset(unitCacheId, datasetUpdates);
        }
      }
      if (typeof unitData.count === 'number' && Number.isFinite(unitData.count)) {
        targetItem.setAttribute('data-unit-count', String(unitData.count));
      }
      const serverCachedCost = Number(unitData.cached_cost);
      const hasServerCachedCost = Number.isFinite(serverCachedCost);
      if (hasServerCachedCost) {
        targetItem.setAttribute('data-unit-cost', String(serverCachedCost));
      }
      if (
        typeof unitData.base_cost_per_model === 'number'
        && Number.isFinite(unitData.base_cost_per_model)
      ) {
        targetItem.setAttribute('data-base-cost-per-model', String(unitData.base_cost_per_model));
      }
      if (unitData.custom_name !== undefined) {
        const serverName = typeof unitData.custom_name === 'string' ? unitData.custom_name : '';
        targetItem.setAttribute('data-unit-custom-name', serverName);
        updateListCustomName(targetItem, serverName.trim());
      }
      if (typeof unitData.loadout_json === 'string') {
        targetItem.setAttribute('data-loadout', unitData.loadout_json);
        invalidateCachedAttribute(targetItem, 'data-loadout');
      }
      if (Object.prototype.hasOwnProperty.call(unitData, 'selected_passive_items')) {
        setItemListAttribute(
          targetItem,
          'data-selected-passives',
          unitData.selected_passive_items,
        );
      }
      if (Object.prototype.hasOwnProperty.call(unitData, 'selected_active_items')) {
        setItemListAttribute(
          targetItem,
          'data-selected-actives',
          unitData.selected_active_items,
        );
      }
      if (Object.prototype.hasOwnProperty.call(unitData, 'selected_aura_items')) {
        setItemListAttribute(targetItem, 'data-selected-auras', unitData.selected_aura_items);
      }
      const unitName = targetItem.getAttribute('data-unit-name') || 'Jednostka';
      if (typeof unitData.count === 'number' && Number.isFinite(unitData.count)) {
        const titleEl = targetItem.querySelector('[data-roster-unit-title]');
        if (titleEl) {
          titleEl.textContent = `${unitData.count}x ${unitName}`;
        }
      }
      const costBadge = targetItem.querySelector('[data-roster-unit-cost]');
      if (costBadge && hasServerCachedCost) {
        costBadge.textContent = `${formatPoints(serverCachedCost)} pkt`;
      }
      const loadoutEl = targetItem.querySelector('[data-roster-unit-loadout]');
      if (loadoutEl) {
        const defaultSummary =
          getUnitDatasetValue(unitCacheId || targetItem, 'default_summary', unitData.default_summary || '-') || '-';
        const summary =
          unitData.loadout_summary !== undefined && unitData.loadout_summary !== null
            ? unitData.loadout_summary
            : defaultSummary;
        loadoutEl.textContent = `Uzbrojenie: ${summary || '-'}`;
      }
      const nextPassiveItems = Object.prototype.hasOwnProperty.call(unitData, 'selected_passive_items')
        ? unitData.selected_passive_items
        : getParsedList(targetItem, 'data-selected-passives');
      const nextActiveItems = Object.prototype.hasOwnProperty.call(unitData, 'selected_active_items')
        ? unitData.selected_active_items
        : getParsedList(targetItem, 'data-selected-actives');
      const nextAuraItems = Object.prototype.hasOwnProperty.call(unitData, 'selected_aura_items')
        ? unitData.selected_aura_items
        : getParsedList(targetItem, 'data-selected-auras');
      updateItemAbilityBadges(targetItem, {
        passives: payloadAdapters.adaptAbilityEntries(nextPassiveItems, 'passive', 'badges.passive_items'),
        actives: payloadAdapters.adaptAbilityEntries(nextActiveItems, 'active', 'badges.active_items'),
        auras: payloadAdapters.adaptAbilityEntries(nextAuraItems, 'aura', 'badges.aura_items'),
      });
      if (isActiveMatch) {
        suppressNextBadgeRefresh = true;
        skipCostDisplayLoading = true;
        syncEditorFromItem(targetItem, { preserveAutoSave: true });
        suppressNextBadgeRefresh = false;
      }
    };

    const unitsPayload = Array.isArray(payload.units)
      ? payload.units.slice()
      : [];
    if (payload.unit) {
      unitsPayload.push(payload.unit);
    }
    if (unitsPayload.length === 0) {
      applyUnitData(payload.unit || {});
    } else {
      const seen = new Set();
      unitsPayload.forEach((unitData) => {
        const unitId = unitData && unitData.id !== undefined ? String(unitData.id) : '';
        if (unitId && seen.has(unitId)) {
          return;
        }
        if (unitId) {
          seen.add(unitId);
        }
        applyUnitData(unitData);
      });
    }
    let totalCostValue = null;
    const payloadTotalCost = Number(payload.total_cost);
    const payloadRosterTotalCost = Number(payload?.roster?.total_cost);
    if (Number.isFinite(payloadTotalCost)) {
      totalCostValue = payloadTotalCost;
    } else if (Number.isFinite(payloadRosterTotalCost)) {
      totalCostValue = payloadRosterTotalCost;
    }
    const fallbackServerVersion = nextRefreshVersion();
    const serverRefreshToken = normalizeRosterRefreshCycleToken(
      refreshToken || {
        version: fallbackServerVersion,
        authoritative: true,
        dedupeKey: `server:${fallbackServerVersion}`,
      },
      fallbackServerVersion,
    );
    refreshRosterCostBadges({
      totalOverride: Number.isFinite(totalCostValue) ? totalCostValue : null,
      recomputeItems: false,
    }, serverRefreshToken);
  }

  function serializeQuotePayloadFromState(state, count) {
    const serialized = serializeLoadoutState(state);
    const parsedLoadout = parseJsonValue(
      serialized,
      'Nie udało się zserializować konfiguracji oddziału',
      {},
    );
    const loadoutObj = parsedLoadout && typeof parsedLoadout === 'object' ? parsedLoadout : {};
    return {
      count: Math.max(Number(count) || 1, 1),
      loadout: lastSelectedRole ? { ...loadoutObj, selected_role: lastSelectedRole } : loadoutObj,
    };
  }

  function setCostDisplayStatus(status) {
    if (!costBadgeEl) {
      return;
    }
    costBadgeEl.classList.toggle('opacity-50', status === 'loading');
    costBadgeEl.classList.toggle('text-bg-danger', status === 'error');
  }

  function getLastKnownItemCost(item) {
    if (!item || typeof item.getAttribute !== 'function') {
      return Number.NaN;
    }
    return Number(item.getAttribute('data-unit-cost'));
  }

  function setRosterItemCostStatus(item, status) {
    if (!item) {
      return;
    }
    const badgeEl = item.querySelector('[data-roster-unit-cost]');
    if (!badgeEl) {
      return;
    }
    badgeEl.classList.toggle('text-bg-danger', status === 'error');
    badgeEl.classList.toggle('opacity-50', status === 'loading');
  }

  async function fetchRosterUnitQuote(requestedRosterUnitId, quotePayload, signal, includeItemCosts = true) {
    if (!rosterId || !requestedRosterUnitId) {
      throw new Error('Brak identyfikatora oddziału do wyceny');
    }
    const body = includeItemCosts
      ? (quotePayload || {})
      : { ...(quotePayload || {}), include_item_costs: false };
    const response = await fetch(`/rosters/${rosterId}/units/${requestedRosterUnitId}/quote`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      credentials: 'same-origin',
      signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    const quote = payloadAdapters.adaptQuotePayload(payload, requestedRosterUnitId, 'roster_editor.quote');
    if (!Number.isFinite(quote.total)) {
      throw new Error('Nieprawidłowa odpowiedź endpointu quote');
    }
    const responseRosterUnitId = normalizeRosterUnitId(quote.rosterUnitId);
    if (
      responseRosterUnitId
      && String(responseRosterUnitId) !== String(requestedRosterUnitId)
    ) {
      throw new Error('Nieprawidłowy identyfikator oddziału w odpowiedzi endpointu quote');
    }
    return quote;
  }

  function renderActiveCost(total) {
    const formatted = formatPoints(total);
    if (costValueEl) {
      costValueEl.textContent = formatted;
    }
    if (costBadgeEl) {
      costBadgeEl.classList.toggle('d-none', false);
    }
    if (activeItem) {
      activeItem.setAttribute('data-unit-cost', String(total));
      const listBadge = activeItem.querySelector('[data-roster-unit-cost]');
      if (listBadge) {
        listBadge.textContent = `${formatted} pkt`;
      }
    }
    return total;
  }

  function refreshRosterCostBadges(options = null, cycleToken = null) {
    const normalizedOptions = options && typeof options === 'object'
      ? options
      : { totalOverride: options };
    const totalOverride = Number.isFinite(normalizedOptions.totalOverride)
      ? normalizedOptions.totalOverride
      : null;
    const recomputeItems = normalizedOptions.recomputeItems !== false;
    const changedUnitId = normalizedOptions.changedUnitId || null;
    const normalizedToken = normalizeRosterRefreshCycleToken(cycleToken, nextRefreshVersion());
    if (normalizedToken.dedupeKey && normalizedToken.dedupeKey === lastRefreshRosterCostCycleToken) {
      return;
    }
    if (refreshRosterCostBadgesInProgress) {
      const pendingToken = normalizeRosterRefreshCycleToken(pendingRefreshCycleToken, -Infinity);
      if (!pendingRefreshCycleToken || normalizedToken.version >= pendingToken.version) {
        pendingRefreshOptions = normalizedOptions;
        pendingRefreshCycleToken = normalizedToken;
      }
      return;
    }

    const currentRefreshCycle = ++rosterRefreshCycleCounter;
    refreshRosterCostBadgesInProgress = true;
    (async () => {
      try {
        const listElement = rosterListEl || ensureRosterList();
        if (!listElement) {
          return;
        }

        const rosterItems = Array.from(listElement.querySelectorAll('[data-roster-item]'));
        if (!rosterItems.length) {
          if (Number.isFinite(totalOverride)) {
            const decision = applyRefreshPriority(normalizedToken);
            if (decision.apply) {
              updateTotalSummary(totalOverride);
            }
          }
          return;
        }

        if (!recomputeItems) {
          const decision = applyRefreshPriority(normalizedToken);
          if (!decision.apply) {
            return;
          }
          if (Number.isFinite(totalOverride)) {
            updateTotalSummary(totalOverride);
            return;
          }
          const summedTotal = rosterItems.reduce((sum, item) => {
            const value = Number(item?.getAttribute?.('data-unit-cost'));
            return Number.isFinite(value) ? sum + value : sum;
          }, 0);
          const expectedSingleUnitTotal = rosterItems.length === 1
            ? Number(rosterItems[0].getAttribute('data-unit-cost'))
            : null;
          const safeTotal = Number.isFinite(expectedSingleUnitTotal) ? expectedSingleUnitTotal : summedTotal;
          updateTotalSummary(safeTotal);
          return;
        }

        if (changedUnitId) {
          const changedItem = rosterItems.find(
            (item) => item.getAttribute('data-roster-unit-id') === String(changedUnitId),
          );
          if (changedItem) {
            setRosterItemCostStatus(changedItem, 'loading');
          }
          const cachedTotal = rosterItems.reduce((sum, item) => {
            const value = Number(item?.getAttribute?.('data-unit-cost'));
            return Number.isFinite(value) ? sum + value : sum;
          }, 0);
          const decision = applyRefreshPriority(normalizedToken);
          if (decision.apply) {
            updateTotalSummary(cachedTotal);
          }
          return;
        }

        let aggregatedTotal = 0;
        const refreshConcurrencyLimit = 5;
        for (let startIndex = 0; startIndex < rosterItems.length; startIndex += refreshConcurrencyLimit) {
          const batchItems = rosterItems.slice(startIndex, startIndex + refreshConcurrencyLimit);
          batchItems.forEach((item) => {
            setRosterItemCostStatus(item, 'loading');
          });
          const batchResults = await Promise.allSettled(
            batchItems.map(async (item) => {
              const rosterUnitId = item.getAttribute('data-roster-unit-id') || '';
              const count = Math.max(Number(item.getAttribute('data-unit-count') || '1'), 1);
              const itemLoadout = hydrateLoadoutStateForItem(item, {
                count,
                weapons: getUnitDatasetList(item, 'weapon_options'),
                activeItems: getUnitDatasetList(item, 'active_items'),
                auraItems: getUnitDatasetList(item, 'aura_items'),
                passiveItems: getUnitDatasetList(item, 'passive_items'),
              });
              const quotePayload = serializeQuotePayloadFromState(itemLoadout, count);
              const quote = await fetchRosterUnitQuote(rosterUnitId, quotePayload, null, false);
              return {
                item,
                rosterUnitId,
                total: quote.total,
              };
            }),
          );

          batchResults.forEach((result, batchIndex) => {
            const item = batchItems[batchIndex];
            if (!item) {
              return;
            }
            const rosterUnitId = item.getAttribute('data-roster-unit-id') || '';
            let total = Number.NaN;
            if (result.status === 'fulfilled') {
              total = Number(result.value?.total);
              setRosterItemCostStatus(item, 'ready');
            } else {
              const knownTotal = getLastKnownItemCost(item);
              if (Number.isFinite(knownTotal)) {
                total = knownTotal;
              }
              const errorReason = result.reason || new Error('Brak wyniku zapytania');
              setRosterItemCostStatus(item, 'error');
              console.error(`Nie udało się pobrać quote dla oddziału ${rosterUnitId}`, errorReason);
            }
            if (!Number.isFinite(total)) {
              return;
            }
            const formatted = formatPoints(total);
            const badgeEl = item.querySelector('[data-roster-unit-cost]');
            if (badgeEl) {
              badgeEl.textContent = `${formatted} pkt`;
            }
            item.setAttribute('data-unit-cost', String(total));
            aggregatedTotal += total;
          });
        }

        const decision = applyRefreshPriority(normalizedToken);
        if (!decision.apply) {
          return;
        }
        if (Number.isFinite(totalOverride)) {
          const expectedSingleUnitTotal = rosterItems.length === 1
            ? Number(rosterItems[0].getAttribute('data-unit-cost'))
            : null;
          const safeTotal = Number.isFinite(expectedSingleUnitTotal) ? expectedSingleUnitTotal : totalOverride;
          updateTotalSummary(safeTotal);
        } else if (Number.isFinite(aggregatedTotal)) {
          const expectedSingleUnitTotal = rosterItems.length === 1
            ? Number(rosterItems[0].getAttribute('data-unit-cost'))
            : null;
          const safeTotal = Number.isFinite(expectedSingleUnitTotal) ? expectedSingleUnitTotal : aggregatedTotal;
          updateTotalSummary(safeTotal);
        }
      } finally {
        refreshRosterCostBadgesInProgress = false;
        if (normalizedToken.dedupeKey) {
          lastRefreshRosterCostCycleToken = normalizedToken.dedupeKey;
        }
        if (pendingRefreshOptions !== null || pendingRefreshCycleToken !== null) {
          const nextOptions = pendingRefreshOptions;
          const nextCycleToken = pendingRefreshCycleToken;
          pendingRefreshOptions = null;
          pendingRefreshCycleToken = null;
          refreshRosterCostBadges(nextOptions, nextCycleToken);
        }
      }
    })();
  }

  function recalculateTotalFromCachedBadges() {
    const listElement = rosterListEl || ensureRosterList();
    if (!listElement) return;
    const items = Array.from(listElement.querySelectorAll('[data-roster-item]'));
    if (!items.length) return;
    const summedTotal = items.reduce((sum, item) => {
      const v = Number(item?.getAttribute?.('data-unit-cost'));
      return Number.isFinite(v) ? sum + v : sum;
    }, 0);
    const expectedSingleUnitTotal = items.length === 1
      ? Number(items[0].getAttribute('data-unit-cost'))
      : null;
    const safeTotal = Number.isFinite(expectedSingleUnitTotal) ? expectedSingleUnitTotal : summedTotal;
    updateTotalSummary(safeTotal);
  }


  function handleStateChange() {
    const editVersion = latestEditVersion + 1;
    latestEditVersion = editVersion;
    const activeEntry = activeItem ? getEntryElementFromItem(activeItem) : null;
    const activeId = getUnitIdFromEntry(activeEntry);
    if (loadoutState) {
      loadoutState.mode = 'total';
    }

    // Batched via RAF — coalesces rapid edits into a single DOM rebuild.
    // loadoutInput.value below is still synced synchronously so the next
    // edit reads the latest serialized state.
    scheduleRender();
    if (loadoutInput && loadoutState) {
      loadoutInput.value = serializeLoadoutState(loadoutState);
    }
    if (quoteRefreshTimer) {
      window.clearTimeout(quoteRefreshTimer);
      quoteRefreshTimer = null;
    }
    if (activeQuoteController) {
      activeQuoteController.abort();
      activeQuoteController = null;
    }
    quoteRefreshTimer = window.setTimeout(() => {
      quoteRefreshTimer = null;
      quoteRequestVersion += 1;
      const requestVersion = quoteRequestVersion;
      activeQuoteController = new AbortController();
      const currentSignal = activeQuoteController.signal;
      const rosterUnitId = activeItem ? activeItem.getAttribute('data-roster-unit-id') || '' : '';
      const quotePayload = serializeQuotePayloadFromState(loadoutState, currentCount);
      if (skipCostDisplayLoading) {
        skipCostDisplayLoading = false;
      } else {
        setCostDisplayStatus('loading');
      }
      fetchRosterUnitQuote(rosterUnitId, quotePayload, currentSignal)
        .then((quote) => {
          if (requestVersion !== quoteRequestVersion) {
            return;
          }
          if (quote.itemCosts && typeof quote.itemCosts === 'object') {
            lastQuoteItemCosts = quote.itemCosts;
            if (rosterUnitId) {
              unitItemCostsCache.set(rosterUnitId, quote.itemCosts);
            }
          }
          if (quote.selectedRole) {
            lastSelectedRole = quote.selectedRole;
          }
          renderEditors();
          setCostDisplayStatus('ready');
          renderActiveCost(quote.total);
          setRosterItemCostStatus(activeItem, 'ready');
          recalculateTotalFromCachedBadges();
        })
        .catch((error) => {
          if (error && error.name === 'AbortError') {
            return;
          }
          console.error('Nie udało się odświeżyć wyceny aktywnego oddziału', error);
          const total = getLastKnownItemCost(activeItem);
          if (Number.isFinite(total)) {
            setCostDisplayStatus('ready');
            renderActiveCost(total);
            setRosterItemCostStatus(activeItem, 'ready');
            return;
          }
          setCostDisplayStatus('error');
          setRosterItemCostStatus(activeItem, 'error');
        })
        .finally(() => {
          if (activeQuoteController && activeQuoteController.signal === currentSignal) {
            activeQuoteController = null;
          }
        });
    }, 400);
    // 400ms debounce: typical burst-edit cadence is ~150-300ms between clicks.
    // At 250ms most burst series fire 1-2 quote requests; at 400ms only one
    // quote fires after the burst settles. Users don't perceive the extra
    // 150ms because they're already waiting for network round-trip.
    let stateChangeCycleToken = null;
    if (activeItem) {
      const dedupeKey = [activeId, String(currentCount), lastSelectedRole || '', loadoutInput?.value || ''].join('::');
      stateChangeCycleToken = {
        dedupeKey,
        version: nextRefreshVersion(editVersion),
        authoritative: false,
      };
    }
    if (activeItem && loadoutInput) {
      activeItem.setAttribute('data-loadout', loadoutInput.value || '{}');
      invalidateCachedAttribute(activeItem, 'data-loadout');
    }
    if (activeItem) {
      activeItem.setAttribute('data-unit-count', String(currentCount));
      invalidateCachedAttribute(activeItem, 'data-unit-count');
    }
    if (suppressNextBadgeRefresh) {
      suppressNextBadgeRefresh = false;
    } else {
      refreshRosterCostBadges({
        totalOverride: null,
        recomputeItems: true,
        changedUnitId: activeId || null,
      }, stateChangeCycleToken);
    }
    if (ignoreNextSave) {
      ignoreNextSave = false;
      return;
    }
    if (autoSaveEnabled) {
      setSaveStatus('dirty');
      scheduleSave(editVersion);
    }
  }

  // RAF-batched wrapper for renderEditors. Multiple state changes within a
  // single animation frame coalesce into one DOM rebuild — eliminates jank
  // when the user rapidly clicks +/- on count or weapon counters.
  // The synchronous renderEditors() call from quote .then() bypasses this
  // because it must reflect freshly-arrived server data immediately.
  let renderScheduled = false;
  function scheduleRender() {
    if (renderScheduled) return;
    renderScheduled = true;
    window.requestAnimationFrame(() => {
      renderScheduled = false;
      renderEditors();
    });
  }

function renderEditors() {
    const passiveState = loadoutState && loadoutState.passive instanceof Map ? loadoutState.passive : new Map();
    if (lastQuoteItemCosts) {
      const weaponCosts = lastQuoteItemCosts.weapons || {};
      currentWeaponCostMap = new Map(
        Object.entries(weaponCosts).map(([id, cost]) => [Number(id), Number(cost)]),
      );
    } else {
      currentWeaponCostMap = new Map();
    }
    const computePassiveDeltaForSlug = (slug) => {
      if (!slug || !lastQuoteItemCosts) {
        return Number.NaN;
      }
      const passiveDeltas = lastQuoteItemCosts.passiveDeltas || lastQuoteItemCosts.passive_deltas || {};
      const identifier = abilityIdentifier(String(slug)) || String(slug);
      const delta = passiveDeltas[identifier];
      return Number.isFinite(delta) ? delta : Number.NaN;
    };
    const decoratedWeapons = Array.isArray(currentWeapons)
      ? currentWeapons.map((option) => {
          if (!option || option.id === undefined || option.id === null) {
            return option;
          }
          const weaponId = Number(option.id);
          const override = currentWeaponCostMap.get(weaponId);
          if (!Number.isFinite(override)) {
            return option;
          }
          return { ...option, cost: override };
        })
      : [];
    const activeIsHero = activeItem
      ? activeItem.getAttribute('data-is-hero') === 'true'
      : false;
    const heroContext = (activeIsHero && isEditable) ? {
      rosterId,
      rosterUnitId: activeItem ? activeItem.getAttribute('data-roster-unit-id') || '' : '',
      currentParentId: activeItem
        ? activeItem.getAttribute('data-parent-roster-unit-id') || ''
        : '',
      attachable: (() => {
        try {
          return JSON.parse(root.getAttribute('data-roster-attachable-units') || '[]');
        } catch (_e) {
          return [];
        }
      })(),
    } : null;
    const hasPassives = renderPassiveEditor(
      passiveContainer,
      currentPassives,
      passiveState,
      currentCount,
      isEditable,
      handleStateChange,
      (context) => {
        if (!context || !context.slug) {
          return Number.NaN;
        }
        return computePassiveDeltaForSlug(context.slug);
      },
      heroContext,
    );
    toggleSectionVisibility(passiveContainer, hasPassives);
    const hasActives = renderAbilityEditor(
      activeContainer,
      currentActives,
      loadoutState.active,
      loadoutState.activeLabels,
      currentCount,
      isEditable,
      handleStateChange,
      loadoutState ? loadoutState.mode : 'total',
    );
    toggleSectionVisibility(activeContainer, hasActives);
    const hasAuras = renderAbilityEditor(
      auraContainer,
      currentAuras,
      loadoutState.aura,
      loadoutState.auraLabels,
      currentCount,
      isEditable,
      handleStateChange,
      loadoutState ? loadoutState.mode : 'total',
    );
    toggleSectionVisibility(auraContainer, hasAuras);
    const hasWeapons = renderWeaponEditor(
      loadoutContainer,
      decoratedWeapons,
      loadoutState.weapons,
      currentCount,
      isEditable,
      handleStateChange,
      loadoutState ? loadoutState.mode : 'total',
      loadoutState ? (loadoutState.primaryWeapon || {}) : {},
      (newPrimaryWeapon) => {
        if (loadoutState) {
          loadoutState.primaryWeapon = newPrimaryWeapon;
        }
        handleStateChange();
      },
    );
    toggleSectionVisibility(loadoutContainer, hasWeapons);
  }

  function collectInitialRosterItems() {
    const initialItems = Array.from(root.querySelectorAll('[data-roster-item]'));
    initialItems.forEach((item) => {
      registerRosterItem(item);
    });
    return initialItems;
  }

  function syncInitialRosterList(initialItems) {
    if (!rosterListEl && initialItems.length) {
      const inferredList = initialItems[0].closest('[data-roster-list]');
      if (inferredList) {
        rosterListEl = inferredList;
      }
    }
    if (rosterListEl) {
      updateMoveButtonStates(rosterListEl);
    }
  }

  function selectInitialRosterItem() {
    try {
      const selectedId = root.dataset.selectedId || '';
      let initialItem = null;
      if (selectedId) {
        initialItem = items.find(
          (element) => element.getAttribute('data-roster-unit-id') === selectedId,
        );
      }
      if (initialItem) {
        selectItem(initialItem);
        if (typeof initialItem.scrollIntoView === 'function') {
          initialItem.scrollIntoView({ block: 'nearest' });
        }
      } else if (items.length) {
        selectItem(items[0]);
      } else if (editor && emptyState) {
        editor.classList.add('d-none');
        emptyState.classList.remove('d-none');
        if (editorActions) {
          editorActions.classList.add('d-none');
        }
      }
    } catch (error) {
      console.error('Nie udało się wybrać początkowego oddziału', error);
      throw error;
    }
  }

  // Fire an immediate save for a unit that is about to lose focus before its
  // debounce timer has elapsed. Bypasses submitChanges (and its version checks)
  // because the departing unit is no longer active — we just want the data on
  // the server and all list-item updates (badge, title, loadout, abilities)
  // reflected via applyServerUpdate when the response arrives.
  function _fireDepartingSave(departingItem) {
    if (!form || !departingItem) return;
    const action = form.getAttribute('action');
    if (!action) return;
    const departingUnitId = departingItem.getAttribute('data-roster-unit-id') || '';
    const savePayload = new FormData(form);
    savePayload.set('count', String(currentCount));
    if (customNameInput) savePayload.set('custom_name', customNameInput.value.trim());
    if (loadoutInput) savePayload.set('loadout_json', loadoutInput.value || '{}');
    fetch(action, {
      method: 'POST',
      body: savePayload,
      headers: { Accept: 'application/json' },
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!data) return;
        // Locate the departing unit's data from the server response.
        // The response may include lock-pair siblings in `data.units` — we must
        // NOT pass those to applyServerUpdate, because if a sibling happens to
        // be the currently-active unit, applyServerUpdate would call
        // syncEditorFromItem on it and overwrite the user's in-progress edits
        // with stale server state (ghost weapons / wrong loadout).
        const allUnits = Array.isArray(data.units) ? [...data.units] : [];
        if (data.unit) allUnits.push(data.unit);
        const departingData = departingUnitId
          ? (allUnits.find((u) => u && String(u.id) === departingUnitId) ?? null)
          : (data.unit ?? null);
        // Apply update for the departing unit only — omit `units` so sibling
        // data is never processed and the active editor is left untouched.
        applyServerUpdate({
          unit: departingData,
          total_cost: data.total_cost,
          roster: data.roster,
        });
        // applyServerUpdate updates badge content but not the loading class;
        // explicitly clear it so the badge doesn't stay semi-transparent.
        if (departingUnitId) {
          const targetItem = root.querySelector(
            `[data-roster-item][data-roster-unit-id="${departingUnitId}"]`,
          );
          if (targetItem) setRosterItemCostStatus(targetItem, 'ready');
        }
      })
      .catch((error) => {
        console.error('Nie udało się zapisać oddziału przy zmianie', error);
      });
  }

  function selectItem(item, options = {}) {
    const { preserveAutoSave = false } = options;
    if (!preserveAutoSave && activeItem === item) {
      return;
    }
    // Flush unsaved edits for the departing unit before switching.
    // cancelPendingSave would destroy the timer without firing the save.
    if (saveTimer !== null && isEditable && autoSaveEnabled && form && activeItem) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
      _fireDepartingSave(activeItem);
    } else {
      cancelPendingSave();
    }
    // Badge may be stuck in 'loading' (set by changedUnitId refresh but quote
    // timer was cancelled). Restore to 'ready' — full refresh will correct the
    // cost value later.
    if (activeItem) {
      setRosterItemCostStatus(activeItem, 'ready');
    }
    if (activeItem) {
      activeItem.classList.remove('active');
    }
    activeItem = item;
    if (activeItem) {
      activeItem.classList.add('active');
    }
    if (!editor || !emptyState) {
      return;
    }
    if (!item) {
      editor.classList.add('d-none');
      emptyState.classList.remove('d-none');
      if (editorActions) {
        editorActions.classList.add('d-none');
      }
      if (customNameInput) {
        customNameInput.value = '';
      }
      currentCustomName = '';
      if (customEditInput) {
        customEditInput.remove();
        customEditInput = null;
      }
      updateCustomLabelDisplay('');
      autoSaveEnabled = false;
      setSaveStatus('idle');
      return;
    }

    try {
      syncEditorFromItem(item, {
        preserveAutoSave,
        updateFormActions: true,
        ensureEditorVisible: true,
      });
    } catch (error) {
      console.error('Błąd podczas wczytywania oddziału', error);
      showRosterEditorError('Nie udało się wczytać danych oddziału.');
    }
  }

  function initializeRosterEditorState() {
    try {
      initializeUnitDatasetRepo();
      initializeMoveForms();
      const initialItems = collectInitialRosterItems();
      syncInitialRosterList(initialItems);
      selectInitialRosterItem();
      refreshRosterCostBadges();
    } catch (error) {
      resetRosterCaches();
      throw error;
    }
  }

  try {
    initializeRosterEditorState();
  } catch (error) {
    console.error('Nie udało się zainicjalizować edytora oddziału', error);
    showRosterEditorError('Panel edycji jest obecnie niedostępny.');
  }

  if (countInput) {
    countInput.addEventListener('change', () => {
      let nextValue = Number(countInput.value);
      if (!Number.isFinite(nextValue) || nextValue < 1) {
        nextValue = 1;
        countInput.value = '1';
      }
      syncDefaultEquipment(currentCount, nextValue);
      currentCount = nextValue;
      handleStateChange();
    });
  }

  if (customLabel) {
    if (isEditable) {
      customLabel.classList.add('cursor-pointer');
      customLabel.addEventListener('click', (event) => {
        event.preventDefault();
        startCustomInlineEdit();
      });
      customLabel.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          startCustomInlineEdit();
        }
      });
    } else {
      customLabel.classList.remove('cursor-pointer');
      customLabel.setAttribute('tabindex', '-1');
      customLabel.setAttribute('role', 'text');
    }
    updateCustomLabelDisplay('');
  }

}


  const api = {
    initRosterEditor: initRosterEditor,
  };
  globalScope.SZOPRosterEditor = api;
  globalScope.initRosterEditor = initRosterEditor;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPRosterEditor = api;
    globalThis.initRosterEditor = initRosterEditor;
  }
}(typeof window !== 'undefined' ? window : globalThis));
