"""Tests for payroll.split."""

import pytest

from payroll.split import split_evenly


def test_split_evenly_divides_total():
    assert split_evenly(30, 3) == [10.0, 10.0, 10.0]


@pytest.mark.parametrize("people", [0, -2])
def test_split_evenly_empty_for_bad_people(people):
    assert split_evenly(30, people) == []
