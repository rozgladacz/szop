// ============================================================
// SECTION: GLOBAL STATE & REFRESH TOKEN UTILS
// normalizeRosterRefreshCycleToken, resolveRosterRefreshPriority
// Globalne zmienne stanu + narzędzia wersjonowania odświeżeń.
// ============================================================

const normalizeRosterRefreshCycleToken = window.SZOPRefreshPriority
  ? window.SZOPRefreshPriority.normalizeRosterRefreshCycleToken
  : function normalizeRosterRefreshCycleTokenFallback(cycleToken, fallbackVersion = 0) {
    const fallback = Number.isFinite(Number(fallbackVersion)) ? Number(fallbackVersion) : 0;
    if (!cycleToken || typeof cycleToken !== 'object') {
      return {
        dedupeKey: cycleToken ? String(cycleToken) : null,
        version: fallback,
        authoritative: false,
      };
    }
    const rawVersion = Number(cycleToken.version);
    const normalizedVersion = Number.isFinite(rawVersion) ? rawVersion : fallback;
    const dedupeKeyValue = cycleToken.dedupeKey ?? cycleToken.key ?? cycleToken.token ?? null;
    return {
      dedupeKey: dedupeKeyValue ? String(dedupeKeyValue) : null,
      version: normalizedVersion,
      authoritative: cycleToken.authoritative === true,
    };
  };

const resolveRosterRefreshPriority = window.SZOPRefreshPriority
  ? window.SZOPRefreshPriority.resolveRosterRefreshPriority
  : function resolveRosterRefreshPriorityFallback(state, cycleToken) {
    const currentState = state && typeof state === 'object'
      ? state
      : { latestAppliedVersion: 0, latestAuthoritativeVersion: 0 };
    const token = normalizeRosterRefreshCycleToken(cycleToken, currentState.latestAppliedVersion || 0);
    const nextState = {
      latestAppliedVersion: Number.isFinite(Number(currentState.latestAppliedVersion))
        ? Number(currentState.latestAppliedVersion)
        : 0,
      latestAuthoritativeVersion: Number.isFinite(Number(currentState.latestAuthoritativeVersion))
        ? Number(currentState.latestAuthoritativeVersion)
        : 0,
    };
    const version = Number.isFinite(token.version) ? token.version : 0;
    if (version < nextState.latestAppliedVersion) {
      return { apply: false, token, state: nextState };
    }
    if (!token.authoritative && version < nextState.latestAuthoritativeVersion) {
      return { apply: false, token, state: nextState };
    }
    nextState.latestAppliedVersion = Math.max(nextState.latestAppliedVersion, version);
    if (token.authoritative) {
      nextState.latestAuthoritativeVersion = Math.max(nextState.latestAuthoritativeVersion, version);
    }
    return { apply: true, token, state: nextState };
  };

