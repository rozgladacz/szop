(function initSZOPWeaponPickerModule(globalScope) {
  const textParsing = globalScope.SZOPTextParsing
    || (typeof globalThis !== 'undefined' ? globalThis.SZOPTextParsing : null)
    || {};
  const rosterRendering = globalScope.SZOPRosterRendering
    || (typeof globalThis !== 'undefined' ? globalThis.SZOPRosterRendering : null)
    || {};
  const normalizeRangeValue = textParsing.normalizeRangeValue
    || globalScope.normalizeRangeValue
    || function normalizeRangeValueFallback(value) { return Number(value) || 0; };
  const formatPoints = rosterRendering.formatPoints
    || globalScope.formatPoints
    || function formatPointsFallback(value) {
      return value !== undefined && value !== null ? String(value) : '0';
    };

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


  const api = {
    initWeaponPicker: initWeaponPicker,
    initWeaponPickers: initWeaponPickers,
  };
  globalScope.SZOPWeaponPicker = api;
  globalScope.initWeaponPicker = initWeaponPicker;
  globalScope.initWeaponPickers = initWeaponPickers;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPWeaponPicker = api;
    globalThis.initWeaponPicker = initWeaponPicker;
    globalThis.initWeaponPickers = initWeaponPickers;
  }
}(typeof window !== 'undefined' ? window : globalThis));
