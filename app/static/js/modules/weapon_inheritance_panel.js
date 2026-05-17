(function initSZOPWeaponInheritancePanelModule(globalScope) {

// ============================================================
// SECTION: WEAPON INHERITANCE PANEL
// initWeaponInheritancePanel — collapsible panel on armory weapon edit
// form with a hierarchical tree picker (one section per ancestor armory).
// Updates hidden inputs inherit_armory_id / inherit_parent_weapon_id.
// ============================================================
function initWeaponTreePickerPanel(panel, cfg) {
  const toggle = cfg.toggleAttr ? panel.querySelector(`[${cfg.toggleAttr}]`) : null;
  const body = cfg.bodyAttr ? panel.querySelector(`[${cfg.bodyAttr}]`) : panel;
  const armorySelect = panel.querySelector(`[${cfg.armorySelectAttr}]`);
  const treeWrapper = panel.querySelector(`[${cfg.treeWrapperAttr}]`);
  const treeContainer = panel.querySelector(`[${cfg.treeAttr}]`);
  const armoryInput = panel.querySelector(`[${cfg.armoryValueAttr}]`);
  const weaponInput = panel.querySelector(`[${cfg.weaponValueAttr}]`);
  const chevron = cfg.chevronAttr ? panel.querySelector(`[${cfg.chevronAttr}]`) : null;
  if (!armorySelect || !treeContainer) {
    return;
  }

  let options = [];
  try {
    options = JSON.parse(panel.dataset[cfg.optionsDataKey] || '[]');
  } catch (_) {
    options = [];
  }

  let current = null;
  try {
    current = cfg.currentDataKey && panel.dataset[cfg.currentDataKey]
      ? JSON.parse(panel.dataset[cfg.currentDataKey])
      : null;
  } catch (_) {
    current = null;
  }

    let selectedArmoryId = current ? String(current.armory_id) : '';
    let selectedWeaponId = current ? String(current.weapon_id) : '';
    const collapsedWeapons = new Set();

    options.forEach((entry) => {
      const opt = document.createElement('option');
      opt.value = String(entry.armory_id);
      opt.textContent = entry.armory_name + (entry.is_current ? ' (bieżąca)' : '');
      armorySelect.appendChild(opt);
    });
    armorySelect.value = selectedArmoryId || '';

    function applySelection() {
      if (armoryInput) armoryInput.value = selectedArmoryId || '';
      if (weaponInput) weaponInput.value = selectedWeaponId || '';
    }
    applySelection();

    function currentEntry() {
      return options.find((e) => String(e.armory_id) === selectedArmoryId) || null;
    }

    function createWeaponNode(weapon, depth) {
      const li = document.createElement('li');
      li.style.listStyle = 'none';
      const row = document.createElement('div');
      row.className = 'd-flex align-items-center gap-1 py-1';
      row.style.paddingLeft = `${depth * 1.25}rem`;

      const hasChildren = Array.isArray(weapon.children) && weapon.children.length > 0;
      const isCollapsed = collapsedWeapons.has(String(weapon.id));

      if (hasChildren) {
        const chevBtn = document.createElement('button');
        chevBtn.type = 'button';
        chevBtn.className = 'btn btn-link btn-sm p-0 text-muted flex-shrink-0';
        chevBtn.style.lineHeight = '1';
        chevBtn.style.width = '1.1rem';
        chevBtn.setAttribute('aria-label', isCollapsed ? 'Rozwiń' : 'Zwiń');
        chevBtn.textContent = isCollapsed ? '▸' : '▾';
        chevBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (collapsedWeapons.has(String(weapon.id))) {
            collapsedWeapons.delete(String(weapon.id));
          } else {
            collapsedWeapons.add(String(weapon.id));
          }
          renderTree();
        });
        row.appendChild(chevBtn);
      } else {
        const spacer = document.createElement('span');
        spacer.style.width = '1.1rem';
        spacer.style.flexShrink = '0';
        spacer.setAttribute('aria-hidden', 'true');
        row.appendChild(spacer);
      }

      const isSelected = selectedWeaponId === String(weapon.id);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `btn btn-sm text-start flex-grow-1 ${isSelected ? 'btn-primary' : 'btn-outline-secondary'}`;
      btn.textContent = weapon.name || `#${weapon.id}`;
      btn.addEventListener('click', () => {
        if (isSelected) {
          selectedWeaponId = '';
        } else {
          selectedWeaponId = String(weapon.id);
        }
        applySelection();
        renderTree();
      });
      row.appendChild(btn);
      li.appendChild(row);

      if (hasChildren && !isCollapsed) {
        const ul = document.createElement('ul');
        ul.className = 'ps-0 mb-0';
        weapon.children.forEach((child) => ul.appendChild(createWeaponNode(child, depth + 1)));
        li.appendChild(ul);
      }
      return li;
    }

    function renderTree() {
      treeContainer.innerHTML = '';
      const entry = currentEntry();
      if (!entry) {
        if (treeWrapper) treeWrapper.classList.add('d-none');
        return;
      }
      if (treeWrapper) treeWrapper.classList.remove('d-none');
      const weapons = Array.isArray(entry.weapons) ? entry.weapons : [];
      if (!weapons.length) {
        const empty = document.createElement('div');
        empty.className = 'text-muted small';
        empty.textContent = 'Brak broni w tej zbrojowni.';
        treeContainer.appendChild(empty);
        return;
      }
      const ul = document.createElement('ul');
      ul.className = 'ps-0 mb-0';
      weapons.forEach((w) => ul.appendChild(createWeaponNode(w, 0)));
      treeContainer.appendChild(ul);
    }

    function initCollapsed(weapons) {
      (Array.isArray(weapons) ? weapons : []).forEach((w) => {
        if (Array.isArray(w.children) && w.children.length) {
          collapsedWeapons.add(String(w.id));
          initCollapsed(w.children);
        }
      });
    }
    options.forEach((entry) => initCollapsed(entry.weapons));

    if (selectedWeaponId) {
      const entry = currentEntry();
      if (entry) {
        const expandPath = (weapons) => {
          for (const w of weapons) {
            if (String(w.id) === selectedWeaponId) return true;
            if (Array.isArray(w.children) && expandPath(w.children)) {
              collapsedWeapons.delete(String(w.id));
              return true;
            }
          }
          return false;
        };
        expandPath(entry.weapons || []);
      }
    }

    armorySelect.addEventListener('change', () => {
      selectedArmoryId = armorySelect.value || '';
      selectedWeaponId = '';
      applySelection();
      renderTree();
    });

    if (toggle && body) {
      let treeInitialized = false;
      toggle.addEventListener('click', () => {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        const next = !expanded;
        toggle.setAttribute('aria-expanded', next ? 'true' : 'false');
        body.classList.toggle('d-none', !next);
        if (chevron) chevron.textContent = next ? '▾' : '▸';
        if (next && !treeInitialized) {
          treeInitialized = true;
          renderTree();
        }
      });
    } else {
      renderTree();
    }
}

