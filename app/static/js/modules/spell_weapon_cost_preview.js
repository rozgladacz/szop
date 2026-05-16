(function initSZOPSpellWeaponCostPreviewModule(globalScope) {
// ============================================================
// SECTION: SPELL WEAPON COST PREVIEW
// initSpellWeaponCostPreview — podgląd kosztu broni zaklęcia,
// wywołuje POST /armies/{id}/spells/weapon-cost-preview
// ============================================================
function initSpellWeaponCostPreview() {
  document.querySelectorAll('form[data-spell-weapon-form]').forEach((form) => {
    const costValueEl = form.querySelector('[data-spell-weapon-cost]');
    if (!costValueEl) {
      return;
    }

    const armyId = form.dataset.armyId || '';
    if (!armyId) {
      return;
    }

    let spellPreviewTimer = null;
    let spellPreviewController = null;

    const collectTraits = () => {
      const hidden = form.querySelector('#weapon-abilities');
      if (!hidden) {
        return [];
      }
      try {
        const payload = JSON.parse(hidden.value || '[]');
        if (!Array.isArray(payload)) {
          return [];
        }
        return payload
          .map((entry) => {
            if (!entry || typeof entry !== 'object') {
              return '';
            }
            const raw = String(entry.raw || '').trim();
            if (raw) {
              return raw;
            }
            return String(entry.label || '').trim();
          })
          .filter((entry) => entry.length > 0);
      } catch (err) {
        return [];
      }
    };

    const collectFormValues = () => {
      const rangeInput = form.querySelector('input[name="range"]');
      const attacksInput = form.querySelector('input[name="attacks"]');
      const apInput = form.querySelector('input[name="ap"]');
      return {
        range: rangeInput ? rangeInput.value : '',
        attacks: attacksInput ? attacksInput.value : '',
        ap: apInput ? apInput.value : '',
        abilities: collectTraits(),
      };
    };

    const updatePreview = () => {
      if (spellPreviewTimer) {
        window.clearTimeout(spellPreviewTimer);
      }
      if (spellPreviewController) {
        spellPreviewController.abort();
        spellPreviewController = null;
      }
      spellPreviewTimer = window.setTimeout(() => {
        spellPreviewTimer = null;
        const formValues = collectFormValues();
        spellPreviewController = new AbortController();
        const signal = spellPreviewController.signal;
        fetch(`/armies/${armyId}/spells/weapon-cost-preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify(formValues),
          credentials: 'same-origin',
          signal,
        })
          .then((res) => res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)))
          .then((data) => {
            if (spellPreviewController && spellPreviewController.signal === signal) {
              spellPreviewController = null;
            }
            const cost = data?.spell_cost;
            if (cost != null) {
              costValueEl.textContent = String(cost);
            }
          })
          .catch((err) => {
            if (err && err.name === 'AbortError') {
              return;
            }
            console.error('Nie udało się pobrać podglądu kosztu broni zaklęcia', err);
          });
      }, 300);
    };

    updatePreview();

    ['input', 'change'].forEach((eventName) => {
      form.addEventListener(eventName, (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        if (
          target.matches('#name')
          || target.matches('#notes')
          || target.matches('.ability-picker-select')
          || target.matches('.ability-picker-value-input')
          || target.matches('.ability-picker-value-select')
          || target.matches('.ability-picker-add')
          || target.closest('.ability-picker-list')
          || target.matches('.range-picker-select')
          || target.matches('.range-picker-custom')
          || target.matches('.number-picker-select')
          || target.matches('.number-picker-custom')
          || target.matches('input[name="range"]')
          || target.matches('input[name="attacks"]')
          || target.matches('input[name="ap"]')
        ) {
          updatePreview();
        }
      });
    });

    const abilitiesInput = form.querySelector('#weapon-abilities');
    if (abilitiesInput) {
      const observer = new MutationObserver(() => {
        updatePreview();
      });
      observer.observe(abilitiesInput, { attributes: true, attributeFilter: ['value'] });
      abilitiesInput.addEventListener('input', updatePreview);
      abilitiesInput.addEventListener('change', updatePreview);
    }
  });
}

  const api = {
    initSpellWeaponCostPreview: initSpellWeaponCostPreview,
  };
  globalScope.SZOPSpellWeaponCostPreview = api;
  globalScope.initSpellWeaponCostPreview = initSpellWeaponCostPreview;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPSpellWeaponCostPreview = api;
    globalThis.initSpellWeaponCostPreview = initSpellWeaponCostPreview;
  }
}(typeof window !== 'undefined' ? window : globalThis));
