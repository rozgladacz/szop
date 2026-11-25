# ADR-0059 — Wspólne ograniczenia wyboru akcji i statusy

- **Status:** Accepted
- **Data:** 2026-11-25
- **Kontekst:** P6, reprodukcje D6.1 i regresja Mobilizacji.

## Decyzja

[Rozjemca](../../app/static/docs/SZOP_Rozjemca.md) w pkt 14.c.iv i 6
blokuje wybór Ostrzału, gdy dowolny żywy wróg jest widoczny w zasięgu 2″.
Sprawdzamy odległość obwód–obwód w modelu MVP oraz istniejący `check_los`.
Osłona nadal oznacza widoczność. Wybór celu i jego widoczność to osobny
warunek z pkt 14.c.i. Niebezpośredni ma wyjątek od widoczności celu zgodnie
z [poz. 62 Zdolności](../../app/static/docs/SZOP_Zdolnosci.md).

Status Wyczerpany blokuje atak (pkt 22.a.i), a Przyszpilony blokuje
Manewr (pkt 22.b.i). Strażnik (poz. 31 Zdolności) i istniejący kontratak
(pkt 14.d.iv) korzystają z tych samych ograniczeń dotyczących ich aktora.
Strażnik zachowuje rygorystyczne odrzucenie podwyższonej linii wzroku,
której geometria MVP nie reprezentuje. Bastion (poz. 1 Zdolności) nadal
wpływa na nadanie Wyczerpanego po kontrataku.

Mobilizacja nadaje Przygotowanego (pkt 14.b). Wspólny `MutexCollision`
usuwa oba statusy po ich współwystąpieniu (pkt 22.b.iii i 22.c.iv).
Istniejący reducer obsługuje też starszy ogon z `StatusRemoved`. Odtwarzanie
historycznej bitwy stosuje zapisane zdarzenia.

## Pierwsze różnice pełnych logów B7

Porównano serializowane logi siedmiu tych samych scenariuszy i seedów
na bazie `0b99a06` oraz po wdrożeniu. Wspólny prefiks każdego logu
odtworzono do stanu sprzed pierwszej różnicy. W tym stanie porównano
kandydatów bazowego i bieżącego enumeratora, a dla specjalizowanych
polityk również stan i wynik wspólnej blokady Ostrzału.

| Scenariusz | Pierwsza różnica | Wynik i liczba zdarzeń przed → po |
|---|---|---|
| `demo_priority_mirror` | Seq 102. Mobilizacja jednostki 4 kończy się `MutexCollision` w miejscu `StatusRemoved(Przyszpilony)`. | P1 (2,3), 245 → P1 (2,3), 243 |
| `demo_priority_mirror_draw` | Seq 99. Mobilizacja jednostki 1 usuwa oba statusy. | remis (2,2), 250 → remis (2,2), 247 |
| `demo_greedy_vs_random` | Seq 161. Lista jest krótsza o Szarżę Wyczerpanej jednostki 6. Random wybiera Manewr jednostki 7 w miejsce Mobilizacji tej jednostki. | P1 (2,3), 212 → P1 (2,3), 203 |
| `clash_priority_vs_greedy` | Seq 82. Brak Szarży Wyczerpanej jednostki 6. Greedy wybiera Ostrzał jednostki 8. | P0 (2,1), 214 → P0 (3,0), 203 |
| `clash_random_mirror` | Seq 67. Lista jest krótsza o dwa Manewry Przyszpilonej jednostki 6. Random zmienia cel Ostrzału jednostki 8 z 1 na 3. | P1 (0,1), 225 → P1 (0,1), 234 |
| `profiles_v3_vs_v2` | Seq 85. Widoczny bliski wróg blokuje Ostrzał jednostki 7, bot wybiera Szarżę. | P0 (3,2), 247 → P0 (3,2), 256 |
| `profiles_v2_vs_priority` | Seq 71. Widoczny bliski wróg blokuje Ostrzał jednostki 7, bot wybiera Szarżę. | P1 (2,3), 235 → remis (2,2), 234 |

Gate B7 nadal sprawdza powtarzalność, replay, remis oraz wyniki obu stron.
Nowe hashe są w [zestawie B7](../../tests/test_engine_regression.py).
Uruchomienie pliku jako skryptu wypisuje hashe bieżącej rewizji. Dane D6.1
i D7 pozostają przypięte do swoich rewizji.

## Granice

LoS używa istniejącej aproksymacji kół i terenu. Kształty podstawek
poszczególnych modeli, ich zasłanianie i wysokość pozostają poza tym
profilem geometrii. Funkcja `expected_damage` liczy wynik warunkowy dla
zadanego ataku. Policy filtruje kandydatów przed użyciem estymacji.
Zakres wniosków z P6 kończy się na opisanych ograniczeniach. Kwalifikacja
danych do uczenia pozostaje oparta na profilu D7.3c.

## Zgodność dowodu D7.3c

Profil D7.3c przypina cały plik `phases.py`, ponieważ dowód rozstawienia
wywołuje `deployment_round`. Porównanie P1 (`0b99a06`) i P6 potwierdziło
bajtową zgodność `deployment_round`, `setup_phase`, `_find_blob` i
`_replace_blob` po normalizacji końców linii. Porównanie AST ograniczyło
zmiany tego pliku do Mobilizacji i opisów kolizji oraz początku aktywacji.
Reducer i kodeki zdarzeń pozostały zgodne, więc replay używa zapisanych efektów.

Kwalifikator przyjmuje dwie dokładne rewizje `phases.py` z końcami LF lub
CRLF. Pozostałe przypięcia i zakres wyboru miejsca obowiązują dalej.
Nierozpoznana wersja pliku zatrzymuje ocenę. Raport oznacza nowy dowód
`compatible_phase_sha256` i wiąże go z `compatible_sources_lf_sha256` w
haszowanym profilu, dzięki czemu zachowuje osobny identyfikator. Raport dla
wcześniejszych pakietów korzysta z pierwotnego profilu i identyfikatora.
