"""Agent role registry — loads contracts from agents/*.md."""
from functools import lru_cache
from pathlib import Path
import re

AGENTS_DIR = Path(__file__).resolve().parents[1] / 'agents'

# Order matters: this is the rådslagningsordningen (CHAIR.md STEG 3).
AGENT_ORDER = ('CHAIR', 'CEO', 'TECH', 'DESIGN', 'OPS', 'FIN', 'LEGAL', 'MARK')

REQUIRED_HEADINGS = ('# Roll', '## Indata', '## Utdata')


def _parse_contract(name: str, raw: str) -> dict:
    missing = [h for h in REQUIRED_HEADINGS if h not in raw]
    if missing:
        raise ValueError(f'agents/{name}.md missing headings: {missing}')
    primary = None
    m = re.search(r'Prim[äa]rt perspektiv\s*\n+([^\n]+)', raw)
    if m:
        primary = m.group(1).strip()
    return {
        'name': name,
        'contract': raw,
        'primary_lens': primary,
        'readable': True,
        'writable': False,
    }


@lru_cache(maxsize=1)
def load_agents() -> dict:
    agents = {}
    for path in sorted(AGENTS_DIR.glob('*.md')):
        raw = path.read_text(encoding='utf-8')
        agents[path.stem] = _parse_contract(path.stem, raw)
    return agents


def all_agents() -> dict:
    return load_agents()


def get_agent(name: str) -> dict:
    agents = load_agents()
    if name not in agents:
        raise KeyError(f'Unknown agent: {name}. Known: {sorted(agents)}')
    return agents[name]


def council_order() -> list:
    """Members in deliberation order, excluding CHAIR (the orchestrator)."""
    agents = load_agents()
    ordered = [n for n in AGENT_ORDER if n in agents and n != 'CHAIR']
    rest = sorted(n for n in agents if n not in AGENT_ORDER and n != 'CHAIR')
    return ordered + rest
