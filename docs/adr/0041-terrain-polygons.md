# ADR-0041 — Wielokąty terenu

- **Status:** Accepted
- **Data:** 2026-11-12
- **Zakres:** E2

## Kontekst

Silnik odwzorowywał teren kołem lub odcinkiem. Żaden z tych kształtów nie
oddaje załamanego obrysu terenu. Źródło reguł definiuje wnętrze elementu w
pkt 4.a, cechy terenu w pkt 4.c i linię wzroku w pkt 6.
[SZOP_Rozjemca.md](../../app/static/docs/SZOP_Rozjemca.md)

## Decyzja

- `TerrainPolygon` przechowuje jeden prosty, zamknięty obrys z 3–256
  skończonych wierzchołków. Ostatnia krawędź prowadzi z ostatniego wierzchołka
  do pierwszego. Obsługujemy obrysy wypukłe i wklęsłe w obu kierunkach.
  Odrzucamy powtórzone wierzchołki, nakładanie i przecięcia krawędzi oraz
  pole równe zeru. Obrys nie ma otworów.
- Kształty udostępniają sprawdzanie wnętrza i przecięcia odcinka.
  Wielokąt używa testu parzystości przecięć dla punktu oraz testów krawędzi
  dla odcinka. Styk należy do obrysu, tak jak dla koła. Odcinek jako
  samodzielny element terenu może przecinać promień, ale nie ma wnętrza.
- LoS zachowuje próbkowanie i trzy wyniki z [ADR-0043](0043-los-3-state.md).
  W wielokącie `Blokujacy` zatrzymuje przecinające go promienie, a
  `Zaslaniajacy` nie blokuje pary, gdy centrum któregoś oddziału jest w
  obrysie lub na jego krawędzi. Centrum koła oddziału pozostaje
  przybliżeniem wnętrza z pkt 4.a. To samo sprawdzenie kształtu obsługuje
  osłonę z `Obronny` i dotychczasowy test pozycji końcowej Manewru w
  `Niebezpieczny`. Źródło tych cech opisuje pkt 4.c.ii, iii, v i vi.
  [SZOP_Rozjemca.md](../../app/static/docs/SZOP_Rozjemca.md)
- Checkpointy v1–v3 dostają addytywny znacznik `TerrainPolygon` z polami
  `vertices` i `features`. Krawędzie i obwiednia są obliczane przy
  odczycie. Dotychczasowe znaczniki i pola pozostają bez zmian. Podgląd
  2D czyta i rysuje nowy kształt z istniejącego checkpointu.
- Fixtura YAML może określić `shape: polygon`, `vertices: [[x, y], ...]` i
  opcjonalne `features`. Pythonowy klient lokalny przyjmuje poligon na
  tej samej ścieżce co pozostałe kształty. Publiczne żądania HTTP tworzące
  bitwę nadal korzystają z istniejących map.

## Konsekwencje

Walidacja obrysu jest kwadratowa względem liczby wierzchołków i ma stały
limit rozmiaru. LoS odrzuca rozłączne obwiednie przed przejściem po
krawędziach. Weryfikacja punktu lub odcinka ma koszt liniowy w liczbie
krawędzi. Koła i odcinki zachowują swoje testy geometryczne o stałym
koszcie. Nie dochodzą zapytania do bazy ani biblioteki.

Walidacja tras i kolizje w ruchu należą do E4. Ten etap zachowuje
przybliżenia silnika dotyczące oddziałów oraz rozłącznych elementów
terenu, w tym istniejący brak łączenia przerw z pkt 4.b.
[SZOP_Rozjemca.md](../../app/static/docs/SZOP_Rozjemca.md)
