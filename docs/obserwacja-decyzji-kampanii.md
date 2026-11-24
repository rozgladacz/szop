# D7.4a — obserwacja decyzji w kampanii v1

Opcjonalny `on_observation` przekazuje synchroniczny strumień rekordów Pythona
z rozstawienia i walki. Można go podać do
`app.services.agents.match.simulate_from_rosters`, włączyć dla samej walki
przez `run_match` albo podłączyć do `scripts.deployment_experiment.run_once`,
czyli pojedynczego wykonania przypadku używanego przez kampanię v1. Przykład
pilota poniżej używa tego ostatniego wejścia.

## Kontrakt śladu

| Rekord | Dane |
|---|---|
| `DeploymentDecision` | Roboczy stan widziany przez wybierającego, gracz, oddział, strefa, zajęte miejsca obu stron, dotychczasowe przydziały celów, faktyczna strategia (`None` oznacza callback), zwrócona pozycja, wynik walidacji i cel zwrócony przez strategię, jeśli go wskazała. |
| `ActionDecision` | `choose_action` lub `continue_activation`, stan widziany przez bota, perspektywa, kontekst oddziału i wcześniejszych akcji, zwrócony wybór oraz wynik `applied`, `rejected`, `none` albo `error`. Dla wykonania zawiera stany przed i po pojedynczej akcji oraz jej zdarzenia w oryginalnej kolejności. |
| `AutomaticTransition` | Stany przed i po kroku automatycznym, jego własne zdarzenia i kontekst. Kroki obejmują faktyczny ruch i domknięcie rozstawienia, początek i koniec aktywacji, zatrzymanie bez kolejnego wywołania bota, przekazanie inicjatywy i koniec rundy. |

Pierwszy `ActionDecision.seen_state` pochodzi sprzed rozpoczęcia aktywacji.
`before` pochodzi już z chwili bezpośrednio przed wykonaniem akcji.
`activation_started` może dlatego poprzedzać pierwszy rekord wyboru, choć
wybór został dokonany wcześniej. `activation_finished` oraz przekazanie
inicjatywy mają osobne zdarzenia. `activation_stopped` oznacza, że resolver
zakończył pętlę bez następnego wywołania dostawcy kontynuacji, np. przy
`action_limit`. Faktyczne `None` od bota ma rekord decyzji z `outcome="none"`.

`reason` dla odrzucenia pochodzi ze wspólnej walidacji, np.
`maneuver_over_budget` lub `invalid_deployment_position`. Rejestracja
odróżnia odrzucenie od błędu wykonania i od wyczerpania ograniczonego
przeszukiwania rozstawienia (`no_deployment_candidate`). Odrzucone wybory i
`None` mają puste `events`. Gdy kod wyboru lub akcja zgłasza wyjątek,
obserwator może zachować już otrzymany prefiks i rekord błędu, a wyjątek
biegnie dalej zwykłą ścieżką. `applied` opisuje faktyczne wykonanie w
obecnym runnerze v1. Ocena zgodności z pełnym profilem reguł ma osobny etap.

Rozstawienie najpierw tworzy listę wyborów. Przyjęty wybór ma
jednobazowy `placement_index`, który wiąże go z sekwencją faktycznego
`deployment_moved` dla tego samego oddziału. Dopiero `deployment_moved`
potwierdza wykonanie, gdyż późniejsze odrzucenie w fazie wyborów może
zatrzymać całą listę przed wykonaniem. Jawne `deployment` daje kroki
wykonania bez wywołania polityki. `deployment_finished` zachowuje migawkę
po rozstawieniu, również przy przejściu rundy bez osobnego zdarzenia.
Zdarzenia rozstawienia i walki mają odrębną numerację od 1.

Strategię, walidator i RNG wywołuje istniejąca ścieżka wykonania. Ślad pomija
kandydatów, których interfejs polityki nie zwrócił. Rekord może trzymać
referencję do niemutowalnego stanu. Mutowalne payloady decyzji i zdarzeń
akcji są odłączone od danych runnera. Odbiorca działa w tym samym wątku i
powinien zakończyć szybko. Rzucony przez niego wyjątek może przerwać ślad.
Dotychczasowy `on_decision` może działać jednocześnie i dalej otrzymuje
tylko wykonane akcje.

## Pilot i odtworzenie

Próbka wykorzystuje manifest D7.1 i dwa mieszane przypadki `demo_skirmish`
polityki `priority`. Na przypadek jedno rozgrzanie w każdej konfiguracji,
następnie 12 przeplatanych powtórzeń z obserwacją i 12 bez. Pomiar obejmuje
wykonanie adaptera `run_once` wraz z rozstawieniem i jego kontrolą replay.
Kolekcja śladu odbywa się w pamięci. Wielkość próbki ogranicza wnioskowanie
o wydajności innych scenariuszy. Poniżej mediany z Windows, Python 3.13.14.

| ID przypadku | Wybory rozstawienia i walki | Zdarzenia rozstawienia i walki | Bez śladu | Ze śladem |
|---|---:|---:|---:|---:|
| `762b987db7935fad6f8e` | 8 + 64 | 16 + 236 | 73,607 ms | 70,602 ms |
| `28256c014c9a157731df` | 8 + 62 | 16 + 231 | 92,118 ms | 94,998 ms |