const INHERITANCE_PANEL_CFG = {
  panelAttr: 'data-inheritance-panel',
  toggleAttr: 'data-inheritance-toggle',
  bodyAttr: 'data-inheritance-body',
  armorySelectAttr: 'data-inheritance-armory-select',
  treeWrapperAttr: 'data-inheritance-tree-wrapper',
  treeAttr: 'data-inheritance-tree',
  armoryValueAttr: 'data-inheritance-armory-value',
  weaponValueAttr: 'data-inheritance-weapon-value',
  chevronAttr: 'data-inheritance-chevron',
  optionsDataKey: 'inheritanceOptions',
  currentDataKey: 'currentInheritance',
};

const IMPORT_PANEL_CFG = {
  panelAttr: 'data-import-panel',
  toggleAttr: null,
  bodyAttr: null,
  armorySelectAttr: 'data-import-armory-select',
  treeWrapperAttr: 'data-import-tree-wrapper',
  treeAttr: 'data-import-tree',
  armoryValueAttr: 'data-import-armory-value',
  weaponValueAttr: 'data-import-weapon-value',
  chevronAttr: null,
  optionsDataKey: 'importOptions',
  currentDataKey: null,
};

function initWeaponInheritancePanel() {
  document.querySelectorAll(`[${INHERITANCE_PANEL_CFG.panelAttr}]`).forEach((panel) => {
    initWeaponTreePickerPanel(panel, INHERITANCE_PANEL_CFG);
  });
}

function initWeaponImportPanel() {
  document.querySelectorAll(`[${IMPORT_PANEL_CFG.panelAttr}]`).forEach((panel) => {
    initWeaponTreePickerPanel(panel, IMPORT_PANEL_CFG);
  });
}

  const api = {
    initWeaponTreePickerPanel: initWeaponTreePickerPanel,
    initWeaponInheritancePanel: initWeaponInheritancePanel,
    initWeaponImportPanel: initWeaponImportPanel,
  };
  globalScope.SZOPWeaponInheritancePanel = api;
  globalScope.initWeaponInheritancePanel = initWeaponInheritancePanel;
  globalScope.initWeaponImportPanel = initWeaponImportPanel;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPWeaponInheritancePanel = api;
    globalThis.initWeaponInheritancePanel = initWeaponInheritancePanel;
    globalThis.initWeaponImportPanel = initWeaponImportPanel;
  }
}(typeof window !== 'undefined' ? window : globalThis));
