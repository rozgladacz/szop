# ADR-0053 — Rename statusu `Ufortyfikowany` → `Przygotowany`

**Status:** Accepted (2026-07-08)
**Kontekst wątku:** `rozwoj-faza-a-merge` (rules-resync 2026-07, decyzja usera).

## Kontekst

User dostarczył 2026-07-08 nowe wersje `SZOP.docx`/`SZOP.pdf`/`SZOP_Zdolnosci.md`/
`SZOP_Rozjemca.md`. Drift pipeline (`scripts/rules_drift.py`) wykrył m.in. że
zdolność `przygotowanie` (warunek: „Jeżeli jest Ufortyfikowany, +1 do rzutów na
trafienie") zniknęła z DOCX, a w jej miejsce pojawiła się `planowanie` z
identycznym efektem, ale warunkiem „Jeżeli jest **Przygotowany**".

Źródło reguł odczytane w tej sesji — `app/static/docs/SZOP_Rozjemca.md`:

- pkt 22.c (linia 170): `Przygotowany:` — sekcja definiująca status (dawniej
  `Ufortyfikowany`).
- pkt 14.c (linia 94): „Oddział otrzymuje stan **Przygotowany** (pkt 22.c) oraz
  stan Aktywowany (pkt 22.d), po czym jego aktywacja się kończy." — akcja Obrona.
- pkt 22.c.iii (linia 173): „Przygotowany zostaje odrzucony na początku
  aktywacji oddziału."
- pkt 22.c.iv / 22.b.iii (linie 169, 174): mutex Przyszpilony↔Przygotowany —
  „oba te stany są odrzucane" (identyczne z dotychczasową semantyką mutex
  Przyszpilony↔Ufortyfikowany, ADR-0048 R5.e).

Nazwa statusu w źródle zmieniła się z „Ufortyfikowany" na „Przygotowany"; **cała
semantyka (mutex z Przyszpilony, odrzucanie na początku aktywacji, nadanie przez
akcję Obrona/Mobilizacja) jest identyczna** — to rename, nie nowa mechanika.

## Decyzja

1. **Rename 1:1** w silniku: `StatusFlag.UFORTYFIKOWANY = "Ufortyfikowany"` →
   `StatusFlag.PRZYGOTOWANY = "Przygotowany"` (`app/services/engine/status.py`),
   analogicznie `STATUS_UFORTYFIKOWANY` → `STATUS_PRZYGOTOWANY`. Zero zmian
   semantyki — identyczny mutex, identyczne triggery nadania/odrzucenia.
2. Zaktualizowane call-site'y: `phases.py` (10 miejsc), `effects.py`,
   `reducers.py` (importy), `actions.py`/`events.py`/`state.py` (docstringi
   opisujące pkt 22), boty `greedy_player.py`/`priority_player.py`/
   `priority_v2_player.py`/`priority_v3_player.py` (komentarze + jeden realny
   warunek w `priority_v3_player.py` sprawdzający status).
3. **Świadomie NIETKNIĘTE** (poza zakresem tego rename'u):
   - `app/data/abilities.py` — opis zdolności `przygotowanie` („Jeżeli jest
     Ufortyfikowany, +1...") zostaje jak jest; ta zdolność ma zostać
     zastąpiona/przemianowana na `planowanie` jako osobna decyzja cost-domain
     (Poziom 3, `HANDOFF_rozwoj-faza-a-merge.md`), nie część tego slice'a.
   - `app/data/strategic_cards.py` — karta taktyczna „Ufortyfikuj" to osobna,
     nieprogramowa (brak importu silnika) treść tabelaryczna kart do druku;
     synchronizacja treści kart z nowym nazewnictwem to osobna decyzja
     redakcyjna, nie mechanika silnika.
4. **Golden regression** (`tests/test_engine_regression.py`) — sha256 digest
   eventlogu zmienił się dla 6/6 case'ów (bo serializowany payload zawiera
   nazwę statusu), ale **winner/rounds/score/event-count identyczne** we
   wszystkich 6 (zweryfikowane przed regeneracją) — potwierdza że to czysto
   kosmetyczna zmiana bajtów, zero zmiany przebiegu gry. Digesty
   zregenerowane przez `python tests/test_engine_regression.py`.

## Konsekwencje

- Zdolności `planowanie`/`ratownik` (nowe/reworkowane w DOCX, warunkujące efekt
  statusem „Przygotowany") mogą teraz referować realny `StatusFlag.PRZYGOTOWANY`
  — odblokowuje ich implementację w `rozwoj-faza-a-merge` Poziom 3.
- `app/data/abilities.py:przygotowanie` ma teraz opis odnoszący się do statusu
  o nazwie, która już nie istnieje w silniku pod tą etykietą — to znany,
  udokumentowany dług do rozwiązania razem z decyzją `przygotowanie`→`planowanie`
  (Poziom 3), nie regresja tego slice'a.
- `app/data/strategic_cards.py` karta „Ufortyfikuj" może wymagać rewizji treści
  przy pełnej synchronizacji rules-resync 2026-07 (poza zakresem silnika).

## Alternatywy odrzucone

- **Nowy, osobny status `Przygotowany` obok `Ufortyfikowany`** — odrzucone;
  źródło (pkt 22.c) opisuje jeden status z jedną semantyką, nie dwa
  współistniejące stany. User potwierdził wprost: „Rename Ufortyfikowany→
  Przygotowany" (nie nowy status).
