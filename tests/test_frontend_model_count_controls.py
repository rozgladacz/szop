import subprocess
from pathlib import Path

from tests.node_runtime import resolve_node_binary

ROOT = Path(__file__).resolve().parents[1]


def test_model_count_buttons_use_native_steps_and_existing_autosave_events():
    script = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
let click;
const document = {addEventListener: (name, handler) => { assert.equal(name, 'click'); click = handler; }};
vm.runInNewContext(fs.readFileSync('app/static/js/modules/model_count_controls.js', 'utf8'), {document, Event});
for (const eventType of ['change', 'input']) {
  const events = [], steps = [];
  const input = {value: '2', valueAsNumber: 2, min: '0',
    stepUp: step => {steps.push(step); input.value = String(Number(input.value) + step);},
    dispatchEvent: event => events.push(event)};
  const control = {querySelector: () => input, getAttribute: () => eventType};
  const button = {closest: () => control, getAttribute: () => '-1'};
  const event = {target: {closest: () => button}, preventDefault() {}};
  click(event);
  assert.deepEqual(steps, [-1]);
  assert.equal(input.value, '1');
  assert.equal(events[0].type, eventType);
  assert.equal(events[0].bubbles, true);
  button.getAttribute = () => '1';
  click(event);
  assert.equal(input.value, '2');
  assert.deepEqual(steps, [-1, 1]);
  input.disabled = true;
  click(event);
  assert.equal(steps.length, 2);
  input.disabled = false;
  input.readOnly = true;
  click(event);
  assert.equal(steps.length, 2);
  input.readOnly = false;
  input.stepUp = () => {}; // Browser keeps the value unchanged at min/max.
  click(event);
  assert.equal(events.length, 2, 'No autosave when native bounds keep the same value');
}
click({target: {closest: () => null}}); // Unrelated buttons are ignored.
'''
    result = subprocess.run([resolve_node_binary(), '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
