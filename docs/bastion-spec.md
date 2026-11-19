# Bastion — audyt B4.4d.C2d4-spec

Status: **audyt zamknięty 2026-11-19; Bastion wykluczony z katalogu
publikacji obecnego main-attacker-only Oznaczenia**. Baza: `4bf700f` na
`Faza_A`, po C2d3. To wynik dokumentacyjny, bez zmiany kodu ani tagów reguł.

## Źródła i wniosek

W tej sesji odczytano [Zdolności, poz. 1, 10, 49 i 50](../app/static/docs/SZOP_Zdolnosci.md)
oraz [Rozjemcę, pkt 11.b, 12, 14.d, 17, 20.f, 22.a i 23](../app/static/docs/SZOP_Rozjemca.md).
Bastion zapobiega otrzymaniu Wyczerpanego **po kontrataku** (poz. 1).
Podmiotem jest wykonujący kontratak, czyli obrońca Szarży; w swojej połowie
sekwencji jest on atakującym (pkt 17). Pkt 14.d.iv uzależnia zwykłe
Wyczerpanie po kontrataku od tego, czy szarżujący został pokonany.

Oznaczenie nadaje X innemu sojuszniczemu **atakującemu**, tylko na jego
konkretny atak (poz. 49). W obecnym protokole `ChargeAttackIntent` deklaruje
szarżującego; reaktywny kontratak jest wewnętrzną częścią rozliczenia tej
akcji, bez odrębnego deklarowanego headu/okna dla drugiej strony. To granica
implementacji, nie reguła zakazująca Oznaczenia kontratakującemu w pełnym
modelu gry. Nie ma podstawy do nadania efektu obrońcy przez override
przypisany szarżującemu.

**Wynik: nie publikować `bastion` w obecnym zakresie Oznaczenia.** Nie
przekierowywać po cichu odbiorcy, nie wydłużać czasu efektu, nie zmieniać
tagu `oznaczenie_tak: true` ani nie traktować wpisu w prywatnym katalogu
jako dowodu działającej mechaniki. Wykluczenie jest wystarczającym wynikiem
zaakceptowanego audytu. Nie wymaga nowej decyzji o regułach i nie blokuje
następnego audytu Planowania.

`scripts/rules_sources_check.py` zwrócił **4/4 CLEAN, exit 0**.
Bieżący tekst Bastionu z `SZOP.docx` odczytano bezpośrednio z XML archiwum:
zgodny z opisem MD i `abilities.yaml`. YAML oraz MD potwierdzają
`rozkaz_kierunek: "−"`, `oznaczenie_tak: true`. DOCX opis Oznaczenia
potwierdza innego sojuszniczego atakującego i czas jednego ataku.
PDF sprawdzono hashem, nie interpretowano niezależnie jego treści.
Hash clean potwierdza wersję, nie pełną zgodność wszystkich mechanik.
Nie zmieniono źródeł, hashy ani ekstraktów.

## Role, moment i nadanie

| Podmiot / źródło | Moment | Oczekiwane znaczenie i obecny kontrakt |
|---|---|---|
| Obrońca D z natywnym Bastionem | Po faktycznie wykonanym kontrataku | Poz. 1: nie otrzymuje Wyczerpanego z tej przyczyny; kod czyta jego `effective_passives`. |
| D bez Bastionu, szarżujący A przeżył | Ten sam moment | Pkt 14.d.iv: otrzymuje Wyczerpany. |
| D bez Bastionu, A pokonany kontratakiem | Ten sam moment | Pkt 14.d.iv: brak tego Wyczerpania już bez Bastionu; nie przypisywać wyniku nowej zdolności. |
| D już Wyczerpany albo bez deklaracji kontrataku | Przed kontratakiem | Pkt 14.d.iv/22.a: nie wykonuje kontrataku; kod nie uruchamia gałęzi po-counter. Bastion nie usuwa istniejącego statusu. |
| D z Kontrą i Bastionem | Kontratak według poz. 10; stan po nim | Kontra zmienia moment/rolę szarżującego, Bastion nadal dotyczy wykonawcy kontrataku (poz. 1/10). Obecny MVP rozlicza counter przed main również bez Kontry; to znana granica sekwencji, nie pełny dowód zgodności kolejności. |
| D z natywnym Bastionem, Rozkaz go odbiera | Do końca aktywacji, przed oceną po-counter | Poz. 50 i kierunek „−” poz. 1: source-correct Rozkaz wymaga `granted=False`. `effective_passives(D)` nie zawiera zdolności. |
| Sztuczny grant Bastionu D w `UnitBlob.ability_overrides` | Ocena po-counter | Kod view uwzględnia grant i deduplikuje go wobec native. To kontrakt wewnętrzny, nie legalna dodatnia opcja publicznego Rozkazu dla tej zdolności. |
| A, deklarowany szarżujący, otrzymał Oznaczenie(Bastion) | Podczas jego zamkniętego ataku v3 | Override dotyczy A. D nie dziedziczy go; A sam nie wykonuje kontrataku w tej sekwencji. Brak użytecznego efektu w obecnym scope. |
| D chciałby otrzymać Oznaczenie na własny kontratak | Własna połowa sekwencji z pkt 17 | Potrzebny odrębny model deklaracji/okna kontrataku. Obecny head A nie reprezentuje tego odbiorcy. Nie implementować go w tym audycie. |
| Strzelający z Bastionem | Ostrzał | Poz. 1 dotyczy kontrataku, nie modyfikatora trafień/obrażeń Ostrzału. |

