"""Dice roller — the deterministic heart of the game.

The AI Warden never rolls dice; it only *asks* for rolls. All randomness lives
here so outcomes are reproducible (seedable) and testable. Supports standard
`NdM+K` notation plus the Cairn idioms we need (d20 saves, 3d6 abilities,
weapon dice like `d8`).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

_DICE_RE = re.compile(r"^\s*(\d*)\s*d\s*(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


@dataclass
class Roll:
    """The full, auditable result of a single dice expression."""
    expr: str
    rolls: list[int]
    modifier: int
    total: int

    def __str__(self) -> str:
        parts = "+".join(str(r) for r in self.rolls)
        if self.modifier:
            parts += f"{self.modifier:+d}"
        return f"{self.expr} → [{parts}] = {self.total}"


class Dice:
    """Seedable dice roller. Pass a seed for reproducible sessions/tests."""

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def roll(self, expr: str) -> Roll:
        """Roll an `NdM+K` expression. `d20`, `3d6`, `1d8+2`, `2d6-1` all work."""
        m = _DICE_RE.match(str(expr))
        if not m:
            raise ValueError(f"Unrecognized dice expression: {expr!r}")
        count = int(m.group(1)) if m.group(1) else 1
        sides = int(m.group(2))
        modifier = int(m.group(3).replace(" ", "")) if m.group(3) else 0
        if count < 1 or count > 100 or sides < 1 or sides > 1000:
            raise ValueError(f"Dice out of sane range: {expr!r}")
        rolls = [self._rng.randint(1, sides) for _ in range(count)]
        return Roll(expr=str(expr), rolls=rolls, modifier=modifier, total=sum(rolls) + modifier)

    def d(self, sides: int) -> Roll:
        return self.roll(f"1d{sides}")

    def d20(self) -> Roll:
        return self.roll("1d20")

    def highest_of(self, exprs: list[str]) -> Roll:
        """Roll several expressions, keep the single highest total (Cairn's
        rule for multiple attackers / dual-wielding)."""
        results = [self.roll(e) for e in exprs]
        best = max(results, key=lambda r: r.total)
        # Represent the kept roll but remember we considered several.
        best.expr = f"highest of {', '.join(exprs)}"
        return best
