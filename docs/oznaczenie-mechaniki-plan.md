# Oznaczenie — plan etapów mechanik X

Status: kierunek wybrany ręcznie 2026-11-10. Plan i wyniki C2d1/C2d2 są
punktem odniesienia dla następnych mechanik. Każda wymaga osobnego wyboru.

## Punkt wyjścia

- `Faza_A`, baza etapu `068745c`: C2a/C2b/C2c i poprawka atomowości
  migracji z `fe15534`, później podgląd 2D oraz E2/E4.
- Prywatne Oznaczenie i attack effect view istnieją; publiczny zbiór
  `_READY_ATTACK_X` w `battle_activations.py` jest pusty.
- Test `test_v3_oznaczenie_reaches_combat_only_for_declared_attacker`
  wstrzykuje modifier przez monkeypatch. Potwierdza drogę przekazania efektu,
  ale nie implementację którejkolwiek mechaniki X.
- Audyt protokołu C2c opisuje [raport QA](c2-qa-2026-11-04.md).
  Ostatni pełny `pytest -q` po E4: 3763 zaliczone testy przed C2d1.

## Mapa prac

Katalog kandydatów wynika z tagów `oznaczenie_tak` w aktualnie odczytanym
[źródle zdolności](../app/static/docs/SZOP_Zdolnosci.md):

| X / źródło | Decyzja planistyczna |
|---|---|
| Furia, poz. 7 | Pierwszy, ograniczony etap C2d1 opisany niżej. |
| Ostrożny, poz. 23 | Następny kandydat; osobny zakres i testy kontekstu całej bitwy. |
| Planowanie, poz. 25 | Osobno od istniejącego `przygotowanie`; zachować wcześniejsze odroczenie kosztów i publicznego katalogu. |
| Mistrzostwo(X), poz. 13 | Osobny projekt parametru X; nie rozszerzać milcząco obecnego payloadu Oznaczenia. |
| Bastion, poz. 1 | Najpierw zweryfikować właściwą rolę i czas działania; istniejący warunek w kontrataku nie dowodzi gotowości attack scope. |
| Niestrudzony, poz. 14 | Najpierw audyt momentu wyboru akcji względem czasu życia attack scope; nie przenosić efektu na następną akcję bez podstawy. |
| Dywersant, poz. 6 | Pozostaje odroczony; wcześniejsza decyzja MVP nie jest uchylana ogólnym wyborem kierunku Oznaczenia. |

To kolejka do osobnego doprecyzowania, nie zestaw zadań uruchamianych naraz.
Rozbieżności między źródłem, opisem YAML, ADR i kodem trzeba nazwać przed
implementacją danego X, a nie rozstrzygać z pamięci.

## B4.4d.C2d1 — prywatna Furia w ataku v3

### Cel i podstawa reguł

Dodać rzeczywisty efekt Furii dla zadeklarowanego szarżującego w prywatnym
attack lifecycle v3, wykorzystując istniejący combat i eventy.

- [Zdolności, poz. 7](../app/static/docs/SZOP_Zdolnosci.md): naturalna 6
  podczas Szarży daje dodatkowe trafienie tej samej broni w ten sam cel.
- [Zdolności, poz. 49](../app/static/docs/SZOP_Zdolnosci.md): Oznaczenie nadaje
  X innemu sojuszniczemu atakującemu tylko na rozpatrywany atak.
- [Zdolności, poz. 10](../app/static/docs/SZOP_Zdolnosci.md): wykonana Kontra
  odbiera szarżującemu kwalifikację do efektów wymagających Szarży.
- [Rozjemca, pkt 14.d i 17](../app/static/docs/SZOP_Rozjemca.md): zachować
  rozdzielenie ról atakującego i obrońcy oraz kolejność rozliczenia ataku.

### Zakres i ograniczenia

1. Jawnie przekazać kontekst Szarży do rozliczenia trafień; samo wywołanie
   `resolve_melee_attack` nie dowodzi, że oddział jest szarżującym.
2. Reużyć `effective_attack_passives` dla podstawowych i nadanych pasywek.
   Ta sama Furia obecna natywnie i przez Oznaczenie nie jest liczona dwa razy.
