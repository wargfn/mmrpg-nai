from random import Random

from mmrpg_nai.dice import roll_d616


def test_roll_d616_standard_result():
    roll = roll_d616(Random(0))

    assert roll.marvel_raw == 4
    assert roll.marvel_display == "4"
    assert roll.marvel_value == 4
    assert roll.die_one == 4
    assert roll.die_two == 1
    assert roll.total == 9
    assert roll.is_fantastic is False
    assert roll.is_ultimate_fantastic is False


def test_roll_d616_marvel_and_ultimate_fantastic():
    class _FixedRandom:
        def __init__(self, values):
            self._values = iter(values)

        def randint(self, a, b):
            return next(self._values)

    roll = roll_d616(_FixedRandom([1, 6, 1]))

    assert roll.marvel_display == "Marvel"
    assert roll.marvel_value == 6
    assert roll.total == 13
    assert roll.is_fantastic is True
    assert roll.is_ultimate_fantastic is True
    assert roll.outcome_text == "ultimate fantastic"
