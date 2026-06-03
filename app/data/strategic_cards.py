"""Definicje Kart Strategicznych (Zadania + Wsparcia).

Lista moze sie zmieniac -- przechowujemy wybory gracza po stabilnym slug,
teksty trzymamy tutaj jako single-source-of-truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class StrategicCard:
    slug: str
    text: str


STRATEGIC_TASKS: List[StrategicCard] = [
    # Natarcie
    StrategicCard(
        'natarcie-cel-wybrany',
        'Natarcie: Kontroluj cel poza strefami rozstawienia wybrany przez przeciwnika.',
    ),
    StrategicCard(
        'natarcie-oddzial-pokonany',
        'Natarcie: Wrogi oddział wybrany przez przeciwnika jest pokonany.',
    ),
    StrategicCard(
        'natarcie-przejmij-cel',
        'Natarcie: Wybierz cel kontrolowany przez przeciwnika; jeżeli takich nie ma,'
        ' to przeciwnik wybiera dowolny. Kontroluj go.',
    ),
    # Obrona
    StrategicCard(
        'obrona-brak-wrogow',
        'Obrona: Nie ma nieprzyszpilonych wrogów w twojej strefie rozstawienia. Odrzuć kartę.',
    ),
    StrategicCard(
        'obrona-twoj-oddzial',
        'Obrona: Twój oddział wybrany przez przeciwnika nie jest pokonany.',
    ),
    # Dywersja
    StrategicCard(
        'dywersja-przewaga',
        'Dywersja: W strefie rozstawienia przeciwnika jest więcej twoich oddziałów niż wroga.'
        ' Możesz położyć kartę z ręki jako dodatkowe zrealizowane zadanie.',
    ),
    StrategicCard(
        'dywersja-teren',
        'Dywersja: Kontroluj wybrany przez przeciwnika element terenu.',
    ),
    # Zwiad
    StrategicCard(
        'Zwiad-kontrola-celu',
        'Zwiad: Kontrolujesz wybrany cel poza swoją strefą rozstawienia. Staje się neutralny.',
    ),
    StrategicCard(
        'zwiad-12-od-celu',
        'Zwiad: 12” od każdego celu jest twój oddział.',
    ),
    StrategicCard(
        'zwiad-12-od-wroga',
        'Zwiad: 12” od każdego wroga jest twój oddział.',
    ),
]


STRATEGIC_SUPPORTS: List[StrategicCard] = [
    StrategicCard(
        'usun-wyczerpany',
        'Przerwij, aby wybrany oddział przestał być Wyczerpany.',
    ),
    StrategicCard(
        'ufortyfikuj',
        'Przerwij i odrzuć kartę, aby wybrany oddział został Ufortyfikowany.',
    ),
    StrategicCard(
        'odrzuc-zamiast-przegrupowania',
        'Odrzuć zamiast wykonywać Przegrupowanie.',
    ),
    StrategicCard(
        'zatrzymaj-inicjatywe',
        'Odrzuć tę i dodatkową kartę, zamiast oddać inicjatywę.',
    ),
    StrategicCard(
        'wystaw_ponownie',
        'Odrzuć kartę, aby w pełni uleczyć i przenieść wybrany przez przeciwnika'
        ' twój pokonany oddział do rezerw. Możesz najpierw pokonać swój oddział.',
    ),
    StrategicCard(
        'polowiczne-leczenie',
        'Zagraj podczas leczenia i odrzuć kartę, aby przywrócić połowę możliwych'
        ' do odzyskania ran oddziału.',
    ),
    StrategicCard(
        'szarza-inny-cel',
        'Przerwij swoją aktywację, aktywny oddział możne w niej wielokrotnie '
        'wykonywać Szarżę, jeżeli mają różne cele.',
    ),
    StrategicCard(
        'ostrzal-inny-cel',
        'Przerwij swoją aktywację. Aktywny oddział wykonuje test trudnego terenu i'
        ' może w niej wielokrotnie wykonywać Ostrzał, jeżeli mają różne cele',
    ),
    StrategicCard(
        'usun-teren',
        'Przerwij, aby usunąć z gry jeden element Niedostępnego lub blokującego terenu'
        ' nie będącego 3” od celu.',
    ),
        StrategicCard(
        'odnow-zdolnosci',
        'Odnów twoje zdolności tak, jakby zmieniła się runda.',
    ),
        StrategicCard(
        'bonus-ap',
        'Przerwij, +1AP dla aktywnego oddziału w tej aktywacji.',
    ),
]


TASKS_BY_SLUG: Dict[str, StrategicCard] = {c.slug: c for c in STRATEGIC_TASKS}
SUPPORTS_BY_SLUG: Dict[str, StrategicCard] = {c.slug: c for c in STRATEGIC_SUPPORTS}
