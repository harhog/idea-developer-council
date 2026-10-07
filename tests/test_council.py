"""Tests for app/council.py routing and offline pipeline — run: python tests/test_council.py"""
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from app import council  # noqa: E402
from app.roles import all_agents, council_order, get_agent  # noqa: E402
from council_memory import Memory  # noqa: E402

FULL_BRIEF = ('Jag vill bygga ett Android-spel där vänner tävlar om poäng, '
              '2 utvecklare, lansering om 3 månader')
RESTRICTIONS = {'platform': 'android-spel', 'users_target': 'tonåringar i Norden',
                'team_size': '2 utvecklare', 'budget': '5000 kr'}


class ClassificationTest(unittest.TestCase):
    def test_web(self):
        self.assertEqual(council.classify('En webbshop för kaffe'), 'web')

    def test_game(self):
        self.assertEqual(council.classify('Ett android-spel med fysik'), 'game')

    def test_app(self):
        self.assertEqual(council.classify('En mobilapp för vanor'), 'app')

    def test_fallback_tech(self):
        self.assertEqual(council.classify('Hur gör jag en binär sökning?'), 'tech')


class RoutingTest(unittest.TestCase):
    def test_agents_exist(self):
        agents = all_agents()
        for name in ('CHAIR', 'CEO', 'TECH', 'DESIGN', 'OPS', 'FIN', 'LEGAL', 'MARK'):
            self.assertIn(name, agents)

    def test_contract_headings(self):
        for name in all_agents():
            contract = get_agent(name)['contract']
            for heading in ('# ', '## Indata', '## Utdata'):
                self.assertIn(heading, contract, f'{name} missing {heading}')

    def test_order_excludes_chair(self):
        order = council_order()
        self.assertNotIn('CHAIR', order)
        self.assertEqual(order[0], 'CEO')

    def test_web_route_is_full_council(self):
        self.assertEqual(len(council.select_route('web')), 7)

    def test_tech_route_is_narrow(self):
        self.assertEqual(council.select_route('tech'), ['TECH', 'OPS'])


class IntakeTest(unittest.TestCase):
    def test_missing_everything(self):
        self.assertEqual(len(council.check_intake('kort')), 4)

    def test_complete_intake(self):
        self.assertEqual(council.check_intake(FULL_BRIEF, RESTRICTIONS), [])


