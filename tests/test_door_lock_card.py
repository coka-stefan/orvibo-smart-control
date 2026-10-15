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
    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_image_history_request_and_opening_display(self):
        card = Path(__file__).parents[1] / 'custom_components/orvibo_smart_control/www/orvibo-smart-control-door-lock-card.js'
        result = subprocess.run([shutil.which('node'), '-e', HARNESS, str(card)],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
