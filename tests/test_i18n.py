import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app import main, models
from app.db import Base, get_db
from app.i18n import CATALOGS, browser_language, safe_next
from app.security import hash_password


@pytest.fixture
def client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(models.User(username='player', password_hash=hash_password('pass')))
        db.add(models.User(username='english', password_hash=hash_password('pass'), preferred_language='en'))
        db.commit()

    def override():
        with sessions() as db:
            yield db

    main.app.dependency_overrides[get_db] = override
    try:
        yield TestClient(main.app), sessions
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.parametrize('cookie,header,expected', [
    ('pl', 'en-GB', 'pl'), ('en', 'pl', 'en'),
    (None, 'fr, en-US;q=0.8, pl;q=0.2', 'en'),
    ('invalid', 'en;q=0,pl;q=.3', 'pl'),
    (None, 'en;q=oops,pl;q=0.1', 'pl'), (None, 'de', 'pl'),
])
def test_browser_language(cookie, header, expected):
    assert browser_language(cookie, header) == expected


@pytest.mark.parametrize('value', ['https://example.com', '//example.com', '/\\example.com', '/\nlocation'])
def test_external_redirect_rejected(value):
    assert safe_next(value) == '/'


def test_language_precedence_and_account_persistence(client):
    browser, sessions = client
    response = browser.get('/auth/login', headers={'accept-language': 'en-GB'})
    assert response.headers['content-language'] == 'en'
    assert '<html lang="en">' in response.text
    assert 'Army lists' in response.text
    browser.post('/language', data={'language': 'pl'})
    response = browser.get('/auth/login', headers={'accept-language': 'en'})
    assert response.headers['content-language'] == 'pl'
    browser.post('/auth/login', data={'username': 'english', 'password': 'pass'})
    assert browser.get('/downloads').headers['content-language'] == 'en'
    response = browser.post('/language', data={'language': 'pl', 'next': '/downloads'}, follow_redirects=False)
    assert response.status_code == 303
    with sessions() as db:
        assert db.query(models.User).filter_by(username='english').one().preferred_language == 'pl'
    browser.post('/auth/logout')
    assert browser.get('/auth/login').headers['content-language'] == 'pl'


def test_initial_login_adopts_browser_language(client):
    browser, sessions = client
    browser.post('/auth/login', data={'username': 'player', 'password': 'pass'}, headers={'accept-language': 'en'}, follow_redirects=False)
    with sessions() as db:
        assert db.query(models.User).filter_by(username='player').one().preferred_language == 'en'
    assert browser.post('/language', data={'language': 'de'}).status_code == 400


def test_downloads_list_only_direct_pdfs(client, tmp_path, monkeypatch):
    browser, _ = client
    folder = tmp_path / 'docs'
    folder.mkdir()
    for name in ['Zasady żółte.pdf', 'English.PDF', 'notes.md', 'rules.docx']:
        (folder / name).write_bytes(b'fixture')
    (folder / 'nested.pdf').mkdir()
    monkeypatch.setattr(main, 'STATIC_DIR', tmp_path)
    response = browser.get('/downloads', headers={'accept-language': 'en'})
    assert response.status_code == 200
    assert 'Downloads' in response.text
    assert 'English.PDF' in response.text and 'Zasady żółte.pdf' in response.text
    assert 'notes.md' not in response.text and 'rules.docx' not in response.text
    assert 'nested.pdf' not in response.text
    assert response.text.index('English.PDF') < response.text.index('Zasady żółte.pdf')
    for path in folder.glob('*'):
        if path.is_file():
            path.unlink()
    assert 'No files available to download.' in browser.get('/downloads', headers={'accept-language': 'en'}).text


def test_template_literals_do_not_translate_user_values(client):
    from starlette.requests import Request
    request = Request({'type': 'http', 'app': main.app, 'headers': [(b'accept-language', b'en')]})
    template = main.templates.env.from_string('<p>Armie</p><p>{{ name }}</p>')
    assert template.render(request=request, name='Armie') == '<p>Armies</p><p>Armie</p>'
    assert template.render(request=request, name='<script>') == '<p>Armies</p><p>&lt;script&gt;</p>'


def test_catalogues_and_all_templates_compile():
    assert CATALOGS['en'].keys() == CATALOGS['pl'].keys()
    for name in main.templates.env.list_templates():
        main.templates.env.get_template(name)


