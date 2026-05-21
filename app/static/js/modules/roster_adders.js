(function initSZOPRosterAddersModule(globalScope) {
// ============================================================
// SECTION: ROSTER ADDERS
// initRosterAdders — przyciski dodawania oddziałów do rozpiski
// ============================================================
function initRosterAdders(root) {
  if (!root) {
    return;
  }
  const registeredForms = new WeakSet();

  function registerForm(form) {
    if (!form || registeredForms.has(form)) {
      return;
    }
    registeredForms.add(form);
    let isSubmitting = false;

    const handleSubmit = async (event) => {
      event.preventDefault();
      if (isSubmitting) {
        return;
      }
      isSubmitting = true;
      const cleanup = () => {
        isSubmitting = false;
      };
      const fallback = () => {
        form.removeEventListener('submit', handleSubmit);
        cleanup();
        form.submit();
      };

      const action = form.getAttribute('action');
      if (!action) {
        fallback();
        return;
      }

      const payload = new FormData(form);

      try {
        const response = await fetch(action, {
          method: 'POST',
          body: payload,
          headers: { Accept: 'application/json' },
          credentials: 'same-origin',
        });
        const contentType = (response.headers.get('content-type') || '').toLowerCase();
        if (!response.ok || !contentType.includes('application/json')) {
          fallback();
          return;
        }
        let data;
        try {
          data = await response.json();
        } catch (err) {
          fallback();
          return;
        }
        if (!data || typeof data !== 'object' || !data.roster_item || !data.unit) {
          fallback();
          return;
        }
        cleanup();
        root.dispatchEvent(
          new CustomEvent('roster:add-unit-success', { detail: { payload: data, form } }),
        );
      } catch (error) {
        console.error('Nie udało się dodać oddziału', error);
        fallback();
      } finally {
        if (isSubmitting) {
          cleanup();
        }
      }
    };

    form.addEventListener('submit', handleSubmit);
  }

  root.querySelectorAll('[data-roster-add-trigger]').forEach((trigger) => {
    const form = trigger.closest('form');
    if (!form) {
      return;
    }
    registerForm(form);
    const submitForm = () => {
      if (typeof form.requestSubmit === 'function') {
        form.requestSubmit();
      } else {
        form.submit();
      }
    };
    trigger.addEventListener('click', (event) => {
      event.preventDefault();
      submitForm();
    });
    trigger.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        submitForm();
      }
    });
  });
}

  const api = {
    initRosterAdders: initRosterAdders,
  };
  globalScope.SZOPRosterAdders = api;
  globalScope.initRosterAdders = initRosterAdders;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPRosterAdders = api;
    globalThis.initRosterAdders = initRosterAdders;
  }
}(typeof window !== 'undefined' ? window : globalThis));
