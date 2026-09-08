"""Dice helpers for Marvel Multiverse RPG rolls."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class D616Roll:
    marvel_raw: int
    marvel_display: str
    marvel_value: int
    die_one: int
    die_two: int
    total: int
    is_fantastic: bool
    is_ultimate_fantastic: bool

    @property
    def dice_text(self) -> str:
        return f"{self.marvel_display}, {self.die_one}, {self.die_two}"

    @property
    def outcome_text(self) -> str:
        if self.is_ultimate_fantastic:
            return "ultimate fantastic"
        if self.is_fantastic:
            return "fantastic"
        return "standard"

    @property
    def summary_text(self) -> str:
        return (
            f"D616 roll: Marvel die {self.marvel_display} (counts as {self.marvel_value}), "
            f"other dice {self.die_one} and {self.die_two}, total {self.total} "
            f"({self.outcome_text} result)."
        )


def build_d616_prompt(roll: D616Roll) -> str:
    return (
        "The player asked for a Marvel Multiverse RPG D616 roll. "
        "Use this exact result and do not reroll or alter any numbers.\n\n"
        f"{roll.summary_text}\n"
        f"Dice shown: {roll.dice_text}.\n"
        f"Outcome type: {roll.outcome_text}.\n\n"
        "Respond as the Narrator in 1-3 concise sentences. "
        "State the dice and total clearly. "
        "If the result is fantastic or ultimate fantastic, say so explicitly and briefly describe the impact."
    )


def roll_d616(rng: random.Random | None = None) -> D616Roll:
    roller = rng if rng is not None else random
    marvel_raw = roller.randint(1, 6)
    die_one = roller.randint(1, 6)
    die_two = roller.randint(1, 6)
    is_marvel = marvel_raw == 1
    marvel_display = "Marvel" if is_marvel else str(marvel_raw)
    marvel_value = 6 if is_marvel else marvel_raw
    total = marvel_value + die_one + die_two
    is_ultimate_fantastic = is_marvel and sorted((die_one, die_two)) == [1, 6]
    return D616Roll(
        marvel_raw=marvel_raw,
        marvel_display=marvel_display,
        marvel_value=marvel_value,
        die_one=die_one,
        die_two=die_two,
        total=total,
        is_fantastic=is_marvel,
        is_ultimate_fantastic=is_ultimate_fantastic,
    )
