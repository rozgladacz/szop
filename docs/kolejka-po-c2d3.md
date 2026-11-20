# Kolejka po C2d3-spec — akceptacje 2026-11-19

Baza planu: `0855277` na `Faza_A`. Użytkownik zaakceptował propozycje 1–5,
przywrócił D5.3, dodał audyt botów i podłączenie agentów oraz jawnie wznowił
cykl. Ostrożny jest rozstrzygnięty: **tylko ataki dystansowe**. Poniższe
zakresy precyzują tę akceptację; nie rozszerzają audytów na implementację
badanych mechanik ani przygotowania publikacji na samą publikację.

## Kolejność i wspólny DoD

Jeden worker realizuje jeden etap, w kolejności tabeli. Każdy etap zależy
od zamknięcia poprzedniego oraz wskazanych niżej prerekwizytów. Markery
`[automation-ready]` w roadmapie pochodzą z akceptacji użytkownika z tej daty.

| Kolejność | ID | Wynik |
|---|---|---|
| 1 | B4.4d.C2d3 | DONE 2026-11-19; prywatny Ostrożny v3, 3987 testów |
| 2 | B4.4d.C2d4-spec | DONE 2026-11-19; Bastion wykluczony z obecnego scope |
| 3 | B4.4d.C2d5-spec | DONE 2026-11-19; specyfikacja Planowania i drift statusu |
| 4 | B4.4d.C2d6-spec | DONE 2026-11-20; wykluczenie attack-only, luka walidacji powtórzeń |
| 5 | D5.3a | Strategia rozstawienia pod cele i jawny wybór |
| 6 | D5.3b | Powtarzalne porównanie z gridem |
| 7 | B4.4d.C2-publication-spec | DONE 2026-11-20; katalog gotowości i security gates, bez publikacji |
| 8 | D6.1-audit | DONE 2026-11-20; audyt 9 rodzin, transport v1, luki legalności i prerekwizyty D6.2 |
| 9 | D6.2-connect | DONE 2026-11-20; priority/v1 one-step → pending, osobna zgoda ownera, 4112 testów |
| 10 | D6.3-play-plan | DONE 2026-11-20; indeksowany plan P1–P16, bez implementacji i nowych markerów |

Przed pierwszą edycją worker czyta `AGENTS.md`, potwierdza cel/DoD,
Layer Checklist i SSOT oraz aktualny HEAD/cudze zmiany. Każdy rules claim
wymaga odczytu odpowiedniego `app/static/docs/SZOP_*.md` w danej sesji.
Decyzja użytkownika o Ostrożnym pozostaje wiążąca. Zielone detale rozstrzyga
worker, żółte koordynator; czerwone pytania według kanonicznego skilla.

Zmiana kodu wymaga encoding gate przed edycją Python, testów celowanych,
pełnego `pytest -q`, audytu wywołań, simplify/review i security review dla
auth/wejścia do DB. Po poprawkach przeglądu powtórzyć testy. Zmiana JS wymaga
smoke na działającej aplikacji (Zbrojownia, Edytor Armii, Rozpiski oraz
zmieniony przepływ); preview używa obecnej bazy. Czysty audyt Markdown:
sprawdzenie źródeł, symboli, linków i diffu oraz simplify/review; bez
ponawiania pytest, jeżeli nie zmieniono kodu. Wynik 3926 testów po D5.2
jest historyczną bazą, nie wynikiem nowych przebiegów.

Każdy etap zapisuje tu lub w indeksowanej dokumentacji wynik, komendy,
testy, ograniczenia i podstawę następnego etapu. Osobny nowy commit na
`Faza_A`, push i potwierdzenie identycznego hasha przez
`git ls-remote --heads origin Faza_A` są częścią DoD. Nie wznawiać HANDOFF.
Zachować zastane pliki, zwłaszcza historyczny hunk B6.2 w roadmapie;
staging roadmapy selektywny. Zero przypadkowych refaktorów i zmian bazy.

