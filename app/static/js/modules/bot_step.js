/* One owner-requested proposal. The existing proposals panel handles consent. */
(function (root) {
  'use strict';

  const ID = /^[0-9]{13}-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  const RETRY_MS = 24 * 60 * 60 * 1000;
  const HTTP_MESSAGES = {
    401: 'Zaloguj się ponownie, aby sprawdzić próbę.',
    403: 'Serwer odrzucił adres tej strony. Otwórz podgląd pod skonfigurowanym adresem aplikacji.',
    409: 'Identyfikator próby jest już związany z innym poleceniem.',
    413: 'Polecenie przekracza dozwolony rozmiar.',
    415: 'Serwer odrzucił format polecenia.',
    422: 'Serwer odrzucił polecenie. Sprawdź dane i zegar urządzenia.',
  };
  const NO_PROPOSAL = {
    unsupported_protocol: 'Bot Priority obsługuje tylko bitwy v1.',
    checkpoint_unavailable: 'Brakuje zgodnego checkpointu. Odśwież podgląd.',
    unsupported_context: 'Ta sytuacja jest poza zakresem pojedynczego kroku Priority.',
    no_candidate: 'Bot nie znalazł propozycji dla tego checkpointu.',
    unsupported_action: 'Wybrana akcja jest poza zakresem pojedynczego kroku Priority.',
    invalid_action: 'Serwer odrzucił akcję z tego checkpointu.',
  };

  function positiveInteger(value) {
    return Number.isSafeInteger(value) && value > 0;
  }

  function commandFor(view, side, rawSeed) {
    const seed = Number(rawSeed);
    if (!view || view.version !== 1 || view.gameOver || side !== view.activePlayer ||
        !/^-?[0-9]+$/.test(rawSeed) || !Number.isSafeInteger(seed)) return null;
    return { schema_version: 1, side, kind: 'priority', seed, protocol: 1, expected_sequence: view.sequence };
  }

  function storedAttempt(value) {
    if (value === null) return null;
    const { id, command } = JSON.parse(value);
    if (!ID.test(id) || !command || ![0, 1].includes(command.side) ||
        command.schema_version !== 1 || command.protocol !== 1 || command.kind !== 'priority' ||
        Object.keys(command).length !== 6 || !Number.isSafeInteger(command.seed) ||
        !Number.isSafeInteger(command.expected_sequence) || command.expected_sequence < 0) {
      throw new Error('Invalid attempt');
    }
    return { id, command };
  }

  function validResult(value, battleId, ref) {
    if (!value || value.schema_version !== 1 || value.battle_id !== battleId ||
        value.attempt_id !== ref.id || value.expected_sequence !== ref.command.expected_sequence) return false;
    if (value.status === 'proposal_created') {
      return positiveInteger(value.proposal_id) && value.actual_sequence === value.expected_sequence &&
        value.reason === null;
    }
    if (value.proposal_id !== null) return false;
    if (value.status === 'stale') {
      return value.reason === 'head_changed' && Number.isSafeInteger(value.actual_sequence) &&
        value.actual_sequence >= 0 && value.actual_sequence !== value.expected_sequence;
    }
    return value.status === 'no_proposal' && Object.hasOwn(NO_PROPOSAL, value.reason);
  }

  function createBotStep({ fetcher, storage, namespace, onChange, uuid, now = Date.now,
                           defer = () => new Promise((resolve) => setTimeout(resolve, 0)) }) {
    let view = null;
    let attempt = null;
    let result = null;
    let proposal = null;
    let operation = null;
    let mode = 'idle';
    let message = '';

    function storageKey() { return `szop:bot-step:v1:${namespace}:${view.battleId}`; }
    function expired(ref) { return now() >= Number(ref.id.slice(0, 13)) + RETRY_MS; }
    function needsRefresh() {
      if (!view || !result) return false;
      if (result.status === 'stale') {
        return view.sequence < result.actual_sequence || view.sequence === result.expected_sequence;
      }
      if (proposal?.status === 'executed' || proposal?.status === 'stale') {
        const head = proposal.status === 'executed' ? proposal.result?.new_sequence : proposal.result?.actual_sequence;
        return !Number.isSafeInteger(head) || view.sequence < head || view.sequence === result.expected_sequence;
      }
      return false;
    }
    function canStart() {
      return Boolean(view && view.version === 1 && !view.gameOver && !operation &&
        (mode === 'idle' || mode === 'resolved') && !needsRefresh());
    }
    function canRetry() {
      return Boolean(view?.version === 1 && !view.gameOver && !operation && mode === 'uncertain' && attempt && !result &&
        !expired(attempt) && view.sequence === attempt.command.expected_sequence);
    }
    function publish() {
      onChange({
        view, message, busy: Boolean(operation), canStart: canStart(), canRetry: canRetry(),
        canCancel: ['queued', 'posting'].includes(operation?.phase),
        canCheck: Boolean(attempt && !operation && ['pending', 'uncertain', 'denied', 'expired'].includes(mode)),
        refresh: !operation && needsRefresh(),
        proposalId: result?.status === 'proposal_created' ? result.proposal_id : null,
      });
    }

    function stopOperation() {
      const current = operation;
      operation = null;
      current?.controller?.abort();
    }

    async function request(current, path, method, body) {
      const controller = new AbortController();
      current.controller = controller;
      const timer = setTimeout(() => controller.abort(), 10000);
      try {
        const headers = { Accept: 'application/json' };
        if (body) headers['Content-Type'] = 'application/json';
        const response = await fetcher(path, {
          method, headers, credentials: 'same-origin', redirect: 'error',
          cache: 'no-store', signal: controller.signal, body,
        });
        return { status: response.status, data: response.ok ? await response.json() : null };
      } catch (_) {
        return { status: 0, data: null };
      } finally {
        clearTimeout(timer);
      }
    }

    function attemptPath(ref) {
      return `/battles/${view.battleId}/bot-proposal-attempts/${ref.id}`;
    }

    function finish(current, nextMode, text) {
      if (operation !== current) return;
      operation = null;
      mode = nextMode;
      message = text;
      publish();
    }

    async function showResult(current, value, ref) {
      result = value;
      if (value.status === 'stale') {
        finish(current, 'resolved', 'Checkpoint się zmienił. Wczytaj aktualny stan przed następnym krokiem.');
        return;
      }
      if (value.status === 'no_proposal') {
        finish(current, 'resolved', NO_PROPOSAL[value.reason]);
        return;
      }
      current.phase = 'reading';
      message = 'Sprawdzanie statusu zapisanej propozycji…';
      publish();
      const reply = await request(current, `/agent_proposals/${value.proposal_id}`, 'GET');
      if (operation !== current) return;
      const card = reply.data;
      if (reply.status !== 200 || !card || card.id !== value.proposal_id ||
          card.action !== 'battle:action' || card.payload?.battle_id !== view.battleId ||
          card.payload.expected_sequence !== ref.command.expected_sequence) {
        finish(current, 'uncertain', `Zapisano propozycję #${value.proposal_id}, jej bieżący status jest niedostępny.`);
        return;
      }
      proposal = card;
      const statuses = {
        pending: 'Oczekuje na osobne zatwierdzenie lub odrzucenie.',
        executed: 'Akcja wykonana. Odśwież checkpoint przed następnym krokiem.',
        rejected: 'Propozycja odrzucona.',
        stale: 'Propozycja jest nieaktualna. Wczytaj bieżący checkpoint.',
      };
      finish(current, card.status === 'pending' ? 'pending' : Object.hasOwn(statuses, card.status) ? 'resolved' : 'uncertain',
        `Propozycja #${card.id}. ${statuses[card.status] || 'Sprawdź status w panelu propozycji.'}`);
    }

    async function reconcile(current, ref, { wasExpired = false, cancelled = false } = {}) {
      current.phase = 'reading';
      message = cancelled
        ? 'Przerwano oczekiwanie. Serwer mógł zapisać wynik, trwa jego sprawdzanie…'
        : 'Sprawdzanie zapisanego wyniku próby…';
      publish();
      const reply = await request(current, attemptPath(ref), 'GET');
      if (operation !== current) return;
      if (reply.status === 200 && validResult(reply.data, view.battleId, ref)) {
        return showResult(current, reply.data, ref);
      }
      if (reply.status === 401 || reply.status === 403) {
        finish(current, 'denied', HTTP_MESSAGES[reply.status]);
      } else if (wasExpired || expired(ref)) {
        if (reply.status === 404) {
          finish(current, 'resolved', 'Okno ponowienia minęło, a wynik jest niedostępny. Zapisane propozycje znajdziesz w panelu propozycji.');
        } else {
          finish(current, 'expired', 'Minęło okno ponowienia. Zapisany wynik można jeszcze sprawdzić.');
        }
      } else {
        finish(current, 'uncertain', reply.status === 404
          ? 'Brak wyniku. Zapis może jeszcze trwać lub ta strona jest niedostępna dla konta. Sprawdź wynik lub ponów tę samą próbę.'
          : 'Wynik pozostaje niepewny. Sprawdź go przed wysłaniem kolejnego polecenia.');
      }
    }

    function check(cancelled = false) {
      if (!view || !attempt || operation) return;
      operation = { phase: 'reading' };
      return reconcile(operation, attempt, { cancelled });
    }

    async function post(ref, save) {
      const current = { phase: 'queued' };
      operation = current;
      message = 'Przygotowywanie żądania…';
      publish();
      await defer();
      if (operation !== current) return;
      if (save) {
        try {
          const latest = storedAttempt(storage.getItem(storageKey()));
          if (latest && latest.id !== attempt?.id) {
            attempt = latest;
            result = proposal = null;
            return reconcile(current, latest);
          }
          storage.setItem(storageKey(), JSON.stringify(ref));
        } catch (_) {
          finish(current, 'storage', 'Zapis próby w przeglądarce jest niedostępny. Włącz zapis lokalny i odśwież podgląd.');
          return;
        }
      }
      attempt = ref;
      result = proposal = null;
      current.phase = 'posting';
      message = 'Serwer przygotowuje jedną propozycję…';
      publish();
      const reply = await request(current, attemptPath(ref), 'POST', JSON.stringify(ref.command));
      if (operation !== current) return;
      if ([200, 201].includes(reply.status) && validResult(reply.data, view.battleId, ref)) {
        return showResult(current, reply.data, ref);
      }
      if (reply.status === 404) return reconcile(current, ref);
      if (Object.hasOwn(HTTP_MESSAGES, reply.status)) {
        finish(current, 'denied', HTTP_MESSAGES[reply.status]);
        return;
      }
      return reconcile(current, ref, { wasExpired: reply.status === 410 });
    }

    function setView(next) {
      stopOperation();
      view = next;
      attempt = result = proposal = null;
      mode = 'idle';
      message = 'Wczytaj checkpoint istniejącej bitwy.';
      if (view) {
        message = view.version !== 1 ? NO_PROPOSAL.unsupported_protocol : view.gameOver
          ? 'Ta bitwa jest zakończona.' : `Aktywna strona checkpointu: ${view.activePlayer + 1}.`;
        try {
          attempt = storedAttempt(storage.getItem(storageKey()));
        } catch (_) {
          mode = 'storage';
          message = 'Nie można odczytać zapisanej próby. Sprawdź zapis lokalny przeglądarki.';
        }
      }
      if (attempt) return check();
      publish();
    }

    function start(side, rawSeed) {
      if (!canStart()) return;
      const command = commandFor(view, side, rawSeed);
      if (!command) {
        message = 'Wybierz aktywną stronę i podaj seed w zakresie bezpiecznych liczb całkowitych.';
        publish();
        return;
      }
      let id;
      try { id = `${now()}-${uuid()}`; } catch (_) { id = ''; }
      if (!ID.test(id)) {
        message = 'Przeglądarka nie może utworzyć identyfikatora próby. Użyj HTTPS lub lokalnego podglądu.';
        publish();
        return;
      }
      return post({ id, command }, true);
    }

    function cancel() {
      if (operation?.phase === 'queued') {
        stopOperation();
        message = 'Próba anulowana przed wysłaniem.';
        publish();
      } else if (operation?.phase === 'posting') {
        stopOperation();
        return check(true);
      }
    }

    function retry() {
      if (canRetry()) return post(attempt, false);
    }

    return { setView, start, cancel, check, retry };
  }

  function mount(host, win) {
    const doc = host.ownerDocument;
    const get = (name) => doc.getElementById(`bot-step-${name}`);
    const status = get('status'), side = get('side'), seed = get('seed'), submit = get('submit');
    if (host.dataset.enabled !== '1' || !host.dataset.namespace) {
      status.textContent = host.dataset.enabled !== '1'
        ? 'Play vs AI wymaga włączenia na tej instancji.'
        : 'Zaloguj się ponownie, aby zlecić krok bota.';
      return;
    }
    const controller = createBotStep({
      fetcher: win.fetch.bind(win),
      storage: {
        getItem: (key) => win.localStorage.getItem(key),
        setItem: (key, value) => win.localStorage.setItem(key, value),
      },
      namespace: host.dataset.namespace,
      uuid: () => win.crypto.randomUUID(),
      onChange(state) {
        status.textContent = state.message;
        side.disabled = seed.disabled = submit.disabled = !state.canStart;
        get('form').setAttribute('aria-busy', String(state.busy));
        get('cancel').hidden = !state.canCancel;
        get('check').hidden = !state.canCheck;
        get('retry').hidden = !state.canRetry;
        get('refresh').hidden = !state.refresh;
        const review = get('review');
        review.hidden = !state.proposalId;
        if (state.proposalId) review.href = `/#agent-proposal-${state.proposalId}`;
        else review.removeAttribute('href');
      },
    });
    doc.getElementById('battle-preview').addEventListener('szop:checkpoint', (event) => {
      if (!event.detail) side.value = '';
      controller.setView(event.detail);
    });
    get('form').addEventListener('submit', (event) => {
      event.preventDefault();
      controller.start(side.value === '' ? null : Number(side.value), seed.value);
      if (submit.disabled) status.focus();
    });
    get('cancel').addEventListener('click', controller.cancel);
    get('check').addEventListener('click', () => controller.check());
    get('retry').addEventListener('click', controller.retry);
    get('refresh').addEventListener('click', () => doc.getElementById('battle-preview-form').requestSubmit());
    win.addEventListener('pageshow', (event) => { if (event.persisted) win.location.reload(); });
    controller.setView(null);
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { createBotStep, mount };
  if (root.document) {
    const host = root.document.getElementById('bot-step');
    if (host) mount(host, root);
  }
})(typeof window !== 'undefined' ? window : globalThis);
