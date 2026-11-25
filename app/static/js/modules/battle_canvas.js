/* Read-only projection of the public checkpoint. No engine, event replay or writes. */
(function (root) {
  'use strict';
  const COLORS = ['#0756a1', '#a33b00'];
  const TERRAIN_LABELS = { circle: 'koło', line: 'odcinek', polygon: 'wielokąt' };
  const LOCATIONS = { front: 'Front', zaplecze: 'Zaplecze', wycofany: 'Wycofany', eliminowany: 'Eliminowany' };
  const PHASES = {
    BEFORE_ACTION: 'Przed akcją', ACTION_READY: 'Gotowość do akcji',
    ATTACK_WINDOW: 'Okno ataku', ATTACK_RESOLUTION_READY: 'Gotowość rozstrzygnięcia ataku',
    AWAITING_CONTINUATION: 'Oczekiwanie na kontynuację', AWAITING_FINALIZATION: 'Oczekiwanie na zakończenie'
  };

  // === SECTION: Public wire projection — validate only data used by this leaf ===
  function requireValue(condition) { if (!condition) throw new Error('malformed'); }
  function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
  function fields(value, name) {
    requireValue(object(value) && value.$dataclass === name && object(value.fields));
    return value.fields;
  }
  function tuple(value) { requireValue(object(value) && Array.isArray(value.$tuple)); return value.$tuple; }
  function number(value) { requireValue(typeof value === 'number' && Number.isFinite(value)); return value; }
  function integer(value, minimum = 0) { requireValue(Number.isSafeInteger(value) && value >= minimum); return value; }
  function player(value) { requireValue(value === 0 || value === 1); return value; }
  function text(value) { requireValue(typeof value === 'string'); return value; }
  function strings(value) { return tuple(value).map(text); }
  function statuses(value) {
    return tuple(value).map((status) => {
      if (typeof status === 'string') return status;
      requireValue(object(status) && status.$enum === 'StatusFlag');
      return text(status.value);
    });
  }
  function position(value) {
    const p = fields(value, 'Position');
    return { x: number(p.x), y: number(p.y) };
  }
  function radius(value) { requireValue(number(value) >= 0); return value; }
  function parseCheckpoint(payload, expectedId) {
    requireValue(object(payload));
    if (payload.schema !== 'szop.battle_state' || ![1, 2, 3].includes(payload.version)) throw new Error('unsupported');
    requireValue(integer(payload.battle_id, 1) === expectedId);
    const s = fields(payload.state, 'BattleState');
    const ids = new Set();
    const units = tuple(s.blobs).map((value) => {
      const b = fields(value, 'UnitBlob');
      const id = integer(b.id);
      requireValue(!ids.has(id)); ids.add(id);
      requireValue(object(b.location) && b.location.$enum === 'Lokalizacja' && Object.hasOwn(LOCATIONS, b.location.value));
      const unit = {
        id, owner: player(b.owner_player), position: position(b.position), radius: radius(b.radius_inches),
        models: integer(b.models_alive), toughness: integer(b.toughness_per_model, 1),
        quality: integer(b.quality), defense: integer(b.defense), location: b.location.value,
        statuses: statuses(b.status_flags), passives: strings(b.passives),
        wounds: integer(b.wounds_received), pending: integer(b.wounds_pending),
        precise: integer(b.wounds_pending_precise), eliminating: integer(b.wounds_eliminating),
        balance: integer(b.damage_balance, -Number.MAX_SAFE_INTEGER)
      };
      unit.onBoard = unit.location === 'front' && unit.models > 0;
      return unit;
    });
    const terrain = tuple(s.terrain).map((value) => {
      if (value && value.$dataclass === 'TerrainCircle') {
        const t = fields(value, 'TerrainCircle');
        return { kind: 'circle', center: position(t.center), radius: radius(t.radius_inches), features: strings(t.features) };
      }
      if (value && value.$dataclass === 'TerrainPolygon') {
        const t = fields(value, 'TerrainPolygon');
        const vertices = tuple(t.vertices).map(position);
        requireValue(vertices.length >= 3);
        return { kind: 'polygon', vertices, features: strings(t.features) };
      }
      const t = fields(value, 'TerrainLine');
      return { kind: 'line', start: position(t.start), end: position(t.end), features: strings(t.features) };
    });
    const objectives = tuple(s.objectives).map((value) => {
      const o = fields(value, 'Objective');
      return { id: integer(o.id), position: position(o.position), controller: o.controller === null ? null : player(o.controller) };
    });
    const score = tuple(s.score).map((v) => integer(v));
    requireValue(score.length === 2 && typeof s.is_game_over === 'boolean');
    let phase = null;
    if (payload.version > 1 && s.activation !== null) {
      const a = fields(s.activation, 'ActivationState');
      requireValue(object(a.phase) && a.phase.$enum === 'ActivationPhase' && Object.hasOwn(PHASES, a.phase.value));
      phase = PHASES[a.phase.value];
    }
    return {
      battleId: payload.battle_id, version: payload.version, sequence: integer(payload.sequence_at),
      round: integer(s.round), activePlayer: player(s.active_player), score, gameOver: s.is_game_over,
      phase, units, terrain, objectives
    };
  }

  // === SECTION: View coordinates — viewport is not an inferred board boundary ===
  function viewBounds(view) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    function include(p, r = 0) {
      minX = Math.min(minX, p.x - r); maxX = Math.max(maxX, p.x + r);
      minY = Math.min(minY, p.y - r); maxY = Math.max(maxY, p.y + r);
    }
    view.units.filter((u) => u.onBoard).forEach((u) => include(u.position, u.radius));
    view.terrain.forEach((t) => {
      if (t.kind === 'circle') include(t.center, t.radius);
      else if (t.kind === 'line') { include(t.start); include(t.end); }
      else t.vertices.forEach((vertex) => include(vertex));
    });
    view.objectives.forEach((o) => include(o.position));
    if (minX === Infinity) return { minX: 0, minY: 0, maxX: 48, maxY: 36, empty: true };
    const pad = Math.max(2, Math.max(maxX - minX, maxY - minY) * 0.08);
    const bounds = { minX: minX - pad, minY: minY - pad, maxX: maxX + pad, maxY: maxY + pad, empty: false };
    requireValue(Object.values(bounds).every((v) => typeof v !== 'number' || Number.isFinite(v)));
    return bounds;
  }
  function transform(bounds, width, height) {
    const scale = Math.min((width - 40) / (bounds.maxX - bounds.minX), (height - 40) / (bounds.maxY - bounds.minY));
    const ox = (width - (bounds.maxX - bounds.minX) * scale) / 2;
    const oy = (height - (bounds.maxY - bounds.minY) * scale) / 2;
    return { scale, point: (p) => ({ x: ox + (p.x - bounds.minX) * scale, y: height - oy - (p.y - bounds.minY) * scale }) };
  }
  function sizeCanvas(canvas, ratio) {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(100, rect.width), height = Math.max(100, rect.height);
    const dpr = Number.isFinite(ratio) && ratio > 0 ? Math.min(ratio, 4) : 1;
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width, height };
  }
  function pickUnit(view, tx, x, y) {
    return [...view.units].reverse().find((u) => {
      if (!u.onBoard) return false;
      const p = tx.point(u.position);
      return Math.hypot(x - p.x, y - p.y) <= Math.max(8, u.radius * tx.scale);
    }) || null;
  }
  function draw(canvas, view, selectedId, ratio = 1) {
    const { ctx, width, height } = sizeCanvas(canvas, ratio);
    ctx.clearRect(0, 0, width, height);
    if (!view) return null;
    const bounds = viewBounds(view), tx = transform(bounds, width, height);
    function circle(p, r) { ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); }
    ctx.font = '12px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    view.terrain.forEach((t, i) => {
      ctx.strokeStyle = '#626970'; ctx.fillStyle = '#d9dddf'; ctx.lineWidth = 2;
      let p;
      if (t.kind === 'circle') {
        p = tx.point(t.center); circle(p, t.radius * tx.scale); ctx.fill(); ctx.stroke();
      } else {
        const vertices = t.kind === 'line' ? [t.start, t.end] : t.vertices;
        p = { x: 0, y: 0 };
        ctx.beginPath();
        vertices.forEach((vertex, index) => {
          const q = tx.point(vertex);
          if (index === 0) ctx.moveTo(q.x, q.y);
          else ctx.lineTo(q.x, q.y);
          p.x += q.x; p.y += q.y;
        });
        if (t.kind === 'polygon') { ctx.closePath(); ctx.fill(); }
        ctx.stroke();
        p.x /= vertices.length; p.y /= vertices.length;
      }
      ctx.fillStyle = '#30363b'; ctx.fillText(`T${i + 1}`, p.x, p.y - 10);
    });
    view.objectives.forEach((o) => {
      const p = tx.point(o.position);
      ctx.fillStyle = o.controller === null ? '#626970' : COLORS[o.controller]; ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(p.x, p.y - 8); ctx.lineTo(p.x + 8, p.y);
      ctx.lineTo(p.x, p.y + 8); ctx.lineTo(p.x - 8, p.y); ctx.closePath(); ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#212529'; ctx.fillText(`Cel ${o.id}`, p.x, p.y + 18);
    });
    view.units.filter((u) => u.onBoard).forEach((u) => {
      const p = tx.point(u.position), r = u.radius * tx.scale;
      ctx.fillStyle = COLORS[u.owner]; ctx.strokeStyle = u.id === selectedId ? '#111' : '#fff';
      ctx.lineWidth = u.id === selectedId ? 4 : 2;
      circle(p, r); ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#fff'; ctx.fillText(String(u.id), p.x, p.y);
    });
    return { bounds, tx };
  }

  // === SECTION: Checkpoint requests — one GET, fail closed, latest request wins ===
  function battleId(raw) {
    if (!/^[1-9]\d*$/.test(raw)) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) ? value : null;
  }
  function errorMessage(code) {
    return ({
      invalid: 'Podaj poprawne dodatnie ID bitwy.',
      401: 'Sesja wygasła lub nie jesteś zalogowany. Zaloguj się ponownie.',
      403: 'Brak uprawnienia do odczytu checkpointu.',
      404: 'Bitwa nie istnieje lub nie masz do niej dostępu.',
      409: 'Bieżący checkpoint bitwy jest niedostępny.',
      unsupported: 'Nieobsługiwany schemat lub wersja checkpointu.',
      malformed: 'Checkpoint ma nieprawidłowe dane. Nie wyświetlono planszy.',
      network: 'Nie udało się pobrać checkpointu. Sprawdź połączenie i spróbuj ponownie.'
    })[code] || 'Nie udało się wczytać checkpointu. Spróbuj ponownie.';
  }
  function createLoader(fetcher, onChange) {
    let epoch = 0, controller = null;
    function clear() {
      epoch += 1;
      if (controller) controller.abort();
      controller = null;
      onChange({ status: 'idle' });
    }
    async function load(raw) {
      clear();
      const id = battleId(raw), current = epoch;
      if (id === null) { onChange({ status: 'error', code: 'invalid' }); return; }
      controller = new AbortController();
      onChange({ status: 'loading' });
      try {
        const response = await fetcher(`/battles/${id}/state`, {
          method: 'GET', credentials: 'same-origin', cache: 'no-store',
          headers: { Accept: 'application/json' }, signal: controller.signal
        });
        if (current !== epoch) return;
        if (!response.ok) { onChange({ status: 'error', code: response.status }); return; }
        let payload;
        try { payload = await response.json(); } catch (_) { throw new Error('malformed'); }
        if (current !== epoch) return;
        const view = parseCheckpoint(payload, id);
        viewBounds(view);
        onChange({ status: 'ready', view });
      } catch (error) {
        if (current !== epoch) return;
        const code = ['malformed', 'unsupported'].includes(error.message) ? error.message : 'network';
        onChange({ status: 'error', code });
      }
    }
    return { load, clear };
  }

  // === SECTION: Page-only UI — text nodes, keyboard list and read-only selection ===
  function mount(host, win) {
    const doc = host.ownerDocument;
    const get = (suffix) => doc.getElementById(`battle-preview-${suffix}`);
    const canvas = get('canvas'), input = get('id'), message = get('message'), summary = get('summary');
    let view = null, selectedId = null, geometry = null;
    function append(parent, tag, value, cls = '') {
      const el = doc.createElement(tag); el.textContent = value; el.className = cls; parent.appendChild(el); return el;
    }
    function redraw() {
      geometry = draw(canvas, view, selectedId, win.devicePixelRatio);
      if (geometry) {
        const b = geometry.bounds, fmt = (n) => Number(n.toFixed(1));
        get('bounds').textContent = `${b.empty ? 'Domyślny pusty widok' : 'Widok dopasowany do danych'}: x ${fmt(b.minX)}–${fmt(b.maxX)}, y ${fmt(b.minY)}–${fmt(b.maxY)} cali. To nie są granice pola bitwy.`;
      }
    }
    function select(id) {
      selectedId = id;
      const u = view && view.units.find((unit) => unit.id === id);
      const details = get('details'); details.replaceChildren();
      if (!u) { details.textContent = 'Wybierz oddział na planszy lub z listy.'; return; }
      append(details, 'p', `Oddział ${u.id} · strona ${u.owner + 1}`, 'fw-semibold');
      [
        `Lokalizacja: ${LOCATIONS[u.location]}${u.models === 0 ? ' · brak żywych modeli' : ''}`,
        `Pozycja: (${u.position.x}, ${u.position.y}) cali · promień: ${u.radius} cali`,
        `Modele: ${u.models} · wytrzymałość/model: ${u.toughness} · jakość: ${u.quality} · obrona: ${u.defense}`,
        `Rany: ${u.wounds} · nadchodzące: ${u.pending} · precyzyjne: ${u.precise} · eliminujące: ${u.eliminating}`,
        `Bilans obrażeń: ${u.balance}`,
        `Statusy: ${u.statuses.join(', ') || 'brak'}`,
        `Pasywy (zapisane): ${u.passives.join(', ') || 'brak'}`
      ].forEach((line) => append(details, 'p', line, 'small mb-2'));
      host.querySelectorAll('[data-battle-unit]').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.battleUnit) === id)));
      redraw();
    }
    function update(state) {
      view = state.view || null; selectedId = null;
      if (win.CustomEvent) host.dispatchEvent(new win.CustomEvent('szop:checkpoint', {
        detail: view ? {
          battleId: view.battleId, version: view.version, sequence: view.sequence,
          activePlayer: view.activePlayer, gameOver: view.gameOver
        } : null
      }));
      summary.hidden = true; summary.textContent = '';
      get('fit').disabled = !view;
      get('front').replaceChildren(); get('off').replaceChildren(); get('features').replaceChildren();
      get('bounds').textContent = 'Granice widoku nie są granicami pola bitwy.';
      select(null); redraw();
      message.className = `alert ${state.status === 'error' ? 'alert-danger' : 'alert-secondary'}`;
      message.textContent = state.status === 'error' ? errorMessage(state.code) : state.status === 'loading' ? 'Wczytywanie checkpointu…' : 'Podaj ID bitwy, aby wczytać checkpoint.';
      if (!view) return;
      message.className = 'alert alert-success'; message.textContent = 'Wczytano utrwalony checkpoint. Zmiany bitwy nie odświeżają widoku automatycznie.';
      summary.hidden = false;
      summary.textContent = `Bitwa ${view.battleId} · runda ${view.round} · aktywna strona ${view.activePlayer + 1} · wynik ${view.score[0]} : ${view.score[1]} · sequence_at ${view.sequence} · v${view.version}${view.phase ? ` · ${view.phase}` : ''}${view.gameOver ? ' · gra zakończona' : ''}`;
      for (const onBoard of [true, false]) {
        const list = get(onBoard ? 'front' : 'off'), units = view.units.filter((u) => u.onBoard === onBoard);
        if (!units.length) append(list, 'li', 'Brak oddziałów.', 'text-muted small');
        units.forEach((u) => {
          const li = append(list, 'li', '');
          const b = append(li, 'button', `Oddział ${u.id} · strona ${u.owner + 1} · ${u.models} modeli · ${LOCATIONS[u.location]}`, `btn btn-outline-secondary battle-side-${u.owner}`);
          b.type = 'button'; b.dataset.battleUnit = String(u.id); b.setAttribute('aria-pressed', 'false');
          b.addEventListener('click', () => select(u.id));
        });
      }
      view.terrain.forEach((t, i) => append(get('features'), 'p', `T${i + 1}: ${TERRAIN_LABELS[t.kind]} · ${t.features.join(', ') || 'bez cech'}`, 'mb-1'));
      view.objectives.forEach((o) => append(get('features'), 'p', `Cel ${o.id}: ${o.controller === null ? 'bez kontroli' : `strona ${o.controller + 1}`}`, 'mb-1'));
    }
    const loader = createLoader(win.fetch.bind(win), update);
    input.addEventListener('input', loader.clear);
    get('form').addEventListener('submit', (event) => {
      event.preventDefault();
      const raw = input.value.trim(), url = new URL(win.location.href);
      url.searchParams.set('battle_id', raw); win.history.replaceState(null, '', url);
      loader.load(raw);
    });
    get('fit').addEventListener('click', redraw);
    canvas.addEventListener('click', (event) => {
      if (!view || !geometry) return;
      const rect = canvas.getBoundingClientRect(), u = pickUnit(view, geometry.tx, event.clientX - rect.left, event.clientY - rect.top);
      if (u) select(u.id);
    });
    if (win.ResizeObserver) new win.ResizeObserver(redraw).observe(canvas.parentElement);
    win.addEventListener('resize', redraw);
    function fromUrl() {
      input.value = new URL(win.location.href).searchParams.get('battle_id') || '';
      if (input.value) loader.load(input.value); else loader.clear();
    }
    win.addEventListener('popstate', fromUrl);
    fromUrl();
    return { loader, select, redraw };
  }
  const api = { parseCheckpoint, viewBounds, transform, sizeCanvas, pickUnit, draw, battleId, errorMessage, createLoader, mount };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.BattleCanvas = api;
  if (typeof document !== 'undefined') {
    const host = document.getElementById('battle-preview');
    if (host) mount(host, root);
  }
})(typeof window !== 'undefined' ? window : globalThis);
