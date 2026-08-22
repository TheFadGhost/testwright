"""Three-dee helpers for the unittest corpus app."""


def cube_volume(side: float) -> float:
    if side < 0:
        raise ValueError("side must not be negative")
    return round(side ** 3, 4)


def diagonal(dx: float, dy: float, dz: float) -> float:
    return round((dx * dx + dy * dy + dz * dz) ** 0.5, 4)
