(function initSZOPAbilityPickerModule(globalScope) {
  const rosterRendering = globalScope.SZOPRosterRendering
    || (typeof globalThis !== 'undefined' ? globalThis.SZOPRosterRendering : null)
    || {};
  const loadoutState = globalScope.SZOPLoadoutState
    || (typeof globalThis !== 'undefined' ? globalThis.SZOPLoadoutState : null)
    || {};
  const textParsing = globalScope.SZOPTextParsing
    || (typeof globalThis !== 'undefined' ? globalThis.SZOPTextParsing : null)
    || {};
  const formatPoints = rosterRendering.formatPoints
    || globalScope.formatPoints
    || function formatPointsFallback(value) {
      return value !== undefined && value !== null ? String(value) : '0';
    };
  const formatAbilityDisplayLabel = loadoutState.formatAbilityDisplayLabel
    || globalScope.formatAbilityDisplayLabel
    || function formatAbilityDisplayLabelFallback(baseLabel, customName) {
      return customName || baseLabel || '';
    };
  const ABILITY_NAME_MAX_LENGTH = (textParsing && Number.isFinite(Number(textParsing.ABILITY_NAME_MAX_LENGTH)))
    ? Number(textParsing.ABILITY_NAME_MAX_LENGTH)
    : (Number.isFinite(Number(globalScope.ABILITY_NAME_MAX_LENGTH)) ? Number(globalScope.ABILITY_NAME_MAX_LENGTH) : 60);
  const ARMY_RULE_OFF_PREFIX = (typeof globalScope.ARMY_RULE_OFF_PREFIX === 'string' && globalScope.ARMY_RULE_OFF_PREFIX)
    ? globalScope.ARMY_RULE_OFF_PREFIX
    : '__army_off__';
  const abilityDefinitionsCache = new Map();

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

  const api = {
    initAbilityPicker: initAbilityPicker,
    initAbilityPickers: initAbilityPickers,
  };
  globalScope.SZOPAbilityPicker = api;
  globalScope.initAbilityPicker = initAbilityPicker;
  globalScope.initAbilityPickers = initAbilityPickers;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPAbilityPicker = api;
    globalThis.initAbilityPicker = initAbilityPicker;
    globalThis.initAbilityPickers = initAbilityPickers;
  }
}(typeof window !== 'undefined' ? window : globalThis));
