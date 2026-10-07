#!/usr/bin/env python3
"""Build and validate member knowledge profiles for the development council.

Reads knowledge/MEMBER_KNOWLEDGE.json and knowledge/SOURCE_CATALOG.json,
verifies every profile is complete and every source reference resolves,
then prints an aggregated report.

Used by: CI (.github/workflows), app/knowledge exports, tests.
Python standard library only.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / 'knowledge'
REQUIRED_FIELDS = ('primary_lens', 'topics', 'web_access_requested', 'corpus_status', 'source_refs')
CORPUS_STATES = ('NOT_INGESTED', 'INGESTED', 'PARTIAL')


def load_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def build(knowledge_path=None, catalog_path=None):
    knowledge_path = Path(knowledge_path or KNOWLEDGE_DIR / 'MEMBER_KNOWLEDGE.json')
    catalog_path = Path(catalog_path or KNOWLEDGE_DIR / 'SOURCE_CATALOG.json')
    members = load_json(knowledge_path)
    catalog = load_json(catalog_path)

    errors = []
    warnings = []
    sources = {s['id']: s for s in catalog.get('sources', [])}
    cards = catalog.get('cards', [])
    card_ids = {c['id'] for c in cards}

    if not members:
        errors.append('MEMBER_KNOWLEDGE.json is empty')

    for name, profile in members.items():
        for field in REQUIRED_FIELDS:
            if field not in profile:
                errors.append(f'{name}: missing field {field}')
        if 'topics' in profile and not profile['topics']:
            errors.append(f'{name}: topics list is empty')
        if 'corpus_status' in profile and profile['corpus_status'] not in CORPUS_STATES:
            errors.append(f'{name}: invalid corpus_status {profile["corpus_status"]}')
        for ref in profile.get('source_refs', []):
            if ref not in sources:
                errors.append(f'{name}: unknown source ref {ref}')
        if profile.get('corpus_status') == 'NOT_INGESTED' and not profile.get('web_access_requested'):
            warnings.append(f'{name}: no corpus ingest and no web access requested')

    for card in cards:
        for field in ('id', 'source_id', 'members', 'summary', 'limitations'):
            if field not in card:
                errors.append(f'card {card.get("id", "?")}: missing field {field}')
        if card.get('source_id') not in sources:
            errors.append(f'card {card.get("id", "?")}: unknown source_id {card.get("source_id")}')
        for member in card.get('members', []):
            if member not in members:
                errors.append(f'card {card.get("id", "?")}: unknown member {member}')
        coverage = sources.get(card.get('source_id'), {}).get('coverage')
        if coverage != 'Full' and card.get('limitations') == []:
            errors.append(f'card {card.get("id", "?")}: partial coverage needs explicit limitations')

    return {
        'members': members,
        'sources': sources,
        'cards': cards,
        'errors': errors,
        'warnings': warnings,
        'ok': not errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build member knowledge report')
    parser.add_argument('--knowledge', default=None, help='Path to MEMBER_KNOWLEDGE.json')
    parser.add_argument('--catalog', default=None, help='Path to SOURCE_CATALOG.json')
    parser.add_argument('--json', action='store_true', help='Print full JSON report')
    parser.add_argument('--strict', action='store_true', help='Exit non-zero on warnings too')
    args = parser.parse_args(argv)

    report = build(args.knowledge, args.catalog)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f'members: {len(report["members"])}  sources: {len(report["sources"])}  cards: {len(report["cards"])}')
        for warning in report['warnings']:
            print(f'WARNING: {warning}')
        for error in report['errors']:
            print(f'ERROR: {error}')
        print('ok' if report['ok'] else 'failed')

    if not report['ok']:
        return 1
    if args.strict and report['warnings']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
