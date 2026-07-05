# SZOP — Zdolności

Plik zbiorczy wszystkich zdolności opisanych w SZOP. Numeracja globalna i stała (id nie zmienia się przy edycjach). Grupy: pasywne, aktywne, aury, broni. W grupach kolejność alfabetyczna. Struktura każdego wpisu przeznaczona do prostej konwersji na YAML.

## Konwencje

- **id** — globalny numer.
- **nazwa** — cytat 1:1 z SZOP, włącznie z `(X)` jeśli parametr występuje.
- **typ** — `pasywna | aktywna | aura | broni`.
- **kategoria** — opcjonalne (np. `zasada-armii` dla pasywnych wycenianych przy założeniu, że ma je prawie każdy oddział).
- **parametr** — semantyka X (pomijany jeśli brak).
- **opis** — cytat 1:1 z SZOP.
- **efekty** — lista; każdy efekt to trójka `kiedy / warunek / co`.
  - `kiedy` — moment rozpatrzenia (np. „stale", „test obrony", „początek aktywacji", „koniec rundy").
  - `warunek` — predykat aktywujący efekt (`—` gdy brak).
  - `co` — konkretny skutek mechaniczny.
- **koszt.bazowy** — koszt statyczny per pkt wytrzymałości oddziału (lub formuła). To jedyna pozycja kosztu przechowywana w pliku. Koszty wariantów Aura / Rozkaz / Klątwa / Oznaczenie są obliczane z `bazowy` i wytrzymałości modelu nosiciela według formuł opisanych niżej. Wartości tabelaryczne (AP, Rozprysk, Zabójczy, Przebijająca, Impet, Brutalny) podawane jako podtabela.

### Wycena Aur i Rozkazów (formuła)

