(function initSZOPSpellAbilityFormsModule(globalScope) {
// ============================================================
// SECTION: SPELL ABILITY FORMS
// initSpellAbilityForms — formularze zdolności zaklęć
// ============================================================
function initSpellAbilityForms() {
  document.querySelectorAll('[data-spell-ability-form]').forEach((form) => {
    const abilitySelect = form.querySelector('[data-ability-select]');
    const valueContainer = form.querySelector('[data-ability-value-container]');
    const valueLabelEl = form.querySelector('[data-ability-value-label]');
    const valueSelect = form.querySelector('[data-ability-value-select]');
    const valueInput = form.querySelector('[data-ability-value-input]');
    const valueDescription = form.querySelector('[data-ability-value-description]');
    const passiveListId = form.dataset.passiveAbilityListId || '';
    const armyId = form.dataset.armyId || '';
    const costBlock = form.querySelector('[data-spell-ability-cost-block]');
    const pointCostEl = form.querySelector('[data-spell-ability-point-cost]');
    const difficultyOptionsEl = form.querySelector('[data-spell-ability-difficulty-options]');
    const defaultDifficulty = String(form.dataset.defaultDifficulty || '4');
    let costTimer = null;
    let costController = null;

    function selectedDifficulty() {
      const checked = form.querySelector('input[name="cast_difficulty"]:checked');
      return checked ? checked.value : defaultDifficulty;
    }

    function renderAbilityCost(data, keepDifficulty) {
      if (!costBlock || !difficultyOptionsEl) {
        return;
      }
      const tokens = (data && data.tokens) || {};
      const diffs = Object.keys(tokens).sort((a, b) => Number(a) - Number(b));
      if (diffs.length === 0) {
        costBlock.classList.add('d-none');
        difficultyOptionsEl.innerHTML = '';
        return;
      }
      costBlock.classList.remove('d-none');
      if (pointCostEl) {
        pointCostEl.textContent = data && data.point_cost != null ? String(data.point_cost) : '—';
      }
      const want = String(keepDifficulty || defaultDifficulty);
      difficultyOptionsEl.innerHTML = '';
      diffs.forEach((d, idx) => {
        const id = `cast-diff-${idx}-${d}`;
        const wrap = document.createElement('div');
        wrap.className = 'form-check';
        const radio = document.createElement('input');
        radio.className = 'form-check-input';
        radio.type = 'radio';
        radio.name = 'cast_difficulty';
        radio.value = d;
        radio.id = id;
        radio.checked = d === want;
        const label = document.createElement('label');
        label.className = 'form-check-label text-nowrap';
        label.setAttribute('for', id);
        label.textContent = `${d}+ — ${tokens[d]} żet.`;
        wrap.appendChild(radio);
        wrap.appendChild(label);
        difficultyOptionsEl.appendChild(wrap);
      });
    }

    function currentAbilityValue() {
      if (valueSelect && !valueSelect.classList.contains('d-none')) {
        return valueSelect.value || '';
      }
      if (valueInput && !valueInput.classList.contains('d-none')) {
        return valueInput.value || '';
      }
      return '';
    }

    function fetchAbilityCost() {
      if (!abilitySelect || !armyId || !costBlock) {
        return;
      }
      const abilityId = abilitySelect.value;
      if (!abilityId) {
        costBlock.classList.add('d-none');
        if (difficultyOptionsEl) {
          difficultyOptionsEl.innerHTML = '';
        }
        return;
      }
      const keep = selectedDifficulty();
      const value = currentAbilityValue();
      if (costTimer) {
        window.clearTimeout(costTimer);
      }
      if (costController) {
        costController.abort();
        costController = null;
      }
      costTimer = window.setTimeout(() => {
        costTimer = null;
        costController = new AbortController();
        const signal = costController.signal;
        fetch(`/armies/${armyId}/spells/ability-cost-preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ ability_id: abilityId, value }),
          credentials: 'same-origin',
          signal,
        })
          .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
          .then((data) => {
            if (costController && costController.signal === signal) {
              costController = null;
            }
            renderAbilityCost(data, keep);
          })
          .catch((err) => {
            if (err && err.name === 'AbortError') {
              return;
            }
            console.error('Nie udało się pobrać kosztu mocy', err);
          });
      }, 250);
    }

    function resetValueDescription() {
      if (valueDescription) {
        valueDescription.textContent = '';
        valueDescription.classList.add('d-none');
      }
    }

    function setValueInputList(kind) {
      if (!valueInput) {
        return;
      }
      if (kind === 'passive' && passiveListId) {
        valueInput.setAttribute('list', passiveListId);
      } else {
        valueInput.removeAttribute('list');
      }
    }

    function updateValueDescriptionFromSelect() {
      if (!valueDescription || !valueSelect) {
        return;
      }
      const option = valueSelect.selectedOptions && valueSelect.selectedOptions.length > 0 ? valueSelect.selectedOptions[0] : null;
      const description = option && option.dataset ? option.dataset.description || '' : '';
      if (description) {
        valueDescription.textContent = description;
        valueDescription.classList.remove('d-none');
      } else {
        resetValueDescription();
      }
    }

    function hideValueInputs() {
      if (valueContainer) {
        valueContainer.classList.add('d-none');
      }
      if (valueSelect) {
        valueSelect.classList.add('d-none');
        valueSelect.innerHTML = '';
        valueSelect.disabled = true;
      }
      if (valueInput) {
        valueInput.classList.add('d-none');
        valueInput.value = '';
        valueInput.disabled = true;
        valueInput.type = 'text';
        valueInput.removeAttribute('list');
      }
      resetValueDescription();
    }

    function showValueSelect(labelText, choices) {
      if (!valueContainer || !valueSelect) {
        return;
      }
      valueContainer.classList.remove('d-none');
      valueSelect.classList.remove('d-none');
      valueSelect.disabled = false;
      valueSelect.innerHTML = '';
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = labelText ? `Wybierz (${labelText})` : 'Wybierz wartość';
      valueSelect.appendChild(placeholder);
      (choices || []).forEach((choice) => {
        if (choice && typeof choice === 'object') {
          const option = document.createElement('option');
          option.value = choice.value ?? '';
          option.textContent = choice.label ?? choice.value ?? '';
          if (choice.description) {
            option.dataset.description = choice.description;
            option.title = choice.description;
          }
          valueSelect.appendChild(option);
        } else {
          const option = document.createElement('option');
          option.value = choice ?? '';
          option.textContent = choice ?? '';
          valueSelect.appendChild(option);
        }
      });
      if (valueInput) {
        valueInput.classList.add('d-none');
        valueInput.disabled = true;
        setValueInputList('');
      }
      resetValueDescription();
      valueSelect.value = '';
      updateValueDescriptionFromSelect();
    }

    function showValueInput(labelText, valueType, valueKind) {
      if (!valueContainer || !valueInput) {
        return;
      }
      valueContainer.classList.remove('d-none');
      valueInput.classList.remove('d-none');
      valueInput.disabled = false;
      valueInput.placeholder = labelText ? `Wartość (${labelText})` : 'Wartość';
      valueInput.type = valueType === 'number' ? 'number' : 'text';
      setValueInputList(valueKind || '');
      if (valueSelect) {
        valueSelect.classList.add('d-none');
        valueSelect.innerHTML = '';
        valueSelect.disabled = true;
      }
      resetValueDescription();
    }

    const htmlDecoder = document.createElement('textarea');

    function parseChoiceDataset(option) {
      if (!option) {
        return [];
      }
      const rawAttribute = option.getAttribute('data-value-choices') || '';
      const rawDataset = option.dataset.valueChoices || '';
      const raw = rawAttribute || rawDataset;
      if (!raw) {
        return [];
      }
      let decoded = raw;
      if (raw.includes('&')) {
        htmlDecoder.innerHTML = raw;
        decoded = htmlDecoder.value || raw;
      }
      try {
        const parsed = JSON.parse(decoded);
        return Array.isArray(parsed) ? parsed : [];
      } catch (err) {
        if (rawAttribute && rawAttribute !== decoded) {
          try {
            const parsed = JSON.parse(rawAttribute);
            return Array.isArray(parsed) ? parsed : [];
          } catch (innerErr) {
            return [];
          }
        }
        return [];
      }
    }

    function handleAbilityChange() {
      if (!abilitySelect) {
        return;
      }
      resetValueDescription();
      const option = abilitySelect.selectedOptions[0];
      if (!option) {
        hideValueInputs();
        return;
      }
      const requiresValue = option.dataset.requiresValue === 'true';
      if (!requiresValue) {
        hideValueInputs();
        return;
      }
      const labelText = option.dataset.valueLabel || '';
      if (valueLabelEl) {
        valueLabelEl.textContent = labelText ? `Wartość (${labelText})` : 'Wartość';
      }
      const valueKind = option.dataset.valueKind || '';
      const choices = parseChoiceDataset(option);
      if (Array.isArray(choices) && choices.length > 0) {
        showValueSelect(labelText, choices);
      } else {
        const valueType = option.dataset.valueType || 'text';
        showValueInput(labelText, valueType, valueKind);
      }
    }

    function applyInitialValue() {
      const initialValue = form.dataset.initialValue || '';
      if (!initialValue) {
        return;
      }
      if (valueSelect && !valueSelect.classList.contains('d-none')) {
        valueSelect.value = initialValue;
        updateValueDescriptionFromSelect();
      } else if (valueInput && !valueInput.classList.contains('d-none')) {
        valueInput.value = initialValue;
      }
    }

    if (abilitySelect) {
      abilitySelect.addEventListener('change', () => {
        handleAbilityChange();
        fetchAbilityCost();
      });
      handleAbilityChange();
      // Edit mode: a pre-selected ability needs its stored value restored once.
      applyInitialValue();
      fetchAbilityCost();
    }
    if (valueSelect) {
      valueSelect.addEventListener('change', () => {
        updateValueDescriptionFromSelect();
        fetchAbilityCost();
      });
    }
    if (valueInput) {
      valueInput.addEventListener('input', fetchAbilityCost);
    }
  });
}

  const api = {
    initSpellAbilityForms: initSpellAbilityForms,
  };
  globalScope.SZOPSpellAbilityForms = api;
  globalScope.initSpellAbilityForms = initSpellAbilityForms;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPSpellAbilityForms = api;
    globalThis.initSpellAbilityForms = initSpellAbilityForms;
  }
}(typeof window !== 'undefined' ? window : globalThis));
