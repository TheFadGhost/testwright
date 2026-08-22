"""Geometry helpers for the unittest corpus app."""

import math


def area_circle(radius: float) -> float:
    if radius < 0:
        raise ValueError("radius must not be negative")
    return round(math.pi * radius * radius, 4)


def clamp(value: float, low: float, high: float) -> float:
    """Constrain value to the closed interval [low, high]."""
    if low > high:
        raise ValueError("low must not exceed high")
    if value < low:
        return low
    if value > high:
        return high
    return value


def hypot2(dx: float, dy: float) -> float:
    return dx * dx + dy * dy
