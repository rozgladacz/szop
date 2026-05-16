// ============================================================
// SECTION: GLOBAL STATE & REFRESH TOKEN UTILS
// normalizeRosterRefreshCycleToken, resolveRosterRefreshPriority
// Globalne zmienne stanu + narzędzia wersjonowania odświeżeń.
// ============================================================
const abilityDefinitionsCache = new Map();
const ARMY_RULE_OFF_PREFIX = '__army_off__';
const ABILITY_NAME_MAX_LENGTH = window.SZOPTextParsing?.ABILITY_NAME_MAX_LENGTH || 60;

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
// initAbilityPicker, initAbilityPickers — picker zdolności w edytorze
// ============================================================
function initAbilityPicker(root) {
  const definitionsData = root.dataset.definitions || '';
  let definitions;
  if (abilityDefinitionsCache.has(definitionsData)) {
    definitions = abilityDefinitionsCache.get(definitionsData);
  } else {
    definitions = definitionsData ? JSON.parse(definitionsData) : [];
    abilityDefinitionsCache.set(definitionsData, definitions);
  }
  const definitionMap = new Map(definitions.map((item) => [item.slug, item]));
  const targetId = root.dataset.targetInput;
  const hiddenInput = targetId ? document.getElementById(targetId) : root.querySelector('input[type="hidden"]');
  const selectEl = root.querySelector('.ability-picker-select');
  const valueContainer = root.querySelector('.ability-picker-value');
  const valueInput = root.querySelector('.ability-picker-value-input');
  const valueSelect = root.querySelector('.ability-picker-value-select');
  const addButton = root.querySelector('.ability-picker-add');
  const listEl = root.querySelector('.ability-picker-list');
  const allowDefaultToggle = root.dataset.defaultToggle === 'true';
  const defaultInitial = root.dataset.defaultInitial === 'true';
  const allowMandatoryToggle = root.dataset.mandatoryToggle === 'true';
  const mandatoryInitial = root.dataset.mandatoryInitial === 'true';
  const allowCustomName = root.dataset.allowCustomName === 'true';
  const hideOwnedAbilities = root.dataset.hideOwnedAbilities === 'true';
  let isUpdatingSelectOptions = false;
  let items = [];

  function getDefinition(slug) {
    if (!slug) {
      return null;
    }
    return definitionMap.get(slug) || null;
  }

  function formatLabel(definition, value, choiceLabel) {
    const displayValue = (choiceLabel || value || '').toString().trim();
    if (!definition) {
      return displayValue;
    }
    if (definition.slug === 'aura' || definition.slug === 'aura_12') {
      if (choiceLabel) {
        return choiceLabel;
      }
      if (value) {
        const [abilityRef, rangeRefRaw] = String(value).split('|', 2);
        const rangeRef = (rangeRefRaw || '').trim().replace(/["”]/g, '');
        const isLongRange = definition.slug === 'aura_12' || rangeRef === '12';
        const baseName = definition.slug === 'aura_12'
          ? definition.name.replace(/\(12"\)$/, '').trim() || definition.name
          : definition.name;
        const prefix = isLongRange ? `${baseName}(12")` : baseName;
        const abilityLabel = (abilityRef || '').trim();
        return abilityLabel ? `${prefix}: ${abilityLabel}` : prefix;
      }
      return definition.display_name || definition.name;
    }
    if (definition.slug === 'rozkaz' || definition.slug === 'klatwa' || definition.slug === 'oznaczenie') {
      const valueLabel = displayValue || value || '';
      return valueLabel
        ? `${definition.name}: ${valueLabel}`
        : definition.display_name || definition.name;
    }
    if (definition.requires_value) {
      return displayValue ? `${definition.name}(${displayValue})` : definition.display_name;
    }
    return definition.name;
  }

  function descriptionFor(item) {
    if (item.description) {
      return item.description;
    }
    const definition = getDefinition(item.slug);
    return definition ? definition.description : '';
  }

  function normalizeEntry(entry) {
    const slug = entry.slug || '';
    const definition = getDefinition(slug);
    const rawValue = entry.value !== undefined && entry.value !== null ? String(entry.value) : '';
    const rawLabel = entry.raw !== undefined && entry.raw !== null ? String(entry.raw) : '';
    const label = entry.label || formatLabel(definition, rawValue, rawLabel);
    const abilityId = entry.ability_id ?? (definition && Object.prototype.hasOwnProperty.call(definition, 'ability_id') ? definition.ability_id : null);
    let isDefault = allowDefaultToggle ? Boolean(entry.is_default ?? defaultInitial) : false;
    const isMandatory = allowMandatoryToggle
      ? Boolean(entry.is_mandatory ?? mandatoryInitial)
      : Boolean(entry.is_mandatory ?? false);
    if (allowDefaultToggle && isMandatory && !isDefault) {
      isDefault = true;
    }
    const baseLabel = entry.base_label || label || rawLabel || rawValue;
    let customName = '';
    if (typeof entry.custom_name === 'string') {
      customName = entry.custom_name.trim().slice(0, ABILITY_NAME_MAX_LENGTH);
    }
    return {
      slug,
      value: rawValue,
      raw: rawLabel || rawValue || baseLabel,
      label: baseLabel || rawLabel || rawValue,
      base_label: baseLabel || '',
      custom_name: customName,
      ability_id: abilityId,
      is_default: isDefault,
      is_mandatory: isMandatory,
      description: entry.description || descriptionFor({ slug }),
      cost: entry.cost !== undefined ? entry.cost : undefined,
    };
  }

  function abilityKey(item) {
    if (!item) {
      return '';
    }
    const slug = (item.slug || '').toString().trim().toLowerCase();
    const value = (item.value || '').toString().trim().toLowerCase();
    const raw = (item.raw || item.label || '').toString().trim().toLowerCase();
    if (!slug || slug === '__custom__') {
      return raw ? `custom::${raw}` : '';
    }
    if (slug === 'aura' || slug === 'aura_12' || slug === 'rozkaz' || slug === 'klatwa' || slug === 'oznaczenie') {
      return `${slug}::${value || raw}`;
    }
    if (slug === 'rozprysk' || slug === 'zabojczy') {
      return slug;
    }
    return slug;
  }

  function isDuplicateAbility(entry) {
    const key = abilityKey(entry);
    if (!key) {
      return false;
    }
    return items.some((existing) => abilityKey(existing) === key);
  }

  function parseInitial() {
    if (!hiddenInput || !hiddenInput.value) {
      items = [];
      return;
    }
    try {
      const parsed = JSON.parse(hiddenInput.value);
      if (Array.isArray(parsed)) {
        items = parsed.map((entry) => normalizeEntry(entry || {}));
      }
    } catch (err) {
      console.warn('Nie udało się odczytać wybranych zdolności', err);
      items = [];
    }
  }

  function updateHidden() {
    if (!hiddenInput) {
      return;
    }
    const safeItems = items.map((entry) => {
      const slugValue =
        entry && entry.slug !== undefined && entry.slug !== null
          ? String(entry.slug)
          : '';
      const labelValue = (() => {
        if (entry && typeof entry.label === 'string' && entry.label) {
          return entry.label;
        }
        if (entry && typeof entry.base_label === 'string' && entry.base_label) {
          return entry.base_label;
        }
        if (entry && typeof entry.raw === 'string' && entry.raw) {
          return entry.raw;
        }
        return slugValue;
      })();
      const payload = {
        slug: slugValue,
        value: entry.value,
        label: labelValue,
        raw: entry.raw,
        ability_id: entry.ability_id ?? null,
        is_default: Boolean(entry.is_default),
      };
      if (allowMandatoryToggle || entry.is_mandatory) {
        payload.is_mandatory = Boolean(entry.is_mandatory);
      }
      if (allowCustomName) {
        const customName = typeof entry.custom_name === 'string' ? entry.custom_name.trim() : '';
        if (customName) {
          payload.custom_name = customName.slice(0, ABILITY_NAME_MAX_LENGTH);
        }
      }
      if (entry.base_label) {
        payload.base_label = entry.base_label;
      }
      return payload;
    });
    hiddenInput.value = JSON.stringify(safeItems);
  }

  function moveItem(fromIndex, toIndex) {
    if (!Array.isArray(items)) {
      return;
    }
    const lastIndex = items.length - 1;
    if (
      fromIndex === toIndex ||
      fromIndex < 0 ||
      toIndex < 0 ||
      fromIndex > lastIndex ||
      toIndex > lastIndex
    ) {
      return;
    }
    const [entry] = items.splice(fromIndex, 1);
    items.splice(toIndex, 0, entry);
    updateHidden();
    renderList();
  }

  let sortableInstance = null;

  function renderList() {
    if (!listEl) {
      return;
    }
    listEl.innerHTML = '';
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'text-muted mb-0';
      empty.textContent = 'Brak wybranych zdolności.';
      listEl.appendChild(empty);
      updateSelectOptionVisibility();
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex flex-column gap-2';
    items.forEach((item, index) => {
      const row = document.createElement('div');
      row.className = 'border rounded p-2 d-flex flex-wrap align-items-center gap-2';

      const labelWrapper = document.createElement('div');
      labelWrapper.className = 'flex-grow-1 d-flex flex-column gap-1';
      const baseLabel = item.base_label || item.label || item.raw || item.slug;
      const desc = descriptionFor(item);

      const nameRow = document.createElement('div');
      nameRow.className = 'd-flex align-items-baseline gap-2 flex-wrap';
      const labelText = document.createElement('span');
      labelText.textContent = formatAbilityDisplayLabel(baseLabel, item.custom_name) || baseLabel;
      if (desc) {
        labelText.title = desc;
      }
      nameRow.appendChild(labelText);

      const itemDef = getDefinition(item.slug);
      const itemCost = item.cost !== undefined ? item.cost : itemDef?.cost_hint;
      if (itemCost !== null && itemCost !== undefined) {
        const costSpan = document.createElement('span');
        costSpan.className = 'text-muted small';
        costSpan.textContent = `+${formatPoints(itemCost)} pkt`;
        nameRow.appendChild(costSpan);
      }

      labelWrapper.appendChild(nameRow);

      if (allowCustomName) {
        const inputId = `ability-picker-name-${index}-${Math.random().toString(16).slice(2)}`;
        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.className = 'form-control form-control-sm';
        nameInput.id = inputId;
        nameInput.placeholder = 'Nazwa własna (opcjonalnie)';
        nameInput.maxLength = ABILITY_NAME_MAX_LENGTH;
        nameInput.value = item.custom_name || '';
        const applyValue = (value) => {
          const limited = typeof value === 'string' ? value.slice(0, ABILITY_NAME_MAX_LENGTH) : '';
          if (limited !== nameInput.value) {
            nameInput.value = limited;
          }
          const normalized = limited.trim();
          item.custom_name = normalized;
          labelText.textContent = formatAbilityDisplayLabel(baseLabel, normalized) || baseLabel;
          updateHidden();
        };
        nameInput.addEventListener('input', () => {
          applyValue(nameInput.value);
        });
        nameInput.addEventListener('change', () => {
          applyValue(nameInput.value);
        });
        nameInput.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            nameInput.blur();
          }
        });
        labelWrapper.appendChild(nameInput);
      }

      row.appendChild(labelWrapper);

      if (allowDefaultToggle || allowMandatoryToggle) {
        const toggleWrapper = document.createElement('div');
        toggleWrapper.className = 'd-flex flex-column gap-1 mb-0';

        let defaultInput;
        let mandatoryInput;

        const syncDefaultState = () => {
          if (!allowDefaultToggle || !defaultInput) {
            return;
          }
          const shouldDisable = allowMandatoryToggle && Boolean(item.is_mandatory);
          defaultInput.disabled = shouldDisable;
          if (shouldDisable) {
            defaultInput.checked = true;
            item.is_default = true;
          }
        };

        if (allowDefaultToggle) {
          const defaultWrapper = document.createElement('div');
          defaultWrapper.className = 'form-check mb-0';
          defaultInput = document.createElement('input');
          defaultInput.type = 'checkbox';
          defaultInput.className = 'form-check-input';
          defaultInput.id = `ability-default-${index}-${Math.random().toString(16).slice(2)}`;
          defaultInput.checked = Boolean(item.is_default);
          defaultInput.addEventListener('change', () => {
            const checked = defaultInput.checked;
            item.is_default = checked;
            if (!checked && allowMandatoryToggle && item.is_mandatory) {
              item.is_mandatory = false;
              if (mandatoryInput) {
                mandatoryInput.checked = false;
              }
              syncDefaultState();
            }
            updateHidden();
          });
          const defaultLabel = document.createElement('label');
          defaultLabel.className = 'form-check-label small';
          defaultLabel.setAttribute('for', defaultInput.id);
          defaultLabel.textContent = 'Domyślna';
          defaultWrapper.appendChild(defaultInput);
          defaultWrapper.appendChild(defaultLabel);
          toggleWrapper.appendChild(defaultWrapper);
        }

        if (allowMandatoryToggle) {
          const mandatoryWrapper = document.createElement('div');
          mandatoryWrapper.className = 'form-check mb-0';
          mandatoryInput = document.createElement('input');
          mandatoryInput.type = 'checkbox';
          mandatoryInput.className = 'form-check-input';
          mandatoryInput.id = `ability-mandatory-${index}-${Math.random().toString(16).slice(2)}`;
          mandatoryInput.checked = Boolean(item.is_mandatory);
          mandatoryInput.addEventListener('change', () => {
            const checked = mandatoryInput.checked;
            item.is_mandatory = checked;
            if (checked && allowDefaultToggle && defaultInput && !defaultInput.checked) {
              defaultInput.checked = true;
              item.is_default = true;
            }
            syncDefaultState();
            updateHidden();
          });
          const mandatoryLabel = document.createElement('label');
          mandatoryLabel.className = 'form-check-label small';
          mandatoryLabel.setAttribute('for', mandatoryInput.id);
          mandatoryLabel.textContent = 'Obowiązkowe';
          mandatoryWrapper.appendChild(mandatoryInput);
          mandatoryWrapper.appendChild(mandatoryLabel);
          toggleWrapper.appendChild(mandatoryWrapper);
        }

        syncDefaultState();
        row.appendChild(toggleWrapper);
      }

      const controlsWrapper = document.createElement('div');
      controlsWrapper.className = 'd-flex flex-column flex-sm-row gap-2 align-items-center';

      if (typeof Sortable !== 'undefined') {
        const handle = document.createElement('span');
        handle.className = 'drag-handle ability-drag-handle';
        handle.setAttribute('aria-hidden', 'true');
        handle.textContent = '⋮⋮';
        controlsWrapper.appendChild(handle);
      }

      const reorderGroup = document.createElement('div');
      reorderGroup.className = 'btn-group-vertical ability-move-buttons';
      const moveUpBtn = document.createElement('button');
      moveUpBtn.type = 'button';
      moveUpBtn.className = 'btn btn-outline-secondary btn-sm';
      moveUpBtn.textContent = '↑';
      moveUpBtn.setAttribute('aria-label', 'Przesuń w górę');
      moveUpBtn.disabled = index === 0;
      moveUpBtn.addEventListener('click', (event) => {
        event.preventDefault();
        moveItem(index, index - 1);
      });
      const moveDownBtn = document.createElement('button');
      moveDownBtn.type = 'button';
      moveDownBtn.className = 'btn btn-outline-secondary btn-sm';
      moveDownBtn.textContent = '↓';
      moveDownBtn.setAttribute('aria-label', 'Przesuń w dół');
      moveDownBtn.disabled = index === items.length - 1;
      moveDownBtn.addEventListener('click', (event) => {
        event.preventDefault();
        moveItem(index, index + 1);
      });
      reorderGroup.appendChild(moveUpBtn);
      reorderGroup.appendChild(moveDownBtn);
      controlsWrapper.appendChild(reorderGroup);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-outline-danger btn-sm';
      removeBtn.textContent = 'Usuń';
      removeBtn.addEventListener('click', () => {
        items.splice(index, 1);
        updateHidden();
        renderList();
      });
      controlsWrapper.appendChild(removeBtn);

      row.appendChild(controlsWrapper);

      wrapper.appendChild(row);
    });

    if (typeof Sortable !== 'undefined') {
      if (sortableInstance) sortableInstance.destroy();
      wrapper.classList.add('ability-list-dnd-active');
      sortableInstance = Sortable.create(wrapper, {
        handle: '.ability-drag-handle',
        animation: 150,
        ghostClass: 'ability-row-ghost',
        onEnd(evt) {
          if (evt.oldIndex === evt.newIndex) return;
          const moved = items.splice(evt.oldIndex, 1)[0];
          items.splice(evt.newIndex, 0, moved);
          updateHidden();
          renderList();
        },
      });
    }

    listEl.appendChild(wrapper);

    updateSelectOptionVisibility();
  }

  function updateSelectOptionVisibility() {
    if (!hideOwnedAbilities || !selectEl) {
      return;
    }
    const usedKeys = new Set(
      items
        .map((entry) => abilityKey(entry))
        .filter((key) => typeof key === 'string' && key)
    );
    let selectionCleared = false;
    Array.from(selectEl.options).forEach((option) => {
      if (!option.value) {
        option.hidden = false;
        option.disabled = false;
        return;
      }
      const definition = getDefinition(option.value);
      const optionSlug = definition && definition.slug ? String(definition.slug) : option.value;
      if (optionSlug && optionSlug.startsWith(ARMY_RULE_OFF_PREFIX)) {
        option.hidden = false;
        option.disabled = false;
        return;
      }
      const optionKey = abilityKey({
        slug: definition ? definition.slug : option.value,
      });
      const shouldHide = optionKey ? usedKeys.has(optionKey) : false;
      option.hidden = shouldHide;
      option.disabled = shouldHide;
      if (shouldHide && option.selected) {
        selectionCleared = true;
      }
    });
    if (selectionCleared) {
      selectEl.value = '';
      if (!isUpdatingSelectOptions) {
        isUpdatingSelectOptions = true;
        handleSelectChange();
        isUpdatingSelectOptions = false;
      }
    }
  }

  function resetValueInputs() {
    if (valueInput) {
      valueInput.value = '';
      valueInput.classList.remove('is-invalid');
      valueInput.type = 'text';
    }
    if (valueSelect) {
      valueSelect.value = '';
    }
  }

  function populateValueChoices(definition) {
    if (!valueSelect) {
      return;
    }
    valueSelect.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = definition.value_label ? `Wybierz (${definition.value_label})` : 'Wybierz wartość';
    valueSelect.appendChild(placeholder);
    (definition.value_choices || []).forEach((choice) => {
      const option = document.createElement('option');
      if (typeof choice === 'string') {
        option.value = choice;
        option.textContent = choice;
      } else if (choice && typeof choice === 'object') {
        option.value = choice.value ?? '';
        option.textContent = choice.label || choice.value || '';
        if (choice.description) {
          option.title = choice.description;
        }
      }
      valueSelect.appendChild(option);
    });
  }

  function handleSelectChange() {
    if (!selectEl || !valueContainer) {
      return;
    }
    resetValueInputs();
    const slug = selectEl.value;
    const definition = getDefinition(slug);
    if (definition && definition.requires_value) {
      valueContainer.classList.remove('d-none');
      if (definition.value_choices && definition.value_choices.length > 0 && valueSelect) {
        valueSelect.classList.remove('d-none');
        populateValueChoices(definition);
        if (valueInput) {
          valueInput.classList.add('d-none');
        }
      } else {
        if (valueSelect) {
          valueSelect.classList.add('d-none');
          valueSelect.innerHTML = '';
        }
        if (valueInput) {
          valueInput.classList.remove('d-none');
          valueInput.placeholder = definition.value_label ? `Wartość (${definition.value_label})` : 'Wartość';
          valueInput.type = definition.value_type === 'number' ? 'number' : 'text';
        }
      }
    } else {
      valueContainer.classList.add('d-none');
      if (valueSelect) {
        valueSelect.classList.add('d-none');
        valueSelect.innerHTML = '';
      }
    }
  }

  function validateValue(definition, value) {
    if (!definition || !definition.requires_value) {
      return true;
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return false;
    }
    if (definition.value_type === 'number') {
      return !Number.isNaN(Number(trimmed));
    }
    return true;
  }

  function handleAdd() {
    if (!selectEl) {
      return;
    }
    const slug = selectEl.value;
    if (!slug) {
      return;
    }
    const definition = getDefinition(slug);
    let rawValue = '';
    let choiceLabel = '';
    if (definition && definition.requires_value) {
      if (definition.value_choices && definition.value_choices.length > 0 && valueSelect) {
        rawValue = valueSelect.value || '';
        const option = valueSelect.selectedOptions[0];
        choiceLabel = option ? option.textContent.trim() : '';
        if (!rawValue) {
          return;
        }
      } else if (valueInput) {
        rawValue = valueInput.value || '';
        if (!validateValue(definition, rawValue)) {
          valueInput.classList.add('is-invalid');
          valueInput.addEventListener(
            'input',
            () => valueInput.classList.remove('is-invalid'),
            { once: true }
          );
          return;
        }
      }
    }
    const label = definition
      ? formatLabel(definition, rawValue, choiceLabel)
      : selectEl.selectedOptions[0]?.textContent || slug;
    const entry = normalizeEntry({
      slug: definition ? definition.slug : '__custom__',
      value: rawValue.trim(),
      raw: choiceLabel,
      label,
      ability_id: definition && Object.prototype.hasOwnProperty.call(definition, 'ability_id')
        ? definition.ability_id
        : null,
      is_default: allowDefaultToggle ? defaultInitial : false,
    });
    if (isDuplicateAbility(entry)) {
      if (selectEl) {
        selectEl.classList.add('is-invalid');
        selectEl.addEventListener(
          'change',
          () => selectEl.classList.remove('is-invalid'),
          { once: true },
        );
      }
      return;
    }
    items.push(entry);
    updateHidden();
    renderList();
    selectEl.value = '';
    handleSelectChange();
  }

  if (addButton) {
    addButton.addEventListener('click', handleAdd);
  }
  if (selectEl) {
    selectEl.addEventListener('change', handleSelectChange);
  }

  parseInitial();
  renderList();
  handleSelectChange();
  updateSelectOptionVisibility();

  root.abilityPicker = {
    setItems(newItems) {
      items = Array.isArray(newItems) ? newItems.map((entry) => normalizeEntry(entry || {})) : [];
      updateHidden();
      renderList();
      updateSelectOptionVisibility();
    },
  };
}

function initAbilityPickers() {
  document.querySelectorAll('[data-ability-picker]').forEach((element) => {
    initAbilityPicker(element);
  });
}

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
// initWeaponPicker, initWeaponPickers — drzewo wyboru broni
// ============================================================
function initWeaponPicker(root) {
  const treePayloadRaw =
    root.dataset.weaponTreePayload ||
    root.dataset.weaponTree ||
    root.dataset.weapons;
  let parsedPayload = null;
  if (treePayloadRaw) {
    try {
      parsedPayload = JSON.parse(treePayloadRaw);
    } catch (err) {
      console.warn('Nie udało się odczytać drzewa uzbrojenia', err);
      parsedPayload = null;
    }
  }

  let rawTree = [];
  let rawFlat = [];
  if (Array.isArray(parsedPayload)) {
    rawTree = parsedPayload;
  } else if (parsedPayload && typeof parsedPayload === 'object') {
    if (Array.isArray(parsedPayload.tree)) {
      rawTree = parsedPayload.tree;
    } else if (Array.isArray(parsedPayload.nodes)) {
      rawTree = parsedPayload.nodes;
    }
    if (Array.isArray(parsedPayload.flat)) {
      rawFlat = parsedPayload.flat;
    }
  }

  if ((!Array.isArray(rawTree) || !rawTree.length) && Array.isArray(rawFlat) && rawFlat.length) {
    const cloneMap = new Map();
    rawFlat.forEach((entry) => {
      if (!entry || typeof entry !== 'object') {
        return;
      }
      const id = Number.parseInt(entry.id ?? entry.weapon_id, 10);
      if (!Number.isFinite(id)) {
        return;
      }
      cloneMap.set(String(id), {
        id,
        name: typeof entry.name === 'string' ? entry.name : '',
        parent_id:
          entry.parent_id !== undefined && entry.parent_id !== null
            ? Number(entry.parent_id)
            : null,
        range_value: entry.range_value,
        category: entry.category,
        children: [],
        path: entry.path,
        path_labels: entry.path_labels,
        path_text: entry.path_text,
        is_leaf: entry.is_leaf,
      });
    });
    const roots = [];
    cloneMap.forEach((node) => {
      const parentId =
        node.parent_id !== undefined && node.parent_id !== null
          ? Number(node.parent_id)
          : null;
      if (Number.isFinite(parentId) && cloneMap.has(String(parentId))) {
        cloneMap.get(String(parentId)).children.push(node);
      } else {
        roots.push(node);
      }
    });
    rawTree = roots;
  }

  const targetId = root.dataset.targetInput;
  const hiddenInput =
    targetId ? document.getElementById(targetId) : root.querySelector('input[type="hidden"]');
  const selectEl = root.querySelector('.weapon-picker-select');
  const defaultCountInput = root.querySelector('.weapon-picker-default-count');
  const addButton = root.querySelector('.weapon-picker-add');
  const listEl = root.querySelector('.weapon-picker-list');
  const treeRoot = root.querySelector('[data-weapon-tree]');
  if (treeRoot) {
    treeRoot.setAttribute('tabindex', '-1');
  }
  const pickerId = Math.random().toString(16).slice(2);

  const treeContainer = root.querySelector('[data-weapon-tree-container]');
  const treeTrigger = root.querySelector('[data-weapon-tree-trigger]');
  const treeTriggerLabel = root.querySelector('[data-weapon-tree-label]');
  const treePlaceholder =
    (treeTrigger && treeTrigger.dataset.weaponTreePlaceholder) ||
    (treeTriggerLabel && treeTriggerLabel.textContent?.trim()) ||
    (treeTrigger && treeTrigger.textContent?.trim()) ||
    'Wybierz broń';
  const treeContainerId =
    treeContainer && (treeContainer.id || `weapon-tree-container-${pickerId}`);
  if (treeContainer && !treeContainer.id && treeContainerId) {
    treeContainer.id = treeContainerId;
  }
  if (treeTrigger && treeContainerId) {
    treeTrigger.setAttribute('aria-controls', treeContainerId);
  }
  if (treeTrigger) {
    treeTrigger.dataset.weaponTreePlaceholder = treePlaceholder;
  }
  if (treeTriggerLabel) {
    treeTriggerLabel.dataset.weaponTreePlaceholder = treePlaceholder;
  }

  let treeExpanded = !treeTrigger;
  let outsidePointerAttached = false;

  function handleOutsidePointer(event) {
    if (!treeExpanded || !treeTrigger || !treeContainer) {
      return;
    }
    const target = event.target;
    if (!(target instanceof Node)) {
      return;
    }
    if (treeExpanded) {
      const safeElements = [treeContainer];
      const caret = root.querySelector('.weapon-picker-tree-trigger-caret');
      if (caret && !safeElements.includes(caret)) {
        safeElements.push(caret);
      }
      const isInsideTree = safeElements.some(
        (element) => element instanceof Node && element.contains(target),
      );
      if (isInsideTree) {
        return;
      }

      treeExpanded = false;
      syncTreeVisibility();
      if (typeof treeTrigger.focus === 'function') {
        treeTrigger.focus();
      }
    }
  }

  function syncTreeVisibility() {
    if (!treeContainer || !treeTrigger) {
      treeExpanded = true;
      if (outsidePointerAttached) {
        document.removeEventListener('pointerdown', handleOutsidePointer, true);
        outsidePointerAttached = false;
      }
      if (treeRoot) {
        treeRoot.setAttribute('aria-hidden', 'false');
      }
      return;
    }
    const expanded = Boolean(treeExpanded);
    if (expanded) {
      if (!outsidePointerAttached) {
        document.addEventListener('pointerdown', handleOutsidePointer, true);
        outsidePointerAttached = true;
      }
    } else if (outsidePointerAttached) {
      document.removeEventListener('pointerdown', handleOutsidePointer, true);
      outsidePointerAttached = false;
    }
    treeContainer.hidden = !expanded;
    treeContainer.classList.toggle('d-none', !expanded);
    treeContainer.classList.toggle('weapon-tree-container-open', expanded);
    treeTrigger.hidden = expanded;
    treeTrigger.classList.toggle('d-none', expanded);
    treeTrigger.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    treeTrigger.classList.toggle('weapon-tree-trigger-open', expanded);
    if (treeRoot) {
      treeRoot.setAttribute('aria-hidden', expanded ? 'false' : 'true');
    }
  }

  syncTreeVisibility();

  if (treeTrigger && treeContainer) {
    treeTrigger.addEventListener('click', (event) => {
      event.preventDefault();
      treeExpanded = !treeExpanded;
      syncTreeVisibility();
      if (treeExpanded && treeRoot && typeof treeRoot.focus === 'function') {
        treeRoot.focus();
      }
    });
  }

  if (treeRoot && treeTrigger && treeContainer) {
    treeRoot.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        treeExpanded = false;
        syncTreeVisibility();
        if (typeof treeTrigger.focus === 'function') {
          treeTrigger.focus();
        }
      }
    });
  }

  const weaponMap = new Map();
  const collapsedNodes = new Set();
  let treeData = [];
  let items = [];
  let selectedWeaponId = null;

  function normalizeCategory(value) {
    if (typeof value !== 'string') {
      return null;
    }
    const lowered = value.trim().toLowerCase();
    if (
      [
        'ranged',
        'dystansowa',
        'dystansowe',
        'dystansowy',
        'shooting',
        'shoot',
        'range',
      ].includes(lowered)
    ) {
      return 'ranged';
    }
    if (['melee', 'wręcz', 'wrecz', 'close', 'close combat'].includes(lowered)) {
      return 'melee';
    }
    return null;
  }

  function sanitizeTree(nodes, parentId = null, parentPathIds = [], parentPathLabels = []) {
    const result = [];
    (Array.isArray(nodes) ? nodes : []).forEach((node) => {
      if (!node || typeof node !== 'object') {
        return;
      }
      const rawId = node.id ?? node.weapon_id;
      const id = Number.parseInt(rawId, 10);
      if (!Number.isFinite(id)) {
        return;
      }
      const rawName = typeof node.name === 'string' ? node.name : '';
      const name = rawName.trim() || `Broń #${id}`;
      let pathIds = Array.isArray(node.path)
        ? node.path
            .map((value) => Number.parseInt(value, 10))
            .filter((value) => Number.isFinite(value))
        : [];
      if (!pathIds.length || pathIds[pathIds.length - 1] !== id) {
        pathIds = [...parentPathIds, id];
      }
      let pathLabels = Array.isArray(node.path_labels)
        ? node.path_labels.map((value) => String(value))
        : [];
      if (!pathLabels.length || pathLabels.length !== pathIds.length) {
        pathLabels = [...parentPathLabels, name];
      }
      const depth = pathIds.length ? pathIds.length - 1 : parentPathIds.length;
      const rangeSource =
        node.range_value ??
        node.range ??
        node.effective_range ??
        node.rangeValue ??
        0;
      const rangeValue = normalizeRangeValue(rangeSource);
      const rawCategory =
        node.category ?? node.range_category ?? node.type ?? null;
      const category =
        normalizeCategory(rawCategory) ?? (rangeValue > 0 ? 'ranged' : 'melee');
      let parentValue = null;
      if (Number.isFinite(Number(node.parent_id))) {
        parentValue = Number(node.parent_id);
      } else if (pathIds.length >= 2) {
        parentValue = pathIds[pathIds.length - 2];
      } else if (Number.isFinite(Number(parentId))) {
        parentValue = Number(parentId);
      }
      const childNodes = sanitizeTree(
        node.children,
        id,
        pathIds,
        pathLabels,
      );
      const hasChildren = childNodes.length > 0;
      const isLeaf = !hasChildren || Boolean(node.is_leaf);
      const meta = {
        id,
        name,
        parent_id: Number.isFinite(parentValue) ? parentValue : null,
        depth,
        path: pathIds,
        path_labels: pathLabels,
        path_text:
          typeof node.path_text === 'string' && node.path_text.trim()
            ? node.path_text.trim()
            : pathLabels.join(' / '),
        category,
        range_value: Number.isFinite(rangeValue) ? rangeValue : 0,
        attacks: node.attacks !== undefined && node.attacks !== null ? node.attacks : null,
        ap: node.ap !== undefined && node.ap !== null ? node.ap : null,
        abilities: Array.isArray(node.abilities) ? node.abilities : [],
        cost: typeof node.cost === 'number' ? node.cost : null,
        is_leaf: isLeaf,
      };
      weaponMap.set(String(id), { ...meta });
      const sanitizedNode = {
        ...meta,
        children: childNodes,
        has_children: hasChildren,
      };
      result.push(sanitizedNode);
    });
    return result;
  }

  function sortTree(nodes) {
    if (!Array.isArray(nodes)) {
      return;
    }
    nodes.sort((a, b) => {
      const nameA = a && a.name ? String(a.name).toLowerCase() : '';
      const nameB = b && b.name ? String(b.name).toLowerCase() : '';
      if (nameA < nameB) {
        return -1;
      }
      if (nameA > nameB) {
        return 1;
      }
      return 0;
    });
    nodes.forEach((node) => {
      if (node && Array.isArray(node.children) && node.children.length) {
        sortTree(node.children);
      }
    });
  }

  treeData = sanitizeTree(rawTree);
  sortTree(treeData);

  if (Array.isArray(rawFlat)) {
    rawFlat.forEach((entry) => {
      if (!entry || typeof entry !== 'object') {
        return;
      }
      const id = Number.parseInt(entry.id ?? entry.weapon_id, 10);
      if (!Number.isFinite(id) || weaponMap.has(String(id))) {
        return;
      }
      const rawName = typeof entry.name === 'string' ? entry.name : '';
      const name = rawName.trim() || `Broń #${id}`;
      const rangeValue = normalizeRangeValue(
        entry.range_value ?? entry.range ?? entry.effective_range ?? 0,
      );
      const category =
        normalizeCategory(entry.category ?? entry.range_category ?? null) ??
        (rangeValue > 0 ? 'ranged' : 'melee');
      let path = Array.isArray(entry.path)
        ? entry.path
            .map((value) => Number.parseInt(value, 10))
            .filter((value) => Number.isFinite(value))
        : [];
      if (!path.length || path[path.length - 1] !== id) {
        path = [...path, id];
      }
      let pathLabels = Array.isArray(entry.path_labels)
        ? entry.path_labels.map((value) => String(value))
        : [];
      if (!pathLabels.length || pathLabels.length !== path.length) {
        pathLabels = path.map((value, index) => {
          if (index === path.length - 1) {
            return name;
          }
          const ancestor = weaponMap.get(String(path[index]));
          return ancestor && ancestor.name ? ancestor.name : `#${path[index]}`;
        });
      }
      weaponMap.set(String(id), {
        id,
        name,
        parent_id:
          entry.parent_id !== undefined && entry.parent_id !== null
            ? Number(entry.parent_id)
            : path.length > 1
            ? path[path.length - 2]
            : null,
        depth: Number.isFinite(Number(entry.depth))
          ? Number(entry.depth)
          : Math.max(path.length - 1, 0),
        path,
        path_labels: pathLabels,
        path_text:
          typeof entry.path_text === 'string' && entry.path_text.trim()
            ? entry.path_text.trim()
            : pathLabels.join(' / '),
        category,
        range_value: Number.isFinite(rangeValue) ? rangeValue : 0,
        attacks: entry.attacks !== undefined && entry.attacks !== null ? entry.attacks : null,
        ap: entry.ap !== undefined && entry.ap !== null ? entry.ap : null,
        abilities: Array.isArray(entry.abilities) ? entry.abilities : [],
        cost: typeof entry.cost === 'number' ? entry.cost : null,
        is_leaf: entry.is_leaf !== undefined ? Boolean(entry.is_leaf) : true,
      });
    });
  }

  function initializeCollapsedState(nodes) {
    (Array.isArray(nodes) ? nodes : []).forEach((node) => {
      if (!node) {
        return;
      }
      if (node.has_children) {
        collapsedNodes.add(String(node.id));
      }
      initializeCollapsedState(node.children);
    });
  }

  initializeCollapsedState(treeData);

  function ensureNodeVisible(weaponId) {
    const meta = weaponMap.get(String(weaponId));
    if (!meta || !Array.isArray(meta.path)) {
      return;
    }
    meta.path.slice(0, -1).forEach((ancestorId) => {
      collapsedNodes.delete(String(ancestorId));
    });
  }

  function toggleNode(nodeId, forceOpen) {
    const key = String(nodeId);
    if (forceOpen === true) {
      collapsedNodes.delete(key);
    } else if (forceOpen === false) {
      collapsedNodes.add(key);
    } else if (collapsedNodes.has(key)) {
      collapsedNodes.delete(key);
    } else {
      collapsedNodes.add(key);
    }
    renderTree();
    updateSelectionState();
  }

  function createNodeElement(node) {
    const li = document.createElement('li');
    li.className = 'weapon-tree-node';
    li.dataset.weaponNode = String(node.id);

    const row = document.createElement('div');
    row.className = 'weapon-tree-row d-flex align-items-center gap-2 py-1';
    li.appendChild(row);

    if (node.has_children) {
      const toggleBtn = document.createElement('button');
      toggleBtn.type = 'button';
      toggleBtn.className = 'btn btn-sm btn-outline-secondary weapon-tree-toggle';
      const collapsed = collapsedNodes.has(String(node.id));
      toggleBtn.textContent = collapsed ? '▸' : '▾';
      toggleBtn.setAttribute('aria-label', collapsed ? 'Rozwiń gałąź' : 'Zwiń gałąź');
      toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      toggleBtn.addEventListener('click', (event) => {
        event.preventDefault();
        toggleNode(node.id);
      });
      row.appendChild(toggleBtn);
    } else {
      const spacer = document.createElement('span');
      spacer.className = 'weapon-tree-toggle-placeholder';
      spacer.style.display = 'inline-block';
      spacer.style.width = '1.75rem';
      spacer.setAttribute('aria-hidden', 'true');
      row.appendChild(spacer);
    }

    if (node.is_leaf) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className =
        'btn btn-sm btn-outline-secondary weapon-tree-select flex-grow-1 text-start';
      button.dataset.weaponSelect = String(node.id);
      button.textContent = node.name;
      button.title = node.path_text || node.name;
      button.addEventListener('click', (event) => {
        event.preventDefault();
        setSelectedNode(node.id);
      });
      button.addEventListener('dblclick', (event) => {
        event.preventDefault();
        setSelectedNode(node.id);
        handleAdd();
      });
      row.appendChild(button);
    } else {
      const label = document.createElement('button');
      label.type = 'button';
      label.className =
        'btn btn-sm btn-outline-secondary weapon-tree-group flex-grow-1 text-start';
      label.dataset.weaponSelect = String(node.id);
      label.textContent = node.name;
      label.title = node.path_text || node.name;
      label.addEventListener('click', (event) => {
        event.preventDefault();
        setSelectedNode(node.id, { allowGroup: true });
      });
      label.addEventListener('dblclick', (event) => {
        event.preventDefault();
        setSelectedNode(node.id, { allowGroup: true });
        handleAdd();
      });
      row.appendChild(label);
    }

    const badge = document.createElement('span');
    if (node.is_leaf) {
      badge.className = 'badge text-bg-secondary weapon-tree-meta';
      badge.textContent = node.range_value > 0 ? `${node.range_value}"` : 'Wręcz';
    } else {
      badge.className = 'badge text-bg-light border text-muted weapon-tree-meta';
      badge.textContent = `${node.children.length}`;
      badge.title = 'Liczba wariantów';
    }
    row.appendChild(badge);

    if (node.children && node.children.length) {
      const childList = document.createElement('ul');
      childList.className = 'list-unstyled mb-0 weapon-tree-children ms-3';
      if (collapsedNodes.has(String(node.id))) {
        childList.hidden = true;
      }
      node.children.forEach((child) => {
        childList.appendChild(createNodeElement(child));
      });
      li.appendChild(childList);
    }

    return li;
  }

  function renderTree() {
    if (!treeRoot) {
      return;
    }
    treeRoot.innerHTML = '';
    treeRoot.classList.add('d-flex', 'flex-column', 'gap-2');
    treeRoot.setAttribute('role', 'tree');

    if (!Array.isArray(treeData) || !treeData.length) {
      const empty = document.createElement('p');
      empty.className = 'text-muted mb-0 fst-italic small';
      empty.textContent = 'Brak dostępnego uzbrojenia.';
      treeRoot.appendChild(empty);
      return;
    }

    const list = document.createElement('ul');
    list.className = 'list-unstyled mb-0 weapon-tree-root';
    treeData.forEach((node) => {
      list.appendChild(createNodeElement(node));
    });
    treeRoot.appendChild(list);
  }

  function updateTriggerLabel() {
    if (!treeTrigger) {
      return;
    }
    const labelElement = treeTriggerLabel || treeTrigger;
    const placeholder =
      treeTrigger.dataset.weaponTreePlaceholder ||
      treeTriggerLabel?.dataset.weaponTreePlaceholder ||
      treePlaceholder;
    let labelText = placeholder;
    let titleText = placeholder || '';
    if (selectedWeaponId) {
      const meta = getWeaponMeta(selectedWeaponId);
      if (meta) {
        labelText = meta.name || placeholder;
        titleText = meta.pathText || meta.name || labelText;
      }
    }
    if (labelElement) {
      labelElement.textContent = labelText;
    }
    if (titleText) {
      treeTrigger.title = titleText;
    } else {
      treeTrigger.removeAttribute('title');
    }
  }

  function updateSelectionState() {
    if (addButton) {
      if (treeRoot) {
        addButton.disabled = !selectedWeaponId;
      } else {
        addButton.disabled = false;
      }
    }
    updateTriggerLabel();
    if (!treeRoot) {
      return;
    }
    treeRoot.querySelectorAll('[data-weapon-select]').forEach((button) => {
      const nodeId = button.dataset.weaponSelect;
      const isSelected = selectedWeaponId && nodeId === selectedWeaponId;
      button.classList.toggle('btn-primary', Boolean(isSelected));
      button.classList.toggle('btn-outline-secondary', !isSelected);
      const nodeElement = button.closest('[data-weapon-node]');
      if (nodeElement) {
        nodeElement.classList.toggle('active', Boolean(isSelected));
      }
    });
  }

  function setSelectedNode(weaponId, options = {}) {
    const key = String(weaponId ?? '');
    if (!key) {
      selectedWeaponId = null;
      updateSelectionState();
      return;
    }
    const meta = weaponMap.get(key);
    if (!meta) {
      return;
    }
    const allowGroup = Boolean(options && options.allowGroup);
    if (!meta.is_leaf && !allowGroup) {
      return;
    }
    selectedWeaponId = key;
    ensureNodeVisible(meta.id);
    if (selectEl) {
      selectEl.value = key;
    }
    renderTree();
    updateSelectionState();
    if (treeTrigger && treeContainer && treeExpanded) {
      treeExpanded = false;
      syncTreeVisibility();
      if (typeof treeTrigger.focus === 'function') {
        treeTrigger.focus();
      }
    }
  }

  function getWeaponMeta(weaponId, entry) {
    const idKey =
      weaponId !== undefined && weaponId !== null ? weaponId : entry ? entry.weapon_id : undefined;
    const meta = idKey !== undefined && idKey !== null ? weaponMap.get(String(idKey)) : undefined;
    const rangeSource =
      (entry && entry.range_value !== undefined ? entry.range_value : undefined) ??
      (entry && entry.range !== undefined ? entry.range : undefined) ??
      (meta && meta.range_value !== undefined ? meta.range_value : undefined) ??
      0;
    const rangeValue = normalizeRangeValue(rangeSource);
    const categorySource =
      (entry && entry.category !== undefined && entry.category !== null ? entry.category : null) ??
      (meta ? meta.category : null);
    const category =
      normalizeCategory(categorySource) ?? (Number.isFinite(rangeValue) && rangeValue > 0 ? 'ranged' : 'melee');
    const pathText = meta && meta.path_text ? meta.path_text : '';
    const pathLabels = meta && Array.isArray(meta.path_labels) ? [...meta.path_labels] : [];
    const path = meta && Array.isArray(meta.path) ? [...meta.path] : [];
    const name =
      (meta && meta.name) ||
      (entry && entry.name) ||
      (selectEl && idKey !== undefined && idKey !== null
        ? selectEl.querySelector(`option[value="${String(idKey)}"]`)?.textContent
        : null) ||
      (idKey !== undefined && idKey !== null ? `Broń #${idKey}` : 'Broń');
    return {
      category,
      rangeValue: Number.isFinite(rangeValue) ? rangeValue : 0,
      pathText,
      pathLabels,
      path,
      name,
      isLeaf: Boolean(meta && meta.is_leaf),
    };
  }

  function parsePrimaryFlag(value) {
    if (typeof value === 'boolean') {
      return value;
    }
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value !== 0 : false;
    }
    if (typeof value === 'string') {
      return ['1', 'true', 'on', 'yes'].includes(value.trim().toLowerCase());
    }
    return false;
  }

  function parseInitial() {
    if (!hiddenInput || !hiddenInput.value) {
      items = [];
      return;
    }
    try {
      const parsed = JSON.parse(hiddenInput.value);
      if (!Array.isArray(parsed)) {
        items = [];
        return;
      }
      items = parsed
        .map((entry) => {
          if (!entry) {
            return null;
          }
          const rawWeaponId = entry.weapon_id ?? entry.weaponId ?? entry.id;
          const weaponId = Number.parseInt(rawWeaponId, 10);
          if (!Number.isFinite(weaponId)) {
            return null;
          }
          const meta = getWeaponMeta(weaponId, entry);
          const name =
            entry.name ||
            meta.name ||
            weaponMap.get(String(weaponId))?.name ||
            `Broń #${weaponId}`;
          const rawCount = entry.count ?? entry.default_count ?? entry.quantity;
          let defaultCount = Number.parseInt(rawCount, 10);
          if (!Number.isFinite(defaultCount)) {
            defaultCount = parsePrimaryFlag(entry.is_default) ? 1 : 0;
          }
          if (defaultCount < 0) {
            defaultCount = 0;
          }
          const primaryFlag = parsePrimaryFlag(
            entry.is_primary ?? entry.primary ?? entry.is_primary_weapon,
          );
          return {
            weapon_id: weaponId,
            name,
            default_count: defaultCount,
            is_primary: primaryFlag && defaultCount > 0,
            category: meta.category,
            range_value: meta.rangeValue,
            path_text: meta.pathText,
            path: meta.path,
            path_labels: meta.pathLabels,
          };
        })
        .filter((entry) => entry && entry.weapon_id);
    } catch (err) {
      console.warn('Nie udało się odczytać listy broni', err);
      items = [];
    }
  }

  function updateHidden() {
    if (hiddenInput) {
      const payload = items.map((entry) => ({
        weapon_id: entry.weapon_id,
        name: entry.name,
        is_default: entry.default_count > 0,
        is_primary: Boolean(entry.is_primary && Number(entry.default_count) > 0),
        count: entry.default_count,
        default_count: entry.default_count,
        category: entry.category,
        range_value: entry.range_value,
      }));
      hiddenInput.value = JSON.stringify(payload);
    }
  }

  function moveItem(fromIndex, toIndex) {
    if (!Array.isArray(items)) {
      return;
    }
    const lastIndex = items.length - 1;
    if (
      fromIndex === toIndex ||
      fromIndex < 0 ||
      toIndex < 0 ||
      fromIndex > lastIndex ||
      toIndex > lastIndex
    ) {
      return;
    }
    const [entry] = items.splice(fromIndex, 1);
    items.splice(toIndex, 0, entry);
    updateHidden();
    renderList();
  }

  function ensureUnique(weaponId) {
    return !items.some((entry) => String(entry.weapon_id) === String(weaponId));
  }

  function sanitizePrimaryFlags() {
    if (!Array.isArray(items)) {
      items = [];
      return false;
    }
    if (!items.length) {
      return false;
    }
    let changed = false;
    items.forEach((entry) => {
      if (!entry) {
        return;
      }
      const countValue = Number(entry.default_count);
      const safeCount = Number.isFinite(countValue) ? countValue : 0;
      const shouldBePrimary = safeCount > 0 ? Boolean(entry.is_primary) : false;
      if (entry.is_primary !== shouldBePrimary) {
        entry.is_primary = shouldBePrimary;
        changed = true;
      }
    });
    return changed;
  }

  let sortableInstance = null;

  function renderList() {
    if (!listEl) {
      return;
    }
    listEl.innerHTML = '';
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'text-muted mb-0';
      empty.textContent = 'Nie wybrano jeszcze żadnej broni.';
      listEl.appendChild(empty);
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex flex-column gap-2';
    items.forEach((item, index) => {
      const row = document.createElement('div');
      row.className = 'border rounded p-2 d-flex align-items-start gap-2';

      const nameWrapper = document.createElement('div');
      nameWrapper.className = 'flex-grow-1 d-flex flex-column';

      const nameRow = document.createElement('div');
      nameRow.className = 'd-flex flex-wrap align-items-center gap-2';

      const nameLabel = document.createElement('span');
      nameLabel.className = 'fw-semibold';
      nameLabel.textContent =
        item.name || weaponMap.get(String(item.weapon_id))?.name || `Broń #${item.weapon_id}`;
      nameRow.appendChild(nameLabel);

      const rangeBadge = document.createElement('span');
      rangeBadge.className = 'badge text-bg-secondary';
      rangeBadge.textContent = Number(item.range_value) > 0 ? `${item.range_value}"` : 'Wręcz';
      nameRow.appendChild(rangeBadge);

      nameWrapper.appendChild(nameRow);

      const weaponStats = weaponMap.get(String(item.weapon_id));
      const attacksDisplay = weaponStats?.attacks !== null && weaponStats?.attacks !== undefined
        ? weaponStats.attacks : '-';
      const apDisplay = weaponStats?.ap !== null && weaponStats?.ap !== undefined
        ? weaponStats.ap : 0;
      const abilitiesDisplay = Array.isArray(weaponStats?.abilities) && weaponStats.abilities.length
        ? weaponStats.abilities.map((a) => a.label || a.raw || a.slug || '').filter(Boolean).join(', ')
        : 'Brak cech';
      const costDisplay = weaponStats?.cost !== null && weaponStats?.cost !== undefined
        ? `${formatPoints(weaponStats.cost)} pkt` : null;
      const statsLine = document.createElement('div');
      statsLine.className = 'text-muted small mt-1';
      let statsText = `Ataki: ${attacksDisplay} • AP: ${apDisplay} • Cechy: ${abilitiesDisplay}`;
      if (costDisplay) {
        statsText += ` • Koszt: ${costDisplay}`;
      }
      statsLine.textContent = statsText;
      nameWrapper.appendChild(statsLine);

      const defaultGroup = document.createElement('div');
      defaultGroup.className = 'd-flex align-items-center gap-2 weapon-default-group';
      const defaultLabel = document.createElement('label');
      defaultLabel.className = 'form-label mb-0 small text-nowrap';
      defaultLabel.textContent = 'Domyślnie:';
      defaultLabel.setAttribute('for', `weapon-default-count-${item.weapon_id}-${index}`);
      const defaultField = document.createElement('input');
      defaultField.className = 'form-control form-control-sm weapon-default-count-input';
      defaultField.type = 'number';
      defaultField.min = '0';
      defaultField.value = Number.isFinite(item.default_count) ? item.default_count : 0;
      defaultField.id = `weapon-default-count-${item.weapon_id}-${index}`;
      defaultField.addEventListener('change', () => {
        const parsed = Number.parseInt(defaultField.value, 10);
        const safeValue = Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
        defaultField.value = safeValue;
        if (items[index]) {
          items[index].default_count = safeValue;
        }
        sanitizePrimaryFlags();
        updateHidden();
        renderList();
      });
      defaultGroup.appendChild(defaultLabel);
      defaultGroup.appendChild(defaultField);

      const primaryWrapper = document.createElement('div');
      primaryWrapper.className = 'form-check mb-0 d-flex align-items-center gap-2';
      const primaryInput = document.createElement('input');
      primaryInput.type = 'checkbox';
      primaryInput.className = 'form-check-input';
      const primaryId = `weapon-primary-${pickerId}-${item.weapon_id}-${index}`;
      primaryInput.id = primaryId;
      const hasDefault = Number(item.default_count) > 0;
      primaryInput.checked = Boolean(item.is_primary) && hasDefault;
      primaryInput.disabled = !hasDefault;
      primaryInput.addEventListener('change', () => {
        if (!items[index]) {
          return;
        }
        items[index].is_primary = Boolean(primaryInput.checked);
        const changed = sanitizePrimaryFlags();
        updateHidden();
        if (changed) {
          renderList();
        }
      });
      const primaryLabel = document.createElement('label');
      primaryLabel.className = 'form-check-label small';
      primaryLabel.setAttribute('for', primaryId);
      primaryLabel.textContent = 'Podstawowa';
      primaryWrapper.appendChild(primaryInput);
      primaryWrapper.appendChild(primaryLabel);

      row.appendChild(nameWrapper);

      const controlsWrapper = document.createElement('div');
      controlsWrapper.className = 'd-flex flex-wrap align-items-center gap-2 flex-shrink-0';
      controlsWrapper.appendChild(defaultGroup);
      controlsWrapper.appendChild(primaryWrapper);

      const actionsWrapper = document.createElement('div');
      actionsWrapper.className = 'd-flex flex-column flex-sm-row gap-2 align-items-center';

      if (typeof Sortable !== 'undefined') {
        const handle = document.createElement('span');
        handle.className = 'drag-handle weapon-drag-handle';
        handle.setAttribute('aria-hidden', 'true');
        handle.textContent = '⋮⋮';
        actionsWrapper.appendChild(handle);
      }

      const reorderGroup = document.createElement('div');
      reorderGroup.className = 'btn-group-vertical weapon-move-buttons';
      const moveUpBtn = document.createElement('button');
      moveUpBtn.type = 'button';
      moveUpBtn.className = 'btn btn-outline-secondary btn-sm';
      moveUpBtn.textContent = '↑';
      moveUpBtn.setAttribute('aria-label', 'Przesuń w górę');
      moveUpBtn.disabled = index === 0;
      moveUpBtn.addEventListener('click', (event) => {
        event.preventDefault();
        moveItem(index, index - 1);
      });
      const moveDownBtn = document.createElement('button');
      moveDownBtn.type = 'button';
      moveDownBtn.className = 'btn btn-outline-secondary btn-sm';
      moveDownBtn.textContent = '↓';
      moveDownBtn.setAttribute('aria-label', 'Przesuń w dół');
      moveDownBtn.disabled = index === items.length - 1;
      moveDownBtn.addEventListener('click', (event) => {
        event.preventDefault();
        moveItem(index, index + 1);
      });
      reorderGroup.appendChild(moveUpBtn);
      reorderGroup.appendChild(moveDownBtn);
      actionsWrapper.appendChild(reorderGroup);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-outline-danger btn-sm';
      removeBtn.textContent = 'Usuń';
      removeBtn.addEventListener('click', () => {
        items.splice(index, 1);
        updateHidden();
        renderList();
      });
      actionsWrapper.appendChild(removeBtn);

      controlsWrapper.appendChild(actionsWrapper);
      row.appendChild(controlsWrapper);
      wrapper.appendChild(row);
    });

    if (typeof Sortable !== 'undefined') {
      if (sortableInstance) sortableInstance.destroy();
      wrapper.classList.add('weapon-list-dnd-active');
      sortableInstance = Sortable.create(wrapper, {
        handle: '.weapon-drag-handle',
        animation: 150,
        ghostClass: 'weapon-row-ghost',
        onEnd(evt) {
          if (evt.oldIndex === evt.newIndex) return;
          const moved = items.splice(evt.oldIndex, 1)[0];
          items.splice(evt.newIndex, 0, moved);
          updateHidden();
          renderList();
        },
      });
    }

    listEl.appendChild(wrapper);
  }

  function handleAdd() {
    const selectedId = selectedWeaponId || (selectEl ? selectEl.value : '');
    if (!selectedId) {
      return;
    }
    if (!ensureUnique(selectedId)) {
      if (selectEl) {
        selectEl.value = '';
      }
      selectedWeaponId = null;
      updateSelectionState();
      return;
    }
    const meta = getWeaponMeta(selectedId);
    const rawCount = defaultCountInput ? Number.parseInt(defaultCountInput.value, 10) : 0;
    const safeCount = Number.isFinite(rawCount) && rawCount >= 0 ? rawCount : 0;
    items.push({
      weapon_id: Number.parseInt(selectedId, 10),
      name: meta.name,
      default_count: safeCount,
      is_primary: false,
      category: meta.category,
      range_value: meta.rangeValue,
      path_text: meta.pathText,
      path: meta.path,
      path_labels: meta.pathLabels,
    });
    sanitizePrimaryFlags();
    updateHidden();
    renderList();
    selectedWeaponId = null;
    if (selectEl) {
      selectEl.value = '';
    }
    if (defaultCountInput) {
      defaultCountInput.value = '0';
    }
    updateSelectionState();
  }

  if (addButton) {
    addButton.addEventListener('click', handleAdd);
  }

  if (selectEl && !treeRoot) {
    selectEl.addEventListener('change', () => {
      const value = selectEl.value;
      selectedWeaponId = value || null;
      updateSelectionState();
    });
  }

  parseInitial();
  if (Array.isArray(items)) {
    items.forEach((entry) => {
      if (entry && entry.weapon_id !== undefined && entry.weapon_id !== null) {
        ensureNodeVisible(entry.weapon_id);
      }
    });
  }
  renderTree();
  sanitizePrimaryFlags();
  updateHidden();
  renderList();
  updateSelectionState();
}


