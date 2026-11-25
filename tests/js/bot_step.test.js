'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { createBotStep, mount } = require('../../app/static/js/modules/bot_step.js');

const originTime = 1795572300000;
const uuid = '550e8400-e29b-41d4-a716-446655440000';
const checkpoint = { battleId: 7, version: 1, sequence: 8, activePlayer: 1, gameOver: false };
const success = (attempt, patch = {}) => ({
  schema_version: 1, attempt_id: attempt.id, battle_id: checkpoint.battleId,
  expected_sequence: attempt.command.expected_sequence, actual_sequence: 8,
  status: 'proposal_created', reason: null, proposal_id: 17, ...patch,
});
const pending = {
  id: 17, action: 'battle:action', status: 'pending',
  payload: { battle_id: checkpoint.battleId, expected_sequence: checkpoint.sequence },
};
const response = (status, data) => ({ status, ok: status >= 200 && status < 300, json: async () => data });
const turn = () => new Promise((resolve) => setImmediate(resolve));

function fixture({ state = new Map(), namespace = 'account-one', store, clock = originTime } = {}) {
  const calls = [], renders = [], queue = [];
  const c = createBotStep({
    namespace, now: () => clock, uuid: () => uuid, defer: turn,
    storage: store ?? { getItem: (key) => state.get(key) ?? null, setItem: (key, value) => state.set(key, value) },
    onChange: (view) => renders.push(view),
    async fetcher(path, options) {
      calls.push({ path, ...options });
      assert.equal(options.redirect, 'error');
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.cache, 'no-store');
      assert.ok(queue.length, `Unexpected ${options.method} ${path}`);
      return queue.shift()(path, options);
    },
  });
  const saved = () => JSON.parse(state.get(`szop:bot-step:v1:${namespace}:7`));
  const attemptReply = (status, patch) => () => response(status, success(saved(), patch));
  const methods = () => calls.map((c) => c.method);
  const view = () => renders.at(-1);
  return { c, calls, queue, saved, methods, view, attemptReply, state };
}

test('one explicit step, frozen payload before POST, separate consent and reload', async () => {
  const f = fixture();
  f.c.setView(checkpoint);
  assert.deepEqual(f.methods(), []);
  await f.c.start(0, '19');
  await f.c.start(1, '9007199254740992');
  assert.deepEqual(f.methods(), []);

  f.queue.push((_, req) => {
    assert.deepEqual(JSON.parse(req.body), f.saved().command);
    assert.equal(f.saved().id, `${originTime}-${uuid}`);
    assert.equal(req.headers['Content-Type'], 'application/json');
    assert.deepEqual(f.saved().command, {
      schema_version: 1, side: 1, kind: 'priority', seed: 19, protocol: 1, expected_sequence: 8,
    });
    return f.attemptReply(201)();
  }, () => response(200, pending));
  const one = f.c.start(1, '19');
  await f.c.start(1, '19');
  await one;
  assert.deepEqual(f.methods(), ['POST', 'GET']);
  assert.equal(f.calls[1].path, '/agent_proposals/17');
  assert.equal(f.view().proposalId, 17);
  assert.equal(f.view().canStart, false);

  const reload = fixture({state: f.state});
  reload.queue.push(reload.attemptReply(200), () => response(200, {
    ...pending, status: 'executed', result: {new_sequence: 10},
  }));
  await reload.c.setView(checkpoint);
  assert.deepEqual(reload.methods(), ['GET', 'GET']);
  assert.equal(reload.view().refresh, true);
  assert.equal(reload.view().canStart, false);

  const next = fixture({state: f.state});
  next.queue.push(next.attemptReply(200), () => response(200, {
    ...pending, status: 'executed', result: {new_sequence: 10},
  }));
  await next.c.setView({...checkpoint, sequence: 11});
  assert.equal(next.view().refresh, false);
  assert.equal(next.view().canStart, true);
  assert.deepEqual(next.methods(), ['GET', 'GET']);

  const other = fixture({state: f.state, namespace: 'next-generation'});
  await other.c.setView(checkpoint);
  assert.deepEqual(other.methods(), []);
  assert.equal(other.view().proposalId, null);
});

test('uncertain network, 503 and 404 recover by same ID and permit one explicit identical retry', async () => {
  for (const failure of [() => { throw new Error('timeout'); }, () => response(503), () => response(404)]) {
    const f = fixture();
    f.c.setView(checkpoint);
    f.queue.push(failure, () => response(404));
    await f.c.start(1, '-4');
    assert.deepEqual(f.methods(), ['POST', 'GET']);
    assert.equal(f.calls[0].path, f.calls[1].path);
    assert.equal(f.view().canRetry, true);
    f.queue.push(f.attemptReply(200), () => response(200, {...pending, status: 'rejected'}));
    await f.c.retry();
    assert.deepEqual(f.methods(), ['POST', 'GET', 'POST', 'GET']);
    assert.equal(f.calls[2].path, f.calls[0].path);
    assert.equal(f.calls[2].body, f.calls[0].body);
    assert.equal(f.view().canStart, true);
    assert.match(f.view().message, /odrzucona/);
  }
});

