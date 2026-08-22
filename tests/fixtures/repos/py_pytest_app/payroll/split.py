"""Even splitting helpers."""


def split_evenly(total: float, people: int) -> list:
    """Split total evenly; zero or negative people yields an empty list."""
    if people <= 0:
        return []
    share = round_to_cents(total / people)
    return [share for _ in range(people)]


def round_to_cents(value: float) -> float:
    scaled = value * 100
    if scaled >= 0:
        rounded = int(scaled + 0.5)
    else:
        rounded = int(scaled - 0.5)
    return rounded / 100
