"""Dice rolling: parses expressions like '1d20+3', '2d6-1', '4d6kh3', '1d8+1d6+2'."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

_rng = random.SystemRandom()

TERM = re.compile(r"([+-]?)\s*(?:(\d*)d(\d+)(?:(kh|kl)(\d+))?|(\d+))", re.I)


@dataclass
class RollResult:
    expression: str
    total: int
    parts: list[str] = field(default_factory=list)
    dice: list[int] = field(default_factory=list)   # every kept die, in order

    def detail(self) -> str:
        return " ".join(self.parts).lstrip("+ ").strip()


def d(sides: int) -> int:
    return _rng.randint(1, sides)


def roll(expression: str) -> RollResult:
    expr = expression.replace(" ", "").lower()
    if not expr:
        raise ValueError("empty dice expression")
    pos = 0
    total = 0
    parts: list[str] = []
    kept_all: list[int] = []
    while pos < len(expr):
        m = TERM.match(expr, pos)
        if not m or m.end() == pos:
            raise ValueError(f"can't read dice expression '{expression}'")
        pos = m.end()
        sign = -1 if m.group(1) == "-" else 1
        sym = "-" if sign < 0 else "+"
        if m.group(3):
            count = int(m.group(2) or 1)
            sides = int(m.group(3))
            if count > 100 or sides > 1000 or sides < 1:
                raise ValueError("that's too many dice")
            rolls = [d(sides) for _ in range(count)]
            kept = rolls
            if m.group(4):
                n = int(m.group(5))
                ordered = sorted(rolls, reverse=(m.group(4) == "kh"))
                kept = ordered[:n]
            sub = sum(kept)
            total += sign * sub
            kept_all.extend(kept)
            shown = ", ".join(str(r) for r in rolls)
            label = f"{count}d{sides}{(m.group(4) or '') + (m.group(5) or '')}"
            parts.append(f"{sym} {label}[{shown}]")
        else:
            val = int(m.group(6))
            total += sign * val
            parts.append(f"{sym} {val}")
    return RollResult(expression, total, parts, kept_all)


def roll_drop_lowest(count: int, keep: int, sides: int = 6) -> tuple[int, list[int]]:
    rolls = [d(sides) for _ in range(count)]
    return sum(sorted(rolls, reverse=True)[:keep]), rolls


def fmt_mod(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)
