# ADR-0022 — Vector store w sqlite-vec

- **Status:** Accepted
- **Data:** 2026-07-17
- **Kontekst:** Strumień C2.3 po deterministycznym korpusie C2.1 i baseline
  BM25 C2.2.

## Problem

Dense retrieval potrzebuje trwałego indeksu, który działa lokalnie, zachowuje
stabilne ID chunków i nie wprowadza osobnego serwera. Przebudowa nie może
uszkodzić poprzedniego poprawnego indeksu, a publiczne entry pointy nie mogą
ładować rozszerzenia ani bazy ze ścieżki podanej przez użytkownika.

## Decyzja

Używamy `sqlite-vec==0.1.9` przez oficjalny Python binding
`sqlite_vec.load()`. Stała baza `build/rag_vectors.sqlite` zawiera:

- `chunks` ze stabilnym `chunk_id`, tekstem i metadanymi wyniku;
- `index_metadata` z wersją schematu, modelem/rewizją, wymiarem, wersją
  sqlite-vec, count i SHA-256 całego manifestu C2.1;
- `rag_vectors` jako `vec0`, float32[384], cosine distance.

Rebuild tworzy bazę tymczasową w tym samym katalogu, ustawia SQLite
`synchronous=FULL`, zapisuje komplet 36 rekordów, zamyka i synchronizuje plik,
sprawdza integrity, metadata, chunk count, vector count, ID, wymiar i finite, a
następnie używa `os.replace`. Awaria przed replace zachowuje poprzedni indeks.

Dense query pobiera wszystkie obecne 36 odległości z `vec0` i stabilizuje
kolejność po `(distance, chunk_id)`. API/CLI przyjmuje tylko query i limit;
ścieżka bazy i sposób ładowania rozszerzenia są stałe.

API bindingu i składnia `vec0` zostały sprawdzone w oficjalnej dokumentacji:
[Python binding](https://alexgarcia.xyz/sqlite-vec/python.html),
[KNN/vec0](https://alexgarcia.xyz/sqlite-vec/features/knn.html) oraz
[PyPI 0.1.9](https://pypi.org/project/sqlite-vec/0.1.9/).

## Konsekwencje

- Pozytywne: jeden przenośny plik, brak serwera, atomowa odbudowa, jawne stale
  detection i pełna praca offline.
- Koszt: sqlite-vec jest pre-v1; pin wersji i metadata wersji rozszerzenia są
  częścią kompatybilności indeksu.
- Koszt: pełne sortowanie 36 odległości jest świadome dla stabilnych remisów;
  strategię trzeba ponownie ocenić przy znacząco większym korpusie.
- Odkładamy: dense+BM25 hybrid, recall@5 hybrid oraz wrappery MCP/HTTP.

## Alternatywy rozważone

- Zwykły BLOB + ręczne distance — odrzucone, bo nie tworzy docelowego store
  `vec0` i omija jego kontrakt KNN.
- Zewnętrzny vector DB — odrzucony jako nieproporcjonalna usługa operacyjna dla
  36 chunków i wymagania local-first.
- Zapis bezpośrednio do pliku docelowego — odrzucony, bo awaria rebuild mogłaby
  zniszczyć poprzedni poprawny indeks.
