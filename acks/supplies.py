"""Rations, ammunition, and animal feed: supplies that get used up a day, a shot, or a feeding at a time.

Rations are counted in days: a week of iron or standard rations (1 stone in the RR's adventuring equipment
table) is 7 days at 1/7 stone. Arrows and bolts weigh 1/6 stone per quiver or case of 20, sling stones and
bullets 1/6 stone per 30 (RR weapons table and sling description), and each is counted singly. Feed is kept
as stone and eaten by an animal's daily food need.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

RATION_DAY = Fraction(1, 7)
RATIONS = {"iron": "Iron rations", "standard": "Standard rations"}
AMMO = {"arrows": ("Arrows", Fraction(1, 120)), "bolts": ("Bolts", Fraction(1, 120)),
        "sling_stones": ("Sling stones", Fraction(1, 180))}
AMMO_SINGULAR = {"arrows": "arrow", "bolts": "bolt", "sling_stones": "sling stone"}
WEAPON_AMMO = {"short_bow": "arrows", "long_bow": "arrows", "composite_bow": "arrows", "crossbow": "bolts",
               "arbalest": "bolts", "sling": "sling_stones", "staff_sling": "sling_stones"}

_ARROWS = re.compile(r"(?<![a-z])arrows?(?![a-z])")
_BOLTS = re.compile(r"(?<![a-z])bolts?(?![a-z])")
_STONES = re.compile(r"(?<![a-z])(sling[ -]?stones?|sling[ -]?bullets?|bullets?|stones?)(?![a-z])")
_FEED = re.compile(r"(?<![a-z])(feed|fodder|hay|oats|grain)(?![a-z])")
_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


@dataclass
class Supply:
    kind: str        # "rations" | "ammo" | "feed"
    base: str | None  # rations: iron/standard; ammo: arrows/bolts/sling_stones
    name: str        # the stack it belongs in, e.g. "Iron rations", "Arrows", "Silver arrows"
    count: int       # how many units (days, shots) one of these names stands for
    each: Fraction   # stone per unit (feed: 0, its weight is whatever was given)


def _number(text: str) -> int | None:
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    for w, n in _WORDS.items():
        if re.search(rf"(?<![a-z]){w}(?![a-z])", text):
            return n
    return None


def recognize(name: str) -> Supply | None:
    """'1 week's iron rations' -> 7 days of Iron rations; 'Quiver with 20 arrows' -> 20 Arrows; 'Hay' -> feed.

    Rations without 'day' in the name are counted in weeks (the book sells them by the week), so a bare
    'Iron rations' is 7 days. Spell names ('prayer book with sling stone'), ballista bolts, and words like
    'thunderbolts' aren't supplies.
    """
    low = name.lower().replace("’", "'")
    if re.search(r"(spell|prayer|holy) ?book|grimoire|memory palace|ballista|thunderbolt", low):
        return None
    if re.search(r"(?<![a-z])rations?(?![a-z])", low):
        base = "standard" if re.search(r"standard|fresh", low) else "iron"
        day = re.search(r"(\d+|\w+)?\s*days?'?s?(?![a-z])", low)
        week = re.search(r"(\d+|\w+)?\s*weeks?'?s?(?![a-z])", low)
        if day and not week:
            count = _number(day.group(0)) or 1
        else:
            count = 7 * ((_number(week.group(0)) if week else None) or 1)
        return Supply("rations", base, RATIONS[base], count, RATION_DAY)
    for base, pattern in (("arrows", _ARROWS), ("bolts", _BOLTS), ("sling_stones", _STONES)):
        m = pattern.search(low)
        if not m:
            continue
        if base == "sling_stones" and m.group(1).startswith("stone") and "sling" not in low:
            return None   # plain "stones" are just rocks
        label, each = AMMO[base]
        silver = "silver" in low
        count = 1
        for n in re.findall(r"(?<![+\d])(\d+)", low):   # '2 cases with 20 bolts' = 40; '+1' is magic, not a count
            count *= int(n)
        if count == 1:
            count = _number(low) or 1
        return Supply("ammo", base, f"Silver {label.lower()}" if silver else label, count, each)
    if _FEED.search(low):
        return Supply("feed", None, name.strip()[:1].upper() + name.strip()[1:], 1, Fraction(0))
    return None


def split_weapon_and_ammo(text: str, find_weapon) -> tuple[str, str] | None:
    """'Sling with 30 sling bullets' -> ('Sling', '30 sling bullets'); a quiver or case isn't a weapon."""
    m = re.match(r"(.+?)\s+with\s+(.+)$", text.strip(), re.I)
    if not m:
        return None
    left, right = m.group(1), m.group(2)
    s = recognize(right)
    if s and s.kind == "ammo" and find_weapon(left):
        return left, right
    return None


def is_supply(it: dict) -> bool:
    return it.get("kind") in ("rations", "ammo", "feed")


def describe_qty(it: dict) -> str:
    """'7 days of ' for rations, '20× ' for other stacks, '' for one of something."""
    n = int(it["qty"])
    if it.get("kind") == "rations":
        return f"{n} day{'s' if n != 1 else ''} of "
    return f"{n}× " if n != 1 else ""


