(function initSZOPTextParsingModule(globalScope) {
  const ARMY_RULE_OFF_PREFIX = globalScope.ARMY_RULE_OFF_PREFIX || '__army_off__';

// ============================================================
// SECTION: TEXT PARSING UTILS
// splitTraits, normalizeName, extractNumber, abilityIdentifier,
// passiveIdentifier, parseFlagString, normalizeRangeValue,
// stripOptionalFlagSuffix
// ============================================================
const ABILITY_NAME_MAX_LENGTH = 60;
const ABILITY_ALIASES = new Map([
  ['nieustepliwy', 'przygotowanie'],
]);

function splitTraits(text) {
  if (!text) {
    return [];
  }
  if (Array.isArray(text)) {
    return text;
  }
  return String(text)
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

function normalizeName(text) {
  if (text === undefined || text === null) {
    return '';
  }
  let value = String(text);
  try {
    value = value.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  } catch (err) {
    value = value
      .replace(/ą/g, 'a')
      .replace(/ć/g, 'c')
      .replace(/ę/g, 'e')
      .replace(/ł/g, 'l')
      .replace(/ń/g, 'n')
      .replace(/ó/g, 'o')
      .replace(/ś/g, 's')
      .replace(/ż/g, 'z')
      .replace(/ź/g, 'z');
  }
  value = value.replace(/[-_]/g, ' ');
  value = value.replace(/[!?]+$/g, '');
  value = value.replace(/\s+/g, ' ').trim();
  return value.toLowerCase();
}

function extractNumber(text) {
  if (text === undefined || text === null) {
    return 0;
  }
  const match = String(text).match(/[0-9]+(?:[.,][0-9]+)?/);
  if (!match) {
    return 0;
  }
  return Number(match[0].replace(',', '.'));
}

function abilityIdentifier(text) {
  if (text === undefined || text === null) {
    return '';
  }
  let base = String(text).trim();
  if (!base) {
    return '';
  }
  if (base.startsWith(ARMY_RULE_OFF_PREFIX)) {
    base = base.slice(ARMY_RULE_OFF_PREFIX.length).trim();
  }
  ['(', '=', ':'].forEach((separator) => {
    if (base.includes(separator)) {
      base = base.split(separator, 1)[0].trim();
    }
  });
  base = base.replace(/[“”]/g, '"');
  while (base.endsWith('?') || base.endsWith('!')) {
    base = base.slice(0, -1).trim();
  }
  const normalized = normalizeName(base);
  return ABILITY_ALIASES.get(normalized) || normalized;
}

function passiveIdentifier(text) {
  const ident = abilityIdentifier(text);
  if (ident) {
    return ident;
  }
  const norm = normalizeName(text);
  let trimmed = norm;
  while (trimmed.endsWith('?') || trimmed.endsWith('!')) {
    trimmed = trimmed.slice(0, -1).trim();
  }
  if (trimmed) {
    return trimmed;
  }
  return norm;
}

function parseFlagString(text) {
  if (!text) {
    return {};
  }
  const entries = String(text)
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
  const result = {};
  entries.forEach((entry) => {
    const separatorIndex = entry.indexOf('=');
    if (separatorIndex >= 0) {
      const key = entry.slice(0, separatorIndex).trim();
      const value = entry.slice(separatorIndex + 1).trim();
      if (key) {
        result[key] = value;
      }
    } else {
      result[entry] = true;
    }
  });
  return result;
}

function normalizeRangeValue(value) {
  if (value === undefined || value === null) {
    return 0;
  }
  if (typeof value === 'number') {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      return 0;
    }
    return Math.round(numeric);
  }
  const text = String(value).trim();
  if (!text) {
    return 0;
  }
  const lowered = text.toLowerCase();
  if (['wręcz', 'wrecz', 'melee', 'm'].includes(lowered)) {
    return 0;
  }
  const numeric = extractNumber(text);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return 0;
  }
  return Math.round(numeric);
}

function stripOptionalFlagSuffix(name) {
  let normalized = String(name || '').trim();
  while (normalized.endsWith('?') || normalized.endsWith('!')) {
    normalized = normalized.slice(0, -1).trim();
  }
  return normalized;
}

  const api = {
    ABILITY_NAME_MAX_LENGTH: ABILITY_NAME_MAX_LENGTH,
    splitTraits: splitTraits,
    normalizeName: normalizeName,
    extractNumber: extractNumber,
    abilityIdentifier: abilityIdentifier,
    passiveIdentifier: passiveIdentifier,
    parseFlagString: parseFlagString,
    normalizeRangeValue: normalizeRangeValue,
    stripOptionalFlagSuffix: stripOptionalFlagSuffix,
  };
  globalScope.SZOPTextParsing = api;
  globalScope.ABILITY_NAME_MAX_LENGTH = ABILITY_NAME_MAX_LENGTH;
  globalScope.splitTraits = splitTraits;
  globalScope.normalizeName = normalizeName;
  globalScope.extractNumber = extractNumber;
  globalScope.abilityIdentifier = abilityIdentifier;
  globalScope.passiveIdentifier = passiveIdentifier;
  globalScope.parseFlagString = parseFlagString;
  globalScope.normalizeRangeValue = normalizeRangeValue;
  globalScope.stripOptionalFlagSuffix = stripOptionalFlagSuffix;
  if (typeof globalThis !== 'undefined') {
    globalThis.SZOPTextParsing = api;
    globalThis.ABILITY_NAME_MAX_LENGTH = ABILITY_NAME_MAX_LENGTH;
    globalThis.splitTraits = splitTraits;
    globalThis.normalizeName = normalizeName;
    globalThis.extractNumber = extractNumber;
    globalThis.abilityIdentifier = abilityIdentifier;
    globalThis.passiveIdentifier = passiveIdentifier;
    globalThis.parseFlagString = parseFlagString;
    globalThis.normalizeRangeValue = normalizeRangeValue;
    globalThis.stripOptionalFlagSuffix = stripOptionalFlagSuffix;
  }
}(typeof window !== 'undefined' ? window : globalThis));
