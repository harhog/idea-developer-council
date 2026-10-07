# Minnesprotokoll — Development Council

Version 1.0 · Standardbibliotek · Inga modellanrop

## Princippunkter
Minnet är **inte** en databas. Det är en audit trail: varje påstående i en
roadmap ska kunna spåras tillbaka till vem, när, med vilken källa och med
vilket beslut. Därför gäller:

1. **Explicit validation** — `Memory.validate()` köras vid varje `load()`
   och `save()`. Trasig data avvisas, tyst reparation finns inte.
2. **Atomic writes** — tempfil + `fsync` + `os.replace`. Ingen halvskriven
   butik efter crash.
3. **Inga implicita fält** — saknas `evidence_refs` skrivs det som `[]`,
   inte som ett fel som upptäcks först i produktion.
4. **Inga modellanrop** — minnet vet inte vad en LLM är.

## Entiteter

| Entitet | Nyckel | Innehåll |
|---|---|---|
| Project | `id` | namn, alias, tidsstämplar |
| Episode | `task_id` | en fråga som rådet svarade på: deltagare, bevis, bidrag, beslut, utfall |
| Evidence | `id` inom episode | påstående + klassificering + källa + granskningsdatum |
| Lesson | `lesson_id` | validerat lärande kopplat till en episode |

## Medlemmar (MEMBERS)
`CEO FIN TECH DESIGN LEGAL MARK OPS` — utökas bara genom att ändra
`tuples` i `council_memory.py` **och** skapa `agents/<NAMN>.md`.

## Beslutsvärden (status)
`FEASIBLE` · `PILOT` · `HOLD` · `NO-GO` · `INSUFFICIENT_EVIDENCE`

Regler vid validering:
- `adil_result` sätts bara om `LEGAL` finns bland deltagarna.
- `founder_choice` kräver `founder_choice_source` — användarens egna val
  sparas med källa, annars går det inte att skilja på råd och beslut.
- Stängd episode kräver reflektion från **varje** aktiv deltagare.
- `OBSERVED`-utfall kräver bevis-referenser + summering.

## CLI-vägar
```
python scripts/council_memory.py validate  <root>
python scripts/council_memory.py register  <root> --id X --name "Namn"
python scripts/council_memory.py start     <root> --task-id T --project X --question "..." --participants TECH CEO
python scripts/council_memory.py evidence  <root> --task-id T --id E1 --claim "..." --source URL
python scripts/council_memory.py contribute<root> --task-id T --member TECH --assessment "..." --recommendation "..." --reflection "..."
python scripts/council_memory.py close     <root> --task-id T --decision '{"status":"FEASIBLE"}' --outcome PENDING
python scripts/council_memory.py lesson    <root> --lesson-id L1 --task-id T --project X --owner TECH --claim "..."
python scripts/council_memory.py context   <root> --project X --member TECH
```
OBSERVERA: `<root>` kommer **efter** subkommandot.

## Vad minnet aktivt vägrar
- Dubbletter av alias, evidence-id, lesson-id, contribution per medlem.
- Delaktighet från medlem som inte är participant.
- Stängning utan beslut.
- Bevis-referenser som inte finns i episoden.
- Överlappande datumformat som inte är ISO.
