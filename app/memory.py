"""Bridge to scripts/council_memory.py (stdlib memory engine)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from council_memory import (  # noqa: E402
    AUDITS,
    CLASSIFICATIONS,
    DEFAULT_ROOT,
    MEMBERS,
    Memory,
    urlsafe_id,
)

_memory = Memory(DEFAULT_ROOT)


def get_memory() -> Memory:
    return _memory


def load():
    return _memory.load()


def save(data):
    _memory.save(data)


def register(project_id: str, name: str, aliases=None) -> dict:
    data = load()
    project = _memory.create_project(data, project_id, name, aliases or [])
    save(data)
    return project


def context(project_id: str, member: str, task_class: str = 'generic') -> dict:
    data = load()
    return _memory.context(data, project_id, member, task_class)


def projects() -> list:
    return _memory.list_projects(load())


def validate() -> dict:
    data = load()
    return {
        'valid': True,
        'revision': data['revision'],
        'projects': len(data['projects']),
        'episodes': len(data['episodes']),
        'lessons': len(data['lessons']),
    }


def record_advice(project_id: str, task_id: str, question: str, task_class: str,
                  participants: list, contributions: list, decision: dict,
                  evidence: list, lesson: dict | None = None) -> dict:
    """Write one full council round-trip to memory. Atomic and validated."""
    data = load()
    if project_id not in data['projects']:
        _memory.create_project(data, project_id, project_id, [])
    _memory.start(data, task_id, project_id, question, task_class, participants)
    if evidence:
        _memory.add_evidence(data, task_id, evidence)
    for contribution in contributions:
        _memory.contribute(
            data, task_id,
            contribution['member'], contribution['assessment'],
            contribution.get('risk', ''), contribution['recommendation'],
            contribution.get('assumptions', []), contribution.get('confidence', 'Moderate'),
            contribution['reflection'], contribution.get('evidence_refs', []),
        )
    outcome = {'status': 'PENDING', 'evidence_refs': [], 'summary': None}
    _memory.close(data, task_id, decision, outcome)
    if lesson:
        _memory.add_lesson(
            data, lesson['lesson_id'], task_id, project_id,
            lesson['owner'], lesson['claim'],
            lesson.get('evidence_refs', []), lesson.get('status', 'CANDIDATE'),
            reviewer=lesson.get('reviewer'),
        )
    save(data)
    return {'task_id': task_id, 'stored': True}