- Niech `T` = wytrzymałość modelu niosącego zdolność.
- **Wytrzymałość efektywna** `T_eff = clamp(4/3 × T, 8, 24)`.
- **Koszt Aury (bez zasięgu)** = `bazowy × T_eff`.
- **Koszt Aury 12″** = `bazowy × (T_eff + 8)`.
- **Koszt Rozkazu** = `bazowy × (T_eff ± 2)` — `+2` jeśli `rozkaz_kierunek = "+"` (psująca pozytywna: dajesz korzystną zdolność sojusznikowi); `−2` jeśli `rozkaz_kierunek = "−"` (psująca negatywna: zdejmujesz niekorzystną zdolność z sojusznika).
- **Koszt Klątwy** = `bazowy(X) × 6` („jak X dla 6 wytrzymałości"; tylko gdy `klatwa_tak: true`).
- **Koszt Oznaczenia** = `bazowy(X) × 6` („jak X dla 6 wytrzymałości"; tylko gdy `oznaczenie_tak: true`).

### Tagi dla zdolności pasywnych

- **aura_tak** — `true | false`. Czy zdolność może być podstawą wersji Aury (kolumna „Aura" w tabeli SZOP s.5).
- **rozkaz_tak** — `true | false`. Czy zdolność może być podstawą wersji Rozkazu (kolumna „Rozkaz").
- **rozkaz_kierunek** — `"+"` | `"−"` | `null`. Znacznik psującej cechy z tabeli: `"+"` = pozytywna (dajesz sojusznikowi korzystną zdolność), `"−"` = negatywna (zdejmujesz z sojusznika niekorzystną zdolność). Wymagane tylko gdy `rozkaz_tak: true`.
- **klatwa_tak** — `true | false`. Czy zdolność może być podstawą wersji Klątwy (kolumna „Klątwa") — domyślnie zdolności niekorzystne dla nosiciela.
- **oznaczenie_tak** — `true | false`. Czy zdolność może być podstawą wersji Oznaczenia (kolumna „Oznaczenie") — typowo zdolności wpływające na atak.
- **zakres** — `model | pozytywna | negatywna`. Reguła łączenia modeli w oddziały:
  - `model` — efekt dotyczy tylko modelu, który ma zdolność (np. Bohater, Wysoki); nie przenosi się na oddział.
  - `pozytywna` — zdolność jest korzystna; przy łączeniu modeli oddział ma ją tylko, gdy mają ją WSZYSTKIE modele.
  - `negatywna` — zdolność jest niekorzystna; przy łączeniu modeli oddział ma ją, gdy ma ją CHOĆBY JEDEN model.

### Tagi dla zdolności broni

- **mistrzostwo_tak** — `true | false`. Czy zdolność może być parametrem X w pasywnej zdolności Mistrzostwo(X).
- **czar_tak** — `true | false`. Czy zdolność może być użyta przy konstrukcji Czaru z listy mocy (pkt zdolności Mag, id 47).

---

## Pasywne

### 1. Bastion

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: false
- oznaczenie_tak: true
- zakres: pozytywna
- opis: "Nie zostajesz wyczerpany po kontrataku."
- efekty:
    - kiedy: po wykonaniu kontrataku (pkt 14.d.iv SZOP_Rozjemca)
      warunek: —
      co: oddział nie otrzymuje stanu Wyczerpany
- koszt:
    bazowy: patrz koszt broni ×1,2 (broń wręcz); bazowy 3 / pkt wytrzymałości

### 2. Bohater

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: model
- opis: "Może być dołączony do dowolnego oddziału. Jeżeli w wyniku tego część oddziału będzie miała zdolności wpływające na cały oddział, przeciwnik wybiera czy są aktywne. Może wykonywać testy przegrupowania za cały oddział, ale oddział korzysta z obrony wybranej przez przeciwnika. Nie może zostać przywrócony do gry. Jego rozmiar jest traktowany jakby miał 2 razy mniejszą wytrzymałość."
- efekty:
    - kiedy: przygotowanie gry (pkt 7.b)
      warunek: —
      co: model może zostać dołączony do dowolnego oddziału jako jego element
    - kiedy: stale, gdy bohater jest w oddziale z co najmniej dwoma różnymi profilami
      warunek: część oddziału ma zdolność wpływającą na cały oddział, której pozostała część nie ma
      co: przeciwnik wybiera, czy te zdolności są aktywne (decyzja może być rewertowana lub zmieniana, gdy zmieni się skład oddziału)
    - kiedy: test Przegrupowania oddziału (pkt 20)
      warunek: bohater jest w oddziale
      co: bohater wykonuje test za cały oddział
    - kiedy: test obrony oddziału z bohaterem
      warunek: bohater jest w oddziale i ma inny profil obrony niż reszta oddziału
      co: przeciwnik wybiera, której wartości obrony (bohatera czy oddziału) używa oddział w danym teście
    - kiedy: Odzyskiwanie ran (pkt 21.c.ii)
      warunek: model bohatera został pokonany
      co: bohatera NIE można przywrócić do gry (pozostaje pokonany)
    - kiedy: stale
      warunek: —
      co: rozmiar (zajmowane miejsce, kolizje) liczony jakby miał wytrzymałość = wytrzymałość / 2
- koszt:
    bazowy: 0

### 3. Cierpliwy

- typ: pasywna
- kategoria: zasada-armii
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: model
- opis: "Masz +1 do rzutów obrony, jeżeli nie rozpocząłeś swojej aktywacji w tej rundzie."
- efekty:
    - kiedy: test obrony (pkt 17.b)
      warunek: oddział nie rozpoczął jeszcze aktywacji w bieżącej rundzie
      co: +1 do testu obrony
- koszt:
    bazowy: 1 / pkt wytrzymałości

### 4. Delikatny

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: true
- oznaczenie_tak: false
- zakres: model
- opis: "Podczas testów obrony naturalna 6 nie oznacza automatycznego sukcesu."
- efekty:
    - kiedy: test obrony (pkt 17.b)
      warunek: wynik kostki = 6
      co: nie traktuje wyniku jako automatyczny sukces; stosuje się normalne porównanie z trudnością
- koszt:
    bazowy: patrz tabela „Modyfikator obrony" w SZOP s.5 (obniża koszt obrony); bazowy 0,5 / pkt wytrzymałości

### 5. Dobrze/źle strzela

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: model
- parametr: wariant — `dobrze` (jakość 4) lub `źle` (jakość 5) dla ataków dystansowych
- opis: "Atakuje na dystans z jakością 4/5."
- efekty:
    - kiedy: test trafienia bronią dystansową (pkt 17.a)
      warunek: —
      co: jakość użyta w teście = 4 (wariant „dobrze") lub 5 (wariant „źle"), niezależnie od jakości modelu
- koszt:
    bazowy: patrz koszt broni (modyfikator szansy trafienia)

### 6. Dywersant

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: true
- zakres: pozytywna
- opis: "Jeżeli jesteś bliżej strefy rozstawienia przeciwnika niż atakowany oddział, przed wykonaniem ataków przeciwnik wybiera, czy podwaja ich liczbę, czy zostaje Przyszpilony."
- efekty:
    - kiedy: deklaracja Ataku (pkt 14.c, 14.d) oddziału z Dywersantem, przed wykonaniem testów trafienia (pkt 17.a)
      warunek: oddział z Dywersantem jest bliżej strefy rozstawienia (pkt 24) przeciwnika niż atakowany oddział
      co: przeciwnik (właściciel celu) wybiera jedną z opcji — (a) liczba ataków atakującego × 2 w tym Ataku; (b) cel otrzymuje stan Przyszpilony (pkt 22.b)
- koszt:
    bazowy: 3,25 / pkt wytrzymałości; dodatkowo modyfikator ×1,2 na koszt każdej broni modelu

### 7. Furia

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: true
- zakres: model
- opis: "Podczas szarży naturalne 6 dają dodatkowe trafienie."
- efekty:
    - kiedy: test trafienia (pkt 17.a) podczas Szarży (pkt 14.d)
      warunek: wynik kostki = 6
      co: dodatkowe trafienie tej samej broni przeciw temu samemu celowi (poza zwykłym sukcesem)
- koszt:
    bazowy: patrz koszt broni; bazowy 3 / pkt wytrzymałości (szansa trafienia +0,65)

### 8. Harcownik

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Przed Leczeniem możesz się ruszyć o 2"."
- efekty:
    - kiedy: bezpośrednio przed Odzyskiwaniem ran / Leczeniem (pkt 11.b.v, pkt 21)
      warunek: gracz zadeklaruje użycie
      co: oddział wykonuje ruch do 2″ (modele zgodnie z regułami spójności z pkt 15.b)
- koszt:
    bazowy: 1,5 / pkt wytrzymałości

### 9. Instynkt

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: true
- oznaczenie_tak: false
- zakres: negatywna
- opis: "Rusza się zawsze w stronę najbliższego wroga i zawsze atakuje najbliższego wroga."
- efekty:
    - kiedy: każdy Ruch (pkt 15) oddziału
      warunek: —
      co: ruch musi zmniejszać dystans do najbliższego wrogiego oddziału (jeżeli to możliwe)
    - kiedy: wybór celu ataku (pkt 14.c.i, 14.d.i)
      warunek: —
      co: musi obrać najbliższy wrogi oddział, jeżeli jest legalnym celem
- koszt:
    bazowy: −1 / pkt wytrzymałości

### 10. Kontra

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Może wykonać kontratak przed atakami szarżującego oddziału, a ten przestaje być uznawany za szarżujący."
- efekty:
    - kiedy: punkt 14.d.iii (po Związaniu szarżującego, przed atakami szarżującego)
      warunek: oddział jest celem Szarży i nie jest Wyczerpany
      co: oddział wykonuje kontratak; szarżujący traci status „szarżującego" (m.in. wyłącza Furia/Impet). Nie może wykonać kontrataku w zwykłym miejscu (pkt 14.d.iv).
- koszt:
    bazowy: 1 / pkt wytrzymałości

### 11. Skok

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Ignoruje teren i jednostki podczas ruchu. Wciąż jest uznawany za przechodzący przez punkt końcowy."
- efekty:
    - kiedy: Ruch (pkt 15) i Związanie (pkt 16)
      warunek: —
      co: ignoruje przeszkody (teren dowolnego typu, modele innych oddziałów) na trasie, z wyjątkiem punktu końcowego
- koszt:
    bazowy: 1 / pkt wytrzymałości

### 12. Maskowanie

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Ma osłonę, gdy jest dalej niż 3" od wrogów."
- efekty:
    - kiedy: stale (sprawdzane przy testach ataku, pkt 17.a)
      warunek: każdy wrogi oddział jest dalej niż 3″ od tego oddziału
      co: oddział ma osłonę (pkt 19)
- koszt:
    bazowy: 2 / pkt wytrzymałości

### 13. Mistrzostwo(X)

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: true
- zakres: pozytywna
- parametr: X — nazwa zdolności broni (np. AP(2), Furia)
- opis: "Każda twoja broń ma zdolność X."
- efekty:
    - kiedy: stale
      warunek: —
      co: każda broń modeli oddziału zyskuje zdolność X (dla X parametryzowanego: z parametrem zdefiniowanym w Mistrzostwo)
- koszt:
    bazowy: "policz koszt broni jakby miały X (formuła SZOP s.5)"

### 14. Niestrudzony

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: true
- zakres: pozytywna
- opis: "Może wykonywać tę samą akcję wielokrotnie w aktywacji."
- efekty:
    - kiedy: pkt 11.b.iii (warunek pętli aktywacji)
      warunek: —
      co: znosi warunek „akcji, której oddział nie wykonywał" — ta sama akcja może być wybrana ponownie w obrębie limitu 2 akcji
- koszt:
    bazowy: patrz koszt broni ×1,5; bazowy 8 / pkt wytrzymałości

### 15. Nieruchomy

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: true
- oznaczenie_tak: false
- zakres: negatywna
- opis: "Po rozstawieniu nie może się przemieszczać i nie może zostać przyszpilony. Podczas szarży może atakować odziały w zasięgu 2"."
- efekty:
    - kiedy: stale po Aktywacji rozstawienia (pkt 13)
      warunek: —
      co: oddział nie może wykonać Manewru (pkt 14.a) ani innego ruchu
    - kiedy: nadanie stanu Przyszpilony (pkt 22.b)
      warunek: —
      co: stan Przyszpilony nie zostaje nadany
    - kiedy: atak bronią wręcz (pkt 14.d.iii) podczas Szarży
      warunek: oddział z Nieruchomym jest celem Szarży lub wykonuje kontratak
      co: zasięg ataku wręcz pozostaje 2″ (Nieruchomy może atakować mimo niezdolności do ruchu — modele w 2″ od atakującego wykonują atak)
- koszt:
    bazowy: −2,5 / pkt wytrzymałości

### 16. Nieustraszony

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Nie testuje przegrupowania, gdy oddział jest powyżej połowy początkowej wytrzymałości."
- efekty:
    - kiedy: Przegrupowanie (pkt 20)
      warunek: oddział ma powyżej połowy swojej początkowej wytrzymałości
      co: oddział nie wykonuje testu z pkt 20.a (znosi cały test Przegrupowania w tej akcji)
- koszt:
    bazowy: patrz tabela „Modyfikator morale" w SZOP s.5 (mnożnik 0,5); bazowy 1,5 / pkt wytrzymałości

### 17. Niewrażliwy

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: model
- opis: "Podczas testów obrony naturalna 5 daje automatyczny sukces."
- efekty:
    - kiedy: test obrony (pkt 17.b)
      warunek: wynik kostki = 5
      co: automatyczny sukces (niezależnie od modyfikatorów)
- koszt:
    bazowy: patrz tabela „Modyfikator obrony" w SZOP s.5; bazowy 1,5 / pkt wytrzymałości

### 18. Niezgrabny

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: true
- oznaczenie_tak: false
- zakres: negatywna
- opis: "Na trudnym i niebezpiecznym terenie wykonuje dodatkowy test trudnego terenu."
- efekty:
    - kiedy: ruch przez teren z cechą Trudny (pkt 4.c.iv) lub Niebezpieczny (pkt 4.c.v)
      warunek: —
      co: oddział wykonuje dodatkowy test reguły danego terenu
- koszt:
    bazowy: −0,5 / pkt wytrzymałości

### 19. Ochroniarz

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: model
- opis: "Bohater. Oddział może korzystać z twojej obrony. Kontrolujący nie może pokonywać innych modeli w oddziale."
- efekty:
    - kiedy: stale
      warunek: model jest w oddziale (Bohater)
      co: oddział może używać obrony Ochroniarza zamiast własnej
    - kiedy: przydział ran (pkt 18)
      warunek: w oddziale są inne modele oprócz Ochroniarza
      co: przydzielający NIE może pokonywać innych modeli, dopóki Ochroniarz nie zostanie pokonany
- koszt:
    bazowy: 0

### 20. Odrodzenie

- typ: pasywna
- kategoria: zasada-armii
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Na koniec aktywacji rzuć tyloma kośćmi, ile ran może odzyskać ten oddział. Na 4+ odzyskuje jedną ranę."
- efekty:
    - kiedy: Odzyskiwanie ran (pkt 21)
      warunek: —
      co: rzuć N k6, gdzie N = maksymalna możliwa liczba ran do odzyskania; każdy wynik ≥4 = jedna odzyskana rana
- koszt:
    bazowy: patrz tabela „Modyfikator obrony" w SZOP s.5 (mnożnik zależny od obrony)

### 21. Odwody

- typ: pasywna
- kategoria: zasada-armii
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: negatywna
- opis: "Przed rozstawieniem podziel oddziały z tą zdolnością bez zdolności Zwiadowca, Zasadzka lub Rezerwa na dwie grupy. Przeciwnik wybiera jedną z nich, a oddziały w niej zyskują zdolność Rezerwa."
- efekty:
    - kiedy: przed Rundą rozstawienia (pkt 9)
      warunek: oddział ma Odwody, ale nie ma Zwiadowca/Zasadzka/Rezerwa
      co: dziel takie oddziały na dwie grupy; przeciwnik wybiera jedną; oddziały z wybranej grupy zyskują Rezerwę
- koszt:
    bazowy: patrz koszt broni ×0,75 (jeżeli brak Rezerwa, Zwiadowca lub Zasadzka)

### 22. Okopany

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "+1 do testów obrony, gdy ma osłonę z terenu."
- efekty:
    - kiedy: test obrony (pkt 17.b)
      warunek: oddział ma osłonę pochodzącą z terenu Obronny (pkt 4.c.vi)
      co: +1 do testu obrony
- koszt:
    bazowy: 1 / pkt wytrzymałości

### 23. Ostrożny

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: true
- zakres: model
- opis: "Jeżeli nie ma wrogów w zasięgu 12" od oddziału modelu, +1 do rzutów na trafienie."
- efekty:
    - kiedy: test trafienia (pkt 17.a)
      warunek: żaden wrogi oddział nie jest w zasięgu 12″ od oddziału strzelającego
      co: +1 do testu trafienia
- koszt:
    bazowy: patrz koszt broni (modyfikator zasięgu „Ostrożny (traf)"); bazowy 4,25 / pkt wytrzymałości

### 24. Parowanie

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Ma osłonę podczas walki wręcz."
- efekty:
    - kiedy: test obrony (pkt 17.b)
      warunek: trafienie pochodzi z broni wręcz
      co: oddział ma osłonę (pkt 19)
- koszt:
    bazowy: 1,5 / pkt wytrzymałości

### 25. Planowanie

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: true
- zakres: model
- opis: "Jeżeli jest Przygotowany, +1 do rzutów na trafienie."
- efekty:
    - kiedy: test trafienia (pkt 17.a)
      warunek: oddział ma stan Przygotowany (pkt 22.c)
      co: +1 do testu trafienia
- koszt:
    bazowy: patrz koszt broni; bazowy 3,5 / pkt wytrzymałości (szansa trafienia +0,65; +0,2 jeśli także Niestrudzony)

### 26. Regeneracja

- USUNIĘTE — zdolność wycofana z SZOP. ID zarezerwowane (nie wykorzystywać ponownie).

### 27. Rezerwa

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: negatywna
- opis: "Jak zasadzka, ale tylko do twojej strefy rozstawienia."
- efekty:
    - kiedy: Runda rozstawienia (pkt 9)
      warunek: —
      co: oddział nie rozstawia się; pozostaje w lokalizacji Zaplecze (pkt 26.a)
    - kiedy: Aktywacja oddziału w lokalizacji Zaplecze (pkt 11.a, pkt 13)
      warunek: —
      co: rozstaw w obrębie własnej strefy rozstawienia (pkt 24), zgodnie z pkt 13.a (bez znoszenia tego wymogu, w odróżnieniu od Zasadzki)
    - kiedy: zajęcie celów w pierwszej rundzie
      warunek: —
      co: nie kontroluje celów w pierwszej rundzie po rozstawieniu
- koszt:
    bazowy: patrz koszt broni ×0,6

### 28. Rój

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Gdy ten oddział jest celem, ignoruj zdolność Zabójczy na broni, ale bronie z Rozprysk działają zawsze z pełną efektywnością."
- efekty:
    - kiedy: atak (pkt 17) wymierzony w ten oddział
      warunek: broń atakująca ma Zabójczy(X)
      co: Zabójczy jest ignorowany
    - kiedy: atak wymierzony w ten oddział
      warunek: broń atakująca ma Rozprysk(X)
      co: mnożnik trafień przez X stosowany bez ograniczenia liczbą modeli w oddziale
- koszt:
    bazowy: 0,25 / pkt wytrzymałości

### 29. Samolot

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytwna
- opis: "Samolot: Nie możesz aktywować oddziału bez tej zdolności, jeżeli masz nieaktywowany oddział z nią. Jako pierwszą akcję musi wykonać ruch i  przemieścić się 30″–36″ w jednej linii. Nie może kontrolować punktów, szarżować, ani być celem szarży. Nie może być celem broni z Niebezpośredni. Nie blokuje ruchu, ani widzenia innych jednostek. Ma osłonę, a jednostki strzelające do niego mają -12″ zasięgu. Wysoki, Skok, Zwinny. Jeżeli jest Przyszpilony, odrzuca ten stan i wykonuje test trudnego terenu."
- efekty:
    - kiedy: wybór oddziału do Aktywacji (pkt 11)
      warunek: w armii istnieje nieaktywowany Samolot
      co: aktywować można tylko oddział z Samolotem (gdy są nieaktywowane Samoloty)
    - kiedy: pierwsza akcja w Aktywacji
      warunek: —
      co: musi być Manewr; ruch ma długość 30″–36″ w prostej linii
    - kiedy: nadanie stanu Przyszpilony (pkt 22.b)
      warunek: —
      co: stan nie zostaje nadany, test trudnego terenu
    - kiedy: sprawdzanie kontroli celów (pkt 5.e)
      warunek: —
      co: Samolot nie kontroluje celów
    - kiedy: deklaracja Szarży (pkt 14.d)
      warunek: —
      co: Samolot nie może szarżować ani być celem Szarży
    - kiedy: deklaracja ataku bronią ze zdolnością Niebezpośredni (id 62)
      warunek: cel = Samolot
      co: atak niedozwolony — Samolot nie może być celem broni Niebezpośrednich
    - kiedy: ruch innych oddziałów oraz sprawdzanie linii wzroku
      warunek: —
      co: Samolot nie blokuje ruchu ani linii wzroku
    - kiedy: test obrony (pkt 17.b) ataku wymierzonego w Samolot
      warunek: —
      co: Samolot ma osłonę
    - kiedy: sprawdzanie zasięgu broni dystansowej na Samolot
      warunek: —
      co: zasięg broni atakującego zmniejszony o 12″
    - kiedy: stale
      warunek: —
      co: Samolot ma zdolności Wysoki (id 38), Skok (id 11), Zwinny (id 43)
- koszt:
    bazowy: 3 × wytrzymałość; zdolności Planowanie i Niestrudzony są ignorowane w wycenie

### 30. Straceńcy

- WYŁĄCZONE — zdolność wycofana z SZOP. ID zarezerwowane (nie wykorzystywać ponownie).

### 31. Strażnik

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Możesz przerwać w aktywacji przeciwnika, aby wykonać Ostrzał. Następnie twój oddział zostaje wyczerpany."
- efekty:
    - kiedy: przerwanie (pkt 12) w aktywacji wrogiego oddziału
      warunek: gracz zadeklaruje użycie
      co: oddział wykonuje akcję Ostrzał (pkt 14.c); po jej rozpatrzeniu otrzymuje stan Wyczerpany (pkt 22.a)
- koszt:
    bazowy: patrz koszt broni ×1,7 (broń dystansowa); bazowy 9 / pkt wytrzymałości

### 32. Szpica

- typ: pasywna
- kategoria: zasada-armii
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Podczas ataku przeciwko oddziałom które nie rozpoczęły swojej aktywacji w te j turze, naturalne 6 dają dodatkowe zwykłe trafienie."
- efekty:
    - kiedy: test trafienia (pkt 17.a)
      warunek: cel nie rozpoczął jeszcze Aktywacji w bieżącej rundzie ORAZ wynik kostki = 6
      co: dodatkowe normalne trafienie tej samej broni przeciw temu samemu celowi
- koszt:
    bazowy: patrz koszt broni (szansa trafienia +0,5)

### 33. Szybki / Wolny

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true (tylko dla wariantu `szybki`)
- rozkaz_kierunek: "+" (tylko dla wariantu `szybki`)
- klatwa_tak: true (tylko dla wariantu `wolny`)
- oznaczenie_tak: false
- zakres: pozytywna (wariant „szybki") | negatywna (wariant „wolny")
- parametr: wariant — `szybki` (+2″) lub `wolny` (−2″)
- opis: "Porusza się o +/- 2"."
- efekty:
    - kiedy: Ruch (pkt 15), Związanie (pkt 16)
      warunek: —
      co: maksymalny dystans ruchu modyfikowany o +2″ (Szybki) lub −2″ (Wolny)
- koszt:
    bazowy: 1 / pkt wytrzymałości (Szybki); −1 / pkt wytrzymałości (Wolny)

### 34. Tarcza

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "−"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: model
- opis: "+1 do testów obrony, gdy nie jest przyszpilony."
- efekty:
    - kiedy: test obrony (pkt 17.b)
      warunek: oddział NIE ma stanu Przyszpilony (pkt 22.b)
      co: +1 do testu obrony
- koszt:
    bazowy: 1,25 / pkt wytrzymałości

### 35. Transport(X)

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: model
- parametr: X — maksymalna sumaryczna wytrzymałość transportowanych oddziałów
- opis: "Przyjazne oddziały o łącznej wytrzymałości do X mogą zostać transportowane przez ten oddział. Jeżeli oddział składa się z kilku modeli z Transport(X), ich pojemność sumuje się. Transportowany oddział jako swoją akcję może zostać rozstawiony: wszystkie jego modele muszą zostać ustawione w odległości do 3" od dowolnych modeli transportującego oddziału. Następnie przestaje być transportowany. Oddział, którego wszystkie modele znajdują się do 3" od transportującego oddziału, może jako swoją akcję zostać zdjęty z planszy i stać się transportowany, jeżeli dostępna pojemność na to pozwala. Jeżeli część modeli transportującego oddziału zostanie pokonana, transportowane oddziały mogą tymczasowo przekraczać jego pojemność. Jeżeli ostatni model transportującego oddziału zostanie pokonany, nadmiarowe rany przechodzą na najliczniejszy transportowany oddział, a następnie wszystkie transportowane oddziały muszą zostać natychmiast rozstawione jak wyżej i stają się Wyczerpane. Jeżeli transportujący oddział wykona podwójny ruch lub początkowy ruch zdolności Samolot, wszystkie transportowane oddziały zostają Przyszpilone. Transportowane oddziały są rozstawiane razem z transporterem, w jednej aktywacji i muszą mieć te same zdolności wpływające na Rozstawienie."
- efekty:
    - kiedy: stale
      warunek: —
      co: oddział może mieć w środku oddziały o sumarycznej wytrzymałości ≤ X (sumowane między modelami z Transport(X) w tym samym oddziale)
    - kiedy: akcja transportowanego oddziału
      warunek: —
      co: rozstaw modele do 3″ od dowolnego modelu transportującego; oddział przestaje być transportowany
    - kiedy: akcja oddziału w 3″ od transportującego
      warunek: dostępna pojemność wystarczy
      co: oddział zostaje zdjęty z planszy i transportowany
    - kiedy: pokonanie modeli transportującego
      warunek: pojemność zmniejszyła się poniżej zawartości
      co: transportowane oddziały mogą tymczasowo przekraczać pojemność
    - kiedy: pokonanie ostatniego modelu transportującego
      warunek: —
      co: nadmiarowe rany przechodzą na najliczniejszy transportowany oddział; wszystkie transportowane oddziały zostają natychmiast rozstawione (do 3″ od pozycji transportującego) i otrzymują stan Wyczerpany
    - kiedy: transportujący wykona dwa Manewry w aktywacji lub początkowy ruch Samolotu
      warunek: —
      co: wszystkie transportowane oddziały otrzymują stan Przyszpilony
    - kiedy: Aktywacja rozstawienia (pkt 13) transportującego
      warunek: —
      co: transportowane oddziały rozstawiają się razem z transportującym w tej samej aktywacji; muszą mieć te same zdolności wpływające na rozstawienie (Zasadzka/Zwiadowca/Rezerwa)
- koszt:
    bazowy: X × (1 + 3 za Samolot + 0,5 za Skok + 0,25 za Szybki/Zwinny)

### 36. Waagh!

- WYŁĄCZONE — zdolność wycofana z SZOP. ID zarezerwowane (nie wykorzystywać ponownie).

### 37. Wrak

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Gdy zostaniesz pokonany, teren, który zajmujesz, do końca bitwy uznawany jest za niebezpieczny i trudny oraz zapewnia osłonę."
- efekty:
    - kiedy: pokonanie ostatniego modelu oddziału
      warunek: —
      co: obszar zajmowany przez modele w momencie pokonania staje się terenem (pkt 4) z cechami Niebezpieczny (4.c.v), Trudny (4.c.iv) i Obronny (4.c.vi) do końca gry
- koszt:
    bazowy: 0

### 38. Wysoki

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: model
- opis: "Sprawdza linię wzroku jakby był na podwyższeniu."
- efekty:
    - kiedy: sprawdzanie linii wzroku (pkt 6) dotyczące tego modelu
      warunek: —
      co: model traktowany jako stojący na elemencie terenu podniesionym
- koszt:
    bazowy: 0

### 39. Zasadzka

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Nie rozstawia się przed grą. Podczas pierwszej rundy, zamiast normalnej aktywacji rozstaw w dowolnym miejscu. Nie kontroluje celów w pierwszej rundzie."
- efekty:
    - kiedy: Runda rozstawienia (pkt 9)
      warunek: —
      co: oddział nie rozstawia się; pozostaje w lokalizacji Zaplecze (pkt 26.a)
    - kiedy: Aktywacja oddziału w lokalizacji Zaplecze (pkt 11.a, pkt 13)
      warunek: —
      co: rozstaw w dowolnym dozwolonym miejscu na planszy (znosi wymóg strefy rozstawienia z pkt 13.a)
    - kiedy: sprawdzanie kontroli celów (pkt 5.e)
      warunek: bieżąca runda = pierwsza po rozstawieniu z Zasadzki
      co: oddział nie kontroluje celów
- koszt:
    bazowy: 4 / pkt wytrzymałości + patrz koszt broni ×0,6 (broń dystansowa)

### 40. Zdobywca

- typ: pasywna
- aura_tak: true
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Możesz ignorować wrogie oddziały bez tej zdolności podczas sprawdzania celów misji."
- efekty:
    - kiedy: sprawdzanie zajęcia/kontroli celu (pkt 5.e)
      warunek: oddział z Zdobywca jest w 3″ od celu
      co: wrogie oddziały BEZ Zdobywca są ignorowane przy ustalaniu, czy „tylko oddziały tego gracza" są przy celu
- koszt:
    bazowy: 3 / pkt wytrzymałości

### 41. Zemsta

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Nie przydzielaj ran od razu, tylko przed Leczeniem w aktywacji tego oddziału. Przeciwnik przydziela rany w zwykłym momencie, ale nie może używać wcześniej przydzielonych ran."
- efekty:
    - kiedy: przydział ran (pkt 17.e, pkt 18) z trafień w oddział z Zemsta, gdy atakującym jest oddział z Zemsta
      warunek: —
      co: rany NIE są przydzielane od razu; kumulują się jako znaczniki ran do późniejszego rozliczenia
    - kiedy: tuż przed Odzyskiwaniem ran / Leczeniem (pkt 11.b.v) w aktywacji oddziału z Zemsta
      warunek: —
      co: oddział z Zemsta rozpatruje skumulowany przydział ran zgodnie z pkt 18 (atakujący przydziela)
    - kiedy: przydział ran zadanych oddziałowi z Zemsta przez przeciwnika
      warunek: —
      co: przydzielanie odbywa się w zwykłym momencie (pkt 17.e), ALE przeciwnik nie może łączyć wcześniej przydzielonych ran (kumulowanych przez Zemsta) z nowymi w celu pokonania modelu
- koszt:
    bazowy: 0 (wpływa na koszt broni: ×1,2 dla każdej broni modelu)

### 42. Zwiadowca

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Jeżeli nie rozstawiłeś przed tym oddziałem, oddziałów bez zdolności Zwiadowca lub Samolot, możesz raz ruszyć ten oddział o 6" zamiast rozstawić następny."
- efekty:
    - kiedy: aktywacja rozstawienia tego oddziału
      warunek: Runda Rozstawienia; nie ma rozstawionych oddziałów tego gracza bez zdolności Zwiadowca lub Samolot
      co: oddział nie otrzymuje stanu Aktywowany
    - kiedy: aktywacja oddziału
      warunek: Runda Rozstawienia; oddział jest Rozstawiony
      co: zamiast normalnej aktywacji wykonaj Ruch o 6″ i zakończ aktywację
- koszt:
    bazowy: 2 / pkt wytrzymałości

### 43. Zwinny

- typ: pasywna
- aura_tak: true
- rozkaz_tak: true
- rozkaz_kierunek: "+"
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: pozytywna
- opis: "Ignoruje trudny i niebezpieczny teren."
- efekty:
    - kiedy: Ruch (pkt 15) i Związanie (pkt 16) przez teren Trudny (4.c.iv) lub Niebezpieczny (4.c.v)
      warunek: —
      co: efekty tych cech terenu nie stosują się
- koszt:
    bazowy: 0,5 / pkt wytrzymałości

### 44. Zwrot

- typ: pasywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- zakres: negatywna
- opis: "Na końcu ruchu w swojej aktywacji wybiera w która stronę jest zwrócony (nie może tego zmienić poza swoją aktywacją). Jego usytuowanie wyznacza 4 nakładające się strefy, każda o kącie 180°: przód, tył, lewo, prawo. Jeżeli oddział, który go atakuje jest cały w tylnej strefie, otrzymuje -1 do obrony. Co najmniej połowa jego broni musi być przypisana do strefy i może atakować tylko cele, które w pełni się w niej znajdują. Pozostałe muszą atakować jeden oddział."
- efekty:
    - kiedy: koniec dowolnego Ruchu w aktywacji oddziału
      warunek: —
      co: gracz wybiera kierunek frontu (orientacja modelu)
    - kiedy: stale
      warunek: —
      co: model wyznacza 4 nakładające się strefy 180° (przód/tył/lewo/prawo)
    - kiedy: test obrony (pkt 17.b)
      warunek: cały atakujący oddział znajduje się w strefie „tył"
      co: −1 do obrony
    - kiedy: przypisanie broni do celów (pkt 14.c.ii)
      warunek: —
      co: co najmniej 50% broni musi być przypisana do konkretnej strefy i atakować tylko cele w pełni w niej; pozostałe muszą atakować jeden oddział
- koszt:
    bazowy: −1 / pkt wytrzymałości

---

## Aktywne

### 45. Klątwa(X)

- typ: aktywna
- parametr: X — nazwa zdolności pasywnej z `klatwa_tak: true`
- opis: "Raz na rundę możesz przerwać, aby wrogi oddział w zasięgu 12" od teraz do końca aktywacji (nie)miał zdolność X."
- efekty:
    - kiedy: przerwanie (pkt 12)
      warunek: raz na rundę; wrogi oddział w 12″
      co: do końca aktywacji wskazany wrogi oddział zyskuje lub traci zdolność X (zgodnie z deklaracją)
- koszt:
    bazowy: bazowy(X) × 6 (formuła „jak X dla 6 wytrzymałości"); wymagane X z `klatwa_tak: true`

### 46. Łatanie

- typ: aktywna
- opis: "W twojej aktywacji oddział w zasięgu 3" leczy k3 rany."
- efekty:
    - kiedy: w aktywacji oddziału z Łataniem, w fazie Odzyskiwania ran (pkt 21)
      warunek: cel jest sojuszniczym oddziałem w 3″
      co: cel odzyskuje k3 rany (zgodnie z pkt 21.c)
- koszt:
    bazowy: 20

### 47. Mag(X)

- typ: aktywna
- parametr: X — liczba żetonów mocy zarobionych na początku rundy (max 2X)
- opis: "Otrzymuje X żetonów mocy na początku każdej rundy, do maksymalnie 2X. Magowie w oddziale współdzielą żetony. Armia ma wspólną listę 6 zdolności lub ataków. W momencie gdy możesz skorzystać z jednej z nich, wydaj przypisaną liczbę żetonów i wykonaj test o przypisanej trudności. Przy sukcesie rozstrzygnij jego efekt. Jedna próba na czar na aktywacje."
- efekty:
    - kiedy: początek rundy (przed pkt 8.a)
      warunek: —
      co: oddział otrzymuje X żetonów mocy (do maksymalnego stanu 2X, kumulujące się z poprzednich rund); magowie w tym samym oddziale współdzielą pulę
    - kiedy: w aktywacji dowolnego oddziału (własnego lub przeciwnika — wielu czarów używa się jako przerwania, pkt 12)
      warunek: jedna próba na czar na każdą aktywację oddziału z Magiem (jako akcja w jego aktywacji ALBO jako przerwanie w aktywacji innego oddziału, zgodnie z opisem konkretnego czaru)
      co: wydaj liczbę żetonów przypisaną do wybranej mocy z listy armii, wykonaj test o przypisanej trudności; przy sukcesie rozstrzygnij efekt
- koszt:
    bazowy: X × clamp(T_nosiciela, 6, 18) — wartości obniżone o połowę względem poprzedniej wersji
- czar_lista_mocy:
    zakres: wspólna lista na całą armię (nie per Mag)
    rozmiar: 6 pozycji
    pozycja: jedno z:
      - zdolność z `czar_tak: true`
      - atak bronią (trafienie z powiązaną jakością)
    koszt_żetonowy_pozycji:
      - dla zdolności: ceil(koszt_punktowy × szansa_rzucenia / 10), gdzie szansa rzucenia to prawdopodobieństwo zdania testu o trudności mocy
      - dla ataku: ceil(koszt_broni_o_powiązanej_jakości / 10)

### 48. Męczennik

- typ: aktywna
- opis: "W twojej aktywacji możesz zostać eliminowany, aby twój oddział odzyskał liczę ran równą twojej wytrzymałości."
- efekty:
    - kiedy: w aktywacji oddziału z Męczennikem
      warunek: gracz zadeklaruje użycie
      co: model z Męczennikem trafia do lokalizacji Eliminowany (pkt 26.d) — NIE może wrócić do gry; oddział odzyskuje rany = wytrzymałość Męczennika
- koszt:
    bazowy: 5

### 49. Oznaczenie(X)

- typ: aktywna
- parametr: X — nazwa zdolności pasywnej z `oznaczenie_tak: true`
- opis: "Raz na rundę możesz przerwać, aby inny sojuszniczy oddział, który atakuje wybrany oddział w zasięgu 12", w trakcie rozpatrywania tego ataku miał zdolność X."
- efekty:
    - kiedy: przerwanie (pkt 12)
      warunek: raz na rundę; inny sojuszniczy oddział atakuje wskazany cel w 12″ od oddziału z Oznaczenie
      co: w trakcie rozpatrywania tego konkretnego ataku ten sojuszniczy atakujący oddział posiada zdolność X (efekt kończy się po rozpatrzeniu ataku)
- koszt:
    bazowy: bazowy(X) × 6 (formuła „jak X dla 6 wytrzymałości"); wymagane X z `oznaczenie_tak: true`

### 50. Rozkaz(X)

- typ: aktywna
- parametr: X — nazwa zdolności pasywnej z `rozkaz_tak: true`
- opis: "Raz na rundę możesz przerwać, aby sojuszniczy oddział w zasięgu 12" od teraz do końca aktywacji (nie)miał zdolność X."
- efekty:
    - kiedy: przerwanie (pkt 12)
      warunek: raz na rundę; sojuszniczy oddział w 12″
      co: do końca aktywacji wskazany sojuszniczy oddział zyskuje lub traci zdolność X (zgodnie ze znacznikiem psującym w tabeli SZOP s.5)
- koszt:
    bazowy: Aura(X) zastosowana dla T_eff + 2_lub_−2 (zgodnie z oznaczeniem +/− w tabeli SZOP s.5 dla zdolności X); T_eff = clamp(4/3 × T_nosiciela, 8, 24); wymagane X z `rozkaz_tak: true`

### 51. Demoralizacja

- typ: aktywna
- aura_tak: false
- rozkaz_tak: false
- klatwa_tak: false
- oznaczenie_tak: false
- opis: "Raz na rundę możesz przerwać, aby wrogi oddział w zasięgu 12″ wykonał test Przegrupowania."
- efekty:
    - kiedy: przerwanie (pkt 12)
      warunek: raz na rundę; wrogi oddział w 12″ od oddziału z Demoralizacją
      co: wybrany wrogi oddział wykonuje test Przegrupowania (pkt 20) — wykonuje pojedynczy test jakości; w razie nieudania kumuluje konsekwencje wg pkt 20.f (1=Przyszpilony, 2=+Wyczerpany, 3=pokonany)
- koszt:
    bazowy: 25 (koszt stały)


---

## Aury

### 52. Ociężałość

- typ: aura
- opis: "Teren w zasięgu 12" jest uznawany za trudny dla wrogich oddziałów."
- efekty:
    - kiedy: ruch wrogiego oddziału przez teren w 12″ od oddziału z aurą
      warunek: —
      co: teren w obszarze aury traktowany jest jak Trudny (pkt 4.c.iv) dla tego oddziału
- koszt:
    bazowy: 20 (koszt stały — aura inherent bez wersji pasywnej)

### 53. Radio

- typ: aura
- opis: "Gdy model w twoim oddziale używa zdolności o zasięgu 12" lub więcej, może wybrać oddział sojuszniczy odległy do 24", który też ma radio."
- efekty:
    - kiedy: użycie zdolności o zasięgu ≥12″ przez model w oddziale z Radio
      warunek: w 24″ jest sojuszniczy oddział mający Radio
      co: ten odległy sojuszniczy oddział może być wybrany jako źródło / cel efektu zdolności (rozszerza efektywny zasięg)
- koszt:
    bazowy: 3 (koszt stały — aura inherent bez wersji pasywnej)

### 78. Ratownik

- typ: aura
- opis: "W aktywacji w której twój oddział otrzymał rany, leczy jedną ranę. Jeżeli na końcu swojej aktywacji oddział ma dwóch ratowników i jest Przygotowany leczy jedną ranę. Nie kumulatywne."
- efekty:
    - kiedy: Odzyskiwanie ran (pkt 21) w aktywacji oddziału w zasięgu aury
      warunek: oddział otrzymał co najmniej jedną ranę w tej aktywacji
      co: oddział odzyskuje 1 ranę (zgodnie z pkt 21.c)
    - kiedy: koniec aktywacji oddziału (pkt 11.b.vi)
      warunek: oddział ma dwóch (lub więcej) modeli/źródeł Ratownika ORAZ oddział jest Przygotowany (pkt 22.c)
      co: oddział odzyskuje 1 ranę (nie kumulatywnie z pierwszym efektem — jeśli już wyleczono ranę w tej aktywacji, ten efekt nie ma zastosowania)
- koszt:
    bazowy: 15 (koszt stały — aura inherent bez wersji pasywnej)

### 54. Spaczenie

- typ: aura
- opis: "Teren w zasięgu 12" jest uznawany za niebezpieczny dla wrogich oddziałów."
- efekty:
    - kiedy: ruch wrogiego oddziału przez teren w 12″ od oddziału z aurą
      warunek: —
      co: teren w obszarze aury traktowany jest jak Niebezpieczny (pkt 4.c.v) dla tego oddziału
- koszt:
    bazowy: 30 (koszt stały — aura inherent bez wersji pasywnej)

---

## Broni

### 55. AP(X)

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- parametr: X — wartość modyfikatora pancerza (zwyczajowy zakres: −1 do 5)
- opis: "-X do rzutów na obronę przed trafieniami tą bronią."
- efekty:
    - kiedy: test obrony (pkt 17.b) za trafienie tą bronią
      warunek: —
      co: −X do testu obrony
- koszt:
    tabela_X:
      "-1": 0,75
      "0": 1,0
      "1": 1,4
      "2": 1,8
      "3": 2,1
      "4": 2,3
      "5": 2,4
    bazowy: patrz tabela_X (modyfikator kosztu broni)

### 56. Artyleria

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- opis: "Każdy oddział w zasięgu 12" od sojuszniczego oddziału jest w zasięgu tej broni."
- efekty:
    - kiedy: sprawdzanie zasięgu broni (pkt 14.c.ii)
      warunek: cel znajduje się w 12″ od dowolnego sojuszniczego oddziału atakującego
      co: cel jest w zasięgu tej broni niezależnie od zasięgu nominalnego
- koszt:
    bazowy: patrz tabela „Modyfikator zasięgu" w SZOP s.5 (np. 12″: +0,85; 18″: +0,55; 24″: +0,35; 30″: +0,2; 36″: +0,15)

### 57. Brutalny

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- opis: "W teście obrony nie ma automatycznych sukcesów."
- efekty:
    - kiedy: test obrony (pkt 17.b) za trafienie tą bronią
      warunek: wynik kostki = 6 (lub inny, który normalnie dałby auto-sukces, np. Niewrażliwy 5)
      co: nie traktowane jako automatyczny sukces; zwykłe porównanie z trudnością
- koszt:
    tabela_AP:
      "-1": 0,00
      "0": 0,01
      "1": 0,02
      "2": 0,10
      "3": 0,20
      "4": 0,30
      "5": 0,40
    bazowy: addytywny modyfikator kosztu broni z tabela_AP (dodawany do mnożnika AP)

### 58. Dezintegracja

- typ: broni
- mistrzostwo_tak: true
- czar_tak: false
- opis: "Naturalne 6 na trafienie ranią bez rzutu na obronę."
- efekty:
    - kiedy: test trafienia (pkt 17.a) tą bronią
      warunek: wynik kostki = 6
      co: trafienie automatycznie zadaje ranę (test obrony pominięty); rana trafia do puli zgodnie z pkt 17.d (naturalna 1 obrońcy nie zachodzi → pula obrońcy)
- koszt:
    bazowy: + (2,9 / modyfikator AP − 1) do szansy trafienia w wycenie broni

### 59. Finezja

- typ: broni
- mistrzostwo_tak: true
- czar_tak: false
- opis: "Wynik udanego rzutu na trafienie możesz traktować jak wynik rzutu na obronę."
- efekty:
    - kiedy: test obrony (pkt 17.b) za trafienie tą bronią
      warunek: gracz wybiera
      co: zamiast rzucać, użyj wartości udanego testu trafienia jako wyniku testu obrony
- koszt:
    bazowy: + (7−jakość)·(6−jakość)² / 50 do szansy trafienia w wycenie broni

### 60. Impet

- typ: broni
- mistrzostwo_tak: true
- czar_tak: false
- opis: "+1 do AP podczas szarży."
- efekty:
    - kiedy: test obrony (pkt 17.b) za trafienie tą bronią podczas Szarży (pkt 14.d)
      warunek: —
      co: AP broni zwiększone o 1 dla tego ataku
- koszt:
    tabela_AP:
      "-1": 0,15
      "0": 0,35
      "1": 0,30
      "2": 0,25
      "3": 0,15
      "4": 0,10
      "5": 0,05
    bazowy: dodatek do modyfikatora kosztu broni z tabela_AP (osobno do AP broni; usunięty składnik trafienia — Impet nie wpływa już na szansę trafienia)

### 61. Namierzanie

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- opis: "Ignoruje negatywne modyfikatory do trafienia i zasięgu."
- efekty:
    - kiedy: test trafienia (pkt 17.a) tą bronią
      warunek: —
      co: ujemne modyfikatory trafienia (np. Osłona pkt 19) nie są stosowane
    - kiedy: sprawdzanie zasięgu broni
      warunek: —
      co: ujemne modyfikatory zasięgu (np. -12″ w Samolot) nie są stosowane
- koszt:
    bazowy: koszt broni ×1,1 (ponadto wpływa na szansę trafienia, patrz wzór SZOP s.5)

### 62. Niebezpośredni

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- opis: "Nie wymaga linii wzroku."
- efekty:
    - kiedy: deklaracja ataku tą bronią (pkt 14.c)
      warunek: —
      co: wymóg linii wzroku (pkt 6) zniesiony
    - kiedy: deklaracja ataku tą bronią
      warunek: cel ma zdolność Samolot (id 29)
      co: atak niedozwolony — ograniczenie przeniesione do zdolności Samolot (poprzednie ograniczenie „cele Latających" zniesione)
- koszt:
    bazowy: koszt broni ×1,2

### 63. Niezawodny

- typ: broni
- mistrzostwo_tak: false
- czar_tak: false
- opis: "Atakuje z jakością 2+."
- efekty:
    - kiedy: test trafienia (pkt 17.a) tą bronią
      warunek: —
      co: jakość użyta w teście trafienia = 2 (niezależnie od jakości modelu)
- koszt:
    bazowy: w wycenie szansy trafienia: jakość = 2

### 64. Nieporęczny

- typ: broni
- mistrzostwo_tak: false
- czar_tak: false
- opis: "Nie może atakować oddziałów w zasięgu 12"."
- efekty:
    - kiedy: deklaracja ataku tą bronią (pkt 14.c)
      warunek: cel w zasięgu 12″
      co: atak niedozwolony
- koszt:
    bazowy: ujemne addytywy do modyfikatora zasięgu (12″: −0,6; 18″: −0,4; 24″: −0,4; 30″: −0,3; 36″: −0,15)

### 65. Podkręcenie

- typ: broni
- mistrzostwo_tak: false
- czar_tak: false
- opis: "W ostatniej rundzie wykonuje podwójną liczbę ataków."
- efekty:
    - kiedy: pkt 17.a w ostatniej rundzie gry
      warunek: bieżąca runda = 4 (zob. pkt 5.g)
      co: liczba ataków tej broni × 2
- koszt:
    bazowy: koszt broni ×1,05

### 66. Podwójny

- typ: broni
- mistrzostwo_tak: true
- czar_tak: false
- opis: "6 na trafienie dają dodatkowe normalne trafienie."
- efekty:
    - kiedy: test trafienia (pkt 17.a) tą bronią
      warunek: wynik kostki = 6
      co: dodatkowe normalne trafienie (oprócz zwykłego sukcesu)
- koszt:
    bazowy: +1 do szansy trafienia w wycenie broni

### 67. Porażenie

- typ: broni
- mistrzostwo_tak: true
- czar_tak: false
- opis: "Podczas sprawdzania kto wygrał walkę wręcz, rany zadane tą bronią liczą się podwójnie."
- efekty:
    - kiedy: ustalanie wyniku walki wręcz (pkt 20.c)
      warunek: —
      co: liczba ran zadanych tą bronią w walce wręcz mnożona przez 2 wyłącznie do porównania „kto wygrał walkę"
- koszt:
    bazowy: koszt broni ×1,1 (broń wręcz)

### 68. Precyzyjny

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- opis: "Atakujący rozdziela wszystkie rany."
- efekty:
    - kiedy: przydział ran (pkt 17.e, pkt 18)
      warunek: rany pochodzą z trafień tą bronią
      co: wszystkie rany trafiają do puli atakującego (z pominięciem reguły z pkt 17.d.ii)
- koszt:
    bazowy: koszt broni ×1,5

### 69. Przebijająca

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- opis: "Każde trafienie zadaje liczbę ran równą wynikowi kostki obrony, jeżeli nie było rzutu to 2."
- efekty:
    - kiedy: pkt 17.d (rozliczanie testu obrony za trafienie tą bronią)
      warunek: —
      co: trafienie zadaje N ran, gdzie N = wynik kostki obrony (lub 2, gdy obrona nie wymagała rzutu, np. auto-sukces z Niewrażliwy lub przy pominięciu rzutu)
- koszt:
    tabela_AP_przebijajaca:
      "-1": 1,5
      "0": 2,0
      "1": 2,5
      "2": 2,7
      "3": 2,8
      "4": 2,9
      "5": 3,0
    bazowy: koszt broni × wartość z tabela_AP_przebijajaca (zamiast standardowego mnożnika AP)

### 70. Przełamanie

- typ: broni
- mistrzostwo_tak: true
- czar_tak: false
- opis: "Jeżeli cel jest w zasięgu celu misji, wykonuje podwójną liczbę ataków."
- efekty:
    - kiedy: pkt 17.a (test trafienia tą bronią)
      warunek: cel jest w 3″ od dowolnego znacznika celu misji (pkt 5)
      co: liczba ataków tej broni × 2
- koszt:
    bazowy: koszt broni ×1,5

### 71. Przewidywalny

- typ: broni
- mistrzostwo_tak: true
- czar_tak: false
- opis: "Jeżeli cel jest Przyszpilony, wykonuje podwójną liczbę ataków."
- efekty:
    - kiedy: pkt 17.a (test trafienia tą bronią)
      warunek: cel ma stan Przyszpilony (pkt 22.b)
      co: liczba ataków tej broni × 2
- koszt:
    bazowy: koszt broni ×1,2

### 72. Rozprysk(X)

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- parametr: X — mnożnik trafień (typowe wartości 2, 3, 6)
- opis: "Przed wykonaniem testów obrony liczba trafień jest mnożona przez X, ale nie więcej, niż jest modeli w atakowanym oddziale."
- efekty:
    - kiedy: po wszystkich testach trafienia, przed testami obrony (pkt 17.b)
      warunek: —
      co: trafienia × X, ograniczone górnym limitem = liczba modeli w celu
- koszt:
    tabela_X:
      "2": 1,9
      "3": 2,7
      "6": 4,3
    bazowy: koszt broni × tabela_X[X]

### 73. Sterowany

- typ: broni
- mistrzostwo_tak: false
- czar_tak: false
- opis: "Zanim wykonasz atak tą bronią, dla każdego powiązanego znacznika ustaw go w zasięgu broni od jego obecnej pozycji albo wykonaj atak z jego pozycji i go odrzuć. Następnie wykonaj zwykły atak albo ustaw nowy znacznik w zasięgu. Możesz mieć dwa znaczniki na planszy, są wspólne dla całego oddziału. Po wystawianiu rozstaw jeden znacznik."
- efekty:
    - kiedy: po rozstawieniu oddziału (pkt 13)
      warunek: —
      co: ustaw jeden znacznik powiązany z bronią
    - kiedy: deklaracja ataku tą bronią (pkt 14.c)
      warunek: —
      co: dla każdego znacznika gracz wybiera (a) przesuń znacznik w zasięgu broni; (b) wykonaj atak z pozycji znacznika i odrzuć znacznik; następnie wykonaj zwykły atak ALBO ustaw nowy znacznik w zasięgu
    - kiedy: stale
      warunek: —
      co: na planszy mogą istnieć maks. 2 znaczniki broni, wspólne dla całego oddziału
- koszt:
    bazowy: koszt broni ×1,5

### 74. Szturmowa

- typ: broni
- mistrzostwo_tak: true
- czar_tak: false
- opis: "Można nią wykonywać również ataki wręcz."
- efekty:
    - kiedy: pkt 14.d.iii (atak wręcz podczas Szarży)
      warunek: —
      co: ta broń dystansowa może być użyta jako broń wręcz w atakach Szarży (i ewentualnym kontrataku)
- koszt:
    bazowy: koszt broni = wyceń również jak broń wręcz (sumarycznie)

### 75. Zabójczy(X)

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- parametr: X — liczba ran przydzielanych zamiast jednej (typowe wartości 2, 3, 6)
- opis: "Zamiast jednej zadaj X ran, ale nie więcej niż najniższa, jeżeli przydziela obrońca, lub najwyższa, jeżeli przydziela atakujący, wytrzymałość w oddziale."
- efekty:
    - kiedy: przydział ran (pkt 17.d) z trafień tą bronią
      warunek: —
      co: zamiast 1 rany przydziel X ran do wybranego modelu (max = najniższa, jeżeli przydziela obrońca, lub najwyższa, jeżeli przydziela atakujący, wytrzymałość w oddziale)
- koszt:
    tabela_X:
      "2": 1,8
      "3": 2,5
      "6": 3,8
    bazowy: koszt broni × tabela_X[X]

### 76. Zguba

- typ: broni
- mistrzostwo_tak: true
- czar_tak: true
- opis: "Licz rany otrzymane taką bronią. Modele pokonane przez przydzielenie pierwszych ran do tej liczby nie mogą wrócić do gry."
- efekty:
    - kiedy: zadawanie ran tą bronią
      warunek: —
      co: dla każdego trafionego oddziału prowadź licznik „rany Zguby" — sumę ran otrzymanych tą bronią
    - kiedy: przydzielanie ran (pkt 18) oddziałowi z licznikiem „ran Zguby" > 0
      warunek: model zostaje pokonany w trakcie przydzielania pierwszych N ran, gdzie N = licznik „ran Zguby"
      co: model trafia do lokalizacji Eliminowany (pkt 26.d) zamiast Wycofany — NIE może wrócić do gry
- koszt:
    bazowy: koszt broni ×1,05

### 77. Zużywalny

- typ: broni
- mistrzostwo_tak: false
- czar_tak: false
- opis: "Można użyć tylko raz na grę. Limit jeden rodzaj broni z tą zdolnością na oddział."
- efekty:
    - kiedy: deklaracja ataku tą bronią (pkt 14.c)
      warunek: broń nie była jeszcze użyta w tej grze
      co: atak dozwolony; po rozpatrzeniu broń oznaczana jako zużyta
    - kiedy: konstrukcja rozpiski
      warunek: —
      co: na jednym oddziale maks. jeden rodzaj broni z Zużywalny
- koszt:
    bazowy: koszt broni ×0,4
