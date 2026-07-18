# ADR-0026 — Weighted RRF dla offline hybrid retrieval

- **Status:** Accepted
- **Data:** 2026-07-18
- **Kontekst:** Strumień C2.4 po baseline BM25 C2.2 i trwałym dense store C2.3.

## Problem

Wyniki BM25 i dense mają nieporównywalne skale score, więc fuzja oparta na ich
wartościach wymagałaby kruchej kalibracji. Hybryda musi zachować stabilne
`chunk_id`, metadane korpusu C2.1, limity wejścia C2.2/C2.3 i działać bez nowego
runtime toola MCP/HTTP. Parametry trzeba wybrać na niezmienionych 30 pytaniach,
bez dostrajania gold setu, chunkingu lub modelu.

## Decyzja

`hybrid_search(query, limit)` wywołuje istniejące `search()` i
`vector_store.dense_search()` z pulą top-5 każdej gałęzi. Kandydaci są
deduplikowani po `chunk_id`, a wynik jest sumą weighted Reciprocal Rank Fusion:

`2 / (60 + rank_bm25) + 1 / (60 + rank_dense)`

Brak kandydata w gałęzi oznacza wkład zero. Remisy rozstrzyga kolejność korpusu
C2.1, a następnie `chunk_id`. Metadane i ograniczony tekst wyniku są odtwarzane
z `indexer.build_corpus()` po `chunk_id`; wyniki gałęzi nie są alternatywnym
źródłem metadanych. Kontrakt zawiera końcowy rank/score oraz per-gałąź rank,
wagę i wkład RRF. Wszystkie liczby muszą być skończone i serializowalne z
`allow_nan=False`.

Przed wyborem zadeklarowano ograniczoną siatkę: głębokość `{5, 10}`, `k`
`{20, 60}` i waga BM25 `{1, 2}` przy wadze dense `1`. Ten sam lokalny MiniLM,
zgodny indeks, korpus i 30 rekordów dały:

| Pula | k | BM25:dense | Hybrid hits/30 |
|---:|---:|---:|---:|
| 5 | 20 | 1:1 | 21 |
| 5 | 20 | 2:1 | 24 |
| 5 | 60 | 1:1 | 21 |
| 5 | 60 | 2:1 | 24 |
| 10 | 20 | 1:1 | 21 |
| 10 | 20 | 2:1 | 22 |
| 10 | 60 | 1:1 | 21 |
| 10 | 60 | 2:1 | 22 |

Wybrano najpłytszą pulę i wagę 2:1, które nie są gorsze od BM25; `k=60` jest
standardowym, prostym parametrem RRF i w tej siatce nie zmienia wyniku względem
20. Finalny publiczny benchmark: BM25 **24/30 (0,800; 0,041 s)**, dense
**8/30 (0,267; 79,741 s)**, hybrid **24/30 (0,800; 69,476 s)**. Hybryda nie
naprawiła i nie pogorszyła żadnego przypadku względem BM25. Gate hybrid to
recall@5 >= 0,800; trzy fazy retrieval trwały łącznie 149,258 s (152,5 s
wall-clock całego procesu z walidacją i startem interpretera).

## Konsekwencje

- Pozytywne: fuzja jest odporna na kalibrację score, deterministyczna, ma małą
  stałą pulę i zachowuje BM25 jako silniejszy sygnał na kanonicznym zbiorze.
- Pozytywne: jeden matcher `source+ref+anchor` raportuje BM25, dense i hybrid
  per case oraz agregaty; dotychczasowe `--retrieval` nadal uruchamia tylko BM25.
- Koszt: obecny dense MiniLM osiąga tylko 8/30, więc hybrid spełnia gate, ale nie
  poprawia baseline; waga 2:1 jest świadomą ochroną jakości leksykalnej.
- Koszt: finalny przebieg 30+30 dense query jest wolny na CPU, ponieważ publiczna
  ścieżka tworzy leniwy adapter dla każdego zapytania; optymalizacja cache modelu
  wymaga osobnego etapu i benchmarku.
- Odkładamy: zmianę modelu/chunkingu, rozszerzenie siatki, runtime wrappery
  MCP/API, HTTP i discovery tools.

## Alternatywy rozważone

- Suma znormalizowanych raw score — odrzucona jako zależna od kalibracji dwóch
  różnych metod.
- Equal-weight RRF — odrzucony, bo uczciwy wynik 21/30 nie przechodzi gate.
- Pula top-10 — odrzucona, bo z wagą 2:1 daje 22/30, gorzej niż top-5.
- Zmiana gold setu, korpusu, chunkingu albo modelu — odrzucona jako zafałszowanie
  porównania C2.1–C2.4.
