// Kolekcja Faza 2b — „Tryb modeli" w prawym panelu edytora rozpiski.
// Samodzielny moduł (nie sięga do domknięcia roster_editor.js): czyta aktywny
// oddział z DOM, pobiera modele kolekcji użytkownika dla tego oddziału i pozwala
// SKOMPONOWAĆ oddział przez wybór egzemplarzy (modele → suma). Zapis jest
// AUTOMATYCZNY po każdej zmianie (debounce), z aktualizacją kosztu w miejscu —
// bez przeładowania. Wyjście z trybu (górny przycisk) przeładowuje raz z
// zachowaniem zaznaczenia, aby zsynchronizować klasyczny edytor.
(function () {
  const SAVE_DEBOUNCE_MS = 400;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function init() {
    const root = document.querySelector('[data-roster-root]');
    if (!root) return;
    const rosterId = root.dataset.rosterId || '';
    const editor = root.querySelector('[data-roster-editor]');
    const toggle = root.querySelector('[data-roster-models-toggle]');
    const panel = root.querySelector('[data-roster-models-panel]');
    if (!rosterId || !editor || !toggle || !panel) return;

    let modelsMode = false;
    let activeItem = null;
    let rosterUnitId = '';
    let data = null; // odpowiedź endpointu
    const selections = new Map(); // collection_model_id (str) -> qty

    let saveTimer = null;
    let saveController = null;
    let saveSeq = 0;
    let appliedSeq = 0;
    let pendingChanges = false; // zmiana niewysłana jeszcze do serwera
    let savedSomething = false; // czy w tej sesji trybu coś zapisano

    const hideEls = () => Array.from(editor.querySelectorAll('[data-models-hide]'));
    const getActiveItem = () => root.querySelector('[data-roster-item].active');

    // W trybie modeli klasyczny formularz (m.in. wciąż widoczne zdolności
    // pasywne) jest read-only — inaczej jego własny autosave nadpisałby
    // skomponowaną broń nieaktualnym stanem sprzed kompozycji.
    function setClassicReadonly(on) {
      const classicForm = editor.querySelector('[data-roster-editor-form]');
      const customLabel = editor.querySelector('[data-roster-editor-custom-label]');
      [classicForm, customLabel].forEach((el) => {
        if (el) el.classList.toggle('roster-models-readonly', on);
      });
    }

    function restoreClassicSections() {
      modelsMode = false;
      toggle.setAttribute('aria-pressed', 'false');
      toggle.classList.remove('active');
      toggle.textContent = 'Tryb modeli';
      panel.classList.add('d-none');
      panel.innerHTML = '';
      hideEls().forEach((el) => el.classList.remove('d-none'));
      setClassicReadonly(false);
      data = null;
      selections.clear();
      activeItem = null;
      rosterUnitId = '';
    }

    async function exitModelsMode() {
      if (saveTimer) {
        window.clearTimeout(saveTimer);
        saveTimer = null;
      }
      // Dokończ ostatnią niewysłaną zmianę zanim przeładujemy.
      if (pendingChanges && aggregate().count > 0) {
        await doSave();
      }
      if (savedSomething && rosterUnitId) {
        // Reload z zaznaczeniem edytowanego oddziału — synchronizuje klasyczny
        // edytor z nowym loadoutem i zachowuje zaznaczenie.
        window.location.href = `/rosters/${rosterId}?selected=${rosterUnitId}`;
        return;
      }
      restoreClassicSections();
    }

    async function enterModelsMode() {
      const item = getActiveItem();
      if (!item) {
        window.alert('Najpierw wybierz oddział z listy.');
        return;
      }
      const unitId = item.getAttribute('data-roster-unit-id');
      if (!unitId) return;
      activeItem = item;
      rosterUnitId = unitId;
      modelsMode = true;
      savedSomething = false;
      pendingChanges = false;
      toggle.setAttribute('aria-pressed', 'true');
      toggle.classList.add('active');
      toggle.textContent = 'Tryb klasyczny';
      hideEls().forEach((el) => el.classList.add('d-none'));
      setClassicReadonly(true);
      panel.classList.remove('d-none');
      panel.innerHTML = '<div class="text-muted small">Wczytywanie modeli…</div>';
      try {
        const resp = await fetch(
          `/rosters/${rosterId}/units/${rosterUnitId}/collection-models`,
          { headers: { Accept: 'application/json' }, credentials: 'same-origin' },
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        data = await resp.json();
      } catch (err) {
        panel.innerHTML = '<div class="text-danger small">Nie udało się wczytać modeli kolekcji.</div>';
        return;
      }
      selections.clear();
      (Array.isArray(data.composed) ? data.composed : []).forEach((entry) => {
        if (entry && entry.id != null) {
          selections.set(String(entry.id), Math.max(0, parseInt(entry.qty, 10) || 0));
        }
      });
      renderPanel();
    }

    function aggregate() {
      let count = 0;
      const weapons = {};
      const models = (data && data.models) || [];
      models.forEach((m) => {
        const qty = selections.get(String(m.id)) || 0;
        if (qty <= 0) return;
        count += qty;
        Object.entries(m.weapons || {}).forEach(([wid, c]) => {
          weapons[wid] = (weapons[wid] || 0) + qty * (Number(c) || 0);
        });
      });
      return { count, weapons };
    }

    function aggregateSummary(weapons) {
      const names = (data && data.weapon_names) || {};
      const parts = Object.keys(weapons)
        .sort((a, b) => Number(a) - Number(b))
        .map((wid) => {
          const name = names[wid] || `Broń #${wid}`;
          const c = weapons[wid];
          return c > 1 ? `${name} ×${c}` : name;
        });
      return parts.length ? parts.join(', ') : '—';
    }

    function renderPanel() {
      const models = (data && data.models) || [];
      const coverage = (data && data.coverage) || { owned: 0, needed: 0 };
      const agg = aggregate();

      let rows = '';
      if (!models.length) {
        rows = '<div class="alert alert-info py-2 px-3 small mb-3">'
          + 'Brak modeli tego oddziału w Twojej kolekcji. '
          + 'Dodaj je w zakładce <a href="/collections">Kolekcja</a>.'
          + '</div>';
      } else {
        rows = models.map((m) => {
          const qty = selections.get(String(m.id)) || 0;
          const label = m.label ? escapeHtml(m.label) : '<span class="text-muted fst-italic">bez nazwy</span>';
          return `
            <div class="d-flex align-items-center gap-2 border rounded p-2 mb-2">
              <div class="flex-grow-1">
                <div class="small fw-semibold">${label}</div>
                <div class="text-muted small">${escapeHtml(m.summary || '—')}</div>
              </div>
              <div class="d-flex align-items-center gap-1 flex-shrink-0">
                <input type="number" class="form-control form-control-sm" style="width:4.5rem"
                       min="0" max="${m.count}" value="${qty}"
                       data-models-qty="${m.id}" aria-label="Liczba modeli" />
                <span class="text-muted small">/ ${m.count}</span>
              </div>
            </div>`;
        }).join('');
      }

      panel.innerHTML = `
        <div class="mb-2 text-muted small">
          Posiadasz <strong>${coverage.owned}</strong> modeli tego oddziału;
          rozpiska liczy <strong>${coverage.needed}</strong>.
        </div>
        <div class="flex-grow-1" data-models-list>${rows}</div>
        <div class="border-top pt-2 mt-2">
          <div class="small">Skomponowany oddział:
            <strong data-models-preview-count>${agg.count}</strong> modeli
          </div>
          <div class="text-muted small" data-models-preview-weapons>${escapeHtml(aggregateSummary(agg.weapons))}</div>
          <div class="text-muted small mt-1" data-models-status></div>
        </div>`;
    }

    function setStatus(text, isError) {
      const el = panel.querySelector('[data-models-status]');
      if (!el) return;
      el.textContent = text || '';
      el.classList.toggle('text-danger', Boolean(isError));
    }

    function updatePreview() {
      const agg = aggregate();
      const countEl = panel.querySelector('[data-models-preview-count]');
      const weaponsEl = panel.querySelector('[data-models-preview-weapons]');
      if (countEl) countEl.textContent = String(agg.count);
      if (weaponsEl) weaponsEl.textContent = aggregateSummary(agg.weapons);
    }

    function applyCostUpdate(payload) {
      if (!payload || typeof payload !== 'object') return;
      const unit = payload.unit || {};
      const cost = unit.cached_cost;
      if (activeItem && cost != null) {
        const badge = activeItem.querySelector('[data-roster-unit-cost]');
        if (badge) badge.textContent = `${cost} pkt`;
        if (unit.count != null) {
          activeItem.setAttribute('data-unit-count', String(unit.count));
          const title = activeItem.querySelector('[data-roster-unit-title]');
          const name = activeItem.getAttribute('data-unit-name') || '';
          if (title) title.textContent = `${unit.count}x ${name}`;
        }
        if (unit.loadout_json) {
          activeItem.setAttribute('data-loadout', unit.loadout_json);
        }
        if (cost != null) activeItem.setAttribute('data-unit-cost', String(cost));
      }
      const editorCost = root.querySelector('[data-roster-editor-cost]');
      if (editorCost && cost != null) editorCost.textContent = String(cost);
      const totalEl = root.querySelector('[data-roster-total]');
      if (totalEl && payload.total_cost != null) {
        totalEl.textContent = String(payload.total_cost);
      }
      if (window.SZOPRosterWarnings && typeof window.SZOPRosterWarnings.recompute === 'function') {
        window.SZOPRosterWarnings.recompute();
      }
    }

    function scheduleSave() {
      pendingChanges = true;
      if (saveTimer) window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(() => {
        saveTimer = null;
        doSave();
      }, SAVE_DEBOUNCE_MS);
    }

    async function doSave() {
      if (!rosterUnitId) return;
      const agg = aggregate();
      if (agg.count <= 0) {
        // Pusty wybór — nie zapisujemy (oddział nie może mieć 0 modeli).
        setStatus('Wybierz co najmniej jeden model.');
        return;
      }
      const baseLoadout = (data && data.current_loadout && typeof data.current_loadout === 'object')
        ? { ...data.current_loadout }
        : {};
      baseLoadout.weapons = agg.weapons;
      baseLoadout.mode = 'total';

      const composed = [];
      selections.forEach((qty, id) => {
        if (qty > 0) composed.push({ id: Number(id), qty });
      });

      const form = new FormData();
      form.set('count', String(agg.count));
      form.set('loadout_json', JSON.stringify(baseLoadout));
      form.set('custom_name', activeItem ? (activeItem.getAttribute('data-unit-custom-name') || '') : '');
      form.set('composed_models_json', JSON.stringify(composed));

      const seq = ++saveSeq;
      pendingChanges = false;
      if (saveController) saveController.abort();
      saveController = new AbortController();
      setStatus('Zapisywanie…');
      try {
        const resp = await fetch(`/rosters/${rosterId}/units/${rosterUnitId}/update`, {
          method: 'POST',
          body: form,
          headers: { Accept: 'application/json' },
          credentials: 'same-origin',
          signal: saveController.signal,
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const payload = await resp.json();
        if (seq >= appliedSeq) {
          appliedSeq = seq;
          applyCostUpdate(payload);
          savedSomething = true;
          setStatus('Zapisano');
        }
      } catch (err) {
        if (err && err.name === 'AbortError') return;
        pendingChanges = true;
        setStatus('Błąd zapisu', true);
      }
    }

    toggle.addEventListener('click', (event) => {
      event.preventDefault();
      if (modelsMode) {
        exitModelsMode();
      } else {
        enterModelsMode();
      }
    });

    panel.addEventListener('input', (event) => {
      const input = event.target.closest('[data-models-qty]');
      if (!input) return;
      const id = input.getAttribute('data-models-qty');
      let qty = parseInt(input.value, 10);
      if (!Number.isFinite(qty) || qty < 0) qty = 0;
      const max = parseInt(input.getAttribute('max'), 10);
      if (Number.isFinite(max) && qty > max) {
        qty = max;
        input.value = String(qty);
      }
      selections.set(String(id), qty);
      updatePreview();
      scheduleSave();
    });

    // Przełączenie na INNY oddział w trybie modeli: dokończ ewentualny zapis w
    // tle i wróć do klasyka BEZ przeładowania — roster_editor sam zhydratyzuje
    // nowo wybrany oddział z aktualnego data-loadout (zaktualizowanego in-place).
    root.addEventListener('click', (event) => {
      if (!modelsMode) return;
      const item = event.target.closest('[data-roster-item]');
      if (!item || item === activeItem) return;
      if (saveTimer) {
        window.clearTimeout(saveTimer);
        saveTimer = null;
      }
      if (pendingChanges && aggregate().count > 0) doSave();
      restoreClassicSections();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