test('expired POST still reads the saved result and never retries automatically', async () => {
  const f = fixture();
  f.c.setView(checkpoint);
  f.queue.push(() => response(410), f.attemptReply(200), () => response(200, pending));
  await f.c.start(1, '19');
  assert.deepEqual(f.methods(), ['POST', 'GET', 'GET']);
  assert.equal(f.view().canRetry, false);
  const expired = fixture({state: f.state, clock: originTime + 86400000});
  expired.queue.push(() => response(404));
  await expired.c.setView(checkpoint);
  assert.deepEqual(expired.methods(), ['GET']);
  assert.equal(expired.view().canRetry, false);
});

test('stale attempts wait for a fresh checkpoint and never replay intent', async () => {
  const f = fixture();
  f.c.setView(checkpoint);
  const stale = { status: 'stale', reason: 'head_changed', proposal_id: null, actual_sequence: 9 };
  f.queue.push(f.attemptReply(201, stale));
  await f.c.start(1, '19');
  await f.c.start(1, '19');
  assert.equal(f.view().refresh, true);
  assert.deepEqual(f.methods(), ['POST']);
  f.queue.push(f.attemptReply(200, stale));
  await f.c.setView({...checkpoint, sequence: 10});
  assert.equal(f.view().refresh, false);
  assert.equal(f.view().canStart, true);
  assert.deepEqual(f.methods(), ['POST', 'GET']);
});

test('cancellation before POST, cancellation after POST, and deferred responses across views', async () => {
  const f = fixture();
  f.c.setView(checkpoint);
  const scheduled = f.c.start(1, '19');
  f.c.cancel();
  await scheduled;
  assert.deepEqual(f.methods(), []);
  assert.equal(f.state.size, 0);

  let resolveOld;
  f.queue.push(() => new Promise((r) => { resolveOld = r; }), () => response(404));
  const sent = f.c.start(1, '19');
  await turn();
  const reconciliation = f.c.cancel();
  assert.match(f.view().message, /Przerwano oczekiwanie.*mógł zapisać/);
  await reconciliation;
  assert.ok(f.calls[0].signal.aborted);
  assert.deepEqual(f.methods(), ['POST', 'GET']);
  assert.equal(f.view().canRetry, true);
  f.c.setView({...checkpoint, battleId: 9});
  resolveOld(f.attemptReply(201)());
  await sent;
  assert.equal(f.view().view.battleId, 9);
  assert.equal(f.view().proposalId, null);
  assert.deepEqual(f.methods(), ['POST', 'GET']);
});

test('storage failure and unsupported views issue no POST', async () => {
  const f = fixture({store: {
    getItem: () => null,
    setItem: () => { throw new Error('denied'); },
  }});
  for (const view of [{...checkpoint, version: 3}, {...checkpoint, gameOver: true}]) {
    f.c.setView(view);
    await f.c.start(1, '19');
    assert.equal(f.view().canStart, false);
  }
  f.c.setView(checkpoint);
  await f.c.start(1, '19');
  assert.deepEqual(f.methods(), []);
  assert.match(f.view().message, /zapis lokalny/);
});

test('form submission works without a click listener and exposes a keyboard status', async () => {
  const elements = new Map();
  const attrs = new Map();
  let focused = null;
  const doc = { getElementById(id) {
    if (!elements.has(id)) {
      elements.set(id, Object.assign(new EventTarget(), {
        value: '', focus() { focused = id; },
        setAttribute(name, value) { attrs.set(name, value); }, removeAttribute() {},
      }));
    }
    return elements.get(id);
  } };
  const get = (name) => doc.getElementById(`bot-step-${name}`);
  const storage = new Map(), sent = [];
  const win = Object.assign(new EventTarget(), {
    localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    crypto: { randomUUID: () => uuid },
    async fetch(_, options) { sent.push(options.method); return response(403); },
  });
  mount({ ownerDocument: doc, dataset: {enabled: '1', namespace: 'owner'} }, win);
  const event = Object.assign(new Event('szop:checkpoint'), { detail: checkpoint });
  doc.getElementById('battle-preview').dispatchEvent(event);
  const submit = new Event('submit', { cancelable: true });
  get('side').value = '1';
  get('seed').value = '5';
  assert.equal(get('form').dispatchEvent(submit), false);
  assert.equal(focused, 'bot-step-status');
  assert.equal(attrs.get('aria-busy'), 'true');
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(sent, ['POST']);
  assert.equal(attrs.get('aria-busy'), 'false');
});
