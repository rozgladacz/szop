(function initSZOPSpellWeaponCostPreviewModule(globalScope) {
// ============================================================
// SECTION: SPELL WEAPON COST PREVIEW
// initSpellWeaponCostPreview — podgląd kosztu broni zaklęcia.
// Wywołuje POST /armies/{id}/spells/weapon-cost-preview, renderuje
// radio buttony trudności (jakości ataku) z kosztem żetonowym każdej opcji.
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

    const frameEl = form.querySelector('[data-spell-quality-frame]');
    const optionsEl = form.querySelector('[data-spell-quality-options]');
    const pointEl = form.querySelector('[data-spell-weapon-point-cost]');
    const defaultQuality = String((frameEl && frameEl.dataset.defaultQuality) || '4');

    let spellPreviewTimer = null;
    let spellPreviewController = null;
    let lastData = {};

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

    const selectedQuality = () => {
      const checked = form.querySelector('input[name="quality"]:checked');
      return checked ? checked.value : defaultQuality;
    };

    const collectFormValues = () => {
      const rangeInput = form.querySelector('input[name="range"]');
      const attacksInput = form.querySelector('input[name="attacks"]');
      const apInput = form.querySelector('input[name="ap"]');
      return {
        range: rangeInput ? rangeInput.value : '',
        attacks: attacksInput ? attacksInput.value : '',
        ap: apInput ? apInput.value : '',
        quality: selectedQuality(),
        abilities: collectTraits(),
      };
    };

    const updateDisplaysFor = (quality) => {
      const tokens = (lastData && lastData.tokens) || {};
      const points = (lastData && lastData.points) || {};
      costValueEl.textContent = tokens[quality] != null ? String(tokens[quality]) : '—';
      if (pointEl) {
        pointEl.textContent = points[quality] != null ? String(points[quality]) : '—';
      }
    };

    const renderQualityOptions = (data, keepQuality) => {
      lastData = data || {};
      if (!optionsEl) {
        const cost = data && data.spell_cost;
        if (cost != null) {
          costValueEl.textContent = String(cost);
        }
        const point = data && data.point_cost;
        if (pointEl && point != null) {
          pointEl.textContent = String(point);
        }
        return;
      }
      const tokens = (data && data.tokens) || {};
      const diffs = Object.keys(tokens).sort((a, b) => Number(a) - Number(b));
      optionsEl.innerHTML = '';
      if (diffs.length === 0) {
        return;
      }
      const want = String(keepQuality || defaultQuality);
      const chosen = diffs.includes(want) ? want : diffs[0];
      diffs.forEach((d) => {
        const id = `spell-quality-${d}`;
        const wrap = document.createElement('div');
        wrap.className = 'form-check';
        const radio = document.createElement('input');
        radio.className = 'form-check-input';
        radio.type = 'radio';
        radio.name = 'quality';
        radio.value = d;
        radio.id = id;
        radio.checked = d === chosen;
        const label = document.createElement('label');
        label.className = 'form-check-label text-nowrap';
        label.setAttribute('for', id);
        label.textContent = `${d}+ — ${tokens[d]} żet.`;
        wrap.appendChild(radio);
        wrap.appendChild(label);
        optionsEl.appendChild(wrap);
      });
      updateDisplaysFor(chosen);
    };

    const updatePreview = () => {
      if (spellPreviewTimer) {
        window.clearTimeout(spellPreviewTimer);
      }
      if (spellPreviewController) {
        spellPreviewController.abort();
        spellPreviewController = null;
      }
      const keep = selectedQuality();
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
          .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
          .then((data) => {
            if (spellPreviewController && spellPreviewController.signal === signal) {
              spellPreviewController = null;
            }
            renderQualityOptions(data, keep);
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
        if (target.matches('input[name="quality"]')) {
          // Switching difficulty only re-reads the cached per-difficulty map.
          updateDisplaysFor(target.value);
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
