"""Bridge to scripts/council_memory.py (stdlib memory engine)."""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
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

# --- Rondhistorik (hela svaren, bläddringsbar via GET /history) --------------
# Separat från store.json: engine:s schema är låst, och här vill vi spara
# exakt det rådet svarade (sektioner + bidrag + model/mode/fel).
HISTORY_FILE = DEFAULT_ROOT / 'history.json'
HISTORY_LIMIT = 100


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


# --- Rondhistorik -----------------------------------------------------------
def _history_load() -> list:
    if not HISTORY_FILE.exists():
        return []
    raw = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
    if not isinstance(raw, list):
        raise ValueError('history.json innehåller inte en lista')
    return raw


def _history_save(runs: list) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(runs, ensure_ascii=False, indent=1),
                   encoding='utf-8')
    os.replace(tmp, HISTORY_FILE)


def record_run(roadmap: dict) -> str:
    """Spara en fullständig rådsron till historiken. Returnerar run_id."""
    run_id = 'R-' + uuid.uuid4().hex[:8]
    stored = dict(roadmap)
    stored['run_id'] = run_id
    sources: dict = {}
    for c in stored.get('contributions', []):
        src = str(c.get('source') or 'llm')
        sources[src] = sources.get(src, 0) + 1
    entry = {
        'run_id': run_id,
        'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'project_id': stored.get('project_id'),
        'task_id': stored.get('task_id'),
        'brief': str(stored.get('brief') or ''),
        'decision': (stored.get('decision') or {}).get('status'),
        'task_class': stored.get('task_class'),
        'mode': stored.get('mode'),
        'model': stored.get('model'),
        'sources': sources,
        'llm_errors': len(stored.get('llm_errors') or []),
        'memory_error': stored.get('memory_error'),
        'roadmap': stored,
    }
    runs = _history_load()
    runs.insert(0, entry)
    del runs[HISTORY_LIMIT:]
    _history_save(runs)
    return run_id


def list_runs() -> list:
    """Summeringar, senast först — utan den tunga roadmap-delen."""
    return [{k: v for k, v in e.items() if k != 'roadmap'}
            for e in _history_load()]


def get_run(run_id: str) -> dict:
    for entry in _history_load():
        if entry.get('run_id') == run_id:
            return entry
    raise ValueError(f'Okänt kör-id: {run_id}')
