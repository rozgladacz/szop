# D5.3b — wyniki zamrożonego eksperymentu

```json
{
  "cases": 480,
  "statuses": {
    "complete": 480
  },
  "mixed_cases": 240,
  "complete_mixed": 240,
  "mixed_outcomes": {
    "objectives": 174,
    "draw": 36,
    "grid": 30
  },
  "non_reproducible": 0
}
```

Każdy przypadek liczony raz; powtórzenia służą weryfikacji determinizmu.

| Mapa/fixture | Polityka | Mieszane zakończone / wszystkie | Cele / grid / remis |
|---|---|---:|---:|
| demo_skirmish | priority | 24 / 24 | 18 / 6 / 0 |
| demo_skirmish | priority3 | 24 / 24 | 18 / 2 / 4 |
| lustrzana_a | priority | 24 / 24 | 20 / 2 / 2 |
| lustrzana_a | priority3 | 24 / 24 | 18 / 4 / 2 |
| objective_clash | priority | 24 / 24 | 12 / 4 / 8 |
| objective_clash | priority3 | 24 / 24 | 10 / 12 / 2 |
| standard_a | priority | 24 / 24 | 16 / 0 / 8 |
| standard_a | priority3 | 24 / 24 | 24 / 0 / 0 |
| symetryczna_a | priority | 24 / 24 | 18 / 0 / 6 |
| symetryczna_a | priority3 | 24 / 24 | 20 / 0 / 4 |

| Strategia | Pozycje | Średni dystans do najbliższego celu | Najgorszy dystans | Średnia liczba różnych najbliższych celów / strona |
|---|---:|---:|---:|---:|
| grid | 1920 | 15.655 | 25.755 | 2.200 |
| objectives | 1920 | 4.245 | 12.000 | 2.400 |

| Strategia | Średnia liczba faktycznych przydziałów / strona | Średni / max dystans do przydzielonego celu | Średnia liczba walidacji kandydatów / strona |
|---|---:|---:|---:|
| grid | 0.000 | brak przydziałów w Grid | 4.800 |
| objectives | 4.000 | 9.508 / 28.453 | 4360.000 |

| Wariant stron | Przypadki | Średni deployment ms | Średnia pełna gra ms |
|---|---:|---:|---:|
| grid / grid | 120 | 0.797 | 46.218 |
| grid / objectives | 120 | 103.838 | 151.600 |
| objectives / grid | 120 | 79.655 | 128.674 |
| objectives / objectives | 120 | 183.750 | 238.529 |
