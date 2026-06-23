# ADR-0030 — Wielu agentów konkurujących: ranking botów (leaderboard) + osobne konta (odłożone)

- **Status:** Accepted
- **Data:** 2026-06-19
- **Aktualizacja:** 2026-06-20 — `faza-d-leaderboard-cleanup`: wspólne helpery przeniesione do `scripts/balance_common.py`; default `--players` zmieniony na tag `useful` z `agents/registry.py`, a `--players all` zachowuje pełny ranking.
- **Kontekst:** Strumień D4 (wątek `faza-d-leaderboard`). Strumień D dał rodzinę botów heurystycznych (D1 random/greedy/priority/priority2/priority3, D4 minimax + claude_v1/v2/v3) napędzanych headless runnerem (ADR-0032) i agregowanych przez `balance_simulate` (D2). `balance_report.py` (D2) produkuje **macierz pairwise** (per para botów × fixtura → win-rate P0/P1), ale nie ma kanonicznego, jednowymiarowego rankingu „który bot jest najsilniejszy ogólnie". Roadmap D4 wymienia deliverable „Leaderboard `reports/leaderboard.md`" oraz „wielu agentów konkurujących — osobne konta + leaderboard".

## Decyzja

Rozdzielić deliverable D4 na **dwie części** o różnej gotowości:

### Część 1 — leaderboard botów (TERAZ, ten wątek)

**`scripts/leaderboard.py`** — skrypt-liść reużywający `balance_simulate.simulate_balance` (SSOT, ADR-0032) + wspólne helpery z `scripts/balance_common.py` (`balance_report.py` używa tej samej infrastruktury). Zero zmian w rdzeniu silnika/agentów.

```python
@dataclass(frozen=True, slots=True)
class BotStanding:
    kind: str; games: int; wins: int; losses: int; draws: int
    # win_rate / loss_rate / draw_rate jako property (zero-games safe)

def player_matchups(player_kinds) -> list[tuple[str, str]]   # combinations (DISTINCT)
def run_leaderboard(config) -> list[BalanceResult]            # fixtura × para różnych botów
def compute_standings(results, player_kinds) -> list[BotStanding]  # agregacja PONAD parami
def format_leaderboard(standings, config, results) -> str    # markdown + tekstowe słupki
```

**Decyzje projektowe:**

1. **Agregacja ponad parami, nie macierz pairwise.** `compute_standings` sumuje dla każdego bota wyniki ze wszystkich par/fixtur z jego perspektywy: dla pary (A=P0, B=P1) bot A zalicza `wins_p0` wygranych / `wins_p1` porażek / `draws` remisów; B symetrycznie. Daje jeden standing per bot (ranking 1-wymiarowy) — to czego `balance_report` nie daje.
2. **Mirror self-play (A vs A) wykluczony** — `combinations` (różne pary), nie `combinations_with_replacement`. Dla botów deterministycznych mirror to gwarantowany remis (np. greedy/greedy 100% remisów, udokumentowane w D-stream), nieinformatywny dla rankingu; dodatkowo zawyżałby `draws`/`games` jednakowo, rozcieńczając win-rate.
3. **Ranking po win-rate** (`wins/games`); tiebreak deterministyczny: więcej wygranych → mniej porażek → nazwa. Determinizm per `--seed` (ADR-0010/0012/0013).
4. **Wykresy tekstowe** (unicode `█`/`░`), dependency-free — spójnie z `balance_report` (matplotlib NIE w `requirements*`). `reports/` gitignored (artefakt generowany).
5. **CLI** `--fixtures/-n/--seed/--players/--out`, default out `reports/leaderboard.md`. Default boty = tag `useful` z `agents/registry.py` (`priority`, `priority3`, `claude_v3`); `--players all` przywraca wszystkie kanoniczne boty.

### Część 2 — wielu agentów: osobne konta + leaderboard międzykontowy (ODŁOŻONE → B2 auth)

Pierwotny zamysł D4 (osobne konta `agent_kind` rywalizujące, persystowany leaderboard) wymaga modelu `User.role=agent` + `AgentToken` + persystencji wyników — wszystko zależne od **B2 auth** (odroczone, wymaga `/security-review`). Leaderboard botów (część 1) realizuje wartość rankingową BEZ tej infrastruktury (boty to typy w `PLAYER_KINDS`, nie konta). Część 2 dojdzie wraz z B2 auth + Strumień C (MCP agent).

## Konsekwencje

**Pozytywne:**
- **Domyka deliverable D4 „Leaderboard"** — kanoniczny artefakt potwierdzający udokumentowany wniosek D-stream („priority/priority3 = najlepszy stosunek siła/koszt"; żaden bot heurystyczny ich nie bije, patrz roadmap D4).
- **Zero kolizji z rdzeniem** — skrypt-liść, tylko odczyt SSOT (`simulate_balance`/`load_battle_fixture`). Bezpieczny równolegle z wątkami silnika/agentów.
- **Headless/deterministyczny** (ADR-0013) — 20 testów; testowalny bez DB/kosztów.

**Negatywne / koszty:**
- **Mirror self-play poza rankingiem** — świadome (deterministyczny remis nieinformatywny). Kto chce macierz pełną (z mirrorami) używa `balance_report.py`.
- **Część 2 (osobne konta) niezrealizowana** — czeka na B2 auth. Leaderboard botów nie persystuje wyników między uruchomieniami (regeneruje per run).
- **Koszt obliczeniowy** rośnie z liczbą botów: C(n,2) par × fixtury × n gier. Domyślny tag `useful` pomija drogie boty referencyjne; dla pełnego zestawu (`--players all`, w tym `claude_v2`/`minimax` ~100–185× priority) używaj małego `-n`.

## Alternatywy rozważone

- **Rozszerzyć `balance_report.py` o sekcję rankingową** zamiast osobnego skryptu. Odrzucone — `balance_report` to macierz pairwise (`combinations_with_replacement`, mirror w `win_rate_p0/p1`); leaderboard to inna agregacja (ponad parami, bez mirror) i inny default output (`reports/leaderboard.md` vs `reports/balance/YYYY-MM-DD.md`). Osobny skrypt = jasna odpowiedzialność, reuse `simulate_balance` (SSOT) bez sprzęgania dwóch raportów.
- **Ranking po score Elo / Glicko.** Odrzucone na ten etap — win-rate round-robin jest wystarczający i czytelny dla skończonego, małego zestawu botów; Elo ma sens przy strumieniu meczów między zmiennymi agentami (część 2, B2 auth).
- **Czekać na B2 auth i zrobić od razu pełen multi-account leaderboard.** Odrzucone — leaderboard botów dostarcza wartość rankingową teraz, bez blokady na auth; część 2 dobuduje persystencję/konta gdy auth powstanie.

## Inwarianty

1. `compute_standings` symetria: dla pary (A,B) `A.wins == B.losses` i `A.losses == B.wins` z tej pary (suma per bot ponad parami).
2. `sum(s.games for s in standings) == 2 × Σ rozegranych gier par` (każda gra liczona dla obu botów pary).
3. Mirror (A vs A) i boty spoza `player_kinds` pomijane w agregacji.
4. `run_leaderboard(config)` deterministyczny per (fixtury, boty, seed) — dziedziczone z `simulate_balance` (ADR-0010/0012).
