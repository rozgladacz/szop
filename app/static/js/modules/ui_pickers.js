(function initSZOPUIPickersModule(globalScope) {
// ============================================================
// SECTION: UI PICKERS — NUMBER, RANGE, WEAPON DEFAULTS
// initNumberPicker, initNumberPickers, initRangePicker,
// initRangePickers, initWeaponDefaults
//
// UWAGA: To są helpery UI (spinners, zakresy) — NIE silnik kosztów.
// Wywoływane w łańcuchu DOMContentLoaded. Ich brak = ReferenceError
// który cicho blokuje całą inicjalizację strony.
// NIE usuwać przy cleanup kosztowym.
// ============================================================
function initNumberPicker(root) {
  const selectEl = root.querySelector('.number-picker-select');
  const customInput = root.querySelector('.number-picker-custom');
  const hiddenInput = root.querySelector('.number-picker-value');
  const initialValue = root.dataset.selected || '';

  const syncHidden = (value) => {
    const text = value !== undefined && value !== null ? String(value) : '';
    if (hiddenInput) {
      hiddenInput.value = text;
    }
    root.dataset.selected = text;
  };

  const hideCustom = () => {
    if (customInput) {
      customInput.classList.add('d-none');
      customInput.value = '';
    }
  };

  const showCustom = () => {
    if (customInput) {
      customInput.classList.remove('d-none');
    }
  };

  const findMatchingOption = (value) => {
    if (!selectEl) {
      return '';
    }
    const textValue = String(value).trim();
    if (!textValue) {
      return '';
    }
    const numeric = Number(textValue);
    let matched = '';
    Array.from(selectEl.options || []).forEach((option) => {
      if (!option.value || option.value === '__custom__') {
        if (!matched && option.value === textValue) {
          matched = option.value;
        }
        return;
      }
      if (option.value === textValue) {
        matched = option.value;
        return;
      }
      const optionNumeric = Number(option.value);
      if (Number.isFinite(optionNumeric) && Number.isFinite(numeric) && optionNumeric === numeric) {
        matched = option.value;
      }
    });
    return matched;
  };

  const setValue = (rawValue) => {
    const textValue = rawValue !== undefined && rawValue !== null ? String(rawValue).trim() : '';
    if (!textValue) {
      if (selectEl) {
        selectEl.value = '';
      }
      hideCustom();
      syncHidden('');
      return;
    }
    const matched = findMatchingOption(textValue);
    if (matched) {
      if (selectEl) {
        selectEl.value = matched;
      }
      hideCustom();
      syncHidden(matched);
      return;
    }
    if (selectEl) {
      selectEl.value = '__custom__';
    }
    showCustom();
    if (customInput) {
      customInput.value = textValue;
    }
    syncHidden(textValue);
  };

  if (selectEl) {
    selectEl.addEventListener('change', () => {
      const value = selectEl.value;
      if (value === '__custom__') {
        showCustom();
        if (customInput && !customInput.value) {
          customInput.focus();
        }
        syncHidden(customInput ? customInput.value || '' : '');
      } else if (value === '') {
        hideCustom();
        syncHidden('');
      } else {
        hideCustom();
        syncHidden(value);
      }
    });
  }

  if (customInput) {
    customInput.addEventListener('input', () => {
      if (selectEl && selectEl.value !== '__custom__') {
        selectEl.value = '__custom__';
      }
      syncHidden(customInput.value || '');
    });
  }

  setValue(initialValue);

  root.numberPicker = {
    setValue: (value) => setValue(value),
  };
}

function initNumberPickers() {
  document.querySelectorAll('[data-number-picker]').forEach((element) => {
    initNumberPicker(element);
  });
}

function initRangePicker(root) {
  const selectEl = root.querySelector('.range-picker-select');
  const customInput = root.querySelector('.range-picker-custom');
  const hiddenInput = root.querySelector('.range-picker-value');
  const initialValue = root.dataset.selected || '';

  const normalizeForOption = (raw) => {
    if (raw === undefined || raw === null) {
      return '';
    }
    const text = String(raw).trim();
    if (!text) {
      return '';
    }
    const lowered = text.toLowerCase();
    if (lowered === 'none' || lowered === 'null' || lowered === 'undefined') {
      return '';
    }
    if (['wrÄ™cz', 'wrecz', 'melee', 'm'].includes(lowered)) {
      return '0';
    }
    const numericMatch = lowered.match(/^(\d+)(?:["â€ť])?$/);
    if (numericMatch) {
      return numericMatch[1];
    }
    return text;
  };

  const showCustom = () => {
    if (customInput) {
      customInput.classList.remove('d-none');
    }
  };

  const hideCustom = () => {
    if (customInput) {
      customInput.classList.add('d-none');
      customInput.value = '';
    }
  };

  const syncHidden = (value) => {
    const text = value !== undefined && value !== null ? String(value) : '';
    if (hiddenInput) {
      hiddenInput.value = text;
    }
    root.dataset.selected = text;
  };

  const setValue = (rawValue) => {
    const textValue = rawValue !== undefined && rawValue !== null ? String(rawValue).trim() : '';
    if (!textValue) {
      if (selectEl) {
        selectEl.value = '';
      }
      hideCustom();
      syncHidden('');
      return;
    }
    if (textValue.toLowerCase() === '__custom__') {
      if (selectEl) {
        selectEl.value = '__custom__';
      }
      showCustom();
      if (customInput && !customInput.value) {
        customInput.focus();
      }
      syncHidden(customInput ? customInput.value || '' : '');
      return;
    }
    const normalized = normalizeForOption(textValue);
    if (!normalized) {
      if (selectEl) {
        selectEl.value = '';
      }
      hideCustom();
      syncHidden('');
      return;
    }
    if (selectEl && normalized !== '__custom__') {
      const option = Array.from(selectEl.options || []).find((opt) => opt.value === normalized);
      if (option && normalized !== '__custom__') {
        selectEl.value = normalized;
        hideCustom();
        syncHidden(normalized);
        return;
      }
    }
    if (selectEl) {
      selectEl.value = '__custom__';
    }
    showCustom();
    if (customInput) {
      customInput.value = textValue;
    }
    syncHidden(textValue);
  };

  if (selectEl) {
    selectEl.addEventListener('change', () => {
      const value = selectEl.value;
      if (value === '__custom__') {
        showCustom();
        if (customInput && !customInput.value) {
          customInput.focus();
        }
        syncHidden(customInput ? customInput.value : '');
      } else {
        hideCustom();
        syncHidden(value);
      }
    });
  }

  if (customInput) {
    customInput.addEventListener('input', () => {
      syncHidden(customInput.value || '');
    });
  }

  setValue(initialValue);
  root.rangePicker = {
    setValue,
  };
}

function initRangePickers() {
  document.querySelectorAll('[data-range-picker]').forEach((element) => {
    initRangePicker(element);
  });
}

function initWeaponDefaults() {
  document.querySelectorAll('form[data-defaults]').forEach((form) => {
    const defaultsData = form.dataset.defaults;
    if (!defaultsData) {
      return;
    }
    let defaults = null;
    try {
      defaults = JSON.parse(defaultsData);
    } catch (err) {
      defaults = null;
    }
    if (!defaults) {
      return;
    }
    const resetButton = form.querySelector('[data-weapon-reset]');
    if (!resetButton) {
      return;
    }
    resetButton.addEventListener('click', () => {
      const nameInput = form.querySelector('#name');
      if (nameInput) {
        nameInput.value = defaults.name || '';
      }
      const rangePicker = form.querySelector('[data-range-picker]');
      if (rangePicker && rangePicker.rangePicker && typeof rangePicker.rangePicker.setValue === 'function') {
        rangePicker.rangePicker.setValue(defaults.range || '');
      }
      const attacksPicker = form.querySelector('[data-number-picker][data-target-input="attacks"]');
      if (attacksPicker && attacksPicker.numberPicker && typeof attacksPicker.numberPicker.setValue === 'function') {
        attacksPicker.numberPicker.setValue(defaults.attacks || '');
      } else {
        const attacksInput = form.querySelector('#attacks');
        if (attacksInput) {
          attacksInput.value = defaults.attacks || '';
        }
      }
      const apPicker = form.querySelector('[data-number-picker][data-target-input="ap"]');
      if (apPicker && apPicker.numberPicker && typeof apPicker.numberPicker.setValue === 'function') {
        apPicker.numberPicker.setValue(defaults.ap || '');
      } else {
        const apInput = form.querySelector('#ap');
        if (apInput) {
          apInput.value = defaults.ap || '';
        }
      }
      const notesInput = form.querySelector('#notes');
      if (notesInput) {
        notesInput.value = defaults.notes || '';
      }
      const abilityPickerRoot = form.querySelector('[data-ability-picker]');
      if (abilityPickerRoot && abilityPickerRoot.abilityPicker && typeof abilityPickerRoot.abilityPicker.setItems === 'function') {
        abilityPickerRoot.abilityPicker.setItems(defaults.abilities || []);
      }
    });
  });
}

  const api = {
    initNumberPicker: initNumberPicker,
    initNumberPickers: initNumberPickers,
    initRangePicker: initRangePicker,
    initRangePickers: initRangePickers,
    initWeaponDefaults: initWeaponDefaults,
  };
  globalScope.SZOPUIPickers = api;
  globalScope.initNumberPicker = initNumberPicker;
  globalScope.initNumberPickers = initNumberPickers;
  globalScope.initRangePicker = initRangePicker;
  globalScope.initRangePickers = initRangePickers;
  globalScope.initWeaponDefaults = initWeaponDefaults;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPUIPickers = api;
    globalThis.initNumberPicker = initNumberPicker;
    globalThis.initNumberPickers = initNumberPickers;
    globalThis.initRangePicker = initRangePicker;
    globalThis.initRangePickers = initRangePickers;
    globalThis.initWeaponDefaults = initWeaponDefaults;
  }
}(typeof window !== 'undefined' ? window : globalThis));
