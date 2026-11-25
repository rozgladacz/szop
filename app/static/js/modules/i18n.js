(function (scope) {
  'use strict';
  const language = scope.SZOP_LANGUAGE || 'pl';
  const messages = scope.SZOP_TRANSLATIONS || {};
  function t(text, values = {}) {
    return (messages[text] || text).replace(/\{(\w+)\}/g, (match, key) =>
      Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match);
  }
  const rules = scope.SZOP_ABILITY_TRANSLATIONS || [];
  const names = new Map(rules.flatMap(rule => [[rule.name.toLowerCase(), rule.display_name], [rule.slug.toLowerCase(), rule.display_name]]));
  names.set('wojownik', language === 'en' ? 'Warrior' : 'Wojownik');
  names.set('strzelec', language === 'en' ? 'Shooter' : 'Strzelec');
  names.set('pkt', language === 'en' ? 'pts' : 'pkt');
  names.set('zdolność', language === 'en' ? 'Ability' : 'Zdolność');
  names.set('brak', language === 'en' ? 'No' : 'Brak');
  const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const namePattern = new RegExp('(^|[^\\p{L}\\p{N}_])(' + [...names.keys()].sort((a,b) => b.length-a.length).map(escape).join('|') + ')(?=$|[^\\p{L}\\p{N}_])', 'giu');
  const parameterRules = rules.filter(rule => rule.description.includes('X')).map(rule => {
    const fragments = rule.description.trim().split('X');
    const pattern = escape(fragments[0]) + '(?<value>[^\\n]{1,160}?)'
      + fragments.slice(1).map((part, index) => escape(part) + (index < fragments.length - 2 ? '\\k<value>' : '')).join('');
    return { pattern: new RegExp(pattern, 'g'), description: rule.display_description };
  });
  function abilityLabel(value) {
    const text = String(value || '');
    if (language !== 'en') return text;
    const bracket = text.lastIndexOf('[');
    const close = text.lastIndexOf(']');
    if (bracket >= 0 && close > bracket && /^(?:\s*[×x]\s*\d+)?$/.test(text.slice(close + 1))) {
      return text.slice(0, bracket + 1) + abilityLabel(text.slice(bracket + 1, close)) + text.slice(close);
    }
    return text.replace(namePattern, (_, prefix, name) => prefix + names.get(name.toLowerCase()));
  }
  function abilityDescription(value) {
    let text = String(value || '');
    if (language !== 'en') return text;
    rules.slice().sort((a,b) => b.description.length-a.description.length).forEach(rule => {
      if (rule.description.trim()) text = text.split(rule.description.trim()).join(rule.display_description);
    });
    parameterRules.forEach(rule => {
      text = text.replace(rule.pattern, (_, value) => rule.description.replace(/2X/g, '2 × ' + abilityLabel(value)).replace(/X/g, abilityLabel(value)));
    });
    return text;
  }
  scope.SZOPI18n = {
    t,
    abilityLabel,
    abilityDescription,
    locale: language === 'en' ? 'en-GB' : 'pl-PL',
    beforeLanguageChange: [],
  };
  document.addEventListener('DOMContentLoaded', () => {
    const dirtyForms = new Set();
    const initialForms = new WeakMap();
    const snapshot = form => JSON.stringify([...new FormData(form)].map(([key, value]) =>
      [key, typeof value === 'string' ? value : [value.name, value.size, value.lastModified]]));
    // Capture after the pickers have normalised their hidden inputs.
    scope.setTimeout(() => {
      document.querySelectorAll('form:not([data-language-switch])').forEach(form => initialForms.set(form, snapshot(form)));
    }, 0);
    document.addEventListener('input', event => {
      const form = event.target.closest('form');
      if (form && !form.matches('[data-language-switch]')) dirtyForms.add(form);
    });
    document.addEventListener('submit', event => {
      if (!event.target.matches('[data-language-switch]')) dirtyForms.delete(event.target);
    });
    document.querySelectorAll('[data-language-switch]').forEach(form => {
      form.addEventListener('submit', async event => {
        event.preventDefault();
        const button = event.submitter;
        try {
          for (const finish of scope.SZOPI18n.beforeLanguageChange) await finish();
          const unsaved = [...document.querySelectorAll('form:not([data-language-switch])')].some(candidate =>
            !candidate.closest('[data-roster-editor]') && !candidate.hasAttribute('data-autosave')
            && (initialForms.has(candidate) ? snapshot(candidate) !== initialForms.get(candidate) : dirtyForms.has(candidate)));
          if (unsaved && !scope.confirm(t('Masz niezapisane zmiany. Opuścić formularz?'))) return;
          const input = document.createElement('input');
          input.type = 'hidden'; input.name = 'language'; input.value = button.value;
          form.appendChild(input);
          HTMLFormElement.prototype.submit.call(form);
        } catch (error) {
          scope.alert(t('Nie udało się zapisać zmian. Język nie został zmieniony.'));
        }
      });
    });
  });
}(window));
