from collections.abc import Iterable

MAX_UNIT_MODELS = 100
MAX_UNIT_EQUIPMENT = 1000
MAX_UNIT_OPTIONS = 100


class UnitBudgetExceeded(ValueError):
    """An editable unit would exceed a bound on work or allocations."""


def require_model_count(count: int) -> None:
    if count > MAX_UNIT_MODELS:
        raise UnitBudgetExceeded(f"Oddział może mieć najwyżej {MAX_UNIT_MODELS} modeli.")


def require_equipment_count(count: int) -> None:
    if count > MAX_UNIT_EQUIPMENT:
        raise UnitBudgetExceeded(f"Oddział może mieć najwyżej {MAX_UNIT_EQUIPMENT} sztuk wyposażenia i zdolności.")


def require_option_count(count: int) -> None:
    if count > MAX_UNIT_OPTIONS:
        raise UnitBudgetExceeded(f"Oddział może mieć najwyżej {MAX_UNIT_OPTIONS} opcji wyposażenia i zdolności.")


def loadout_instance_count(
    weapons: Iterable[int], active: Iterable[int], aura: Iterable[int], *, multiplier: int,
) -> int:
    return (sum(weapons) + sum(active) + sum(aura)) * multiplier
