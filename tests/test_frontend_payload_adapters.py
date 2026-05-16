from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from tests.node_runtime import resolve_node_binary


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_JS_PATH = ROOT_DIR / "app/static/js/app.js"
MODULE_PATHS = [
    ROOT_DIR / "app/static/js/modules/refresh_priority.js",
    ROOT_DIR / "app/static/js/modules/payload_adapters.js",
    ROOT_DIR / "app/static/js/modules/text_parsing.js",
    ROOT_DIR / "app/static/js/modules/ui_pickers.js",
    ROOT_DIR / "app/static/js/modules/spell_weapon_cost_preview.js",
    ROOT_DIR / "app/static/js/modules/spell_ability_forms.js",
    ROOT_DIR / "app/static/js/modules/roster_rendering.js",
    ROOT_DIR / "app/static/js/modules/loadout_state.js",
    ROOT_DIR / "app/static/js/modules/editor_renderers.js",
    ROOT_DIR / "app/static/js/modules/roster_adders.js",
]
QUOTE_FIXTURE_DIR = ROOT_DIR / "tests/fixtures/quote_snapshots"


def _build_sandbox_script(body: str, *, dev_mode: bool = False) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const modulePaths = {json.dumps([str(path) for path in MODULE_PATHS])};
        const appCode = fs.readFileSync({json.dumps(str(APP_JS_PATH))}, 'utf8');
        const errors = [];
        const consoleCapture = {{
          log: console.log,
          warn: (...args) => console.warn(...args),
          error: (...args) => errors.push(args.map(String).join(' ')),
        }};
        const sandbox = {{
          console: consoleCapture,
          Map,
          Set,
          JSON,
          Number,
          String,
          Boolean,
          Array,
          Object,
          window: {{
            console: consoleCapture,
            SZOP_DEV_MODE: {json.dumps(dev_mode)},
            setTimeout,
            clearTimeout,
          }},
          document: {{
            addEventListener: () => {{}},
          }},
        }};
        sandbox.window.window = sandbox.window;
        vm.createContext(sandbox);
        modulePaths.forEach((modulePath) => {{
          vm.runInContext(fs.readFileSync(modulePath, 'utf8'), sandbox, {{ filename: modulePath }});
        }});
        vm.runInContext(appCode, sandbox);
        {body}
        """
    )


def _run_node(script: str) -> dict[str, object]:
    result = subprocess.run(
        [resolve_node_binary(), "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = result.stdout.strip()
    assert stdout, "Node script produced no output"
    return json.loads(stdout)


def test_quote_adapter_normalizes_existing_snapshots_and_unit_alias() -> None:
    per_model = json.loads((QUOTE_FIXTURE_DIR / "quote_per_model.json").read_text(encoding="utf-8"))
    massive = json.loads((QUOTE_FIXTURE_DIR / "quote_massive_total.json").read_text(encoding="utf-8"))
    alias_payload = dict(per_model)
    alias_payload.pop("roster_unit_id", None)
    alias_payload["unit_id"] = 77

    script = _build_sandbox_script(
        f"""
        const adapters = sandbox.SZOPPayloadAdapters;
        const payloads = {json.dumps([per_model, massive, alias_payload])};
        const adapted = payloads.map((payload) => adapters.adaptQuotePayload(payload, 'fallback'));
        console.log(JSON.stringify({{
          totals: adapted.map((item) => item.total),
          rosterUnitIds: adapted.map((item) => item.rosterUnitId),
          loadoutModes: adapted.map((item) => item.loadout && item.loadout.mode),
          itemCosts: adapted.map((item) => item.itemCosts),
        }}));
        """
    )

    result = _run_node(script)

    assert result["totals"] == [43.12, 81.03, 43.12]
    assert result["rosterUnitIds"] == ["1", "1", "77"]
    assert result["loadoutModes"] == ["per_model", "total", "per_model"]
    assert result["itemCosts"] == [
        {"weapons": {}, "active": {}, "aura": {}, "passiveDeltas": {}},
        {"weapons": {}, "active": {}, "aura": {}, "passiveDeltas": {}},
        {"weapons": {}, "active": {}, "aura": {}, "passiveDeltas": {}},
    ]


def test_quote_validator_logs_readable_missing_field_in_dev_mode() -> None:
    script = _build_sandbox_script(
        """
        const adapters = sandbox.SZOPPayloadAdapters;
        const ok = adapters.assertQuotePayloadShape('quote-test', {
          roster_unit_id: 1,
          loadout: {},
          item_costs: { weapons: {}, active: {}, aura: {}, passive_deltas: {} },
        });
        console.log(JSON.stringify({ ok, errors }));
        """,
        dev_mode=True,
    )

    result = _run_node(script)

    assert result["ok"] is False
    assert result["errors"] == ["[SZOPPayload:quote-test] Missing field: selected_total"]


def test_item_costs_adapter_normalizes_string_keyed_numeric_maps() -> None:
    script = _build_sandbox_script(
        """
        const adapters = sandbox.SZOPPayloadAdapters;
        const itemCosts = adapters.adaptItemCosts({
          weapons: { 7: '4.5', bad: 'nope' },
          active: { 11: 3 },
          aura: { 12: '2.25' },
          passive_deltas: { strzelec: '-1.5' },
        });
        console.log(JSON.stringify({ itemCosts, errors }));
        """,
        dev_mode=True,
    )

    result = _run_node(script)

    assert result["itemCosts"] == {
        "weapons": {"7": 4.5},
        "active": {"11": 3},
        "aura": {"12": 2.25},
        "passiveDeltas": {"strzelec": -1.5},
    }
    assert result["errors"] == []


def test_weapon_options_adapter_preserves_stats_and_normalizes_core_fields() -> None:
    script = _build_sandbox_script(
        """
        const adapters = sandbox.SZOPPayloadAdapters;
        const weapons = adapters.adaptWeaponOptions([{
          id: 7,
          name: 'Karabin',
          cost: '5.5',
          default_count: '2',
          is_default: 1,
          is_primary: 0,
          range: '24"',
          attacks: 2,
          ap: 1,
          traits: 'Rending',
        }]);
        console.log(JSON.stringify({ weapon: weapons[0], errors }));
        """,
        dev_mode=True,
    )

    result = _run_node(script)

    assert result["weapon"] == {
        "id": "7",
        "weapon_id": "7",
        "name": "Karabin",
        "cost": 5.5,
        "default_count": 2,
        "is_default": True,
        "is_primary": False,
        "range": '24"',
        "attacks": 2,
        "ap": 1,
        "traits": "Rending",
    }
    assert result["errors"] == []


def test_ability_entries_adapter_normalizes_keys_labels_and_defaults() -> None:
    script = _build_sandbox_script(
        """
        const adapters = sandbox.SZOPPayloadAdapters;
        const entries = adapters.adaptAbilityEntries([
          {
            loadout_key: 'aura::banner',
            ability_id: 50,
            label: 'Sztandar',
            raw: 'Aura',
            custom_name: 'Chorazy',
            cost: '3.5',
            default_count: '1',
            is_default: true,
          },
          {
            ability_id: 11,
            slug: 'szarza',
            cost: null,
            is_default: false,
          },
        ], 'active', 'ability-test');
        console.log(JSON.stringify({ entries, errors }));
        """,
        dev_mode=True,
    )

    result = _run_node(script)

    assert result["entries"] == [
        {
            "loadout_key": "aura::banner",
            "ability_id": "50",
            "label": "Sztandar",
            "raw": "Aura",
            "custom_name": "Chorazy",
            "cost": 3.5,
            "default_count": 1,
            "is_default": True,
            "kind": "active",
        },
        {
            "loadout_key": "11",
            "ability_id": "11",
            "slug": "szarza",
            "label": "szarza",
            "raw": "szarza",
            "custom_name": "",
            "cost": 0,
            "default_count": 0,
            "is_default": False,
            "kind": "active",
        },
    ]
    assert result["errors"] == []
