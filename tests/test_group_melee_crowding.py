"""End-to-end tests for group-level melee crowding: a base unit + its
attached hero share ONE melee pool for the base_size discount, with limits
taken from the BASE unit (not the hero) -- see rosters.py's
_classification_map Phase 1.5 and HANDOFF_rozmiar-podstawki.md decision
"limity z oddzialu bazowego"."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models
from app.db import Base
from app.routers import rosters
from app.services import costs


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _world(session):
    user = models.User(username="crowding-tester", password_hash="x")
    ruleset = models.RuleSet(name="Crowding Rules")
    armory = models.Armory(name="Crowding Armory", owner=user)
    session.add_all([user, ruleset, armory])
    session.flush()

    # Pure melee weapon, moderate AP so the per-model cost is meaningfully
    # non-zero (distinguishable from 0 in assertions below).
    blade = models.Weapon(armory=armory, name="Blade", range="", attacks=1, ap=2)
    # Pricier melee weapon for hero fixtures -- higher AP outranks `blade` in
    # melee_crowding_factors's cost-descending sort, so a hero carrying this
    # can "bump" a base-unit model into a worse discount tier when pooled
    # (proves pooling re-ranks by VALUE across the group, not just position).
    great_blade = models.Weapon(armory=armory, name="Great Blade", range="", attacks=1, ap=4)
    session.add_all([blade, great_blade])
    session.flush()

    army = models.Army(name="Crowding Army", owner=user, ruleset=ruleset, armory=armory)
    session.add(army)
    session.flush()

    bohater = models.Ability(name="Bohater", type="passive", description="")
    session.add(bohater)
    session.flush()

    return SimpleNamespace(
        user=user, ruleset=ruleset, armory=armory, blade=blade,
        great_blade=great_blade, army=army, bohater=bohater,
    )


def _unit(session, w, *, name, toughness, base_size, typical_models=1, weapon=None):
    weapon = weapon or w.blade
    unit = models.Unit(
        army=w.army, name=name, quality=4, defense=4, toughness=toughness,
        base_size=base_size, typical_models=typical_models, position=0,
        default_weapon=weapon,
    )
    session.add(unit)
    session.flush()
    session.add(
        models.UnitWeapon(
            unit=unit, weapon=weapon, is_default=True, default_count=1,
            is_primary=True, position=0,
        )
    )
    session.flush()
    return unit


def _hero_unit(session, w, *, base_size="srednia", weapon=None):
    unit = _unit(session, w, name="Kapitan", toughness=1, base_size=base_size, weapon=weapon)
    session.add(models.UnitAbility(unit=unit, ability=w.bohater, position=0))
    session.flush()
    return unit


def test_group_pools_hero_into_base_units_melee_crowding():
    session = _session()
    try:
        w = _world(session)
        # duza: limit1=2, limit2=4. Hero carries a PRICIER weapon than the
        # base troopers, so pooling must re-rank by VALUE across the group:
        # the hero's model outranks (stays full price) while "stealing" one
        # of the base unit's full-price slots -- the base unit's OWN 5 models
        # (all identical "Blade") would otherwise occupy ranks 1-2 (full),
        # 3-4 (half), 5 (tenth) standalone; pooled, the hero's "Great Blade"
        # takes rank 1, pushing the base unit's models to ranks 2 (full),
        # 3-4 (half), 5-6 (tenth) -- one fewer full-price slot for the base
        # unit than standalone.
        base_unit = _unit(session, w, name="Grunts", toughness=3, base_size="duza", typical_models=5)
        hero_unit = _hero_unit(session, w, base_size="mala", weapon=w.great_blade)  # own base_size must be ignored

        roster = models.Roster(name="Test Roster", army=w.army, owner=w.user)
        session.add(roster)
        session.flush()
        base_ru = models.RosterUnit(roster=roster, unit=base_unit, count=5, position=0)
        session.add(base_ru)
        session.flush()
        hero_ru = models.RosterUnit(
            roster=roster, unit=hero_unit, count=1, position=1,
            parent_roster_unit_id=base_ru.id,
        )
        session.add(hero_ru)
        session.flush()

        blade_cost = costs.weapon_cost_components(w.blade, 4, [])["melee"]
        great_blade_cost = costs.weapon_cost_components(w.great_blade, 4, [])["melee"]
        assert great_blade_cost > blade_cost  # sanity: fixture assumption holds

        # Realistic sanitized loadouts (explicit weapons dict, matching what
        # _roster_unit_loadout produces for a fresh RosterUnit with no
        # extra_weapons_json override) -- a bare {} loadout would NOT match
        # real usage: role_totals.py has no default-weapon fallback (see
        # HANDOFF_rozmiar-podstawki.md notes), so an empty weapons dict makes
        # its melee contribution silently zero regardless of crowding.
        base_loadout = rosters._roster_unit_loadout(base_ru)
        hero_loadout = rosters._roster_unit_loadout(hero_ru)

        # --- Pooled (grouped) computation ---
        classifications, totals_by_id = rosters._classification_map(
            [base_ru, hero_ru], {base_ru.id: base_loadout, hero_ru.id: hero_loadout}
        )
        base_role = classifications[base_ru.id]["slug"]
        hero_role = classifications[hero_ru.id]["slug"]
        base_total_pooled = totals_by_id[base_ru.id][base_role]
        hero_total_pooled = totals_by_id[hero_ru.id][hero_role]

        # --- Standalone reference (no pooling) for the SAME units/counts ---
        base_quote_standalone = costs.calculate_roster_unit_quote(base_unit, base_loadout, 5)
        hero_quote_standalone = costs.calculate_roster_unit_quote(hero_unit, hero_loadout, 1)

        # Pooling must produce a STRICTLY LOWER total for the base unit than
        # its own standalone (duza-only) computation -- the hero's pricier
        # weapon bumps one base-unit model out of the full-price tier.
        assert base_total_pooled < base_quote_standalone["selected_total"]

        # The hero's own weapon is the most expensive in the pool -> it stays
        # rank 1 (full price) whether pooled or standalone. Exact equality
        # here proves the discount tier assignment came from a real ranking
        # (not e.g. every member silently getting the worst tier).
        assert round(hero_total_pooled, 2) == round(hero_quote_standalone["selected_total"], 2)
    finally:
        session.close()


def test_group_pooling_uses_base_unit_base_size_not_hero_own_size():
    """A hero with base_size='duza' attached to a 'mala' base unit must NOT
    tighten the pool's limits -- limits always come from the base unit."""
    session = _session()
    try:
        w = _world(session)
        # mala: limit1=8, limit2=12 -- 5 base + 1 hero = 6, well under limit1.
        base_unit = _unit(session, w, name="Grunts", toughness=1, base_size="mala", typical_models=5)
        hero_unit = _hero_unit(session, w, base_size="duza")  # tight limits, must be ignored

        roster = models.Roster(name="Test Roster", army=w.army, owner=w.user)
        session.add(roster)
        session.flush()
        base_ru = models.RosterUnit(roster=roster, unit=base_unit, count=5, position=0)
        session.add(base_ru)
        session.flush()
        hero_ru = models.RosterUnit(
            roster=roster, unit=hero_unit, count=1, position=1,
            parent_roster_unit_id=base_ru.id,
        )
        session.add(hero_ru)
        session.flush()

        base_loadout = rosters._roster_unit_loadout(base_ru)
        hero_loadout = rosters._roster_unit_loadout(hero_ru)

        classifications, totals_by_id = rosters._classification_map(
            [base_ru, hero_ru], {base_ru.id: base_loadout, hero_ru.id: hero_loadout}
        )
        base_role = classifications[base_ru.id]["slug"]
        hero_role = classifications[hero_ru.id]["slug"]
        base_total_pooled = totals_by_id[base_ru.id][base_role]
        hero_total_pooled = totals_by_id[hero_ru.id][hero_role]

        base_quote_standalone = costs.calculate_roster_unit_quote(base_unit, base_loadout, 5)
        hero_quote_standalone = costs.calculate_roster_unit_quote(hero_unit, hero_loadout, 1)

        # A 6-model pool under mala's limit1=8 gets NO discount at all --
        # pooled totals must equal standalone totals exactly (not just <=).
        assert round(base_total_pooled, 2) == round(base_quote_standalone["selected_total"], 2)
        assert round(hero_total_pooled, 2) == round(hero_quote_standalone["selected_total"], 2)
    finally:
        session.close()


def test_standalone_unit_without_hero_unaffected_by_pooling_phase():
    """A lone unit (no parent, no attached heroes) must go through Phase 1.5
    as a no-op -- its Phase 1 standalone totals are used unchanged."""
    session = _session()
    try:
        w = _world(session)
        base_unit = _unit(session, w, name="Grunts", toughness=3, base_size="duza", typical_models=8)

        roster = models.Roster(name="Test Roster", army=w.army, owner=w.user)
        session.add(roster)
        session.flush()
        base_ru = models.RosterUnit(roster=roster, unit=base_unit, count=8, position=0)
        session.add(base_ru)
        session.flush()

        base_loadout = rosters._roster_unit_loadout(base_ru)
        classifications, totals_by_id = rosters._classification_map(
            [base_ru], {base_ru.id: base_loadout}
        )
        role = classifications[base_ru.id]["slug"]
        pooled_total = totals_by_id[base_ru.id][role]

        standalone_quote = costs.calculate_roster_unit_quote(base_unit, base_loadout, 8)
        assert round(pooled_total, 2) == round(standalone_quote["selected_total"], 2)
    finally:
        session.close()
