"""Character model and every derived number on the sheet.

A Character wraps a plain dict (what gets stored as JSON in SQLite) and
computes AC, attack throws, saving throws, encumbrance, and speed from it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

from . import rules
from .dice import d, fmt_mod
from .rules import ARMOR_RANKS, ArmorDef, ClassDef, WeaponDef

MODIFIER_TARGETS = {
    "attack": "All attack throws",
    "melee_attack": "Melee attack throws",
    "ranged_attack": "Missile attack throws",
    "damage": "All damage rolls",
    "melee_damage": "Melee damage rolls",
    "ranged_damage": "Missile damage rolls",
    "ac": "Armor Class",
    "saves": "All saving throws",
    "save_paralysis": "Paralysis saves",
    "save_death": "Death saves",
    "save_blast": "Blast saves",
    "save_implements": "Implements saves",
    "save_spells": "Spells saves",
    "initiative": "Initiative",
}

RANGE_PENALTY = {"short": 0, "medium": -2, "long": -5}

EQUIP_SLOTS = ["main", "off", "missile", "armor", "shield"]
SLOT_LABELS = {"main": "Main hand", "off": "Off hand", "missile": "Missile", "armor": "Armor", "shield": "Shield"}


def new_character_data(guild_id: int, owner_id: int) -> dict:
    return {
        "guild_id": guild_id,
        "owner_id": owner_id,
        "name": "Unnamed",
        "class_key": "fighter",
        "level": 1,
        "xp": 0,
        "attributes": {a: 10 for a in rules.ATTRIBUTES},
        "hp": {"current": 1, "max": 1},
        "alignment": "Neutral",
        "homeland": "",
        "sex": "",
        "age": "",
        "description": "",
        "template": "",
        "proficiencies": ["Adventuring"],
        "options": {},
        "items": [],
        "next_item_id": 1,
        "equipped": {"main": None, "off": None, "two_handed": False, "missile": None, "armor": None,
                     "shield": None},
        "purse": {c: 0 for c in rules.COIN_TYPES},
        "modifiers": [],
        "notes": "",
    }


@dataclass
class Bonus:
    """A labelled list of numeric contributions, for showing the math."""
    parts: list[tuple[str, int]] = field(default_factory=list)

    def add(self, label: str, value: int) -> None:
        if value:
            self.parts.append((label, value))

    @property
    def total(self) -> int:
        return sum(v for _, v in self.parts)

    def describe(self) -> str:
        if not self.parts:
            return "no modifiers"
        return ", ".join(f"{fmt_mod(v)} {label}" for label, v in self.parts)


@dataclass
class AttackProfile:
    kind: str                       # melee | missile
    weapon_name: str
    weapon: WeaponDef | None
    style: str
    throw: int                      # base attack throw value (before target AC)
    bonus: Bonus
    damage_die: str
    damage_bonus: Bonus
    extra_dice_on_hit: int = 0      # backstab / ambush dice
    weapon_focus: bool = False
    nonproficient: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    off_hand_name: str | None = None

    def damage_expression(self) -> str:
        dice = self.damage_die
        if self.extra_dice_on_hit and dice not in ("0", ""):
            n, _, sides = dice.partition("d")
            dice = f"{int(n or 1) + self.extra_dice_on_hit}d{sides}"
        b = self.damage_bonus.total
        return f"{dice}{fmt_mod(b) if b else ''}"


class Character:
    def __init__(self, data: dict, char_id: int | None = None):
        self.data = data
        self.id = char_id

    # -- basic accessors ---------------------------------------------------
    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def cls(self) -> ClassDef:
        return rules.CLASSES[self.data["class_key"]]

    @property
    def level(self) -> int:
        return int(self.data["level"])

    def score(self, attr: str) -> int:
        return int(self.data["attributes"][attr])

    def mod(self, attr: str) -> int:
        return rules.attr_mod(self.score(attr))

    @property
    def options(self) -> dict:
        return self.data.setdefault("options", {})

    def has_prof(self, *needles: str) -> bool:
        return any(rules.proficiency_matches(p, *needles) for p in self.data["proficiencies"])

    def profs_matching(self, *needles: str) -> list[str]:
        return [p for p in self.data["proficiencies"] if rules.proficiency_matches(p, *needles)]

    def modifier_total(self, *targets: str) -> Bonus:
        b = Bonus()
        for m in self.data.get("modifiers", []):
            if m["target"] in targets:
                b.add(m["name"], int(m["value"]))
        return b

    # -- items -------------------------------------------------------------
    def items(self) -> list[dict]:
        return self.data["items"]

    def item(self, item_id: int | None) -> dict | None:
        if item_id is None:
            return None
        for it in self.data["items"]:
            if it["id"] == item_id:
                return it
        return None

    @staticmethod
    def item_stone_each(it: dict) -> Fraction:
        w = Fraction(str(it.get("weight", 0)))
        unit = it.get("unit", "stone")
        if unit == "items":
            return w / 6
        if unit == "coins":
            return w / rules.COINS_PER_STONE
        return w

    def item_weapon(self, it: dict | None) -> WeaponDef | None:
        if not it or it.get("kind") != "weapon":
            return None
        base = rules.WEAPONS.get(it.get("base") or "")
        if it.get("custom"):
            return rules.custom_weapon(base, it["custom"], it["name"])
        return base

    def item_armor(self, it: dict | None) -> ArmorDef | None:
        if not it or it.get("kind") not in ("armor", "shield"):
            return None
        base = rules.ARMORS.get(it.get("base") or "")
        if it.get("custom"):
            return rules.custom_armor(base, it["custom"], it["name"])
        return base

    def add_item(self, name: str, qty: int = 1, weight: float | Fraction = 0, unit: str = "stone",
                 kind: str = "gear", base: str | None = None, magic: int = 0, notes: str = "",
                 custom: dict | None = None) -> dict:
        # stack identical plain items
        for it in self.data["items"]:
            if (it["name"].lower() == name.lower() and it.get("kind") == kind and it.get("base") == base
                    and (it.get("custom") or None) == (custom or None)
                    and int(it.get("magic", 0)) == magic and it.get("unit") == unit
                    and Fraction(str(it.get("weight", 0))) == Fraction(str(weight))):
                it["qty"] += qty
                return it
        it = {
            "id": self.data["next_item_id"], "name": name, "qty": qty,
            "weight": _store_number(weight), "unit": unit, "kind": kind, "base": base,
            "magic": magic, "notes": notes,
        }
        if custom:
            it["custom"] = custom
        self.data["next_item_id"] += 1
        self.data["items"].append(it)
        return it

    def remove_item(self, item_id: int, qty: int | None = None) -> tuple[dict, int]:
        it = self.item(item_id)
        if it is None:
            raise KeyError(item_id)
        take = it["qty"] if qty is None else min(qty, it["qty"])
        it["qty"] -= take
        if it["qty"] <= 0:
            self.data["items"].remove(it)
        self._fix_equipped()
        return it, take

    def _fix_equipped(self) -> None:
        eq = self.data["equipped"]
        for slot in EQUIP_SLOTS:
            if eq.get(slot) is not None and self.item(eq[slot]) is None:
                eq[slot] = None
        main, off = self.item(eq.get("main")), self.item(eq.get("off"))
        if main and off and main["id"] == off["id"] and main["qty"] < 2:
            eq["off"] = None
        if eq.get("main") is None:
            eq["two_handed"] = False

    # -- equipment ---------------------------------------------------------
    def equipped(self, slot: str) -> dict | None:
        return self.item(self.data["equipped"].get(slot))

    def armor_def(self) -> ArmorDef | None:
        return self.item_armor(self.equipped("armor"))

    def shield_def(self) -> ArmorDef | None:
        return self.item_armor(self.equipped("shield"))

    def armor_category(self) -> str:
        a = self.armor_def()
        return a.category if a else "none"

    def styles(self) -> set[str]:
        s = set(self.cls.styles)
        if self.cls.key == "barbarian":
            s = {"single", "missile"} | rules.BARBARIAN_REGIONS.get(
                self.options.get("barbarian_region", ""), {}).get("styles", set())
        # styles picked at creation (e.g. dual OR weapon and shield); unpicked options are not granted
        chosen = self.options.get("style_choice")
        if self.cls.style_choice and chosen is not None:
            s -= set(self.cls.style_choice["options"]) - set(chosen)
        # /character training: styles granted or removed by class choices or powers
        for style, on in self.options.get("style_overrides", {}).items():
            if on:
                s.add(style)
            else:
                s.discard(style)
        return s | {"single", "missile"}

    def style_choice_pending(self) -> bool:
        """The class picks fighting styles and this character hasn't picked yet."""
        return bool(self.cls.style_choice) and self.options.get("style_choice") is None

    def set_style_choice(self, picks) -> None:
        picks = tuple(s for s in rules.STYLES if s in picks)
        if picks not in rules.style_choices(self.cls):
            raise ValueError(f"{self.cls.name}s {rules.describe_styles(self.cls).split('; ')[-1]}.")
        self.options["style_choice"] = list(picks)

    def melee_style(self) -> str:
        eq = self.data["equipped"]
        if eq.get("main") is None:
            return "unarmed"
        if eq.get("two_handed"):
            return "two_handed"
        if eq.get("off") is not None:
            return "dual"
        if eq.get("shield") is not None:
            return "weapon_and_shield"
        return "single"

    def equip(self, item_id: int, slot: str) -> list[str]:
        """Equip an item. Returns notes about anything else that changed."""
        it = self.item(item_id)
        if it is None:
            raise ValueError("That item isn't in the inventory.")
        eq = self.data["equipped"]
        notes: list[str] = []
        w = self.item_weapon(it)
        if slot in ("main", "off", "both"):
            if not w:
                raise ValueError(f"**{it['name']}** isn't a weapon. Add it with a weapon `base` to wield it.")
            if not w.melee:
                raise ValueError(f"**{it['name']}** is a missile weapon. Equip it in the **missile** slot.")
        if slot == "both":
            if w.size not in ("medium", "large"):
                raise ValueError("Only medium or large weapons can be wielded two-handed.")
            eq["main"], eq["two_handed"] = item_id, True
            if eq.get("off") is not None:
                eq["off"] = None
                notes.append("off-hand weapon put away")
            if eq.get("shield") is not None:
                eq["shield"] = None
                notes.append("shield slung")
        elif slot == "main":
            eq["main"] = item_id
            eq["two_handed"] = w.size == "large"
            if w.size == "large":
                notes.append("large weapon: wielded two-handed")
                if eq.get("off") is not None:
                    eq["off"] = None
                    notes.append("off-hand weapon put away")
                if eq.get("shield") is not None:
                    eq["shield"] = None
                    notes.append("shield slung")
        elif slot == "off":
            if w.size == "large":
                raise ValueError("A large weapon can't be held in the off hand.")
            if eq.get("main") is None:
                raise ValueError("Equip a main-hand weapon first.")
            if eq.get("main") == item_id and it["qty"] < 2:
                raise ValueError(f"You only have one **{it['name']}**.")
            main_w = self.item_weapon(self.equipped("main"))
            if main_w and main_w.size == "large":
                raise ValueError("Your main weapon needs both hands.")
            eq["off"], eq["two_handed"] = item_id, False
            if eq.get("shield") is not None:
                eq["shield"] = None
                notes.append("shield slung")
        elif slot == "missile":
            if not w or not w.missile:
                raise ValueError(f"**{it['name']}** can't be used as a missile weapon.")
            eq["missile"] = item_id
        elif slot == "armor":
            a = self.item_armor(it)
            if not a or a.category == "shield":
                raise ValueError(f"**{it['name']}** isn't body armor.")
            eq["armor"] = item_id
        elif slot == "shield":
            a = self.item_armor(it)
            if not a or a.category != "shield":
                raise ValueError(f"**{it['name']}** isn't a shield.")
            eq["shield"] = item_id
            if eq.get("two_handed"):
                main_w = self.item_weapon(self.equipped("main"))
                if main_w and main_w.size == "large":
                    eq["main"] = None
                    notes.append("two-handed weapon put away")
                else:
                    notes.append("main weapon now wielded one-handed")
                eq["two_handed"] = False
            if eq.get("off") is not None:
                eq["off"] = None
                notes.append("off-hand weapon put away")
        else:
            raise ValueError(f"Unknown slot {slot}")
        return notes

    def unequip(self, slot: str) -> None:
        eq = self.data["equipped"]
        if slot == "all":
            for s in EQUIP_SLOTS:
                eq[s] = None
            eq["two_handed"] = False
            return
        eq[slot] = None
        if slot == "main":
            eq["two_handed"] = False
            eq["off"] = None

    def auto_equip(self) -> None:
        """Pick sensible gear after a template: best armor, shield, melee, missile."""
        eq = self.data["equipped"]
        armors = [i for i in self.items() if i["kind"] == "armor"]
        if armors:
            eq["armor"] = max(armors, key=lambda i: (self._armor_ok(self.item_armor(i)),
                                                     self.item_armor(i).ac))["id"]
        styles = self.styles()
        shields = [i for i in self.items() if i["kind"] == "shield"]
        melee = [i for i in self.items() if (w := self.item_weapon(i)) and w.melee]
        missile = [i for i in self.items() if (w := self.item_weapon(i)) and w.missile]

        def melee_rank(i: dict) -> tuple:
            w = self.item_weapon(i)
            size_rank = {"tiny": 0, "small": 1, "medium": 2, "large": 3}[w.size]
            return (self.weapon_proficient(w), w.key not in ("net", "rock", "staff_sling"),
                    not w.thrown or w.key == "spear", size_rank)

        melee.sort(key=melee_rank, reverse=True)
        if melee:
            main = melee[0]
            mw = self.item_weapon(main)
            if shields and "weapon_and_shield" in styles and mw.size != "large":
                eq["main"], eq["shield"] = main["id"], shields[0]["id"]
                eq["two_handed"] = False
            else:
                eq["main"] = main["id"]
                off = None
                if mw.size != "large" and "dual" in styles and not self._fss("two_handed"):
                    if main["qty"] >= 2:
                        off = main
                    else:
                        # keep throwing weapons free for the missile slot unless trained to dual-wield
                        others = [i for i in melee if i["id"] != main["id"] and self.item_weapon(i).size != "large"
                                  and (self._fss("dual") or not self.item_weapon(i).thrown)]
                        off = others[0] if others else None
                if off:
                    eq["off"], eq["two_handed"] = off["id"], False
                else:
                    eq["two_handed"] = mw.size == "large" or (mw.size == "medium" and "two_handed" in styles
                                                              and mw.damage_2h is not None)
        if missile:
            def missile_rank(i: dict) -> tuple:
                w = self.item_weapon(i)
                return (self.weapon_proficient(w), w.key not in ("net", "bola", "military_oil", "rock"),
                        not w.melee, i["id"] not in (eq.get("main"), eq.get("off")) or i["qty"] > 1)
            eq["missile"] = max(missile, key=missile_rank)["id"]

    # -- proficiency -------------------------------------------------------
    def _armor_ok(self, a: ArmorDef | None) -> bool:
        if a is None or a.category == "shield":
            return True
        allowed = ARMOR_RANKS[self.cls.armor]
        if self.cls.key == "barbarian":
            allowed = ARMOR_RANKS["medium"]
        if self.options.get("armor_override"):   # /character training
            allowed = max(allowed, ARMOR_RANKS[self.options["armor_override"]])
        for p in self.profs_matching("armor training"):
            for cat in ("heavy", "medium", "light"):
                if cat in rules.normalize(p):
                    allowed = max(allowed, ARMOR_RANKS[cat])
                    break
            else:
                allowed = min(ARMOR_RANKS["heavy"], allowed + 1)
        return ARMOR_RANKS[a.category] <= allowed

    def armor_proficient(self) -> bool:
        return self._armor_ok(self.armor_def())

    def weapon_proficient(self, w: WeaponDef | None) -> bool:
        if w is None:
            return True
        if w.key in ("rock", "military_oil"):
            return True   # everyone can throw bottles, flasks, rocks, and torches
        if w.key in self.options.get("extra_weapons", []):   # /character training
            return True
        wp = self.cls.weapons
        if self.cls.key == "barbarian":
            region = rules.BARBARIAN_REGIONS.get(self.options.get("barbarian_region", ""))
            wp = rules.WeaponProficiency(weapons=region["weapons"] if region else ())
        ok = False
        if w.key in wp.excluded:
            ok = False
        elif wp.all:
            ok = True
        elif w.key in wp.weapons or w.category in wp.categories:
            ok = True
        elif wp.missile_all and w.missile and not w.melee:
            ok = True
        elif w.melee and w.size in wp.melee_sizes:
            ok = True
        elif wp.missile_all and w.missile:
            ok = True
        if not ok:
            for p in self.profs_matching("martial training"):
                if any(rules.weapon_in_group(w, g) for g in rules.weapon_groups_in(p)):
                    ok = True
                if w.name.lower().split(" (")[0] in rules.normalize(p):
                    ok = True
        return ok

    def melee_nonproficiency(self) -> list[str]:
        reasons = []
        if not self.armor_proficient():
            reasons.append(f"not proficient in {self.armor_category()} armor")
        styles = self.styles()
        style = self.melee_style()
        for slot in ("main", "off"):
            w = self.item_weapon(self.equipped(slot))
            if w and not self.weapon_proficient(w):
                reasons.append(f"not proficient with {w.name.lower()}")
        if style == "dual" and "dual" not in styles:
            reasons.append("no dual weapon fighting style")
        if style == "two_handed" and "two_handed" not in styles:
            reasons.append("no two-handed fighting style")
        return reasons

    def missile_nonproficiency(self) -> list[str]:
        reasons = []
        if not self.armor_proficient():
            reasons.append(f"not proficient in {self.armor_category()} armor")
        w = self.item_weapon(self.equipped("missile"))
        if w and not self.weapon_proficient(w):
            reasons.append(f"not proficient with {w.name.lower()}")
        return reasons

    # -- combat numbers ----------------------------------------------------
    def attack_throw(self) -> int:
        row = self.cls.row(self.level)
        if row:
            return int(row["attack"])
        return 10 - rules.improvements(self.cls.attack_prog, self.level)

    def save_target(self, save: str) -> int:
        row = self.cls.row(self.level)
        if row:
            return int(row[save])
        return self.cls.save_base[save] - rules.improvements(self.cls.save_prog, self.level)

    def save_bonus(self, save: str, foe: str | None = None, agility: bool = False) -> Bonus:
        """WIL + Divine Blessing + modifiers; `foe`/`agility` add situational class power and proficiency bonuses."""
        b = Bonus()
        b.add("WIL", self.mod("WIL"))
        if self.has_prof("divine blessing"):
            b.add("Divine Blessing", 2)
        if foe == "evil" and self.cls.key == "paladin":
            b.add("Aura of Protection", 1)
        if foe == "vermin" and self.has_prof("vermin-slaying"):
            b.add("Vermin-Slaying", 1)
        if agility and self.has_prof("acrobatics"):
            b.add("Acrobatics", 2)
        for label, v in self.modifier_total("saves", f"save_{save}").parts:
            b.add(label, v)
        return b

    def class_damage_bonus(self, kind: str, w: WeaponDef | None) -> int:
        c = self.cls
        mode = c.damage_bonus
        if mode == "none":
            return 0
        if mode in ("melee", "missile") and kind != mode:
            return 0
        if mode == "barbarian" and kind != self.options.get("barbarian_damage", "melee"):
            return 0
        if mode == "ruinguard" and (kind != "melee" or not self.weapon_proficient(w)):
            return 0
        row = c.row(self.level)
        if row:
            return int(row.get("damage_bonus") or 0)
        return sum(1 for lvl in c.damage_bonus_levels if self.level >= lvl)

    def cleaves(self) -> int:
        if self.cls.cleave == "none":
            return 0
        n = self.level if self.cls.cleave == "level" else self.level // 2
        return n + (1 if self.has_prof("combat ferocity") else 0)

    def _light_and_nimble(self) -> bool:
        cat = self.armor_category()
        return cat in ("none", "very light", "light") and self.encumbrance() <= 5

    def armor_class(self) -> Bonus:
        b = Bonus()
        a = self.armor_def()
        armor_item = self.equipped("armor")
        if a:
            b.add(a.name, a.ac)
            b.add("magic armor", int(armor_item.get("magic", 0)))
        nonprof = bool(self.melee_nonproficiency())
        shield = self.shield_def()
        if shield:
            if "weapon_and_shield" in self.styles():
                b.add("shield", shield.ac)
                b.add("magic shield", int(self.equipped("shield").get("magic", 0)))
                if self._fss("weapon_and_shield"):
                    b.add("Fighting Style Spec.", 1)
            else:
                b.add("magic shield", int(self.equipped("shield").get("magic", 0)))
        if not nonprof:
            b.add("DEX", self.mod("DEX"))
        row = self.cls.row(self.level)
        if row and row.get("ac_bonus") and not nonprof:
            cond = self.cls.ac_bonus_condition
            if (cond == "unarmored" and a is None) or \
                    (cond == "nimble" and self.armor_category() in ("none", "very light", "light")
                     and self.encumbrance() <= 7) or cond is None:
                b.add(self.cls.ac_bonus_label, int(row["ac_bonus"]))
        step = 1 + (self.level >= 7) + (self.level >= 13)
        graceful = self.cls.graceful_fighting and not nonprof and self._light_and_nimble()
        if graceful:
            b.add("Graceful Fighting", step)
        if self.has_prof("swashbuckling") and self._light_and_nimble():
            swash = step
            if graceful and self.armor_category() != "none":
                swash = 1
            b.add("Swashbuckling", swash)
        for label, v in self.modifier_total("ac").parts:
            b.add(label, v)
        return b

    def ac(self) -> int:
        return self.armor_class().total

    def initiative_bonus(self, casting: bool = False) -> Bonus:
        b = Bonus()
        b.add("DEX", self.mod("DEX"))
        if self.cls.animal_reflexes:   # the +1 initiative power goes by different names per class
            b.add({"ruinguard": "Preternatural Quickening", "bao_lifeshaper": "Urgent Care"}.get(
                self.cls.key, "Animal Reflexes"), 1)
        if self.has_prof("combat reflexes") and not casting:   # doesn't apply when casting spells
            b.add("Combat Reflexes", 1)
        if casting and self.has_prof("battle magic"):
            b.add("Battle Magic", 1)
        if self.cls.graceful_fighting and self._light_and_nimble():
            b.add("Graceful Fighting", 1)
        if self.melee_style() == "single" and self._fss("single"):
            b.add("Fighting Style Spec.", 1)
        for label, v in self.modifier_total("initiative").parts:
            b.add(label, v)
        return b

    def _fss(self, style: str) -> bool:
        for p in self.profs_matching("style"):
            n = rules.normalize(p)
            if "spec" in n and any(k in n for k in rules.STYLE_KEYWORDS[style]):
                return True
        return False

    def _weapon_focus(self, w: WeaponDef | None, thrown: bool = False) -> bool:
        if w is None:
            return False
        for p in self.profs_matching("weapon focus"):
            for g in rules.weapon_groups_in(p):
                if rules.weapon_in_group(w, g) and (g != "slings_thrown" or thrown or w.key in
                                                     ("sling", "staff_sling")):
                    return True
        return False

    def _sneak_dice(self, sneak: bool, kind: str, range_band: str, nonprof: bool) -> tuple[int, int, str | None]:
        """(attack bonus, extra damage dice, note) for a backstab/ambush."""
        if not sneak:
            return 0, 0, None
        if kind == "missile" and range_band != "short" and not self.has_prof("sniping"):
            return 0, 0, "Backstabs and ambushes with missiles only work at short range (Sniping allows long range)."
        if self.cls.backstab and not nonprof:
            if self.cls.key == "assassin" and self.armor_category() in ("medium", "heavy"):
                return 0, 0, "Assassins can't backstab in medium or heavier armor."
            return 4, 1 + (self.level - 1) // 4, "backstab"
        if (self.cls.ambush and not nonprof) or self.has_prof("ambushing"):
            return 4, 1, "ambush"
        return 0, 0, "This character can't backstab or ambush."

    FOES = {"goblinoid": ("goblin-slaying", "Goblin-Slaying"), "kin": ("kin-slaying", "Kin-Slaying"),
            "vermin": ("vermin-slaying", "Vermin-Slaying")}

    def _situational_attack(self, b: Bonus, notes: list[str], kind: str, w: WeaponDef | None,
                            conditions: set[str], foe: str | None) -> None:
        """Toggled circumstances: berserk rage, mounted, blinded, and favoured foes."""
        if "berserk" in conditions:
            if self.cls.key == "bta_fury" and not self.has_prof("berserkergang"):
                notes.append("Fighting Fury: +2 damage, immune to fear, can't retreat or withdraw.")
            elif not self.has_prof("berserkergang"):
                notes.append("Raging needs Berserkergang; no bonus applied.")
            elif kind == "melee" or (w and w.thrown):
                b.add("Berserkergang", 2)
                notes.append("Raging: -2 AC, can't retreat or withdraw, immune to fear.")
            else:
                notes.append("Berserkergang only helps melee and thrown attacks.")
        if "mounted" in conditions:
            if self.has_prof("mounted combat"):
                b.add("Mounted Combat", 1)
            else:
                notes.append("Fighting from the saddle without Mounted Combat may carry penalties (Judge's call).")
        if "blind" in conditions:
            b.add("blind" + (" (Blind Fighting)" if self.has_prof("blind fighting") else ""),
                  -2 if self.has_prof("blind fighting") else -4)
        if foe in self.FOES:
            needle, label = self.FOES[foe]
            if self.has_prof(needle):
                bonus = 1 if foe == "vermin" else 1 + (self.level >= 7) + (self.level >= 13)
                b.add(label, bonus)
        if foe == "evil" and self.cls.key == "paladin":
            notes.append("Aura of Protection: +1 AC and saves against this evil foe.")

    def melee_profile(self, situational: int = 0, sneak: bool = False, conditions: set[str] | None = None,
                      foe: str | None = None) -> AttackProfile:
        main_it = self.equipped("main")
        off_it = self.equipped("off")
        w = self.item_weapon(main_it)
        style = self.melee_style()
        reasons = self.melee_nonproficiency()
        nonprof = bool(reasons)
        notes: list[str] = []
        b = Bonus()
        if w is None:
            row = self.cls.row(self.level)
            if row and row.get("unarmed_damage"):
                weapon_name, die = "Bare fists", row["unarmed_damage"]
            else:
                weapon_name, die = "Unarmed (brawling)", "1d2"
        else:
            weapon_name = main_it["name"]
            die = w.damage_2h if (style == "two_handed" and w.damage_2h) else w.damage
        throw = rules.NONPROFICIENT_ATTACK_THROW if nonprof else self.attack_throw()
        if not nonprof:
            attr, attr_val = "STR", self.mod("STR")
            finesse = (self.has_prof("weapon finesse") and (w is None or w.size in ("tiny", "small", "medium"))) or \
                      (self.cls.weapon_finesse and self.weapon_proficient(w))
            if finesse and self.mod("DEX") > attr_val:
                attr, attr_val = "DEX (Weapon Finesse)", self.mod("DEX")
            b.add(attr, attr_val)
        if main_it:
            b.add("magic weapon", int(main_it.get("magic", 0)))
        if style == "dual":
            b.add("dual weapons", 1)
            if self._fss("dual"):
                b.add("Fighting Style Spec.", 1)
            b.add("off-hand magic", int(off_it.get("magic", 0)) if off_it else 0)
        for label, v in self.modifier_total("attack", "melee_attack").parts:
            b.add(label, v)
        sneak_bonus, extra_dice, sneak_note = self._sneak_dice(sneak, "melee", "short", nonprof)
        if sneak_bonus:
            b.add(sneak_note.capitalize(), sneak_bonus)
        elif sneak_note:
            notes.append(sneak_note)
        self._situational_attack(b, notes, "melee", w, conditions or set(), foe)
        b.add("situational", situational)

        dmg = Bonus()
        dmg.add("STR", self.mod("STR"))
        if not nonprof:
            dmg.add("class", self.class_damage_bonus("melee", w))
        if main_it:
            dmg.add("magic", int(main_it.get("magic", 0)))
        if style == "two_handed" and self._fss("two_handed"):
            dmg.add("Fighting Style Spec.", 1)
        if "berserk" in (conditions or set()) and self.cls.key == "bta_fury":
            dmg.add("Fighting Fury", 2)
        for label, v in self.modifier_total("damage", "melee_damage").parts:
            dmg.add(label, v)
        if w and w.key == "net":
            notes.append("Nets deal no damage (entangling).")
        return AttackProfile("melee", weapon_name, w, style, throw, b, die, dmg, extra_dice,
                             self._weapon_focus(w) and not nonprof, reasons, notes,
                             off_it["name"] if off_it else None)

    def missile_profile(self, range_band: str = "short", situational: int = 0, sneak: bool = False,
                        conditions: set[str] | None = None, foe: str | None = None) -> AttackProfile:
        it = self.equipped("missile")
        w = self.item_weapon(it)
        if w is None:
            raise ValueError("No missile weapon equipped. Use `/equip` with the **missile** slot.")
        reasons = self.missile_nonproficiency()
        nonprof = bool(reasons)
        notes: list[str] = []
        throw = rules.NONPROFICIENT_ATTACK_THROW if nonprof else self.attack_throw()
        b = Bonus()
        if not nonprof:
            b.add("DEX", self.mod("DEX"))
        b.add("magic weapon", int(it.get("magic", 0)))
        penalty_band = range_band
        if self.has_prof("long range volleying") and range_band != "short":
            penalty_band = {"medium": "short", "long": "medium"}[range_band]   # treats targets one band closer
        b.add(f"{range_band} range" + (" (Long Range Volleying)" if penalty_band != range_band else ""),
              RANGE_PENALTY[penalty_band])
        if self._fss("missile"):
            b.add("Fighting Style Spec.", 1)
        for label, v in self.modifier_total("attack", "ranged_attack").parts:
            b.add(label, v)
        sneak_bonus, extra_dice, sneak_note = self._sneak_dice(sneak, "missile", range_band, nonprof)
        if sneak_bonus:
            b.add(sneak_note.capitalize(), sneak_bonus)
        elif sneak_note:
            notes.append(sneak_note)
        self._situational_attack(b, notes, "missile", w, conditions or set(), foe)
        b.add("situational", situational)

        dmg = Bonus()
        if w.thrown and w.key != "military_oil":
            dmg.add("STR", self.mod("STR"))
        if not nonprof:
            dmg.add("class", self.class_damage_bonus("missile", w))
        dmg.add("magic", int(it.get("magic", 0)))
        for label, v in self.modifier_total("damage", "ranged_damage").parts:
            dmg.add(label, v)
        if w.ranges:
            s, m, l = w.ranges
            notes.append(f"Range {s}'/{m}'/{l}'")
        if "Slow" in w.special:
            notes.append("Slow: can't fire on consecutive rounds unless stationary or mounted.")
        return AttackProfile("missile", it["name"], w, "missile", throw, b, w.damage, dmg, extra_dice,
                             self._weapon_focus(w, thrown=w.thrown) and not nonprof, reasons, notes)

    # -- encumbrance -------------------------------------------------------
    def coin_count(self) -> int:
        return sum(int(v) for v in self.data["purse"].values())

    def coin_stone(self) -> Fraction:
        """1,000 coins = 1 stone, counted in 1/6-stone 'items' so pocket change weighs nothing."""
        return Fraction(self.coin_count() * 6 // rules.COINS_PER_STONE, 6)

    def harness_relief(self) -> Fraction:
        """An adventurer's (delver's, burglar's) harness ignores 1 stone of light gear; not over heavy armor."""
        if self.armor_category() == "heavy":
            return Fraction(0)
        if not any("harness" in it["name"].lower() for it in self.items()):
            return Fraction(0)
        light = sum((self.item_stone_each(it) * int(it["qty"]) for it in self.items()
                     if it["kind"] not in ("armor", "shield", "clothing", "animal")
                     and self.item_stone_each(it) < 1), Fraction(0))
        return min(Fraction(1), light)

    def encumbrance(self) -> Fraction:
        total = Fraction(0)
        for it in self.items():
            total += self.item_stone_each(it) * int(it["qty"])
        return total + self.coin_stone() - self.harness_relief()

    def max_encumbrance(self) -> int:
        return 20 + self.mod("STR")

    def speeds(self) -> dict:
        enc = self.encumbrance()
        explore, band = rules.speed_for(enc, self.mod("STR"))
        if (self.has_prof("running") and enc <= 7
                and ARMOR_RANKS[self.armor_category()] <= ARMOR_RANKS["medium"]):
            explore += 30   # Running proficiency
        return {"exploration": explore, "combat": explore // 3, "running": explore,
                "expedition": explore // 5, "band": band}

    def purse_value_gp(self) -> Fraction:
        return sum((Fraction(int(self.data["purse"][c])) * rules.COIN_VALUES_GP[c] for c in rules.COIN_TYPES),
                   Fraction(0))

    def spend_coins(self, amount: int, coin: str, make_change: bool = True) -> dict[str, int]:
        """Spend coins of one kind. When short, break as few larger coins as needed into that kind
        (1 gp -> 100 cp, 1 gp -> 10 sp...); the change stays in the purse. Returns the coins broken."""
        purse, values = self.data["purse"], rules.COIN_VALUES_GP
        have = int(purse.get(coin, 0))
        broken: dict[str, int] = {}
        if amount > have:
            short = (amount - have) * values[coin]
            # smallest coins first, so a pp is only broken when gp and ep can't cover it
            pool = sorted((c for c in rules.COIN_TYPES if values[c] > values[coin] and int(purse.get(c, 0))),
                          key=values.get) if make_change else []
            while short > 0 and pool:
                enough = next((c for c in pool if int(purse[c]) * values[c] >= short), None)
                if enough:
                    broken[enough] = math.ceil(short / values[enough])
                    short = 0
                else:
                    c = pool.pop(0)
                    broken[c] = int(purse[c])
                    short -= broken[c] * values[c]
            if short > 0:
                hint = (" and no larger coins to make change from" if make_change
                        else "; leave `make_change` on to break larger coins")
                raise ValueError(f"**{self.name}** only has {have:,} {coin}{hint}." if not broken
                                 else f"**{self.name}** only has {have:,} {coin}, and breaking every larger coin "
                                      f"still leaves them short (purse ≈ {float(self.purse_value_gp()):,.2f} gp).")
        for c, n in broken.items():
            purse[c] = int(purse[c]) - n
        gained = sum((n * values[c] for c, n in broken.items()), Fraction(0)) / values[coin]
        purse[coin] = have + int(gained) - amount   # larger coin values are whole multiples of smaller ones
        return broken

    # -- XP and levels -----------------------------------------------------
    def xp_for_next(self) -> int | None:
        if self.level >= self.cls.max_level:
            return None
        return self.cls.xp[self.level]

    def xp_bonus_pct(self) -> int:
        return min(rules.xp_bonus(self.score(a)) for a in self.cls.key_attributes)

    def can_level(self) -> bool:
        nxt = self.xp_for_next()
        return nxt is not None and self.data["xp"] >= nxt

    def hit_dice_label(self, level: int | None = None) -> str:
        level = level or self.level
        hd = self.cls.hit_die
        if level == 1 and self.cls.first_level_hp_bonus:
            return f"1d{hd}+{self.cls.first_level_hp_bonus}"
        if level <= 9:
            return f"{level}d{hd}"
        return f"9d{hd}+{(level - 9) * self.cls.hp_after_9}"

    def eligible(self) -> bool:
        return eligible_for(self.cls, self.data["attributes"])

    # -- hit points --------------------------------------------------------
    def roll_first_level_hp(self, maximize: bool = False) -> tuple[int, str]:
        """1 HD, a roll of 4 or less counts as 4, plus CON (never below 1)."""
        hd, con = self.cls.hit_die, self.mod("CON")
        raw = hd if maximize else d(hd)
        die = max(4, raw)
        bonus = self.cls.first_level_hp_bonus
        hp = max(1, die + bonus + con)
        how = "max" if maximize else f"rolled {raw}" + (" → 4" if raw < 4 else "")
        detail = f"1d{hd} ({how}){f' +{bonus}' if bonus else ''} {fmt_mod(con)} CON = **{hp}**"
        return hp, detail

    def roll_level_hp(self, level: int) -> tuple[int, str]:
        """Re-roll all Hit Dice for `level`, CON on each die (each die min 1)."""
        hd, con = self.cls.hit_die, self.mod("CON")
        n = min(level, 9)
        rolls = [d(hd) for _ in range(n)]
        total = sum(max(1, r + con) for r in rolls)
        flat = max(0, level - 9) * self.cls.hp_after_9
        total += flat
        detail = f"{n}d{hd} [{', '.join(map(str, rolls))}] {fmt_mod(con)} CON each"
        if flat:
            detail += f" +{flat}"
        return total, detail

    def level_up(self) -> tuple[int, int, str]:
        """Advance one level. Returns (old max hp, new max hp, roll detail)."""
        if self.level >= self.cls.max_level:
            raise ValueError(f"{self.cls.name}s can't advance past level {self.cls.max_level}.")
        old = int(self.data["hp"]["max"])
        self.data["level"] = self.level + 1
        rolled, detail = self.roll_level_hp(self.level)
        new = rolled if rolled > old else old + 1
        if rolled <= old:
            detail += f" = {rolled} (not more than {old}, so +1)"
        else:
            detail += f" = {rolled}"
        self.data["hp"]["max"] = new
        self.data["hp"]["current"] = int(self.data["hp"]["current"]) + (new - old)
        return old, new, detail


def eligible_for(c: ClassDef, attributes: dict) -> bool:
    if any(int(attributes[a]) < 9 for a in c.key_attributes):
        return False
    return all(int(attributes[a]) >= v for a, v in c.requirements.items())


def _store_number(x) -> str | int:
    """Weights are stored as ints or exact fraction strings like '1/6'."""
    f = x if isinstance(x, Fraction) else Fraction(str(x))
    f = f.limit_denominator(10000)
    if f.denominator == 1:
        return int(f)
    return str(f)
