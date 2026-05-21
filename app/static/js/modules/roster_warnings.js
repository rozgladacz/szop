// ============================================================
// SECTION: ROSTER WARNINGS
// SZOPRosterWarnings — badge ⚠ z listą ostrzeżeń pod
// nagłówkiem "Oddziały w rozpisce". Recompute po każdej
// zmianie kosztu/liczebności oddziałów (hooki w roster_editor.js).
// ============================================================
(function initSZOPRosterWarnings(globalScope) {
  // Feature flags — możliwe wyłączenie przez window.SZOP_ROSTER_WARNINGS_ENABLED
  // lub window.SZOP_ROSTER_WARNINGS_HEAVY_ENABLED (warunki 6-8).
  function isEnabled() {
    return globalScope.SZOP_ROSTER_WARNINGS_ENABLED !== false;
  }
  function isHeavyEnabled() {
    return isEnabled() && globalScope.SZOP_ROSTER_WARNINGS_HEAVY_ENABLED !== false;
  }

  // --------------------------------------------------------
  // DOM helpers
  // --------------------------------------------------------
  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = String(text == null ? '' : text);
    return div.innerHTML;
  }

  function getRoot() {
    return document.querySelector('[data-roster-root]');
  }

  function getIndicator(root) {
    return root && root.querySelector('[data-roster-warnings]');
  }

  // --------------------------------------------------------
  // Frame aggregation
  // --------------------------------------------------------
  function getFrames(root) {
    var listEl = root && root.querySelector('[data-roster-list]');
    if (!listEl) return [];

    var allItems = listEl.querySelectorAll('[data-roster-item]');
    var framesMap = [];
    var heroMap = {};

    allItems.forEach(function (item) {
      var isAttached = item.hasAttribute('data-roster-attached-hero');
      var isHero = item.getAttribute('data-is-hero') === 'true';
      var id = item.getAttribute('data-roster-unit-id') || '';
      var parentId = item.getAttribute('data-parent-roster-unit-id') || '';
      var count = Math.max(parseInt(item.getAttribute('data-unit-count') || '1', 10) || 1, 1);
      var cost = parseFloat(item.getAttribute('data-unit-cost') || '0') || 0;
      var toughness = parseFloat(item.getAttribute('data-unit-toughness') || '0') || 0;
      var weaponCost = parseFloat(item.getAttribute('data-unit-weapon-cost') || '0') || 0;

      var titleEl = item.querySelector('[data-roster-unit-title]');
      var rawTitle = titleEl ? (titleEl.textContent || '') : (item.getAttribute('data-unit-name') || 'Oddział');
      // Strip leading "Nx " prefix added by renderning (e.g. "3x Marines" → "Marines")
      var name = rawTitle.replace(/^\d+x\s+/, '');

      var entry = {
        id: id,
        name: name,
        count: count,
        cost: cost,
        toughness: toughness * count,  // totalToughness per unit incl all models
        weaponCost: weaponCost,         // already per-unit-total (from backend classification formula)
        isHero: isHero,
        isAttached: isAttached,
        parentId: parentId,
      };

      if (isAttached) {
        (heroMap[parentId] = heroMap[parentId] || []).push(entry);
      } else {
        framesMap.push(entry);
      }
    });

    // Merge attached heroes into their parent frame
    framesMap.forEach(function (frame) {
      var attached = heroMap[frame.id] || [];
      attached.forEach(function (hero) {
        frame.cost += hero.cost;
        frame.toughness += hero.toughness;
        frame.weaponCost += hero.weaponCost;
      });
    });

    return framesMap;
  }

  // --------------------------------------------------------
  // Warning computation
  // --------------------------------------------------------
  function computeWarnings(root) {
    var warnings = [];

    var framesCountEl = root.querySelector('[data-roster-frames-count]');
    var heroCountEl = root.querySelector('[data-roster-hero-count]');
    var totalEl = root.querySelector('[data-roster-total]');
    var totalContainerEl = root.querySelector('[data-roster-total-container]');

    var framesCount = framesCountEl ? (parseInt(framesCountEl.textContent, 10) || 0) : 0;
    var heroModels = heroCountEl ? (parseInt(heroCountEl.textContent, 10) || 0) : 0;
    // Sum data-unit-cost attributes directly (raw numbers) to avoid locale parsing.
    var listEl = root.querySelector('[data-roster-list]');
    var allCostItems = listEl ? listEl.querySelectorAll('[data-roster-item]') : [];
    var totalCost = Array.from(allCostItems).reduce(function (sum, item) {
      return sum + (parseFloat(item.getAttribute('data-unit-cost') || '0') || 0);
    }, 0);
    var pointsLimit = totalContainerEl ? (parseFloat(totalContainerEl.getAttribute('data-limit') || '0') || 0) : 0;

    // 1. Za mało oddziałów
    if (framesCount < 4) {
      warnings.push('Masz mniej niż 4 oddziały.');
    }
    // 2. Za dużo oddziałów
    if (framesCount > 8) {
      warnings.push('Masz więcej niż 8 oddziałów.');
    }
    // 3. Brak bohatera
    if (heroModels === 0) {
      warnings.push('Nie masz żadnego bohatera.');
    }
    // 4. Za dużo bohaterów
    if (heroModels > 4) {
      warnings.push('Masz więcej niż 4 bohaterów.');
    }
    // 5. Przekroczony limit punktów
    if (pointsLimit > 0 && totalCost > pointsLimit) {
      warnings.push('Przekroczyłeś limit punktów.');
    }

    if (!isHeavyEnabled()) {
      return warnings;
    }

    var frames = getFrames(root);

    // 6. Jeden oddział ponad 4× droższy od najtańszego (tylko skrajna para)
    if (frames.length >= 2) {
      var maxFrame = frames[0];
      var minFrame = frames[0];
      frames.forEach(function (f) {
        if (f.cost > maxFrame.cost) maxFrame = f;
        if (f.cost < minFrame.cost) minFrame = f;
      });
      if (maxFrame !== minFrame && minFrame.cost > 0 && maxFrame.cost > 4 * minFrame.cost) {
        warnings.push(
          'Oddział ' + maxFrame.name + ' jest ponad 4 razy droższy od ' + minFrame.name + '.'
        );
      }
    }

    // 7-8. Mało/dużo broni vs wytrzymałość
    frames.forEach(function (f) {
      if (f.toughness <= 0) return;
      if (f.weaponCost < 5 * f.toughness) {
        warnings.push('Oddział ' + f.name + ' ma mało broni.');
      } else if (f.weaponCost > 25 * f.toughness) {
        warnings.push('Oddział ' + f.name + ' ma dużo broni.');
      }
    });

    return warnings;
  }

  // --------------------------------------------------------
  // Tooltip initialization / update
  // --------------------------------------------------------
  function initOrUpdateTooltip(el, htmlContent) {
    if (typeof bootstrap === 'undefined' || !bootstrap.Tooltip) return;
    var existing = bootstrap.Tooltip.getInstance(el);
    if (existing) {
      existing.setContent({ '.tooltip-inner': htmlContent });
    } else {
      el.setAttribute('data-bs-title', htmlContent);
      new bootstrap.Tooltip(el, { trigger: 'hover focus', html: true });
    }
  }

  // --------------------------------------------------------
  // Render
  // --------------------------------------------------------
  function renderWarnings(root, warnings) {
    var indicator = getIndicator(root);
    if (!indicator) return;

    var countEl = indicator.querySelector('[data-roster-warnings-count]');

    if (warnings.length === 0) {
      indicator.classList.add('d-none');
      if (countEl) countEl.textContent = '0';
      return;
    }

    var listHtml = '<ul class="mb-0 ps-3 text-start">' +
      warnings.map(function (w) { return '<li>' + escapeHtml(w) + '</li>'; }).join('') +
      '</ul>';

    if (countEl) countEl.textContent = String(warnings.length);
    indicator.classList.remove('d-none');
    initOrUpdateTooltip(indicator, listHtml);
  }

  // --------------------------------------------------------
  // Public API
  // --------------------------------------------------------
  function recompute() {
    if (!isEnabled()) return;
    var root = getRoot();
    if (!root) return;
    var warnings = computeWarnings(root);
    renderWarnings(root, warnings);
  }

  function mount() {
    if (!isEnabled()) return;
    // Initial render on page load
    recompute();
  }

  document.addEventListener('DOMContentLoaded', mount);

  globalScope.SZOPRosterWarnings = { mount: mount, recompute: recompute };

}(typeof window !== 'undefined' ? window : this));
