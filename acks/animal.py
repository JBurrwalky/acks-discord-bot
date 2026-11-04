"""Animal sheets: a simple stat block with an inventory, load-limited speed, barding, and attack routines.

An Animal wraps a plain dict (stored as JSON in SQLite), like Character does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from . import rules
from .character import Bonus, ItemStore, _store_number
from .dice import d, roll

ATTACK_TEXT = re.compile(r"^\s*(?:(\d+)\s*[x×]?\s+)?(.+?)\s+(\d*d\d+(?:[+-]\d+)?)\s*$", re.I)


def new_animal_data(guild_id: int, user_id: int, name: str) -> dict:
    return {
        "guild_id": guild_id, "user_id": user_id, "name": name, "kind": "Animal", "owner_char": None,
        "hd": "1", "hp": {"current": 1, "max": 1}, "ac": 0, "attack_throw": None, "save": "", "morale": 0,
        "speed": 120, "normal_load": 0, "max_load": 0, "food": 0, "water": 0, "size": "large",
        "attacks": [], "abilities": [], "notes": "",
        "items": [], "next_item_id": 1, "barding": None,
    }


def parse_attacks(text: str) -> list[dict]:
    """'2 hoof 1d6, bite 1d4' -> [{'name': 'hoof', 'count': 2, 'damage': '1d6'}, ...]"""
    out = []
    for part in re.split(r"[;,\n]", text):
        if not part.strip():
            continue
        m = ATTACK_TEXT.match(part)
        if not m:
            raise ValueError(f"Can't read the attack `{part.strip()}`. Write it like `2 hoof 1d6` or `bite 1d4+1`.")
        out.append(make_attack(m.group(2), m.group(3), int(m.group(1) or 1)))
    return out


def make_attack(name: str, damage: str, count: int = 1) -> dict:
    damage = damage.replace(" ", "").lower()
    if not re.fullmatch(r"\d*d\d+([+-]\d+)?", damage):
        raise ValueError(f"Damage must be dice like `1d6` or `1d4+1`, not `{damage}`.")
    roll(damage)   # checks the dice limits
    if not 1 <= count <= 10:
        raise ValueError("An attack can be repeated 1 to 10 times.")
    return {"name": name.strip()[:40], "count": count, "damage": damage}


def roll_hd(hd: str) -> tuple[int, str]:
    """Hit points for a monster: d8 per Hit Die (1d4 for 1/2 HD) plus any bonus, minimum 1."""
    whole, half, bonus = rules.parse_hd(hd)
    expr = "1d4" if half or whole == 0 else f"{min(whole, 100)}d8"
    if bonus:
        expr += f"{bonus:+d}"
    r = roll(expr)
    return max(1, r.total), r.detail()


@dataclass
class AttackResult:
    attack: dict
    natural: int
    total: int
    need: int
    hit: bool
    damage: int | None
    damage_detail: str


class Animal(ItemStore):
    def __init__(self, data: dict, animal_id: int | None = None):
        self.data = data
        self.id = animal_id

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def owner_char(self) -> int | None:
        return self.data.get("owner_char")

    # -- stats -------------------------------------------------------------
    def attack_throw(self) -> int:
        at = self.data.get("attack_throw")
        return int(at) if at is not None else rules.monster_attack_throw(self.data["hd"])

    def barding_item(self) -> dict | None:
        return self.item(self.data.get("barding"))

    @staticmethod
    def barding_stats(it: dict) -> dict:
        return it.get("custom") or {}

    def armor_class(self) -> Bonus:
        b = Bonus()
        b.add("natural", int(self.data["ac"]))
        it = self.barding_item()
        if it:
            b.add(it["name"], int(self.barding_stats(it).get("ac", 0)) + int(it.get("magic", 0)))
        return b

    def ac(self) -> int:
        return self.armor_class().total

    def spiked(self) -> bool:
        it = self.barding_item()
        return bool(it and self.barding_stats(it).get("spiked"))

    # -- load and speed ----------------------------------------------------
    def encumbrance(self) -> Fraction:
        return sum((self.item_stone_each(it) * int(it["qty"]) for it in self.items()), Fraction(0))

    def speeds(self) -> dict:
        """Full speed up to the normal load, half up to the maximum load, no movement beyond it."""
        enc, normal, maximum = self.encumbrance(), Fraction(str(self.data["normal_load"])), \
            Fraction(str(self.data["max_load"]))
        base = int(self.data["speed"])
        if enc <= normal:
            explore, band = base, "Unencumbered"
        elif enc <= maximum:
            explore, band = base // 2, "Encumbered (half speed)"
        else:
            explore, band = 0, "Overloaded: can't move"
        return {"exploration": explore, "combat": explore // 3, "running": explore,
                "expedition": explore // 5, "band": band}

    def daily_food(self) -> Fraction:
        return Fraction(str(self.data["food"]))

    def daily_water(self) -> Fraction:
        return Fraction(str(self.data["water"]))

    # -- barding -----------------------------------------------------------
    def equip_barding(self, item_id: int) -> dict:
        it = self.item(item_id)
        if it is None or it.get("kind") != "barding":
            raise ValueError("Only barding can be equipped on an animal. Add some with `/animal barding`.")
        self.data["barding"] = it["id"]
        return it

    def unequip_barding(self) -> dict | None:
        it = self.barding_item()
        self.data["barding"] = None
        return it

    def _fix_equipped(self) -> None:
        if self.barding_item() is None:
            self.data["barding"] = None

    # -- HP ----------------------------------------------------------------
    def set_max_hp(self, mx: int) -> None:
        hp = self.data["hp"]
        hp["max"] = max(1, mx)
        hp["current"] = min(hp["current"], hp["max"])

    # -- attacks -----------------------------------------------------------
    def attacks(self) -> list[dict]:
        return self.data["attacks"]

    def damage_expression(self, attack: dict) -> str:
        """Spiked barding adds +1 damage per die to natural attacks (RR p. 129)."""
        dmg = attack["damage"]
        m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", dmg)
        if not self.spiked() or not m:
            return dmg
        flat = int(m.group(3) or 0) + int(m.group(1) or 1)
        return f"{m.group(1)}d{m.group(2)}" + (f"{flat:+d}" if flat else "")

    def roll_attack(self, attack: dict, target_ac: int, bonus: int = 0) -> AttackResult:
        natural = d(20)
        total = natural + bonus
        need = self.attack_throw() + target_ac
        hit = natural == 20 or (natural != 1 and total >= need)
        damage, detail = None, ""
        if hit:
            expr = self.damage_expression(attack)
            r = roll(expr)
            damage = max(1, r.total)
            detail = f"{expr}: {r.detail()}" + (" (minimum 1)" if r.total < 1 else "")
        return AttackResult(attack, natural, total, need, hit, damage, detail)


def attack_label(attack: dict) -> str:
    return f"{attack['count']}× {attack['name']}" if attack["count"] > 1 else attack["name"]


def store_stone(x) -> str | int:
    """Loads, food and water are stored like item weights: ints or exact fractions like '3/2'."""
    return _store_number(x)
