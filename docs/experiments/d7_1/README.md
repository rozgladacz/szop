# D7.1 — pilot trwałej kampanii v1

Data: 2026-11-22. Baza definicji: `df60897` na `Faza_A`.
Cel: porównać pełne wykonanie z wykonaniem zatrzymanym i wznowionym,
sprawdzić no-op, archiwizację i koszt dziennika. To próba infrastruktury,
bez rankingu botów ani wniosków o ogólnym balansie gry.

- [Manifest](manifest.json), zamrożony przed pierwszym pomiarem;
- [kompaktowy wynik i dowody zgodności](results.json);
- [runner](../../../scripts/campaign_v1.py),
  [regresje](../../../tests/test_campaign_v1.py);
- [kontrakt, recovery i backup](../../trwala-kampania-v1.md).

SHA256 pliku manifestu przed pomiarem:
`793cdb325ec8f65cfd51fb957f184c8a6fb7efc49d0850bbf06fcb46f4b3ac59`.
Digest kanonicznego JSON niezależny od CRLF/LF:
`5497f0d81cc3ce6b0cb762b7d125b7558457192aa0a8ccbb900e1989a5ffbac6`.
Manifest nie był strojony po wynikach.

## Projekt próby

Jedna fixture demo_skirmish, priority, seedy 11/19, obie zamiany stron,
obie inicjatywy, cztery pary grid/objectives, dwa powtórzenia determinizmu:
**32 przypadki / 64 wykonania na kampanię**. Dwie kampanie wykonują ten
sam zestaw, nie powiększają próby statystycznej o niezależne obserwacje.
Manifest zachowuje activation cap 2000 i model v1 D5.3b.

1. `full`: start z limitem 32 nowych przypadków.
2. `split`: start z limitem 8, następnie resume w nowym procesie z limitem 24.
3. Porównanie case/result/reproducible wszystkich 32 rekordów bez czasów;
   agregaty również muszą być równe. Każdy przypadek zachowuje replay proof.
4. Kolejny resume ukończonego split: 0 nowych rekordów i identyczne bajty
   wszystkich plików danych/raportu/checksum.
5. Jawne report/verify, archive do nowego katalogu, verify i no-op resume kopii.
   Kontrola hashy journalu, nagłówka i zamrożonych fixture.

Przykładowe odtworzenie używa nowych, nieistniejących katalogów:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py start --manifest docs/experiments/d7_1/manifest.json --directory build/campaigns/repro-full --max-cases 32
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py start --manifest docs/experiments/d7_1/manifest.json --directory build/campaigns/repro-split --max-cases 8
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py resume --directory build/campaigns/repro-split --max-cases 24
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py resume --directory build/campaigns/repro-split --max-cases 32
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py verify --directory build/campaigns/repro-split
.\.venv\Scripts\python.exe -X utf8 scripts/campaign_v1.py archive --directory build/campaigns/repro-split --destination build/campaigns/repro-archive
```

## Wynik pilota

Obie kampanie ukończyły po **32 przypadki / 64 wykonania**; razem 128
wykonań tego samego zestawu, bez błędów, niedeterminizmu lub niezgodności
replay. Split zatrzymał się po 8 rekordach kodem 2, a nowy proces dopisał
pozostałe 24. Wszystkie 32 deterministyczne rekordy i agregaty są identyczne
z pełną kampanią. Resume ukończonego split i kopii archiwum dopisał 0
rekordów; bajty danych/raportu/checksum pozostały identyczne.

Jawne report/verify oraz archive/verify przeszły. Snapshot archiwum można
wznowić z nowego katalogu przy zgodnym checkoutcie. Zapisany katalog runtime:
`build/campaigns/d7_1/pilot-20261122T195451Z` (`full`, `split`, `archive`).
Pełne dzienniki pozostają w tym ignorowanym folderze; kompaktowy JSON zawiera
provenance/source digests, 32 hashe wyników, checksums archiwum, wyjścia CLI
i pomiary. Same dwa powtórzenia oraz drugi przebieg nie są niezależną próbą
balansu; wynik mieszany 10:6 nie zmienia rekomendacji domyślnego gridu.

64 zatwierdzenia wyników: średnio **28,614 ms**, mediana **36,185 ms**,
max **138,953 ms** (serializacja + append/flush/fsync). Preflight pełnego
startu: **117,211 ms**, split start **111,743 ms**, resume po 8 przypadkach
**159,404 ms**, końcowy no-op **116,596 ms**, no-op kopii **134,345 ms**.
To pomiar tej maszyny i lokalnego folderu OneDrive, bez równoległego pytest;
nie stanowi SLA ani wyniku dla dowolnego dysku/synchronizacji.

Celowane DoD: **77 passed** (w tym 34 nowe przypadki D7.1), 68,89 s.
Pełny pytest po końcowym simplify/review: **4146 passed, 4 dependency warnings**,
532,09 s. Testy objęły rzeczywistą śmierć własnego subprocessu, blokadę
drugiego writera i resume w nowym procesie, partial tail/korupcję, zmianę
manifestu/źródeł, duplikaty, no-op, odbudowę raportu oraz kopię katalogu.

## Interpretacja i backup

`persistence_ms` mierzy serializację, append, flush i fsync jednego rekordu;
`startup_ms` obejmuje preflight `run`, bez importu Pythona i inicjalizacji
katalogu. Czas całej komendy w wyniku zawiera także te koszty. Czasy nie
muszą odtworzyć się na innym komputerze i nie są SLA. Próbę wykonuje się
po pełnym pytest, bez równoległej instrumentacji testowej.

Pełne archiwa są w ignorowanym `build/campaigns/`; ścieżki konkretnego pilota
zapisuje wynik. Ten folder wymaga osobnego backupu. Git przechowuje manifest,
kompaktowy wynik, źródła i instrukcję; nie stanowi backupu wszystkich
runtime journalów. Produkcyjna baza i sekrety nie są wejściem pilota.
Znane ograniczenia reguł i efektu strony z D6.1/D5.3b pozostają aktualne.
