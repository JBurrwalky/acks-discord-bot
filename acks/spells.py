"""Spell slot (and spell point) tracking: spend and refresh. No spell rules are modelled.

A character's spell pools come from its class table ("Arcane", "Divine", or "Spells"), at its current level.
Any pool can be given a manual maximum, which also lets a class without a table track slots.

Stored on the character as data["spells"]:
    {"slots":  {pool: {"used": {"1": 2}, "max": {"1": 3}}},   # "max" = manual overrides by spell level
     "points": {pool: {"used": 4, "max": 12}}}
"""
from __future__ import annotations

from .character import Character

class SpellError(ValueError):
    pass


def slot_word(pool: str) -> str:
    """'arcane ' for Arcane slots, '' for the generic Spells pool (so messages read '1 level 2 slot')."""
    return "" if pool == "Spells" else pool.lower() + " "


def class_table(ch: Character) -> dict:
    return ch.cls.spells or {}


def _state(ch: Character) -> dict:
    st = ch.data.setdefault("spells", {})
    st.setdefault("slots", {})
    st.setdefault("points", {})
    return st


def slot_pools(ch: Character) -> dict[str, dict[int, tuple[int, int]]]:
    """{pool: {spell level: (max, used)}} for every pool with at least one slot."""
    st = _state(ch)
    out: dict[str, dict[int, tuple[int, int]]] = {}
    table = class_table(ch).get("slots", {})
    names = list(table) + [p for p in st["slots"] if p not in table]
    for pool in names:
        rows = table.get(pool)
        row = rows[min(ch.level, len(rows)) - 1] if rows else []
        saved = st["slots"].get(pool, {})
        overrides = {int(k): int(v) for k, v in saved.get("max", {}).items()}
        used = {int(k): int(v) for k, v in saved.get("used", {}).items()}
        levels = {}
        for lvl in sorted(set(range(1, len(row) + 1)) | set(overrides)):
            mx = overrides.get(lvl, row[lvl - 1] if lvl <= len(row) else 0)
            if mx > 0:
                levels[lvl] = (mx, min(used.get(lvl, 0), mx))
        if levels:
            out[pool] = levels
    return out


def point_pools(ch: Character) -> dict[str, tuple[int, int]]:
    """{pool: (max points, used points)}."""
    st = _state(ch)
    out = {}
    table = class_table(ch).get("points")
    if table:
        saved = st["points"].get("Spell points", {})
        # Before All Others: each Magical Music a spellsinger takes adds one spell point
        music = len(ch.profs_matching("magical music"))
        mx = int(saved.get("max", table[min(ch.level, len(table)) - 1] + music))
        out["Spell points"] = (mx, min(int(saved.get("used", 0)), mx))
    for pool, saved in st["points"].items():
        if pool not in out and saved.get("max"):
            out[pool] = (int(saved["max"]), min(int(saved.get("used", 0)), int(saved["max"])))
    return out


def has_spells(ch: Character) -> bool:
    return bool(slot_pools(ch) or point_pools(ch))


def _pick_slot_pool(ch: Character, pool: str | None) -> str:
    pools = slot_pools(ch)
    if not pools:
        raise SpellError(f"**{ch.name}** has no spell slots. If they should, set them with `/spell set_slots`.")
    if pool:
        for name in pools:
            if name.lower() == pool.lower():
                return name
        raise SpellError(f"**{ch.name}** has no **{pool}** spell slots (has: {', '.join(pools)}).")
    if len(pools) > 1:
        raise SpellError(f"**{ch.name}** has more than one kind of spell slot ({', '.join(pools)}). "
                         f"Choose one with the `pool` option.")
    return next(iter(pools))


