"""Council orchestration: classify brief → route members → roadmap."""
import json
import re
import uuid

from . import llm, memory
from .roles import all_agents, council_order, get_agent

# --- Inträdeskrav (ROADMAP_PROTOCOL.md §1) ---------------------------------
REQUIRED_FIELDS = (
    ('platform', 'plattform (webb / android-spel / android-app / ios)'),
    ('users_target', 'målgrupp i en mening'),
    ('team_size', 'team-storlek'),
)

PLATFORM_KEYWORDS = {
    'web': (r'\b(webb|website|hemsida|webbplats|e-?handel|webshop|saas|landing)\w*',),
    'game': (r'\b(spel|game|android[- ]?spel|mobilt spel|pygame|unity|godot)\w*',),
    'app': (r'\b(app|applikation|mobilapp|android[- ]?app|ios[- ]?app|flutter|react native)\w*',),
}


def classify(brief: str) -> str:
    text = brief.casefold()
    for task_class, patterns in PLATFORM_KEYWORDS.items():
        for pat in patterns:
            if re.search(pat, text):
                return task_class
    return 'tech'


DEFAULT_PARTICIPANTS = {
    'web': ['CEO', 'TECH', 'DESIGN', 'OPS', 'FIN', 'LEGAL', 'MARK'],
    'game': ['CEO', 'TECH', 'DESIGN', 'OPS', 'FIN', 'LEGAL', 'MARK'],
    'app': ['CEO', 'TECH', 'DESIGN', 'OPS', 'FIN', 'LEGAL', 'MARK'],
    'tech': ['TECH', 'OPS'],
    'legal': ['LEGAL'],
}


def select_route(task_class: str) -> list:
    ordered = council_order()
    wanted = DEFAULT_PARTICIPANTS.get(task_class, ['TECH', 'OPS'])
    return [m for m in ordered if m in wanted]


def check_intake(brief: str, restrictions: dict | None = None) -> list:
    """Return list of missing human-readable inputs (else empty list)."""
    missing = []
    text = brief or ''
    if len(text.strip()) < 20:
        missing.append('beskrivning (minst en mening, 20 tecken)')
    restrictions = restrictions or {}
    for key, label in REQUIRED_FIELDS:
        value = restrictions.get(key)
        if not value or not str(value).strip():
            missing.append(label)
    return missing


def _member_messages(member: str, brief: str, restrictions: dict,
                     task_class: str, prior: dict) -> list:
    agent = get_agent(member)
    system = (
        f'{agent["contract"]}\n\n'
        'Du är i ett råd med flera medlemmar. Svara ENBART med ett JSON-objekt '
        'i denna form: {"assessment": str, "risk": str, "recommendation": str, '
        '"assumptions": [str], "confidence": "High|Moderate|Low|Very Low", '
        '"reflection": str, "roadmap_input": {fri struktur relevant för din roll}}. '
        'Inga markdown-fences, inga förklaringar utanför JSON.'
    )
    context_block = json.dumps(prior, ensure_ascii=False) if prior else 'inget tidigare minne'
    user = (
        f'Uppgift: {brief}\n'
        f'Klass: {task_class}\n'
        f'Restriktioner: {json.dumps(restrictions, ensure_ascii=False)}\n'
        f'Tidigare minne för dig: {context_block}'
    )
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def _offline_member(member: str, task_class: str, brief: str) -> dict:
    """Heuristic contribution used when no LLM key is configured."""
    stubs = {
        'CEO': {'recommendation': 'Validera problemet med ett litet experiment innan bygge (E0).',
                'assessment': 'Idé kräver problemvalidering före stackval.'},
        'TECH': {'recommendation': _stack_stub(task_class),
                 'assessment': 'Stackförslag baserat på plattformsklass.'},
        'DESIGN': {'recommendation': 'Skriv kernflödet först, sedan skärmar; WCAG-kontrast 4.5:1.',
                   'assessment': 'UX behöver kernflöde innan gränssnitt.'},
        'OPS': {'recommendation': 'En miljö + CI från dag 1; PaaS före egen server vid litet team.',
                'assessment': 'Drift simplast möjliga initialt.'},
        'FIN': {'recommendation': 'Håll drift under månadsbandet tills första intäkt; räkna intervall.',
                'assessment': 'Kostnad behöver band, inte punktskatt.'},
        'LEGAL': {'recommendation': 'Integritetspolicy + villkor före publicering; GDPR om persondata.',
                  'assessment': 'Baseline-compliance krävs före lansering.'},
        'MARK': {'recommendation': 'En organisk kanal först; betalt först efter bevis.',
                 'assessment': 'Distribution behöver en kanalhypotes.'},
    }
    base = stubs.get(member, {'assessment': 'Ingen stub definierad.', 'recommendation': ''})
    return {
        'member': member,
        'assessment': base['assessment'],
        'risk': 'Heuristik utan LLM-verifiering',
        'recommendation': base['recommendation'],
        'assumptions': ['offline-läge: inget LLM_API_KEY satt'],
        'confidence': 'Low',
        'reflection': 'Ersättningsbidrag i offline-läge; behöver verifieras.',
        'roadmap_input': {},
        'source': 'offline',
    }