function initWeaponPickers() {
  document.querySelectorAll('[data-weapon-picker]').forEach((element) => {
    initWeaponPicker(element);
  });
}

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
  const lockPairCache = new Map();
  const LOCK_PAIR_DATASET_KEY = 'rosterLockPairs';

  function resetRosterCaches() {
    rosterDatasetCache = new WeakMap();
    rosterUnitDatasetCache.clear();
    rosterUnitDatasetRepo.clear();
    lockPairCache.clear();
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

  function parseLockPairs(rawValue) {
    const parsed = safeParseJson(rawValue, [], 'Nie udało się odczytać par blokad ekwipunku');
    return Array.isArray(parsed) ? parsed : [];
  }

  function readLockPairDataset() {
    if (!root || !root.dataset) {
      return '[]';
    }
    const raw = root.dataset[LOCK_PAIR_DATASET_KEY] || root.dataset.lockPairs || '';
    return raw || '[]';
  }

  function writeLockPairDataset(serializedPairs) {
    if (!root || !root.dataset || typeof serializedPairs !== 'string') {
      return;
    }
    root.dataset[LOCK_PAIR_DATASET_KEY] = serializedPairs;
    if (Object.prototype.hasOwnProperty.call(root.dataset, 'lockPairs')) {
      delete root.dataset.lockPairs;
    }
  }

  function normalizeRosterUnitId(value) {
    if (value === null || value === undefined) {
      return null;
    }
    const text = String(value).trim();
    return text || null;
  }

  function cloneLockPairCache(source) {
    const clone = new Map();
    if (!(source instanceof Map)) {
      return clone;
    }
    source.forEach((partners, unitId) => {
      if (!(partners instanceof Set)) {
        return;
      }
      clone.set(unitId, new Set(partners));
    });
    return clone;
  }

  function applyLockPairsFromServer(payload) {
    if (payload === undefined || payload === null) {
      return;
    }
    const payloadIsList = Array.isArray(payload) || typeof payload === 'string';
    const hasLockPairListProp =
      payload && typeof payload === 'object' && Object.prototype.hasOwnProperty.call(payload, 'lock_pairs');
    const replaceCache = payloadIsList || hasLockPairListProp;

    const nextCache = replaceCache ? new Map() : cloneLockPairCache(lockPairCache);
    let hasPayload = false;

    const ensureEntry = (unitId) => {
      const normalized = normalizeRosterUnitId(unitId);
      if (!normalized) {
        return null;
      }
      if (!nextCache.has(normalized)) {
        nextCache.set(normalized, new Set());
      }
      return nextCache.get(normalized);
    };

    const addPair = (first, second) => {
      const firstId = normalizeRosterUnitId(first);
      const secondId = normalizeRosterUnitId(second);
      if (!firstId || !secondId || firstId === secondId) {
        return;
      }
      hasPayload = true;
      const firstSet = ensureEntry(firstId);
      const secondSet = ensureEntry(secondId);
      if (firstSet) {
        firstSet.add(secondId);
      }
      if (secondSet) {
        secondSet.add(firstId);
      }
    };

    const addUnitPartners = (unit) => {
      if (!unit || typeof unit !== 'object' || !Object.prototype.hasOwnProperty.call(unit, 'locked_pair_unit_ids')) {
        return;
      }
      const unitId = normalizeRosterUnitId(unit.id ?? unit.roster_unit_id ?? unit.rosterUnitId);
      if (!unitId) {
        return;
      }
      hasPayload = true;
      ensureEntry(unitId);
      const partners = Array.isArray(unit.locked_pair_unit_ids) ? unit.locked_pair_unit_ids : [];
      partners.forEach((partnerId) => addPair(unitId, partnerId));
    };

    const addPairList = (pairs) => {
      if (!Array.isArray(pairs)) {
        return;
      }
      hasPayload = true;
      pairs.forEach((pair) => {
        if (!pair || typeof pair !== 'object') {
          return;
        }
        const first = pair.first_roster_unit_id ?? pair.first ?? pair.first_id;
        const second = pair.second_roster_unit_id ?? pair.second ?? pair.second_id;
        addPair(first, second);
      });
    };

    if (Array.isArray(payload)) {
      addPairList(payload);
    } else if (typeof payload === 'string') {
      addPairList(parseLockPairs(payload));
    } else if (payload && typeof payload === 'object') {
      if (Object.prototype.hasOwnProperty.call(payload, 'lock_pairs')) {
        addPairList(payload.lock_pairs);
      }
      const unitList = [];
      if (Array.isArray(payload.units)) {
        unitList.push(...payload.units);
      }
      if (payload.unit && typeof payload.unit === 'object') {
        unitList.push(payload.unit);
      }
      unitList.forEach((unit) => addUnitPartners(unit));
    } else {
      return;
    }

    if (!hasPayload) {
      return;
    }

    lockPairCache.clear();
    nextCache.forEach((partners, unitId) => {
      lockPairCache.set(unitId, partners);
    });
  }

  function getPartnerId(rosterUnitId) {
    const targetId = normalizeRosterUnitId(rosterUnitId);
    if (!targetId) {
      return null;
    }
    const cachedPartners = lockPairCache.get(targetId);
    if (cachedPartners instanceof Set) {
      const candidate = Array.from(cachedPartners).find(
        (partnerId) => partnerId && partnerId !== targetId,
      );
      if (candidate) {
        return candidate;
      }
      if (cachedPartners.size === 0) {
        return null;
      }
    }
    const datasetPartners = getUnitDatasetValue(targetId, 'locked_pair_unit_ids', []);
    if (Array.isArray(datasetPartners)) {
      const partnerId = datasetPartners
        .map((value) => normalizeRosterUnitId(value))
        .find((value) => value && value !== targetId);
      if (partnerId) {
        return partnerId;
      }
    }
    const parsedPairs = parseLockPairs(readLockPairDataset());
    if (parsedPairs.length) {
      const partnerFromPairs = parsedPairs.reduce((result, pair) => {
        if (result || !pair || typeof pair !== 'object') {
          return result;
        }
        const first = normalizeRosterUnitId(pair.first_roster_unit_id ?? pair.first ?? pair.first_id);
        const second = normalizeRosterUnitId(
          pair.second_roster_unit_id ?? pair.second ?? pair.second_id,
        );
        if (!first || !second || first === second) {
          return result;
        }
        if (first === targetId) {
          return second;
        }
        if (second === targetId) {
          return first;
        }
        return result;
      }, null);
      if (partnerFromPairs) {
        return partnerFromPairs;
      }
    }
    return null;
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
    if (Array.isArray(payload.lock_pairs)) {
      const serializedPairs = JSON.stringify(payload.lock_pairs);
      writeLockPairDataset(serializedPairs);
    }
    applyLockPairsFromServer(payload);
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

  function hydrateInitialLockPairs() {
    const rawLockPairs = readLockPairDataset();
    const initialPairs = parseLockPairs(rawLockPairs);
    writeLockPairDataset(JSON.stringify(initialPairs));
    const initialUnitPayloads = Array.from(rosterUnitDatasetRepo.values()).filter(
      (value) => value && typeof value === 'object',
    );
    applyLockPairsFromServer({ lock_pairs: initialPairs, units: initialUnitPayloads });
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
          lock_pairs: data.lock_pairs,
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
      hydrateInitialLockPairs();
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

// ============================================================
// SECTION: SPELL ABILITY FORMS
// Extracted to app/static/js/modules/spell_ability_forms.js
// ============================================================
const {
  initSpellAbilityForms,
} = window.SZOPSpellAbilityForms;

// ============================================================
// SECTION: ARMORY WEAPON TREE
// initArmoryWeaponTree — drzewo broni w zbrojowni (filtry, sortowanie)
// ============================================================
function initArmoryWeaponTree() {
  const root = document.getElementById('armory-weapons-tree');
  if (!root) {
    return;
  }
  const treeBody = root.querySelector('[data-tree-body]');
  const emptyState = root.querySelector('[data-empty-state]');
  const filterEmptyState = root.querySelector('[data-filter-empty-state]');
  const filterInput = document.getElementById('weapons-filter');
  const sortButtons = Array.from(root.querySelectorAll('[data-sort-key]'));
  const canEdit = root.dataset.canEdit === 'true';
  const highlightWeaponId = root.dataset.highlightWeapon ? String(root.dataset.highlightWeapon) : '';

  let highlightRow = null;
  let highlightScrollPending = Boolean(highlightWeaponId);

  let rawData;
  try {
    rawData = root.dataset.weapons ? JSON.parse(root.dataset.weapons) : [];
  } catch (err) {
    rawData = [];
  }
  const nodeState = new Map();
  const sortState = { key: null, direction: 'none', type: 'text' };
  let filterQuery = '';

  const normalizeText = typeof normalizeName === 'function'
    ? (value) => normalizeName(value || '')
    : (value) => (value === undefined || value === null ? '' : String(value).toLowerCase());

  const nodeLookup = new Map();

  const hydrate = (node, level = 0, orderIndex = 0, parentId = null) => {
    const abilityItems = Array.isArray(node.abilities) ? node.abilities : [];
    const abilityLabels = abilityItems.map((ability) => ability.label || ability.raw || ability.slug || '');
    const abilityDescriptions = abilityItems.map((ability) => ability.description || ability.raw || '');
    const hydrated = {
      ...node,
      abilities: abilityItems,
      level: Number.isFinite(node.level) ? Number(node.level) : level,
      default_order: Number.isFinite(node.default_order) ? Number(node.default_order) : orderIndex,
      nameSort:
        typeof node.name_sort === 'string' && node.name_sort
          ? node.name_sort
          : normalizeText(node.name || ''),
      abilitiesSort:
        typeof node.abilities_sort === 'string' && node.abilities_sort
          ? node.abilities_sort
          : normalizeText(abilityLabels.join(' ')),
      range_value: Number.isFinite(Number(node.range_value))
        ? Number(node.range_value)
        : normalizeRangeValue(node.range),
      attacks_value: Number.isFinite(Number(node.attacks_value))
        ? Number(node.attacks_value)
        : Number(node.attacks ?? 0),
      ap: Number.isFinite(Number(node.ap)) ? Number(node.ap) : Number(node.ap ?? 0),
      cost: Number.isFinite(Number(node.cost)) ? Number(node.cost) : 0,
      cost_display:
        typeof node.cost_display === 'string' && node.cost_display
          ? node.cost_display
          : (Number.isFinite(Number(node.cost)) ? Number(node.cost).toFixed(2) : '0.00'),
      overrides: { ...(node.overrides || {}) },
      parent_id:
        node.parent_id !== undefined && node.parent_id !== null
          ? node.parent_id
          : parentId !== undefined && parentId !== null
            ? parentId
            : null,
      has_parent:
        node.has_parent !== undefined
          ? Boolean(node.has_parent)
          : node.parent_id !== undefined && node.parent_id !== null,
      parent_name: node.parent_name || '',
    };
    if (hydrated.attacks === undefined || hydrated.attacks === null) {
      hydrated.attacks = Math.round(hydrated.attacks_value);
    }
    hydrated.searchText = normalizeText(
      [
        hydrated.name || '',
        hydrated.range || '',
        String(hydrated.attacks ?? ''),
        String(hydrated.ap ?? ''),
        hydrated.parent_name || '',
        abilityLabels.join(' '),
        abilityDescriptions.join(' '),
      ]
        .filter((part) => part && part.length)
        .join(' '),
    );
    nodeLookup.set(String(hydrated.id), hydrated);

    const childLevel = hydrated.level + 1;
    hydrated.children = Array.isArray(node.children)
      ? node.children.map((child, idx) =>
          hydrate(
            child,
            Number.isFinite(child.level) ? Number(child.level) : childLevel,
            Number.isFinite(child.default_order) ? Number(child.default_order) : idx,
            hydrated.id,
          ),
        )
      : [];
    if (!nodeState.has(hydrated.id) && hydrated.children.length) {
      nodeState.set(hydrated.id, { expanded: false });
    }
    return hydrated;
  };

  const treeData = Array.isArray(rawData)
    ? rawData.map((node, index) =>
        hydrate(
          node,
          Number.isFinite(node.level) ? Number(node.level) : 0,
          Number.isFinite(node.default_order) ? Number(node.default_order) : index,
          node.parent_id !== undefined && node.parent_id !== null ? node.parent_id : null,
        ),
      )
    : [];

  if (highlightWeaponId && nodeLookup.has(highlightWeaponId)) {
    const visited = new Set();
    let current = nodeLookup.get(highlightWeaponId);
    while (current && current.parent_id !== null && !visited.has(current.id)) {
      visited.add(current.id);
      const parentId = current.parent_id;
      const state = nodeState.get(parentId) || {};
      if (state.expanded === false) {
        nodeState.set(parentId, { ...state, expanded: true });
      }
      current = nodeLookup.get(String(parentId));
    }
  }

  const restoreDefaultOrder = (nodes) => {
    nodes.sort((a, b) => (a.default_order ?? 0) - (b.default_order ?? 0));
    nodes.forEach((node) => {
      if (Array.isArray(node.children) && node.children.length) {
        restoreDefaultOrder(node.children);
      }
    });
  };

  const updateSortIndicators = () => {
    const indicatorSymbols = { asc: '▲', desc: '▼' };
    sortButtons.forEach((button) => {
      const indicator = button.querySelector('.armory-tree-sort-indicator');
      const key = button.dataset.sortKey;
      const isActive = sortState.key === key && sortState.direction !== 'none';
      button.dataset.sortDirection = isActive ? sortState.direction : 'none';
      if (indicator) {
        indicator.textContent = isActive ? indicatorSymbols[sortState.direction] || '' : '';
      }
    });
  };

  const sortAccessors = {
    name: (node) => node.nameSort || '',
    range: (node) => (Number.isFinite(node.range_value) ? node.range_value : 0),
    attacks: (node) => (Number.isFinite(node.attacks_value) ? node.attacks_value : 0),
    ap: (node) => (Number.isFinite(node.ap) ? node.ap : 0),
    abilities: (node) => node.abilitiesSort || '',
    cost: (node) => (Number.isFinite(node.cost) ? node.cost : 0),
  };

  const sortBranch = (nodes, comparator) => {
    nodes.sort(comparator);
    nodes.forEach((node) => {
      if (Array.isArray(node.children) && node.children.length) {
        sortBranch(node.children, comparator);
      }
    });
  };

  const applySort = () => {
    if (!treeData.length) {
      return;
    }
    if (sortState.direction === 'none' || !sortState.key) {
      restoreDefaultOrder(treeData);
      return;
    }
    restoreDefaultOrder(treeData);
    const accessor = sortAccessors[sortState.key];
    if (typeof accessor !== 'function') {
      return;
    }
    const comparator = (a, b) => {
      const rawA = accessor(a);
      const rawB = accessor(b);
      let result = 0;
      if (sortState.type === 'number') {
        const valueA = Number.isFinite(rawA) ? rawA : Number.NEGATIVE_INFINITY;
        const valueB = Number.isFinite(rawB) ? rawB : Number.NEGATIVE_INFINITY;
        result = valueA - valueB;
      } else {
        const textA = String(rawA || '');
        const textB = String(rawB || '');
        result = textA.localeCompare(textB, undefined, { sensitivity: 'base' });
      }
      if (result === 0) {
        result = (a.default_order ?? 0) - (b.default_order ?? 0);
      }
      return sortState.direction === 'asc' ? result : -result;
    };
    sortBranch(treeData, comparator);
  };

  const computeVisibility = (nodes) => {
    let visibleCount = 0;
    nodes.forEach((node) => {
      const childVisible = computeVisibility(Array.isArray(node.children) ? node.children : []);
      const matches = !filterQuery || node.searchText.includes(filterQuery);
      const isVisible = matches || childVisible > 0;
      node._matches = matches;
      node._visible = isVisible;
      node._visibleChildren = childVisible;
      if (isVisible) {
        visibleCount += 1;
      }
    });
    return visibleCount;
  };

  const createInheritanceLabel = (isOverridden, indentRem = 0) => {
    const label = document.createElement('div');
    label.className = 'text-muted small';
    label.textContent = isOverridden ? 'Nadpisano' : 'Dziedziczone';
    if (indentRem > 0) {
      label.style.paddingLeft = `${indentRem}rem`;
    }
    return label;
  };

  const renderNode = (node, rows) => {
    if (!node._visible) {
      return;
    }
    const isExpanded = filterQuery ? true : (nodeState.get(node.id)?.expanded !== false);
    const row = document.createElement('div');
    row.className = 'armory-tree-row row g-3 align-items-start px-3 py-3 border-bottom';
    row.dataset.nodeId = String(node.id);

    if (highlightWeaponId && String(node.id) === highlightWeaponId) {
      row.classList.add('armory-tree-highlight');
      highlightRow = row;
    }

    const nameCol = document.createElement('div');
    nameCol.className = 'col-12 col-lg-3 d-flex flex-column gap-1';
    const nameWrapper = document.createElement('div');
    nameWrapper.className = 'd-flex align-items-center gap-2';
    const nameIndent = Math.max(0, node.level) * 1.5;
    nameWrapper.style.paddingLeft = `${nameIndent}rem`;

    const toggleContainer = document.createElement('div');
    toggleContainer.className = 'flex-shrink-0';
    const toggleWidthRem = 1.5;
    toggleContainer.style.width = `${toggleWidthRem}rem`;
    if (Array.isArray(node.children) && node.children.length) {
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'btn btn-link btn-sm p-0 armory-tree-toggle';
      toggle.innerHTML = `<span aria-hidden="true">${isExpanded ? '▾' : '▸'}</span>`;
      toggle.setAttribute('aria-label', isExpanded ? 'Zwiń potomne' : 'Rozwiń potomne');
      toggle.disabled = Boolean(filterQuery);
      toggle.addEventListener('click', (event) => {
        event.preventDefault();
        const current = nodeState.get(node.id) || { expanded: true };
        nodeState.set(node.id, { expanded: !current.expanded });
        applyFilterAndRender();
      });
      toggleContainer.appendChild(toggle);
    } else {
      const spacer = document.createElement('span');
      spacer.style.display = 'inline-block';
      spacer.style.width = '0.75rem';
      spacer.style.height = '1rem';
      toggleContainer.appendChild(spacer);
    }
    nameWrapper.appendChild(toggleContainer);

    const nameText = document.createElement('span');
    nameText.textContent = node.name || 'Bez nazwy';
    nameWrapper.appendChild(nameText);
    nameCol.appendChild(nameWrapper);
    if (node.has_parent) {
      const nameLabelIndent = nameIndent + toggleWidthRem;
      nameCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.name), nameLabelIndent));
    }

    const rangeCol = document.createElement('div');
    rangeCol.className = 'col-6 col-sm-4 col-lg-1 d-flex flex-column gap-1';
    const rangeValue = node.range && String(node.range).trim() ? node.range : '-';
    const rangeText = document.createElement('span');
    if (!node.range || !String(node.range).trim()) {
      rangeText.className = 'text-muted';
    }
    rangeText.textContent = rangeValue;
    rangeCol.appendChild(rangeText);
    if (node.has_parent) {
      rangeCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.range)));
    }

    const attacksCol = document.createElement('div');
    attacksCol.className = 'col-6 col-sm-4 col-lg-1 d-flex flex-column gap-1';
    const attacksText = document.createElement('span');
    attacksText.textContent = String(node.attacks ?? Math.round(node.attacks_value ?? 0));
    attacksCol.appendChild(attacksText);
    if (node.has_parent) {
      attacksCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.attacks)));
    }

    const apCol = document.createElement('div');
    apCol.className = 'col-6 col-sm-4 col-lg-1 d-flex flex-column gap-1';
    const apText = document.createElement('span');
    apText.textContent = String(Number.isFinite(node.ap) ? node.ap : 0);
    apCol.appendChild(apText);
    if (node.has_parent) {
      apCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.ap)));
    }

    const abilitiesCol = document.createElement('div');
    abilitiesCol.className = 'col-12 col-lg-3 d-flex flex-column gap-1 mt-2 mt-lg-0 justify-content-lg-center';
    if (Array.isArray(node.abilities) && node.abilities.length) {
      const abilityWrapper = document.createElement('div');
      abilityWrapper.className = 'd-flex flex-wrap gap-1';
      node.abilities.forEach((ability) => {
        const badge = document.createElement('span');
        badge.className = 'badge text-bg-secondary';
        badge.textContent = ability.label || ability.raw || ability.slug || '-';
        const title = ability.description || ability.raw || '';
        if (title) {
          badge.title = title;
        }
        abilityWrapper.appendChild(badge);
      });
      abilitiesCol.appendChild(abilityWrapper);
    } else {
      const empty = document.createElement('span');
      empty.className = 'text-muted';
      empty.textContent = '-';
      abilitiesCol.appendChild(empty);
    }
    if (node.has_parent) {
      abilitiesCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.tags)));
    }

    const costCol = document.createElement('div');
    costCol.className = 'col-6 col-sm-4 col-lg-1 d-flex flex-column gap-1 mt-2 mt-lg-0 justify-content-lg-center';
    const costText = document.createElement('span');
    costText.textContent = node.cost_display || Number(node.cost || 0).toFixed(2);
    costCol.appendChild(costText);

    const actionsCol = document.createElement('div');
    actionsCol.className = 'col-12 col-lg-2 d-flex justify-content-lg-end align-items-lg-center mt-2 mt-lg-0';
    if (canEdit) {
      const group = document.createElement('div');
      group.className = 'btn-group btn-group-sm';
      const editLink = document.createElement('a');
      editLink.className = 'btn btn-outline-secondary';
      editLink.href = node.edit_url;
      editLink.textContent = 'Edytuj';
      group.appendChild(editLink);

      const deleteForm = document.createElement('form');
      deleteForm.method = 'post';
      deleteForm.action = node.delete_url;
      deleteForm.addEventListener('submit', (event) => {
        if (!confirm('Usunąć broń?')) {
          event.preventDefault();
        }
      });
      const deleteButton = document.createElement('button');
      deleteButton.type = 'submit';
      deleteButton.className = 'btn btn-outline-danger';
      deleteButton.textContent = 'Usuń';
      deleteForm.appendChild(deleteButton);
      group.appendChild(deleteForm);

      actionsCol.appendChild(group);
    } else {
      const readonly = document.createElement('span');
      readonly.className = 'text-muted small';
      readonly.textContent = 'Tylko podgląd';
      actionsCol.appendChild(readonly);
    }

    if (filterQuery && !node._matches && node._visibleChildren > 0) {
      row.classList.add('text-muted');
    }

    row.appendChild(nameCol);
    row.appendChild(rangeCol);
    row.appendChild(attacksCol);
    row.appendChild(apCol);
    row.appendChild(abilitiesCol);
    row.appendChild(costCol);
    row.appendChild(actionsCol);
    treeBody.appendChild(row);
    rows.push(row);

    const showChildren = Array.isArray(node.children) && node.children.length && (filterQuery ? true : isExpanded);
    if (showChildren) {
      node.children.forEach((child) => {
        renderNode(child, rows);
      });
    }
  };

  const renderTree = (visibleCount) => {
    if (!treeBody) {
      return;
    }
    treeBody.innerHTML = '';
    sortButtons.forEach((button) => {
      button.disabled = !treeData.length;
    });
    if (!treeData.length) {
      if (filterInput) {
        filterInput.disabled = true;
        filterInput.placeholder = 'Brak pozycji do filtrowania';
      }
      if (emptyState) {
        emptyState.classList.remove('d-none');
      }
      if (filterEmptyState) {
        filterEmptyState.classList.add('d-none');
      }
      return;
    }
    if (filterInput && filterInput.disabled) {
      filterInput.disabled = false;
      filterInput.placeholder = 'Wpisz nazwę, zdolność lub inną cechę';
    }
    if (filterQuery && visibleCount === 0) {
      if (filterEmptyState) {
        filterEmptyState.classList.remove('d-none');
      }
      if (emptyState) {
        emptyState.classList.add('d-none');
      }
      return;
    }
    if (emptyState) {
      emptyState.classList.add('d-none');
    }
    if (filterEmptyState) {
      filterEmptyState.classList.add('d-none');
    }
    const rows = [];
    highlightRow = null;
    treeData.forEach((node) => {
      renderNode(node, rows);
    });
    if (rows.length) {
      rows[rows.length - 1].classList.remove('border-bottom');
    }

    if (highlightRow && highlightScrollPending) {
      highlightScrollPending = false;
      if (typeof highlightRow.scrollIntoView === 'function') {
        requestAnimationFrame(() => {
          highlightRow.scrollIntoView({ block: 'center' });
        });
      }
    }
  };

  const applyFilterAndRender = () => {
    applySort();
    const visibleCount = computeVisibility(treeData);
    renderTree(visibleCount);
    updateSortIndicators();
  };

  sortButtons.forEach((button) => {
    const sortKey = button.dataset.sortKey;
    const sortType = button.dataset.sortType || 'text';
    button.addEventListener('click', (event) => {
      event.preventDefault();
      if (!treeData.length) {
        return;
      }
      let nextDirection = 'asc';
      if (sortState.key === sortKey) {
        nextDirection = sortState.direction === 'asc' ? 'desc' : sortState.direction === 'desc' ? 'none' : 'asc';
      }
      sortState.key = nextDirection === 'none' ? null : sortKey;
      sortState.direction = nextDirection;
      sortState.type = sortType;
      applyFilterAndRender();
    });
  });

  if (filterInput) {
    filterInput.addEventListener('input', () => {
      filterQuery = normalizeText(filterInput.value || '');
      applyFilterAndRender();
    });
  }

  applyFilterAndRender();
}

