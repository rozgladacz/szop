# HANDOFF — aideas-knowledge-base

> **Wątek:** Przygotowanie kopii i ekstraktów z aplikacji jako baza wiedzy dla ćwiczenia AIDEAS.
> **Status:** Ready for archive
> **Utworzony:** 2026-06-24
> **Ostatnia aktualizacja:** 2026-06-24

## Cel
Zebrać samodzielny pakiet plików w `AIdeas/Baza wiedzy`, który da szkoleniowemu agentowi kontekst o SZOP bez dotykania kodu aplikacji. Pakiet ma zawierać źródła zasad, wybrane ekstrakty z dokumentacji aplikacji oraz guardrails dla PoC.

## Zablokowane pliki / katalogi
- `AIdeas/Baza wiedzy/` — tworzenie materiałów wejściowych dla szkoleniowego agenta.

## Blokuje / Blokowane przez
- **Blokuje:** brak
- **Blokowane przez:** brak

## Gałąź git
- **Branch:** `Faza_A`
- **Base:** `main`

## Plan implementacji

### Faza 1 — Dobór źródeł
- [x] Krok 1.1: Zidentyfikować dokumenty zasad, konfigurację reguł i dokumentację aplikacji przydatną dla bazy wiedzy.
- [x] Krok 1.2: Wybrać mały zestaw plików, który pasuje do ograniczeń szkoleniowego środowiska.

### Faza 2 — Materiały bazy wiedzy
- [x] Krok 2.1: Skopiować źródłowe dokumenty zasad i wybrane YAML/JSON.
- [x] Krok 2.2: Utworzyć krótkie ekstrakty opisujące zakres agenta, aplikację, narzędzia i ograniczenia bezpieczeństwa.
- [x] Krok 2.3: Dodać indeks bazy wiedzy.

### Faza 3 — Format zgodny z AIDEAS
- [x] Krok 3.1: Przygotować wariant uploadowy tylko w formatach obsługiwanych przez narzędzie szkoleniowe.
- [x] Krok 3.2: Przekonwertować ekstrakty tekstowe do `.docx`, a YAML/MD do `.json` lub `.docx`.
- [x] Krok 3.3: Zweryfikować, że wariant uploadowy nie zawiera nieobsługiwanych rozszerzeń.

### Faza N — Weryfikacja end-to-end (Definition of Done)
- [!] `pytest -q` — nie dotyczy: brak zmian kodu aplikacji.
- [!] Smoke test JS — nie dotyczy: brak zmian `app.js`.
- [!] Call-site check dla zmienionych funkcji — nie dotyczy: brak zmian funkcji.
- [x] `/simplify` — zakres ograniczony do minimalnego pakietu plików, bez refaktorów.
- [!] `/review` — nie dotyczy: materiały pomocnicze poza aplikacją.
- [!] `/security-review` — nie dotyczy kodu; guardrails bezpieczeństwa są częścią treści.
- [!] Re-run `pytest -q` jeśli `/simplify` lub `/review` coś zmieniły — nie dotyczy.
- [x] Diff review przed zamknięciem.

## Pliki dotknięte
- `AIdeas/Baza wiedzy/` — pakiet wiedzy dla PoC.
- `AIdeas/Baza wiedzy - upload/` — wariant zgodny z formatami uploadu AIDEAS.
- `.gitignore` — lokalny katalog szkoleniowy `AIdeas/` wyłączony z trackingu.
- `docs/handoffs/HANDOFF_aideas-knowledge-base.md` — kontekst pracy.
- `HANDOFF.md` — wpis aktywnego wątku.

## Decyzje zamrożone (NIE podnosić ponownie)
- 2026-06-24: `AIdeas` nie jest częścią aplikacji; materiały są pomocnicze dla szkolenia.

## Hipotezy / pytania otwarte
- READY: Po zakończeniu ćwiczenia można wyciągnąć przydatne wnioski do właściwego SZOP.

## Jak zweryfikować
```bash
Get-ChildItem -Recurse "AIdeas/Baza wiedzy"
git diff --stat
```

## Decyzje
- 2026-06-24: Tworzymy kopie/ekstrakty, nie integrację z aplikacją.

## Notatki / odkrycia w trakcie
- 2026-06-24: Folder `AIdeas/Baza wiedzy` istnieje, ale nie zawiera jeszcze widocznych plików.
- 2026-06-24: Pakiet bazy wiedzy ma 23 pliki: 7 ekstraktów, 4 kopie zasad, 6 plików rulesetu, 1 plik kontekstu aplikacji i 4 przykłady danych plus README.
- 2026-06-24: SHA256 kopii źródłowych zgodne ze źródłami. `AIdeas/` dopisane do `.gitignore`, więc pakiet pozostaje lokalnym artefaktem szkoleniowym.
- 2026-06-24: Dodany wariant `AIdeas/Baza wiedzy - upload` z 18 plikami wyłącznie w obsługiwanych rozszerzeniach (`.docx`, `.pdf`, `.json`). Wygenerowane `.docx` otwierają się przez `python-docx`.
