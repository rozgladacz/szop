# ADR-0052 — Końcowy odstęp Manewru od innych oddziałów

**Status:** Accepted (2026-06-25)
**Kontekst wątku:** `faza-b-engine-mvp` / E4 slice.

## Kontekst

Engine MVP reprezentuje oddział jako koło (ADR-0008). Przed tą decyzją `resolver`
walidował dystans Manewru (`dist <= effective_move_inches`), ale nie sprawdzał,
czy końcowa pozycja nachodzi na inne oddziały albo staje w odległości 1″.

Źródło reguł odczytane w tej sesji:

- `SZOP_Rozjemca.md` pkt 2.d: modele są terenem `Niedostępny` i `Blokujący`.
- `SZOP_Rozjemca.md` pkt 4.c.i: na terenie `Niedostępny` model nie może się
  zatrzymać ani przez niego przemieszczać.
- `SZOP_Rozjemca.md` pkt 14.a: Manewr wykonuje Ruch.
- `SZOP_Rozjemca.md` pkt 15.b.iii: po Ruchu modele muszą być dalej niż 1″ od
  modeli innych oddziałów.
- `SZOP_Rozjemca.md` pkt 16.d: Związanie ma własny wyjątek dla celów Związania.

## Decyzja

1. Dla `ManeuverAction` walidujemy końcową pozycję oddziału jako koło: gap
   obwód-obwód do każdego innego żywego oddziału na Froncie musi być `> 1″`.
   Boundary `1″` jest nielegalne, bo źródło mówi "dalej niż 1″".
2. Wspólny helper `app/services/engine/movement.py` (`maneuver_destination_blocker`
   / `maneuver_destination_is_clear`) jest używany przez `resolver` i boty.
3. Boty filtrują swoje kandydaty Manewru tym samym helperem (`legal_actions`,
   `PriorityPlayer`, `PriorityV2Player`, `PriorityV3Player`), żeby symulacje nie
   wybierały akcji, które publiczny resolver natychmiast odrzuci.
4. `ChargeAction` nie jest objęty tą walidacją, bo Związanie ma osobny model ruchu
   i wyjątek pkt 16.d.
5. Ruch po ścieżce przez teren `Niedostępny` / `Trudny` oraz pełny pathfinding
   pozostają poza tym slice E4.

## Konsekwencje

- **+** Publiczny resolver domyka część E4 i przestaje akceptować końcowe
  nakładanie się oddziałów po Manewrze.
- **+** Boty zachowują spójność z resolverem i nie crashują na własnych
  kandydatach Manewru.
- **−** Zmienił się przebieg symulacji pełnych bitew; B7 golden digesty zostały
  odświeżone 2026-06-25.
- **Koszt runtime:** `O(number_of_blobs)` tylko dla `ManeuverAction`; bez DB i bez
  dodatkowych zapytań.
