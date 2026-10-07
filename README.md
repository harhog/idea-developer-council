# Idea Developer Council

Ett program som ger utvecklare och kreatörer en **komplett roadmap och råd**
när de ska bygga en webbplats, ett Android-spel eller en app: teknikstack,
arkitektur, serverval, juridik, etapper och genomförbarhet — sammanställt
av ett råd av sju specialister med spårbar minne och källor.

## Medlemmar (agenter)

| Agent | Roll |
|---|---|
| **CHAIR** | Samordnare: klassificerar, kallar in, sammanställer roadmappen |
| **CEO** | Idévalidering, MVP-scope, go/no-go |
| **TECH** | Stackval, arkitektur, teknisk genomförbarhet |
| **DESIGN** | UX, tillgänglighet (WCAG), game feel |
| **OPS** | Server/hosting, CI/CD, backup, skalning |
| **FIN** | Kostnad, budget, break-even |
| **LEGAL** | GDPR, villkor, licenser, butikspolicy (compliance-gate) |
| **MARK** | Positionering, kanaler, lansering |

Varje agent har ett kontrakt i [`agents/`](agents/) med roll, indata och
obligatoriskt utdataformat. Kunskapsbasen ligger i
[`knowledge/`](knowledge/) och protokollen i [`protocols/`](protocols/).

## Så fungerar det

1. **Intäke** — brief + restriktioner (plattform, målgrupp, team, budget).
   Saknas något → `INSUFFICIENT_EVIDENCE` med lista vad som fattas.
2. **Klassificering** — `web` / `game` / `app` / `tech` / `legal` styr vilka
   medlemmar som kallas in.
3. **Kontext** — varje medlem läser sitt minne (`context`) innan den svarar.
4. **Bidrag** — varje medlem svarar i sitt eget format enligt sitt kontrakt.
5. **Beslut** — deterministiska regler: `FEASIBLE` / `PILOT` / `HOLD` /
   `NO-GO` / `INSUFFICIENT_EVIDENCE`. LEGAL blockerar alltid.
6. **Roadmap** — obligatoriska sektioner: beslut → tekniker → arkitektur →
   server & drift → juridik → etapper med mätbara kriterier → risker →
   nästa experiment.
7. **Minne** — hela ronden skrivs till JSON-butiken med atomiska skrivningar
   och explicit validering (`scripts/council_memory.py`).

## Kom igång

```bash
pip install -r requirements.txt
cp .env.example .env        # valfritt: lägg LLM_API_KEY för onlineläge

uvicorn app.main:app --reload
```

Öppna sedan **http://127.0.0.1:8000/** i webbläsaren — där finns ett
inbyggt **webb-UI** (svenskt, mörkt, inga externa beroenden): fyll i brief
och restriktioner, klicka **"Få råd av rådet"** och se beslut, roadmap-sektioner
(etapper som tabell) och varje medlems bidrag renderade direkt. Statusraden
visar LLM-läge (online/offline) och minnets hälsa. API-dokumentationen ligger
kvar på `/docs`.

Utan `LLM_API_KEY` körs rådet i **offline-läge**: heuristiska bidrag som
fungerar utan nätverk (märkt `mode: "offline"`).

### API

```bash
GET  /                       # webb-UI (HTML)
GET  /health
GET  /agents
GET  /memory/validate
GET  /memory/projects
GET  /memory/context/{project_id}/{member}?task_class=web
POST /roadmap
```

```bash
curl -X POST http://127.0.0.1:8000/roadmap -H "Content-Type: application/json" -d '{
  "brief": "En webbshop för hundägare med egen produktionslager",
  "restrictions": {
    "platform": "webb",
    "users_target": "Hundägare i Sverige",
    "team_size": "1 utvecklare",
    "budget": "0 kr"
  },
  "project_id": "dogshop"
}'
```

### CLI (minnesmotorn, stdlib-only)

```bash
python scripts/council_memory.py validate  memory/
python scripts/council_memory.py register  memory/ --id dogshop --name "Dogshop"
python scripts/council_memory.py start     memory/ --task-id T1 --project dogshop \
    --question "Vilken stack?" --task-class web --participants TECH CEO
python scripts/council_memory.py context   memory/ --project dogshop --member TECH
python scripts/member_knowledge.py --strict   # validera kunskapsbasen
```

OBSERVERA: `<root>` kommer **efter** subkommandot.

## Tester

```bash
python tests/test_council_memory.py     # 10 tester
python tests/test_member_knowledge.py   # 6 tester
python tests/test_council.py            # 14 tester (routing + offline-pipeline)
```

Körs direkt (ingen `unittest discover`), som i CI.

## Designprinciper

- **stdlib-only** i minnet och kunskapsbyggaren; bara `fastapi`/`uvicorn`/`pydantic` i appen.
- Inga modellanrop i minnet — LLM:n sitter bakom `app/llm.py`.
- Ingen siffra utan antagande; ingen utdata utan ansvarig medlem.
- Juridik är en gate, inte en åsikt: ingen `FEASIBLE` med öppen blockerare.
