---
name: roadmap-coordinator
description: Koordynuj autonomiczną realizację roadmapy projektu szop_a z bieżącego wątku Codex. Używaj podczas heartbeatów i ręcznych poleceń wyboru, wznowienia lub uruchomienia następnego etapu; rozstrzygaj bezpieczne pytania techniczne, eskaluj tylko decyzje rzeczywiście wymagające użytkownika i zapobiegaj duplikowaniu zadań.
---

# Roadmap coordinator

To jest jedyne źródło procedury automatycznego koordynatora. Prompt heartbeat i
`AGENTS.md` mogą wyłącznie wskazywać ten skill, bez kopiowania jego reguł.

Koordynuj jeden aktywny etap naraz. Nie wykonuj implementacji w wątku
koordynacyjnym i nie reaktywuj pełnego protokołu HANDOFF.

## Bramka czasu

Najpierw ustal lokalny czas `Europe/Warsaw`. Od poniedziałku do piątku w
przedziale `13:00:00 <= czas < 19:00:00` zakończ bez odczytywania roadmapy,
uruchamiania zadań i publikowania statusu.

## Trwały stan — zawsze używaj helpera

Stan jest atomowo zapisywany w ignorowanym pliku
`.codex/runtime/roadmap-coordinator-state.json`. Nigdy nie edytuj go ręcznie.
Uruchamiaj helper przez Python repozytorium z `-X utf8`:

```powershell
.\.venv\Scripts\python.exe -X utf8 .agents\skills\roadmap-coordinator\scripts\coordinator_state.py show
.\.venv\Scripts\python.exe -X utf8 .agents\skills\roadmap-coordinator\scripts\coordinator_state.py ready-stages
```

Jeśli `.venv` nie istnieje, użyj skonfigurowanego Pythona workspace. Błąd
odczytu lub zapisu stanu jest fail-closed: nie uruchamiaj workera.

Po inspekcji zapisz dokładnie jedną obserwację:

```powershell
# nic nie pracuje i brak blokady
.\.venv\Scripts\python.exe -X utf8 .agents\skills\roadmap-coordinator\scripts\coordinator_state.py observe --status ready

# worker aktywny lub zakolejkowany
.\.venv\Scripts\python.exe -X utf8 .agents\skills\roadmap-coordinator\scripts\coordinator_state.py observe --status running --stage-key "B4.4d.C2a2" --thread-id "<thread-id>"

# blokada
.\.venv\Scripts\python.exe -X utf8 .agents\skills\roadmap-coordinator\scripts\coordinator_state.py observe --status blocked --blocker-kind "approval_required" --blocker-key "thread:<thread-id>" --blocker-version "<stable-revision>" --blocker-summary "Worker oczekuje na zatwierdzenie narzędzia."
```

Fingerprint to SHA-256 kanonicznych pól `kind`, `key` i `version`; `summary`
jest tylko stabilnym opisem raportowym. Używaj stabilnych wartości, nie czasu
heartbeat:

- approval/pytanie: `key=thread:<id>`, `version=updatedAt` lub digest pytania;
- limit: `key=weekly_limit`, `version=<reason>:<resets_at>`;
- brak etapu: `key=roadmap`, `version=no_automation_ready_stage`;
- błąd: stabilny kod komponentu i istotna rewizja wejścia.

Zmiana sensu pytania, przyczyny, źródłowego `updatedAt` lub czasu resetu ma
zmienić fingerprint. Kosmetyczne przeformułowanie nie powinno go zmieniać.

### Tabela stanów

| Stan + obserwacja | Nowy stan | Powiadom | Działanie |
|---|---|---:|---|
| `READY` + worker | `RUNNING` | nie | zapisz etap i wątek |
| `RUNNING` + brak workera/blokady | `READY` | nie | wyczyść etap |
| dowolny aktywny + nowa/zmieniona blokada | `BLOCKED` | tak | ustaw fingerprint, `first_seen_at`, `last_notified_at`, `unchanged_runs=0` |
| `BLOCKED` + ta sama blokada poniżej progu | `BLOCKED` | nie | zwiększ `unchanged_runs` |
| trzecia identyczna obserwacja lub wiek `>=90 min` | `PAUSE_PENDING` | nie | spróbuj wstrzymać heartbeat |
| pauza automatyzacji potwierdzona | `PAUSED` | tak, raz | uruchom `confirm-pause` |
| `PAUSE_PENDING` + nieudana pauza | `PAUSE_PENDING` | nie | ponów pauzę w następnym przebiegu |
| `PAUSE_PENDING` + blokada znikła przed pauzą | `READY`/`RUNNING` | nie | anuluj oczekującą pauzę |
| `PAUSED` + heartbeat/ręczna kontrola | `PAUSED` | nie | czekaj na jawne wznowienie |
| `PAUSED` + jawne wznowienie użytkownika | `READY` | raport ręczny | wyczyść blokadę i włącz heartbeat |

