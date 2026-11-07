import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ['MURMUR_INTERNAL_TOKEN'] = 'isolated-test-token'
import engine as core
import api
import runtime
from fastapi.testclient import TestClient

CONFIG = Path(core.__file__).parent / 'config.example.yaml'


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.oldcwd = Path.cwd()
        os.chdir(self.root)
        data = self.root / 'data'
        self.patches = [patch.object(core, 'DATA', data),
                        patch.object(core, 'STATE_FILE', data / 'state.json'),
                        patch.object(core, 'EVENTS_FILE', data / 'events.jsonl'),
                        patch.object(core, 'SNAP_DIR', data / 'snapshots'),
                        patch.object(runtime, 'DATA', data),
                        patch.object(api, 'MOVED_LOG', data / 'moved_log.jsonl')]
        for p in self.patches:
            p.start()
        self.engine = core.EmotionEngine(CONFIG)
        self.engine.unanswered_signals = runtime.engine.unanswered_signals
        self.patches.extend([patch.object(api, 'engine', self.engine), patch.object(runtime, 'engine', self.engine)])
        for p in self.patches[-2:]:
            p.start()
        self.client = TestClient(runtime.app, headers={'Authorization': 'Bearer isolated-test-token'})

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        os.chdir(self.oldcwd)
        self.tmp.cleanup()

    def test_native_schema_and_authentication(self):
        public = TestClient(runtime.app)
        self.assertEqual(public.get('/health').status_code, 200)
        self.assertEqual(public.get('/emotion/state').status_code, 401)
        self.assertEqual(public.get('/docs').status_code, 401)
        state = self.client.get('/emotion/state').json()
        self.assertEqual(set(state['dimensions']), set(self.engine.dims))
        self.assertEqual(state['character'], 'aria')
        self.assertNotIn('drives', state)
        self.assertEqual(self.client.get('/internal/v1/chats/default/emotion/state').status_code, 404)

    def test_dynamics_caps_momentum_and_real_time_decay(self):
        self.engine.update({'warmth': 5}, source='internal')
        self.assertLessEqual(self.engine.state['warmth'], .8)
        self.engine.history['warmth'] = .2
        applied = self.engine.update({'warmth': -.1}, source='internal')['warmth']
        self.assertLess(abs(applied), .1)
        before = self.engine.state['warmth']
        self.engine.last_tick_at = time.time() - 600
        self.engine.tick()
        self.assertAlmostEqual(self.engine.state['warmth'], .6 + (before - .6) * math.exp(-.001 * 10), places=5)

    def test_event_retry_is_deduplicated_after_restart(self):
        payload = {'event_id': 'reply-1', 'source': 'internal', 'dimensions': {'upset': .2}}
        first = self.client.post('/emotion/update', json=payload)
        self.assertEqual(first.status_code, 200)
        old = self.engine.state['upset']
        second = self.client.post('/emotion/update', json=payload).json()
        self.assertTrue(second['duplicate'])
        self.assertEqual(self.engine.state['upset'], old)
        restarted = core.EmotionEngine(CONFIG)
        self.assertEqual(restarted.update({'upset': .2}, event_id='reply-1'), {})
        self.assertEqual(restarted.state['upset'], old)

    def test_absence_and_goodnight(self):
        self.engine.config['absence_rules'] = [{'after_minutes': 120, 'trigger': 'test', 'dimensions': {'longing': .1}}]
        self.engine.last_input_at = time.time() - 120 * 60
        self.engine.last_tick_at = time.time() - 300
        result = self.engine.tick()
        self.assertIn('test', result['absence_fired'])
        self.client.post('/emotion/sleep', json={})
        self.engine.last_input_at = time.time() - 120 * 60
        self.engine.last_tick_at = time.time() - 300
        with patch('time.localtime', return_value=time.struct_time((2026, 11, 6, 23, 1, 0, 4, 310, -1))):
            self.assertEqual(self.engine.tick()['absence_fired'], [])

    def test_unanswered_requires_actual_presence_and_outreach(self):
        self.engine.config['unanswered']['hours'] = [0, 24]
        self.engine.last_input_at = time.time() - 60 * 60
        self.assertEqual(self.engine._unanswered_tick(time.time(), 5, 12), [])
        self.client.post('/emotion/outreach', json={'ts': time.time() - 21 * 60})
        self.assertEqual(self.engine._unanswered_tick(time.time(), 5, 12), [])
        self.client.post('/emotion/presence', json={})
        self.assertTrue(self.engine._unanswered_tick(time.time(), 5, 12))

    def test_session_carry_and_reset(self):
        self.engine.update({'upset': .35, 'excitement': .3}, source='internal')
        self.engine.end_session('graceful', carry=['upset'])
        restarted = core.EmotionEngine(CONFIG)
        self.assertEqual(restarted.state['upset'], .35)
        self.assertEqual(restarted.state['excitement'], .1)
        restarted.end_session('graceful', carry=[])
        self.assertEqual(core.EmotionEngine(CONFIG).state['upset'], 0)

    def test_vitals_moved_and_validation(self):
        response = self.client.post('/emotion/update', json={'dimensions': {}, 'moved': True, 'event_id': 'moved-1'})
        self.assertEqual(response.status_code, 200)
        self.assertGreater(self.client.get('/emotion/vitals').json()['contrib']['moved'], 0)
        self.client.post('/emotion/update', json={'dimensions': {}, 'moved': True, 'event_id': 'moved-1'})
        self.assertEqual(self.client.get('/emotion/moved').json()['count'], 1)
        self.assertEqual(self.client.post('/emotion/snapshot', json={'end_type': 'typo'}).status_code, 422)
        self.assertEqual(self.client.post('/emotion/presence', json={'ts': time.time() + 60}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