def _stack_stub(task_class: str) -> str:
    return {
        'web': 'Next.js/React + Postgres på PaaS (t.ex. Vercel+Neon eller kontainer-VPS)',
        'game': 'Godot 4 (2D/3D, öppen licens) eller Unity om 3D-pipeline krävs; C# eller GDScript',
        'app': 'Flutter (en kodbas iOS+Android) eller React Native om teamet kan JS/TS',
        'tech': 'Enklast möjliga stack som matchar teamets befintliga kunskap',
    }.get(task_class, 'Välj efter plattform; se TECH-kontraktet.')


# --- Pipeline --------------------------------------------------------------
def _collect_contributions(task_class: str, brief: str, restrictions: dict,
                           project_id: str) -> tuple:
    members = select_route(task_class)
    contributions = []
    mode = 'offline'
    for member in members:
        try:
            prior = memory.context(project_id, member, task_class)
        except Exception:
            prior = {'current_decisions': [], 'lessons': []}
        if llm.online():
            mode = 'online'
            raw = llm.chat(_member_messages(member, brief, restrictions, task_class, prior),
                           json_mode=True)
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f'{member} returned non-JSON: {raw[:200]}') from exc
            parsed['member'] = member
            parsed.setdefault('source', 'llm')
            contributions.append(parsed)
        else:
            contributions.append(_offline_member(member, task_class, brief))
    return contributions, mode


def _decision_for(contributions: list, members: list) -> dict:
    """Deterministic decision rules (ROADMAP_PROTOCOL.md §4)."""
    by_member = {c['member']: c for c in contributions}
    legal = by_member.get('LEGAL')
    if legal and re.search(r'blocker|ej tillåtet|förbjuden',
                           (legal.get('risk', '') + legal.get('assessment', '')).casefold()):
        return {'status': 'NO-GO', 'reason': 'LEGAL blockerar: ' + legal.get('risk', '')[:300],
                'adil_result': 'NO-GO', 'founder_choice': None, 'founder_choice_source': None}
    if len(contributions) < len(members):
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Alla medlemmar måste bidra',
                'adil_result': None, 'founder_choice': None, 'founder_choice_source': None}
    return {'status': 'PILOT', 'reason': 'Rådet rekommenderar pilot: bygg litet, mät, skala sedan',
            'adil_result': None, 'founder_choice': None, 'founder_choice_source': None}