Pierwsza obserwacja ma `unchanged_runs=0`; trzecia identyczna ma wartość `2`.
Zmiana fingerprintu rozpoczyna nowy cykl i powiadamia. Usunięcie blokady
przechodzi do `RUNNING` albo `READY` bez osobnego powiadomienia.

### Efekty helpera

- `notify=true`: użyj `NOTIFY` wyłącznie dla pierwszej/zmienionej blokady albo
  po potwierdzonej pauzie.
- `pause_automation=true`: przez narzędzie automatyzacji ustaw
  `roadmapa-koordynacja-poza-szczytem-pn-pt` na `PAUSED`, zachowując pozostałe
  pola, i zweryfikuj zapis. Dopiero po sukcesie uruchom:

```powershell
.\.venv\Scripts\python.exe -X utf8 .agents\skills\roadmap-coordinator\scripts\coordinator_state.py confirm-pause
```

Potwierdzenie przechodzi do `PAUSED`, aktualizuje `last_notified_at` i zwraca
jedyny komunikat o automatycznym wstrzymaniu. Gdy zmiana konfiguracji nie
powiedzie się, zostaw `PAUSE_PENDING`; następny heartbeat ponowi próbę bez
powiadomienia.

## Bramka tygodniowego limitu

Bramka dotyczy tworzenia, zastępowania i wznawiania zadań. Nie zatrzymuj zadania,
które już pracuje. Bezpośrednio przed każdą operacją, która uruchomi workera,
wykonaj:

```powershell
.\.venv\Scripts\python.exe -X utf8 .agents\skills\roadmap-coordinator\scripts\check_weekly_limit.py --threshold-percent 10
```

Helper odczytuje najświeższą lokalną telemetrię Codex dla okna `10080` minut,
czyli 7 dni. Pole `remaining_percent` oznacza `100 - used_percent`.

- Gdy `allow_start=true`, możesz wykonać zaplanowaną operację.
- Gdy `remaining_percent < 10` albo `allow_start=false`, nie twórz, nie zastępuj
  i nie wznawiaj zadania.
- Brak pomiaru, niepoprawny pomiar lub pomiar starszy niż 12 godzin traktuj
  bezpiecznie jak `allow_start=false`; nie estymuj limitu z tokenów kontekstu,
  budżetu `/goal` ani czasu pracy.
- Jeśli repozytorium nie ma `.venv`, użyj skonfigurowanego Pythona workspace z
  obowiązkową flagą `-X utf8`.

Każdy wynik `allow_start=false` zapisz jako blokadę w maszynie stanów. To ona
decyduje o pierwszym powiadomieniu, deduplikacji i automatycznej pauzie.

## 1. Sprawdź stan

1. Odczytaj trwały stan, potem użyj narzędzi wątków Codex i sprawdź wszystkie
   relewantne zadania projektu:
   aktywne, zakolejkowane, oczekujące, świeżo zakończone i zarchiwizowane.
2. Jeśli zadanie pracuje, zapisz `running` i nie uruchamiaj kolejnego. Jeśli
   czeka na zatwierdzenie narzędzia, zapisz `blocked`; nie traktuj oczekiwania
   jako zwykłego aktywnego stanu.
3. Jeśli zadanie zakończyło się pytaniem, sklasyfikuj decyzję przed eskalacją.

## 2. Rozstrzygaj pytania autonomicznie

Stosuj kolejno: źródła w repo, zaakceptowane ADR, istniejące kontrakty i testy,
a następnie priorytety `correctness > compatibility > simplicity`.

### Zielone — worker rozstrzyga sam

Nie zatrzymuj pracy dla:

- nazw prywatnych symboli, lokalnego podziału plików i struktury testów;
- odwracalnych szczegółów implementacji;
- wartości lub kształtu jednoznacznie wynikających z przykładów, invariantów,
  call sites albo istniejącego formatu;
- wyboru pomiędzy równoważnymi rozwiązaniami bez wpływu na publiczny kontrakt.

Worker wybiera rozwiązanie, testuje je i opisuje założenie w raporcie.

### Żółte — koordynator rozstrzyga i wznawia

Koordynator samodzielnie podejmuje odwracalną decyzję architektoniczną, gdy:

- mieści się w zatwierdzonym celu etapu;
- nie zmienia reguł gry, zakresu produktu, publicznego API ani modelu zagrożeń;
- można ją obronić kodem, ADR-em, kompatybilnością i testem regresji.

Przed wznowieniem zastosuj bramkę tygodniowego limitu. Jeśli pozwala, wyślij
decyzję do istniejącego zadania i wznów je. Nie pytaj użytkownika.
Zamroź trwały format w ADR lub dokumentacji, jeśli luka dotyczyła kontraktu.

### Czerwone — wymagana decyzja użytkownika

Zatrzymaj pracę i powiadom użytkownika tylko przy:

