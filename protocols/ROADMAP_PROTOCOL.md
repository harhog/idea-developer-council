# Roadmapprotokoll — Development Council

Version 1.0 · Definitionen av "komplett råd"

Ett råd är inte färdigt förrän användaren kan agera på det. Detta protokoll
definerar vad varje leverans måste innehålla oavsett fråga.

## 1. Inträdeskrav (annars `INSUFFICIENT_EVIDENCE`)
Innan rådet svarar måste följande finnas, annars returneras en
"info saknas"-lista i stället för gissningar:

- **Plattform**: webb / Android-spel / Android-app / iOS / flera
- **Målplattform-versioner** (t.ex. Android 10+)
- **Problem/målgrupp** (1 mening räcker)
- **Team-storlek** och erfarenhetsnivå
- **Deadline** eller "ingen"
- **Budget** (kan vara 0)

## 2. Obligatoriska sektioner i varje roadmap
Se `agents/CHAIR.md` STEG 6. Kort återgivet:
beslut → tekniker → arkitektur (ASCII) → server & drift → juridik →
etapper med kriterier → risker & antaganden → nästa experiment.

## 3. Teknikval-regler
1. Varje val följs av **1 motivationsrad**.
2. Minst **1 alternativ** + när alternativet vore bättre.
3. Inga ny-ceremonier: välj inte en teknik som kräver fler människor än
   teamet har.
4. Öppen källa före proprietär när kvaliteten är jämförbar; proprietär
   kräver utdatalplan (exit-strategi) skriven ut.

## 4. Genomförbarhetsbedömning
| Bedömning | Villkor |
|---|---|
| `FEASIBLE` | Alla 7 deltagare ja, LEGAL inte blockerad, budget inom band |
| `PILOT` | Teknik ja, men efterfrågan/ juridik osäker → billigt experiment först |
| `HOLD` | Överenskommelse saknas eller evidence saknas, plan för att skaffa det |
| `NO-GO` | Mätt blockerare: regel, kostnad eller teknisk omöjlighet med källa |
| `INSUFFICIENT_EVIDENCE` | Inträdeskrav uppfylls inte |

## 5. Etappstruktur (så här skärs en roadmap)
- **E0 — Validering** (1–2 veckor): problemexperiment, teknisk spik
- **E1 — MVP**: endast bullseye-funktioner, en miljö, en kanal
- **E2 — Hårdning**: övervakning, backup, tillgänglighet, policyer
- **E3 — Tillväxt**: första betalda kanal, skalningstrappa
- Varje etapp: **kriterium för klart** som går att mäta
  (t.ex. "10 användare genomför köpflödet utan hjälp"), inte "klart".

## 6. Juridik-gate
LEGAL går alltid sist före beslut. Ingen roadmap lanseras med en
öppen blockerare. "Kontrollera med juridik" är en etapp, inte ett avslag.

## 7. Uppföljning
- `close` skriver `outcome=PENDING`.
- När verkligheten mäts → ny outcome `OBSERVED` med bevis → `lesson`.
- Lesson som visar sig fel → `DISPUTED`/`SUPERSEDED`, aldrig raderad.