// ============================================================
// SECTION: WEAPON INHERITANCE PANEL
// initWeaponInheritancePanel — collapsible panel on armory weapon edit
// form with a hierarchical tree picker (one section per ancestor armory).
// Updates hidden inputs inherit_armory_id / inherit_parent_weapon_id.
// ============================================================
function initWeaponTreePickerPanel(panel, cfg) {
  const toggle = cfg.toggleAttr ? panel.querySelector(`[${cfg.toggleAttr}]`) : null;
  const body = cfg.bodyAttr ? panel.querySelector(`[${cfg.bodyAttr}]`) : panel;
  const armorySelect = panel.querySelector(`[${cfg.armorySelectAttr}]`);
  const treeWrapper = panel.querySelector(`[${cfg.treeWrapperAttr}]`);
  const treeContainer = panel.querySelector(`[${cfg.treeAttr}]`);
  const armoryInput = panel.querySelector(`[${cfg.armoryValueAttr}]`);
  const weaponInput = panel.querySelector(`[${cfg.weaponValueAttr}]`);
  const chevron = cfg.chevronAttr ? panel.querySelector(`[${cfg.chevronAttr}]`) : null;
  if (!armorySelect || !treeContainer) {
    return;
  }

  let options = [];
  try {
    options = JSON.parse(panel.dataset[cfg.optionsDataKey] || '[]');
  } catch (_) {
    options = [];
  }

  let current = null;
  try {
    current = cfg.currentDataKey && panel.dataset[cfg.currentDataKey]
      ? JSON.parse(panel.dataset[cfg.currentDataKey])
      : null;
  } catch (_) {
    current = null;
  }

    let selectedArmoryId = current ? String(current.armory_id) : '';
    let selectedWeaponId = current ? String(current.weapon_id) : '';
    const collapsedWeapons = new Set();

    options.forEach((entry) => {
      const opt = document.createElement('option');
      opt.value = String(entry.armory_id);
      opt.textContent = entry.armory_name + (entry.is_current ? ' (bieżąca)' : '');
      armorySelect.appendChild(opt);
    });
    armorySelect.value = selectedArmoryId || '';

    function applySelection() {
      if (armoryInput) armoryInput.value = selectedArmoryId || '';
      if (weaponInput) weaponInput.value = selectedWeaponId || '';
    }
    applySelection();

    function currentEntry() {
      return options.find((e) => String(e.armory_id) === selectedArmoryId) || null;
    }

    function createWeaponNode(weapon, depth) {
      const li = document.createElement('li');
      li.style.listStyle = 'none';
      const row = document.createElement('div');
      row.className = 'd-flex align-items-center gap-1 py-1';
      row.style.paddingLeft = `${depth * 1.25}rem`;

      const hasChildren = Array.isArray(weapon.children) && weapon.children.length > 0;
      const isCollapsed = collapsedWeapons.has(String(weapon.id));

      if (hasChildren) {
        const chevBtn = document.createElement('button');
        chevBtn.type = 'button';
        chevBtn.className = 'btn btn-link btn-sm p-0 text-muted flex-shrink-0';
        chevBtn.style.lineHeight = '1';
        chevBtn.style.width = '1.1rem';
        chevBtn.setAttribute('aria-label', isCollapsed ? 'Rozwiń' : 'Zwiń');
        chevBtn.textContent = isCollapsed ? '▸' : '▾';
        chevBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (collapsedWeapons.has(String(weapon.id))) {
            collapsedWeapons.delete(String(weapon.id));
          } else {
            collapsedWeapons.add(String(weapon.id));
          }
          renderTree();
        });
        row.appendChild(chevBtn);
      } else {
        const spacer = document.createElement('span');
        spacer.style.width = '1.1rem';
        spacer.style.flexShrink = '0';
        spacer.setAttribute('aria-hidden', 'true');
        row.appendChild(spacer);
      }

      const isSelected = selectedWeaponId === String(weapon.id);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `btn btn-sm text-start flex-grow-1 ${isSelected ? 'btn-primary' : 'btn-outline-secondary'}`;
      btn.textContent = weapon.name || `#${weapon.id}`;
      btn.addEventListener('click', () => {
        if (isSelected) {
          selectedWeaponId = '';
        } else {
          selectedWeaponId = String(weapon.id);
        }
        applySelection();
        renderTree();
      });
      row.appendChild(btn);
      li.appendChild(row);

      if (hasChildren && !isCollapsed) {
        const ul = document.createElement('ul');
        ul.className = 'ps-0 mb-0';
        weapon.children.forEach((child) => ul.appendChild(createWeaponNode(child, depth + 1)));
        li.appendChild(ul);
      }
      return li;
    }

    function renderTree() {
      treeContainer.innerHTML = '';
      const entry = currentEntry();
      if (!entry) {
        if (treeWrapper) treeWrapper.classList.add('d-none');
        return;
      }
      if (treeWrapper) treeWrapper.classList.remove('d-none');
      const weapons = Array.isArray(entry.weapons) ? entry.weapons : [];
      if (!weapons.length) {
        const empty = document.createElement('div');
        empty.className = 'text-muted small';
        empty.textContent = 'Brak broni w tej zbrojowni.';
        treeContainer.appendChild(empty);
        return;
      }
      const ul = document.createElement('ul');
      ul.className = 'ps-0 mb-0';
      weapons.forEach((w) => ul.appendChild(createWeaponNode(w, 0)));
      treeContainer.appendChild(ul);
    }

    function initCollapsed(weapons) {
      (Array.isArray(weapons) ? weapons : []).forEach((w) => {
        if (Array.isArray(w.children) && w.children.length) {
          collapsedWeapons.add(String(w.id));
          initCollapsed(w.children);
        }
      });
    }
    options.forEach((entry) => initCollapsed(entry.weapons));

    if (selectedWeaponId) {
      const entry = currentEntry();
      if (entry) {
        const expandPath = (weapons) => {
          for (const w of weapons) {
            if (String(w.id) === selectedWeaponId) return true;
            if (Array.isArray(w.children) && expandPath(w.children)) {
              collapsedWeapons.delete(String(w.id));
              return true;
            }
          }
          return false;
        };
        expandPath(entry.weapons || []);
      }
    }

    armorySelect.addEventListener('change', () => {
      selectedArmoryId = armorySelect.value || '';
      selectedWeaponId = '';
      applySelection();
      renderTree();
    });

    if (toggle && body) {
      let treeInitialized = false;
      toggle.addEventListener('click', () => {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        const next = !expanded;
        toggle.setAttribute('aria-expanded', next ? 'true' : 'false');
        body.classList.toggle('d-none', !next);
        if (chevron) chevron.textContent = next ? '▾' : '▸';
        if (next && !treeInitialized) {
          treeInitialized = true;
          renderTree();
        }
      });
    } else {
      renderTree();
    }
}

