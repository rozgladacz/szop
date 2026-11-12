# ADR-0057 — Trasy Manewru i kolizje

- **Status:** Accepted
- **Data:** 2026-11-12
- **Zakres:** E4
- **Zastępuje:** [ADR-0052](0052-maneuver-final-clearance.md)

## Źródła

Manewr wykonuje Ruch (pkt 14.a). Żywe modele stanowią przeszkodę (pkt 2.d).
Teren Niedostępny zabrania przejścia i zatrzymania (pkt 4.c.i). Przejście
przez Trudny obniża o połowę budżet całego ruchu (pkt 4.c.iv i 15.a).
Aktualny pkt 15.c znosi wymóg 1″ pomiędzy oddziałami. ADR-0052 opierał się
na historycznym pkt 15.b.iii, którego nie ma w aktualnym tekście.
[SZOP_Rozjemca.md](../../app/static/docs/SZOP_Rozjemca.md)

Budżet wejściowy pochodzi z `effective_move_inches`, które uwzględnia
Szybki, Wolny i czasowe zmiany zdolności (poz. 33).
[SZOP_Zdolnosci.md](../../app/static/docs/SZOP_Zdolnosci.md)

## Decyzja

- `ManeuverAction` deklaruje dokładny punkt końcowy. Resolver szuka legalnej
  trasy w stanie sprzed tej akcji. To samo sprawdzenie obowiązuje dla kolejnej
  akcji w lokalnej aktywacji i w trwałym protokole v2/v3.
- Przesuwamy koło oddziału, reprezentację Pareto MVP. Cała powierzchnia,
  którą pokrywa podczas ruchu, jest testowana na każdym odcinku, również na
  skosach i przy wejściu do celu. Przeszkodami są żywe oddziały na Froncie
  i teren Niedostępny, z uwzględnieniem kół, odcinków i wielokątów
  [E2](0041-terrain-polygons.md). Koła oddziałów mogą się stykać (pkt 15.c),
  a brzeg terenu jest częścią przeszkody. Jeżeli stary stan zawiera
  nakładające się oddziały, ruch może wyprowadzić je z kolizji bez
  pogłębiania nakładania. Punkt końcowy musi być wolny.
- Najpierw sprawdzamy prosty odcinek. Gdy potrzebny jest objazd, A* bada
  lokalną siatkę heksagonalną o kroku 1″, zaczynającą się w pozycji oddziału,
  oraz dokładne odcinki od osiągalnych węzłów do celu. Dijkstra na tej samej
  siatce zwraca kandydatów do decyzji botów. Rozróżniamy trasy czyste i
  przecinające Trudny. Krótsza trasa przez Trudny nie wypiera dłuższej czystej,
  jeżeli tylko ta druga mieści się w swoim budżecie.
- Prosta trasa nie wymaga budowania grafu. Szukanie objazdu ma O(B²) węzłów
  dla budżetu B w calach i do sześciu sąsiadów na węzeł. Każdy węzeł może
  mieć dwie etykiety. Pomijamy przeszkody poza zasięgiem przed wyszukiwaniem
  oraz teren o rozłącznej obwiedni przy sprawdzaniu odcinka. Przeszukiwanie
  nie wymaga zapytań SQL, dodatkowych bibliotek ani losowania.

## Konsekwencje

- Walidacja przyjmuje trasę w obrębie siatki z dokładnym odcinkiem do celu.
  Bardzo ciasny objazd między węzłami może zostać odrzucony, nawet jeżeli
  istnieje w geometrii ciągłej. Wyszukiwanie używa aktualnego budżetu ruchu,
  więc bot może wybrać legalny postęp w tym Manewrze, bez planowania wielu tur.
- Zdarzenie ruchu zapisuje dotychczasowy punkt początkowy i końcowy.
  Odtwarzanie z dziennika nie wyznacza tras i stosuje już zapisane wyniki,
  także dla bitew sprzed E4.
- Osobno pozostają ruch Związania, rozstawienie, odzysk ze starego
  nakładania na Niedostępny, granice planszy, łączenie przerw między
  terenami z pkt 4.b i wykrywanie przejść przez Niebezpieczny (pkt 4.c.v).
- Odświeżono sześć przebiegów B7 po porównaniu z kodem sprzed E4. Np. w
  `demo_priority_mirror` drugi Manewr oddziału 3 zastępuje Obronę od
  zdarzenia 31. W `clash_priority_vs_greedy` trasa zmienia pozycję
  docelową w zdarzeniu 24. W `clash_random_mirror` zestaw kandydatów
  zmienia już wybór pierwszego oddziału. Zestaw nadal zawiera zwycięstwa
  każdej strony oraz remis.
