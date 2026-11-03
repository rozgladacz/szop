import json
import subprocess
from pathlib import Path

import pytest

from tests.node_runtime import resolve_node_binary

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('save_result', ['ok', 'http_error', 'aborted'])
def test_models_hero_attachment_saves_composition_before_shared_attach(save_result):
    script = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const saveResult = SAVE_RESULT;
class Element {
  constructor(attrs = {}) {
    this.attrs = attrs; this.children = []; this.listeners = {}; this.style = {};
    this.classList = {add() {}, remove() {}, toggle() {}};
  }
  getAttribute(key) { return this.attrs[key] || ''; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  addEventListener(key, callback) { this.listeners[key] = callback; }
  appendChild(child) { this.children.push(child); }
  get childElementCount() { return this.children.length; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
const hero = new Element({'data-roster-unit-id': '5', 'data-is-hero': 'true',
  'data-parent-roster-unit-id': '8'});
const target = new Element({'data-roster-unit-id': '8', 'data-unit-custom-name': 'Squad <A>'});
const otherHero = new Element({'data-roster-unit-id': '9', 'data-is-hero': 'true'});
const toggle = new Element();
const passives = new Element();
const panel = new Element();
panel.querySelector = key => key === '[data-models-passives]' ? passives : null;
const editor = new Element();
const root = new Element();
root.dataset = {rosterId: '3'};
root.querySelector = key => ({'[data-roster-editor]': editor,
  '[data-roster-models-toggle]': toggle, '[data-roster-models-panel]': panel,
  '[data-roster-item].active': hero})[key] || null;
root.querySelectorAll = key => key === '[data-roster-item]' ? [hero, target, otherHero] : [];
const document = {readyState: 'complete', querySelector: () => root,
  createElement: () => new Element()};
const window = {location: {href: 'http://localhost/rosters/3'}, clearTimeout() {}, setTimeout};
const requests = [];
const fetch = async (url, options = {}) => {
  requests.push({url, options});
  if (url.endsWith('/collection-models')) return {ok: true, json: async () => ({
    composed: [{id: null, qty: 1, weapons: {}}], models: [],
    passive_items: [{slug: 'bohater', label: 'Bohater', default_count: 1,
      custom_name: 'Commander <A>', display_label: 'Commander <A> [Bohater]'}],
  })};
  if (url.endsWith('/update')) {
    if (saveResult === 'aborted') throw Object.assign(new Error('aborted'), {name: 'AbortError'});
    return {ok: saveResult === 'ok', status: 500, json: async () => ({})};
  }
  return {ok: true, json: async () => ({})};
};
const sandbox = {window, document, fetch, console, URL, FormData, AbortController, setTimeout};
vm.createContext(sandbox);
for (const file of ['text_parsing.js', 'roster_rendering.js', 'roster_collection_models.js']) {
  vm.runInContext(fs.readFileSync('app/static/js/modules/' + file, 'utf8'), sandbox);
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const walk = node => [node, ...node.children.flatMap(walk)];
(async () => {
  toggle.listeners.click({preventDefault() {}});
  await tick();
  const select = walk(passives).find(node => String(node.id).startsWith('hero-attach-'));
  assert.ok(select, 'Models mode must render the shared hero selector');
  assert.ok(walk(passives).some(node => node.textContent === 'Commander <A> [Bohater]'));
  assert.equal(select.value, '8');
  assert.equal(select.children.length, 2, 'Only non-hero targets are attachable');
  assert.equal(select.children[1].textContent, 'Squad <A>');
  for (const parent of ['8', '']) {
    requests.length = 0;
    select.value = parent;
    select.listeners.change();
    await tick(); await tick();
    assert.ok(requests[0].url.endsWith('/update'));
    assert.equal(requests[0].options.body.get('composed_models_json'),
      JSON.stringify([{id: null, weapons: {}, abilities: [], qty: 1}]));
    if (saveResult === 'ok') {
      assert.ok(requests[1].url.endsWith(parent ? '/attach' : '/detach'));
      if (parent) assert.equal(JSON.parse(requests[1].options.body).parent_roster_unit_id, 8);
      assert.ok(window.location.href.includes('selected=5'));
    } else {
      assert.equal(requests.length, 1, 'Failed saves must block attachment and detachment');
      assert.equal(select.disabled, false);
      assert.ok(walk(passives).some(node => String(node.textContent).includes('kompozycję')));
    }
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
'''.replace('SAVE_RESULT', json.dumps(save_result))
    result = subprocess.run([resolve_node_binary(), '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