# ---------------------------------------------------------------------------
# Using supplies up
# ---------------------------------------------------------------------------

def ammo_for(item: dict | None) -> str | None:
    """The ammunition a missile weapon item shoots (None for thrown weapons and homebrew launchers)."""
    if not item:
        return None
    return WEAPON_AMMO.get(item.get("base") or "")


def is_special_ammo(it: dict) -> bool:
    """Silver or magic arrows are only shot when picked, never by default."""
    return "silver" in it["name"].lower() or bool(int(it.get("magic", 0)))


def ammo_stack(holder, base: str, prefer: str | None = None) -> dict | None:
    """The stack a shot comes from: the one named in `prefer` (an item id or name), else the largest ordinary one."""
    stacks = [it for it in holder.items() if it.get("kind") == "ammo" and it.get("base") == base]
    if prefer:
        p = prefer.strip().lstrip("#").lower()
        chosen = [it for it in stacks if str(it["id"]) == p or it["name"].lower() == p]
        return chosen[0] if chosen else None
    return max((it for it in stacks if not is_special_ammo(it)), key=lambda it: int(it["qty"]), default=None)


def special_ammo(holder, base: str) -> list[dict]:
    return [it for it in holder.items() if it.get("kind") == "ammo" and it.get("base") == base and is_special_ammo(it)]


def ammo_count(holder, base: str) -> int:
    return sum(int(it["qty"]) for it in holder.items() if it.get("kind") == "ammo" and it.get("base") == base)


def ammo_label(base: str, n: int) -> str:
    return f"{n} {AMMO[base][0].lower() if n != 1 else AMMO_SINGULAR[base]}"


def ration_days(holder) -> int:
    return sum(int(it["qty"]) for it in holder.items() if it.get("kind") == "rations")


def eat(holder, days: int) -> tuple[list[tuple[str, int]], int]:
    """Eat `days` of rations, standard first (they spoil sooner), then iron. Returns ([(name, days)], days short)."""
    eaten: list[tuple[str, int]] = []
    left = days
    for base in ("standard", "iron"):
        for it in [i for i in holder.items() if i.get("kind") == "rations" and i.get("base") == base]:
            if left <= 0:
                break
            take = min(left, int(it["qty"]))
            holder.remove_item(it["id"], take)
            eaten.append((it["name"], take))
            left -= take
    return eaten, left


def feed_stone(holder) -> Fraction:
    return sum((holder.item_stone_each(it) * int(it["qty"]) for it in holder.items() if it.get("kind") == "feed"),
               Fraction(0))


def add_feed(holder, name: str, stone: Fraction, notes: str = "") -> dict:
    """Feed is one item per kind of feed whose weight is what's left; adding more raises the weight."""
    for it in holder.items():
        if it.get("kind") == "feed" and it["name"].lower() == name.lower():
            it["weight"] = _store(holder.item_stone_each(it) * int(it["qty"]) + stone)
            it["qty"], it["unit"] = 1, "stone"
            return it
    return holder.add_item(name, 1, stone, "stone", "feed", notes=notes)


def feed(holder, need: Fraction) -> tuple[Fraction, Fraction]:
    """Eat `need` stone of feed from the animal's packs. Returns (stone eaten, stone short)."""
    left = need
    for it in [i for i in holder.items() if i.get("kind") == "feed"]:
        if left <= 0:
            break
        have = holder.item_stone_each(it) * int(it["qty"])
        take = min(have, left)
        rest = have - take
        if rest > 0:
            it["weight"], it["qty"], it["unit"] = _store(rest), 1, "stone"
        else:
            holder.remove_item(it["id"])
        left -= take
    return need - left, left


def _store(x: Fraction):
    from .character import _store_number
    return _store_number(x)


# ---------------------------------------------------------------------------
# Converting items saved before supplies were tracked
# ---------------------------------------------------------------------------

def convert_legacy(holder) -> list[str]:
    """Turn plain-gear rations, ammo and feed into tracked supplies. Returns a line per change."""
    changes = []
    for it in list(holder.items()):
        if it.get("kind") != "gear":
            continue
        name, qty = it["name"], int(it["qty"])
        typed = re.fullmatch(r"""\s*["']?(.+?)["']?\s+quantity\s+(\d+)\s*""", name, re.I)   # 'X' quantity 4
        if typed:
            name, qty = typed.group(1), qty * int(typed.group(2))
        s = recognize(name)
        if s is None:
            continue
        if s.kind == "feed":
            stone = holder.item_stone_each(it) * qty
            holder.data["items"].remove(it)
            add_feed(holder, s.name, stone, it.get("notes", ""))
            changes.append(f"{qty}× {it['name']} → feed, {_fmt(stone)}")
            continue
        units = qty * s.count
        holder.data["items"].remove(it)
        holder.add_item(s.name, units, s.each, "stone", s.kind, s.base, int(it.get("magic", 0)), it.get("notes", ""))
        shown = f"{units} day{'s' if units != 1 else ''} of {s.name}" if s.kind == "rations" else f"{units}× {s.name}"
        changes.append(f"{qty}× {it['name']} → {shown}")
    return changes


def _fmt(x: Fraction) -> str:
    from .rules import fmt_stone
    return fmt_stone(x)