class OfflinePipelineTest(unittest.TestCase):
    """run_council without LLM key (offline mode) against a temp store."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='idc-council-'))
        council.memory._memory = Memory(self.tmp)
        from app import memory as mem
        self._hist_file = mem.HISTORY_FILE
        mem.HISTORY_FILE = self.tmp / 'history.json'
        self._online = council.llm.online
        council.llm.online = lambda: False  # force offline mode for determinism

    def tearDown(self):
        from app import memory as mem
        mem.HISTORY_FILE = self._hist_file
        council.llm.online = self._online
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_game_roadmap_structure(self):
        result = council.run_council(FULL_BRIEF, RESTRICTIONS, project_id='game-demo')
        self.assertEqual(result['task_class'], 'game')
        self.assertEqual(result['decision']['status'], 'PILOT')
        for section in ('stack', 'architecture', 'server', 'legal', 'phases',
                        'risks', 'assumptions', 'next_experiment'):
            self.assertIn(section, result)
        self.assertEqual(len(result['phases']), 4)
        self.assertTrue(result['members'])
        self.assertEqual(result['model'], 'offline')

    def test_intake_blocks_incomplete(self):
        result = council.run_council('hej', {}, store=False)
        self.assertEqual(result['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertTrue(result['missing'])

    def test_result_is_stored_in_memory(self):
        result = council.run_council(FULL_BRIEF, RESTRICTIONS, project_id='game-demo2')
        self.assertIn('task_id', result)
        ctx = council.memory.context('game-demo2', 'TECH', 'game')
        self.assertGreaterEqual(len(ctx['current_decisions']), 1)


class UIApiTest(unittest.TestCase):
    """Smoke tests for the built-in web UI (no httpx/TestClient needed)."""

    def test_index_route_serves_existing_html(self):
        from app.main import home
        resp = home()
        page = Path(str(resp.path))
        self.assertTrue(str(page).replace('\\', '/').endswith('static/index.html'))
        html = page.read_text(encoding='utf-8')
        self.assertIn('Idea Developer Council', html)
        self.assertIn("fetch('/roadmap'", html)
        self.assertIn('INSUFFICIENT_EVIDENCE', html)

    def test_app_registers_root_route(self):
        from app.main import app
        paths = [r.path for r in app.routes]
        self.assertIn('/', paths)
        self.assertIn('/roadmap', paths)
        self.assertIn('/history', paths)
        self.assertIn('/history/{run_id}', paths)
        self.assertIn('/models', paths)

    def test_index_offers_history_ui(self):
        from app.main import home
        html = Path(home().path).read_text(encoding='utf-8')
        self.assertIn("fetch('/history'", html)
        self.assertIn('Tidigare svar', html)
        self.assertIn('showRun', html)
        self.assertIn('loadHistory', html)


class LLMModelsTest(unittest.TestCase):
    """Model list + JSON tolerance + health info (no network)."""

    def test_parse_models_free_first(self):
        from app import llm
        data = {'data': [{'id': 'paid/x'}, {'id': 'a/b:free'}, {'id': 'openrouter/free'}]}
        models = llm.parse_models(data)
        self.assertEqual(len(models), 3)
        self.assertTrue(models[0]['free'], 'gratismodeller ska komma först')
        by_id = {m['id']: m['free'] for m in models}
        self.assertTrue(by_id['a/b:free'])
        self.assertTrue(by_id['openrouter/free'])
        self.assertFalse(by_id['paid/x'])

    def test_extract_json_tolerates_fences_and_prose(self):
        from app import llm
        self.assertEqual(llm.extract_json('```json\n{"ok": true}\n```'), {'ok': True})
        self.assertEqual(llm.extract_json('Här är svaret: {"ok": false} / slut'),
                         {'ok': False})
        with self.assertRaises(RuntimeError):
            llm.extract_json('ingen json här')

    def test_models_endpoint_uses_cache(self):
        from app import llm
        from app.main import models as models_route
        seed = (llm._MODELS_CACHE['at'], llm._MODELS_CACHE['data'])
        try:
            llm._MODELS_CACHE['at'] = time.monotonic()
            llm._MODELS_CACHE['data'] = {
                'models': [{'id': 'x/y:free', 'free': True}],
                'default': 'openrouter/free', 'source': 'live'}
            out = models_route()
            self.assertEqual(out['source'], 'live')
            self.assertEqual(out['models'][0]['id'], 'x/y:free')
            self.assertIn('default', out)
        finally:
            llm._MODELS_CACHE['at'], llm._MODELS_CACHE['data'] = seed

    def test_health_reports_llm_state(self):
        from app.main import health
        h = health()
        self.assertIn(h['llm_mode'], ('online', 'offline'))
        self.assertIn('model', h)
        self.assertIn('base_url', h)


class HistoryTest(unittest.TestCase):
    """memory/history.json — spara och bläddra bland tidigare svar."""

    def setUp(self):
        from app import memory as mem
        self.tmp = Path(tempfile.mkdtemp(prefix='idc-history-'))
        self._hfile, self._hlimit = mem.HISTORY_FILE, mem.HISTORY_LIMIT
        mem.HISTORY_FILE = self.tmp / 'history.json'
        self._mem = council.memory._memory
        council.memory._memory = Memory(self.tmp)
        self._online = council.llm.online
        council.llm.online = lambda: False

    def tearDown(self):
        from app import memory as mem
        mem.HISTORY_FILE, mem.HISTORY_LIMIT = self._hfile, self._hlimit
        council.memory._memory = self._mem
        council.llm.online = self._online
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _minimal(**over):
        d = {'project_id': 'p1', 'brief': 'En webbshop för kaffe',
             'decision': {'status': 'PILOT'}, 'task_class': 'web',
             'mode': 'offline', 'model': 'offline',
             'contributions': [{'member': 'TECH', 'source': 'offline'}],
             'sections_order': ['decision']}
        d.update(over)
        return d

    def test_record_list_and_get_run(self):
        from app import memory as mem
        rid = mem.record_run(self._minimal())
        self.assertTrue(rid.startswith('R-'))
        runs = mem.list_runs()
        self.assertEqual(len(runs), 1)
        self.assertNotIn('roadmap', runs[0], 'listningar ska vara lättvägta')
        self.assertEqual(runs[0]['run_id'], rid)
        self.assertEqual(runs[0]['decision'], 'PILOT')
        entry = mem.get_run(rid)
        self.assertIn('roadmap', entry)
        self.assertEqual(entry['brief'], 'En webbshop för kaffe')
        self.assertEqual(entry['roadmap']['run_id'], rid)

    def test_unknown_run_raises_value_error(self):
        from app import memory as mem
        with self.assertRaises(ValueError):
            mem.get_run('R-nope')

    def test_history_is_capped_and_newest_first(self):
        from app import memory as mem
        mem.HISTORY_LIMIT = 2
        ids = [mem.record_run(self._minimal(n=n)) for n in range(4)]
        runs = mem.list_runs()
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]['run_id'], ids[-1], 'senaste först')
        self.assertEqual(runs[1]['run_id'], ids[-2])

    def test_offline_council_run_is_saved_with_task_and_run_id(self):
        # Regression: 'Missing reflection' kraschade tidigare lagringen.
        result = council.run_council(FULL_BRIEF, RESTRICTIONS, project_id='hist-p')
        self.assertIn('task_id', result)
        self.assertNotIn('memory_error', result)
        self.assertIn('run_id', result)
        self.assertNotIn('history_error', result)
        from app import memory as mem
        entry = mem.get_run(result['run_id'])
        self.assertIn('stack', entry['roadmap'])
        self.assertIn('contributions', entry['roadmap'])
        self.assertEqual(entry['task_id'], result['task_id'])
        ctx = council.memory.context('hist-p', 'TECH', 'game')
        self.assertGreaterEqual(len(ctx['current_decisions']), 1)

    def test_store_false_writes_nothing(self):
        from app import memory as mem
        result = council.run_council(FULL_BRIEF, RESTRICTIONS, store=False)
        self.assertNotIn('run_id', result)
        self.assertNotIn('task_id', result)
        self.assertEqual(mem.list_runs(), [])

    def test_history_api_routes(self):
        from app import memory as mem
        from app.main import history_list, history_run
        from fastapi import HTTPException
        rid = mem.record_run(self._minimal())
        self.assertEqual(history_list()['runs'][0]['run_id'], rid)
        self.assertEqual(history_run(rid)['run_id'], rid)
        with self.assertRaises(HTTPException) as ctx:
            history_run('R-nope')
        self.assertEqual(ctx.exception.status_code, 404)


class LLMResilienceTest(unittest.TestCase):
    """chat/_post: retries, JSON-tolerans och felkoder — helt utan nätverk."""

    def setUp(self):
        from app import llm
        self.llm = llm
        self._online = llm.online
        llm.online = lambda: True

    def tearDown(self):
        self.llm.online = self._online

    @staticmethod
    def _body(content):
        return {'choices': [{'message': {'content': content}}]}

    def test_looks_like_json_classifies_replies(self):
        llm = self.llm
        self.assertTrue(llm._looks_like_json('{"a": 1}'))
        self.assertTrue(llm._looks_like_json('  ```json\n{"a": 1}'))
        self.assertTrue(llm._looks_like_json('Här: {"assessment": "x"}'))
        self.assertFalse(llm._looks_like_json('User Safety: safe'))
        self.assertFalse(llm._looks_like_json('Låt mig tänka igenom detta först...'))

    def test_chat_retries_on_junk_content(self):
        llm = self.llm
        calls = []

        def fake_post(path, payload):
            calls.append(payload)
            if len(calls) == 1:
                return self._body('User Safety: safe')
            return self._body('{"assessment":"a","recommendation":"r"}')

        with mock.patch.object(llm, '_post', fake_post):
            out = llm.chat([{'role': 'user', 'content': 'x'}], json_mode=True)
        self.assertEqual(len(calls), 2, 'skräpsvar ska ge exakt ett nyförsök')
        self.assertIn('assessment', out)

    def test_chat_drops_response_format_on_http_400(self):
        llm = self.llm
        calls = []

        def fake_post(path, payload):
            calls.append(payload)
            if 'response_format' in payload:
                raise RuntimeError('LLM HTTP 400: response_format is not supported')
            return self._body('{"ok": true}')

        with mock.patch.object(llm, '_post', fake_post):
            out = llm.chat([{'role': 'user', 'content': 'x'}], json_mode=True)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('response_format', calls[1])
        self.assertEqual(json.loads(out), {'ok': True})

    def test_post_retries_http_500_then_succeeds(self):
        import io
        import urllib.error
        llm = self.llm
        calls = {'n': 0}

        class Resp:
            def read(self):
                return b'{"choices": []}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.HTTPError(
                    req.full_url, 500, 'Server Error', {},
                    io.BytesIO(b'{"error":"empty response content"}'))
            return Resp()

        with mock.patch.object(llm.urllib.request, 'urlopen', fake_urlopen), \
                mock.patch.object(llm.time, 'sleep', lambda s: None):
            out = llm._post('/chat/completions', {'x': 1})
        self.assertEqual(calls['n'], 2)
        self.assertIn('choices', out)

    def test_post_retries_timeout_then_succeeds(self):
        llm = self.llm
        calls = {'n': 0}

        class Resp:
            def read(self):
                return b'{"ok": 1}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            calls['n'] += 1
            if calls['n'] == 1:
                raise TimeoutError('The read operation timed out')
            return Resp()

        with mock.patch.object(llm.urllib.request, 'urlopen', fake_urlopen), \
                mock.patch.object(llm.time, 'sleep', lambda s: None):
            out = llm._post('/chat/completions', {'x': 1})
        self.assertEqual(calls['n'], 2)
        self.assertEqual(out, {'ok': 1})


class CouncilOnlineResilienceTest(unittest.TestCase):
    """Medlemsnivån online: 2 försök, validering och tydlig fallback."""

    def setUp(self):
        from app import memory as mem
        self.tmp = Path(tempfile.mkdtemp(prefix='idc-online-'))
        self._mem = council.memory._memory
        council.memory._memory = Memory(self.tmp)
        self._hfile = mem.HISTORY_FILE
        mem.HISTORY_FILE = self.tmp / 'history.json'
        self._online = council.llm.online
        council.llm.online = lambda: True

    def tearDown(self):
        from app import memory as mem
        mem.HISTORY_FILE = self._hfile
        council.memory._memory = self._mem
        council.llm.online = self._online
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _valid(**over):
        d = {'assessment': 'Använd Postgres + Prisma', 'risk': 'Ingen',
             'recommendation': 'Bygg MVP först', 'assumptions': ['A'],
             'confidence': 'High', 'reflection': 'Ser över tid'}
        d.update(over)
        return json.dumps(d)

    def test_member_retries_then_succeeds(self):
        calls = []

        def fake_chat(messages, **kw):
            calls.append(kw)
            if len(calls) == 1:
                raise RuntimeError('LLM HTTP 500: empty response content')
            return self._valid()

        with mock.patch.object(council.llm, 'chat', fake_chat):
            contrib, err = council._one_contribution(
                'TECH', FULL_BRIEF, RESTRICTIONS, 'game', 'p1', None)
        self.assertIsNone(err)
        self.assertEqual(contrib['source'], 'llm')
        self.assertEqual(contrib['confidence'], 'High')
        self.assertEqual(len(calls), 2, 'första felet ska ge ett nyförsök')

    def test_member_falls_back_after_two_failures(self):
        with mock.patch.object(council.llm, 'chat',
                               side_effect=RuntimeError('read timed out')):
            contrib, err = council._one_contribution(
                'TECH', FULL_BRIEF, RESTRICTIONS, 'game', 'p1', None)
        self.assertEqual(contrib['source'], 'offline-fallback')
        self.assertIn('efter 2 försök', err)
        self.assertIn('TECH', err)

    def test_incomplete_json_answer_falls_back(self):
        with mock.patch.object(council.llm, 'chat', return_value='{"foo": 1}'):
            contrib, err = council._one_contribution(
                'TECH', FULL_BRIEF, RESTRICTIONS, 'game', 'p1', None)
        self.assertEqual(contrib['source'], 'offline-fallback')
        self.assertIn('assessment/recommendation', err)

    def test_normalizes_confidence_and_reflection(self):
        with mock.patch.object(council.llm, 'chat',
                               return_value=self._valid(confidence='Extreme')):
            contrib, _ = council._one_contribution(
                'TECH', FULL_BRIEF, RESTRICTIONS, 'game', 'p1', None)
        self.assertEqual(contrib['confidence'], 'Moderate')
        self.assertTrue(contrib['reflection'].strip())
        with mock.patch.object(council.llm, 'chat',
                               return_value=self._valid(confidence='high')):
            contrib2, _ = council._one_contribution(
                'TECH', FULL_BRIEF, RESTRICTIONS, 'game', 'p1', None)
        self.assertEqual(contrib2['confidence'], 'High')
        with mock.patch.object(council.llm, 'chat',
                               return_value=self._valid(confidence='')):
            contrib3, _ = council._one_contribution(
                'TECH', FULL_BRIEF, RESTRICTIONS, 'game', 'p1', None)
        self.assertEqual(contrib3['confidence'], 'Moderate')

    def test_full_online_council_always_answers_even_if_all_llm_fail(self):
        def broken(*a, **kw):
            raise RuntimeError('modellen svarar inte')

        with mock.patch.object(council.llm, 'chat', broken):
            result = council.run_council(FULL_BRIEF, RESTRICTIONS,
                                         project_id='online-fail')
        # Alla medlemmar föll → svaret är rent heuristik (mode offline),
        # men FELEN från online-försöken ska rapporteras tydligt:
        self.assertEqual(result['mode'], 'offline')
        self.assertEqual(len(result.get('llm_errors', [])), len(result['members']))
        self.assertTrue(all(c['source'] == 'offline-fallback'
                            for c in result['contributions']))
        self.assertIn('efter 2 försök', result['llm_errors'][0])
        self.assertIn('task_id', result, 'lagringen ska inte krascha')
        self.assertNotIn('memory_error', result)
        self.assertIn('run_id', result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
