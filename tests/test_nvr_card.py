"""Exercise the shipped vanilla card's query/play/stop flow in a DOM harness."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]

HARNESS = r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert/strict');
class Element {
 constructor(){this.children=[];this.events={};this.value='';this.textContent='';this.disabled=false;}
 addEventListener(type,fn){this.events[type]=fn;}
 replaceChildren(...children){this.children=children;}
 querySelectorAll(){return this.children;}
}
class Root {
 constructor(){this.elements={};this.heading=new Element();}
 set innerHTML(value){this.html=value;for(const id of [...value.matchAll(/id="([^"]+)"/g)])this.elements[id[1]]=new Element();}
 getElementById(id){return this.elements[id];}
 querySelector(){return this.heading;}
}
global.HTMLElement=class {attachShadow(){this.shadowRoot=new Root();}};
global.document={createElement(){return new Element();}};
const definitions=new Map();
global.customElements={get:k=>definitions.get(k),define:(k,v)=>definitions.set(k,v)};
const calls=[];const configs=[];
global.window={customCards:[],loadCardHelpers:async()=>({createCardElement(config){configs.push(config);return new Element();}})};
const source=fs.readFileSync(process.argv[1],'utf8');vm.runInThisContext(source);vm.runInThisContext(source);
assert.equal(window.customCards.length,1);
const Card=definitions.get('orvibo-smart-control-nvr-card');
const card=new Card();card.setConfig({});
let response;let failure=false;
card.hass={states:{'camera.live':{attributes:{video_mode:'live'}},'camera.hdd3':{attributes:{video_mode:'hdd_playback',friendly_name:'<img onerror=evil>'}}},
callWS:async(request)=>{calls.push(request);if(failure)throw Error('PRIVATE');return {response};}};
(async()=>{
 assert.equal(card._entity,'camera.hdd3');
 assert.equal(card._ui('channel').children[0].textContent,'<img onerror=evil>');
 assert(!card.shadowRoot.html.includes('<img onerror=evil>'));
 card._ui('day').value='2026-10-15';
 response={stage:'hdd_search_received',recording_days:['20261001','20261015'],recording_count:2};
 await card._search('month');
 assert.deepEqual(calls.at(-1).service_data,{entity_id:'camera.hdd3',operation:'month',date:'202610'});
 assert.equal(card._ui('days').children.length,2);
 response={stage:'hdd_search_received',fragments:[{start:'20261015090000',end:'20261015100000'}],recording_count:1,fragments_truncated:false};
 await card._search('day');
 assert.equal(card._ui('fragments').children[0].textContent,'09:00:00 — 10:00:00　播放');
 response={stage:'playback_selected'};
 await card._play('20261015090000');
 assert.equal(calls.at(-1).service,'start_hdd_playback');
 assert.equal(configs.at(-1).entity,'camera.hdd3');assert.equal(configs.at(-1).camera_view,'live');
 assert.equal(card._ui('player').children.length,1);
 response={stage:'playback_stopped'};
 await card._stop();assert.equal(card._ui('player').children.length,0);
 assert.equal(calls.at(-1).service,'stop_hdd_playback');
 failure=true;await card._search('day');
 assert(!card._ui('status').textContent.includes('PRIVATE'));assert.equal(card._busy,false);
 assert.equal(card._ui('search').disabled,false);
 card._config={entity:'camera.missing'};card._sync();assert.equal(card._entity,undefined);
 assert.equal(card._ui('search').disabled,true);
 console.log('NVR card query, playback, stop, retry, selection and text safety passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''


class NvrCardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_interactive_recording_workflow(self):
        result = subprocess.run([shutil.which("node"), "-e", HARNESS,
            str(ROOT / "custom_components/orvibo_smart_control/www/orvibo-smart-control-nvr-card.js")],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
