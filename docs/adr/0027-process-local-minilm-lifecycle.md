# ADR-0027 — Procesowy lifecycle fixed MiniLM

- **Status:** Accepted
- **Data:** 2026-07-18
- **Kontekst:** Strumień C2.5 po trwałym dense store C2.3 i benchmarku
  hybrid C2.4.

## Problem

Domyślne `rebuild_index()` i każde `dense_search()` tworzyły nowy leniwy
`SentenceTransformerEmbedder`. Adapter był lekki, ale pierwsze `embed()` każdej
instancji ponownie konstruowało MiniLM. Pełny benchmark C2.4 wykonywał 60 dense
queries i wielokrotnie ładował ten sam przypięty model. Przyszłe wrappery
runtime wymagają przewidywalnego lifecycle, lecz nie mogą osłabić offline-only,
lazy importu, dependency injection ani granicy osobnego downloadu.

## Decyzja

`mcp_server.embeddings.get_default_embedder()` zwraca jeden procesowy adapter
offline, tworzony leniwie pod dedykowanym lockiem. Domyślne `rebuild_index()` i
`dense_search()` pobierają ten adapter wyłącznie wtedy, gdy caller nie przekazał
jawnego `Embedder`; injection nadal całkowicie omija singleton.

Sam `SentenceTransformerEmbedder` ma dwa małe locki:

- model-load lock z ponownym sprawdzeniem stanu zapewnia najwyżej jedną udaną
  konstrukcję fixed MiniLM przy równoległym first use; wyjątek nie zapisuje
  modelu i następne wywołanie może bezpiecznie ponowić próbę;
- encode lock serializuje inference współdzielonej instancji, ponieważ publiczny
  kontrakt SentenceTransformer nie gwarantuje thread-safe równoległych wywołań
  `encode` na jednym modelu.

Nie ma cache tekstów ani wektorów użytkownika. Ciężkie moduły pozostają za
importem wewnątrz `_load_model()`. Zwykły singleton zawsze zachowuje stałe
model ID, rewizję, cache `build/models`, CPU, backend torch,
`local_files_only=True`, `trust_remote_code=False` i `token=False`.
`download_model()` tworzy osobny, krótkotrwały adapter z
`allow_download=True`; nie odczytuje ani nie modyfikuje singletonu offline.

Stały `mcp_server.retrieval_benchmark` najpierw wymaga zgodnego `check_index()`,
a następnie w jednym procesie mierzy dokładnie sześć istniejących rekordów
`eval-rules-001`–`006` przez `hybrid_search`. JSON-safe raport zawiera cold first
call, warm p50/p95, total, status indeksu i rankingi `chunk_id`; CLI nie przyjmuje
query, modelu ani ścieżki.

Pomiar offline na tym samym modelu, indeksie, korpusie i gold secie:

| Wariant | Cold (s) | Warm p50 (s) | Warm p95 (s) | Total 6 (s) |
|---|---:|---:|---:|---:|
| Przed C2.5 | 18,516 | 2,610 | 3,577 | 32,269 |
| Po C2.5 | 14,691 | 0,080 | 0,090 | 15,107 |

Warm p50 przyspieszył około 32,5×. Wszystkie sześć rankingów pozostało
identycznych. Pełne 30 pytań dało BM25 24/30 w 0,048 s, dense 8/30 w
16,031 s i hybrid 24/30 w 2,739 s; lista hit/miss hybrid pozostała identyczna z
C2.4, bez przypadków poprawionych lub pogorszonych względem BM25.

## Konsekwencje

- Pozytywne: koszt konstrukcji modelu jest płacony najwyżej raz na proces dla
  zwykłej ścieżki offline, a kolejne query korzystają z warm inference.
- Pozytywne: równoległy first use i inference mają jawny, testowalny kontrakt;
  błąd ładowania nie zatruwa procesu na stałe.
- Koszt: encode jest świadomie serializowane, więc pojedynczy proces nie skaluje
  inference przez wątki; priorytetem jest bezpieczny współdzielony model CPU.
- Koszt: cold start nadal wynosi około 14 s na mierzonym środowisku Windows.
- Odkładamy: runtime wrappery MCP/API, HTTP, discovery tools, cache zapytań,
  batching między requestami, zmianę modelu, GPU i multiprocessing.

## Alternatywy rozważone

- `functools.lru_cache` na fabryce — odrzucone, ponieważ przy równoległym miss
  owinięta funkcja może wykonać się więcej niż raz.
- Singleton konstruowany przy imporcie — odrzucony, bo łamie lazy lifecycle i
  granicę importu ciężkich bibliotek.
- Współbieżne `encode` bez locka — odrzucone z powodu braku gwarancji
  thread-safety współdzielonego SentenceTransformer.
- Cache query→vector — odrzucone jako niepotrzebne przechowywanie danych
  użytkownika i inny lifecycle niż cache modelu.
