(function initSZOPArmoryTreeModule(globalScope) {
  const textParsing = globalScope.SZOPTextParsing
    || (typeof globalThis !== 'undefined' ? globalThis.SZOPTextParsing : null)
    || {};
  const normalizeName = textParsing.normalizeName
    || globalScope.normalizeName
    || function normalizeNameFallback(value) {
      return value === undefined || value === null ? '' : String(value).toLowerCase();
    };
  const normalizeRangeValue = textParsing.normalizeRangeValue
    || globalScope.normalizeRangeValue
    || function normalizeRangeValueFallback(value) { return Number(value) || 0; };

// ============================================================
// SECTION: ARMORY WEAPON TREE
// initArmoryWeaponTree — drzewo broni w zbrojowni (filtry, sortowanie)
// ============================================================
function initArmoryWeaponTree() {
  const root = document.getElementById('armory-weapons-tree');
  if (!root) {
    return;
  }
  const treeBody = root.querySelector('[data-tree-body]');
  const emptyState = root.querySelector('[data-empty-state]');
  const filterEmptyState = root.querySelector('[data-filter-empty-state]');
  const filterInput = document.getElementById('weapons-filter');
  const sortButtons = Array.from(root.querySelectorAll('[data-sort-key]'));
  const canEdit = root.dataset.canEdit === 'true';
  const highlightWeaponId = root.dataset.highlightWeapon ? String(root.dataset.highlightWeapon) : '';

  let highlightRow = null;
  let highlightScrollPending = Boolean(highlightWeaponId);

  let rawData;
  try {
    rawData = root.dataset.weapons ? JSON.parse(root.dataset.weapons) : [];
  } catch (err) {
    rawData = [];
  }
  const nodeState = new Map();
  const sortState = { key: null, direction: 'none', type: 'text' };
  let filterQuery = '';

  const normalizeText = typeof normalizeName === 'function'
    ? (value) => normalizeName(value || '')
    : (value) => (value === undefined || value === null ? '' : String(value).toLowerCase());

  const nodeLookup = new Map();

  const hydrate = (node, level = 0, orderIndex = 0, parentId = null) => {
    const abilityItems = Array.isArray(node.abilities) ? node.abilities : [];
    const abilityLabels = abilityItems.map((ability) => ability.label || ability.raw || ability.slug || '');
    const abilityDescriptions = abilityItems.map((ability) => ability.description || ability.raw || '');
    const hydrated = {
      ...node,
      abilities: abilityItems,
      level: Number.isFinite(node.level) ? Number(node.level) : level,
      default_order: Number.isFinite(node.default_order) ? Number(node.default_order) : orderIndex,
      nameSort:
        typeof node.name_sort === 'string' && node.name_sort
          ? node.name_sort
          : normalizeText(node.name || ''),
      abilitiesSort:
        typeof node.abilities_sort === 'string' && node.abilities_sort
          ? node.abilities_sort
          : normalizeText(abilityLabels.join(' ')),
      range_value: Number.isFinite(Number(node.range_value))
        ? Number(node.range_value)
        : normalizeRangeValue(node.range),
      attacks_value: Number.isFinite(Number(node.attacks_value))
        ? Number(node.attacks_value)
        : Number(node.attacks ?? 0),
      ap: Number.isFinite(Number(node.ap)) ? Number(node.ap) : Number(node.ap ?? 0),
      cost: Number.isFinite(Number(node.cost)) ? Number(node.cost) : 0,
      cost_display:
        typeof node.cost_display === 'string' && node.cost_display
          ? node.cost_display
          : (Number.isFinite(Number(node.cost)) ? Number(node.cost).toFixed(2) : '0.00'),
      overrides: { ...(node.overrides || {}) },
      parent_id:
        node.parent_id !== undefined && node.parent_id !== null
          ? node.parent_id
          : parentId !== undefined && parentId !== null
            ? parentId
            : null,
      has_parent:
        node.has_parent !== undefined
          ? Boolean(node.has_parent)
          : node.parent_id !== undefined && node.parent_id !== null,
      parent_name: node.parent_name || '',
    };
    if (hydrated.attacks === undefined || hydrated.attacks === null) {
      hydrated.attacks = Math.round(hydrated.attacks_value);
    }
    hydrated.searchText = normalizeText(
      [
        hydrated.name || '',
        hydrated.range || '',
        String(hydrated.attacks ?? ''),
        String(hydrated.ap ?? ''),
        hydrated.parent_name || '',
        abilityLabels.join(' '),
        abilityDescriptions.join(' '),
      ]
        .filter((part) => part && part.length)
        .join(' '),
    );
    nodeLookup.set(String(hydrated.id), hydrated);

    const childLevel = hydrated.level + 1;
    hydrated.children = Array.isArray(node.children)
      ? node.children.map((child, idx) =>
          hydrate(
            child,
            Number.isFinite(child.level) ? Number(child.level) : childLevel,
            Number.isFinite(child.default_order) ? Number(child.default_order) : idx,
            hydrated.id,
          ),
        )
      : [];
    if (!nodeState.has(hydrated.id) && hydrated.children.length) {
      nodeState.set(hydrated.id, { expanded: false });
    }
    return hydrated;
  };

  const treeData = Array.isArray(rawData)
    ? rawData.map((node, index) =>
        hydrate(
          node,
          Number.isFinite(node.level) ? Number(node.level) : 0,
          Number.isFinite(node.default_order) ? Number(node.default_order) : index,
          node.parent_id !== undefined && node.parent_id !== null ? node.parent_id : null,
        ),
      )
    : [];

  if (highlightWeaponId && nodeLookup.has(highlightWeaponId)) {
    const visited = new Set();
    let current = nodeLookup.get(highlightWeaponId);
    while (current && current.parent_id !== null && !visited.has(current.id)) {
      visited.add(current.id);
      const parentId = current.parent_id;
      const state = nodeState.get(parentId) || {};
      if (state.expanded === false) {
        nodeState.set(parentId, { ...state, expanded: true });
      }
      current = nodeLookup.get(String(parentId));
    }
  }

  const restoreDefaultOrder = (nodes) => {
    nodes.sort((a, b) => (a.default_order ?? 0) - (b.default_order ?? 0));
    nodes.forEach((node) => {
      if (Array.isArray(node.children) && node.children.length) {
        restoreDefaultOrder(node.children);
      }
    });
  };

  const updateSortIndicators = () => {
    const indicatorSymbols = { asc: '▲', desc: '▼' };
    sortButtons.forEach((button) => {
      const indicator = button.querySelector('.armory-tree-sort-indicator');
      const key = button.dataset.sortKey;
      const isActive = sortState.key === key && sortState.direction !== 'none';
      button.dataset.sortDirection = isActive ? sortState.direction : 'none';
      if (indicator) {
        indicator.textContent = isActive ? indicatorSymbols[sortState.direction] || '' : '';
      }
    });
  };

  const sortAccessors = {
    name: (node) => node.nameSort || '',
    range: (node) => (Number.isFinite(node.range_value) ? node.range_value : 0),
    attacks: (node) => (Number.isFinite(node.attacks_value) ? node.attacks_value : 0),
    ap: (node) => (Number.isFinite(node.ap) ? node.ap : 0),
    abilities: (node) => node.abilitiesSort || '',
    cost: (node) => (Number.isFinite(node.cost) ? node.cost : 0),
  };

  const sortBranch = (nodes, comparator) => {
    nodes.sort(comparator);
    nodes.forEach((node) => {
      if (Array.isArray(node.children) && node.children.length) {
        sortBranch(node.children, comparator);
      }
    });
  };

  const applySort = () => {
    if (!treeData.length) {
      return;
    }
    if (sortState.direction === 'none' || !sortState.key) {
      restoreDefaultOrder(treeData);
      return;
    }
    restoreDefaultOrder(treeData);
    const accessor = sortAccessors[sortState.key];
    if (typeof accessor !== 'function') {
      return;
    }
    const comparator = (a, b) => {
      const rawA = accessor(a);
      const rawB = accessor(b);
      let result = 0;
      if (sortState.type === 'number') {
        const valueA = Number.isFinite(rawA) ? rawA : Number.NEGATIVE_INFINITY;
        const valueB = Number.isFinite(rawB) ? rawB : Number.NEGATIVE_INFINITY;
        result = valueA - valueB;
      } else {
        const textA = String(rawA || '');
        const textB = String(rawB || '');
        result = textA.localeCompare(textB, undefined, { sensitivity: 'base' });
      }
      if (result === 0) {
        result = (a.default_order ?? 0) - (b.default_order ?? 0);
      }
      return sortState.direction === 'asc' ? result : -result;
    };
    sortBranch(treeData, comparator);
  };

  const computeVisibility = (nodes) => {
    let visibleCount = 0;
    nodes.forEach((node) => {
      const childVisible = computeVisibility(Array.isArray(node.children) ? node.children : []);
      const matches = !filterQuery || node.searchText.includes(filterQuery);
      const isVisible = matches || childVisible > 0;
      node._matches = matches;
      node._visible = isVisible;
      node._visibleChildren = childVisible;
      if (isVisible) {
        visibleCount += 1;
      }
    });
    return visibleCount;
  };

  const createInheritanceLabel = (isOverridden, indentRem = 0) => {
    const label = document.createElement('div');
    label.className = 'text-muted small';
    label.textContent = isOverridden ? 'Nadpisano' : 'Dziedziczone';
    if (indentRem > 0) {
      label.style.paddingLeft = `${indentRem}rem`;
    }
    return label;
  };

  const renderNode = (node, rows) => {
    if (!node._visible) {
      return;
    }
    const isExpanded = filterQuery ? true : (nodeState.get(node.id)?.expanded !== false);
    const row = document.createElement('div');
    row.className = 'armory-tree-row row g-3 align-items-start px-3 py-3 border-bottom';
    row.dataset.nodeId = String(node.id);

    if (highlightWeaponId && String(node.id) === highlightWeaponId) {
      row.classList.add('armory-tree-highlight');
      highlightRow = row;
    }

    const nameCol = document.createElement('div');
    nameCol.className = 'col-12 col-lg-3 d-flex flex-column gap-1';
    const nameWrapper = document.createElement('div');
    nameWrapper.className = 'd-flex align-items-center gap-2';
    const nameIndent = Math.max(0, node.level) * 1.5;
    nameWrapper.style.paddingLeft = `${nameIndent}rem`;

    const toggleContainer = document.createElement('div');
    toggleContainer.className = 'flex-shrink-0';
    const toggleWidthRem = 1.5;
    toggleContainer.style.width = `${toggleWidthRem}rem`;
    if (Array.isArray(node.children) && node.children.length) {
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'btn btn-link btn-sm p-0 armory-tree-toggle';
      toggle.innerHTML = `<span aria-hidden="true">${isExpanded ? '▾' : '▸'}</span>`;
      toggle.setAttribute('aria-label', isExpanded ? 'Zwiń potomne' : 'Rozwiń potomne');
      toggle.disabled = Boolean(filterQuery);
      toggle.addEventListener('click', (event) => {
        event.preventDefault();
        const current = nodeState.get(node.id) || { expanded: true };
        nodeState.set(node.id, { expanded: !current.expanded });
        applyFilterAndRender();
      });
      toggleContainer.appendChild(toggle);
    } else {
      const spacer = document.createElement('span');
      spacer.style.display = 'inline-block';
      spacer.style.width = '0.75rem';
      spacer.style.height = '1rem';
      toggleContainer.appendChild(spacer);
    }
    nameWrapper.appendChild(toggleContainer);

    const nameText = document.createElement('span');
    nameText.textContent = node.name || 'Bez nazwy';
    nameWrapper.appendChild(nameText);
    nameCol.appendChild(nameWrapper);
    if (node.has_parent) {
      const nameLabelIndent = nameIndent + toggleWidthRem;
      nameCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.name), nameLabelIndent));
    }

    const rangeCol = document.createElement('div');
    rangeCol.className = 'col-6 col-sm-4 col-lg-1 d-flex flex-column gap-1';
    const rangeValue = node.range && String(node.range).trim() ? node.range : '-';
    const rangeText = document.createElement('span');
    if (!node.range || !String(node.range).trim()) {
      rangeText.className = 'text-muted';
    }
    rangeText.textContent = rangeValue;
    rangeCol.appendChild(rangeText);
    if (node.has_parent) {
      rangeCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.range)));
    }

    const attacksCol = document.createElement('div');
    attacksCol.className = 'col-6 col-sm-4 col-lg-1 d-flex flex-column gap-1';
    const attacksText = document.createElement('span');
    attacksText.textContent = String(node.attacks ?? Math.round(node.attacks_value ?? 0));
    attacksCol.appendChild(attacksText);
    if (node.has_parent) {
      attacksCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.attacks)));
    }

    const apCol = document.createElement('div');
    apCol.className = 'col-6 col-sm-4 col-lg-1 d-flex flex-column gap-1';
    const apText = document.createElement('span');
    apText.textContent = String(Number.isFinite(node.ap) ? node.ap : 0);
    apCol.appendChild(apText);
    if (node.has_parent) {
      apCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.ap)));
    }

    const abilitiesCol = document.createElement('div');
    abilitiesCol.className = 'col-12 col-lg-3 d-flex flex-column gap-1 mt-2 mt-lg-0 justify-content-lg-center';
    if (Array.isArray(node.abilities) && node.abilities.length) {
      const abilityWrapper = document.createElement('div');
      abilityWrapper.className = 'd-flex flex-wrap gap-1';
      node.abilities.forEach((ability) => {
        const badge = document.createElement('span');
        badge.className = 'badge text-bg-secondary';
        badge.textContent = ability.label || ability.raw || ability.slug || '-';
        const title = ability.description || ability.raw || '';
        if (title) {
          badge.title = title;
        }
        abilityWrapper.appendChild(badge);
      });
      abilitiesCol.appendChild(abilityWrapper);
    } else {
      const empty = document.createElement('span');
      empty.className = 'text-muted';
      empty.textContent = '-';
      abilitiesCol.appendChild(empty);
    }
    if (node.has_parent) {
      abilitiesCol.appendChild(createInheritanceLabel(Boolean(node.overrides?.tags)));
    }

    const costCol = document.createElement('div');
    costCol.className = 'col-6 col-sm-4 col-lg-1 d-flex flex-column gap-1 mt-2 mt-lg-0 justify-content-lg-center';
    const costText = document.createElement('span');
    costText.textContent = node.cost_display || Number(node.cost || 0).toFixed(2);
    costCol.appendChild(costText);

    const actionsCol = document.createElement('div');
    actionsCol.className = 'col-12 col-lg-2 d-flex justify-content-lg-end align-items-lg-center mt-2 mt-lg-0';
    if (canEdit) {
      const group = document.createElement('div');
      group.className = 'btn-group btn-group-sm';
      const editLink = document.createElement('a');
      editLink.className = 'btn btn-outline-secondary';
      editLink.href = node.edit_url;
      editLink.textContent = 'Edytuj';
      group.appendChild(editLink);

      const deleteForm = document.createElement('form');
      deleteForm.method = 'post';
      deleteForm.action = node.delete_url;
      deleteForm.addEventListener('submit', (event) => {
        if (!confirm('Usunąć broń?')) {
          event.preventDefault();
        }
      });
      const deleteButton = document.createElement('button');
      deleteButton.type = 'submit';
      deleteButton.className = 'btn btn-outline-danger';
      deleteButton.textContent = 'Usuń';
      deleteForm.appendChild(deleteButton);
      group.appendChild(deleteForm);

      actionsCol.appendChild(group);
    } else {
      const readonly = document.createElement('span');
      readonly.className = 'text-muted small';
      readonly.textContent = 'Tylko podgląd';
      actionsCol.appendChild(readonly);
    }

    if (filterQuery && !node._matches && node._visibleChildren > 0) {
      row.classList.add('text-muted');
    }

    row.appendChild(nameCol);
    row.appendChild(rangeCol);
    row.appendChild(attacksCol);
    row.appendChild(apCol);
    row.appendChild(abilitiesCol);
    row.appendChild(costCol);
    row.appendChild(actionsCol);
    treeBody.appendChild(row);
    rows.push(row);

    const showChildren = Array.isArray(node.children) && node.children.length && (filterQuery ? true : isExpanded);
    if (showChildren) {
      node.children.forEach((child) => {
        renderNode(child, rows);
      });
    }
  };

  const renderTree = (visibleCount) => {
    if (!treeBody) {
      return;
    }
    treeBody.innerHTML = '';
    sortButtons.forEach((button) => {
      button.disabled = !treeData.length;
    });
    if (!treeData.length) {
      if (filterInput) {
        filterInput.disabled = true;
        filterInput.placeholder = 'Brak pozycji do filtrowania';
      }
      if (emptyState) {
        emptyState.classList.remove('d-none');
      }
      if (filterEmptyState) {
        filterEmptyState.classList.add('d-none');
      }
      return;
    }
    if (filterInput && filterInput.disabled) {
      filterInput.disabled = false;
      filterInput.placeholder = 'Wpisz nazwę, zdolność lub inną cechę';
    }
    if (filterQuery && visibleCount === 0) {
      if (filterEmptyState) {
        filterEmptyState.classList.remove('d-none');
      }
      if (emptyState) {
        emptyState.classList.add('d-none');
      }
      return;
    }
    if (emptyState) {
      emptyState.classList.add('d-none');
    }
    if (filterEmptyState) {
      filterEmptyState.classList.add('d-none');
    }
    const rows = [];
    highlightRow = null;
    treeData.forEach((node) => {
      renderNode(node, rows);
    });
    if (rows.length) {
      rows[rows.length - 1].classList.remove('border-bottom');
    }

    if (highlightRow && highlightScrollPending) {
      highlightScrollPending = false;
      if (typeof highlightRow.scrollIntoView === 'function') {
        requestAnimationFrame(() => {
          highlightRow.scrollIntoView({ block: 'center' });
        });
      }
    }
  };

  const applyFilterAndRender = () => {
    applySort();
    const visibleCount = computeVisibility(treeData);
    renderTree(visibleCount);
    updateSortIndicators();
  };

  sortButtons.forEach((button) => {
    const sortKey = button.dataset.sortKey;
    const sortType = button.dataset.sortType || 'text';
    button.addEventListener('click', (event) => {
      event.preventDefault();
      if (!treeData.length) {
        return;
      }
      let nextDirection = 'asc';
      if (sortState.key === sortKey) {
        nextDirection = sortState.direction === 'asc' ? 'desc' : sortState.direction === 'desc' ? 'none' : 'asc';
      }
      sortState.key = nextDirection === 'none' ? null : sortKey;
      sortState.direction = nextDirection;
      sortState.type = sortType;
      applyFilterAndRender();
    });
  });

  if (filterInput) {
    filterInput.addEventListener('input', () => {
      filterQuery = normalizeText(filterInput.value || '');
      applyFilterAndRender();
    });
  }

  applyFilterAndRender();
}

  const api = {
    initArmoryWeaponTree: initArmoryWeaponTree,
  };
  globalScope.SZOPArmoryTree = api;
  globalScope.initArmoryWeaponTree = initArmoryWeaponTree;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPArmoryTree = api;
    globalThis.initArmoryWeaponTree = initArmoryWeaponTree;
  }
}(typeof window !== 'undefined' ? window : globalThis));