Backup osobno: ignorowana `data/szop.db`, lokalne sekrety/konfiguracja;
środowisko odtworzyć z requirements. Początkowy SHA256 bazy:
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Źródła SZOP DOCX/PDF/MD są śledzone w Git. Stan runtime automatyzacji jest
lokalny; przeniesienie kodu nie przenosi schedulerów ani poświadczeń.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
git status --short --branch
git ls-remote --heads origin Faza_A
```

## 1. B4.4d.C2d3 — implementacja Ostrożnego

Cel i zakres: wdrożyć [specyfikację](ostrozny-spec.md) według decyzji
2026-11-19. Prywatny pasujący zamknięty Ostrzał v3, natywna zdolność i
attack-scoped Oznaczenie, wspólny predykat z pełnym kontekstem bitwy oraz
jawny kontekst prediction. W źródle poz. 23 [Zdolności](../app/static/docs/SZOP_Zdolnosci.md)
warunek obejmuje brak wrogów w 12″ od atakującego oddziału. Melee nie
otrzymuje bonusu. Nie włączać globalnie `source_correct`, legacy v1/v2,
publicznego Strażnika ani `_READY_ATTACK_X`.

Warstwy: effects/combat/prediction i testy, ewentualnie wąski adapter phases;
bez DB, codec, API, JS/CSS. Performance: O(N) od jednostek, fast-path bez
zdolności, zero SQL/nowych rzutów RNG. Zmierzyć combat/prediction na fixture.

DoD: testy 11.999/12/12.001″ z różnymi promieniami, dodatkowy bliski wróg,
role/lokalizacje, native/granted/both raz, brak efektu po ataku, poprawny
closed-v3 gate, restart/replay/future RNG i failed-resolve immutability.
Prediction używa tego samego warunku. Testy wskazane w specyfikacji:
engine effects/combat/activation/checkpoints/interrupts, prediction parity,
regression i publiczny transport fail-closed; pełny pytest i wspólny DoD.

### Wynik implementacji C2d3 — 2026-11-19

Baza: `d6b742d`. Hook `_ostrozny_attack` w `effects.py` jest jedynym miejscem
skanu wrogów i pomiaru `circle_edge_distance`; `EffectContext.is_ranged_attack`
ma domyślne False. Combat kwalifikuje każdy profil przez `_matching_closed_shoot`:
pasujący zamknięty Shoot intent, bieżące bloby, canonical inventory i strict
profile equality. Matcher reużywa `_canonical_action_from_attack` oraz
`_same_weapon_profile` z protokołu przez lokalny import, bez drugiej walidacji
inline. Dopiero ten gate przekazuje pełny stan i włącza hook. Szeroki
`source_correct` pozostaje niezmieniony i celowo nie włącza Ostrożnego.

`prediction.expected_damage(..., *, state=None)` ma jawny opcjonalny kontekst.
Gdy podano pełny pasujący zamknięty stan v3, stosuje ten sam matcher i hook.
Bez kontekstu wynik historyczny zostaje zachowany. Nie dodano pól DB, eventu,
checkpointu, wire/API, klienta, JS ani CSS; `_READY_ATTACK_X` pozostaje puste.

**Audyt wywołań.** `_resolve_ranged_profile_pools` jest wołane wyłącznie przez
volley SSOT. Jego callerzy to single-profile `resolve_ranged_attack` oraz
publiczny Strażnik z `source_correct=True`; Strażnik zachowuje istniejącą
odmowę Ostrożnego. `phases._apply_shoot` nadal deleguje bez zmiany parametrów.
Matcher służy wyłącznie combat i opt-in prediction. `aggregate_attack_modifier`
nie zmienia swojego algorytmu deduplikacji; domyślny False chroni dotychczasowe
konteksty melee. Pięciu konsumentów `expected_damage` (Greedy, PriorityV2/V3,
ClaudeV1/V3) nie przekazuje state i zachowuje historyczny scoring. Pozostałe
rodziny dziedziczące te wyceny nie otrzymują automatycznego opt-in.

**Weryfikacja.** Pierwszy wymagany zestaw dziewięciu plików przed końcowym
simplify: 804 passed. Po simplify i dodatkowych regresjach: effects/combat/
activation/prediction **347 passed** oraz Strażnik i pięć rodzin scoringu
**92 passed**. Pełny `pytest --tb=short -q`: **3987 passed, 4 warnings** zależności
(195.27 s), po końcowym simplify; +61 testów wobec bazy3926. Goldeny
i historyczny replay pozostają bez zmian.
Nowe 61 przypadków obejmują granice dla trzech par promieni, drugi bliski wróg,
statusy/lokalizacje/sojuszników/pokonanych, native/granted/both i Rozkaz revoke,
realne trafienia v3 na naturalnej 3 przy jakości 4, clamp/naturalne 1/6,
niepasujące intent/profile/actor/target/inventory/state, v2 ready, per-profile
volley, restart/pełny replay/12 przyszłych rzutów, failed resolve/retry oraz
Monte Carlo prediction po 1000 seedów dla dwóch wariantów bliskości.

**Wydajność.** Fixture `_furia_battle` z istniejących testów protokołu:
3 bloby, aktor z `ostrozny`, cel `(20,0)`, sojuszniczy nosiciel `(20,2)`,
jedna broń/atak; closed Shoot v3, seed 225. `timeit.repeat`, mediana siedmiu
prób po 1000 wywołań. Bazowe moduły z `git show d6b742d:app/services/engine/...`
wczytano wyłącznie do pamięci tego samego procesu, bez zmiany checkoutu.
Combat: **37.618 → 64.265 µs**, prediction bez opt-in: **11.447 → 8.799 µs**,
nowy prediction z opt-in: **26.639 µs**. To pomiar diagnostyczny podczas
równoległego pytest, nie SLA ani dowód przyspieszenia starego prediction.
Dodatkowy pomiar 32 blobów: combat 64.988 µs, opt-in prediction 41.433 µs.
Koszt poprawności obejmuje ponowny canonical preflight (w tym walidację
strzału), potem liniowy skan; brak zdolności/closed gate omija ten preflight.
Zero SQL/I/O/nowych rzutów, bez cache. Sam predykat ma O(1) dodatkowej pamięci.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_engine_effects.py tests/test_engine_combat.py tests/test_engine_activation_protocol.py tests/test_prediction_vs_simulation.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_engine_straznik.py tests/test_agents_greedy.py tests/test_agents_priority_v2.py tests/test_agents_priority_v3.py tests/test_agents_claude_v1.py tests/test_agents_claude_v3.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest --tb=short -q
git diff --check
```

Simplify/review objęły per-profile gate, reuse canonical validation, brak
poszerzenia source_correct, role/lifetime, pełny obraz wrogów, RNG i backward
compatibility. Gate został uproszczony do jednego miejsca w core, bez nowego
parametru AttackState przenoszonego przez volley. Security review/UI smoke
nie dotyczą zakresu bez auth/input→DB/JS. Ograniczenia: jest to prywatny
zakres closed-v3; legacy, publiczny Strażnik i katalog publikacji pozostają
przed osobnymi etapami. Bez zmiany danych produkcyjnych.

**Przeniesienie.** Własny commit C2d3 na Faza_A musi być potwierdzony na
origin/Faza_A; cudzy hunk B6.2 i historyczne pliki pozostają poza nim.
Baza i lokalne sekrety/konfiguracja wymagają osobnego backupu, jak powyżej.
Następny zaakceptowany etap to **B4.4d.C2d4-spec — audyt Bastionu**.
Nie uruchomiono go w ramach C2d3. Brak nowych pytań o reguły.

## 2–4. Audyty Bastionu, Planowania i Niestrudzonego

Każdy to oddzielny dokumentacyjny etap; wynik indeksować w docs/README.
Źródło: aktualne poz. 1, 25 i 14 [Zdolności](../app/static/docs/SZOP_Zdolnosci.md)
oraz wskazane tam punkty Rozjemcy. Wspólny zakres: źródła i synchronizacja,
faktyczne call sites effects/combat/activation/interrupts/reducers/prediction,
role, moment oceny, trwałość efektu, compatibility v1/v2 i wymagane testy.
Nie implementować nowych mechanik w trakcie audytu ani nie zmieniać kosztów.

- **C2d4-spec — Bastion:** ustalić podmiot kontrataku i czy nadanie X
  deklarowanemu atakującemu może osiągnąć właściwą rolę. Rozdzielić zdolność
  natywną/Rozkaz od attack-scoped Oznaczenia. Odmowa niepasującego X może być
  poprawnym wynikiem audytu; nie rozszerzać semantyki źródła dla publikacji.
- **C2d5-spec — Planowanie:** sprawdzić stan Przygotowany w chwili trafienia,
  jego zmiany w sekwencji, główny atak/kontratak, deduplikację grantów;
  rozdzielić `planowanie` i istniejące historyczne `przygotowanie`.
- **C2d6-spec — Niestrudzony:** sprawdzić wybór akcji względem attack scope,
  limit/kontrolę pętli aktywacji i wygaszanie nadania. Nie przenosić
  krótkotrwałej zdolności na następną akcję na podstawie samego sluga.

Warstwy: dokumenty i roadmapa. Oszacować przyszły koszt i kontekst, zero
SQL. DoD każdego: konkretne przykłady brzegowe, mapa plików/wywołań,
macierz testów, wykonalny ograniczony etap implementacyjny albo uzasadnione
wykluczenie. Nierozstrzygalny konflikt źródeł daje jedno pytanie z
rekomendacją; audyt można zamknąć z pytaniem, dalszy cykl blokuje koordynator.
Weryfikacja: źródła/sync, symbole i linki, diff review; docs-only DoD wyżej.