def test_language_migration_is_idempotent(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "old.db"}')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)'))
        connection.execute(text("INSERT INTO users VALUES (1, 'unchanged')"))
    monkeypatch.setattr(db_module, 'engine', engine)
    monkeypatch.setattr(db_module, 'DB_URL', str(engine.url))
    db_module._migrate_schema()
    db_module._migrate_schema()
    assert 'preferred_language' in {column['name'] for column in inspect(engine).get_columns('users')}
    with engine.connect() as connection:
        assert connection.execute(text('SELECT username, preferred_language FROM users')).one() == ('unchanged', None)
    engine.dispose()


def test_every_ability_has_english_text_and_preserves_canonical_definitions():
    from app.data.abilities import all_definitions, find_definition
    from app.i18n import ABILITY_TRANSLATIONS
    assert {d.slug for d in all_definitions()} == ABILITY_TRANSLATIONS.keys()
    for canonical in all_definitions():
        english = find_definition(canonical.slug, 'en')
        assert english.slug == canonical.slug
        assert english.description
        assert find_definition(canonical.slug).name == canonical.name
    assert 'w aktywacji' in find_definition('niestrudzony').description
    assert 'in an activation' in find_definition('niestrudzony', 'en').description


@pytest.mark.parametrize('slug,value,expected', [
    ('mag', '2', 'Caster(2)'),
    ('transport', '11', 'Transport(11)'),
    ('mistrzostwo', 'porazenie', 'Mastery(Shock)'),
    ('rozkaz', 'szybki', 'Command: Fast'),
    ('klatwa', 'mistrzostwo:porazenie', 'Curse: Mastery: Shock'),
    ('aura', 'mistrzostwo:porazenie|12', 'Aura(12"): Mastery: Shock'),
])
def test_parameterised_ability_presentation(slug, value, expected):
    from app.data.abilities import (
        description_with_value,
        display_with_value,
        find_definition,
    )
    definition = find_definition(slug)
    assert display_with_value(definition, value, 'en') == expected
    assert description_with_value(definition, value, 'en')
    assert find_definition(slug) is definition


def test_display_payload_does_not_change_saving_fields():
    from app.services.ability_presentation import ability_label, present_data
    entry = {'slug': 'mag', 'value': '2', 'label': 'Mag(2)', 'custom_name': 'Mag', 'ability_id': 42}
    english = present_data(entry, 'en')
    assert english['display_label'] == 'Caster(2)'
    assert {key: english[key] for key in entry} == entry
    assert 'display_label' not in entry
    assert ability_label('Mag [Mag(2)]', 'en') == 'Mag [Caster(2)]'


def test_localised_export_keeps_names_and_input_unchanged():
    from app.services.ability_presentation import export_entries
    entry = {'unit_name': 'Mag', 'custom_name': 'Szybki', 'passive_labels': ['Szybki'],
             'weapon_details': [{'name': 'Bohater', 'traits': 'Rozprysk(3)', 'range': 'Wręcz'}]}
    translated = export_entries([entry], 'en')[0]
    assert translated['unit_name'] == 'Mag' and translated['custom_name'] == 'Szybki'
    assert translated['passive_labels'] == ['Fast']
    assert translated['weapon_details'][0] == {'name': 'Bohater', 'traits': 'Blast(3)', 'range': 'Melee'}
    assert entry['weapon_details'][0]['traits'] == 'Rozprysk(3)'


def test_dynamic_html_attributes_and_battle_keys_stay_canonical(client):
    from starlette.requests import Request
    request = Request({'type': 'http', 'app': main.app, 'headers': [(b'accept-language', b'en')]})
    template = main.templates.env.from_string('<a href="/armies/{{ id }}">Wróć</a><span data-ability-toggle="{{ label }}">{{ label | ability }}</span>')
    rendered = template.render(request=request, id=1, label='Mag(2)')
    assert '>Back</a>' in rendered
    assert 'data-ability-toggle="Mag(2)"' in rendered
    assert '>Caster(2)</span>' in rendered


def test_english_workbook_headers_and_ability_names():
    from openpyxl import Workbook

    from app.routers.export_xlsx import _append_roster_sheet
    workbook = Workbook()
    _append_roster_sheet(workbook, [{'unit_name': 'Mag', 'count': 1, 'passive_labels': ['Fast']}], 12, language='en')
    assert workbook.active.title == 'Army list'
    assert workbook.active['A1'].value == 'Unit'
    assert workbook.active['A2'].value == 'Mag'
    assert workbook.active['G2'].value == 'Passive: Fast'


def test_english_strategic_cards_use_stable_slugs():
    from app.data.strategic_cards import STRATEGIC_SUPPORTS, STRATEGIC_TASKS
    from app.i18n import translate
    for card in STRATEGIC_TASKS + STRATEGIC_SUPPORTS:
        assert translate(card.text, 'en') != card.text
        assert translate(card.text, 'pl') == card.text


