# ADR-0058 — Kontrola celu w promieniu 2″

- **Status:** Accepted
- **Data:** 2026-11-18
- **Kontekst:** zaakceptowany etap B3.objectives-2in; korekta implementacji reguły, bez zmiany rulesetu.

## Decyzja

Źródłem jest odczytany w tej sesji [Rozjemca, pkt 5.d–g](../../app/static/docs/SZOP_Rozjemca.md).
Pkt 5.d wymaga odległości podstawka–znacznik ≤2″. Ustawiamy
`phases.OBJECTIVE_CONTROL_RANGE = 2.0`; `_check_objective_control` pozostaje
SSOT rozliczenia. Aproksymacja obwodu oddziału to dystans jego środka do
znacznika minus promień bloba. Trwałość i odbicie pozostają zgodne z pkt 5.e,
przeliczenie na końcu rundy z pkt 5.f, rozstrzygnięcie po czwartej rundzie
z pkt 5.g.

Boty Priority/V2, Minimax, ClaudeV1 i policy_eval już reużywają helpera.
Greedy korzysta z policy_eval; ClaudeV2 wywołuje ocenę ClaudeV1, a ClaudeV3
dziedziczy ścieżkę kontroli Priority.
Predykat bliskości PriorityV3 porównuje odległość obwodu ze wspólną stałą.
Żaden drugi próg kontroli nie jest potrzebny.

## Dowód zmiany goldenów B7

Przed edycją utrwalono sześć pełnych logów bazy `64e9e81`. Po korekcie
porównano kanoniczny JSON event po evencie. Cztery logi pozostały identyczne.
Przywrócenie **wyłącznie stałej 3.0 w pamięci** odtworzyło wszystkie sześć
bazowych digestów, więc poniższy drift pochodzi z korekty kontroli celu.

| Przebieg | Pierwsza różnica i przyczyna | Wynik / liczba eventów przed → po |
|---|---|---|
| `demo_priority_mirror`, seed 0 | `MoveExecuted`, seq 30, jednostka 3: cel 3 przestaje być kontestowany przez jednostkę 6 (P1, obwód–znacznik 2.303698″), a Priority wybiera inny cel marszu | remis (2,2), 247 → P1 (2,3), 245 |
| `clash_priority_vs_greedy`, seed 0 | seq 75: znika drugi Manewr jednostki 7. Jego dotychczasowy koniec miał odległość 2.545769″ do celu 3, co po korekcie nie odbija celu; Greedy kończy aktywację | P0 (3,0), 217 → P0 (2,1), 214 |

Nowe digesty są zapisane w `tests/test_engine_regression.py`. Zachowano
dotychczasowe scenariusze i dodano remis Priority mirror, seed 11: wynik
(2,2), 250 eventów. Gate nadal obejmuje remis i wygrane obu stron, powtórne
symulacje oraz replay kontroli i wyniku każdej pełnej bitwy.

## Konsekwencje i ograniczenia

Zmiana nie dodaje SQL, losowań, pól modelu, codec ani schemy eventów.
Historia odtwarza zapisane `ObjectiveControlChanged` i `RoundEnded`, bez
ponownego rozliczania geometrii według nowego progu; regresja obejmuje stary
zapis kontroli z odległości 2.5″. Nowe akcje stosują próg 2″.

Zachowano dotychczasowy filtr `models_alive` i Przyszpilony. Sam helper nie
filtruje `location`; żywa rezerwa na podanych współrzędnych zachowuje
dotychczasową semantykę. Ten etap nie rozstrzyga innych mechanik lokalizacji.
Nie zmienia też innych zasięgów, czasu przeliczenia ani aproksymacji kołem.

Weryfikację i gotowość przeniesienia pracy zapisuje
[wynik etapu 0](../kolejka-po-c2d1.md#0-b3objectives-2in--kontrola-celu-w-zasięgu-2).

## Alternatywy

- Pozostawienie 3″ odrzucono jako sprzeczne z pkt 5.d i zleceniem użytkownika.
- Osobne poprawki progów w każdym bocie odrzucono: istniejący helper i stała
  zapewniają jeden kontrakt bez replikowania rozliczenia.