const INHERITANCE_PANEL_CFG = {
  panelAttr: 'data-inheritance-panel',
  toggleAttr: 'data-inheritance-toggle',
  bodyAttr: 'data-inheritance-body',
  armorySelectAttr: 'data-inheritance-armory-select',
  treeWrapperAttr: 'data-inheritance-tree-wrapper',
  treeAttr: 'data-inheritance-tree',
  armoryValueAttr: 'data-inheritance-armory-value',
  weaponValueAttr: 'data-inheritance-weapon-value',
  chevronAttr: 'data-inheritance-chevron',
  optionsDataKey: 'inheritanceOptions',
  currentDataKey: 'currentInheritance',
};

const IMPORT_PANEL_CFG = {
  panelAttr: 'data-import-panel',
  toggleAttr: null,
  bodyAttr: null,
  armorySelectAttr: 'data-import-armory-select',
  treeWrapperAttr: 'data-import-tree-wrapper',
  treeAttr: 'data-import-tree',
  armoryValueAttr: 'data-import-armory-value',
  weaponValueAttr: 'data-import-weapon-value',
  chevronAttr: null,
  optionsDataKey: 'importOptions',
  currentDataKey: null,
};

function initWeaponInheritancePanel() {
  document.querySelectorAll(`[${INHERITANCE_PANEL_CFG.panelAttr}]`).forEach((panel) => {
    initWeaponTreePickerPanel(panel, INHERITANCE_PANEL_CFG);
  });
}

function initWeaponImportPanel() {
  document.querySelectorAll(`[${IMPORT_PANEL_CFG.panelAttr}]`).forEach((panel) => {
    initWeaponTreePickerPanel(panel, IMPORT_PANEL_CFG);
  });
}


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