const payloadAdapters = window.SZOPPayloadAdapters || {
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



window.normalizeRosterRefreshCycleToken = normalizeRosterRefreshCycleToken;
window.resolveRosterRefreshPriority = resolveRosterRefreshPriority;
if (typeof globalThis !== 'undefined') {
  globalThis.normalizeRosterRefreshCycleToken = normalizeRosterRefreshCycleToken;
  globalThis.resolveRosterRefreshPriority = resolveRosterRefreshPriority;
}

// ============================================================
// SECTION: ABILITY PICKER
// Extracted to app/static/js/modules/ability_picker.js
// ============================================================
const {
  initAbilityPicker,
  initAbilityPickers,
} = window.SZOPAbilityPicker;

// ============================================================
// SECTION: TEXT PARSING UTILS
// Extracted to app/static/js/modules/text_parsing.js
// ============================================================
const {
  splitTraits,
  normalizeName,
  extractNumber,
  abilityIdentifier,
  passiveIdentifier,
  parseFlagString,
  normalizeRangeValue,
  stripOptionalFlagSuffix,
} = window.SZOPTextParsing;

// ============================================================
// SECTION: SPELL WEAPON COST PREVIEW
// Extracted to app/static/js/modules/spell_weapon_cost_preview.js
// ============================================================
const {
  initSpellWeaponCostPreview,
} = window.SZOPSpellWeaponCostPreview;

// ============================================================
// SECTION: UI PICKERS - NUMBER, RANGE, WEAPON DEFAULTS
// Extracted to app/static/js/modules/ui_pickers.js
// ============================================================
const {
  initNumberPicker,
  initNumberPickers,
  initRangePicker,
  initRangePickers,
  initWeaponDefaults,
} = window.SZOPUIPickers;

// ============================================================
// SECTION: WEAPON PICKER
// Extracted to app/static/js/modules/weapon_picker.js
// ============================================================
const {
  initWeaponPicker,
  initWeaponPickers,
} = window.SZOPWeaponPicker;

// ============================================================
// SECTION: ROSTER ITEM RENDERING
// Extracted to app/static/js/modules/roster_rendering.js
// ============================================================
const {
  formatPoints,
  createRosterItemElement,
  renderPassiveEditor,
} = window.SZOPRosterRendering;

// ============================================================
// SECTION: LOADOUT STATE MANAGEMENT
// Extracted to app/static/js/modules/loadout_state.js
// ============================================================
const {
  normalizeLoadoutKey,
  resolveLoadoutEntryKey,
  createLoadoutState,
  cloneLoadoutState,
  serializeLoadoutState,
  ensureStateEntries,
  ensureBaseStateEntries,
  ensureBaseLabelEntries,
  ensurePassiveStateEntries,
  formatAbilityDisplayLabel,
  normalizeLoadoutMode,
  formatLoadoutCostLabel,
  createModeIndicator,
} = window.SZOPLoadoutState;

// ============================================================
// SECTION: EDITOR RENDERERS
// Extracted to app/static/js/modules/editor_renderers.js
// ============================================================
const {
  renderAbilityEditor,
  toggleSectionVisibility,
  renderWeaponEditor,
} = window.SZOPEditorRenderers;

// ============================================================
// SECTION: ROSTER ADDERS
// Extracted to app/static/js/modules/roster_adders.js
// ============================================================
const {
  initRosterAdders,
} = window.SZOPRosterAdders;

// ============================================================
// SECTION: ROSTER EDITOR CLOSURE
// Extracted to app/static/js/modules/roster_editor.js
// ============================================================
const {
  initRosterEditor,
} = window.SZOPRosterEditor;

// ============================================================
// SECTION: SPELL ABILITY FORMS
// Extracted to app/static/js/modules/spell_ability_forms.js
// ============================================================
const {
  initSpellAbilityForms,
} = window.SZOPSpellAbilityForms;

// ============================================================
// SECTION: ARMORY WEAPON TREE
// Extracted to app/static/js/modules/armory_tree.js
// ============================================================
const {
  initArmoryWeaponTree,
} = window.SZOPArmoryTree;

// ============================================================
// SECTION: WEAPON INHERITANCE PANEL
// Extracted to app/static/js/modules/weapon_inheritance_panel.js
// ============================================================
const {
  initWeaponInheritancePanel,
  initWeaponImportPanel,
} = window.SZOPWeaponInheritancePanel;

// ============================================================
// SECTION: BOOTSTRAP — DOMContentLoaded
// Łańcuch inicjalizacji (kolejność krytyczna — patrz AGENTS.md):
//   initAbilityPickers → initNumberPickers → initRangePickers →
//   initWeaponPickers → initRosterEditor → initWeaponDefaults →
//   initSpellAbilityForms → initArmoryWeaponTree → initSpellWeaponCostPreview
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  initAbilityPickers();
  initNumberPickers();
  initRangePickers();
  initWeaponPickers();
  initRosterEditor();
  initWeaponDefaults();
  initSpellAbilityForms();
  initArmoryWeaponTree();
  initSpellWeaponCostPreview();
  initWeaponInheritancePanel();
  initWeaponImportPanel();
});
