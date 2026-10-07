"""Tests for scripts/council_memory.py — run: python tests/test_council_memory.py"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from council_memory import Memory, urlsafe_id  # noqa: E402


class MemoryEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='idc-test-'))
        self.mem = Memory(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_project(self):
        data = self.mem.load()
        self.mem.create_project(data, 'webshop', 'Webbshop MVP', ['webbshop'])
        self.mem.save(data)

    def _roundtrip(self, participants=('TECH', 'CEO')):
        data = self.mem.load()
        self.mem.start(data, 'T1', 'webshop', 'Vilken stack?', 'tech', list(participants))
        self.mem.add_evidence(data, 'T1', [
            {'id': 'E1', 'claim': 'Next.js passar', 'source': 'https://nextjs.org/docs'}])
        for member in participants:
            self.mem.contribute(data, 'T1', member, 'assess ' + member, 'risk ' + member,
                                'rec ' + member, ['a1'], 'Moderate', 'reflect ' + member, ['E1'])
        self.mem.close(data, 'T1', {'status': 'FEASIBLE'},
                       {'status': 'PENDING', 'evidence_refs': [], 'summary': None})
        self.mem.add_lesson(data, 'L1', 'T1', 'webshop', participants[0], 'lesson claim')
        self.mem.save(data)

    def test_empty_store_validates(self):
        self.mem.load()
        self.mem.save(self.mem.load())
        data = self.mem.load()
        self.assertEqual(data['revision'], 0)
        self.assertEqual(data['projects'], {})

    def test_full_roundtrip_and_context(self):
        self._seed_project()
        self._roundtrip()
        data = self.mem.load()
        ep = data['episodes']['T1']
        self.assertEqual(ep['state'], 'CLOSED')
        self.assertEqual(ep['decision']['status'], 'FEASIBLE')
        ctx = self.mem.context(data, 'webshop', 'TECH', 'tech')
        self.assertEqual(len(ctx['current_decisions']), 1)
        self.assertEqual(ctx['lessons'][0]['lesson_id'], 'L1')
        self.assertIsNone(ctx['warning'])

    def test_alias_lookup(self):
        self._seed_project()
        data = self.mem.load()
        self.assertEqual(self.mem.project(data, 'WEBBSHOP')['id'], 'webshop')
        self.assertEqual(self.mem.project_ids(data, 'Webbshop'), ['webshop'])

    def test_unknown_member_rejected(self):
        self._seed_project()
        data = self.mem.load()
        self.mem.start(data, 'T1', 'webshop', 'q?', 'tech', ['TECH'])
        self.mem.save(data)
        data = self.mem.load()
        with self.assertRaises(ValueError):
            self.mem.contribute(data, 'T1', 'CEO', 'a', 'r', 'rec', [], 'Low', 'refl')

    def test_duplicate_contribution_rejected(self):
        self._seed_project()
        self._roundtrip()
        data = self.mem.load()
        with self.assertRaises(ValueError):
            self.mem.contribute(data, 'T1', 'TECH', 'a', 'r', 'rec', [], 'Low', 'refl')

    def test_close_without_participants_rejected(self):
        self._seed_project()
        data = self.mem.load()
        self.mem.start(data, 'T1', 'webshop', 'q?', 'tech', ['TECH', 'OPS'])
        self.mem.contribute(data, 'T1', 'TECH', 'a', 'r', 'rec', [], 'Low', 'refl')
        with self.assertRaises(ValueError):
            self.mem.close(data, 'T1', {'status': 'PILOT'},
                           {'status': 'PENDING', 'evidence_refs': [], 'summary': None})

    def test_bad_evidence_ref_rejected(self):
        self._seed_project()
        data = self.mem.load()
        self.mem.start(data, 'T1', 'webshop', 'q?', 'tech', ['TECH'])
        with self.assertRaises(ValueError):
            self.mem.contribute(data, 'T1', 'TECH', 'a', 'r', 'rec', [], 'Low', 'refl', ['MISSING'])

    def test_observed_outcome_needs_evidence(self):
        self._seed_project()
        self._roundtrip()
        data = self.mem.load()
        data['episodes']['T1']['outcome'] = {'status': 'OBSERVED', 'evidence_refs': [], 'summary': 'x'}
        with self.assertRaises(ValueError):
            self.mem.validate(data)

    def test_duplicate_alias_rejected(self):
        data = self.mem.load()
        self.mem.create_project(data, 'p1', 'Name One', [])
        with self.assertRaises(ValueError):
            self.mem.create_project(data, 'p2', 'name one', [])

    def test_urlsafe_id_format(self):
        tid = urlsafe_id()
        self.assertRegex(tid, r'^\d{14}-[0-9a-f]{6}$')


if __name__ == '__main__':
    unittest.main(verbosity=2)