- sprzeczności aktualnych źródeł reguł albo braku źródła dla rules claim;
- zmianie celu, zakresu produktu, publicznego API/UX lub kompatybilności;
- decyzji o bezpieczeństwie, prywatności, kosztach lub uprawnieniach;
- działaniu zewnętrznym, destrukcyjnym albo trudno odwracalnym;
- dwóch istotnie różnych rozwiązaniach z różnymi skutkami produktowymi.

Zadaj jedno konkretne pytanie z rekomendacją. Nie uruchamiaj innego etapu.
Fingerprint musi uwzględniać treść pytania albo stabilne `updatedAt` zadania.

## 3. Odzyskaj zadanie, które nie daje się wznowić

Jeśli ukończonego lub zarchiwizowanego zadania nie można kontynuować:

1. Sprawdź `git status`, HEAD, ostatni commit i raport zadania.
2. Gdy zadanie nie zmieniło plików i nie utworzyło commitu, a żaden worker nie
   realizuje tego etapu, zastosuj bramkę tygodniowego limitu. Jeśli pozwala,
   utwórz jedno zadanie zastępcze z rozstrzygnięciem i oznacz poprzednie jako
   zastąpione.
3. Gdy istnieją zmiany albo commit, nie twórz duplikatu. Wznów lub przygotuj
   bezpieczny etap integracyjny; przy niejednoznacznym właścicielu zmian zatrzymaj
   się.

## 4. Wybierz następny etap tylko z allowlisty roadmapy

Wybieraj dopiero, gdy nic nie pracuje i nie ma czerwonego pytania.

1. Odczytaj `AGENTS.md`, wynik ostatniego etapu i `docs/roadmap.md`, a następnie
   uruchom helper `ready-stages`.
2. Kandydatem może być wyłącznie otwarty punkt `- [ ]`, który na tej samej
   pozycji ma dokładną etykietę `[automation-ready]`. Nie wyprowadzaj gotowości
   z kolejności, ADR, dawnych wątków, zwykłego `[ ]` ani ogólnego backlogu.
3. Jeśli helper zwraca zero kandydatów, zapisz blokadę
   `no_automation_ready_stage`. Jeśli zwraca więcej niż jeden kandydat i ich
   kolejność nie jest jednoznaczna, zapisz czerwone pytanie; nie wybieraj losowo.
4. Zweryfikuj zależności jedynego kandydata. Koordynator nie dodaje sam etykiet
   `[automation-ready]` i nie rozszerza zakresu etapu.
5. Zdefiniuj cel, zakres, ograniczenia, Layer Checklist, performance gate,
   Definition of Done oraz konkretne testy i artefakty.
6. Zastosuj bramkę tygodniowego limitu. Jeśli pozwala, utwórz jedno osobne
   zadanie w tym samym projekcie. Prompt ma wymagać:
   zachowania cudzych zmian, encoding gate, procedur z `AGENTS.md`, pełnej
   weryfikacji, call-site audit, osobnego commitu i zatrzymania po etapie.
7. W promptach workerów używaj klasyfikacji zielone/żółte/czerwone. Nie nakazuj
   pytać użytkownika przy każdej niejednoznaczności.
8. Po udanym utworzeniu zadania zapisz `running` z ID etapu i wątku. Błąd
   utworzenia zapisz jako blokadę; nie twórz drugiego workera w tym przebiegu.

## 5. Raportuj oszczędnie

Powiadom tylko o:

- uruchomieniu lub zastąpieniu zadania;
- nowym czerwonym pytaniu;
- pierwszej lub zmienionej blokadzie wskazanej przez helper;
- potwierdzonym automatycznym wstrzymaniu po progu;
- zakończeniu całej roadmapy albo braku kolejnego bezpiecznego etapu.

Przy `notify=false` zwróć `DONT_NOTIFY`. Nigdy nie twórz dwóch zadań dla tego
samego etapu i nie reaktywuj pełnego HANDOFF.

## 6. Ręczne wznowienie po blokadzie

Wykonuj tylko na jawne polecenie użytkownika:

1. Potwierdź, że przyczyna blokady została rozwiązana albo świadomie
   zaakceptowana i że żaden worker nie realizuje etapu.
2. Uruchom:

```powershell
.\.venv\Scripts\python.exe -X utf8 .agents\skills\roadmap-coordinator\scripts\coordinator_state.py resume
```

3. Przez narzędzie automatyzacji ustaw istniejący heartbeat na `ACTIVE`, nie
   zmieniając promptu, harmonogramu ani targetu.
4. Jeśli aktywacja nie powiedzie się, stan `READY` jest bezpieczny i polecenie
   `resume` jest idempotentne; ponów wyłącznie aktywację automatyzacji.
5. Poinformuj użytkownika raz o ręcznym wznowieniu. Nie uruchamiaj etapu w tym
   samym ręcznym przebiegu; zrobi to kolejny heartbeat.
