// Kolekcja Faza 2b/2b.1 — „Tryb modeli" w prawym panelu edytora rozpiski.
// Samodzielny moduł (nie sięga do domknięcia roster_editor.js): czyta aktywny
// oddział z DOM, pobiera modele kolekcji dla tego oddziału i pozwala SKOMPONOWAĆ
// oddział z egzemplarzy (modele → suma). Broń/aktywne/aury/liczność liczy
// AUTORYTATYWNIE backend z selekcji; tutaj wysyłamy selekcję + pasywne. Zapis
// automatyczny (debounce), aktualizacja kosztu w miejscu. Limit modeli miękki:
// nadwyżka ponad „dostępne" = proxy tego wariantu; nowe wpisy proxy dla broni
// nieposiadanej. Pasywne edytowalne (reuse renderPassiveEditor).
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
    let data = null;                 // odpowiedź endpointu
    const selections = new Map();    // collection_model_id (str) -> qty (może > available = proxy)
    let proxies = [];                // [{weapons: {wid: cnt}, qty}] — proxy wariantów nieposiadanych
    const passiveMap = new Map();    // slug -> 0/1

    let saveTimer = null;
    let saveController = null;
    let saveSeq = 0;
    let appliedSeq = 0;
    let pendingChanges = false;
    let savedSomething = false;

    const hideEls = () => Array.from(editor.querySelectorAll('[data-models-hide]'));
    const getActiveItem = () => root.querySelector('[data-roster-item].active');
    const weaponName = (wid) => ((data && data.weapon_names) || {})[String(wid)] || `Broń #${wid}`;
    const abilityName = (aid) => ((data && data.ability_names) || {})[String(aid)] || `Zdolność #${aid}`;
    const availableOf = (m) => Number(m.available != null ? m.available : m.count) || 0;

    // W trybie modeli chowamy CAŁY klasyczny formularz (jego puste, rozciągliwe
    // `flex-grow-1` sekcje zostawiałyby lukę pod statystykami w szerokim układzie).
    // Etykietę custom-name (w nagłówku, poza formularzem) robimy read-only — jej
    // edycja odpaliłaby autosave klasycznego edytora ze starym loadoutem.
    function setClassicHidden(on) {
      const classicForm = editor.querySelector('[data-roster-editor-form]');
      const customLabel = editor.querySelector('[data-roster-editor-custom-label]');
      if (classicForm) classicForm.classList.toggle('d-none', on);
      if (customLabel) customLabel.classList.toggle('roster-models-readonly', on);
    }

    function restoreClassicSections() {
      modelsMode = false;
      toggle.setAttribute('aria-pressed', 'false');
      toggle.classList.remove('active');
      toggle.textContent = 'Tryb modeli';
      panel.classList.add('d-none');
      panel.innerHTML = '';
      hideEls().forEach((el) => el.classList.remove('d-none'));
      setClassicHidden(false);
      data = null;
      selections.clear();
      proxies = [];
      passiveMap.clear();
      activeItem = null;
      rosterUnitId = '';
    }

    async function exitModelsMode() {
      if (saveTimer) {
        window.clearTimeout(saveTimer);
        saveTimer = null;
      }
      if (pendingChanges && aggregate().count > 0) {
        await doSave();
      }
      if (savedSomething && rosterUnitId) {
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
      setClassicHidden(true);
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
      // Wstępna selekcja: zapisana kompozycja lub derywacja suma→modele (z serwera).
      selections.clear();
      proxies = [];
      (Array.isArray(data.composed) ? data.composed : []).forEach((entry) => {
        if (!entry) return;
        const qty = Math.max(0, parseInt(entry.qty, 10) || 0);
        if (qty <= 0) return;
        if (entry.id != null) {
          selections.set(String(entry.id), (selections.get(String(entry.id)) || 0) + qty);
        } else {
          proxies.push({
            weapons: entry.weapons && typeof entry.weapons === 'object' ? entry.weapons : {},
            abilities: Array.isArray(entry.abilities) ? entry.abilities : [],
            qty,
          });
        }
      });
      passiveMap.clear();
      const passiveState = (data.passive_state && typeof data.passive_state === 'object') ? data.passive_state : {};
      Object.entries(passiveState).forEach(([slug, val]) => passiveMap.set(String(slug), val ? 1 : 0));
      renderPanel();
    }

    function aggregate() {
      let count = 0;
      const weapons = {};
      const add = (wid, n) => { weapons[wid] = (weapons[wid] || 0) + n; };
      ((data && data.models) || []).forEach((m) => {
        const qty = selections.get(String(m.id)) || 0;
        if (qty <= 0) return;
        count += qty;
        Object.entries(m.weapons || {}).forEach(([wid, c]) => add(wid, qty * (Number(c) || 0)));
      });
      proxies.forEach((p) => {
        const qty = Math.max(0, parseInt(p.qty, 10) || 0);
        if (qty <= 0) return;
        count += qty;
        Object.entries(p.weapons || {}).forEach(([wid, c]) => add(wid, qty * (Number(c) || 0)));
      });
      return { count, weapons };
    }

    function aggregateSummary(weapons) {
      const parts = Object.keys(weapons)
        .sort((a, b) => Number(a) - Number(b))
        .map((wid) => (weapons[wid] > 1 ? `${weaponName(wid)} ×${weapons[wid]}` : weaponName(wid)));
      return parts.length ? parts.join(', ') : '—';
    }

    function ownedRowsHtml() {
      const models = (data && data.models) || [];
      if (!models.length) {
        return '<div class="alert alert-info py-2 px-3 small mb-2">'
          + 'Brak modeli tego oddziału w kolekcji. Dodaj je w zakładce '
          + '<a href="/collections">Kolekcja</a> lub użyj proxy poniżej.</div>';
      }
      return models.map((m) => {
        const qty = selections.get(String(m.id)) || 0;
        const avail = availableOf(m);
        const overflow = Math.max(qty - avail, 0);
        const labelLine = m.label ? `<div class="small fw-semibold">${escapeHtml(m.label)}</div>` : '';
        const proxyTag = overflow > 0
          ? ` <span class="badge text-bg-warning" title="Sztuki ponad dostępne traktowane jako proxy">proxy +${overflow}</span>`
          : '';
        return `
          <div class="d-flex align-items-center gap-2 border rounded p-2 mb-2">
            <div class="flex-grow-1">
              ${labelLine}
              <div class="text-muted small">${escapeHtml(m.summary || '—')}${proxyTag}</div>
            </div>
            <div class="d-flex align-items-center gap-1 flex-shrink-0">
              <input type="number" class="form-control form-control-sm" style="width:4.5rem"
                     min="0" value="${qty}" data-models-qty="${m.id}" aria-label="Liczba modeli" />
              <span class="text-muted small">/ ${avail}</span>
            </div>
          </div>`;
      }).join('');
    }

    function proxyRowsHtml() {
      const opts = Object.keys((data && data.weapon_names) || {})
        .map((wid) => `<option value="${wid}">${escapeHtml(weaponName(wid))}</option>`)
        .join('');
      const list = proxies.map((p, i) => {
        const wsum = aggregateSummary(
          Object.fromEntries(Object.entries(p.weapons || {}).map(([w, c]) => [w, Number(c) || 0])),
        );
        const abilSum = (p.abilities || []).map(abilityName).join(', ');
        const detail = abilSum ? `${escapeHtml(wsum)} • ${escapeHtml(abilSum)}` : escapeHtml(wsum);
        return `
          <div class="d-flex align-items-center gap-2 border border-dashed rounded p-2 mb-2" data-proxy-row="${i}">
            <div class="flex-grow-1">
              <div class="small fw-semibold">Proxy <span class="badge text-bg-secondary">brak w kolekcji</span></div>
              <div class="text-muted small">${detail}</div>
            </div>
            <div class="d-flex align-items-center gap-1 flex-shrink-0">
              <input type="number" class="form-control form-control-sm" style="width:4.5rem"
                     min="0" value="${p.qty}" data-proxy-qty="${i}" aria-label="Liczba proxy" />
              <button type="button" class="btn btn-outline-danger btn-sm py-0 px-1" data-proxy-remove="${i}" title="Usuń">✕</button>
            </div>
          </div>`;
      }).join('');
      return `
        ${list}
        <div class="d-flex align-items-center gap-2 mt-1">
          <select class="form-select form-select-sm" style="max-width:14rem" data-proxy-weapon>
            <option value="">— bez broni —</option>
            ${opts}
          </select>
          <button type="button" class="btn btn-outline-secondary btn-sm" data-proxy-add>+ Dodaj proxy</button>
        </div>`;
    }

    function renderPanel() {
      const agg = aggregate();
      panel.innerHTML = `
        <div class="fw-semibold small text-uppercase text-muted mb-1">Zdolności pasywne</div>
        <div data-models-passives class="mb-2"></div>
        <div class="py-2 mb-2 border-top border-bottom">
          <div class="small">Skomponowany oddział:
            <strong data-models-preview-count>${agg.count}</strong> modeli
            <span class="text-muted ms-1" data-models-status></span>
          </div>
          <div class="text-muted small" data-models-preview-weapons>${escapeHtml(aggregateSummary(agg.weapons))}</div>
        </div>
        <div class="fw-semibold small text-uppercase text-muted mb-1">Modele</div>
        <div data-models-list>${ownedRowsHtml()}</div>
        <div class="fw-semibold small text-uppercase text-muted mt-2 mb-1">Proxy (uzupełnienie braków)</div>
        <div data-proxy-list>${proxyRowsHtml()}</div>`;
      renderPassives(agg.count);
    }

    function renderPassives(modelCount) {
      const container = panel.querySelector('[data-models-passives]');
      const rendering = window.SZOPRosterRendering || {};
      if (!container || typeof rendering.renderPassiveEditor !== 'function') {
        if (container) container.innerHTML = '<span class="text-muted small">—</span>';
        return;
      }
      rendering.renderPassiveEditor(
        container,
        (data && data.passive_items) || [],
        passiveMap,
        modelCount != null ? modelCount : aggregate().count,
        true,
        () => scheduleSave(),
      );
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
        if (unit.loadout_json) activeItem.setAttribute('data-loadout', unit.loadout_json);
        activeItem.setAttribute('data-unit-cost', String(cost));
      }
      const editorCost = root.querySelector('[data-roster-editor-cost]');
      if (editorCost && cost != null) editorCost.textContent = String(cost);
      const totalEl = root.querySelector('[data-roster-total]');
      if (totalEl && payload.total_cost != null) totalEl.textContent = String(payload.total_cost);
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

    function buildSelectionPayload() {
      const out = [];
      selections.forEach((qty, id) => {
        if (qty > 0) out.push({ id: Number(id), qty });
      });
      proxies.forEach((p) => {
        const qty = Math.max(0, parseInt(p.qty, 10) || 0);
        if (qty > 0) out.push({ id: null, weapons: p.weapons || {}, abilities: p.abilities || [], qty });
      });
      return out;
    }

    async function doSave() {
      if (!rosterUnitId) return;
      const agg = aggregate();
      if (agg.count <= 0) {
        setStatus('Wybierz co najmniej jeden model.');
        return;
      }
      // Broń/aktywne/aury liczy serwer z selekcji; wysyłamy tylko pasywne w loadout.
      const baseLoadout = (data && data.current_loadout && typeof data.current_loadout === 'object')
        ? { ...data.current_loadout }
        : {};
      baseLoadout.passive = Object.fromEntries(passiveMap);

      const form = new FormData();
      form.set('count', String(agg.count));
      form.set('loadout_json', JSON.stringify(baseLoadout));
      form.set('custom_name', activeItem ? (activeItem.getAttribute('data-unit-custom-name') || '') : '');
      form.set('composed_models_json', JSON.stringify(buildSelectionPayload()));

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
      if (modelsMode) exitModelsMode(); else enterModelsMode();
    });

    // Zmiany ilości (modele owned + proxy) — input.
    panel.addEventListener('input', (event) => {
      const ownedInput = event.target.closest('[data-models-qty]');
      if (ownedInput) {
        let qty = parseInt(ownedInput.value, 10);
        if (!Number.isFinite(qty) || qty < 0) { qty = 0; ownedInput.value = '0'; }
        selections.set(String(ownedInput.getAttribute('data-models-qty')), qty);
        refreshAfterChange();
        return;
      }
      const proxyInput = event.target.closest('[data-proxy-qty]');
      if (proxyInput) {
        const i = parseInt(proxyInput.getAttribute('data-proxy-qty'), 10);
        let qty = parseInt(proxyInput.value, 10);
        if (!Number.isFinite(qty) || qty < 0) { qty = 0; proxyInput.value = '0'; }
        if (proxies[i]) proxies[i].qty = qty;
        refreshAfterChange();
      }
    });

    // Dodawanie/usuwanie proxy — click.
    panel.addEventListener('click', (event) => {
      const addBtn = event.target.closest('[data-proxy-add]');
      if (addBtn) {
        const sel = panel.querySelector('[data-proxy-weapon]');
        const wid = sel ? sel.value : '';
        proxies.push({ weapons: wid ? { [String(wid)]: 1 } : {}, abilities: [], qty: 1 });
        renderPanel();
        scheduleSave();
        return;
      }
      const removeBtn = event.target.closest('[data-proxy-remove]');
      if (removeBtn) {
        const i = parseInt(removeBtn.getAttribute('data-proxy-remove'), 10);
        if (i >= 0 && i < proxies.length) {
          proxies.splice(i, 1);
          renderPanel();
          scheduleSave();
        }
      }
    });

    // Aktualizuje podgląd + licznik pasywnych (cost delta) bez pełnego re-renderu
    // listy (zachowuje focus w polach ilości), po czym planuje zapis.
    function refreshAfterChange() {
      updatePreview();
      scheduleSave();
    }

    // Przełączenie na INNY oddział w trybie modeli: dokończ zapis w tle i wróć do
    // klasyka bez przeładowania (roster_editor zhydratyzuje nowy wybór).
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
