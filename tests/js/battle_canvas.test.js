/* Executed by pytest with production-codec v1/v2/v3 fixtures on stdin. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const api = require('../../app/static/js/modules/battle_canvas.js');
const fixtures = JSON.parse(fs.readFileSync(0, 'utf8'));
const clone = (v) => JSON.parse(JSON.stringify(v));
const flush = () => new Promise((resolve) => setImmediate(resolve));
const response = (payload) => ({ ok: true, status: 200, json: async () => payload });

// === SECTION: Wire projection, coordinates, radius, terrain, hit selection and DPR ===
const views = fixtures.map((p) => api.parseCheckpoint(p, 7));
assert.equal(views[3].phase, 'Przed akcją');
assert.equal(views[4].phase, 'Przed akcją');
for (const view of views) {
  assert.equal(view.units.length, 6);
  assert.equal(view.units.filter((u) => u.onBoard).length, 2);
  assert.equal(view.units[0].radius, 2);
  assert.deepEqual(view.units[0].statuses, ['Aktywowany', 'Wyczerpany']);
  assert.equal(view.terrain[0].kind, 'circle');
  assert.equal(view.terrain[1].kind, 'line');
  assert.deepEqual(view.terrain[2], {
    kind: 'polygon', features: ['Blokujacy'],
    vertices: [{ x: 18, y: 12 }, { x: 21, y: 12 }, { x: 21, y: 19 }, { x: 19, y: 17 }, { x: 18, y: 19 }]
  });
  assert.equal(view.objectives[0].controller, 1);
  assert.equal(view.objectives[1].controller, null);
  const bounds = api.viewBounds(view);
  assert.ok(bounds.maxX < 30); // The off-Front unit at 999,999 must not affect fitting.
  assert.ok(bounds.maxX > 21 && bounds.maxY > 19);
  assert.ok(bounds.minX < -6);
  const tx = api.transform(bounds, 600, 400), p = tx.point(view.units[0].position);
  assert.equal(api.pickUnit(view, tx, p.x, p.y).id, 1);
  assert.equal(api.pickUnit(view, tx, -1000, -1000), null);
  assert.ok(tx.point({ x: 0, y: 1 }).y < tx.point({ x: 0, y: 0 }).y);
}
const bad = clone(fixtures[0]); bad.state.fields.blobs.$tuple[0].fields.position.fields.x = null;
assert.throws(() => api.parseCheckpoint(bad, 7), /malformed/);
assert.throws(() => api.parseCheckpoint(fixtures[0], 8), /malformed/);
assert.throws(() => api.parseCheckpoint({ ...fixtures[0], version: 4 }, 7), /unsupported/);
const unknownTerrain = clone(fixtures[0]); unknownTerrain.state.fields.terrain.$tuple[0].$dataclass = 'Unknown';
assert.throws(() => api.parseCheckpoint(unknownTerrain, 7), /malformed/);
const shortPolygon = clone(fixtures[0]); shortPolygon.state.fields.terrain.$tuple[2].fields.vertices.$tuple.length = 2;
assert.throws(() => api.parseCheckpoint(shortPolygon, 7), /malformed/);
const empty = { ...views[0], units: [], terrain: [], objectives: [] };
assert.equal(api.viewBounds(empty).empty, true);
assert.equal(api.battleId('7'), 7);
for (const value of ['../7', '0', '-1', '1.2', '7e1', '<script>', '9007199254740992']) assert.equal(api.battleId(value), null);

const calls = [];
const context = new Proxy({}, { get: (_, name) => (...args) => calls.push([name, ...args]), set: () => true });
const canvas = { getContext: () => context, getBoundingClientRect: () => ({ width: 600, height: 400, left: 0, top: 0 }) };
let rendered = api.draw(canvas, views[0], 1, 2);
assert.equal(canvas.width, 1200); assert.equal(canvas.height, 800);
assert.deepEqual(calls[0], ['setTransform', 2, 0, 0, 2, 0, 0]);
const arcs = calls.filter((c) => c[0] === 'arc');
assert.equal(arcs.length, 3); // One terrain circle + two live Front units.
assert.equal(arcs[1][3], 2 * rendered.tx.scale);
assert.ok(calls.some((c) => c[0] === 'fillText' && c[1] === 'Cel 1'));
assert.ok(calls.some((c) => c[0] === 'lineTo'));
const polygonPath = views[0].terrain[2].vertices.map((v, i) => {
  const p = rendered.tx.point(v);
  return [i === 0 ? 'moveTo' : 'lineTo', p.x, p.y];
});
const firstClose = calls.findIndex(([name]) => name === 'closePath');
assert.deepEqual(calls.slice(firstClose - polygonPath.length, firstClose + 3), [
  ...polygonPath, ['closePath'], ['fill'], ['stroke']
]);
api.draw(canvas, null, null, 1);
assert.equal(canvas.width, 600);
api.draw(canvas, empty, null, 2);

// === SECTION: Request failures, clearing, GET-only and overlapping refreshes ===
async function requests() {
  for (const status of [401, 403, 404, 409, 500]) {
    const updates = [];
    const loader = api.createLoader(async (path, options) => {
      assert.equal(path, '/battles/7/state'); assert.equal(options.method, 'GET');
      assert.equal(options.credentials, 'same-origin'); assert.equal(options.cache, 'no-store');
      return { ok: false, status };
    }, (s) => updates.push(s));
    await loader.load('7');
    assert.deepEqual(updates.map((s) => s.status), ['idle', 'loading', 'error']);
    assert.equal(updates.at(-1).code, status); assert.equal(updates.at(-1).view, undefined);
    assert.equal(typeof api.errorMessage(status), 'string');
  }
  for (const [fetcher, code] of [
    [async () => { throw new TypeError('offline'); }, 'network'],
    [async () => response({}), 'unsupported'],
    [async () => response(bad), 'malformed'],
    [async () => ({ ok: true, json: async () => { throw new Error('html'); } }), 'malformed']
  ]) {
    const updates = [], loader = api.createLoader(fetcher, (s) => updates.push(s));
    await loader.load('7'); assert.equal(updates.at(-1).code, code);
  }
  const deferred = [], updates = [];
  const loader = api.createLoader((path, options) => new Promise((resolve) => deferred.push({ resolve, options })), (s) => updates.push(s));
  const first = loader.load('7'), second = loader.load('7');
  assert.equal(deferred[0].options.signal.aborted, true);
  deferred[1].resolve(response(fixtures[1])); await second;
  deferred[0].resolve(response(fixtures[0])); await first;
  assert.equal(updates.at(-1).view.version, 2);
  const third = loader.load('7'); loader.clear();
  deferred[2].resolve(response(fixtures[0])); await third;
  assert.equal(updates.at(-1).status, 'idle');
  const invalid = api.createLoader(() => { throw Error('must not fetch'); }, (s) => updates.push(s));
  await invalid.load('x'); assert.equal(updates.at(-1).code, 'invalid');
  // Race while response.json itself is still pending.
  let resolveJson;
  const slow = api.createLoader(async () => ({ ok: true, json: () => new Promise((resolve) => { resolveJson = resolve; }) }), (s) => updates.push(s));
  const pending = slow.load('7'); await flush(); slow.clear(); resolveJson(fixtures[0]); await pending;
  assert.equal(updates.at(-1).status, 'idle');
}

// === SECTION: Real mount execution with a tiny DOM, keyboard-equivalent buttons ===
class Element {
  constructor(tag, doc) { this.tagName = tag; this.ownerDocument = doc; this.children = []; this.events = {}; this.dataset = {}; this.attributes = {}; this.textContent = ''; }
  appendChild(el) { this.children.push(el); }
  replaceChildren() { this.children = []; this.textContent = ''; }
  addEventListener(name, fn) { this.events[name] = fn; }
  setAttribute(name, value) { this.attributes[name] = value; }
  querySelectorAll() { return this.children.flatMap((c) => [...(c.dataset.battleUnit ? [c] : []), ...c.querySelectorAll()]); }
  set innerHTML(_) { throw Error('Untrusted HTML is forbidden'); }
}
async function page() {
  const elements = {};
  const doc = { getElementById: (id) => elements[id], createElement: (tag) => new Element(tag, doc) };
  const host = new Element('section', doc);
  for (const suffix of ['canvas', 'id', 'message', 'summary', 'fit', 'front', 'off', 'features', 'bounds', 'details', 'form']) {
    const el = new Element(suffix, doc); elements[`battle-preview-${suffix}`] = el; host.appendChild(el);
  }
  const uiCanvas = elements['battle-preview-canvas'];
  uiCanvas.getContext = canvas.getContext; uiCanvas.getBoundingClientRect = canvas.getBoundingClientRect;
  uiCanvas.parentElement = host;
  let fetchCount = 0;
  const win = {
    fetch: async () => { fetchCount++; return response(fixtures[0]); }, devicePixelRatio: 2,
    location: { href: 'http://localhost/battle-preview?battle_id=7' },
    history: { replaceState: (_, __, url) => { win.location.href = String(url); } },
    addEventListener: () => {}, ResizeObserver: class { constructor(fn) { this.fn = fn; } observe() { this.fn(); } }
  };
  const mounted = api.mount(host, win); await flush();
  assert.equal(fetchCount, 1);
  assert.match(elements['battle-preview-summary'].textContent, /sequence_at 0/);
  const buttons = host.querySelectorAll();
  assert.equal(buttons.length, 6);
  assert.equal(buttons[0].type, 'button'); // Native Enter/Space activation, not canvas-only.
  buttons[0].events.click();
  assert.equal(buttons[0].attributes['aria-pressed'], 'true');
  assert.ok(elements['battle-preview-details'].children.some((el) => el.textContent.includes('<img src=x')));
  assert.ok(elements['battle-preview-features'].children.some((el) => el.textContent.includes('Trudny')));
  assert.ok(elements['battle-preview-features'].children.some((el) => el.textContent.includes('wielokąt · Blokujacy')));
  const p = api.transform(api.viewBounds(views[0]), 600, 400).point(views[0].units[1].position);
  uiCanvas.events.click({ clientX: p.x, clientY: p.y });
  assert.equal(buttons[1].attributes['aria-pressed'], 'true');
  elements['battle-preview-id'].events.input();
  assert.equal(elements['battle-preview-front'].children.length, 0);
  assert.equal(elements['battle-preview-summary'].hidden, true);
  assert.equal(elements['battle-preview-details'].textContent, 'Wybierz oddział na planszy lub z listy.');
  mounted.redraw(); assert.equal(fetchCount, 1);
  elements['battle-preview-id'].value = '8';
  await mounted.loader.load('8'); // Wrong battle ID fixture fails closed, never retains battle 7.
  assert.equal(elements['battle-preview-summary'].hidden, true);
  assert.equal(elements['battle-preview-front'].children.length, 0);
}
(async () => { await requests(); await page(); process.stdout.write(JSON.stringify({ passed: true })); })().catch((error) => { console.error(error); process.exitCode = 1; });
