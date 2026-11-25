"""Localise rule presentation without modifying canonical payloads or ORM objects."""
from __future__ import annotations

import re
from functools import lru_cache

from ..data import abilities
from ..i18n import ABILITY_TRANSLATIONS


@lru_cache(maxsize=1)
def label_dictionary():
    names = {d.name: ABILITY_TRANSLATIONS[d.slug]['name'] for d in abilities.all_definitions()}
    names.update({d.slug: ABILITY_TRANSLATIONS[d.slug]['name'] for d in abilities.all_definitions()})
    names.update({'Wojownik': 'Warrior', 'Strzelec': 'Shooter', 'Wręcz': 'Melee', 'pkt': 'pts', 'Zdolność': 'Ability', 'Brak': 'No'})
    return {name.casefold(): translation for name, translation in names.items()}


@lru_cache(maxsize=4096)
def ability_label(text: str, language: str = 'pl') -> str:
    if language != 'en' or not text:
        return text
    # Custom names are kept verbatim; only their bracketed system rule changes.
    bracket = re.match(r'^(.*\[)([^\[\]]+)(\](?:\s*[×x]\s*\d+)?)$', text)
    if bracket:
        return bracket[1] + ability_label(bracket[2], language) + bracket[3]
    if text.startswith('"') and '" ' in text[1:]:
        prefix, rule = text[1:].split('" ', 1)
        return '"' + prefix + '" ' + ability_label(rule, language)
    names = label_dictionary()
    pattern = r'(?<!\w)(' + '|'.join(re.escape(k) for k in sorted(names, key=len, reverse=True)) + r')(?!\w)'
    return re.sub(pattern, lambda match: names[match[0].casefold()], text, flags=re.IGNORECASE)


@lru_cache(maxsize=4096)
def ability_description(text: str, language: str = 'pl') -> str:
    if language != 'en' or not text:
        return text
    for definition in sorted(abilities.all_definitions(), key=lambda d: len(d.description), reverse=True):
        if definition.description:
            text = text.replace(definition.description.strip(), ABILITY_TRANSLATIONS[definition.slug]['description'])
    for pattern, description in parameter_descriptions():
        text = pattern.sub(lambda match, description=description: description.replace('2X', '2 × ' + ability_label(match['value'], language)).replace('X', ability_label(match['value'], language)), text)
    return text


@lru_cache(maxsize=1)
def parameter_descriptions():
    result = []
    for definition in abilities.all_definitions():
        if 'X' not in definition.description:
            continue
        fragments = definition.description.strip().split('X')
        pattern = re.escape(fragments[0]) + r'(?P<value>[^\n]{1,160}?)'
        pattern += ''.join(re.escape(part) + (r'(?P=value)' if index < len(fragments) - 2 else '')
                           for index, part in enumerate(fragments[1:]))
        result.append((re.compile(pattern), ABILITY_TRANSLATIONS[definition.slug]['description']))
    return tuple(result)


def present_data(value, language: str):
    """Add display fields to dictionaries; never change labels used for saving."""
    if language == 'pl':
        return value
    if isinstance(value, list):
        return [present_data(item, language) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: present_data(item, language) for key, item in value.items()}
    slug = str(value.get('slug') or '')
    base_slug = slug
    if slug.startswith('aura_'):
        base_slug = 'aura'
    elif slug.endswith('_mistrzostwo'):
        base_slug = slug[:-12]
    definition = abilities.find_definition(base_slug)
    if definition:
        label = value.get('display_label') or value.get('base_label') or value.get('label') or value.get('display_name') or definition.display_name()
        result['display_label'] = ability_label(str(label), language)
        raw_value = value.get('value')
        if raw_value is not None:
            canonical = abilities.combined_description(definition, str(raw_value))
            extra = str(value.get('description') or '')
            if extra.startswith(canonical):
                extra = extra[len(canonical):].strip()
            result['display_description'] = abilities.combined_description(definition, str(raw_value), extra, language)
        else:
            result['display_description'] = ability_description(value.get('description') or definition.description, language)
        for choice in result.get('value_choices') or []:
            if isinstance(choice, dict):
                choice['display_label'] = ability_label(str(choice.get('label') or choice.get('value') or ''), language)
                choice['display_description'] = ability_description(choice.get('description') or '', language)
    return result


def javascript_rules(language: str):
    return [{
        'slug': d.slug, 'name': d.name, 'description': d.description,
        'display_name': abilities.find_definition(d.slug, language).name,
        'display_description': abilities.find_definition(d.slug, language).description,
    } for d in abilities.all_definitions()]


def export_entries(entries, language: str):
    result = []
    for entry in entries:
        item = dict(entry)
        for key in ('passive_labels', 'active_labels', 'aura_labels'):
            item[key] = [ability_label(label, language) for label in entry.get(key, [])]
        item['weapon_details'] = []
        for original in entry.get('weapon_details', []):
            weapon = dict(original)
            weapon['traits'] = ability_label(original.get('traits') or '', language)
            if language == 'en' and weapon.get('range') == 'Wręcz':
                weapon['range'] = 'Melee'
            item['weapon_details'].append(weapon)
        result.append(item)
    return result


def spell_texts(base_label: str, description: str, kind: str, value, language: str):
    """Rebuild generated spell text without fetching an Ability or changing names."""
    if language != 'en':
        return base_label, description
    if kind == 'weapon':
        from ..i18n import translate
        label = ability_label(base_label, language)
        if label.startswith('trafienie'):
            label = translate('Trafienie z broni', language) + label[len('trafienie'):]
        label = re.sub(r'^(\d+) trafienia\b', lambda match: translate('{count} trafienia', language, count=match[1]), label)
        # Translate only the generated stats; the prefix and suffix are user text.
        stats = re.fullmatch(r'(?P<prefix>(?:.* \| )?)Zasięg: (?P<range>[^|]+) \| Ataki: (?P<attacks>\d+) \| AP: (?P<ap>-?\d+)(?P<suffix>.*)', description, re.DOTALL)
        if stats:
            suffix = stats['suffix']
            traits = base_label.partition(f" AP{stats['ap']}")[2].strip()
            trait_part = ' | Cechy: ' + traits
            if traits and (suffix == trait_part or suffix.startswith(trait_part + ' | ')):
                suffix = ' | ' + translate('Cechy:', language) + ' ' + ability_label(traits, language) + suffix[len(trait_part):]
            description = (stats['prefix'] + translate('Zasięg:', language) + ' ' + ability_label(stats['range'], language)
                           + ' | ' + translate('Ataki:', language) + ' ' + stats['attacks']
                           + ' | AP: ' + stats['ap'] + suffix)
        return label, description
    name = base_label.split(':', 1)[0].split('(', 1)[0].strip()
    definition = abilities.find_definition(abilities.slug_for_name(name) or '')
    if definition:
        return (abilities.display_with_value(definition, value, language),
                abilities.description_with_value(definition, value, language))
    return base_label, description


def localize_spells(entries, language: str):
    if language != 'en':
        return [dict(entry) for entry in entries]
    result = []
    for entry in entries:
        spell = dict(entry)
        if 'base_label' in entry:
            base, description = spell_texts(entry['base_label'], entry.get('description') or '',
                                           entry.get('kind') or '', entry.get('value'), language)
            custom = entry.get('custom_name') or ''
            spell['label'] = f'"{custom}" {base}' if custom else base
            spell['description'] = description
        elif entry.get('kind') != 'weapon':
            spell['label'] = ability_label(entry.get('label') or '', language)
        result.append(spell)
    return result
