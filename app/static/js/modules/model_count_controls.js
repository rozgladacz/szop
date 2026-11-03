// Delegacja obsługuje także wiersze modeli/proxy dodawane po otwarciu panelu.
(function () {
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-model-count-step]');
    if (!button || button.disabled) return;
    const control = button.closest('[data-model-count-control]');
    const input = control && control.querySelector('input[type="number"]');
    if (!input || input.disabled || input.readOnly) return;
    event.preventDefault();
    const previous = input.value;
    if (!Number.isFinite(input.valueAsNumber)) input.value = input.min || '0';
    input.stepUp(Number(button.getAttribute('data-model-count-step')));
    if (input.value !== previous) {
      const eventType = control.getAttribute('data-model-count-event') === 'input' ? 'input' : 'change';
      input.dispatchEvent(new Event(eventType, { bubbles: true }));
    }
  });
}());
