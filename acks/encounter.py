"""Initiative roster for one encounter (pure data, no Discord).

ACKS II: each round every combatant rolls 1d6 + modifiers (a party-sized group of identical monsters may
share one roll), and the Judge counts down from the highest number. Ties: combatants on the same side
choose their order; between sides, the side with fewer members chooses (the Judge's side if equal).
"""
from __future__ import annotations

from typing import Callable

from .character import Character
from .dice import d, fmt_mod

SIDES = {"party": "Party", "ally": "Ally", "enemy": "Enemy"}


def new_encounter(owner_id: int) -> dict:
    return {"owner_id": owner_id, "round": 0, "combatants": [], "next_id": 1, "message_id": None}


def _add(enc: dict, entry: dict) -> dict:
    entry.update(id=enc["next_id"], roll=None, total=None, detail="")
    enc["next_id"] += 1
    enc["combatants"].append(entry)
    return entry


def add_character(enc: dict, ch: Character) -> dict:
    for c in enc["combatants"]:
        if c.get("char_id") == ch.id:
            raise ValueError(f"**{ch.name}** is already in the roster.")
    return _add(enc, {"name": ch.name, "kind": "pc", "char_id": ch.id, "side": "party", "count": 1,
                      "modifier": ch.initiative_bonus().total})


def add_npc(enc: dict, name: str, modifier: int = 0, count: int = 1, side: str = "enemy",
            individually: bool = False) -> list[dict]:
    """Add a combatant or group. A group shares one roll unless `individually` is set."""
    name = name.strip() or "Combatant"
    if side not in SIDES or side == "party":
        side = "enemy"
    count = max(1, min(int(count), 500))
    if individually and count > 1:
        if count > 25:
            raise ValueError("Roll individually works for up to 25 combatants; use a shared group roll for more.")
        return [_add(enc, {"name": f"{name} {i}", "kind": "npc", "char_id": None, "side": side, "count": 1,
                           "modifier": int(modifier)}) for i in range(1, count + 1)]
    return [_add(enc, {"name": name, "kind": "npc", "char_id": None, "side": side, "count": count,
                       "modifier": int(modifier)})]


def remove(enc: dict, combatant_id: int) -> dict:
    for c in enc["combatants"]:
        if c["id"] == combatant_id:
            enc["combatants"].remove(c)
            return c
    raise ValueError("That combatant isn't in the roster.")


def roll_one(c: dict, characters: Callable[[int], Character | None]) -> None:
    detail = ""
    if c["kind"] == "pc":
        ch = characters(c["char_id"])
        if ch:   # recompute every round: equipment, encumbrance and proficiencies can change mid-fight
            bonus = ch.initiative_bonus()
            c["modifier"], c["name"] = bonus.total, ch.name
            detail = bonus.describe() if bonus.parts else ""
    r = d(6)
    c["roll"], c["total"], c["detail"] = r, r + int(c["modifier"]), detail


def roll_round(enc: dict, characters: Callable[[int], Character | None]) -> None:
    """Start a new round: everyone rolls again."""
    enc["round"] += 1
    for c in enc["combatants"]:
        roll_one(c, characters)


def side_size(enc: dict, side: str) -> int:
    group = "party" if side in ("party", "ally") else "enemy"
    return sum(c["count"] for c in enc["combatants"]
               if ("party" if c["side"] in ("party", "ally") else "enemy") == group)


def order(enc: dict) -> list[dict]:
    """Highest initiative first; unrolled combatants last. Ties keep roster order (resolved at the table)."""
    rolled = [c for c in enc["combatants"] if c["total"] is not None]
    waiting = [c for c in enc["combatants"] if c["total"] is None]
    return sorted(rolled, key=lambda c: -c["total"]) + waiting


def tie_notes(enc: dict) -> list[str]:
    """Explain who decides the order for each initiative number shared by both sides."""
    notes = []
    by_total: dict[int, list[dict]] = {}
    for c in enc["combatants"]:
        if c["total"] is not None:
            by_total.setdefault(c["total"], []).append(c)
    friends, foes = side_size(enc, "party"), side_size(enc, "enemy")
    for total in sorted(by_total, reverse=True):
        group = by_total[total]
        if len(group) < 2:
            continue
        sides = {"party" if c["side"] in ("party", "ally") else "enemy" for c in group}
        if len(sides) == 1:
            notes.append(f"**{total}**: same side, so they choose their order.")
        elif friends < foes:
            notes.append(f"**{total}**: the party is the smaller side, so the players choose who goes first.")
        else:
            notes.append(f"**{total}**: the Judge's side is {'smaller' if foes < friends else 'equal'}, "
                         f"so the Judge chooses who goes first.")
    return notes


def describe(c: dict) -> str:
    if c["total"] is None:
        return f"rolls next round ({fmt_mod(int(c['modifier']))})"
    return f"d6 {c['roll']} {fmt_mod(int(c['modifier']))}"