def _assemble_roadmap(task_class: str, brief: str, contributions: list, decision: dict) -> dict:
    by_member = {c['member']: c for c in contributions}
    tech = by_member.get('TECH', {})
    ops = by_member.get('OPS', {})
    legal = by_member.get('LEGAL', {})
    fin = by_member.get('FIN', {})
    roadmap_input = tech.get('roadmap_input') or {}

    stack = [{
        'area': 'primary',
        'choice': roadmap_input.get('stack') or tech.get('recommendation', _stack_stub(task_class)),
        'why': roadmap_input.get('why') or 'Passar plattform och teamstorlek (TECH)',
        'alternative': roadmap_input.get('alternative') or 'Samma plattform med mindre ramverk om teamet är 1 person',
    }]
    architecture = roadmap_input.get('architecture') or {
        'web': ' [Webbklient] -> [API] -> [Databas]\n              \\-> [Betalning, e-post]',
        'game': ' [Spelmotor] -> [Game server / lokal] -> [Leaderboard-db]\n                         \\-> [Analys]',
        'app': ' [Flutter-app] -> [API] -> [Databas]\n                    \\-> [Push-notiser]',
    }.get(task_class, ' [Klient] -> [API] -> [Databas]')

    phases = [
        {'id': 'E0', 'name': 'Validering', 'criteria': 'Problemexperiment + teknisk spik bekräftad', 'duration': '1–2 veckor'},
        {'id': 'E1', 'name': 'MVP', 'criteria': 'Kernflöde klar för 10 riktiga användare utan hjälp', 'duration': '2–6 veckor'},
        {'id': 'E2', 'name': 'Hårdning', 'criteria': 'Policyer publicerade, övervakning + backup aktiv', 'duration': '1–2 veckor'},
        {'id': 'E3', 'name': 'Tillväxt', 'criteria': 'Första kanal bevisad + första betalande kund', 'duration': 'löpande'},
    ]
    return {
        'decision': decision,
        'stack': stack,
        'architecture': architecture,
        'server': {
            'recommendation': ops.get('recommendation', 'PaaS med CI från dag 1'),
            'note': fin.get('recommendation', 'Håll driftkostnaden i band'),
        },
        'legal': {
            'must_have': ['Integritetspolicy om persondata hanteras',
                          'Villkor/användaravtal',
                          'Licenser i kodbasen dokumenterade'],
            'blockers': legal.get('risk', ''),
            'note': 'Kontrollera med juridik före lansering',
        },
        'phases': phases,
        'risks': [c.get('risk', '') for c in contributions if c.get('risk')],
        'assumptions': [a for c in contributions for a in c.get('assumptions', [])],
        'next_experiment': by_member.get('CEO', {}).get(
            'recommendation', 'Formulera problemet och testa med 5 målgruppsintervjuer'),
    }


def run_council(brief: str, restrictions: dict | None = None,
                project_id: str | None = None, store: bool = True) -> dict:
    """Full pipeline: intake → route → contributions → decision → roadmap → memory."""
    restrictions = restrictions or {}
    missing = check_intake(brief, restrictions)
    if missing:
        return {'status': 'INSUFFICIENT_EVIDENCE', 'missing': missing}

    task_class = classify(brief)
    project_id = project_id or ('proj-' + uuid.uuid4().hex[:8])
    members = select_route(task_class)

    contributions, mode = _collect_contributions(task_class, brief, restrictions, project_id)
    decision = _decision_for(contributions, members)
    roadmap = _assemble_roadmap(task_class, brief, contributions, decision)
    roadmap.update({
        'project_id': project_id,
        'task_class': task_class,
        'mode': mode,
        'brief': brief,
        'members': members,
        'contributions': contributions,
        'sections_order': ['decision', 'stack', 'architecture', 'server', 'legal',
                           'phases', 'risks', 'assumptions', 'next_experiment'],
    })

    if store:
        task_id = 'T-' + uuid.uuid4().hex[:8]
        try:
            memory.record_advice(
                project_id=project_id, task_id=task_id, question=brief[:500],
                task_class=task_class, participants=members,
                contributions=[{k: c.get(k) for k in
                                ('member', 'assessment', 'risk', 'recommendation',
                                 'assumptions', 'confidence', 'reflection')}
                               for c in contributions],
                decision=decision, evidence=[],
            )
            roadmap['task_id'] = task_id
        except Exception as exc:  # memory never breaks advice delivery
            roadmap['memory_error'] = str(exc)
    return roadmap
