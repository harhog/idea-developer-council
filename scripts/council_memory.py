#!/usr/bin/env python3
"""Project-scoped council memory. Python standard library; no model calls.
Generic development strategy advisor for technical founders.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone, date

MEMBERS = ('CEO', 'FIN', 'TECH', 'DESIGN', 'LEGAL', 'MARK', 'OPS')
AUDITS = ('FEASIBLE', 'PILOT', 'HOLD', 'NO-GO', 'INSUFFICIENT_EVIDENCE')
CLASSIFICATIONS = ('PRIMARY', 'SECONDARY', 'HINT', 'UNKNOWN')
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / 'memory'

def now():
    return datetime.now(timezone.utc).isoformat()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def text(value):
    return isinstance(value, str) and bool(value.strip())

def key(value):
    require(text(value), 'Name must be non-empty text')
    return value.strip().casefold()

def identifier(value):
    require(text(value) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}', value), 'Invalid identifier')
    return value

def array(value, name):
    require(isinstance(value, list), name + ' must be an array')
    return value

def valid_date(value):
    if value is not None:
        require(text(value), 'Date must be ISO date or null')
        date.fromisoformat(value)

def validate_evidence(rows):
    ids = set()
    for row in array(rows, 'evidence'):
        require(isinstance(row, dict), 'Evidence must be an object')
        eid = identifier(row.get('id'))
        require(eid not in ids, 'Duplicate evidence id')
        ids.add(eid)
        require(text(row.get('claim')), 'Evidence needs claim')
        require(row.get('classification') in CLASSIFICATIONS, 'Invalid evidence classification')
        require(text(row.get('source')), 'Evidence needs traceable source')
        valid_date(row.get('review_due'))
    return ids

class Memory:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.path = self.root / 'store.json'

    def load(self):
        if not self.path.exists():
            return {'schema_version': 1, 'revision': 0, 'projects': {}, 'episodes': {}, 'lessons': {}, 'events': []}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.validate(data)
        return data

    @staticmethod
    def validate(data):
        require(data.get('schema_version') == 1, 'Unsupported schema version')
        require(isinstance(data.get('revision'), int) and data['revision'] >= 0, 'Invalid revision')
        for field in ('projects', 'episodes', 'lessons'):
            require(isinstance(data.get(field), dict), 'Invalid store: ' + field)
        require(isinstance(data.get('events'), list), 'Invalid event log')
        names = set()
        for pid, project in data['projects'].items():
            identifier(pid)
            require(project['id'] == pid, 'Project id mismatch')
            for name in [project['name']] + project['aliases']:
                normalized = key(name)
                require(normalized not in names, 'Ambiguous project alias')
                names.add(normalized)
        for tid, episode in data['episodes'].items():
            identifier(tid)
            require(episode['task_id'] == tid, 'Task id mismatch')
            require(episode['project_id'] in data['projects'], 'Unknown episode project')
            require(episode['state'] in ('OPEN', 'CLOSED'), 'Invalid episode state')
            require(all(m in MEMBERS for m in episode['participants']), 'Unknown member')
            require(len(set(episode['participants'])) == len(episode['participants']), 'Duplicate member')
            eids = validate_evidence(episode['evidence'])
            for contribution in episode['contributions'].values():
                require(set(contribution['evidence_refs']) <= eids, 'Invalid contribution evidence')
                require(text(contribution['reflection']), 'Missing reflection')
                require(contribution['confidence'] in ('High', 'Moderate', 'Low', 'Very Low'), 'Invalid confidence')
            if episode['state'] == 'CLOSED':
                require(set(episode['contributions']) == set(episode['participants']), 'Missing active member reflection')
                require(episode['decision'] is not None, 'Closed task needs decision record')

            decision = episode['decision']
            if decision:
                require(decision['status'] in ('FEASIBLE', 'PILOT', 'HOLD', 'NO-GO', 'INSUFFICIENT_EVIDENCE'), 'Invalid decision status')
                require(decision.get('adil_result') is None or ('LEGAL' in episode['participants'] and decision['adil_result'] in AUDITS), 'Invalid audit result')
                require(decision.get('founder_choice') is None or text(decision.get('founder_choice_source')), 'Founder choice needs explicit source')
            outcome = episode['outcome']
            require(outcome['status'] in ('PENDING', 'OBSERVED', 'INCONCLUSIVE', 'NOT_EXECUTED'), 'Invalid outcome')
            require(set(outcome.get('evidence_refs') or []) <= eids, 'Invalid outcome evidence')
            if outcome['status'] == 'OBSERVED':
                require(outcome.get('evidence_refs') and text(outcome.get('summary')), 'Observed outcome needs evidence')
        for lid, lesson in data['lessons'].items():
            identifier(lid)
            require(lesson['task_id'] in data['episodes'], 'Unknown lesson episode')
            ep = data['episodes'][lesson['task_id']]
            require(lesson['project_id'] == ep['project_id'], 'Lesson project mismatch')
            require(lesson['owner'] in ep['participants'], 'Inactive lesson owner')
            require(lesson['status'] in ('CANDIDATE', 'VALIDATED', 'DISPUTED', 'SUPERSEDED', 'REJECTED'), 'Invalid lesson status')
            require(text(lesson['claim']), 'Lesson needs claim')
            if lesson['status'] == 'VALIDATED':
                require(text(lesson['reviewer']), 'Validated lesson needs reviewer')
                require(set(lesson['evidence_refs']) <= eids, 'Lesson evidence must exist')

    def save(self, data):
        """Atomic save: temp file + fsync + os.replace."""
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.root), prefix='.store-', suffix='.json')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def project(self, data, name):
        """Get project by canonical id, name or case-insensitive alias."""
        name = name.strip()
        if name in data['projects']:
            return data['projects'][name]
        for pid, project in data['projects'].items():
            if key(project['name']) == key(name) or any(key(a) == key(name) for a in project['aliases']):
                return project
        raise ValueError('Unknown project: ' + name)

    def project_ids(self, data, name):
        return [pid for pid, p in data['projects'].items()
                if key(p['name']) == key(name) or any(key(a) == key(name) for a in p['aliases'])]

    def create_project(self, data, id, name, aliases=None):
        require(not id or data['projects'].get(id) is None, 'Project id already exists')
        pid = id or urlsafe_id()
        existing = set()
        for p in data['projects'].values():
            existing.add(key(p['name']))
            existing.update(key(a) for a in p['aliases'])
        require(key(name) not in existing, 'Ambiguous project alias')
        for alias in aliases or []:
            require(key(alias) not in existing, 'Ambiguous project alias')
        data['projects'][pid] = {
            'id': pid,
            'name': name,
            'aliases': aliases or [],
            'created': now(),
            'last_updated': now(),
        }
        return data['projects'][pid]

    def start(self, data, task_id, project, question, task_class, participants, mode='STANDARD'):
        require(task_id not in data['episodes'], 'Task id already exists')
        data['episodes'][task_id] = {
            'task_id': task_id,
            'project_id': project,
            'question': question[:2000],
            'task_class': task_class,
            'mode': mode,
            'participants': participants,
            'state': 'OPEN',
            'evidence': [],
            'contributions': {},
            'decision': None,
            'outcome': {'status': 'PENDING', 'evidence_refs': [], 'summary': None},
            'created': now(),
            'updated': now(),
        }
        return data['episodes'][task_id]

    def contribute(self, data, task_id, member, assessment, risk, recommendation,
                   assumptions, confidence, reflection, evidence_refs=None):
        ep = data['episodes'].get(task_id)
        require(ep is not None, 'Unknown task')
        require(member in ep['participants'], 'Inactive member contribution not allowed')
        if member in ep['contributions']:
            raise ValueError('Contribution already exists. Use update instead.')
        known = {e['id'] for e in ep['evidence']}
        unknown = set(evidence_refs or []) - known
        require(not unknown, 'Unknown evidence refs: ' + ', '.join(sorted(unknown)))
        ep['contributions'][member] = {
            'member': member,
            'assessment': assessment,
            'risk': risk,
            'recommendation': recommendation,
            'assumptions': assumptions,
            'confidence': confidence,
            'reflection': reflection,
            'evidence_refs': evidence_refs or [],
            'created': now(),
        }
        ep['updated'] = now()
        return ep['contributions'][member]

    def add_evidence(self, data, task_id, evidence):
        ep = data['episodes'].get(task_id)
        require(ep is not None, 'Unknown task')
        for e in array(evidence, 'evidence'):
            eid = identifier(e.get('id'))
            require(eid not in {x['id'] for x in ep['evidence']}, 'Duplicate evidence id')
            e['classification'] = e.get('classification') or 'PRIMARY'
            e['source'] = e.get('source') or 'project-memory'
            e['review_due'] = e.get('review_due')
            e['created'] = now()
            ep['evidence'].append(e)
        ep['updated'] = now()
        return ep['evidence']




    def add_lesson(self, data, lesson_id, task_id, project_id, owner, claim,
                   evidence_refs=None, status='CANDIDATE', applicability=None,
                   exclusions=None, invalidation_triggers=None, review_due=None, reviewer=None):
        require(lesson_id not in data['lessons'], 'Lesson id already exists')
        ep = data['episodes'].get(task_id)
        require(ep is not None, 'Unknown episode')
        data['lessons'][lesson_id] = {
            'lesson_id': lesson_id,
            'task_id': task_id,
            'project_id': project_id,
            'owner': owner,
            'claim': claim,
            'status': status,
            'evidence_refs': evidence_refs or [],
            'applicability': applicability or [],
            'exclusions': exclusions or [],
            'invalidation_triggers': invalidation_triggers or [],
            'review_due': review_due,
            'reviewer': reviewer,
            'created': now(),
        }
        return data['lessons'][lesson_id]

    def close(self, data, task_id, decision, outcome, reflections=None):
        ep = data['episodes'].get(task_id)
        require(ep is not None, 'Unknown task')
        require(ep['state'] == 'OPEN', 'Episode is not open')
        require(decision is not None, 'Decision cannot be empty')
        require(outcome is not None, 'Outcome cannot be empty')
        require(set(ep['contributions']) == set(ep['participants']),
                'Every active member must reflect before closing')
        if reflections:
            require(set(reflections) <= set(ep['participants']), 'Unknown reflection owner')
            for member, reflection in reflections.items():
                ep['contributions'][member]['reflection'] = reflection
        outcome.setdefault('evidence_refs', [])
        outcome.setdefault('summary', None)
        decision.setdefault('adil_result', None)
        decision.setdefault('founder_choice', None)
        decision.setdefault('founder_choice_source', None)
        ep['decision'] = decision
        ep['outcome'] = outcome
        ep['updated'] = now()
        ep['state'] = 'CLOSED'
        return ep


    def context(self, data, project_id, member, task_class='generic', limit=3):
        """Prior decisions + lessons for one member in one project."""
        decisions = []
        lessons = []
        for tid, episode in data['episodes'].items():
            if episode['project_id'] != project_id:
                continue
            if episode['state'] != 'CLOSED':
                continue
            if task_class != 'generic' and episode['task_class'] != task_class:
                continue
            contribution = episode['contributions'].get(member)
            if contribution is None or episode['decision'] is None:
                continue
            decision = episode['decision']
            decisions.append({
                'task_id': tid,
                'question': episode['question'],
                'recommendation': contribution['recommendation'],
                'status': decision['status'],
                'adil_result': decision.get('adil_result'),
            })
        for lid, lesson in data['lessons'].items():
            if lesson['project_id'] == project_id and lesson['owner'] == member:
                lessons.append({
                    'lesson_id': lid,
                    'task_id': lesson['task_id'],
                    'claim': lesson['claim'],
                    'status': lesson['status'],
                    'review_due': lesson['review_due'],
                })
        warning = None
        if any(d['status'] == 'NO-GO' for d in decisions):
            warning = 'NO-GO decision exists for this project'
        return {
            'project_id': project_id,
            'member': member,
            'current_decisions': decisions[-limit:],
            'lessons': lessons,
            'warning': warning,
        }

    def list_projects(self, data):
        return list(data['projects'].values())

    def project_history(self, data, project_id):
        return {
            'project': data['projects'].get(project_id, {'id': project_id}),
            'episodes': [ep for ep in data['episodes'].values() if ep['project_id'] == project_id],
        }


def urlsafe_id():
    return datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '-' + os.urandom(3).hex()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Development strategy memory engine')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('validate', help='Validate the store')
    p.add_argument('root', nargs='?', default=str(DEFAULT_ROOT))

    p = sub.add_parser('register', help='Register a project')
    p.add_argument('root', nargs='?', default=str(DEFAULT_ROOT))
    p.add_argument('--id', '-i')
    p.add_argument('--name', '-n', required=True)
    p.add_argument('--aliases', '-a', nargs='*', default=[])

    p = sub.add_parser('start', help='Start a new task')
    p.add_argument('root', nargs='?', default=str(DEFAULT_ROOT))
    p.add_argument('--task-id', '-t')
    p.add_argument('--project', '-p', required=True)
    p.add_argument('--question', '-q', required=True)
    p.add_argument('--task-class', '-c', default='generic')
    p.add_argument('--participants', '-m', nargs='+', required=True)

    p = sub.add_parser('contribute', help='Record a contribution')
    p.add_argument('root', nargs='?', default=str(DEFAULT_ROOT))
    p.add_argument('--task-id', '-t', required=True)
    p.add_argument('--member', '-m', required=True)
    p.add_argument('--assessment', '-a', required=True)
    p.add_argument('--risk', '-r', default='')
    p.add_argument('--recommendation', required=True)
    p.add_argument('--assumptions', nargs='+', default=[])
    p.add_argument('--confidence', default='Moderate')
    p.add_argument('--reflection', '-f', required=True)
    p.add_argument('--evidence-refs', nargs='*', default=[])

    p = sub.add_parser('evidence', help='Record evidence for a task')
    p.add_argument('root', nargs='?', default=str(DEFAULT_ROOT))
    p.add_argument('--task-id', '-t', required=True)
    p.add_argument('--id', '-i', required=True)
    p.add_argument('--claim', '-k', required=True)
    p.add_argument('--classification', '-cls', default='PRIMARY')
    p.add_argument('--source', '-s', required=True)
    p.add_argument('--review-due', '-d', default=None)

    p = sub.add_parser('lesson', help='Create a lesson')
    p.add_argument('root', nargs='?', default=str(DEFAULT_ROOT))
    p.add_argument('--lesson-id', '-l', required=True)
    p.add_argument('--task-id', '-t', required=True)
    p.add_argument('--project', '-p', required=True)
    p.add_argument('--owner', '-o', required=True)
    p.add_argument('--claim', '-k', required=True)
    p.add_argument('--status', '-st', default='CANDIDATE')
    p.add_argument('--evidence-refs', nargs='*', default=[])
    p.add_argument('--reviewer', '-rv', default=None)

    p = sub.add_parser('close', help='Close a task with decision + outcome')
    p.add_argument('root', nargs='?', default=str(DEFAULT_ROOT))
    p.add_argument('--task-id', '-t', required=True)
    p.add_argument('--decision', '-dec', required=True)
    p.add_argument('--outcome', '-o', default='PENDING')

    p = sub.add_parser('context', help='Show member context')
    p.add_argument('root', nargs='?', default=str(DEFAULT_ROOT))
    p.add_argument('--project', '-p', required=True)
    p.add_argument('--member', '-m', required=True)
    p.add_argument('--task-class', '-c', default='generic')

    args = parser.parse_args(argv)
    mem = Memory(Path(args.root))

    if args.command == 'validate':
        data = mem.load()
        print(json.dumps({'valid': True, 'revision': data['revision'],
                          'projects': len(data['projects']),
                          'episodes': len(data['episodes']),
                          'lessons': len(data['lessons'])}, indent=2))
        return

    data = mem.load()

    if args.command == 'register':
        out = mem.create_project(data, args.id, args.name, args.aliases)
    elif args.command == 'start':
        tid = args.task_id or urlsafe_id()
        proj = mem.project(data, args.project)
        out = mem.start(data, tid, proj['id'], args.question, args.task_class, args.participants)
    elif args.command == 'contribute':
        out = mem.contribute(data, args.task_id, args.member, args.assessment,
                             args.risk, args.recommendation, args.assumptions,
                             args.confidence, args.reflection, args.evidence_refs)
    elif args.command == 'evidence':
        out = mem.add_evidence(data, args.task_id, [{
            'id': args.id, 'claim': args.claim,
            'classification': args.classification,
            'source': args.source, 'review_due': args.review_due}])
    elif args.command == 'lesson':
        proj = mem.project(data, args.project)
        out = mem.add_lesson(data, args.lesson_id, args.task_id, proj['id'],
                             args.owner, args.claim, args.evidence_refs,
                             args.status, reviewer=args.reviewer)
    elif args.command == 'close':
        decision = json.loads(args.decision)
        outcome = {'status': args.outcome}
        out = mem.close(data, args.task_id, decision, outcome)
    elif args.command == 'context':
        proj = mem.project(data, args.project)
        print(json.dumps(mem.context(data, proj['id'], args.member, args.task_class), indent=2))
        return

    mem.save(data)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
