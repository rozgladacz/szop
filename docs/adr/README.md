# Architecture Decision Records

Krótki, immutable zapis decyzji architektonicznych. Każdy ADR = jeden plik
`NNNN-tytul-w-kebab-case.md`. Po zatwierdzeniu nie edytujemy treści —
zmianę decyzji wprowadza **nowy** ADR z polem `Supersedes: NNNN`.

Pełen indeks ADR (status, tytuł): [docs/roadmap.md → "ADR index"](../roadmap.md#adr-index).

## Szablon

```markdown
# ADR-NNNN — Tytuł

- **Status:** Proposed / Accepted / Superseded by NNNN
- **Data:** YYYY-MM-DD
- **Kontekst:** w jakiej fazie / dla którego strumienia

## Decyzja

Krótko, w trybie deklaratywnym: "Robimy X, bo Y."

## Konsekwencje

- Pozytywne: ...
- Negatywne / koszty: ...
- Co odkładamy / czego NIE robimy: ...

## Alternatywy rozważone

- Alt 1 — odrzucone, bo ...
- Alt 2 — odrzucone, bo ...
```
