"""Request-local presentation translations. Canonical game data stays Polish."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

SUPPORTED_LANGUAGES = ('pl', 'en')
COOKIE_NAME = 'szop_language'
CATALOG_DIR = Path(__file__).parent / 'locales'


def catalog(language: str) -> dict[str, str]:
    return CATALOGS.get(language, CATALOGS['pl'])


CATALOGS = {
    language: json.loads((CATALOG_DIR / f'{language}.json').read_text(encoding='utf-8'))
    for language in SUPPORTED_LANGUAGES
}


ABILITY_TRANSLATIONS = json.loads((CATALOG_DIR / 'abilities.en.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=2)
def javascript_catalog(language: str) -> str:
    from .services.ability_presentation import javascript_rules
    return ('window.SZOP_TRANSLATIONS=' + json.dumps(catalog(language)) + ';\n'
            'window.SZOP_ABILITY_TRANSLATIONS=' + json.dumps(javascript_rules(language)) + ';\n')


@lru_cache(maxsize=2)
def translation_version(language: str) -> str:
    return hashlib.sha256(javascript_catalog(language).encode()).hexdigest()[:12]


def browser_language(cookie: str | None, accept: str = '') -> str:
    if cookie in SUPPORTED_LANGUAGES:
        return cookie
    choices = []
    for position, entry in enumerate(accept.split(',')):
        parts = entry.strip().split(';')
        language = parts[0].lower().split('-')[0]
        try:
            quality = next((float(p.strip()[2:]) for p in parts[1:] if p.strip().startswith('q=')), 1.0)
        except ValueError:
            continue
        if language in SUPPORTED_LANGUAGES and 0 < quality <= 1:
            choices.append((-quality, position, language))
    return min(choices)[2] if choices else 'pl'


def language_for(request) -> str:
    return getattr(request.state, 'language', None) or browser_language(
        request.cookies.get(COOKIE_NAME), request.headers.get('accept-language', '')
    )


@lru_cache(maxsize=1)
def message_patterns():
    result = []
    for source, translated in CATALOGS['en'].items():
        placeholders = list(re.finditer(r'\{([a-z_]+)\}', source))
        if not placeholders:
            continue
        pattern = ''
        start = 0
        for match in placeholders:
            pattern += re.escape(source[start:match.start()]) + '(?P<' + match[1] + '>.*?)'
            start = match.end()
        pattern += re.escape(source[start:])
        result.append((re.compile('^' + pattern + '$', re.DOTALL), translated))
    return tuple(result)


def translate(text: str, language: str = 'pl', **values) -> str:
    result = catalog(language).get(text, text)
    if language == 'en' and result == text and not values:
        for pattern, translated in message_patterns():
            match = pattern.fullmatch(text)
            if match:
                return translated.format_map(match.groupdict())
    return result.format_map(values) if values else result


def safe_next(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return '/'
    if not value.startswith('/') or value.startswith('//') or parsed.netloc or parsed.scheme:
        return '/'
    if '\\' in value or any(ord(c) < 32 for c in value):
        return '/'
    return value


def set_language_cookie(response, language: str, *, secure: bool = False):
    response.set_cookie(COOKIE_NAME, language, max_age=365 * 86400,
                        httponly=True, secure=secure, samesite='lax')
    return response


class LanguageMiddleware:
    """ASGI middleware: do not buffer request bodies or streamed exports."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        from starlette.datastructures import MutableHeaders
        from starlette.requests import Request
        request = Request(scope)
        request.state.language = browser_language(request.cookies.get(COOKIE_NAME), request.headers.get('accept-language', ''))

        async def localized_send(message):
            if message['type'] == 'http.response.start':
                MutableHeaders(scope=message)['Content-Language'] = language_for(request)
            await send(message)

        await self.app(scope, receive, localized_send)