3. Liczyć efekt z naturalnych wyników istniejącego `RollResult.rolls`, bez
   ponawiania testów trafienia. Dodatkowe trafienia przechodzą zwykłe testy
   obrony i alokację ran przez istniejący SSOT.
4. C2d1 obejmuje tylko poprawny pending attack v3. Zachować wynik i RNG
   dotychczasowych ścieżek v1/v2 oraz wywołań bez tego scope. Pełna publikacja
   mechaniki natywnej poza v3 nie jest ukrytym rozszerzeniem tego etapu.
5. Nadana Furia nie trafia do kontratakującego obrońcy, Ostrzału, następnego
   ataku ani kolejnej aktywacji. Zachować obsługę wykonanej Kontry.
6. Nie zmieniać publicznego allowlistu ani `_READY_ATTACK_X`, API, payloadu,
   checkpoint/event schema, kosztów, katalogu/UI i publicznego Planowania.
   Nie implementować innych X, recovery, MCP ani LocalClient.
7. Nie dublować mechaniki naturalnych 6 z istniejącym helperem dodatkowych
   trafień broni. Interakcję z Podwójnym (źródło zdolności, poz. 66) sprawdzić
   jawnie; nierozstrzygalną kwestię reguł eskalować, nie maskować testem.

### Layer Checklist i performance gate

- Data model/DB: bez migracji, nowych tabel i trwałych pól.
- Engine: `combat.py`, ewentualny wąski adapter kontekstu w `phases.py` lub
  `activation_protocol.py`; `state.py` pozostaje SSOT widoku pasywek.
- Backend payload/HttpClient/JS/CSS: bez zmian; publiczne Oznaczenie nadal
  odrzucane bez zapisu.
- Tests/docs: rzeczywiste wyniki trafień i stanu, nie tylko obecność sluga.
- Zero nowych DB queries; brak I/O i dodatkowych rzutów trafienia przy
  sprawdzaniu zdolności. Dodatkowe testy obrony są skutkiem dodatkowych trafień.
  `/quote` i `/rosters/{id}` poza zakresem; istniejące pułapy SQL pozostają.

### Definition of Done

- Kontrolowane naturalne 6 / brak 6 dają oczekiwane trafienia i wynik walki.
- Przypadki: Furia natywna, nadana, obie naraz; atak bez Furii; Ostrzał;
  kontratak obrońcy; Kontra wykonana i niewykonana; pokonanie szarżującego
  przed jego atakiem; brak wycieku do drugiego ataku.
- Complete-tail replay, restart z checkpointu i przyszłe rzuty RNG zgodne
  z przebiegiem live; błąd po częściowym użyciu prywatnego RNG nie zmienia
  wejścia, a legalne retry jest deterministyczne.
- V1/v2 i v3 bez Furii pozostają zgodne z dotychczasowymi regresjami;
  publiczny request Oznaczenia nadal nie zapisuje domeny.
- Call-site audit zmienionych funkcji, simplify i code review; security review
  dodatkowo tylko jeśli rzeczywisty patch dotknie publicznego wejścia/auth/DB.
- Pełny `pytest -q`, czysty własny diff i osobny commit na `Faza_A`.
  Zapisać wynik w tym planie i w roadmapie oraz potwierdzić obecność commitu
  na `origin/Faza_A`. Zachować zastane zmiany i sumę kontrolną `data/szop.db`.

