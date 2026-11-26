import re

from fastapi.templating import Jinja2Templates as BaseTemplates
from jinja2 import pass_context
from jinja2.ext import Extension

from .config import APP_VERSION
from .i18n import catalog, language_for, translate, translation_version
from .services.ability_presentation import (
    ability_description,
    ability_label,
    localize_spells,
    present_data,
    spell_texts,
)


class StaticTranslations(Extension):
    """Translate source literals before compilation, never rendered user values.

    Mask Jinja first so tags split across expressions remain whole HTML tags.
    """
    def preprocess(self, source, name, filename=None):
        import json
        expressions = []
        def mask(match):
            expressions.append(match[0])
            return chr(0xE000) + str(len(expressions) - 1) + chr(0xE001)
        masked = re.sub(r'({{.*?}}|{%.*?%}|{#.*?#})', mask, source, flags=re.DOTALL)
        marker = r'(' + chr(0xE000) + r'\d+' + chr(0xE001) + r')'

        def literal(text):
            stripped = text.strip()
            if stripped not in catalog('en'):
                return text
            start = len(text) - len(text.lstrip())
            return text[:start] + '{{ t(' + json.dumps(stripped, ensure_ascii=False) + ') }}' + text[start + len(stripped):]

        def fragments(text):
            return ''.join(piece if piece.startswith(chr(0xE000)) else literal(piece)
                           for piece in re.split(marker, text))

        skip = False
        output = []
        for part in re.split(r'(<[^>]+>)', masked):
            if part.startswith('<'):
                if re.match(r'<(?:script|style)\b', part, re.IGNORECASE):
                    skip = True
                if re.match(r'</(?:script|style)\b', part, re.IGNORECASE):
                    skip = False
                part = re.sub(r'(\b(?:title|placeholder|aria-label)="|data-placeholder=")([^"<>]*)(")',
                              lambda match: match[1] + fragments(match[2]) + match[3], part)
                output.append(part)
            else:
                output.append(part if skip else fragments(part))
        result = ''.join(output)
        return re.sub(chr(0xE000) + r'(\d+)' + chr(0xE001),
                      lambda match: expressions[int(match[1])], result)


@pass_context
def template_translate(context, text, **values):
    return translate(text, language_for(context['request']), **values)


def locale_context(request):
    language = language_for(request)
    return {'language': language, 'locale': 'en-GB' if language == 'en' else 'pl-PL',
            'translation_version': translation_version(language)}


@pass_context
def template_ability(context, text):
    return ability_label(str(text or ''), language_for(context['request']))


@pass_context
def template_description(context, text):
    return ability_description(str(text or ''), language_for(context['request']))


@pass_context
def template_spell(context, spell):
    base, _ = spell_texts(spell.base_display_label, spell.description or '', spell.kind,
                         spell.ability_value, language_for(context['request']))
    custom = spell.normalized_custom_name
    return f'{custom} [{base}]' if custom and base else custom or base


@pass_context
def template_spell_description(context, spell):
    return spell_texts(spell.base_display_label, spell.description or '', spell.kind,
                       spell.ability_value, language_for(context['request']))[1]


@pass_context
def spell_entry_label(context, spell):
    return localize_spells([spell], language_for(context['request']))[0].get('label', '')


@pass_context
def spell_entry_description(context, spell):
    return localize_spells([spell], language_for(context['request']))[0].get('description', '')


class Jinja2Templates(BaseTemplates):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context_processors.append(locale_context)
        self.env.globals['app_version'] = APP_VERSION
        self.env.globals['t'] = template_translate
        self.env.globals['spell_display'] = template_spell
        self.env.globals['spell_description'] = template_spell_description
        self.env.globals['spell_entry_label'] = spell_entry_label
        self.env.globals['spell_entry_description'] = spell_entry_description
        self.env.filters['ability'] = template_ability
        self.env.filters['ability_description'] = template_description
        self.env.add_extension(StaticTranslations)

    def TemplateResponse(self, name, context, *args, **kwargs):
        context = dict(context)
        language = language_for(context['request'])
        context = present_data(context, language)
        for key in ('error', 'message', 'create_error'):
            if isinstance(context.get(key), str):
                context[key] = translate(context[key], language)
        return super().TemplateResponse(context['request'], name, context, *args, **kwargs)