def cast(ch: Character, level: int, pool: str | None = None, count: int = 1) -> tuple[str, int, int]:
    """Spend `count` slots of a spell level. Returns (pool, remaining, max)."""
    name = _pick_slot_pool(ch, pool)
    levels = slot_pools(ch)[name]
    if level not in levels:
        have = ", ".join(f"level {lvl}" for lvl in levels)
        raise SpellError(f"**{ch.name}** has no level {level} {slot_word(name)}slots (has {have}).")
    mx, used = levels[level]
    if used + count > mx:
        left = mx - used
        raise SpellError(f"**{ch.name}** has {'no' if left == 0 else f'only {left}'} level {level} "
                         f"{slot_word(name)}slot{'s' if left != 1 else ''} left. Refresh with `/spell refresh`.")
    saved = _state(ch)["slots"].setdefault(name, {})
    saved.setdefault("used", {})[str(level)] = used + count
    return name, mx - used - count, mx


def spend_points(ch: Character, points: int, pool: str | None = None) -> tuple[str, int, int]:
    pools = point_pools(ch)
    if not pools:
        raise SpellError(f"**{ch.name}** doesn't use spell points.")
    name = pool if pool in pools else next(iter(pools))
    mx, used = pools[name]
    if used + points > mx:
        raise SpellError(f"**{ch.name}** has only {mx - used} spell points left.")
    _state(ch)["points"].setdefault(name, {})["used"] = used + points
    return name, mx - used - points, mx


def refresh(ch: Character, level: int | None = None, pool: str | None = None, count: int = 1) -> str:
    """level given: restore `count` slots of that level. No level: restore every slot (and spell points)."""
    st = _state(ch)
    if level is None:
        targets = [p for p in slot_pools(ch) if not pool or p.lower() == pool.lower()]
        for p in targets:
            st["slots"].setdefault(p, {})["used"] = {}
        points = [p for p in point_pools(ch) if not pool or p.lower() == pool.lower()]
        for p in points:
            st["points"].setdefault(p, {})["used"] = 0
        if not targets and not points:
            raise SpellError(f"**{ch.name}** has no{' ' + pool if pool else ''} spells to refresh.")
        kinds = [t.lower() for t in targets if t != "Spells"] + [p.lower() for p in points]
        label = " and ".join(kinds) + " " if kinds else ""
        return f"all {label}slots restored" if not points else f"all {label}restored"
    name = _pick_slot_pool(ch, pool)
    levels = slot_pools(ch)[name]
    if level not in levels:
        raise SpellError(f"**{ch.name}** has no level {level} {slot_word(name)}slots.")
    mx, used = levels[level]
    if used == 0:
        raise SpellError(f"All of **{ch.name}**'s level {level} {slot_word(name)}slots are already available.")
    back = min(count, used)
    st["slots"].setdefault(name, {}).setdefault("used", {})[str(level)] = used - back
    return f"{back} level {level} {slot_word(name)}slot{'s' if back != 1 else ''} restored"


def set_slots(ch: Character, level: int, slots: int | None, pool: str = "Spells") -> None:
    """Manual maximum for one spell level (None = back to the class table)."""
    saved = _state(ch)["slots"].setdefault(pool, {})
    maxes = saved.setdefault("max", {})
    if slots is None:
        maxes.pop(str(level), None)
    else:
        maxes[str(level)] = max(0, slots)


def set_points(ch: Character, points: int | None, pool: str = "Spell points") -> None:
    saved = _state(ch)["points"].setdefault(pool, {})
    if points is None:
        saved.pop("max", None)
    else:
        saved["max"] = max(0, points)


def summary_lines(ch: Character) -> list[str]:
    """One line per pool, e.g. 'Arcane · 1st ◆◆◇ · 2nd ◆'. ◆ = available, ◇ = spent."""
    lines = []
    for pool, levels in slot_pools(ch).items():
        cells = [f"{_ordinal(lvl)} {'◆' * (mx - used)}{'◇' * used}" for lvl, (mx, used) in levels.items()]
        lines.append(f"**{pool}** · " + " · ".join(cells))
    for pool, (mx, used) in point_pools(ch).items():
        lines.append(f"**{pool}** · {mx - used} / {mx}")
    return lines


def _ordinal(n: int) -> str:
    return f"{n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'}"
