(function initPayloadAdaptersModule(globalScope) {
  function isDevMode() {
    return globalScope.SZOP_DEV_MODE === true;
  }

  function hasOwn(value, key) {
    return Boolean(value && Object.prototype.hasOwnProperty.call(value, key));
  }

  function logMissing(moduleName, path) {
    if (!isDevMode()) {
      return;
    }
    const name = moduleName || 'unknown';
    if (globalScope.console && typeof globalScope.console.error === 'function') {
      globalScope.console.error(`[SZOPPayload:${name}] Missing field: ${path}`);
    }
  }

  function requireFields(moduleName, payload, fields) {
    if (!isDevMode()) {
      return true;
    }
    let ok = true;
    fields.forEach((field) => {
      if (!hasOwn(payload, field)) {
        logMissing(moduleName, field);
        ok = false;
      }
    });
    return ok;
  }

  function assertQuotePayloadShape(moduleName, payload) {
    if (!payload || typeof payload !== 'object') {
      logMissing(moduleName, '<payload>');
      return false;
    }
    let ok = requireFields(moduleName, payload, [
      'selected_total',
      'loadout',
      'item_costs',
    ]);
    if (!hasOwn(payload, 'roster_unit_id') && !hasOwn(payload, 'unit_id')) {
      logMissing(moduleName, 'roster_unit_id|unit_id');
      ok = false;
    }
    return ok;
  }

  function assertItemCostsShape(moduleName, itemCosts) {
    if (!itemCosts || typeof itemCosts !== 'object') {
      logMissing(moduleName, 'item_costs');
      return false;
    }
    return requireFields(moduleName, itemCosts, [
      'weapons',
      'active',
      'aura',
      'passive_deltas',
    ]);
  }

  function assertWeaponOptionsShape(moduleName, options) {
    if (!Array.isArray(options)) {
      logMissing(moduleName, 'weapon_options');
      return false;
    }
    let ok = true;
    options.forEach((entry, index) => {
      if (!entry || typeof entry !== 'object') {
        logMissing(moduleName, `weapon_options[${index}]`);
        ok = false;
        return;
      }
      ['id', 'name'].forEach((field) => {
        if (!hasOwn(entry, field)) {
          logMissing(moduleName, `weapon_options[${index}].${field}`);
          ok = false;
        }
      });
    });
    return ok;
  }

  function assertAbilityEntriesShape(moduleName, entries) {
    if (!Array.isArray(entries)) {
      logMissing(moduleName, 'ability_entries');
      return false;
    }
    let ok = true;
    entries.forEach((entry, index) => {
      if (!entry || typeof entry !== 'object') {
        logMissing(moduleName, `ability_entries[${index}]`);
        ok = false;
        return;
      }
      if (!hasOwn(entry, 'loadout_key') && !hasOwn(entry, 'ability_id') && !hasOwn(entry, 'id')) {
        logMissing(moduleName, `ability_entries[${index}].loadout_key|ability_id|id`);
        ok = false;
      }
      if (!hasOwn(entry, 'label') && !hasOwn(entry, 'raw') && !hasOwn(entry, 'slug')) {
        logMissing(moduleName, `ability_entries[${index}].label|raw|slug`);
        ok = false;
      }
    });
    return ok;
  }

  function numericOr(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function stringKey(value) {
    if (value === undefined || value === null) {
      return '';
    }
    return String(value);
  }

  function normalizeCostMap(source) {
    const result = {};
    if (!source || typeof source !== 'object') {
      return result;
    }
    Object.entries(source).forEach(([key, value]) => {
      const normalizedKey = stringKey(key).trim();
      if (!normalizedKey) {
        return;
      }
      const numeric = Number(value);
      if (Number.isFinite(numeric)) {
        result[normalizedKey] = numeric;
      }
    });
    return result;
  }

  function adaptItemCosts(itemCosts, moduleName = 'item_costs') {
    const source = itemCosts && typeof itemCosts === 'object' ? itemCosts : {};
    assertItemCostsShape(moduleName, source);
    return {
      weapons: normalizeCostMap(source.weapons),
      active: normalizeCostMap(source.active),
      aura: normalizeCostMap(source.aura),
      passiveDeltas: normalizeCostMap(source.passive_deltas || source.passiveDeltas),
    };
  }

  function adaptQuotePayload(payload, requestedRosterUnitId, moduleName = 'quote') {
    const source = payload && typeof payload === 'object' ? payload : {};
    assertQuotePayloadShape(moduleName, source);
    const selectedTotal = Number(source.selected_total);
    const rawRosterUnitId = source.roster_unit_id ?? source.unit_id ?? requestedRosterUnitId;
    return {
      total: selectedTotal,
      rosterUnitId: stringKey(rawRosterUnitId || requestedRosterUnitId),
      loadout: source.loadout && typeof source.loadout === 'object' ? source.loadout : null,
      itemCosts: adaptItemCosts(source.item_costs, `${moduleName}.item_costs`),
      selectedRole: typeof source.selected_role === 'string' ? source.selected_role : null,
    };
  }

  function adaptWeaponOptions(options, moduleName = 'weapon_options') {
    const source = Array.isArray(options) ? options : [];
    assertWeaponOptionsShape(moduleName, source);
    return source
      .filter((entry) => entry && typeof entry === 'object')
      .map((entry) => {
        const normalized = { ...entry };
        normalized.id = stringKey(entry.id ?? entry.weapon_id);
        normalized.weapon_id = normalized.id;
        normalized.name = stringKey(entry.name || entry.label || '');
        normalized.cost = numericOr(entry.cost, 0);
        normalized.default_count = numericOr(entry.default_count, entry.is_default ? 1 : 0);
        normalized.is_default = Boolean(entry.is_default);
        normalized.is_primary = Boolean(entry.is_primary);
        return normalized;
      });
  }

  function adaptAbilityEntries(entries, kind = 'ability_entries', moduleName = kind) {
    const source = Array.isArray(entries) ? entries : [];
    assertAbilityEntriesShape(moduleName, source);
    return source
      .filter((entry) => entry && typeof entry === 'object')
      .map((entry) => {
        const normalized = { ...entry };
        const key = entry.loadout_key ?? entry.ability_id ?? entry.id ?? entry.slug;
        normalized.loadout_key = stringKey(key);
        if (entry.ability_id !== undefined && entry.ability_id !== null) {
          normalized.ability_id = stringKey(entry.ability_id);
        }
        if (entry.id !== undefined && entry.id !== null) {
          normalized.id = stringKey(entry.id);
        }
        normalized.label = stringKey(entry.label ?? entry.raw ?? entry.slug ?? '');
        normalized.raw = stringKey(entry.raw ?? entry.label ?? entry.slug ?? normalized.label);
        normalized.custom_name = typeof entry.custom_name === 'string' ? entry.custom_name : '';
        normalized.cost = numericOr(entry.cost, 0);
        normalized.default_count = numericOr(entry.default_count, entry.is_default ? 1 : 0);
        normalized.is_default = Boolean(entry.is_default);
        normalized.kind = normalized.kind || kind;
        return normalized;
      });
  }

  globalScope.SZOPPayloadAdapters = {
    assertQuotePayloadShape,
    assertItemCostsShape,
    assertWeaponOptionsShape,
    assertAbilityEntriesShape,
    adaptQuotePayload,
    adaptItemCosts,
    adaptWeaponOptions,
    adaptAbilityEntries,
  };
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPPayloadAdapters = globalScope.SZOPPayloadAdapters;
  }
}(typeof window !== 'undefined' ? window : globalThis));
