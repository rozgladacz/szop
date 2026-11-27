# Kolejka po D8 — P13, D4 i D5

Roadmapa definiuje [kolejność](roadmap.md#kolejka-po-d8--p13-d4-i-d5).
W P13 i D4.2a wynikiem etapu jest propozycja gotowa do oceny. Jej przyjęcie
jest bramką wdrożenia powiązanego kontraktu. D5.4a może się zakończyć po
zapisaniu wyniku pilota, niezależnie od kierunku zaobserwowanego efektu.

Każdy etap zapisuje wynik, wykorzystaną rewizję i polecenia odtworzenia w
dokumentacji oraz oznacza wynik w Roadmapie. Osobny commit na `Faza_A` trzeba
potwierdzić na `origin/Faza_A`. Przy pakiecie lokalnym poza Git podaj ścieżkę,
sumę kontrolną oraz sposób backupu i odzyskania. Po zmianie kodu obowiązuje
pełny `python -X utf8 -m pytest -q` i pozostałe bramki z [AGENTS.md](../AGENTS.md).

## P13. Kontrakt konfiguracji bitwy i rozstawienia

**Wejście i zakres.** Zależności P2 i D5.3a/b są zamknięte. Przygotuj
propozycję ADR zgodnie z [planem P13](play-vs-ai-plan.md#p13-publiczny-kontrakt-setup-i-rozstawienia).
Przyjmij uzgodnioną pierwszą wersję kreatora dla człowieka i bota, w której
obie rozpiski należą do jednego właściciela.
Opisz przypisanie rozpisek i stron, mapę, teren, cele, seed, protokół,
granice pola, wybór stref i strategii, przebieg rundy 0 oraz wznowienie
i idempotencję tworzenia sesji. Zweryfikuj reguły bezpośrednio w
[SZOP_Rozjemca.md](../app/static/docs/SZOP_Rozjemca.md), w szczególności
pkt 9, 13 i 24. Wskaż różnice między źródłem, kontraktem i aktualnym MVP.

**Warstwy i granice.** ADR, przykładowe wejścia i plan testów, z budżetami
P13 z planu Play vs AI. Opisz kontrakt na istniejącej podstawie D5, w tym
kolejność zajmowania pozycji i dzisiejszy start bitwy. Wdrożenie dotyczy
P14 po akceptacji P13, z zachowaniem wymagań P3 i P10.

**Odbiór.** Wersjonowane przykłady setupu z dwiema własnymi rozpiskami,
ponowienia żądania, braku legalnej pozycji i odrzucenia obcej rozpiski.
Zdefiniuj, co utrwala transakcja i co musi odtworzyć replay rundy 0.
Zmapuj propozycję na obecne
testy `tests/test_battle_creation.py`, `tests/test_agents_deployment.py`
i `tests/test_battle_replay.py` oraz wskaż nowe testy wymagane w P14.

## D4.2a. Kontrakt kont agentów i rankingu

**Wejście i zakres.** Rozwiń drugą część [ADR-0030](adr/0030-multi-agent-leaderboard.md)
w nowej propozycji ADR. Punktem wyjścia są istniejące `User.role`,
`AgentToken`, `AgentPrincipal`, [ADR-0025](adr/0025-agent-scoped-tokens.md)
i narzędzia C3. Rozróżnij właściciela, uczestnika i poświadczenie.
Stabilna tożsamość uczestnika musi pozwolić powiązać wyniki mimo wymiany
lub odwołania tokenu. Źródłem wyniku jest zweryfikowana bitwa, z jednoznacznym
powiązaniem z uczestnikami i deduplikacją ponowionych zapisów. Wskaż, jak
odbudować ranking.

**Decyzje użytkownika 2026-11-27.**

- Zgoda jest udzielana raz na konkretną bitwę rankingową. Przy dwóch
  właścicielach każdy zatwierdza udział swojego agenta. Wspólny właściciel
  potwierdza udział obu agentów jedną zgodą. Po uzyskaniu zgody agenci grają
  samodzielnie w ramach tej bitwy. Kontrakt określa też, jak właściciel
  zatrzymuje dalszą grę.
- Ranking obejmuje wszystkie zakończone, zweryfikowane bitwy rankingowe
  dwóch agentów, zarówno tego samego właściciela, jak i różnych właścicieli.
- Ranking jest publiczny, także bez logowania. Kontrakt określa publiczną
  tabelę wyników i pola potrzebne do jej wyświetlenia. Odczyt szczegółów
  bitwy podlega uprawnieniom uczestników.

**Warstwy i granice.** Dokumentacja przyszłego modelu danych, backendu,
uprawnień i testów. Opisz mały etap wdrożenia i jego budżet zapytań.
Opisz migrację, zakres zgody na bitwę i publiczną projekcję rankingu.
Na potrzeby kontraktu użyj syntetycznych przykładów.

**Odbiór.** ADR obejmuje bitwy agentów jednego i dwóch właścicieli, brak
wymaganej zgody, zatrzymanie gry, remis, niedokończoną bitwę, retry,
odwołany token i odtworzenie rankingu. Uwzględnij anonimowy odczyt rankingu
i odmowę dostępu osoby postronnej do szczegółów bitwy. Przeprowadź
security review kontraktu. Oprzyj plan regresji o `tests/test_agent_token_security.py`,
`tests/test_agent_tokens_router.py`, `tests/test_battle_invite_accept_router.py`
i `tests/test_leaderboard.py`. Wskaż nowe testy przed wdrożeniem.

## D5.4a. Pilot strategii pokrycia celów

**Wejście i zakres.** Użyj geometrii E2/E4 i wspólnej ścieżki D5.3a.
Przetestuj strategię, która preferuje legalną pozycję dodającą najwięcej
dotychczas niepokrytych celów własnej stronie. Z góry zapisz miarę
pokrycia i regułę rozstrzygania remisów. Pokrycie jest miarą eksperymentu.
Za legalność nadal odpowiada `is_deployment_position_legal`. Użyj
dotychczasowego ograniczonego zbioru kandydatów i przekazuj tylko faktycznie
zajęte pozycje. Obsłuż brak celów i wyczerpanie zbioru kandydatów.

**Warstwy i granice.** Funkcja wyboru pozycji, lokalny runner pilota, fixtury,
testy i raport. Podłącz prototyp lokalnie przez `Player.choose_deployment`
i porównaj z wbudowanymi `grid` i `objectives` na tej samej wersji silnika.
Zachowaj formaty archiwum i śladu D7 oraz istniejący publiczny kontrakt i
domyślne rozstawienie. Koszt wyboru jest ograniczony wspólną pulą kandydatów.

**Odbiór.** Zamroź dwie mapy, cztery seedy, dwa warianty stron i inicjatywy
oraz dwie strategie odniesienia. Dwie egzekucje na przypadek dają łącznie
**64 przypadki i 128 wykonań**. Zapisz powtarzalność pozycji i wyników,
pokrycie, koszt obliczeń oraz porażki techniczne. Raport wskaże granice
porównania i komendę odtworzenia. Uruchom `tests/test_agents_deployment.py`,
`tests/test_agents_match.py`, `tests/test_deployment_experiment.py` oraz
nowe testy legalności, niezmienionych domyślnych wyborów i determinizmu.
