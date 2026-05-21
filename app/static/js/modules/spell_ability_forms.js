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

    if (abilitySelect) {
      abilitySelect.addEventListener('change', handleAbilityChange);
      handleAbilityChange();
    }
    if (valueSelect) {
      valueSelect.addEventListener('change', updateValueDescriptionFromSelect);
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
