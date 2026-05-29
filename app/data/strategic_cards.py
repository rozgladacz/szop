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
        'ulecz-i-przenies',
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
        'Przerwij w aktywacji twojego oddziału który wykonał Szarżę.'
        ' Wykonuje Szarżę na inny cel i zostaje Wyczerpany.',
    ),
    StrategicCard(
        'ostrzal-inny-cel',
        'Przerwij w aktywacji twojego oddziału który wykonał Ostrzał.'
        ' Wykonuje Ostrzał na inny cel i zostaje Wyczerpany.',
    ),
]


TASKS_BY_SLUG: Dict[str, StrategicCard] = {c.slug: c for c in STRATEGIC_TASKS}
SUPPORTS_BY_SLUG: Dict[str, StrategicCard] = {c.slug: c for c in STRATEGIC_SUPPORTS}
