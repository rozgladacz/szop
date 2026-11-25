import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import config, models
from app.db import Base
from app.routers import armies, armories, users
from app.services import utils


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def weapons(db):
    owner = models.User(username='owner', password_hash='unused')
    public = models.Armory(name='Public catalogue')
    variant = models.Armory(name='Variant', parent=public, owner=owner)
    private_army = models.Army(
        name='Private army',
        armory=public,
        ruleset=models.RuleSet(name='Core'),
        owner=models.User(username='another owner', password_hash='unused'),
    )
    catalogue = models.Weapon(armory=public, name='Catalogue weapon')
    spell = models.Weapon(armory=public, army=private_army, name='Private spell weapon')
    db.add_all([catalogue, spell, variant])
    db.flush()
    return catalogue, spell, variant


def test_catalogue_variants_exclude_spell_weapons(db, weapons):
    catalogue, spell, variant = weapons
    utils.ensure_armory_variant_sync(db, variant)
    assert {weapon.parent_id for weapon in variant.weapons} == {catalogue.id}

    legacy = models.Weapon(armory=variant, parent=spell)
    child = models.Armory(name='Child variant', parent=variant, owner=variant.owner)
    db.add_all([legacy, child])
    db.flush()
    child_catalogue = utils.load_armory_weapons(db, child)
    assert [weapon.effective_name for weapon in child_catalogue] == [catalogue.name]
    assert len(child.weapons) == 1
    assert db.get(models.Weapon, legacy.id) is legacy


def test_copy_and_reparent_keep_legacy_private_weapon_out_of_catalogue(db, weapons):
    catalogue, spell, variant = weapons
    utils.ensure_armory_variant_sync(db, variant)
    db.add(models.Weapon(armory=variant, parent=spell))
    db.flush()

    armories.copy_armory(
        variant.id, request=None, name='Copy', is_global=None, db=db, current_user=variant.owner
    )
    copy = db.scalar(select(models.Armory).where(models.Armory.name == 'Copy'))
    assert [weapon.effective_name for weapon in copy.weapons] == [catalogue.name]

    armories.change_armory_parent(
        variant.id, request=None, new_parent_id='', db=db, current_user=variant.owner
    )
    assert [weapon.effective_name for weapon in utils.load_armory_weapons(db, variant)] == [catalogue.name]


def test_unit_accepts_catalogue_weapon_only(db, weapons):
    catalogue, spell, _ = weapons
    selection = json.dumps([{'weapon_id': weapon.id} for weapon in (catalogue, spell)])
    result = armies._parse_weapon_payload(db, catalogue.armory, selection)
    assert [weapon for weapon, _, _ in result] == [catalogue]


def test_armory_edit_does_not_resolve_spell_weapon(db, weapons):
    catalogue, spell, _ = weapons
    assert armories._get_weapon(db, catalogue.armory, catalogue.id) is catalogue
    with pytest.raises(HTTPException) as denied:
        armories._get_weapon(db, catalogue.armory, spell.id)
    assert denied.value.status_code == 404


def test_public_mode_does_not_publish_deleted_account_resources(db, weapons, monkeypatch):
    _, _, variant = weapons
    owner_id = variant.owner_id
    variant_id = variant.id
    admin = models.User(username='admin', password_hash='unused', is_admin=True)
    db.add(admin)
    db.commit()
    monkeypatch.setattr(config, 'PUBLIC_ORIGIN', 'https://example.test')

    response = users.delete_user(owner_id, request=None, db=db, current_user=admin)

    assert response.headers['location'] == '/users?error=public-delete-disabled'
    assert db.get(models.User, owner_id) is not None
    assert db.scalar(select(models.Armory.owner_id).where(models.Armory.id == variant_id)) == owner_id
