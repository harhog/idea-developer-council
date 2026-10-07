"""Tests for app/council.py routing and offline pipeline — run: python tests/test_council.py"""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

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
        self._online = council.llm.online
        council.llm.online = lambda: False  # force offline mode for determinism

    def tearDown(self):
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
