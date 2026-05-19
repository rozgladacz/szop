(function initSZOPRosterRenderingModule(globalScope) {
  const payloadAdapters = globalScope.SZOPPayloadAdapters || (typeof globalThis !== 'undefined' ? globalThis.SZOPPayloadAdapters : null) || {
    adaptWeaponOptions(options) { return Array.isArray(options) ? options : []; },
    adaptAbilityEntries(entries) { return Array.isArray(entries) ? entries : []; },
  };

// ============================================================
// SECTION: ROSTER ITEM RENDERING
// formatPoints, createRosterItemElement, renderPassiveEditor
// Tworzą elementy listy rozpiski i edytor pasywek.
// ============================================================
function formatPoints(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value !== undefined && value !== null ? String(value) : '0';
  }
  const baseOptions = { minimumFractionDigits: 0, maximumFractionDigits: 2 };
  if (!Number.isInteger(number)) {
    baseOptions.minimumFractionDigits = 2;
  }
  return number.toLocaleString('pl-PL', baseOptions);
}

function createRosterItemElement(data, options = {}) {
  if (!data || typeof data !== 'object') {
    return null;
  }
  const { rosterId = '', isEditable = false } = options || {};
  const itemId = data.id !== undefined && data.id !== null ? String(data.id) : '';
  const count = Number.isFinite(Number(data.count)) ? Number(data.count) : 1;
  const cachedCost = Number.isFinite(Number(data.cached_cost)) ? Number(data.cached_cost) : 0;
  const unitName = data.unit_name || 'Jednostka';
  const unitQuality = data.unit_quality !== undefined ? data.unit_quality : '-';
  const unitDefense = data.unit_defense !== undefined ? data.unit_defense : '-';
  const unitToughness = data.unit_toughness !== undefined ? data.unit_toughness : '-';
  const unitCacheId =
    data.unit_cache_id !== undefined && data.unit_cache_id !== null
      ? String(data.unit_cache_id)
      : data.unit_id !== undefined && data.unit_id !== null
        ? String(data.unit_id)
        : '';
  const defaultSummary = data.default_summary || '';
  const loadoutSummary = data.loadout_summary || defaultSummary;
  const customName = typeof data.custom_name === 'string' ? data.custom_name : '';
  const weaponOptions = payloadAdapters.adaptWeaponOptions(data.weapon_options, 'roster_item.weapon_options');
  const passiveItems = payloadAdapters.adaptAbilityEntries(data.passive_items, 'passive', 'roster_item.passive_items');
  const activeItems = payloadAdapters.adaptAbilityEntries(data.active_items, 'active', 'roster_item.active_items');
  const auraItems = payloadAdapters.adaptAbilityEntries(data.aura_items, 'aura', 'roster_item.aura_items');
  const baseCostPerModel = Number.isFinite(Number(data.base_cost_per_model))
    ? Number(data.base_cost_per_model)
    : 0;
  const toJsonString = (value, fallback) => {
    const base = value === undefined ? fallback : value;
    try {
      return JSON.stringify(base);
    } catch (err) {
      try {
        return JSON.stringify(fallback);
      } catch (innerErr) {
        if (Array.isArray(fallback)) {
          return '[]';
        }
        if (fallback && typeof fallback === 'object') {
          return '{}';
        }
        return 'null';
      }
    }
  };

  const outer = document.createElement('div');
  outer.className = 'list-group-item border-0 px-0 py-2';
  outer.setAttribute('data-roster-entry', '');

  const entry = document.createElement('div');
  entry.className = 'roster-unit-entry';
  outer.appendChild(entry);

  if (isEditable) {
    const handle = document.createElement('div');
    handle.className = 'roster-drag-handle drag-handle';
    handle.setAttribute('aria-hidden', 'true');
    handle.textContent = '⋮⋮';
    entry.appendChild(handle);

    const reorder = document.createElement('div');
    reorder.className = 'roster-unit-reorder';
    entry.appendChild(reorder);

    ['up', 'down'].forEach((direction) => {
      const form = document.createElement('form');
      form.method = 'post';
      if (rosterId) {
        form.action = `/rosters/${rosterId}/units/${itemId || ''}/move`;
      }
      form.setAttribute('data-roster-move-form', '');

      const hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = 'direction';
      hidden.value = direction;
      form.appendChild(hidden);

      const button = document.createElement('button');
      button.type = 'submit';
      button.className = 'btn btn-outline-secondary btn-sm';
      button.setAttribute('data-roster-move', '');
      button.setAttribute(
        'aria-label',
        direction === 'up' ? 'Przesuń jednostkę w górę' : 'Przesuń jednostkę w dół',
      );
      button.textContent = direction === 'up' ? '↑' : '↓';
      form.appendChild(button);

      reorder.appendChild(form);
    });
  }

  const item = document.createElement('div');
  item.className =
    'roster-unit-item roster-card text-start position-relative flex-grow-1 border rounded p-3 bg-body';
  item.setAttribute('data-roster-item', '');
  if (itemId) {
    item.setAttribute('data-roster-unit-id', itemId);
  }
  item.setAttribute('data-unit-name', unitName);
  item.setAttribute('data-unit-count', String(count));
  item.setAttribute('data-unit-cost', String(cachedCost));
  item.setAttribute('data-base-cost-per-model', String(baseCostPerModel));
  item.setAttribute('data-unit-quality', String(unitQuality));
  item.setAttribute('data-unit-defense', String(unitDefense));
  item.setAttribute('data-unit-toughness', String(unitToughness));
  item.setAttribute('data-unit-custom-name', customName);
  if (unitCacheId) {
    item.setAttribute('data-unit-cache-id', unitCacheId);
  }
  if (data.unit_flags !== undefined && data.unit_flags !== null) {
    item.setAttribute('data-unit-flags', String(data.unit_flags));
  }
  item.setAttribute('data-is-hero', data.is_hero ? 'true' : 'false');
  item.setAttribute('data-default-summary', defaultSummary || '');
  item.setAttribute('data-weapon-options', toJsonString(weaponOptions, []));
  item.setAttribute('data-passives', toJsonString(passiveItems, []));
  item.setAttribute('data-actives', toJsonString(activeItems, []));
  item.setAttribute('data-auras', toJsonString(auraItems, []));
  item.setAttribute('data-selected-passives', toJsonString(data.selected_passive_items, []));
  item.setAttribute('data-selected-actives', toJsonString(data.selected_active_items, []));
  item.setAttribute('data-selected-auras', toJsonString(data.selected_aura_items, []));
  item.setAttribute('data-loadout', toJsonString(data.loadout, {}));
  item.setAttribute('data-unit-classification', toJsonString(data.classification, null));
  item.setAttribute('role', 'button');
  item.setAttribute('tabindex', '0');

  const costBadge = document.createElement('span');
  costBadge.className = 'badge text-bg-primary roster-cost-badge';
  costBadge.setAttribute('data-roster-unit-cost', '');
  costBadge.textContent = `${formatPoints(cachedCost)} pkt`;
  item.appendChild(costBadge);

  const title = document.createElement('div');
  title.className = 'fw-semibold';
  title.setAttribute('data-roster-unit-title', '');
  title.textContent = `${count}x ${unitName}`;
  item.appendChild(title);

  const custom = document.createElement('div');
  custom.className = 'text-muted small';
  custom.setAttribute('data-roster-unit-custom', '');
  const trimmedCustom = customName.trim();
  custom.textContent = trimmedCustom;
  if (!trimmedCustom) {
    custom.classList.add('d-none');
  }
  item.appendChild(custom);

  const stats = document.createElement('div');
  stats.className = 'text-muted small';
  stats.textContent = `Jakość ${unitQuality} / Obrona ${unitDefense} / Wytrzymałość ${unitToughness}`;
  item.appendChild(stats);

  const abilities = document.createElement('div');
  abilities.className = 'd-flex flex-wrap gap-1 mt-2';
  abilities.setAttribute('data-roster-unit-abilities', '');
  item.appendChild(abilities);

  const loadoutEl = document.createElement('div');
  loadoutEl.className = 'text-muted small mt-2';
  loadoutEl.setAttribute('data-roster-unit-loadout', '');
  loadoutEl.textContent = `Uzbrojenie: ${loadoutSummary || '-'}`;
  item.appendChild(loadoutEl);

  entry.appendChild(item);

  return outer;
}

function renderPassiveEditor(
  container,
  items,
  stateMap,
  modelCount,
  editable,
  onChange,
  getDelta,
  heroContext,
) {
  if (!container) {
    return false;
  }
  container.innerHTML = '';
  const safeItems = (Array.isArray(items) ? items : []).filter(
    (entry) => entry && !entry.is_army_rule,
  );
  if (!safeItems.length) {
    return false;
  }
  const totalModels = Math.max(Number(modelCount) || 0, 0);
  const wrapper = document.createElement('div');
  wrapper.className = 'd-flex flex-column gap-2';
  safeItems.forEach((entry) => {
    if (!entry || !entry.slug) {
      return;
    }
    const slug = String(entry.slug);
    const normalizedSlug = slug.trim().toLowerCase();
    const isLockedAbility = Boolean(entry.is_mandatory);
    let currentValue = Number(stateMap.get(slug));
    if (!Number.isFinite(currentValue)) {
      currentValue = Number(entry.default_count ?? (entry.is_default ? 1 : 0));
    }
    if (!Number.isFinite(currentValue) || currentValue <= 0) {
      currentValue = 0;
    } else {
      currentValue = 1;
    }
    if (isLockedAbility) {
      currentValue = 1;
    }
    stateMap.set(slug, currentValue);

    const row = document.createElement('div');
    row.className = 'roster-ability-item';

    const info = document.createElement('div');
    info.className = 'roster-ability-details flex-grow-1';
    const name = document.createElement('span');
    name.className = 'roster-ability-label';
    name.textContent = entry.label || entry.raw || slug;
    if (entry.description) {
      name.title = entry.description;
    }
    info.appendChild(name);
    const cost = document.createElement('span');
    cost.className = 'roster-ability-cost';
    const costValue = Number(entry.cost);
    const multiplier = Math.max(totalModels, 1);
    let currentFlag = currentValue > 0 ? 1 : 0;
    if (isLockedAbility) {
      currentFlag = 1;
    }
    const computeDelta = () => {
      if (typeof getDelta === 'function') {
        try {
          const context = {
            slug,
            entry,
            currentFlag,
            models: totalModels,
          };
          const deltaResult = getDelta(context);
          if (deltaResult && typeof deltaResult === 'object' && Object.prototype.hasOwnProperty.call(deltaResult, 'diff')) {
            const diffValue = Number(deltaResult.diff);
            if (Number.isFinite(diffValue)) {
              return diffValue;
            }
          }
          const numericResult = Number(deltaResult);
          if (Number.isFinite(numericResult)) {
            return numericResult;
          }
        } catch (err) {
          console.warn('Nie udało się obliczyć kosztu zdolności pasywnej', slug, err);
        }
      }
      if (Number.isFinite(costValue)) {
        return costValue * multiplier;
      }
      return Number.NaN;
    };
    let deltaValue = computeDelta();
    const normalizeDeltaForDisplay = (value) => {
      const numericValue = Number(value);
      if (!Number.isFinite(numericValue)) {
        return Number.NaN;
      }
      const roundedValue = Math.round(numericValue * 100) / 100;
      const roundedInteger = Math.round(roundedValue);
      if (Math.abs(roundedValue - roundedInteger) < 0.005) {
        return roundedInteger;
      }
      return roundedValue;
    };
    const formatDeltaText = () => {
      const normalizedDelta = normalizeDeltaForDisplay(deltaValue);
      if (!Number.isFinite(normalizedDelta) || Math.abs(normalizedDelta) < 0.005) {
        return 'Δ 0 pkt';
      }
      const prefix = normalizedDelta > 0 ? '+' : '-';
      return `Δ ${prefix}${formatPoints(Math.abs(normalizedDelta))} pkt`;
    };
    cost.textContent = formatDeltaText();
    info.appendChild(cost);
    row.appendChild(info);

    const controls = document.createElement('div');
    controls.className = 'roster-ability-controls text-end';

    const isHeroBohater = normalizedSlug === 'bohater';
    if (editable && isHeroBohater && heroContext && heroContext.rosterId) {
      // Replace the on/off toggle with a "Dołącz do:" selector that calls the
      // attach/detach endpoints. Page reloads to reflect the new grouping.
      const heroWrap = document.createElement('div');
      heroWrap.className = 'd-flex align-items-center gap-2 flex-wrap';
      heroWrap.style.minWidth = '190px';

      const selectLabel = document.createElement('label');
      selectLabel.className = 'form-label small mb-0';
      selectLabel.textContent = 'Dołącz do:';
      const selectId = `hero-attach-${slug}-${Math.random().toString(16).slice(2)}`;
      selectLabel.setAttribute('for', selectId);
      heroWrap.appendChild(selectLabel);

      const heroSelect = document.createElement('select');
      heroSelect.className = 'form-select form-select-sm';
      heroSelect.id = selectId;
      const noneOpt = document.createElement('option');
      noneOpt.value = '';
      noneOpt.textContent = '— (samodzielny)';
      heroSelect.appendChild(noneOpt);
      (heroContext.attachable || [])
        .filter((u) => u && u.id && String(u.id) !== String(heroContext.rosterUnitId))
        .forEach((u) => {
          const opt = document.createElement('option');
          opt.value = String(u.id);
          opt.textContent = u.label || `Oddział ${u.id}`;
          heroSelect.appendChild(opt);
        });
      heroSelect.value = heroContext.currentParentId || '';
      heroWrap.appendChild(heroSelect);

      const errorBox = document.createElement('div');
      errorBox.className = 'text-danger small d-none';
      heroWrap.appendChild(errorBox);

      heroSelect.addEventListener('change', () => {
        const newParentId = heroSelect.value;
        const { rosterId: rId, rosterUnitId: ruId } = heroContext;
        if (!rId || !ruId) {
          errorBox.textContent = 'Nie można ustalić kontekstu dołączenia.';
          errorBox.classList.remove('d-none');
          return;
        }
        errorBox.classList.add('d-none');
        heroSelect.disabled = true;
        const isAttach = Boolean(newParentId);
        const url = isAttach
          ? `/rosters/${rId}/units/${ruId}/attach`
          : `/rosters/${rId}/units/${ruId}/detach`;
        const init = {
          method: 'POST',
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        };
        if (isAttach) {
          init.headers['Content-Type'] = 'application/json';
          init.body = JSON.stringify({ parent_roster_unit_id: Number(newParentId) });
        }
        fetch(url, init)
          .then((r) => {
            if (!r.ok) {
              return r.text().then((t) => { throw new Error(t || `HTTP ${r.status}`); });
            }
            return r.json();
          })
          .then(() => { window.location.reload(); })
          .catch((err) => {
            heroSelect.disabled = false;
            errorBox.textContent = `Błąd: ${err && err.message ? err.message : String(err)}`;
            errorBox.classList.remove('d-none');
          });
      });

      controls.appendChild(heroWrap);
    } else if (editable) {
      const wrapperCheck = document.createElement('div');
      wrapperCheck.className = 'form-check form-switch mb-0';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'form-check-input';
      input.id = `passive-${slug}-${Math.random().toString(16).slice(2)}`;
      input.checked = currentFlag > 0;
      if (isLockedAbility) {
        input.disabled = true;
      }
      const label = document.createElement('label');
      label.className = 'form-check-label small';
      label.setAttribute('for', input.id);
      const updateLabel = () => {
        if (isLockedAbility) {
          label.textContent = 'Zawsze aktywna';
          return;
        }
        label.textContent = input.checked ? 'Aktywna' : 'Wyłączona';
      };
      updateLabel();
      if (!isLockedAbility) {
        input.addEventListener('change', () => {
          const flag = input.checked ? 1 : 0;
          stateMap.set(slug, flag);
          currentFlag = flag;
          deltaValue = computeDelta();
          cost.textContent = formatDeltaText();
          updateLabel();
          if (typeof onChange === 'function') {
            onChange();
          }
        });
      }
      wrapperCheck.appendChild(input);
      wrapperCheck.appendChild(label);
      controls.appendChild(wrapperCheck);
    } else {
      const status = document.createElement('div');
      status.className = 'text-muted small';
      status.textContent = currentFlag > 0 ? 'Aktywna' : 'Wyłączona';
      controls.appendChild(status);
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

  const api = {
    formatPoints: formatPoints,
    createRosterItemElement: createRosterItemElement,
    renderPassiveEditor: renderPassiveEditor,
  };
  globalScope.SZOPRosterRendering = api;
  globalScope.formatPoints = formatPoints;
  globalScope.createRosterItemElement = createRosterItemElement;
  globalScope.renderPassiveEditor = renderPassiveEditor;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPRosterRendering = api;
    globalThis.formatPoints = formatPoints;
    globalThis.createRosterItemElement = createRosterItemElement;
    globalThis.renderPassiveEditor = renderPassiveEditor;
  }
}(typeof window !== 'undefined' ? window : globalThis));
