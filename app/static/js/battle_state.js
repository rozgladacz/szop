(function () {
  "use strict";

  const STORAGE_PREFIX = "opr.battleState.";
  const MELEE_ASSAULT_TRAITS = new Set(["szturmowy", "szturmowa", "assault"]);
  const UNWIELDY_TRAITS = new Set(["nieporeczna", "unwieldy"]);

  // Status buttons config: key → {selector, btn color} — buttons live on the
  // group card, not on individual unit cards. A hero + parent share statuses.
  const STATUS_CONFIGS = [
    { key: "activated", selector: '[data-status-toggle="activated"]', color: "primary"   },
    { key: "entrenched",selector: '[data-status-toggle="entrenched"]',color: "success"   },
    { key: "pinned",    selector: '[data-status-toggle="pinned"]',    color: "warning"   },
    { key: "fatigued",  selector: '[data-status-toggle="fatigued"]',  color: "secondary" },
    { key: "defeated",  selector: "[data-defeated-toggle]",           color: "danger"    },
  ];

  function normalizeSlug(value) {
    if (value == null) return "";
    let text = String(value).trim().toLowerCase();
    if (text.normalize) {
      text = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    }
    return text;
  }

  function isAssaultTrait(trait) {
    return MELEE_ASSAULT_TRAITS.has(normalizeSlug(trait));
  }

  function isUnwieldyTrait(trait) {
    return UNWIELDY_TRAITS.has(normalizeSlug(trait));
  }

  function parseRangeInt(weapon) {
    if (typeof weapon.range_int === "number" && Number.isFinite(weapon.range_int)) {
      return weapon.range_int;
    }
    const raw = weapon.range;
    if (raw == null || raw === "") return 0;
    const text = String(raw).trim().toLowerCase();
    if (text === "melee" || text === "m") return 0;
    const num = parseInt(text.replace(/[^0-9-]/g, ""), 10);
    return Number.isFinite(num) ? num : 0;
  }

  function isMelee(weapon) {
    return parseRangeInt(weapon) === 0;
  }

  function traitsList(weapon) {
    if (Array.isArray(weapon.traits_list)) return weapon.traits_list;
    const raw = weapon.traits;
    if (!raw) return [];
    return String(raw).split(",").map((t) => t.trim()).filter(Boolean);
  }

  function traitBaseName(trait) {
    return trait.split("(")[0].trim();
  }

  function makeTooltipSpan(text, suffix) {
    const descs = window._abilityDescriptions;
    const desc = (descs && (descs[text] || descs[traitBaseName(text)])) || "";
    const s = document.createElement("span");
    s.textContent = text + (suffix || "");
    if (desc) {
      s.dataset.bsToggle = "tooltip";
      s.dataset.bsPlacement = "top";
      s.dataset.bsTitle = desc;
    }
    return s;
  }

  function effectiveIsPrimary(weapon, idx, us) {
    const key = weaponKey(weapon, idx);
    if (us.primaryOverrides && key in us.primaryOverrides) {
      return !!us.primaryOverrides[key];
    }
    return !!weapon.is_primary;
  }

  function storageKey(rosterId) {
    return STORAGE_PREFIX + String(rosterId);
  }

  function loadState(rosterId) {
    try {
      const raw = window.localStorage.getItem(storageKey(rosterId));
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function saveState(rosterId, state) {
    try {
      window.localStorage.setItem(storageKey(rosterId), JSON.stringify(state));
    } catch (e) { /* noop */ }
  }

  function clearState(rosterId) {
    try {
      window.localStorage.removeItem(storageKey(rosterId));
    } catch (e) { /* noop */ }
  }

  function weaponKey(weapon, idx) {
    if (weapon.weapon_id != null) return "w" + weapon.weapon_id;
    return "i" + idx;
  }

  function unitInitialState(card) {
    const initialModels = parseInt(card.dataset.initialModels || "0", 10) || 0;
    let weapons = [];
    try { weapons = JSON.parse(card.dataset.weaponsJson || "[]") || []; } catch (e) { weapons = []; }
    const weaponCounts = {};
    weapons.forEach((w, idx) => {
      const key = weaponKey(w, idx);
      const c = parseInt(w.count, 10);
      weaponCounts[key] = Number.isFinite(c) && c >= 0 ? c : 0;
    });
    const meleeFightingDefault = parseInt(card.dataset.meleeFightingDefault || "0", 10) || 0;
    return {
      activeModels: initialModels,
      // "Walczące modele" (rozmiar podstawki) — domyślnie limit1 z base_size
      // bazowego oddziału (server-rendered), spadek do initialModels gdyby
      // atrybut brakował/był 0 (nigdy nie chcemy 0 walczących modeli).
      meleeFighting: meleeFightingDefault > 0 ? meleeFightingDefault : initialModels,
      weapons: weaponCounts,
      primaryOverrides: {},
      struckAbilities: [],
      eliminated: {},
      withdrawn: {},
      eliminationMode: false,
    };
  }

  // Aktualna, wyklamrowana wartość "walczących modeli": [1, activeModels].
  // Wołane przy każdym renderze (self-healing, jak inne defensywne mutacje
  // stanu w renderUnit — patrz np. eliminated/withdrawn init w trybie „Modele").
  function clampMeleeFighting(unitState) {
    const max = Math.max(parseInt(unitState.activeModels, 10) || 0, 0);
    if (max <= 0) return 0;
    const raw = parseInt(unitState.meleeFighting, 10);
    const value = Number.isFinite(raw) ? raw : max;
    return Math.max(1, Math.min(value, max));
  }

  // Wybiera F "instancji" broni wręcz o najwyższym koszcie (F = walczące
  // modele), przycinając activeCount każdego wpisu aż do wyczerpania budżetu.
  // Koszt bierzemy z weapon.cost (server-rendered, SSOT — patrz
  // _loadout_weapon_details w rosters.py); remisy wg oryginalnej kolejności
  // (stabilny sort) dla determinizmu. Zwraca NOWE wpisy (nie mutuje `filtered`).
  function selectTopMeleeInstances(filtered, budget) {
    if (!Number.isFinite(budget) || budget <= 0) return [];
    const ranked = filtered.map((entry, order) => {
      const cost = parseFloat(entry.weapon.cost);
      return { entry, cost: Number.isFinite(cost) ? cost : 0, order };
    });
    ranked.sort((a, b) => (b.cost - a.cost) || (a.order - b.order));
    let remaining = budget;
    const result = [];
    ranked.forEach(({ entry }) => {
      if (remaining <= 0) return;
      const used = Math.min(entry.activeCount || 0, remaining);
      if (used <= 0) return;
      result.push(Object.assign({}, entry, { activeCount: used }));
      remaining -= used;
    });
    return result;
  }

  // 2c: grupy wariantów modeli (oddziały komponowane) z data-collection-groups.
  const _groupsCache = new WeakMap();
  function parseGroupsCached(card) {
    if (_groupsCache.has(card)) return _groupsCache.get(card);
    let groups = [];
    try { groups = JSON.parse(card.dataset.collectionGroups || "[]") || []; } catch (e) { groups = []; }
    if (!Array.isArray(groups)) groups = [];
    _groupsCache.set(card, groups);
    return groups;
  }

  // Licznik „− wartość / suma +" w jednym `.counter-group` (nowrap) — wspólny dla
  // trybu Modele i Wyposażenie, by nie rozbijał się przy wieloliniowej etykiecie.
  function counterGroup(dec, valueSpan, totalSpan, inc) {
    const g = document.createElement("span");
    g.className = "counter-group";
    [dec, valueSpan, totalSpan, inc].forEach((el) => g.appendChild(el));
    return g;
  }

  // Prosty przycisk licznika (−/+) o stałym wyglądzie — dla liczników bez
  // warunkowego stylu (np. "Walczące modele"). Tryb Modele/Wyposażenie mają
  // własne warianty (ikony/klasy zależne od trybu eliminacji lub primary
  // toggle) i celowo NIE korzystają z tego helpera.
  function counterButton(text, datasetKey, datasetValue) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-outline-secondary btn-sm counter-btn";
    btn.textContent = text;
    btn.dataset[datasetKey] = datasetValue;
    return btn;
  }

  // 2d: klucze etykiet do auto-przekreślenia po eliminacji modelu (#4). Dla każdej
  // zdolności liczymy ile modeli ją niosących padło (Σ po grupach) i przekreślamy
  // tyle jej wystąpień w górnej sekcji — znajdując je po `data-ability-id` (klucz
  // przekreślenia niesie sam span, brak duplikacji formatu `{label}[{idx}]`).
  function computeAutoStruck(card, us) {
    const auto = new Set();
    const groups = parseGroupsCached(card);
    if (!groups.length) return auto;
    const elim = (us && us.eliminated) || {};
    const dead = {};
    groups.forEach((g) => {
      const e = parseInt(elim[g.key], 10) || 0;
      if (e <= 0) return;
      (g.abilities || []).forEach((aid) => { dead[aid] = (dead[aid] || 0) + e; });
    });
    Object.keys(dead).forEach((aid) => {
      const spans = card.querySelectorAll('[data-ability-toggle][data-ability-id="' + aid + '"]');
      const n = Math.min(dead[aid], spans.length);
      for (let i = 0; i < n; i++) auto.add(spans[i].dataset.abilityToggle);
    });
    return auto;
  }

  // Znormalizowany licznik z mapy stanu (0..cap) — wspólny dla eliminated/withdrawn.
  function clampCount(store, key, cap) {
    return Math.max(0, Math.min(parseInt((store || {})[key], 10) || 0, cap));
  }

  // Wspólna mutacja licznika wariantu (grp) — tryb eliminacji vs wycofanie.
  // [−]: eliminuj (do count) lub wycofaj (do available); [+]: cofnij o 1. Zakłada
  // zainicjowane us.eliminated/us.withdrawn. Używane przez licznik globalny i per-wariant.
  function applyModelMinus(us, grp) {
    const count = parseInt(grp.count, 10) || 0;
    if (us.eliminationMode) {
      us.eliminated[grp.key] = Math.min((us.eliminated[grp.key] || 0) + 1, count);
    } else {
      const available = Math.max(count - (us.eliminated[grp.key] || 0), 0);
      us.withdrawn[grp.key] = Math.min((us.withdrawn[grp.key] || 0) + 1, available);
    }
  }
  function applyModelPlus(us, grp) {
    const store = us.eliminationMode ? us.eliminated : us.withdrawn;
    const cur = store[grp.key] || 0;
    if (cur > 0) store[grp.key] = cur - 1;
  }

  // Model liczebności (karty komponowane): dla każdej grupy wariantu
  //   dostępna (available) = count − eliminated  (eliminacja [x] — trwała),
  //   aktualna (current)    = available − withdrawn  (wycofanie [−] — odwracalne).
  // Broń liczona z AKTUALNYCH (na polu) modeli. Zwraca true dla kart komponowanych.
  function recomputeComposed(card, us) {
    const groups = parseGroupsCached(card);
    if (!groups.length) return false;
    if (!us.eliminated || typeof us.eliminated !== "object") us.eliminated = {};
    if (!us.withdrawn || typeof us.withdrawn !== "object") us.withdrawn = {};
    let totalCurrent = 0;
    const weapons = {};
    groups.forEach((g) => {
      const count = parseInt(g.count, 10) || 0;
      const elim = clampCount(us.eliminated, g.key, count);
      us.eliminated[g.key] = elim;
      const available = count - elim;
      const withdrawn = clampCount(us.withdrawn, g.key, available);
      us.withdrawn[g.key] = withdrawn;
      const current = available - withdrawn;
      totalCurrent += current;
      Object.keys(g.weapons || {}).forEach((wid) => {
        const key = "w" + wid;
        weapons[key] = (weapons[key] || 0) + current * (parseInt(g.weapons[wid], 10) || 0);
      });
    });
    us.activeModels = totalCurrent;
    us.weapons = weapons;
    return true;
  }

  // Σ dostępnych (żywych = count − eliminated) dla karty komponowanej; null dla klasycznej.
  function composedAvailable(card, us) {
    const groups = parseGroupsCached(card);
    if (!groups.length) return null;
    const elim = (us && us.eliminated) || {};
    let total = 0;
    groups.forEach((g) => {
      const count = parseInt(g.count, 10) || 0;
      total += count - clampCount(elim, g.key, count);
    });
    return total;
  }

  // Żywe modele (do progu zdrowia): dostępne dla komponowanych, activeModels dla klasycznych.
  function unitAliveModels(card, us) {
    const avail = composedAvailable(card, us);
    return avail != null ? avail : (us.activeModels || 0);
  }

  // Próg krytyczny grupy (parent + bohaterowie): (Σ żywe×wytrz − rany)*2 ≤ Σ początkowe×wytrz.
  function groupIsCritical(state, groupCard) {
    let initialHealth = 0;
    let aliveHealth = 0;
    groupCard.querySelectorAll("[data-battle-unit]").forEach((card) => {
      const us = state.units[card.dataset.rosterUnitId];
      if (!us) return;
      const t = parseInt(card.dataset.toughness || "1", 10) || 1;
      const initial = parseInt(card.dataset.initialModels || "0", 10) || 0;
      initialHealth += initial * t;
      aliveHealth += unitAliveModels(card, us) * t;
    });
    const gs = state.groups[groupCard.dataset.groupId];
    const wounds = (gs && parseInt(gs.woundsRemaining, 10)) || 0;
    return initialHealth > 0 && (aliveHealth - wounds) * 2 <= initialHealth;
  }

  function groupInitialState() {
    return {
      defeated: false,
      pinned: false,
      fatigued: false,
      entrenched: false,
      activated: false,
      woundsRemaining: 0,
      mode: "equipment",
    };
  }

  function getCards() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-battle-unit]"));
  }

  function getGroupCards() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-battle-group]"));
  }

  function filterWeaponsForMode(weapons, mode, unitState) {
    return weapons
      .map((w, idx) => ({ weapon: w, idx, key: weaponKey(w, idx) }))
      .filter((entry) => {
        const active = unitState.weapons[entry.key] || 0;
        if (active <= 0) return false;
        const w = entry.weapon;
        const range = parseRangeInt(w);
        const traits = traitsList(w);
        if (mode === "equipment") return true;
        if (mode === "melee") {
          if (range === 0) return true;
          return traits.some(isAssaultTrait);
        }
        if (mode.startsWith("ranged:")) {
          const r = parseInt(mode.slice(7), 10);
          if (!Number.isFinite(r)) return false;
          if (range < r) return false;
          if (r === 12 && traits.some(isUnwieldyTrait)) return false;
          return true;
        }
        return true;
      });
  }

  function groupAttacks(filtered) {
    const groups = new Map();
    filtered.forEach((entry) => {
      const w = entry.weapon;
      const activeCount = entry.activeCount || 0;
      const attacksPer = parseFloat(w.attacks);
      const a = Number.isFinite(attacksPer) ? attacksPer : 1;
      const traits = traitsList(w).filter((t) => !isAssaultTrait(t));
      const ap = w.ap == null ? 0 : parseInt(w.ap, 10) || 0;
      const traitKey = traits.map(normalizeSlug).sort().join("|");
      const key = ap + "|" + traitKey;
      const total = a * activeCount;
      if (groups.has(key)) {
        groups.get(key).totalAttacks += total;
      } else {
        groups.set(key, { ap, traits, totalAttacks: total });
      }
    });
    return Array.from(groups.values()).sort((a, b) => {
      if (b.totalAttacks !== a.totalAttacks) return b.totalAttacks - a.totalAttacks;
      return a.ap - b.ap;
    });
  }

  function formatAttacks(value) {
    if (Math.abs(value - Math.round(value)) < 0.01) return String(Math.round(value));
    return value.toFixed(1);
  }

  // "Walczące modele" — licznik (−/wartość/+) jako pierwsza pozycja
  // podsumowania trybu Wręcz. Nie modyfikuje unitState — wołający ustawia
  // unitState.meleeFighting PRZED wywołaniem (renderUnit) i obsługuje mutację
  // w event handlerach (data-melee-fighting-decrement/increment).
  function renderMeleeFightingCounter(unitState, fighting) {
    const row = document.createElement("div");
    row.className = "attack-summary-row";

    const dec = counterButton("−", "meleeFightingDecrement", "1");

    const valueSpan = document.createElement("span");
    valueSpan.className = "counter-value";
    valueSpan.textContent = fighting;

    const totalSpan = document.createElement("span");
    totalSpan.className = "text-muted small";
    totalSpan.textContent = "/ " + (unitState.activeModels || 0);

    const inc = counterButton("+", "meleeFightingIncrement", "1");

    const label = document.createElement("span");
    label.className = "small text-muted ms-1";
    label.textContent = "Walczące modele";

    row.appendChild(counterGroup(dec, valueSpan, totalSpan, inc));
    row.appendChild(label);
    return row;
  }

  function disposeTooltipsIn(container) {
    if (typeof bootstrap === "undefined" || !bootstrap.Tooltip) return;
    container.querySelectorAll("[data-bs-toggle='tooltip']").forEach(function (el) {
      const inst = bootstrap.Tooltip.getInstance(el);
      if (inst) inst.dispose();
    });
  }

  function computeGroupWoundMax(state, groupCard) {
    let max = 0;
    groupCard.querySelectorAll("[data-battle-unit]").forEach((card) => {
      const us = state.units[card.dataset.rosterUnitId];
      if (!us) return;
      if ((us.activeModels || 0) <= 0) return;
      const t = parseInt(card.dataset.toughness || "1", 10) || 1;
      if (t > max) max = t;
    });
    return max;
  }

  function renderUnit(card, unitState, groupState) {
    const weapons = parseWeaponsCached(card);

    // Model counter (per-unit). Heroes always show counter even at count=1.
    // Karty komponowane: aktualna / dostępna / początkowa; klasyczne: aktualna / początkowa.
    const modelsValue = card.querySelector("[data-models-value]");
    if (modelsValue) modelsValue.textContent = unitState.activeModels;
    const availWrap = card.querySelector("[data-models-available-wrap]");
    const availVal = card.querySelector("[data-models-available]");
    const available = composedAvailable(card, unitState);
    const initialModels = parseInt(card.dataset.initialModels || "0", 10) || 0;
    // Środkowa wartość (dostępna) tylko gdy są modele wyeliminowane (available < initial).
    const showAvail = available != null && available < initialModels;
    if (availWrap) availWrap.classList.toggle("d-none", !showAvail);
    if (availVal && showAvail) availVal.textContent = available;

    // Mode toolbar active state (shared mode across the group)
    const toolbar = card.querySelector("[data-mode-toolbar]");
    if (toolbar) {
      toolbar.querySelectorAll("[data-mode]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.mode === groupState.mode);
      });
    }

    const list = card.querySelector("[data-weapon-list]");
    const summary = card.querySelector("[data-attack-summary]");
    if (!list || !summary) return;

    disposeTooltipsIn(list);
    disposeTooltipsIn(summary);
    list.innerHTML = "";
    summary.innerHTML = "";

    // Tryb „Modele" — grupy wariantów (karty komponowane). Wiersz: [−] licznik [+]
    // + nazwa (pogrubiona) i wyposażenie. Checkbox „Eliminacja" (na dole) przełącza
    // [−]/[+] między wycofaniem a TRWAŁĄ eliminacją (chroni przed misclick).
    // Licznik: aktualna/dostępna/początkowa gdy są eliminowane, inaczej aktualna/początkowa.
    const modelGroups = parseGroupsCached(card);
    if (groupState.mode === "models" && modelGroups.length) {
      summary.classList.add("d-none");
      if (!unitState.eliminated || typeof unitState.eliminated !== "object") unitState.eliminated = {};
      if (!unitState.withdrawn || typeof unitState.withdrawn !== "object") unitState.withdrawn = {};
      const elimMode = !!unitState.eliminationMode;
      modelGroups.forEach((g) => {
        const count = parseInt(g.count, 10) || 0;
        const elim = clampCount(unitState.eliminated, g.key, count);
        const available = count - elim;
        const withdrawn = clampCount(unitState.withdrawn, g.key, available);
        const current = available - withdrawn;
        const row = document.createElement("div");
        row.className = "weapon-line" + (elim > 0 ? " model-group-depleted" : "");

        const wrap = document.createElement("div");
        wrap.className = "weapon-label-wrap d-flex align-items-center gap-1";

        const mkBtn = (cls, txt, title, dataKey) => {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "btn " + cls + " btn-sm counter-btn";
          b.textContent = txt;
          b.title = title;
          b.dataset[dataKey] = g.key;
          return b;
        };
        const dec = mkBtn(elimMode ? "btn-outline-danger" : "btn-outline-secondary",
          elimMode ? "✕" : "−", elimMode ? "Wyeliminuj (trwale)" : "Wycofaj", "modelMinus");
        const inc = mkBtn("btn-outline-secondary",
          elimMode ? "↺" : "+", elimMode ? "Cofnij eliminację" : "Przywróć", "modelPlus");

        const valueSpan = document.createElement("span");
        valueSpan.className = "counter-value";
        valueSpan.textContent = current;

        const totalSpan = document.createElement("span");
        totalSpan.className = "text-muted small";
        totalSpan.textContent = elim > 0 ? ("/ " + available + " / " + count) : ("/ " + count);

        const counter = counterGroup(dec, valueSpan, totalSpan, inc);

        const label = document.createElement("span");
        label.className = "weapon-label ms-2";
        const nameEl = document.createElement("div");
        const strong = document.createElement("strong");
        strong.textContent = g.name || "—";
        nameEl.appendChild(strong);
        const eq = document.createElement("div");
        eq.className = "small fw-normal";
        eq.textContent = g.summary || "—";
        label.appendChild(nameEl);
        label.appendChild(eq);

        wrap.appendChild(counter);
        wrap.appendChild(label);
        row.appendChild(wrap);
        list.appendChild(row);
      });

      // Tryb eliminacji (checkbox): gdy zaznaczony [−] eliminuje trwale, [+] cofa.
      const modeRow = document.createElement("div");
      modeRow.className = "form-check form-switch small mt-1";
      const cb = document.createElement("input");
      cb.className = "form-check-input";
      cb.type = "checkbox";
      cb.checked = elimMode;
      cb.id = "elim-mode-" + card.dataset.rosterUnitId;
      cb.dataset.elimModeToggle = "1";
      const cbLabel = document.createElement("label");
      cbLabel.className = "form-check-label";
      cbLabel.setAttribute("for", cb.id);
      cbLabel.textContent = "Eliminacja";
      modeRow.appendChild(cb);
      modeRow.appendChild(cbLabel);
      list.appendChild(modeRow);
      return;
    }

    const initialWeapons = weapons.map((w, idx) => ({
      weapon: w,
      idx,
      key: weaponKey(w, idx),
      initialCount: parseInt(w.count, 10) || 0,
      activeCount: unitState.weapons[weaponKey(w, idx)] || 0,
    }));

    if (groupState.mode === "equipment") {
      summary.classList.add("d-none");
      initialWeapons.forEach((entry) => {
        const w = entry.weapon;
        const line = document.createElement("div");
        line.className = "weapon-line";
        line.dataset.battleWeapon = entry.key;
        line.dataset.active = entry.activeCount > 0 ? "1" : "0";

        const labelWrap = document.createElement("div");
        labelWrap.className = "weapon-label-wrap d-flex align-items-center gap-1";

        const dec = document.createElement("button");
        dec.type = "button";
        dec.className = "btn btn-outline-secondary btn-sm counter-btn";
        dec.textContent = "−";
        dec.dataset.weaponDecrement = entry.key;

        const valueSpan = document.createElement("span");
        valueSpan.className = "counter-value";
        valueSpan.textContent = entry.activeCount;

        const initialSpan = document.createElement("span");
        initialSpan.className = "text-muted small";
        initialSpan.textContent = "/ " + entry.initialCount;

        const inc = document.createElement("button");
        inc.type = "button";
        inc.className = "btn btn-outline-secondary btn-sm counter-btn";
        inc.textContent = "+";
        inc.dataset.weaponIncrement = entry.key;

        const labelText = document.createElement("span");
        labelText.className = "weapon-label ms-2";
        labelText.style.cursor = "pointer";
        const isPrimary = effectiveIsPrimary(w, entry.idx, unitState);
        labelText.textContent = (isPrimary ? "⚑ " : "") + (w.name || "Broń");
        labelText.dataset.weaponPrimaryToggle = entry.key;
        const rangeDisp = parseRangeInt(w) || "wręcz";
        const trDisp = w.traits || "-";
        labelText.dataset.bsToggle = "tooltip";
        labelText.dataset.bsPlacement = "top";
        labelText.dataset.bsTitle = "Ataki: " + (w.attacks ?? "-") + " | Zasięg: " + rangeDisp + " | AP: " + (w.ap ?? "-") + " | Cechy: " + trDisp;

        // Licznik trzymamy razem (nowrap) — nie rozbija się, gdy etykieta wieloliniowa.
        labelWrap.appendChild(counterGroup(dec, valueSpan, initialSpan, inc));
        labelWrap.appendChild(labelText);

        const stats = document.createElement("span");
        stats.className = "weapon-stats";
        const range = parseRangeInt(w);
        const attacks = w.attacks == null ? "-" : w.attacks;
        const ap = w.ap == null ? "-" : w.ap;
        stats.appendChild(document.createTextNode(
          "Ataki: " + attacks + " | Zasięg: " + (range || "wręcz") + " | AP: " + ap + " | Cechy: "
        ));
        const traits = traitsList(w);
        if (traits.length === 0) {
          stats.appendChild(document.createTextNode("-"));
        } else {
          traits.forEach(function (trait, i) {
            stats.appendChild(makeTooltipSpan(trait, i < traits.length - 1 ? ", " : ""));
          });
        }

        line.appendChild(labelWrap);
        line.appendChild(stats);
        list.appendChild(line);
      });
      return;
    }

    // Attack mode — grouped summary
    const filtered = filterWeaponsForMode(weapons, groupState.mode, unitState);
    filtered.forEach((entry) => { entry.activeCount = unitState.weapons[entry.key] || 0; });

    summary.classList.remove("d-none");

    // "Walczące modele" (tylko widok Wręcz, pomijane dla pojedynczego modelu)
    // — pierwsza pozycja widoku; ogranicza podsumowanie do F najdroższych
    // instancji broni wręcz (F = liczba walczących modeli).
    let attackFiltered = filtered;
    if (groupState.mode === "melee" && (unitState.activeModels || 0) > 1) {
      const fighting = clampMeleeFighting(unitState);
      unitState.meleeFighting = fighting;
      summary.appendChild(renderMeleeFightingCounter(unitState, fighting));
      attackFiltered = selectTopMeleeInstances(filtered, fighting);
    }

    if (attackFiltered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "text-muted small";
      empty.textContent = "Brak dostępnych ataków w tym trybie.";
      summary.appendChild(empty);
      return;
    }
    const groups = groupAttacks(attackFiltered);
    groups.forEach((g) => {
      const row = document.createElement("div");
      row.className = "attack-summary-row";
      const total = document.createElement("span");
      total.className = "attack-summary-total";
      total.textContent = formatAttacks(g.totalAttacks) + " ataków";
      const meta = document.createElement("span");
      meta.className = "small";
      meta.appendChild(document.createTextNode("AP" + g.ap + " | "));
      if (g.traits.length === 0) {
        meta.appendChild(document.createTextNode("bez cech"));
      } else {
        g.traits.forEach(function (trait, i) {
          meta.appendChild(makeTooltipSpan(trait, i < g.traits.length - 1 ? ", " : ""));
        });
      }
      row.appendChild(total);
      row.appendChild(meta);
      summary.appendChild(row);
    });
  }

  function renderGroup(state, groupCard) {
    const gid = groupCard.dataset.groupId;
    const gs = state.groups[gid];
    if (!gs) return;

    // Wound counter (shared per group)
    const woundsValue = groupCard.querySelector("[data-group-wounds-value]");
    const woundsMax = groupCard.querySelector("[data-group-wounds-max]");
    const max = computeGroupWoundMax(state, groupCard);
    if (woundsValue) woundsValue.textContent = gs.woundsRemaining;
    if (woundsMax) woundsMax.textContent = max;

    // Status buttons (on the group card)
    STATUS_CONFIGS.forEach(({ key, selector, color }) => {
      const btn = groupCard.querySelector(selector);
      if (!btn) return;
      const isActive = key === "defeated" ? !!gs.defeated : !!gs[key];
      if (isActive) {
        btn.classList.remove("btn-outline-" + color);
        btn.classList.add("btn-" + color, "active");
      } else {
        btn.classList.remove("btn-" + color, "active");
        btn.classList.add("btn-outline-" + color);
      }
    });

    groupCard.classList.toggle("is-defeated", !!gs.defeated);
  }

  const _weaponsCache = new WeakMap();
  function parseWeaponsCached(card) {
    if (_weaponsCache.has(card)) return _weaponsCache.get(card);
    let weapons = [];
    try { weapons = JSON.parse(card.dataset.weaponsJson || "[]") || []; } catch (e) { weapons = []; }
    _weaponsCache.set(card, weapons);
    return weapons;
  }

  function repositionSpellsTile(state) {
    const tile = document.querySelector("[data-battle-spells-tile]");
    if (!tile) return;
    const section = document.querySelector("[data-battle-section]");
    if (!section) return;

    let mageGroupIds;
    try { mageGroupIds = JSON.parse(tile.dataset.mageGroupIds || "[]"); } catch (e) { mageGroupIds = []; }
    if (!mageGroupIds.length) { section.appendChild(tile); return; }

    const anyMageAlive = mageGroupIds.some(function (gid) {
      return !state.groups?.[String(gid)]?.defeated;
    });

    const wrappers = Array.prototype.slice.call(
      section.querySelectorAll("[data-battle-card-wrapper]")
    );

    if (anyMageAlive) {
      // Place after the last non-defeated wrapper (before first defeated)
      var lastAlive = null;
      for (var i = wrappers.length - 1; i >= 0; i--) {
        var gc = wrappers[i].querySelector("[data-battle-group]");
        var gid = gc && gc.dataset.groupId;
        if (gid && !state.groups?.[gid]?.defeated) {
          lastAlive = wrappers[i];
          break;
        }
      }
      if (lastAlive) {
        lastAlive.after(tile);
      } else {
        section.appendChild(tile);
      }
    } else {
      // All mages defeated: place at the very end
      section.appendChild(tile);
    }
  }

  function reorderDefeated(state) {
    const sections = document.querySelectorAll("[data-battle-section]");
    sections.forEach((section) => {
      const wrappers = Array.prototype.slice.call(section.querySelectorAll("[data-battle-card-wrapper]"));
      wrappers.sort((a, b) => {
        const groupCard = a.querySelector("[data-battle-group]");
        const groupCardB = b.querySelector("[data-battle-group]");
        const gidA = groupCard?.dataset.groupId;
        const gidB = groupCardB?.dataset.groupId;
        const da = state.groups?.[gidA]?.defeated ? 1 : 0;
        const db = state.groups?.[gidB]?.defeated ? 1 : 0;
        if (da !== db) return da - db;
        return parseInt(a.dataset.originalPosition || 0) - parseInt(b.dataset.originalPosition || 0);
      });
      wrappers.forEach((w) => section.appendChild(w));
    });
    repositionSpellsTile(state);
  }

  function updateSummaryBadge(state, groupCards) {
    let active = 0;
    groupCards.forEach((card) => {
      if (!state.groups?.[card.dataset.groupId]?.defeated) active += 1;
    });
    const a = document.querySelector("[data-active-units]");
    const t = document.querySelector("[data-total-units]");
    if (a) a.textContent = active;
    if (t) t.textContent = groupCards.length;
  }

  function updateRoundDisplay(state) {
    const el = document.querySelector("[data-round-number]");
    if (el) el.textContent = state.round || 1;
  }

  function applyAbilityStates(card, us) {
    // Suma ręcznych przekreśleń i auto-przekreśleń wynikających z eliminacji.
    const struck = new Set(us.struckAbilities || []);
    computeAutoStruck(card, us).forEach((k) => struck.add(k));
    card.querySelectorAll("[data-ability-toggle]").forEach(function (span) {
      span.classList.toggle("is-struck", struck.has(span.dataset.abilityToggle));
    });
  }

  function initTooltips(root) {
    if (typeof bootstrap === "undefined" || !bootstrap.Tooltip) return;
    (root || document).querySelectorAll("[data-bs-toggle='tooltip']").forEach(function (el) {
      if (!bootstrap.Tooltip.getInstance(el)) {
        new bootstrap.Tooltip(el, { trigger: "hover" });
      }
    });
  }

  function migrateLegacyState(legacy, cards) {
    // Old format had every per-unit dict carrying defeated/pinned/...,
    // woundsRemaining, mode. The new format splits those into state.groups.
    // For each card we know its (unit_id, group_id); copy legacy unit flags
    // to the group bucket (OR-merging when multiple members had flags set).
    const migrated = { units: {}, groups: {}, round: legacy.round || 1 };
    const legacyUnits = legacy.units || {};
    cards.forEach((card) => {
      const uid = card.dataset.rosterUnitId;
      const gid = card.dataset.groupId || uid;
      const stored = legacyUnits[uid] || null;
      const init = unitInitialState(card);
      if (stored) {
        migrated.units[uid] = {
          activeModels: typeof stored.activeModels === "number" ? stored.activeModels : init.activeModels,
          meleeFighting: typeof stored.meleeFighting === "number" ? stored.meleeFighting : init.meleeFighting,
          weapons: {},
          primaryOverrides: (stored.primaryOverrides && typeof stored.primaryOverrides === "object") ? stored.primaryOverrides : {},
          struckAbilities: Array.isArray(stored.struckAbilities) ? stored.struckAbilities : [],
          eliminated: (stored.eliminated && typeof stored.eliminated === "object") ? stored.eliminated : {},
          withdrawn: (stored.withdrawn && typeof stored.withdrawn === "object") ? stored.withdrawn : {},
          eliminationMode: !!stored.eliminationMode,
        };
        Object.keys(init.weapons).forEach((k) => {
          migrated.units[uid].weapons[k] = typeof stored.weapons?.[k] === "number" ? stored.weapons[k] : init.weapons[k];
        });
      } else {
        migrated.units[uid] = init;
      }
      if (!migrated.groups[gid]) migrated.groups[gid] = groupInitialState();
      const gs = migrated.groups[gid];
      if (stored) {
        if (stored.defeated) gs.defeated = true;
        if (stored.pinned) gs.pinned = true;
        if (stored.fatigued) gs.fatigued = true;
        if (stored.entrenched) gs.entrenched = true;
        if (stored.activated) gs.activated = true;
        if (typeof stored.woundsRemaining === "number" && stored.woundsRemaining > gs.woundsRemaining) {
          gs.woundsRemaining = stored.woundsRemaining;
        }
        if (typeof stored.mode === "string" && stored.mode && gs.mode === "equipment") {
          gs.mode = stored.mode;
        }
      }
    });
    return migrated;
  }

  function init() {
    const root = document.querySelector("[data-battle-root]");
    if (!root) return;
    const rosterId = root.dataset.rosterId;
    const cards = getCards();
    const groupCards = getGroupCards();

    let state = loadState(rosterId);
    if (!state || !state.groups) {
      // Legacy (per-unit) or no stored state — build/migrate.
      state = migrateLegacyState(state || {}, cards);
    } else {
      // Ensure every current unit / group has an entry.
      if (!state.units) state.units = {};
      if (!state.groups) state.groups = {};
      if (!state.round) state.round = 1;
      cards.forEach((card) => {
        const uid = card.dataset.rosterUnitId;
        const gid = card.dataset.groupId || uid;
        if (!state.units[uid]) state.units[uid] = unitInitialState(card);
        if (!state.groups[gid]) state.groups[gid] = groupInitialState();
      });
    }

    // Backfill "walczące modele" for state saved before this field existed
    // (existing unit entries, not just newly-added ones handled above).
    cards.forEach((card) => {
      const uid = card.dataset.rosterUnitId;
      const us = state.units[uid];
      if (us && typeof us.meleeFighting !== "number") {
        us.meleeFighting = unitInitialState(card).meleeFighting;
      }
    });

    // Guard: ensure every group card has a valid state entry regardless of
    // migration path (handles stale localStorage with mismatched group IDs).
    groupCards.forEach((g) => {
      const gid = g.dataset.groupId;
      if (gid && (!state.groups[gid] || typeof state.groups[gid] !== "object")) {
        state.groups[gid] = groupInitialState();
      }
    });

    // 2c: dla kart komponowanych przelicz weapons/activeModels z zapisanego
    // `eliminated` (spójność po reloadzie / zmianie kompozycji).
    cards.forEach((card) => {
      const us = state.units[card.dataset.rosterUnitId];
      if (us) recomputeComposed(card, us);
    });

    saveState(rosterId, state);

    function rerenderAll() {
      cards.forEach((card) => {
        const us = state.units[card.dataset.rosterUnitId];
        const gid = card.dataset.groupId || card.dataset.rosterUnitId;
        const gs = state.groups[gid];
        if (!us || !gs) return;
        renderUnit(card, us, gs);
        applyAbilityStates(card, us);
      });
      // Próg krytyczny (≤50% zdrowia grupy): etykiety Rany:/Modele: na czerwono.
      // Licz raz per grupa (Rany: od razu), potem etykiety Modele: per oddział.
      const criticalByGid = {};
      groupCards.forEach((g) => {
        const crit = groupIsCritical(state, g);
        criticalByGid[g.dataset.groupId] = crit;
        renderGroup(state, g);
        const woundsLabel = g.querySelector("[data-wounds-label]");
        if (woundsLabel) woundsLabel.classList.toggle("label-critical", crit);
      });
      cards.forEach((card) => {
        const label = card.querySelector("[data-models-label]");
        if (label) label.classList.toggle("label-critical", !!criticalByGid[card.dataset.groupId || card.dataset.rosterUnitId]);
      });
      reorderDefeated(state);
      updateSummaryBadge(state, groupCards);
      updateRoundDisplay(state);
    }

    function commit() {
      saveState(rosterId, state);
      rerenderAll();
      initTooltips();
    }

    function clamp(value, min, max) {
      if (value < min) return min;
      if (max != null && value > max) return max;
      return value;
    }

    // Per-unit event handlers (model counter, weapon counters, ability toggles,
    // mode toolbar — note: mode click affects the entire group).
    cards.forEach((card) => {
      const uid = card.dataset.rosterUnitId;
      const gid = card.dataset.groupId || uid;
      const initialModels = parseInt(card.dataset.initialModels || "0", 10) || 0;
      const weapons = parseWeaponsCached(card);
      const initialWeaponCounts = {};
      weapons.forEach((w, idx) => {
        const k = weaponKey(w, idx);
        const c = parseInt(w.count, 10);
        initialWeaponCounts[k] = Number.isFinite(c) && c >= 0 ? c : 0;
      });

      card.addEventListener("click", function (ev) {
        const us = state.units[uid];
        const gs = state.groups[gid];
        if (!us || !gs) return;

        // Ability toggle (span click)
        const abilitySpan = ev.target.closest("[data-ability-toggle]");
        if (abilitySpan) {
          const label = abilitySpan.dataset.abilityToggle;
          if (!Array.isArray(us.struckAbilities)) us.struckAbilities = [];
          const idx = us.struckAbilities.indexOf(label);
          if (idx >= 0) us.struckAbilities.splice(idx, 1);
          else us.struckAbilities.push(label);
          commit();
          return;
        }

        // Primary weapon toggle (weapon name click)
        const primaryToggleEl = ev.target.closest("[data-weapon-primary-toggle]");
        if (primaryToggleEl) {
          const key = primaryToggleEl.dataset.weaponPrimaryToggle;
          const wIdx = weapons.findIndex((w, i) => weaponKey(w, i) === key);
          if (wIdx < 0) return;
          const w = weapons[wIdx];
          const thisMelee = isMelee(w);
          if (!us.primaryOverrides) us.primaryOverrides = {};
          if (effectiveIsPrimary(w, wIdx, us)) {
            us.primaryOverrides[key] = false;
          } else {
            weapons.forEach((ow, oi) => {
              const ok = weaponKey(ow, oi);
              if (ok !== key && isMelee(ow) === thisMelee && effectiveIsPrimary(ow, oi, us)) {
                us.primaryOverrides[ok] = false;
              }
            });
            us.primaryOverrides[key] = true;
          }
          commit();
          return;
        }

        // Przełącznik trybu eliminacji (checkbox, nie button) — przed guardem button.
        const elimToggle = ev.target.closest("[data-elim-mode-toggle]");
        if (elimToggle) {
          us.eliminationMode = !!elimToggle.checked;
          commit();
          return;
        }

        const target = ev.target.closest("button");
        if (!target) return;

        // Komponowany licznik ±: w trybie eliminacji [−] eliminuje / [+] cofa
        // eliminację; inaczej [−] wycofuje / [+] przywraca. Najtańsza grupa.
        const ensureModelState = () => {
          if (!us.eliminated || typeof us.eliminated !== "object") us.eliminated = {};
          if (!us.withdrawn || typeof us.withdrawn !== "object") us.withdrawn = {};
        };
        if (target.matches("[data-models-decrement]")) {
          const composedGroups = parseGroupsCached(card);
          if (composedGroups.length) {
            ensureModelState();
            // Najtańsza grupa z „miejscem" na operację (available>0 dla eliminacji,
            // current>0 dla wycofania); mutacja przez wspólny applyModelMinus.
            const grp = composedGroups.find((x) => {
              const avail = (parseInt(x.count, 10) || 0) - (us.eliminated[x.key] || 0);
              return us.eliminationMode ? avail > 0 : avail - (us.withdrawn[x.key] || 0) > 0;
            });
            if (grp) { applyModelMinus(us, grp); recomputeComposed(card, us); commit(); }
            return;
          }
          const newCount = clamp(us.activeModels - 1, 0, initialModels);
          if (initialModels > 0) {
            Object.keys(initialWeaponCounts).forEach((k) => {
              us.weapons[k] = Math.round(initialWeaponCounts[k] * newCount / initialModels);
            });
          }
          us.activeModels = newCount;
          commit();
          return;
        }

        if (target.matches("[data-models-increment]")) {
          const composedGroups = parseGroupsCached(card);
          if (composedGroups.length) {
            ensureModelState();
            const store = us.eliminationMode ? us.eliminated : us.withdrawn;
            const grp = composedGroups.find((x) => (store[x.key] || 0) > 0);
            if (grp) { applyModelPlus(us, grp); recomputeComposed(card, us); commit(); }
            return;
          }
          const newCount = clamp(us.activeModels + 1, 0, initialModels);
          if (initialModels > 0) {
            Object.keys(initialWeaponCounts).forEach((k) => {
              us.weapons[k] = Math.round(initialWeaponCounts[k] * newCount / initialModels);
            });
          }
          us.activeModels = newCount;
          commit();
          return;
        }

        // "Walczące modele" (widok Wręcz): [−]/[+] w granicach [1, activeModels].
        if (target.matches("[data-melee-fighting-decrement]")) {
          us.meleeFighting = Math.max(1, clampMeleeFighting(us) - 1);
          commit();
          return;
        }
        if (target.matches("[data-melee-fighting-increment]")) {
          const max = Math.max(us.activeModels || 0, 0);
          us.meleeFighting = Math.min(max, clampMeleeFighting(us) + 1);
          commit();
          return;
        }

        // Tryb Modele — per wariant: [−] (eliminuj/wycofaj), [+] (cofnij/przywróć),
        // zależnie od trybu eliminacji (us.eliminationMode).
        const minusKey = target.dataset.modelMinus;
        if (minusKey) {
          ensureModelState();
          const grp = parseGroupsCached(card).find((x) => x.key === minusKey);
          if (grp) { applyModelMinus(us, grp); recomputeComposed(card, us); commit(); }
          return;
        }
        const plusKey = target.dataset.modelPlus;
        if (plusKey) {
          ensureModelState();
          const grp = parseGroupsCached(card).find((x) => x.key === plusKey);
          if (grp) { applyModelPlus(us, grp); recomputeComposed(card, us); commit(); }
          return;
        }

        const decKey = target.dataset.weaponDecrement;
        if (decKey) {
          const cur = us.weapons[decKey] || 0;
          if (cur <= 0) return;
          us.weapons[decKey] = cur - 1;
          const decIdx = weapons.findIndex((w, i) => weaponKey(w, i) === decKey);
          const thisWeaponDec = weapons[decIdx];
          if (thisWeaponDec && !effectiveIsPrimary(thisWeaponDec, decIdx, us)) {
            const decIsMelee = isMelee(thisWeaponDec);
            weapons.some((w, idx) => {
              if (!effectiveIsPrimary(w, idx, us)) return false;
              if (isMelee(w) !== decIsMelee) return false;
              const pk = weaponKey(w, idx);
              us.weapons[pk] = (us.weapons[pk] || 0) + 1;
              return true;
            });
          }
          commit();
          return;
        }

        const incKey = target.dataset.weaponIncrement;
        if (incKey) {
          const cap = initialWeaponCounts[incKey] || 0;
          const cur = us.weapons[incKey] || 0;
          if (cur >= cap) return;
          us.weapons[incKey] = cur + 1;
          const incIdx = weapons.findIndex((w, i) => weaponKey(w, i) === incKey);
          const thisWeaponInc = weapons[incIdx];
          if (thisWeaponInc && !effectiveIsPrimary(thisWeaponInc, incIdx, us)) {
            const incIsMelee = isMelee(thisWeaponInc);
            weapons.some((w, idx) => {
              if (!effectiveIsPrimary(w, idx, us)) return false;
              if (isMelee(w) !== incIsMelee) return false;
              const pk = weaponKey(w, idx);
              const pcur = us.weapons[pk] || 0;
              if (pcur > 0) { us.weapons[pk] = pcur - 1; return true; }
              return false;
            });
          }
          commit();
          return;
        }

        // Mode toolbar click: shared with the entire group. Update group state
        // so all member tables filter to the same mode (Wręcz on hero ⇒ Wręcz
        // on the parent and vice versa).
        const mode = target.dataset.mode;
        if (mode) {
          gs.mode = mode;
          commit();
          return;
        }
      });
    });

    // Per-group event handlers (status buttons, defeated toggle, shared wound counter)
    groupCards.forEach((groupCard) => {
      const gid = groupCard.dataset.groupId;
      groupCard.addEventListener("click", function (ev) {
        const gs = state.groups[gid];
        if (!gs) return;
        const target = ev.target.closest("button");
        if (!target) return;

        if (target.matches("[data-group-wounds-decrement]")) {
          // Allow values below zero? Clamp at 0. Max is informational only —
          // we let users exceed it (e.g. 9/6 from Zemsta).
          gs.woundsRemaining = Math.max(0, (gs.woundsRemaining || 0) - 1);
          commit();
          return;
        }
        if (target.matches("[data-group-wounds-increment]")) {
          gs.woundsRemaining = (gs.woundsRemaining || 0) + 1;
          commit();
          return;
        }
        if (target.matches("[data-defeated-toggle]")) {
          gs.defeated = !gs.defeated;
          commit();
          return;
        }
        const statusKey = target.dataset.statusToggle;
        if (statusKey) {
          const newVal = !gs[statusKey];
          gs[statusKey] = newVal;
          if (newVal) {
            if (statusKey === "activated") gs.entrenched = false;
            else if (statusKey === "entrenched") gs.pinned = false;
            else if (statusKey === "pinned") gs.entrenched = false;
          }
          commit();
          return;
        }
      });
    });

    // End round button
    const endRoundBtn = document.querySelector("[data-battle-end-round]");
    if (endRoundBtn) {
      endRoundBtn.addEventListener("click", function () {
        state.round = (state.round || 1) + 1;
        Object.values(state.groups).forEach((gs) => { gs.activated = false; });
        commit();
      });
    }

    // Reset button
    const resetBtn = document.querySelector("[data-battle-reset]");
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        if (!window.confirm("Zakończyć starcie? Stan bitewny zostanie usunięty i przywrócony do wartości początkowych.")) return;
        clearState(rosterId);
        state = { units: {}, groups: {}, round: 1 };
        cards.forEach((card) => {
          state.units[card.dataset.rosterUnitId] = unitInitialState(card);
        });
        groupCards.forEach((g) => {
          state.groups[g.dataset.groupId] = groupInitialState();
        });
        saveState(rosterId, state);
        rerenderAll();
      });
    }

    rerenderAll();
    initTooltips();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
