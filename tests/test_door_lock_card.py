"""Exercise image-only history and opening identity in the shipped card."""
from pathlib import Path
import shutil
import subprocess
import unittest

HARNESS = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
global.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = {innerHTML: '', querySelector: () => ({addEventListener(){}}), querySelectorAll: () => []};
  }
};
const definitions = new Map();
global.customElements = {get: name => definitions.get(name), define: (name, cls) => definitions.set(name, cls)};
global.window = {customCards: []};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
const Card = definitions.get('orvibo-smart-control-door-lock-card');
(async () => {
  const card = new Card();
  card.setConfig({history_limit: 47});
  assert.equal(card._historyLimit, 47);
  card._deviceId = 'a'; card._entitiesLoaded = true;
  card._entities = {unlock: 'sensor.unlock'};
  const requests = [];
  card._hass = {states: {'sensor.unlock': {state: '<张三>外开（指纹）'}}, callWS: async request => {
    requests.push(request);
    if (request.type === 'media_source/resolve_media') return {url: '/media/picture.jpg'};
    return {response: {events: [
      {type:'video', kind:'ring', time:'2', media_id:'video'},
      {type:'image', kind:'ring', time:'1', media_id:'image'},
    ]}};
  }};
  await card._loadEvents();
  assert.deepEqual(requests[0].service_data, {device_id:'a', limit:47, media_type:'image'});
  assert.equal(requests[1].media_id, 'image');
  assert.equal(card._events.length, 1);
  assert(card.shadowRoot.innerHTML.includes('&lt;张三&gt;外开（指纹）'));
  assert(!card.shadowRoot.innerHTML.includes('<张三>'));
  card.setConfig({}); assert.equal(card._historyLimit, 30);
  card.setConfig({history_limit:1000}); assert.equal(card._historyLimit, 500);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''


class DoorLockCardTests(unittest.TestCase):
    def _run_script(self, body):
        if not shutil.which('node'):
            self.skipTest('Node.js required')
        setup = HARNESS.split('(async () => {', 1)[0]
        script = setup + '(async () => {\n' + body + '\n})().catch(error => { console.error(error); process.exitCode = 1; });'
        card = Path(__file__).parents[1] / 'custom_components/orvibo_smart_control/www/orvibo-smart-control-door-lock-card.js'
        result = subprocess.run([shutil.which('node'), '-e', script, str(card)],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_battery_selection_validates_percentages_including_zero(self):
        self._run_script(r'''
const card = new Card();
card._entities = {dry_battery:'sensor.dry', lithium_battery:'sensor.lithium'};
card._hass = {states:{}};
for (const invalid of ['unknown','unavailable','', ' ', '-1', '101', '1.5', false]) {
  card._hass.states = {'sensor.lithium':{state:invalid,attributes:{is_setup:true}},
    'sensor.dry':{state:'0',attributes:{is_setup:true}}};
  const battery=card._batterySummary();
  assert.equal(battery.label,'干电池');
  assert.equal(battery.value,'0%');
  assert.equal(battery.level,0);
}
card._hass.states['sensor.lithium']={state:'85',attributes:{is_setup:false}};
assert.equal(card._batterySummary().label,'干电池');
''')

    def test_inside_opening_does_not_display_stale_name_or_credential(self):
        self._run_script(r'''
const card = new Card();
card._entities={unlock:'sensor.unlock',lock_state:'sensor.lock',door:'binary_sensor.door'};
card._hass={states:{'sensor.unlock':{state:'旧用户外开（指纹）',attributes:{
  open_direction:'inside',unlock_user_name:'旧用户',unlock_method:'fingerprint'}}}};
const opening=card._openingSummary();
assert.equal(opening.label,'人员未知');
assert.equal(opening.direction,'内开');
assert(!opening.detail.includes('指纹'));
card._hass.states['sensor.lock']={state:'unknown',attributes:{door_open:false,inside_locked:false}};
assert.equal(card._lockState(),'unknown');
assert.equal(card._doorSummary().label,'门已关');
card._hass.states['sensor.lock'].attributes.door_open=null;
assert.equal(card._doorSummary().label,'门磁未知');
''')

    def test_image_resolution_is_bounded_ordered_and_preserves_failed_refresh(self):
        self._run_script(r'''
const card = new Card();
card._deviceId='lock'; card._entitiesLoaded=true;
const events=Array.from({length:9},(_,index)=>({type:'image',media_id:'image-'+index,time:9-index,kind:'ring'}));
let active=0, peak=0, mode='ok';
card._hass={states:{},callWS:async request=>{
  if(request.service==='list_events') {
    if(mode==='network')throw new Error('network down');
    if(mode==='invalid')return {response:{}};
    return {response:{events}};
  }
  active++; peak=Math.max(peak,active);
  await new Promise(resolve=>setTimeout(resolve,request.media_id.endsWith('0')?12:1));
  active--;
  if(mode==='partial' && request.media_id==='image-0')throw new Error('resolve failed');
  return {url:'/media/'+request.media_id};
}};
await card._loadEvents();
assert(peak>1 && peak<=4);
assert.deepEqual(card._events.map(event=>event.mediaId),events.map(event=>event.media_id));
for(const failure of ['partial','network','invalid']) {
  mode=failure;
  await card._loadEvents(true);
  assert.equal(card._events.length,9);
  assert.equal(card._events[0].url,'/media/image-0');
  assert(card._eventsError);
  assert(card._eventsMarkup().includes('ov-snapshot-latest'));
}
''')

    def test_new_snapshot_failure_keeps_previous_image_until_recovered(self):
        self._run_script(r'''
const card = new Card();
card._deviceId='lock'; card._entitiesLoaded=true; card._historyLimit=1;
const oldImage={mediaId:'old-image',url:'/media/old-image',time:1,kind:'ring'};
card._events=[oldImage];
let fail=true, events=[{type:'image',media_id:'new-image',time:2,kind:'ring'}];
card._hass={states:{},callWS:async request=>{
  if(request.service==='list_events')return {response:{events}};
  if(fail)throw new Error('resolve temporarily unavailable');
  return {url:'/media/new-image'};
}};
await card._loadEvents(true);
assert.deepEqual(card._events,[oldImage]);
assert(card._eventsError);
assert(card._eventsLoaded);
assert(!card._eventsLoading);
assert(card._eventsMarkup().includes('/media/old-image'));
fail=false;
await card._loadEvents(true);
assert.equal(card._events.length,1);
assert.equal(card._events[0].mediaId,'new-image');
assert.equal(card._eventsError,'');
events=[];
await card._loadEvents(true);
assert.deepEqual(card._events,[]);
assert.equal(card._eventsError,'');
''')

    def test_history_from_old_configuration_is_discarded(self):
        self._run_script(r'''
const card = new Card();
card._deviceId='old-lock'; card._entitiesLoaded=true;
let resolveList;
card._hass={states:{},callWS:request=>{
  if(request.service==='list_events')return new Promise(resolve=>{resolveList=resolve;});
  if(request.type.startsWith('config/'))return Promise.resolve([]);
  throw new Error('old images must not be resolved');
}};
const pending=card._loadEvents();
card.setConfig({device_id:'new-lock'});
resolveList({response:{events:[{type:'image',media_id:'old-image'}]}});
await pending;
assert.equal(card._events.length,0);
assert.equal(card._eventsLoaded,false);
assert.equal(card._eventsLoading,false);
''')

    def test_unrelated_ha_state_updates_do_not_replace_card_dom(self):
        self._run_script(r'''
const card = new Card();
card._entitiesLoaded=true;
card._entities={lock_state:'sensor.lock',door:'binary_sensor.door'};
const lock={state:'locked'}, door={state:'off'};
card._hass={states:{'sensor.lock':lock,'binary_sensor.door':door,'sensor.other':{state:'1'}}};
let renders=0; card._render=()=>{renders++;};
card.hass={states:{'sensor.lock':lock,'binary_sensor.door':door,'sensor.other':{state:'2'}}};
assert.equal(renders,0);
card.hass={states:{'sensor.lock':{state:'unlocked'},'binary_sensor.door':door}};
assert.equal(renders,1);
''')

    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_image_history_request_and_opening_display(self):
        card = Path(__file__).parents[1] / 'custom_components/orvibo_smart_control/www/orvibo-smart-control-door-lock-card.js'
        result = subprocess.run([shutil.which('node'), '-e', HARNESS, str(card)],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
