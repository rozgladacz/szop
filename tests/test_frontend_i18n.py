"""Exercise the real browser formatter with canonical rule data."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.data.abilities import description_with_value, find_definition
from app.services.ability_presentation import javascript_rules


def test_browser_localisation_keeps_custom_names_and_rule_values():
    scope = {'SZOP_LANGUAGE': 'en', 'SZOP_TRANSLATIONS': {},
             'SZOP_ABILITY_TRANSLATIONS': javascript_rules('en')}
    canonical = description_with_value(find_definition('zabojczy'), '3')
    program = '''
const vm = require('vm'), fs = require('fs');
const scope = SCOPE;
scope.document = {addEventListener() {}};
const sandbox = {window:scope, globalThis:scope, document:scope.document};
vm.runInNewContext(fs.readFileSync('app/static/js/modules/i18n.js','utf8'),sandbox);
vm.runInNewContext(fs.readFileSync('app/static/js/modules/loadout_state.js','utf8'),sandbox);
console.log(JSON.stringify({
 label:scope.SZOPLoadoutState.formatAbilityDisplayLabel('Mag(2)', 'Mag'),
 multiple:scope.SZOPI18n.abilityLabel('Mag [Mag(2)] ×2'),
 description:scope.SZOPI18n.abilityDescription(DESCRIPTION)
}));
'''.replace('SCOPE', json.dumps(scope)).replace('DESCRIPTION', json.dumps(canonical))
    process = subprocess.run([shutil.which('node'), '-'], input=program, cwd=ROOT,
                             capture_output=True, text=True, encoding='utf-8', timeout=20, check=True)
    result = json.loads(process.stdout)
    assert result['label'] == 'Mag [Caster(2)]'
    assert result['multiple'] == 'Mag [Caster(2)] ×2'
    assert result['description'].startswith('Inflict 3 wounds')
    assert 'Zamiast' not in result['description']


def test_language_switch_keeps_unsaved_hidden_fields_and_blocks_failed_autosave():
    program = r'''
const vm = require('vm'), fs = require('fs');
const events = {};
let languageSubmit, submitted = 0, prompts = 0, alerts = 0;
const ordinary = {fields:[['abilities','original']], closest(){return null}, hasAttribute(){return false}};
const languageForm = {addEventListener(type,handler){languageSubmit=handler}, appendChild(){throw Error('Unexpected mutation')}};
const document = {
 addEventListener(type, handler){events[type]=handler},
 querySelectorAll(selector){return selector.startsWith('form:') ? [ordinary] : [languageForm]},
 createElement(){throw Error('Unexpected navigation')}
};
class FormData {constructor(form){this.values=form.fields} [Symbol.iterator](){return this.values[Symbol.iterator]()}}
const scope = {SZOP_LANGUAGE:'en',document,setTimeout(handler){handler()},confirm(){prompts++;return false},alert(){alerts++}};
const sandbox = {window:scope,globalThis:scope,document,FormData,HTMLFormElement:{prototype:{submit(){submitted++}}}};
vm.runInNewContext(fs.readFileSync('app/static/js/modules/i18n.js','utf8'),sandbox);
events.DOMContentLoaded();
(async()=>{
 ordinary.fields=[['abilities','after-removing-an-ability']];
 await languageSubmit({preventDefault(){},submitter:{value:'pl'}});
 const cancelled = {prompts,submitted,alerts};
 scope.SZOPI18n.beforeLanguageChange.push(async()=>{throw Error('Save failed')});
 await languageSubmit({preventDefault(){},submitter:{value:'pl'}});
 console.log(JSON.stringify({cancelled,failed:{prompts,submitted,alerts}}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
    process = subprocess.run([shutil.which('node'), '-'], input=program, cwd=ROOT,
                             capture_output=True, text=True, encoding='utf-8', timeout=20, check=True)
    result = json.loads(process.stdout)
    assert result['cancelled'] == {'prompts': 1, 'submitted': 0, 'alerts': 0}
    assert result['failed'] == {'prompts': 1, 'submitted': 0, 'alerts': 1}


@pytest.mark.parametrize('edit_during_save', [False, True])
def test_models_language_switch_checks_edits_made_while_saving(edit_during_save):
    program = r'''
const vm = require('vm'), fs = require('fs'), assert = require('assert/strict');
class Element {
 constructor(attrs={}) {this.attrs=attrs; this.listeners={}; this.classList={add(){},remove(){},toggle(){}}}
 getAttribute(key){return this.attrs[key] || ''}
 setAttribute(key,value){this.attrs[key]=String(value)}
 addEventListener(key,handler){this.listeners[key]=handler}
 querySelector(){return null}
 querySelectorAll(){return []}
}
const item = new Element({'data-roster-unit-id':'5'}), panel = new Element(), toggle = new Element(), editor = new Element();
const root = new Element(); root.dataset={rosterId:'3'};
root.querySelector = key => ({'[data-roster-editor]':editor,'[data-roster-models-toggle]':toggle,
 '[data-roster-models-panel]':panel,'[data-roster-item].active':item})[key] || null;
const document = {readyState:'complete',querySelector(){return root}};
let resolveSave, submittedCount, timer = 0;
const scope = {document, SZOPI18n:{t:text=>text,beforeLanguageChange:[]},
 setTimeout(){return ++timer},clearTimeout(){}};
const fetch = async (url,options={}) => {
 if (url.endsWith('/collection-models')) return {ok:true,json:async()=>({models:[],composed:[{id:null,qty:1,weapons:{}}]})};
 submittedCount=options.body.get('count');
 return new Promise(resolve=>{resolveSave=()=>resolve({ok:true,json:async()=>({})})});
};
const sandbox={window:scope,document,fetch,FormData,AbortController,console};
vm.runInNewContext(fs.readFileSync('app/static/js/modules/roster_collection_models.js','utf8'),sandbox);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 toggle.listeners.click({preventDefault(){}}); await tick();
 const switching=scope.SZOPI18n.beforeLanguageChange[0]();
 assert.equal(submittedCount,'1');
 if (EDIT_DURING_SAVE) {
  const input={value:'2',getAttribute(){return '0'},closest(selector){return selector==='[data-proxy-qty]' ? this : null}};
  panel.listeners.input({target:input});
 }
 resolveSave();
 if (EDIT_DURING_SAVE) await assert.rejects(switching, /Unsaved/);
 else await switching;
})().catch(error=>{console.error(error);process.exitCode=1});
'''.replace('EDIT_DURING_SAVE', json.dumps(edit_during_save))
    result = subprocess.run([shutil.which('node'), '-'], input=program, cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', timeout=20, check=False)
    assert result.returncode == 0, result.stderr