### Wynik C2d4-spec — 2026-11-19

Na bazie `4bf700f` powstał [audyt Bastionu](bastion-spec.md). Właściwym
podmiotem jest kontratakujący obrońca (poz. 1/10 Zdolności, pkt 14.d.iv/17
Rozjemcy), a obecny attack override wiąże wyłącznie deklarowanego
szarżującego. Bastion zostaje **wykluczony z katalogu publikacji obecnego
main-attacker-only Oznaczenia**. Tag źródłowy pozostaje prawdziwy; wykluczenie
dotyczy obecnego zakresu protokołu. Nie dodano implementacji ani nowego
okna kontrataku. Rozkaz dla Bastionu ma kierunek „−”, więc source-correct
payload odbiera zdolność, nie nadaje jej.

Źródła: `rules_sources_check.py` **4/4 CLEAN**, odczyt DOCX/MD/YAML zgodny
w zakresie Bastionu; PDF zweryfikowany hashem. Sprawdzono symbole i call
sites, role/lifetimes, istniejące regresje native/counter oraz macierz
przyszłych testów. Simplify/review, link check i `git diff --check`.
Kod/testy niezmienione: bez ponownego pytest; **3987 passed** to historyczny
wynik C2d3. Nie zmieniono DB/API/JS, RNG ani kosztów. Wskazano istniejące
ograniczenie kolejności MVP counter/main, bez rozszerzania tego audytu.

Osobny commit dokumentacji na `Faza_A` potwierdzany na `origin/Faza_A`;
backup bazy/sekretów/konfiguracji według wspólnych warunków. SHA256 bazy
bez zmian. Cudze pliki i historyczny hunk B6.2 zachowane poza commitem.
Brak nowego pytania do użytkownika. Następny zaakceptowany etap to
**C2d5-spec — audyt Planowania**, nieuruchomiony w C2d4-spec.

### Wynik C2d5-spec — 2026-11-19

Na bazie `a09e55a` powstała [specyfikacja Planowania](planowanie-spec.md).
Warunek dotyczy aktualnego Przygotowanego rzeczywistego atakującego
(poz. 25 Zdolności, pkt 17/22.c Rozjemcy). Start aktywacji usuwa status,
Mobilizacja może go nadać ponownie; natywny kontratak i mark szarżującego
mają różne role. `planowanie`, historyczne `przygotowanie` i status nie są
aliasami. Brak hooka; prywatny handler/tag i monkeypatch test nie dowodzą
mechaniki. Zapisano gate Shoot/Charge v3, prediction, macierz przyszłych
testów i pliki/DoD osobnej implementacji, bez publikacji `_READY_ATTACK_X`.

Zidentyfikowano istniejącą różnicę `_apply_defend` wobec pkt 22.b.iii/22.c.iv:
Mobilizacja przy wcześniej Przyszpilonym usuwa tylko Przyszpilony zamiast
obu stanów. Nie zmieniono kodu; przed przyszłą implementacją określić jawny
zakres regresji statusów. To nie jest konflikt źródeł ani nowe pytanie.

Weryfikacja: źródła **4/4 CLEAN**, bezpośredni DOCX/MD/YAML, 29 symboli AST
w 9 plikach, call sites, 4 nowe cele linków, simplify/review oraz
`git diff --check`. Wyłącznie Markdown; pytest
nie ponawiano, **3987 passed** jest historyczną bazą C2d3. Zero SQL/RNG,
bez DB/API/UI. Osobny commit na Faza_A potwierdzany na origin/Faza_A;
backup bazy i sekretów/konfiguracji jak we wspólnym DoD. SHA256 bazy zgodny,
cudze zmiany i historyczny hunk B6.2 zachowane. Następny zaakceptowany etap:
**C2d6-spec — audyt Niestrudzonego**, nieuruchomiony tutaj. Brak nowych pytań.

### Wynik C2d6-spec — 2026-11-20

Na bazie `7a132f5` powstał [audyt Niestrudzonego](niestrudzony-spec.md).
Niestrudzony znosi ograniczenia powtórzenia Ostrzału/Szarży, nie limit 2
akcji (poz. 14 Zdolności, pkt 11.b.iv/14.c.v/14.d.vi Rozjemcy). Obecny
grant Oznaczenia istnieje po legalnej deklaracji i znika przy AttackResolved;
nie zalegalizuje kolejnej deklaracji ani nie może trwać do następnej akcji.
Wynik: wykluczenie z publikacji obecnego attack-only scope, bez zmiany tagów.

Wspólna walidacja `can_append_activation_action_type` nie czyta pasywek,
więc odrzuca powtórzenia również przy native/Rozkaz Niestrudzonym. To
istniejąca luka kodu do osobnego zakresu. DOCX/MD mówią o aktywacji, wtórny
opis YAML o rundzie; odsyłacz MD 11.b.iii jest nieaktualny wobec 11.b.iv.
Zapisano oba drifty, bez zmiany źródeł/kodu. Nie ma nowego pytania o reguły.

Weryfikacja: źródła **4/4 CLEAN**, bezpośredni odczyt DOCX/MD/YAML,
25 symboli AST w 9 plikach, call sites, 6 nowych celów linków,
simplify/review oraz diff check.
Wyłącznie Markdown; pytest nie ponawiano, **3987 passed** jest historycznym
wynikiem C2d3. Zero SQL/RNG, baza nietknięta i SHA256 zgodny. Osobny commit
Faza_A potwierdzany na origin/Faza_A; backup bazy/sekretów/konfiguracji jak
we wspólnym DoD. Cudze zmiany oraz hunk B6.2 pozostają poza commitem.
Następny zaakceptowany etap: **D5.3a**, nieuruchomiony w tym audycie.

## 5–6. D5.3a/b — strategia rozstawienia i pomiary