Bastion nie jest ogólną odpornością na Wyczerpanie: poz. 1 ogranicza efekt
do stanu po kontrataku. Przegrupowanie może nadać ten stan niezależnie
(pkt 20.f.ii). Nie kasować wcześniejszego Wyczerpanego ani późniejszego
Wyczerpanego z innego źródła.

Przykład ról: gracz P0 ma szarżującego A=11 i nosiciela S0=12,
a P1 ma obrońcę D=21 oraz nosiciela S1=22. W headzie A→D handler może nadać
X od S0 do A, mierząc S0→D (poz. 49). Nie nadaje X do D. S1 nie może użyć
tego samego headu jako deklaracji ataku D→A. W przyszłym odrębnym kontrataku
D→A podmiotem byłby D, a zasięg nosiciela mierzony S1→A; to przykład
wymagań przyszłego kontraktu, nie istniejąca funkcja API.

## Sprawdzona mapa kodu i call sites

| Symbol / plik w `app/services/engine/` | Odczytany kontrakt |
|---|---|
| `phases._apply_charge` | Jedyny produkcyjny caller `combat.resolve_charge_attack`; przekazuje decyzję `counter_attack_declared` i aktualizuje oba bloby. |
| `combat.resolve_charge_attack` | Wykonuje counter, potem ocenia `counter_result.new_attacker` jako `post_counter_defender`. Jeśli A żyje i D nie ma efektywnego Bastionu, emituje `StatusAdded(Wyczerpany)` dla D. Main nie dostaje z tego zdolności D. |
| `combat.resolve_melee_attack` | D jest atakującym w wywołaniu counter, A w main. Wspólny modifier hook nie zastępuje decyzji o statusie po counter. |
| `combat._matching_closed_charge` | Zwraca head deklarowanego A; C2d1/C2d2 używają go dla Furii/aliasów. Samo użycie go w warunku Bastionu nie naprawiłoby roli odbiorcy. |
| `state.effective_passives` | Native plus aktywacyjne grant/suppress, w kolejności, bez podwójnego sluga. To view obecnego warunku Bastionu. |
| `state.effective_attack_passives` | Dodaje attack override tylko gdy `blob.id == attack.intent.attacker_unit_id`. D w headzie A dostaje wyłącznie swoje bazowe/aktywacyjne view. |
| `interrupts._validated_rozkaz_payload`, `_rozkaz_capable_directions`, `_apply_rozkaz` | Kierunek pochodzi z YAML; Bastion „−” oznacza suppress. `AbilityOverrideApplied` trafia do D, jeżeli D jest legalnym celem Rozkazu. |
| `interrupts._validated_oznaczenie_attack_payload`, `execute_oznaczenie_attack_interrupt_outcomes` | Prywatny katalog tagów zawiera Bastion; handler waliduje source/ally/target/range/limit i emituje `AttackAbilityOverrideApplied` dla deklarowanego A. Nie dowodzi użytecznego efektu Bastionu. |
| `activation_protocol._canonical_action_from_attack`, `_resolve_activation_attack` | Head Charge odtwarza jedną akcję z decyzją o counter; resolve klonuje RNG, rozlicza całą akcję i dopiero potem dopisuje terminalny `AttackResolved`. Brak osobnego okna drugiej połowy. |
| `reducers._reduce_attack_ability_override_applied`, `_reduce_attack_resolved` | Pierwszy wiąże override z headem/attackerem; drugi usuwa cały `activation.attack`. Nie zapisują attack grantu w `UnitBlob.ability_overrides`. |
| `reducers._reduce_ability_override_applied`, `phases._finalize_activation` | Osobny aktywacyjny grant/suppress i jego wygaśnięcie na końcu aktywacji; nie zamieniać go z krótszym scope Oznaczenia (poz. 49/50, pkt 11.b.vi). |
| `effects.aggregate_attack_modifier`, `prediction.expected_damage` | Brak hooka Bastionu. Prediction estymuje rany, nie stan po counter, więc dodanie bonusu obrażeń byłoby błędnym odwzorowaniem poz. 1. |
| `app/services/battle_activations.py::_READY_ATTACK_X` | Nadal pusty. Audyt nie zmienia publicznej odmowy Oznaczenia ani routingu. |