W obu przypadkach kontrola replay przeszła, ślad był identyczny w
powtórzeniach, a wynik, skrót logu i skrót stanu końcowego były zgodne bez
obserwacji i z nią. Mediany zmieniły się odpowiednio o −4,1% i +3,1%.
Kierunek różnicy zależał od próbki.

```powershell
$pilot = @'
from collections import Counter
import json
import platform
from pathlib import Path
from statistics import median
from time import perf_counter

from scripts import deployment_experiment as experiment
from app.services.engine.observation import ActionDecision, AutomaticTransition

manifest = experiment.load_manifest(Path("docs/experiments/d7_1/manifest.json"))
coordinates = [
    (11, False, 0, ["objectives", "grid"]),
    (19, True, 1, ["grid", "objectives"]),
]
cases = list(experiment.iter_cases(manifest))
print(platform.python_version(), platform.system())
for coordinate in coordinates:
    case = next(c for c in cases if (
        c["seed"], c["swap"], c["initiative"], c["strategies"],
    ) == coordinate)

    def play(enabled):
        trace = []
        start = perf_counter()
        row = experiment.run_once(case, manifest, on_observation=trace.append if enabled else None)
        return (perf_counter() - start) * 1000, experiment.deterministic(row), trace

    _, baseline, _ = play(False)
    _, observed, reference = play(True)
    assert observed == baseline and baseline["status"] == "complete" and baseline["replay_equal"]
    deployment = [
        event for r in reference if isinstance(r, AutomaticTransition) and r.kind.startswith("deployment_")
        for event in r.events
    ]
    battle = [
        event for r in reference
        if not isinstance(r, experiment.match.DeploymentDecision)
        and not r.kind.startswith("deployment_")
        for event in r.events
    ]
    assert [event.sequence for event in deployment] == list(range(1, len(deployment) + 1))
    assert [event.sequence for event in battle] == list(range(1, len(battle) + 1))
    assert experiment.digest([experiment.event_to_json(e) for e in battle]) == observed["event_digest"]
    samples = {False: [], True: []}
    for index in range(12):
        for enabled in (False, True) if index % 2 == 0 else (True, False):
            elapsed, row, trace = play(enabled)
            assert row == baseline
            if enabled:
                assert trace == reference
            samples[enabled].append(elapsed)
    print(json.dumps({
        "case": case["id"],
        "decision_counts": dict(Counter((r.kind + ":" + r.outcome) for r in reference if isinstance(r, ActionDecision))),
        "deployment_decisions": sum(isinstance(r, experiment.match.DeploymentDecision) for r in reference),
        "deployment_events": len(deployment),
        "battle_events": len(battle),
        "automatic": sum(isinstance(r, AutomaticTransition) for r in reference),
        "winner": baseline["winner"],
        "score": baseline["score"],
        "event_digest": baseline["event_digest"],
        "final_digest": baseline["final_digest"],
        "median_off_ms": round(median(samples[False]), 3),
        "median_on_ms": round(median(samples[True]), 3),
    }, sort_keys=True))
'@
$pilot | .\.venv\Scripts\python.exe -B -X utf8 -
```

## Weryfikacja

- **252 testy celowane** obejmują runner, rozstawienie, resolver, adapter,
  D7.1, LocalClient i goldeny B7. Testy porównują faktyczne wywołania botów,
  decyzje, logi, wynik, stan i dalsze rzuty. Sprawdzają też rozdzielenie etapów,
  odrzucone wybory, `None`, częściową listę rozstawienia oraz parytet
  dotychczasowego `on_decision`.
- **4222 testy w pełnym `pytest -q`**, cztery ostrzeżenia zależności.
- `python -B -X utf8 -m scripts.engine_smoke_replay` potwierdził zgodność
  odtworzenia na 34 zdarzeniach.

Audyt wywołań objął `LocalClient`, tworzenie bitwy, protokoły aktywacji,
symulację rozpisek, audyt botów i narzędzia CLI korzystające z runnera.
Używają istniejących wejść, a obserwator jest opcjonalny. Wspólne walidatory
zachowują typ i tekst wyjątku. `run_case` i dziennik D7.1 zachowują dotychczasowy
format. Przegląd objął granice zdarzeń, działanie bez odbiorcy, odłączenie
mutowalnych payloadów oraz ścieżki błędów. Instrumentacja działa bez zapytań
SQL i bez I/O po stronie runnera.

## Kontynuacja na innym komputerze

Kod, kontrakt, polecenie i wynik pilota są w Git. Pełny ślad jest odtwarzany
z manifestu i fixtury, więc pilot nie wymaga kopiowania plików runtime.
Istniejące archiwa kampanii zachowuje się według
[instrukcji backupu](archiwum-eksperymentow.md#backup-i-odtworzenie).
`campaign_v1` nadal sprawdza fingerprint źródeł i stosuje dotychczasowy
format. Zmiana obserwowanych modułów zmienia fingerprint nowego checkoutu.
Wcześniej rozpoczętą kampanię wznowić na rewizji zgodnej z fingerprintem
jej nagłówka po wykonaniu `verify`. [Instrukcja D7.1](trwala-kampania-v1.md)

D7.4b może użyć kolektora `run_once` do budowy wersjonowanego pakietu,
sprawdzić odtworzenie walki ze stanu po rozstawieniu i połączyć decyzje z
konkretnymi sekwencjami. D7.4a dostarcza obserwacje w pamięci, a trwały
eksport pozostaje w D7.4b.
