"""Tests for scripts/member_knowledge.py — run: python tests/test_member_knowledge.py"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from member_knowledge import build  # noqa: E402


class MemberKnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='idc-knowledge-'))
        self.knowledge = self.tmp / 'MEMBER_KNOWLEDGE.json'
        self.catalog = self.tmp / 'SOURCE_CATALOG.json'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, knowledge, catalog):
        self.knowledge.write_text(json.dumps(knowledge), encoding='utf-8')
        self.catalog.write_text(json.dumps(catalog), encoding='utf-8')

    def test_repo_knowledge_is_valid(self):
        report = build()
        self.assertTrue(report['ok'], report['errors'])
        self.assertIn('TECH', report['members'])
        self.assertIn('LEGAL', report['members'])
        self.assertEqual(report['warnings'], [])

    def test_unknown_source_ref_fails(self):
        self._write(
            {'TECH': {'primary_lens': 'x', 'topics': ['t'], 'web_access_requested': True,
                      'corpus_status': 'NOT_INGESTED', 'source_refs': ['NOPE']}},
            {'sources': [], 'cards': []})
        report = build(self.knowledge, self.catalog)
        self.assertFalse(report['ok'])
        self.assertTrue(any('NOPE' in e for e in report['errors']))

    def test_missing_field_fails(self):
        self._write({'FIN': {'topics': ['money']}}, {'sources': [], 'cards': []})
        report = build(self.knowledge, self.catalog)
        self.assertFalse(report['ok'])
        self.assertTrue(any('primary_lens' in e for e in report['errors']))

    def test_card_with_partial_coverage_needs_limitations(self):
        self._write(
            {'TECH': {'primary_lens': 'x', 'topics': ['t'], 'web_access_requested': True,
                      'corpus_status': 'NOT_INGESTED', 'source_refs': ['S1']}},
            {'sources': [{'id': 'S1', 'coverage': 'Partial'}],
             'cards': [{'id': 'C1', 'source_id': 'S1', 'members': ['TECH'],
                        'summary': 's', 'limitations': []}]})
        report = build(self.knowledge, self.catalog)
        self.assertFalse(report['ok'])
        self.assertTrue(any('limitations' in e for e in report['errors']))

    def test_card_unknown_member_fails(self):
        self._write(
            {'TECH': {'primary_lens': 'x', 'topics': ['t'], 'web_access_requested': True,
                      'corpus_status': 'NOT_INGESTED', 'source_refs': ['S1']}},
            {'sources': [{'id': 'S1', 'coverage': 'Full'}],
             'cards': [{'id': 'C1', 'source_id': 'S1', 'members': ['GHOST'],
                        'summary': 's', 'limitations': []}]})
        report = build(self.knowledge, self.catalog)
        self.assertFalse(report['ok'])
        self.assertTrue(any('GHOST' in e for e in report['errors']))

    def test_cli_returns_zero_on_repo(self):
        import member_knowledge
        self.assertEqual(member_knowledge.main([]), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