Nie reużywać historycznego `_oznaczenie_handler`: jego aktywacyjny,
order-like model jest wyraźnie innym uproszczeniem niż prywatny v3 handler.
Źródłem zgodności reguł są poz. 1/49/50 i pkt 17, nie historyczne komentarze
ani ADR. [ADR-0056](adr/0056-interrupt-activation-protocol.md) opisuje istniejący
kontrakt trwałości, ale nie zmienia źródłowych ról.

## Dowody istniejące i wymagania przyszłej weryfikacji

Odczytano `tests/test_engine_combat.py`: testy
`test_charge_bastion_prevents_exhaustion_after_counter`,
`test_charge_defender_becomes_exhausted_after_counter`,
`test_charge_counter_kills_charger_defender_not_exhausted`,
`test_charge_counter_does_not_kill_charger_defender_becomes_exhausted`,
`test_charge_no_counter_when_defender_exhausted` i
`test_charge_no_counter_when_declared_false`. Pokrywają native/bez zdolności,
przeżycie A i brak counter. Ich obecność nie dowodzi source-correct
Oznaczenia(Bastion), publicznego v3 ani kompletnej kolejności Kontry.
Nie uruchamiano ich ponownie w tym dokumentacyjnym audycie.

| Przyszła regresja | Wymagany dowód |
|---|---|
| Native D / brak / aktywacyjny suppress | Różnica dotyczy tylko właściwego statusu D; bez zmiany rzutów i ran. |
| Native plus wewnętrzny grant / suppress po grant / grant po suppress | View deduplikuje, ostatni aktywacyjny override wygrywa; legalność publicznego payloadu jest osobną walidacją. |
| Grant wyłącznie A w headzie A→D | Nie chroni D ani nie zmienia jego RNG/eventów po counter. |
| A pokonany / przeżył, D pokonany main, counter odmówiony, D wcześniej Wyczerpany | Stan i eventy respektują istniejące gałęzie; brak kontrataku nie jest dowodem działania Bastionu. |
| Kontra wykonana / niewykonana | Role D/A i wpływ wyłącznie na właściwe źródło Wyczerpanego. |
| Przegrupowanie po akcji | Native Bastion nie daje immunitetu na status z pkt 20.f. |
| Restart / pełny tail / retry / future RNG | Stan/eventy replay równe live, failed outcome nie mutuje wejść, attack override nie przechodzi na kolejny atak. |
| Publiczny katalog | Bastion niewymieniony jako gotowy; odmowa bez zapisu/ujawniania cudzej bitwy. |

Przygotowanie publikacji `C2-publication-spec` ma oznaczyć Bastion jako
**wykluczony z obecnego zakresu**, oddzielnie od mechanik już wdrożonych.
Nie potrzeba teraz kolejnego etapu implementacji Bastionu. Ewentualny przyszły
projekt kontrataku musi jawnie określić własny intent/window, uprawnionego
odbiorcę i moment wygaśnięcia po zastosowaniu stanu po-counter; następnie
zaprojektować codec/eventy/restart/auth/CAS/no-oracle oraz regresje legacy.
Tego rozszerzenia nie zatwierdza obecny audyt. Nie dodano dla niego markera.

Koszt bieżącej decyzji o statusie to lookup w efektywnych pasywkach D,
bez skanu bitwy, SQL i RNG. Nie proponować nowego modifiera obrażeń/cache.
W tym etapie brak zmian wykonywalnych i brak benchmarku nowej implementacji.
Gdy powstanie osobny przyszły zakres, dotyczyłby przede wszystkim
`combat.py`, `state.py`, `activation_protocol.py`, `interrupts.py`,
`reducers.py` i testów protokołu/persistence/transport; nie wystarczy jedna
zamiana `effective_passives` na `effective_attack_passives`.

## Weryfikacja i kontynuacja na innym komputerze

Przeprowadzono audyt źródeł/call sites, sprawdzono AST 20 symboli w 8
plikach silnika oraz 7 nowych lokalnych celów linków,
`git diff --check` oraz simplify/review dokumentu (role, kierunek Rozkazu,
oddzielne lifetimes, rozróżnienie kodu i reguł, brak pozornej publikacji).
Zmiany wyłącznie Markdown; zgodnie z DoD kolejki nie ponawiano pytest.
Historyczna pełna baza po C2d3: **3987 passed, 4 warnings**, nie jest wynikiem
tego audytu. Security review/UI smoke nie dotyczą zakresu dokumentacji.

Wynik, plan i indeks są śledzone w Git, osobny commit na `Faza_A` wymaga
potwierdzenia na `origin/Faza_A`. Baza niezmieniona SHA256
`AB6D92E654BB6A3D050A4FAC88A7533DA89539E4CB351E38E526EF086C5BE8E6`.
Osobno zachować backup `data/szop.db` oraz lokalnych sekretów/konfiguracji;
środowisko odtworzyć z requirements. Źródła SZOP są śledzone w Git.
Cudze lokalne pliki i historyczny hunk B6.2 nie należą do tego audytu.
Następny zaakceptowany etap: **C2d5-spec — audyt Planowania**, nieuruchomiony.
Brak nowego pytania wymagającego rozstrzygnięcia użytkownika.