Minimalne komendy weryfikujące dla przyszłej implementacji (dołączyć nowy plik
testów, jeśli zostanie wydzielony):

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_engine_combat.py tests/test_engine_effects.py tests/test_engine_activation_protocol.py tests/test_engine_checkpoints.py tests/test_engine_regression.py tests/test_engine_multi_action.py tests/test_battle_activations.py tests/test_battle_activation_transport.py
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
```

### Wynik C2d1 (2026-11-17)

Silnik rozlicza Furię w głównym ataku zamkniętej Szarży v3. Efekt wrodzony
i nadany przez Oznaczenie liczy się raz. Wykonana Kontra odbiera kwalifikację
do Furii. Furia i Podwójny dodają własne trafienie z tej samej naturalnej 6,
a wszystkie trafienia idą do zwykłej obrony i alokacji ran. Podstawę stanowią
[poz. 7, 10, 49 i 66 Zdolności](../app/static/docs/SZOP_Zdolnosci.md) oraz
[pkt 14.d i 17 Rozjemcy](../app/static/docs/SZOP_Rozjemca.md).

Regresje w `tests/test_engine_activation_protocol.py` pokrywają rozliczenie
trafień, odtworzenie pełnego ciągu zdarzeń, restart, izolację następnego ataku
i ponowienie po błędzie alokacji. Próba HTTP na SQLite w pamięci z seedem 19
dała jedno trafienie bez Furii i dwa z Furią, zgodny zapis RNG i zgodny replay.
Publiczny `oznaczenie` dla `furia` zwrócił `unsupported_interrupt` bez zapisu.
Pełny lokalny `pytest -q`: 3777 zaliczonych testów. Zestaw celowany C2d1:
665 zaliczonych testów. Próba combat i protokołu po korekcie opisu: 210.

Na zamknięciu C2d1 pozostała rozbieżność nazw Podwójnego w walce wręcz:
`combat.py` rozpoznawał `podwojny`, a katalog YAML używał `rozrywajacy`.
Próba współdziałania z Furią używała istniejącego identyfikatora `podwojny`.
Rozbieżność w prywatnym melee v3 zamyka zaakceptowane C2d2 poniżej.

## B4.4d.C2d2 — wynik zgodności nazw Podwójnego (2026-11-18)

Podstawa reguł: [poz. 66, 7 i 10 Zdolności](../app/static/docs/SZOP_Zdolnosci.md)
oraz [pkt 14.d i 17 Rozjemcy](../app/static/docs/SZOP_Rozjemca.md), odczytane
w tej sesji. Podwójny daje jedno dodatkowe normalne trafienie za naturalną 6;
Furia dodaje własne trafienie tylko kwalifikującemu się szarżującemu.

`resolve_charge_attack` wyznacza raz pasujący zamknięty `AttackState` v3
przez istniejący `_matching_closed_charge`. Obecność tego kontekstu włącza
`canonical_aliases` w obu wywołaniach melee, niezależnie od kwalifikacji do
Furii. Istniejący SSOT `_count_hits` traktuje `podwojny` i `rozrywajacy`
jako jedną zdolność, także gdy obie nazwy są obecne naraz. Wykonana Kontra
może wyłączyć Furię głównego ataku, zachowując Podwójny obu własnych broni.

Regresje porównują całe eventy i RNG trzech wariantów aliasów, naturalną 6
i brak 6, Furię natywną/nadaną/obie, kontratak i Kontrę. Każdy wariant v3
ma pełny replay od stanu początkowego, restart zamkniętego checkpointu,
niezmieniony wejściowy RNG i zgodnych 12 przyszłych rzutów. Osobne granice
sprawdzają otwarte okno, inną broń i inną deklarację kontrataku.

Historyczne v1/v2 oraz ranged v1/v2/v3 zachowują wcześniejszą interpretację
nazw i RNG; ich ujednolicenie wymaga osobnego zakresu. Source-correct ranged
Strażnika nadal korzysta z istniejącego `_count_hits` bez zmian. Nie zmieniono
modelu, codec, API, DB, UI ani pustego publicznego `_READY_ATTACK_X`.
Komendy, wyniki testów i warunki przeniesienia są w
[kolejce etapów](kolejka-po-c2d1.md#1-b44dc2d2--nazwa-podwójnego-w-prywatnym-melee-v3).

## Późniejsza publikacja

Odblokowanie publicznego Oznaczenia jest osobnym etapem po potwierdzeniu
gotowości wybranych X. Wymaga jawnego zakresu wspieranych wartości i testów
auth/no-oracle, rollback/restart/RNG, jednego POST klienta oraz SQL gates.
Ukończenie samego C2d1 nie oznacza ukończenia całego Oznaczenia.
