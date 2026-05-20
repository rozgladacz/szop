(function initSZOPLoadoutStateModule(globalScope) {
  const rosterRendering = globalScope.SZOPRosterRendering || (typeof globalThis !== 'undefined' ? globalThis.SZOPRosterRendering : null) || {};
  const formatPoints = rosterRendering.formatPoints || globalScope.formatPoints || function formatPointsFallback(value) {
    return value !== undefined && value !== null ? String(value) : '0';
  };
  const ABILITY_NAME_MAX_LENGTH = 60;

// ============================================================
// SECTION: LOADOUT STATE MANAGEMENT
// createLoadoutState, cloneLoadoutState, serializeLoadoutState,
// ensureStateEntries, ensurePassiveStateEntries, itp.
// Zarządza stanem loadoutu oddziału (broń, zdolności, pasywki).
// ============================================================
function normalizeLoadoutKey(rawKey) {
  if (rawKey === undefined || rawKey === null) {
    return '';
  }
  if (typeof rawKey === 'string') {
    const trimmed = rawKey.trim();
    return trimmed ? trimmed : '';
  }
  if (typeof rawKey === 'number') {
    return Number.isFinite(rawKey) ? String(rawKey) : '';
  }
  if (typeof rawKey === 'bigint') {
    return rawKey.toString();
  }
  const numeric = Number(rawKey);
  if (Number.isFinite(numeric)) {
    return String(numeric);
  }
  const text = String(rawKey).trim();
  return text ? text : '';
}

function resolveLoadoutEntryKey(entry, ...idKeys) {
  if (!entry || typeof entry !== 'object') {
    return '';
  }
  const candidates = [];
  const loadoutKey = entry.loadout_key ?? entry.loadoutKey;
  if (loadoutKey !== undefined && loadoutKey !== null) {
    candidates.push(loadoutKey);
  }
  const flatIdKeys = [];
  idKeys.forEach((key) => {
    if (!key) {
      return;
    }
    if (Array.isArray(key)) {
      key.forEach((inner) => {
        if (inner) {
          flatIdKeys.push(inner);
        }
      });
      return;
    }
    flatIdKeys.push(key);
  });
  flatIdKeys.push('id');
  const seen = new Set();
  flatIdKeys.forEach((key) => {
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    if (Object.prototype.hasOwnProperty.call(entry, key)) {
      candidates.push(entry[key]);
    }
  });
  for (let index = 0; index < candidates.length; index += 1) {
    const normalized = normalizeLoadoutKey(candidates[index]);
    if (normalized) {
      return normalized;
    }
  }
  return '';
}

function createLoadoutState(rawLoadout) {
  const state = {
    weapons: new Map(),
    active: new Map(),
    aura: new Map(),
    baseActive: new Map(),
    baseAura: new Map(),
    passive: new Map(),
    activeLabels: new Map(),
    auraLabels: new Map(),
    baseActiveLabels: new Map(),
    baseAuraLabels: new Map(),
    mode: 'per_model',
    primaryWeapon: {},
  };
  if (!rawLoadout || typeof rawLoadout !== 'object') {
    return state;
  }
  if (typeof rawLoadout.mode === 'string') {
    state.mode = rawLoadout.mode;
  }
  const sections = [
    ['weapons', 'weapon_id'],
    ['active', 'ability_id'],
    ['aura', 'ability_id'],
  ];
  sections.forEach(([section, idKey]) => {
    const values = rawLoadout[section];
    if (!values) {
      return;
    }
    let entries;
    if (Array.isArray(values)) {
      entries = values;
    } else if (typeof values === 'object') {
      entries = Object.entries(values).map(([id, count]) => ({ id, per_model: count }));
    } else {
      entries = [];
    }
    entries.forEach((entry) => {
      if (!entry) {
        return;
      }
      const key = resolveLoadoutEntryKey(entry, idKey, ['weapon_id', 'ability_id']);
      if (!key) {
        return;
      }
      const rawCount = entry.per_model ?? entry.count ?? 0;
      let parsedCount = Number(rawCount);
      if (!Number.isFinite(parsedCount) || parsedCount < 0) {
        parsedCount = 0;
      }
      state[section].set(key, parsedCount);
    });
  });
  const passiveSource = rawLoadout.passive;
  if (passiveSource && typeof passiveSource === 'object') {
    let entries;
    if (Array.isArray(passiveSource)) {
      entries = passiveSource;
    } else {
      entries = Object.entries(passiveSource).map(([slug, enabled]) => ({ slug, enabled }));
    }
    entries.forEach((entry) => {
      if (!entry) {
        return;
      }
      const slug = entry.slug ?? entry.id;
      if (slug === undefined || slug === null) {
        return;
      }
      const rawValue = entry.enabled ?? entry.count ?? entry.value;
      const numeric = Number(rawValue);
      let flag = 0;
      if (typeof rawValue === 'boolean') {
        flag = rawValue ? 1 : 0;
      } else if (Number.isFinite(numeric)) {
        flag = numeric > 0 ? 1 : 0;
      } else if (rawValue) {
        flag = 1;
      }
      state.passive.set(String(slug), flag);
    });
  }
  const labelSections = [
    ['activeLabels', rawLoadout.active_labels],
    ['auraLabels', rawLoadout.aura_labels],
    ['baseActiveLabels', rawLoadout.base_active_labels],
    ['baseAuraLabels', rawLoadout.base_aura_labels],
  ];
  labelSections.forEach(([targetKey, source]) => {
    const target = state[targetKey];
    if (!(target instanceof Map) || !source) {
      return;
    }
    let entries;
    if (Array.isArray(source)) {
      entries = source;
    } else if (typeof source === 'object') {
      entries = Object.entries(source).map(([id, name]) => ({
        id,
        name,
      }));
    } else {
      entries = [];
    }
    entries.forEach((entry) => {
      if (!entry) {
        return;
      }
      const key = resolveLoadoutEntryKey(entry, 'ability_id');
      if (!key) {
        return;
      }
      const rawName = entry.name ?? entry.value ?? entry.label;
      if (rawName === undefined || rawName === null) {
        return;
      }
      const trimmed = String(rawName).trim().slice(0, ABILITY_NAME_MAX_LENGTH);
      if (!trimmed) {
        return;
      }
      target.set(key, trimmed);
    });
  });
  const rawPrimary = rawLoadout.primary_weapon;
  if (rawPrimary && typeof rawPrimary === 'object' && !Array.isArray(rawPrimary)) {
    const safe = {};
    if (Object.prototype.hasOwnProperty.call(rawPrimary, 'melee')) {
      safe.melee = rawPrimary.melee !== null ? String(rawPrimary.melee) : null;
    }
    if (Object.prototype.hasOwnProperty.call(rawPrimary, 'ranged')) {
      safe.ranged = rawPrimary.ranged !== null ? String(rawPrimary.ranged) : null;
    }
    state.primaryWeapon = safe;
  }
  return state;
}

function cloneLoadoutState(state) {
  const cloneSection = (section) => {
    if (section instanceof Map) {
      return new Map(section);
    }
    return new Map();
  };
  if (!state || typeof state !== 'object') {
    return {
      weapons: new Map(),
      active: new Map(),
      aura: new Map(),
      baseActive: new Map(),
      baseAura: new Map(),
      passive: new Map(),
      activeLabels: new Map(),
      auraLabels: new Map(),
      baseActiveLabels: new Map(),
      baseAuraLabels: new Map(),
      mode: 'per_model',
      primaryWeapon: {},
    };
  }
  return {
    weapons: cloneSection(state.weapons),
    active: cloneSection(state.active),
    aura: cloneSection(state.aura),
    baseActive: cloneSection(state.baseActive),
    baseAura: cloneSection(state.baseAura),
    passive: cloneSection(state.passive),
    activeLabels: cloneSection(state.activeLabels),
    auraLabels: cloneSection(state.auraLabels),
    baseActiveLabels: cloneSection(state.baseActiveLabels),
    baseAuraLabels: cloneSection(state.baseAuraLabels),
    mode: state.mode === 'total' ? 'total' : 'per_model',
    primaryWeapon: (state.primaryWeapon && typeof state.primaryWeapon === 'object')
      ? { ...state.primaryWeapon }
      : {},
  };
}

function serializeLoadoutState(state) {
  const result = {
    weapons: [],
    active: [],
    aura: [],
    passive: [],
    active_labels: [],
    aura_labels: [],
    mode: 'total',
  };
  if (!state) {
    return JSON.stringify(result);
  }
  result.mode = state.mode === 'total' ? 'total' : 'per_model';
  state.weapons.forEach((value, id) => {
    result.weapons.push({ id, count: value });
  });
  state.active.forEach((value, id) => {
    result.active.push({ id, count: value });
  });
  state.aura.forEach((value, id) => {
    result.aura.push({ id, count: value });
  });
  state.passive.forEach((value, slug) => {
    result.passive.push({ slug, enabled: Boolean(value) });
  });
  if (state.activeLabels instanceof Map) {
    state.activeLabels.forEach((value, id) => {
      const text = typeof value === 'string' ? value.trim() : String(value || '').trim();
      if (!text) {
        return;
      }
      result.active_labels.push({ id, name: text.slice(0, ABILITY_NAME_MAX_LENGTH) });
    });
  }
  if (state.auraLabels instanceof Map) {
    state.auraLabels.forEach((value, id) => {
      const text = typeof value === 'string' ? value.trim() : String(value || '').trim();
      if (!text) {
        return;
      }
      result.aura_labels.push({ id, name: text.slice(0, ABILITY_NAME_MAX_LENGTH) });
    });
  }
  if (state.primaryWeapon && typeof state.primaryWeapon === 'object'
      && Object.keys(state.primaryWeapon).length > 0) {
    result.primary_weapon = { ...state.primaryWeapon };
  }
  return JSON.stringify(result);
}

function ensureStateEntries(map, entries, idKey, defaultKey, options = {}) {
  const safeEntries = Array.isArray(entries) ? entries : [];
  const fallbackIdKeys = Array.isArray(options.fallbackIdKeys) ? options.fallbackIdKeys : [];
  safeEntries.forEach((entry) => {
    if (!entry) {
      return;
    }
    const key = resolveLoadoutEntryKey(entry, idKey, fallbackIdKeys);
    if (!key) {
      return;
    }
    let defaultCount = Number(entry[defaultKey] ?? 0);
    if (!Number.isFinite(defaultCount) || defaultCount < 0) {
      defaultCount = 0;
    }
    if (!map.has(key)) {
      map.set(key, defaultCount);
    }
  });
}

function ensureBaseStateEntries(map, entries, idKey, defaultKey, options = {}) {
  if (!(map instanceof Map)) {
    return;
  }
  const safeEntries = Array.isArray(entries) ? entries : [];
  const fallbackIdKeys = Array.isArray(options.fallbackIdKeys) ? options.fallbackIdKeys : [];
  safeEntries.forEach((entry) => {
    if (!entry) {
      return;
    }
    const key = resolveLoadoutEntryKey(entry, idKey, fallbackIdKeys);
    if (!key || map.has(key)) {
      return;
    }
    const rawDefault = entry[defaultKey] ?? (entry.is_default ? 1 : 0);
    let defaultCount = Number(rawDefault);
    if (!Number.isFinite(defaultCount) || defaultCount < 0) {
      defaultCount = 0;
    }
    map.set(key, defaultCount);
  });
}

function ensureBaseLabelEntries(map, entries, idKey, options = {}) {
  if (!(map instanceof Map)) {
    return;
  }
  const safeEntries = Array.isArray(entries) ? entries : [];
  const fallbackIdKeys = Array.isArray(options.fallbackIdKeys) ? options.fallbackIdKeys : [];
  safeEntries.forEach((entry) => {
    if (!entry) {
      return;
    }
    const key = resolveLoadoutEntryKey(entry, idKey, fallbackIdKeys);
    if (!key || map.has(key)) {
      return;
    }
    const rawDefault = entry.default_count ?? (entry.is_default ? 1 : 0);
    const defaultCount = Number(rawDefault);
    if (!Number.isFinite(defaultCount) || defaultCount <= 0) {
      return;
    }
    const label = String(entry.label ?? entry.name ?? entry.raw ?? '').trim();
    if (!label) {
      return;
    }
    map.set(key, label.slice(0, ABILITY_NAME_MAX_LENGTH));
  });
}

function ensurePassiveStateEntries(map, entries) {
  const safeEntries = Array.isArray(entries) ? entries : [];
  safeEntries.forEach((entry) => {
    if (!entry) {
      return;
    }
    const slug = entry.slug || entry.value || entry.label;
    if (!slug) {
      return;
    }
    let defaultCount = Number(entry.default_count ?? (entry.is_default ? 1 : 0));
    if (!Number.isFinite(defaultCount) || defaultCount <= 0) {
      defaultCount = 0;
    } else {
      defaultCount = 1;
    }
    const key = String(slug);
    if (!map.has(key)) {
      map.set(key, defaultCount);
    }
  });
}

function formatAbilityDisplayLabel(baseLabel, customName) {
  const base = typeof baseLabel === 'string' ? baseLabel.trim() : '';
  const custom = typeof customName === 'string' ? customName.trim() : '';
  if (custom && base) {
    return `${custom} [${base}]`;
  }
  if (custom) {
    return custom;
  }
  return base;
}

function normalizeLoadoutMode(mode) {
  return mode === 'per_model' ? 'per_model' : 'total';
}

function formatLoadoutCostLabel(costValue, mode) {
  if (costValue === undefined || costValue === null) {
    return 'wliczone';
  }
  const normalizedMode = normalizeLoadoutMode(mode);
  const suffix = normalizedMode === 'per_model' ? 'pkt/model' : 'pkt';
  return `+${formatPoints(costValue)} ${suffix}`;
}

function createModeIndicator(mode) {
  const normalizedMode = normalizeLoadoutMode(mode);
  if (normalizedMode !== 'per_model') {
    return null;
  }
  const indicator = document.createElement('span');
  indicator.className = 'badge rounded-pill text-bg-light border roster-mode-indicator';
  indicator.textContent = 'Tryb: pkt/model';
  indicator.title = 'Wartość dotyczy pojedynczego modelu.';
  return indicator;
}

  const api = {
    normalizeLoadoutKey: normalizeLoadoutKey,
    resolveLoadoutEntryKey: resolveLoadoutEntryKey,
    createLoadoutState: createLoadoutState,
    cloneLoadoutState: cloneLoadoutState,
    serializeLoadoutState: serializeLoadoutState,
    ensureStateEntries: ensureStateEntries,
    ensureBaseStateEntries: ensureBaseStateEntries,
    ensureBaseLabelEntries: ensureBaseLabelEntries,
    ensurePassiveStateEntries: ensurePassiveStateEntries,
    formatAbilityDisplayLabel: formatAbilityDisplayLabel,
    normalizeLoadoutMode: normalizeLoadoutMode,
    formatLoadoutCostLabel: formatLoadoutCostLabel,
    createModeIndicator: createModeIndicator,
  };
  globalScope.SZOPLoadoutState = api;
  globalScope.normalizeLoadoutKey = normalizeLoadoutKey;
  globalScope.resolveLoadoutEntryKey = resolveLoadoutEntryKey;
  globalScope.createLoadoutState = createLoadoutState;
  globalScope.cloneLoadoutState = cloneLoadoutState;
  globalScope.serializeLoadoutState = serializeLoadoutState;
  globalScope.ensureStateEntries = ensureStateEntries;
  globalScope.ensureBaseStateEntries = ensureBaseStateEntries;
  globalScope.ensureBaseLabelEntries = ensureBaseLabelEntries;
  globalScope.ensurePassiveStateEntries = ensurePassiveStateEntries;
  globalScope.formatAbilityDisplayLabel = formatAbilityDisplayLabel;
  globalScope.normalizeLoadoutMode = normalizeLoadoutMode;
  globalScope.formatLoadoutCostLabel = formatLoadoutCostLabel;
  globalScope.createModeIndicator = createModeIndicator;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPLoadoutState = api;
    globalThis.normalizeLoadoutKey = normalizeLoadoutKey;
    globalThis.resolveLoadoutEntryKey = resolveLoadoutEntryKey;
    globalThis.createLoadoutState = createLoadoutState;
    globalThis.cloneLoadoutState = cloneLoadoutState;
    globalThis.serializeLoadoutState = serializeLoadoutState;
    globalThis.ensureStateEntries = ensureStateEntries;
    globalThis.ensureBaseStateEntries = ensureBaseStateEntries;
    globalThis.ensureBaseLabelEntries = ensureBaseLabelEntries;
    globalThis.ensurePassiveStateEntries = ensurePassiveStateEntries;
    globalThis.formatAbilityDisplayLabel = formatAbilityDisplayLabel;
    globalThis.normalizeLoadoutMode = normalizeLoadoutMode;
    globalThis.formatLoadoutCostLabel = formatLoadoutCostLabel;
    globalThis.createModeIndicator = createModeIndicator;
  }
}(typeof window !== 'undefined' ? window : globalThis));
