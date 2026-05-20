(function initSZOPEditorRenderersModule(globalScope) {
  const rosterRendering = globalScope.SZOPRosterRendering || (typeof globalThis !== 'undefined' ? globalThis.SZOPRosterRendering : null) || {};
  const loadoutState = globalScope.SZOPLoadoutState || (typeof globalThis !== 'undefined' ? globalThis.SZOPLoadoutState : null) || {};
  const textParsing = globalScope.SZOPTextParsing || (typeof globalThis !== 'undefined' ? globalThis.SZOPTextParsing : null) || {};
  const formatPoints = rosterRendering.formatPoints || globalScope.formatPoints || function formatPointsFallback(value) {
    return value !== undefined && value !== null ? String(value) : '0';
  };
  const normalizeRangeValue = textParsing.normalizeRangeValue || globalScope.normalizeRangeValue || function normalizeRangeValueFallback(value) { return Number(value) || 0; };
  const resolveLoadoutEntryKey = loadoutState.resolveLoadoutEntryKey || globalScope.resolveLoadoutEntryKey;
  const formatAbilityDisplayLabel = loadoutState.formatAbilityDisplayLabel || globalScope.formatAbilityDisplayLabel || function formatAbilityDisplayLabelFallback(baseLabel, customName) { return customName || baseLabel || ''; };
  const normalizeLoadoutMode = loadoutState.normalizeLoadoutMode || globalScope.normalizeLoadoutMode || function normalizeLoadoutModeFallback(mode) { return mode === 'per_model' ? 'per_model' : 'total'; };
  const formatLoadoutCostLabel = loadoutState.formatLoadoutCostLabel || globalScope.formatLoadoutCostLabel || function formatLoadoutCostLabelFallback(costValue) { return costValue === undefined || costValue === null ? 'wliczone' : `+${formatPoints(costValue)} pkt`; };
  const createModeIndicator = loadoutState.createModeIndicator || globalScope.createModeIndicator || function createModeIndicatorFallback() { return null; };

// ============================================================
// SECTION: EDITOR RENDERERS
// renderAbilityEditor, renderWeaponEditor, toggleSectionVisibility
// Renderują edytory zdolności i broni w prawym panelu rozpiski.
// ============================================================
function renderAbilityEditor(
  container,
  items,
  stateMap,
  labelMap = null,
  modelCount,
  editable,
  onChange,
  stateMode = 'total',
) {

  if (!container) {
    return false;
  }
  container.innerHTML = '';
  const safeItems = Array.isArray(items) ? items : [];
  if (!safeItems.length) {
    return false;
  }
  const wrapper = document.createElement('div');
  wrapper.className = 'd-flex flex-column gap-2';
  const normalizedMode = normalizeLoadoutMode(stateMode);
  const safeLabelMap = labelMap instanceof Map ? labelMap : null;
  const maxCount = Math.max(Number(modelCount) || 0, 0);
  safeItems.forEach((item) => {
    if (!item) {
      return;
    }
    const abilityKey = resolveLoadoutEntryKey(item, 'ability_id');
    if (!abilityKey) {
      return;
    }
    let totalCount = Number(stateMap.get(abilityKey));
    if (!Number.isFinite(totalCount) || totalCount < 0) {
      totalCount = Number(item.default_count ?? 0);
      if (!Number.isFinite(totalCount) || totalCount < 0) {
        totalCount = 0;
      }
    }
    if (maxCount > 0 && totalCount > maxCount) {
      totalCount = maxCount;
    }
    stateMap.set(abilityKey, totalCount);

    const row = document.createElement('div');
    row.className = 'roster-ability-item';

    const info = document.createElement('div');
    info.className = 'roster-ability-details flex-grow-1';
    const name = document.createElement('span');
    name.className = 'roster-ability-label';
    const baseLabel = item.label || 'Zdolność';

    let customName = '';
    if (safeLabelMap && safeLabelMap.has(abilityKey)) {
      const override = safeLabelMap.get(abilityKey);
      if (typeof override === 'string') {
        customName = override.trim();
      } else if (override !== undefined && override !== null) {
        customName = String(override).trim();
      }
    }
    if (!customName && typeof item.custom_name === 'string') {
      customName = item.custom_name;
    }
    if (item.description) {
      name.title = item.description;
    }
    name.textContent = formatAbilityDisplayLabel(baseLabel, customName);

    info.appendChild(name);
    const cost = document.createElement('span');
    cost.className = 'roster-ability-cost';
    cost.textContent = formatLoadoutCostLabel(item.cost, normalizedMode);
    info.appendChild(cost);

    if (!editable && customName) {
      const customInfo = document.createElement('div');
      customInfo.className = 'text-muted small mt-1';
      customInfo.textContent = `Nazwa własna: ${customName}`;

      info.appendChild(customInfo);
    }
    row.appendChild(info);

    const controls = document.createElement('div');
    controls.className = 'roster-ability-controls text-end';
    if (editable) {
      if (normalizedMode === 'per_model') {
        const modeIndicator = createModeIndicator(normalizedMode);
        if (modeIndicator) {
          controls.appendChild(modeIndicator);
        }
      }
      const input = document.createElement('input');
      input.type = 'number';
      input.className = 'form-control form-control-sm roster-count-input';
      input.min = '0';
      input.value = String(totalCount);
      if (maxCount > 0) {
        input.max = String(maxCount);
      }
      input.addEventListener('change', () => {
        let nextValue = Number(input.value);
        if (!Number.isFinite(nextValue) || nextValue < 0) {
          nextValue = 0;
        }
        if (maxCount > 0 && nextValue > maxCount) {
          nextValue = maxCount;
        }
        input.value = String(nextValue);
        stateMap.set(abilityKey, nextValue);
        const hasCustomInput = typeof customInput !== 'undefined' && customInput;
        if (nextValue <= 0) {
          if (typeof applyCustomName === 'function') {
            applyCustomName('');
          }
          if (hasCustomInput) {
            customInput.value = '';
            customInput.disabled = true;
          }
        } else if (hasCustomInput) {
          customInput.disabled = false;
          if (typeof formatDisplayLabel === 'function' && currentCustomName) {
            formatDisplayLabel(currentCustomName);
          }
        }
        if (typeof onChange === 'function') {
          onChange();
        }
      });
      controls.appendChild(input);
    } else {
      const valueDisplay = document.createElement('div');
      valueDisplay.className = 'text-muted small';
      valueDisplay.textContent = `${formatPoints(totalCount)} szt.`;
      controls.appendChild(valueDisplay);
    }

    row.appendChild(controls);
    wrapper.appendChild(row);
  });
  if (!wrapper.childElementCount) {
    return false;
  }
  container.appendChild(wrapper);
  return true;
}

function toggleSectionVisibility(container, isVisible) {
  if (!container) {
    return;
  }
  const wrapper = container.closest('[data-roster-section]');
  if (wrapper) {
    wrapper.classList.toggle('d-none', !isVisible);
  }
}

function renderWeaponEditor(
  container,
  options,
  stateMap,
  modelCount,
  editable,
  onChange,
  stateMode = 'total',
  primaryWeapon = {},
  onPrimaryChange = null,
) {
  if (!container) {
    return false;
  }
  container.innerHTML = '';
  const safeOptions = Array.isArray(options) ? options : [];
  if (!safeOptions.length) {
    return false;
  }
  const normalizedMode = normalizeLoadoutMode(stateMode);
  const numericModelCount = Math.max(Number(modelCount) || 0, 0);
  const weaponInfoMap = new Map();
  const classInfoMap = new Map();
  const inputRefs = new Map();
  const wrapper = document.createElement('div');
  wrapper.className = 'd-flex flex-column gap-2';
  const parseSafeNumber = (value) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) {
      return 0;
    }
    return numeric;
  };
  const getStoredCount = (key, fallback = 0) => {
    if (!(stateMap instanceof Map) || !key) {
      return 0;
    }
    const stored = Number(stateMap.get(key));
    if (Number.isFinite(stored) && stored >= 0) {
      return stored;
    }
    const fallbackNumeric = Number(fallback);
    if (Number.isFinite(fallbackNumeric) && fallbackNumeric >= 0) {
      return fallbackNumeric;
    }
    return 0;
  };
  safeOptions.forEach((option) => {
    if (!option || option.id === undefined || option.id === null) {
      return;
    }
    const weaponId = Number(option.id);
    if (!Number.isFinite(weaponId)) {
      return;
    }
    const weaponKey = resolveLoadoutEntryKey(option, 'id', ['weapon_id']);
    if (!weaponKey) {
      return;
    }
    const normalizedRange = normalizeRangeValue(option.range);
    const weaponClass = normalizedRange > 0 ? 'ranged' : 'melee';
    const defaultPerModel = parseSafeNumber(option.default_count ?? (option.is_default ? 1 : 0));
    const isDefaultWeapon = Boolean(option.is_default) || defaultPerModel > 0;
    const isPrimaryWeapon = Boolean(option.is_primary) && defaultPerModel > 0;
    const weaponMeta = {
      option,
      weaponKey,
      weaponClass,
      defaultPerModel,
      isPrimaryWeapon,
      isDefaultWeapon,
      currentValue: 0,
    };
    weaponInfoMap.set(weaponKey, weaponMeta);
    let classInfo = classInfoMap.get(weaponClass);
    if (!classInfo) {
      classInfo = {
        classKey: weaponClass,
        weapons: [],
        defaultWeapon: null,
        capacity: 0,
        total: 0,
      };
      classInfoMap.set(weaponClass, classInfo);
    }
    let totalCount = Number(stateMap.get(weaponKey));
    if (!Number.isFinite(totalCount) || totalCount < 0) {
      totalCount = Number(option.default_count ?? 0);
      if (!Number.isFinite(totalCount) || totalCount < 0) {
        totalCount = 0;
      }
    }
    stateMap.set(weaponKey, totalCount);
    weaponMeta.currentValue = totalCount;
    classInfo.weapons.push(weaponMeta);
    const safeWeapon = (primaryWeapon && typeof primaryWeapon === 'object') ? primaryWeapon : {};
    const hasOverride = Object.prototype.hasOwnProperty.call(safeWeapon, weaponClass);
    const isCurrentPrimary = hasOverride
      ? (safeWeapon[weaponClass] !== null && safeWeapon[weaponClass] === weaponKey)
      : isPrimaryWeapon;
    classInfo.total += totalCount;
    const assignDefaultWeapon = () => {
      classInfo.defaultWeapon = weaponMeta;
      let capacity = defaultPerModel;
      if (normalizedMode === 'total') {
        const multiplier = numericModelCount > 0 ? numericModelCount : 1;
        capacity *= multiplier;
      }
      if (!Number.isFinite(capacity) || capacity <= 0) {
        capacity = totalCount;
      }
      classInfo.capacity = capacity;
    };
    if (isPrimaryWeapon) {
      assignDefaultWeapon();
    } else if (!classInfo.defaultWeapon && isDefaultWeapon) {
      assignDefaultWeapon();
    }

    const row = document.createElement('div');
    row.className = 'roster-ability-item';

    const info = document.createElement('div');
    info.className = 'roster-ability-details flex-grow-1';
    const name = document.createElement('span');
    name.className = 'roster-ability-label';
    name.textContent = (isCurrentPrimary ? '⚑ ' : '') + (option.name || 'Broń');
    if (editable && typeof onPrimaryChange === 'function') {
      name.style.cursor = 'pointer';
      name.title = isCurrentPrimary
        ? 'Broń podstawowa — kliknij aby przenieść flagę'
        : 'Kliknij aby ustawić jako broń podstawową';
      name.addEventListener('click', () => {
        const next = Object.assign({}, safeWeapon);
        if (isCurrentPrimary) {
          next[weaponClass] = null;
        } else {
          next[weaponClass] = weaponKey;
        }
        onPrimaryChange(next);
      });
    }
    info.appendChild(name);
    const cost = document.createElement('span');
    cost.className = 'roster-ability-cost';
    cost.textContent = formatLoadoutCostLabel(option.cost, normalizedMode);
    info.appendChild(cost);
    const statsLine = document.createElement('div');
    statsLine.className = 'text-muted small mt-1';
    const rangeText = option.range !== undefined && option.range !== null && option.range !== '' ? option.range : '-';
    const attacksText = option.attacks !== undefined && option.attacks !== null && option.attacks !== ''
      ? option.attacks
      : '-';
    const apText = option.ap !== undefined && option.ap !== null && option.ap !== '' ? option.ap : 0;
    const traitsText = option.traits ? String(option.traits) : 'Brak cech';
    statsLine.textContent = `Zasięg: ${rangeText} • Ataki: ${attacksText} • AP: ${apText} • Cechy: ${traitsText}`;
    info.appendChild(statsLine);
    row.appendChild(info);

    const controls = document.createElement('div');
    controls.className = 'roster-ability-controls text-end';
    if (editable) {
      if (normalizedMode === 'per_model') {
        const modeIndicator = createModeIndicator(normalizedMode);
        if (modeIndicator) {
          controls.appendChild(modeIndicator);
        }
      }
      const input = document.createElement('input');
      input.type = 'number';
      input.className = 'form-control form-control-sm roster-count-input';
      input.min = '0';
      input.value = String(totalCount);
      inputRefs.set(weaponKey, input);
      input.addEventListener('change', () => {
        let nextValue = Number(input.value);
        if (!Number.isFinite(nextValue) || nextValue < 0) {
          nextValue = 0;
        }
        input.value = String(nextValue);
        const weaponInfo = weaponInfoMap.get(weaponKey);
        const classInfo = weaponInfo ? classInfoMap.get(weaponInfo.weaponClass) : null;
        const previousValue = getStoredCount(weaponKey);
        let delta = nextValue - previousValue;
        let defaultPrevious = null;
        let defaultNext = null;
        if (
          weaponInfo
          && classInfo
          && classInfo.defaultWeapon
          && classInfo.defaultWeapon.weaponKey !== weaponKey
          && delta !== 0
        ) {
          const defaultWeapon = classInfo.defaultWeapon;
          const defaultKey = defaultWeapon.weaponKey;
          defaultPrevious = getStoredCount(defaultKey);
          const otherTotal = classInfo.weapons.reduce((sum, entry) => {
            if (!entry || entry.weaponKey === weaponKey || entry.weaponKey === defaultKey) {
              return sum;
            }
            return sum + getStoredCount(entry.weaponKey);
          }, 0);
          if (delta > 0) {
            defaultNext = Math.max(defaultPrevious - delta, 0);
          } else {
            const baselineTotal = defaultPrevious + previousValue + otherTotal;
            const effectiveCapacity = Math.max(classInfo.capacity, baselineTotal);
            const desiredDefault = defaultPrevious - delta;
            const maxDefault = Math.max(effectiveCapacity - (otherTotal + nextValue), 0);
            if (desiredDefault > maxDefault) {
              defaultNext = maxDefault;
              const recalculatedOptional = Math.max(
                effectiveCapacity - (otherTotal + defaultNext),
                0,
              );
              if (recalculatedOptional !== nextValue) {
                nextValue = recalculatedOptional;
                delta = nextValue - previousValue;
                input.value = String(nextValue);
              }
            } else {
              defaultNext = desiredDefault;
            }
          }
          if (defaultNext !== null && defaultNext !== defaultPrevious) {
            stateMap.set(defaultKey, defaultNext);
            defaultWeapon.currentValue = defaultNext;
            const defaultInput = inputRefs.get(defaultKey);
            if (defaultInput && defaultInput !== input) {
              defaultInput.value = String(defaultNext);
            }
          }
        }
        stateMap.set(weaponKey, nextValue);
        if (weaponInfo) {
          weaponInfo.currentValue = nextValue;
        }
        if (classInfo) {
          classInfo.total = classInfo.weapons.reduce((sum, entry) => {
            if (!entry) {
              return sum;
            }
            return sum + getStoredCount(entry.weaponKey);
          }, 0);
        }
        if (
          typeof onChange === 'function'
          && (delta !== 0
            || (defaultPrevious !== null && defaultNext !== null && defaultNext !== defaultPrevious))
        ) {
          onChange();
        }
      });
      controls.appendChild(input);
    } else {
      const valueDisplay = document.createElement('div');
      valueDisplay.className = 'text-muted small';
      valueDisplay.textContent = `${formatPoints(totalCount)} szt.`;
      controls.appendChild(valueDisplay);
    }

    row.appendChild(controls);
    wrapper.appendChild(row);
  });
  classInfoMap.forEach((classInfo) => {
    if (!classInfo) {
      return;
    }
    if (!Number.isFinite(classInfo.capacity) || classInfo.capacity <= 0) {
      classInfo.capacity = classInfo.total;
    }
  });
  if (!wrapper.childElementCount) {
    return false;
  }
  container.appendChild(wrapper);
  return true;
}

  const api = {
    renderAbilityEditor: renderAbilityEditor,
    toggleSectionVisibility: toggleSectionVisibility,
    renderWeaponEditor: renderWeaponEditor,
  };
  globalScope.SZOPEditorRenderers = api;
  globalScope.renderAbilityEditor = renderAbilityEditor;
  globalScope.toggleSectionVisibility = toggleSectionVisibility;
  globalScope.renderWeaponEditor = renderWeaponEditor;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPEditorRenderers = api;
    globalThis.renderAbilityEditor = renderAbilityEditor;
    globalThis.toggleSectionVisibility = toggleSectionVisibility;
    globalThis.renderWeaponEditor = renderWeaponEditor;
  }
}(typeof window !== 'undefined' ? window : globalThis));