def test_parameter_description_is_not_duplicated_and_multiplier_is_explicit():
    from app.data.abilities import description_with_value, find_definition
    from app.services.ability_presentation import ability_description, present_data
    definition = find_definition('zabojczy')
    canonical = description_with_value(definition, '3')
    translated = present_data({'slug': 'zabojczy', 'value': '3', 'description': canonical}, 'en')
    assert translated['display_description'].count('Inflict 3 wounds') == 1
    assert 'Zamiast' not in translated['display_description']
    assert 'Before Defence tests' in ability_description(description_with_value(find_definition('rozprysk'), '3'), 'en')
    assert '2 × 2' in description_with_value(find_definition('mag'), '2', 'en')


def test_catalog_script_has_no_database_queries(client):
    from sqlalchemy import event
    browser, sessions = client
    engine = sessions.kw['bind']
    queries = []
    def observe(*args):
        queries.append(args[2])
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        browser.cookies.set('szop_language', 'pl')
        response = browser.get('/i18n/en.js?v=test')
        assert response.status_code == 200
        assert response.headers['content-language'] == 'en'
        assert 'immutable' in response.headers['cache-control']
        assert 'Caster' in response.text
        assert queries == []
    finally:
        event.remove(engine, 'before_cursor_execute', observe)


def test_dynamic_error_preserves_interpolated_names():
    from app.i18n import translate
    assert translate('Użytkownik "Armie" już istnieje.', 'en') == 'User "Armie" already exists.'


def test_spell_rebuilds_system_description_from_current_definition():
    from app.services.ability_presentation import localize_spells
    original = {'kind': 'ability', 'base_label': 'Rozkaz: Maskowanie', 'custom_name': 'Mag',
                'value': 'maskowanie', 'description': 'Stary opis zasięgu 3".', 'label': 'Mag [Rozkaz: Maskowanie]'}
    result = localize_spells([original], 'en')[0]
    assert result['label'] == '"Mag" Command: Camouflage'
    assert '2”' in result['description'] and 'Stary opis' not in result['description']
    assert original['description'] == 'Stary opis zasięgu 3".'


def test_weapon_spell_preserves_custom_name_and_translates_system_traits():
    from app.services.ability_presentation import localize_spells
    original = {'kind': 'weapon', 'base_label': 'trafienie 12" AP0 namierzanie, precyzyjny',
                'custom_name': 'Artyleria!', 'value': None,
                'description': 'Artyleria! | Zasięg: 12" | Ataki: 1 | AP: 0 | Cechy: namierzanie, precyzyjny'}
    result = localize_spells([original], 'en')[0]
    assert result['label'].startswith('"Artyleria!" Weapon hit')
    assert 'Targeting, Precise' in result['label']
    assert result['description'].startswith('Artyleria! | Range:')
    assert 'Traits: Targeting, Precise' in result['description']


@pytest.mark.parametrize('name', ['Mag | Szybki', 'Mag', ''])
def test_weapon_spell_keeps_notes_and_name_verbatim(name):
    from app.services.ability_presentation import spell_texts
    notes = 'Szybki, Mag | Cechy: moje notatki'
    prefix = name + ' | ' if name else ''
    description = prefix + 'Zasięg: Wręcz | Ataki: 3 | AP: 0 | Cechy: precyzyjny | ' + notes
    label, translated = spell_texts('3 trafienia Wręcz AP0 precyzyjny', description, 'weapon', None, 'en')
    assert label == '3 weapon hits Melee AP0 Precise'
    assert translated == prefix + 'Range: Melee | Attacks: 3 | AP: 0 | Traits: Precise | ' + notes


def test_catalog_version_covers_the_generated_rules(monkeypatch):
    import hashlib

    from starlette.requests import Request

    from app import i18n
    from app.services import ability_presentation
    from app.templating import locale_context

    request = Request({'type': 'http', 'headers': [(b'accept-language', b'en')]})
    original_rules = ability_presentation.javascript_rules
    original_version = locale_context(request)['translation_version']
    def changed_rules(language):
        rules = original_rules(language)
        rules[0]['description'] += ' Changed canonical rule.'
        return rules
    monkeypatch.setattr(ability_presentation, 'javascript_rules', changed_rules)
    i18n.javascript_catalog.cache_clear()
    i18n.translation_version.cache_clear()
    try:
        version = locale_context(request)['translation_version']
        assert version == hashlib.sha256(i18n.javascript_catalog('en').encode()).hexdigest()[:12]
        assert version != original_version
    finally:
        i18n.javascript_catalog.cache_clear()
        i18n.translation_version.cache_clear()
