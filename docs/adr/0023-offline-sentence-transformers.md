# ADR-0023 — Sentence-transformers offline

- **Status:** Accepted
- **Data:** 2026-07-17
- **Kontekst:** Strumień C2.3, embeddingi dla trwałego store z ADR-0022.

## Problem

Korpus jest polskojęzyczny i wymaga stałych embeddingów semantycznych, ale
zwykły import aplikacji/MCP oraz standardowy pytest nie mogą ładować ciężkiego
stosu ML ani wykonywać ukrytych pobrań sieciowych.

## Decyzja

Używamy `sentence-transformers==5.6.0` i jednego modelu
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` w rewizji
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Model zwraca 384 wymiary zgodnie
z [oficjalną kartą modelu](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
i jest uruchamiany wyłącznie na CPU przez przypięty PyTorch CPU.

Adapter importuje sentence-transformers leniwie, batchuje po 16, wymusza
`device=cpu`, `trust_remote_code=False`, float embeddings i normalizację L2, a
następnie niezależnie waliduje count, wymiar, finite i niezerową normę.

Jedna osobna komenda może pobrać przypiętą rewizję do stałego, gitignored
`build/models`. Rebuild i dense query zawsze używają tego cache z
`local_files_only=True`; publiczne API/CLI nie przyjmuje model ID, rewizji ani
ścieżki cache. Zależności są wyłącznie w `requirements-rag.txt`, nie w bazowym
profilu aplikacji.

Aktualne parametry `cache_folder`, `revision`, `local_files_only`, `device` i
`normalize_embeddings` potwierdzono w
[dokumentacji SentenceTransformer](https://sbert.net/docs/package_reference/sentence_transformer/model.html)
oraz [PyPI 5.6.0](https://pypi.org/project/sentence-transformers/5.6.0/).

Realny smoke CPU przeszedł 2026-07-17: pobranie i probe 34,9 s; offline
3×384 embeddingów 11,622 s; pełny rebuild 36 chunków 4,053 s; ponowne otwarcie
indeksu i dense top-5 offline 2,391 s. Cache Windows bez symlinków zajmował
479 729 205 B, a baza 1 769 472 B.

## Konsekwencje

- Pozytywne: po jawnym bootstrapie wszystkie zwykłe operacje dense działają bez
  sieci i są związane z dokładną rewizją modelu.
- Pozytywne: import `mcp_server.server` nie importuje torch/transformers i nie
  widzi nowego narzędzia.
- Koszt: opcjonalny profil oraz cache modelu są duże; Windows bez symlinków może
  zużyć więcej miejsca.
- Odkładamy: tuning modelu, GPU, dowolne modele użytkownika, hybrid search,
  docelową ewaluację hybrid i runtime wrappery.

## Alternatywy rozważone

- Pobieranie przy pierwszym query/rebuild — odrzucone jako ukryty efekt sieciowy
  i źródło nieodtwarzalnych awarii.
- Model wybierany z CLI — odrzucony, bo rozbija zgodność metadata i rozszerza
  granicę zaufania na dowolny kod/model z registry.
- Dodanie ML do `requirements.txt` — odrzucone, bo obciąża aplikację i zwykły
  workflow testowy zależnościami nieużywanymi na runtime.