Użytkownik 2026-11-19 odwołał wcześniejsze odłożenie obu części D5.3.
Obowiązują zakresy [D5.3a i D5.3b z poprzedniej kolejki](kolejka-po-c2d1.md#4-d53--opcjonalne-rozstawianie-pod-cele),
z poniższą aktualizacją bazy: D5.1/D5.2 zamknięte, kontrola celu 2″
wdrożona w `f57b26b`. Nie ma już rozbieżności stałej 3″ do naprawiania.

**D5.3a:** Python runner wybiera grid lub nową deterministyczną heurystykę
rozstawienia pod różne cele, niezależnie od polityki walki. Grid pozostaje
domyślny. Wspólna ograniczona pula kandydatów D5.2, walidator D5.1, jawne
occupied i sekwencyjny obraz, deterministyczne remisy i fallback bez celów.
Obsłużyć więcej/mniej oddziałów niż celów i wyczerpanie kandydatów.
Warstwy deployment/runner/tests, bez HTTP allowlist/DB/UI. Zero SQL,
limit kandydatów bez permutacji; mierzyć liczbę ocen/czas. DoD: legalne i
powtarzalne pozycje, oddzielne przydziały, niezmieniony default, testy
agents_deployment/match/factory, balance_simulate, regression + pełny pytest.

**Wynik D5.3a 2026-11-20** Baza: `da0bfbd`. Python runner ma opcjonalne
`deployment_strategies=(choice_p0, choice_p1)`: każda pozycja to `None`
(dotychczasowy callback gracza), `"grid"` albo `"objectives"`. Brak parametru
pozostawia dotychczasowy grid botów deterministycznych i seeded Random.
Jawny wybór jest niezależny od polityki walki, działa tylko z
`deployment_zones` i nie łączy się z explicit `deployment`. Błędny typ,
liczba stron lub nazwa daje `ValueError` przed callbackami. Przykład:

```python
result = simulate_from_rosters(
    rosters, players, seed=19, terrain=terrain, objectives=objectives,
    deployment_zones=zones, deployment_strategies=("objectives", "grid"),
)
```

`objective_deployment_choice` zwraca `(position, target_id)` bez mutacji
liczników. Runner utrzymuje osobne słowniki przydziałów dla obu stron,
nowe dla każdego rozstawienia; zwiększa licznik dopiero po niezależnej
walidacji wyboru. `None` zamiast celu oznacza fallback bez celów.
Przydział nie oznacza kontroli celu z pkt 5.d–f
[Rozjemcy](../app/static/docs/SZOP_Rozjemca.md).

Grid i cele używają tego samego `_grid_candidates`: dotychczasowy
preferowany slot, następnie siatka 33×33 z D5.2. Każdy punkt przechodzi
D5.1 ze stanem i jawnym `occupied` D5.2 przed oceną. Ranking to
`(liczba_przydziałów, max(0, odległość_środków - promień_oddziału),
id_celu, x, y)`. Liczy się więc najpierw najmniej obsadzony cel, potem
geometryczne dojście, identyfikator i współrzędne. Pomiar podstawka–znacznik
jest przybliżeniem koła; strategia nie sprawdza tras ani wyniku bitwy.
Nie zmieniono SSOT kontroli celów, walidacji miejsca, pól stanu, RNG ani
publicznych API/allowlist/klienta/UI. Zero SQL.

**Weryfikacja D5.3a** Dodano 21 przypadków: osobne przydziały i nadmiarowe
wsparcie, obie strony i reset między grami, deterministyczne remisy,
poligon/wąska strefa/różne promienie, brak celów, rezerwy/pokonani i
placeholdery, bounded exhaustion, późny błąd bez częściowego zatwierdzenia,
walidacja parametrów, wybrany callback i RNG Random bez dryftu,
opt-in równe explicit oraz pełny deterministyczny replay.
Końcowy zestaw celowany **219 passed, 1 warning**, deployment **124 passed**.
Pełna suita: **4008 passed, 4 warnings** zależności (215.87 s), po końcowym simplify/review; +21 przypadków wobec 3987.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_agents_deployment.py tests/test_agents_match.py tests/test_agents_factory.py tests/test_balance_simulate.py tests/test_engine_regression.py tests/test_engine_replay_invariant.py tests/test_clients_parity.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest --tb=short -q
git diff --check
```

**Pomiary D5.3a** Mapy z `build_map(name, 19)`, po 8 jednostek i 5 celów,
`priority` po obu stronach, seedy decyzji 19/20, seed bitwy 19, strefy
`DEFAULT_DEPLOYMENT_ZONES`. Mediana 5 prób: po 10 rozstawień, po 1 pełnej
grze; budowanie graczy w mierzonej funkcji. Licznik opakowuje walidator
kandydatów; końcowe 8 walidacji runnera jest dodatkowe.

| Mapa | Default przed zmianą: rozstawienie / gra ms | Grid po zmianie: rozstawienie / gra ms | Cele: rozstawienie / gra ms | Kandydaci Grid / cele |
|---|---:|---:|---:|---:|
| Standard_A | 0.806 / 38.146 | 0.640 / 39.688 | 216.134 / 251.185 | 16 / 8720 |
| Lustrzana_A | 0.532 / 31.213 | 0.654 / 30.607 | 199.824 / 230.588 | 8 / 8720 |
| Symetryczna_A | 0.551 / 37.738 | 0.658 / 32.061 | 221.818 / 234.373 | 8 / 8720 |

To diagnostyka, nie SLA ani dowód przewagi strategii. Cele skanują do
1090 punktów na jednostkę i oceniają do `1090 × liczba_celów` par;
pamięć nie przechowuje wszystkich par. Koszt opt-in jest istotnie wyższy
niż early-exit Grid. Czas pełnych gier obejmuje też inne pozycje i decyzje;
porównanie skuteczności pozostaje D5.3b. Brak backtrackingu, badania
permutacji i gwarancji znalezienia małej wolnej szczeliny między próbkami.
Domyślny wybór pozostaje bez zmian.

**Audyt wywołań i przeglądy** `grid_deployment_position` nadal obsługuje
GridDeploymentMixin i jawny runner; bez celów nowy helper do niego deleguje.
`_grid_candidates` jest wspólny tylko dla gridu i celów, `_first_legal_position`
nadal obsługuje grid/Random i identyczny błąd wyczerpania. Jedyny caller
nowego wyboru to runner. Pięć skryptów (`balance_simulate`, `battle_replay`,
`exploit_hunt`, `analyze_battle`, `analyze_agents`) i `roster_simulation`
nie podają nowego argumentu: zachowują dotychczasową ścieżkę. Klienci i
transport HTTP nie dostały nowego parametru. Simplify/review sprawdziły
SSOT puli/walidacji, lokalny czas życia liczników, tie-breaks, callback
context, brak efektów ubocznych i compat defaults. Security review/UI smoke
nie dotyczą zakresu bez auth/input→DB/JS. Nie zmieniono goldenów.

**Przeniesienie D5.3a** Wynik ma osobny nowy commit na `Faza_A`, potwierdzany
na `origin/Faza_A`; zastany B6.2 i lokalne pliki poza commitem. Baza pozostaje
nietknięta, SHA256 zgodny ze wspólną sekcją backupu; bazę, sekrety i lokalną
konfigurację zachować osobno, środowisko odtworzyć z requirements.
Następny zaakceptowany etap D5.3b może wybrać strategie osobno dla stron
przez nowy parametr. Helper wyboru zwraca ID celu do pomiarów przydziałów;
nie ma go w trwałym stanie/eventach. Nie uruchomiono D5.3b w tym etapie.

**D5.3b:** po D5.3a zamrozić mapy/armie/seedy, sparować grid/cele przy tej
samej polityce, zamienić strony/inicjatywę, dodać kontrole lustrzane.
Pomiar: legalność i błędy, pokrycie/przydziały, dystanse, zwycięstwa/remisy,
czas rozstawienia i pełnej gry, deterministyczne pozycje/eventy. Użyć
istniejących fixture i map z poprzedniego planu, factory/registry jako SSOT.
Warstwy skrypt eksperymentu/testy/wersjonowany raport; bez silnika/DB/UI.
DoD: komendy, parametry, hashe i dane wyniku dostępne w Git, nie tylko
ignorowane reports; gorszy wynik również kończy etap. Nie przełączać
milcząco domyślnej strategii. Kod skryptu wymaga pełnego pytest.

**Wynik D5.3b 2026-11-20 — zamknięty** Baza `5588fed`.
[Metodyka i rekomendacja](experiments/d5_3b/README.md),
[zamrożony manifest](experiments/d5_3b/manifest.json),
[surowe dane](experiments/d5_3b/results.json) i
[tabele wyniku](experiments/d5_3b/results.md) są wersjonowane w Git.
Leaf `scripts/deployment_experiment.py` reużywa runner, helper wyboru,
walidator D5.1, factory/registry i replay; bez zmian kodu produkcji.

480 przypadków, 960 wykonań: trzy generowane mapy (seed 19), dwa istniejące
YAML, polityki priority/priority3 w parach tej samej polityki, seedy 11/19/42,
obie zamiany armii i inicjatywy, wszystkie cztery pary grid/objectives,
2 powtórzenia. Manifest zamrożono przed pomiarem. Wszystkie przypadki
zakończyły pełną grę, bez błędów/cap; wszystkie powtórzenia zgodne poza
czasem i wszystkie pełne replay równe live. Powtórki nie zwiększają
liczby przypadków w statystykach. Hash manifestu, źródeł i bazowego commitu
są w danych; ograniczenia CRLF/LF oraz odtworzenie opisano w metodyce.

Mieszane 240 przypadków: **cele 174 wygrane (72,5%), grid 30 (12,5%),
36 remisów (15%)**. Cele przegrały komórkę objective_clash/priority3:
10 wygranych vs 12 gridu i 2 remisy. Najbliższy cel: średni dystans
15,655→4,245 cala, najgorszy 25,755→12; średnie przestrzenne pokrycie
2,2→2,4 różnych najbliższych celów/strona. Cele mają 4 jawne przydziały,
ale nie są one tym samym co najbliższe cele ani formalna kontrola.
Maksymalny dystans do przydzielonego celu 28,453 cala ilustruje koszt
priorytetu różnych przydziałów nad dystansem.

Średni deployment grid/grid **0,797ms**, cele/cele **183,750ms**;
pełna gra z metrykami/setup odpowiednio **46,218ms** i **238,529ms**.
Walidacje kandydatów: średnio4,8 / strona grid vs 4360 cele. To pomiar
bez równoległego pytest, z jawną instrumentacją; nie SLA. Kontrole
lustrzane wykazują efekt strony: grid/grid: 58 P0 / 8 P1 / 54 remisy,
cele/cele: 42 P0 / 66 P1 / 12 remisów. Nie traktować 960 wykonań jako niezależnej
próby ani wyniku jako dowodu ogólnej przewagi. **Zachować grid domyślny,
cele jawnie eksperymentalne**; nie stroić kodu pod te dane.

**Weryfikacja D5.3b** Nowe 17 testów bada manifest/parowanie, realną zamianę
ownerów i seedów, wynik równy `simulate_from_rosters`, replay, cleanup
instrumentacji, błędy rozstawienia/cap bez udawanego remisu, detekcję
niedeterminizmu z pominięciem czasu i denominatory raportu. Celowane
6 plików: **214 passed**. Pełny `pytest --tb=short -q`: **4025 passed,
4 warnings** zależności, 217.63s; +17 wobec bazy 4008. Simplify/review,
call-site audit, linki i diff check zakończone bez dalszych zmian kodu.
Nowe funkcje są używane wyłącznie przez CLI/harness/testy; patche helperów
istnieją tylko podczas sekwencyjnego pomiaru i są zawsze przywracane.
Brak nowych SQL, DB, API, auth, JS, event/checkpoint schema, defaultów,
wag i goldenów. Security review/UI smoke nie dotyczą tej warstwy.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/deployment_experiment.py --manifest docs/experiments/d5_3b/manifest.json --out docs/experiments/d5_3b/results.json --report docs/experiments/d5_3b/results.md
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_deployment_experiment.py tests/test_agents_deployment.py tests/test_agents_match.py tests/test_balance_simulate.py tests/test_agents_factory.py tests/test_engine_regression.py -x --tb=short -q
.\.venv\Scripts\python.exe -X utf8 -m pytest --tb=short -q
```

**Przeniesienie D5.3b** Osobny nowy commit na Faza_A potwierdzany na
origin/Faza_A. Artefakty są w Git, nie ignorowanych reports/build. Baza
pozostała nietknięta, SHA256 jak we wspólnej sekcji; baza i lokalne
sekrety/konfiguracja wymagają osobnego backupu. Cudze pliki/hunk B6.2 poza
commitem. Następny zaakceptowany etap to **B4.4d.C2-publication-spec**;
nie uruchomiono go w D5.3b. Brak nowych pytań/decyzji do realizacji audytu.

## 7. B4.4d.C2-publication-spec — przygotowanie publikacji

Cel: przygotować ograniczony katalog X i konkretny plan publikacji
Oznaczenia na podstawie wyników C2d1–C2d6. [Plan mechanik](oznaczenie-mechaniki-plan.md)
i [QA C2](c2-qa-2026-11-04.md) są kontekstem, źródła reguł odczytać ponownie.
Zakres: tabela gotowe/prywatne/wykluczone, audyt owner/scope/no-oracle,
atomowości błędu, rollback/restart/RNG, CAS/stale sequence i SQL gates;
minimalne etapy serwis/HTTP/HttpClient/MCP/UI oraz ich zależności i testy.
Warstwy dokumentacja/security audit, bez zmiany `_READY_ATTACK_X`, auth,
endpointów lub danych produkcji. Zliczyć istniejące SQL i wskazać przyszłe
budżety. DoD: jawny katalog bez domniemanej gotowości z samego audytu,
konkretne pliki/kontrakty i negatywna macierz testów, review/security review,
linki i diff check. Przygotowanie nie upoważnia do samej publikacji.

### Wynik C2-publication-spec — 2026-11-20

Na bazie `0ef2968` powstał indeksowany [plan ograniczonej publikacji](oznaczenie-publication-spec.md).
Publiczny katalog nadal **pusty**; prywatna Furia jest propozycją pierwszego
minimalnego katalogu, Ostrożny drugiego rozszerzenia. Podwójny to zależność
broni, nie osobny pasywny X; Bastion i Niestrudzony są wykluczone z obecnego
attack-only scope. Planowanie pozostaje audytem bez hooka. Mobilizacja oraz
native/Rozkaz Niestrudzony mają własne przyszłe prerekwizyty, bez napraw w tym
etapie. Tabela opiera się na źródłach i rzeczywistych call sites, nie tagach.

Audyt obejmuje private core → durable service → HTTP → HttpClient → MCP → UI,
owner/scope/no-oracle, role nosiciela/atakującego/celu, stale/CAS, rollback,
restart/checkpoint/event tail i RNG. Rozdzielono transakcję domeny (router)
od wcześniejszego commitu audytu autoryzacji bearera. Wskazano brakujące
pozytywne przepływy i małe przyszłe etapy; **nie otrzymały automation-ready**.
MCP nadal ma istniejące propozycje zatwierdzane przez użytkownika, bez nowego
bezpośredniego write toola. Nie zmieniono `_READY_ATTACK_X`, API lub uprawnień.

**Weryfikacja:** `rules_sources_check.py` **4/4 CLEAN**; pięć istniejących
izolowanych testów SQL/fail-closed/retry-RNG **5 passed, 1 dependency warning**.
Zmierzono istniejące pułapy 5 SELECT service / 6 session / 7 bearer; accepted-X
ma je dopiero udowodnić. Test prywatnego durable seam nadaje Furię podczas
Shoot, więc nie dowodzi jej efektu w Szarży. Dokładne testy i komendy są
w specyfikacji. Odczyt źródeł/symboli, linki, diff check oraz ręczne odpowiedniki
simplify/review/security review; docs-only, bez ponownego pełnego pytest.
Historyczna baza po D5.3b: 4025 passed, nie wynik tego przebiegu.

**Przeniesienie:** osobny nowy commit na Faza_A, potwierdzany na origin/Faza_A.
Wszystkie artefakty etapu w Git. Baza nietknięta (SHA256 we wspólnym DoD);
baza i lokalne sekrety/konfiguracja wymagają osobnego backupu. Zastane pliki
i hunk B6.2 poza commitem. Brak nowego pytania o reguły/uprawnienia; sama
publikacja pozostaje do osobnego zatwierdzenia. Następny zaakceptowany etap
to **D6.1-audit**; ten worker go nie uruchamia.

## 8. D6.1-audit — audyt botów

Cel: ocenić gotowość istniejących botów po E2/E4, kontroli celu 2″,
Ostrożnym i D5.3. `agents/registry.py`/`factory.py` są SSOT katalogu i
konstrukcji; nazwy claude_v* oznaczają obecne implementacje, nie połączenie
z płatnym modelem. Brak nowych dostawców lub zewnętrznych kont.

Zakres: legalność akcji i kontynuacji, deployment, ruch, prediction vs
resolver, zakończenie gry, deterministyczność seedów, tagi i koszt, oraz
przekład decyzji na publiczny lifecycle v1/v2/v3. Oddzielić jakość polityki
od poprawności reguł. Sprawdzić wszystkie rodziny; drogie boty oceniać na
jawnie ograniczonych próbkach. Nie stroić wag ani zmieniać rankingów bez
pomiaru. Porównać także publiczny state bez RNG z danymi wymaganymi przez
wybranego bota. Osobno zidentyfikować blokery integracji przed D6.2.

Warstwy audyt + testy/regresje/harness, bez publikacji nowego API i zmian
auth. DoD: wersjonowany raport z komendami/seedami/czasem i macierz
bot × obsługiwany protokół × scenariusz, odtworzenia usterek i lista
prerekwizytów D6.2. Testy registry/factory/base, botów, match/deployment,
move_fidelity, regression, clients parity; pełny pytest przy zmianie kodu.
Brak wymaganej zdolności ma być jawny, nie zastępowany nielegalną decyzją.

### Wynik D6.1-audit — 2026-11-20

Baza `4082bd9`, [raport i macierze](boty-audit.md),
[manifest/wyniki](experiments/d6_1/manifest.json),
[harness](../scripts/bots_audit.py). Wszystkie 9 rodzin przez registry/factory;
alias `claude` osobno, bez dostawców zewnętrznych. **239 przypadków / 478
wykonań**, wszystkie pary powtarzalne. 144/144 nieterminalne pierwsze akcje
akceptowane przez obecny resolver, 101 drugich akcji, 144/144 replay;
54/54 legalne deployment (default/grid/objectives, także wąska strefa i
poligon), 9/9 zakończonych końcówek oraz 14/14 pełnych fixture fast.
Drogie rodziny mają jawnie małą próbkę, bez pełnych 8-unit gier.

Akceptacja resolvera **nie dowodzi zgodności z regułami**: reprodukcje
Shoot przy bliskim wrogu, ataku Wyczerpanego i Manewru Przyszpilonego
pozostają w harnessie/raporcie. Nie poprawiano produkcyjnego silnika ani
polityk. Prediction Ostrożnego wymaga opt-in closed v3, którego boty nie
przekazują; znane luki Mobilizacji/Niestrudzonego są oddzielone od jakości
polityki. Ponowne grupowanie danych D5.3b i konkretne kontrprzykłady
slotów ID/kolejności celów pokazują czynniki asymetrii, bez ogłoszenia
uniwersalnej przyczyny wyników lub zmiany domyślnego deployment/tagów.

**Gotowość D6.2:** `priority`, jawny seed, publiczny v1, bounded one-step,
consent-gated proposal. Pierwszy ograniczony zakres bez walki:
Manewr/Defend/discard_exhausted z jawnymi ograniczeniami stanów i profili
w raporcie; nieobsługiwany kandydat daje brak propozycji, bez fallbacku.
V2/v3 nie są obsługiwane przez żaden bot jako lifecycle. Propozycja v2
jest dziś przyjmowana, lecz approval trafia w błąd checkpoint codec v1;
test dowodzi rollbacku i pending. Adapter ma odrzucić tę wersję przed
POST. Rozszerzenie walki potrzebuje wspólnej walidacji, a v2/v3 osobnego
projektu consent lifecycle; nie obchodzić granicy direct-write/core.

Izolowany rzeczywisty HttpClient/FastAPI/SQLite in-memory dowiódł publiczny
odczyt → priority → pending → owner approval executed, sequence 2→6.
Adapter: **2 GET + 1 POST, 15 SELECT (4+5+6), decyzja 0 SQL**; auth zapisuje
audit/last_used, a bitwa pozostaje bez mutacji do approval. Approval service
osobno 8 SELECT bez lookup ownera. Czasy pierwszych decyzji po 32 pomiary
na kind: mean 0,293–4,706 ms; odstający pierwszy priority max 59,789 ms.
Nie ekstrapolować kosztów na duże armie ani zmieniać historycznych ratio.

**Weryfikacja:** 28 nowych przypadków testowych; audit+proposals 35 passed;
celowane pakiety 1007 passed; pełny `pytest -q` **4053 passed, 4 dependency
warnings, 218,59 s**. Encoding gate, call-site audit, ręczne odpowiedniki
simplify/review/security review oraz diff check; bez zmian JS, API/auth,
silnika i DB. Komendy/provenance/denominatory w raporcie.

**Przeniesienie:** raport, manifest, dane, harness i regresje w osobnym
commicie Faza_A, potwierdzanym na origin/Faza_A. SHA256 bazy bez zmian
(wspólny DoD); baza i lokalne sekrety/konfiguracja wymagają osobnego backupu.
Zastane pliki i historyczny hunk B6.2 poza commitem. Brak nowego czerwonego
pytania; rekomendowane ograniczenie D6.2 jest decyzją techniczną dla
koordynatora. Ten worker kończy po audycie i nie uruchamia D6.2.

## 9. D6.2-connect — podłączenie istniejących agentów

Cel: działający ograniczony adapter **publiczny stan → decyzja istniejącego
bota → propozycja akcji**, oparty na wyniku D6.1, factory/registry,
`szop_client.HttpClient` i istniejącym consent-gated `propose_battle_action`.
Zachować podpisy i walidację publicznego klienta, owner/scope i zatwierdzenie
propozycji przez użytkownika. Pokazać pełny przebieg od autoryzowanego
odczytu, wyboru bota i utworzenia propozycji do jej akceptacji przez istniejący
mechanizm oraz aktualizacji stanu/eventów. Nie dodawać alternatywnej ścieżki
zapisu do DB/silnika, pętli w tle ani automatycznego zatwierdzania propozycji.
To podłączenie istniejących agentów; autonomiczna gra UI zostanie podzielona
w D6.3. Jeżeli audyt wykaże brak koniecznego publicznego kontraktu, najpierw
przedstawić koordynatorowi konkretny prerekwizyt zamiast obchodzić granicę.

Warstwy adapter klienta/agentów, istniejąca ścieżka propozycji, testy,
dokumentacja użycia; UI tylko jeżeli potrzebne w istniejącym przepływie.
Zero nowych uprawnień; bez RNG checkpointu w danych bota, sekretów w logach,
zewnętrznych modeli i usług. Bounded one-step, jawny seed decyzji, brak retry
mutacji po niepewnym wyniku; zliczyć requesty/SQL i zmierzyć czas decyzji.

DoD: co najmniej jeden bot z raportu działa end-to-end, obsługiwane kindy
pochodzą z rejestru i dowodów audytu; nieznany/nieobsługiwany kind, cudza
bitwa, zły scope, wygasły token, stale sequence, timeout i powtórka nie
powodują niejawnego zapisu ani wycieku. Testy agent proposals/token security,
HTTP client, battle action proposals i wybranych botów + pełny pytest,
security review, smoke przy JS. Udokumentować protokoły/zdolności/granice.

### Wynik integracji D6.2 — 2026-11-20

[Instrukcja, zakres i odtwarzanie](boty-connect.md) oraz
[adapter/CLI](../szop_client/bot_proposals.py) są trwałym wynikiem etapu.
Koordynator przyjął rekomendację D6.1: `priority`, nowa instancja z jawnym
seedem, publiczny v1 i jeden krok niebojowy. Działające faktyczne decyzje
to Manewr, Mobilizacja (`Defend`) i `discard_exhausted`; wybrany przez bota
Shoot/Charge daje jawny brak propozycji bez zamiany akcji.

Warstwy: nowy leaf klienta/CLI, testy i docs. Nie zmieniano silnika, schema,
HTTP API, auth, JS/CSS ani katalogu X. Reużyto registry/factory, publiczny
`get_battle_metadata` + atomowy `get_state_checkpoint` (state i sequence
razem), codec akcji i ManeuverPlanner. Późniejszy race pozostaje chroniony
CAS-em serwera. Wstępne gate'y wymagają zgodnego v1/headu/rundy/identity,
active perspective, dopuszczonego aktora i profili bez zdolności/override;
odrzucają pending context, Przyszpilony/nieznane statusy i niezweryfikowaną
geometrię. Pierwszy tryb wymaga **jawnie pustego terrain**; brak obsługi terenu
jest konserwatywnym zawężeniem, obejmującym Niebezpieczny.

`BotProposalAttempt.run()` jest one-shot i chroniony lockiem. Zwraca ten sam
wynik przy powtórce/concurrency w instancji. Nie ma retry, automatycznego
approval ani bezpośredniego wykonania. Timeout/5xx/zerwanie/malformed po POST
wymaga jawnej rekoncyliacji ownera. Endpoint nie daje idempotency key/reuse,
więc dedup nie przechodzi przez nową instancję, CLI, restart lub komputer.
Dokumentacja opisuje sprawdzenie istniejących propozycji przed nową próbą.
Owner/scope pozostają serwerowym SSOT: tylko `battle:read` oraz
`agent_proposals:create`, bez `battle:act` i bez nowych kont/uprawnień.

**Weryfikacja:** 59 nowych przypadków w `test_bot_proposals.py`; rzeczywisty
HttpClient → FastAPI → SQLite in-memory → pending, bez zmiany Battle/events/
checkpoint/RNG do osobnego istniejącego HTTP approval przez sesję ownera.
Approval daje executed i state/event/replay parity, a ponowny approval nie
wykonuje akcji drugi raz. Negatywne obejmują kind/alias, v2/v3, mismatch,
terminal/perspective/actor/status/abilities/hazard/geometry, faktyczny
Shoot/Charge, foreign/missing/expiry/scope, prawdziwy CAS race, timeout
przed/po zapisie, 5xx/malformed, redakcję sekretów i concurrent run.
Zestaw proposals/token security/HTTP/priority/registry/factory/audit:
**370 passed, 1 dependency warning**, 15,53 s. Pełny `pytest -q`:
**4112 passed, 4 dependency warnings**, 226,10 s; po końcowym simplify
ponowiony pełny gate: **4112 passed, 4 dependency warnings**, 221,67 s.
Rzeczywisty moduł CLI przeszedł `--help` bez requestów. Komendy są
w instrukcji D6.2. Ostrzeżenia pochodzą z reportlab/openpyxl.

**Koszt:** każdy dodatni krok 2 GET + 1 POST, SELECT **4+5+6=15**,
bot **0 SQL**; brak zapytań per kandydat. Standardowe auth audit/last_used
mogą zapisywać wcześniej niż domena; asercje oddzielają te zapisy od bitwy.
Próbka samej decyzji seed 19, dwie jednostki: Manewr 1,216 ms,
discard_exhausted i Mobilizacja po 0,061 ms. To próbka, nie SLA.
Hot path `/quote`/`/rosters/{id}` i indeksy są nietknięte.

Slash niedostępne: wykonano ręczne simplify/review/security-review. Usunięto
nieużywany import testowy; sprawdzono call sites (wyłącznie nowy CLI/testy,
bez zmian podpisów istniejących klientów), SSOT, redakcję błędów, scope/
no-oracle, osobną zgodę, brak prywatnego RNG i brak retry. Review domknął
overflow promienia i typ statusu HTTP; poprawki przeszły ponowne testy.
Ruff nie jest zainstalowany w `.venv`; ręczny AST check importów i przegląd
diffu wykonano bez instalowania nowych zależności. JS nie zmieniano.

**Przeniesienie i podkład D6.3:** kod/testy/docs w osobnym commicie Faza_A
potwierdzonym na origin/Faza_A; środowisko odtworzyć z requirements i
editable szop_client. Po zmianie komputera lub restarcie najpierw
rekoncyliacja prób. Baza i lokalne sekrety/konfiguracja oraz scheduler/runtime
wymagają osobnego backupu. Produkcyjna `data/szop.db` nietknięta, SHA256
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Zachowano cudzy hunk B6.2 oraz historyczne HANDOFF poza commitem. D6.3
powinno uwzględnić ograniczenia walki/walidatora, lifecycle consent v2/v3,
teren, restart/deduplikację i UX. Nie wdrażano ich w D6.2 ani nie dodawano
nowych markerów. Brak nowej decyzji użytkownika do tego zamknięcia.

## 10. D6.3-play-plan — podział Play vs AI

Cel: gotowe małe etapy dojścia od obecnego podglądu i D6.2 do gry z botem
w UI, zgodnie z zaakceptowanym punktem 5. Zakres: wybór istniejącego agenta,
rosterów/stron/rozstawienia, przebieg tury i przerwań, prawo wykonania akcji,
bounded wykonanie i anulowanie, obsługa konfliktów/reload/restart, informacja
zwrotna i odtwarzanie. Uwzględnić luki wykryte przez D6.1/D6.2 oraz granicę
propozycja/zatwierdzenie/autonomiczne wykonanie.

Warstwy dokumentacja, prototyp opisowy przepływu i test plan. Bez wdrażania
nowego UX/auth/background workera ani płatnej integracji. DoD: indeksowany
plan z kolejnością, zależnościami, plikami, Layer Checklist, kontraktami,
SQL/time budgets i testami każdej części; konkretna decyzja produktowa tylko
jeżeli naprawdę nie wynika z obecnej akceptacji. Sama implementacja UI
wymaga wyboru z tego podziału; nie dodawać jej samodzielnie automation-ready.

### Wynik D6.3 — 2026-11-20

[Plan Play vs AI](play-vs-ai-plan.md) powstał na bazie commitu D6.2
`23022eb9becbf883ec020a3f5ca669d3b7d499f1`. Zawiera opisowy przepływ UI,
maszynę stanów próby, mapę rzeczywistych kontraktów/SSOT i propozycje
P1–P16 z zależnościami, plikami, warstwami, SQL/time gates oraz testami.
P12 i P14 wskazują oddzielne zamykane przebiegi backend/planner/UI.

Rekomendowany pierwszy wybór: **P1 — fail-closed v2/v3 w legacy consent**.
Pierwszy przyrost UI to P2–P5: trwała próba i jawny producent jednego
kroku priority/v1 do pending, osobna zgoda ownera. Dalsze części obejmują
naprawy wspólnej legalności, consent v2/v3, decyzję obrońcy o kontrataku,
setup/rozstawienie, teren, restart i odtwarzanie. Automatyczne wykonywanie
tur bota wymaga osobnej decyzji; wybór bota nie nadaje zgody ani uprawnień.
Nowe kontrakty producenta, v3/kontrataku i round-0 wymagają późniejszego
wyboru, nie są zatwierdzone przez samo planowanie. Publiczny katalog X
pozostaje osobnym zakresem.

Weryfikacja: odczyt źródła Rozjemcy pkt 4/5/8–14/22/24, rzeczywistych
routerów/services/clienta, registry/factory, adaptera D6.2 i modułów UI;
audyt symboli/call sites/linków/kotwic i zależności oraz `git diff --check`.
`scripts/rules_sources_check.py`: **4/4 CLEAN**.
Ręczne simplify/review/security-review rozdzieliły consent od execution,
dedup create od idempotencji approve i stan bitwy od edycyjnego stanu
rozpiski. Zero zmian kodu/testów/UX/auth/DB; pełnego pytest nie ponawiano
dla czystego Markdown. Wynik **4112 passed / 4 warnings** jest bazą D6.2.

Własny nowy commit D6.3 na Faza_A i potwierdzenie identycznego SHA przez
`git ls-remote origin refs/heads/Faza_A` są częścią zamknięcia. Cudzy hunk
B6.2 i historyczne HANDOFF pozostają poza commitem. SHA256 produkcyjnej
bazy bez zmian; baza/sekrety/lokalna konfiguracja/scheduler wymagają
osobnego backupu zgodnie z początkiem kolejki. Plan zawiera instrukcję
kontynuacji na innym komputerze i rekoncyliacji niepewnych prób D6.2.

**Zaakceptowana kolejka 2026-11-19 zakończona.** Nie oznacza to zakończenia
całej roadmapy. Dalsza implementacja wymaga wyboru z planu; nie dodano
nowych markerów gotowości ani nie uruchomiono kolejnego etapu.

## Weryfikacja przygotowania kolejki — 2026-11-19

Zmiany koordynacyjne obejmują wyłącznie Markdown i wznowienie istniejącego
heartbeat. Helper `coordinator_state.py ready-stages` zwrócił dokładnie
10 powyższych ID w tej kolejności. Sprawdzono unikalność markerów, zakresy,
zależności, 10 nowych lokalnych celów linków oraz `git diff --check`.
Simplify/review usunęły nieaktualną odmowę automatycznego startu C2d3 ze
specyfikacji i wskazały datowane informacje historyczne w starej kolejce.
Nie zmieniono kodu ani testów, więc pytest nie ponawiano. SHA256 bazy zgodny
z wartością powyżej. Cudze zmiany pozostają poza commitem kolejki.
