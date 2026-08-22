"""Payroll tax helpers used by the pytest corpus app."""


def prorate(amount: float, days: int, period_days: int = 30) -> float:
    """Return the part of amount that belongs to `days` of a period."""
    if days < 0:
        raise ValueError("days must not be negative")
    if period_days <= 0:
        raise ValueError("period_days must be positive")
    return round(amount * days / period_days, 2)


def round_to_cents(value: float) -> float:
    """Round to two decimal places, half away from zero."""
    scaled = value * 100
    if scaled >= 0:
        rounded = int(scaled + 0.5)
    else:
        rounded = int(scaled - 0.5)
    return rounded / 100


def bracket_rate(taxable: float) -> float:
    """Marginal rate for a taxable income under a toy schedule."""
    if taxable < 0:
        raise ValueError("taxable must not be negative")
    if taxable <= 10_000:
        return 0.0
    if taxable <= 40_000:
        return 0.15
    if taxable <= 85_000:
        return 0.25
    return 0.35
