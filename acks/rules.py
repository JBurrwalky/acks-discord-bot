"""Static ACKS II rules data (Revised Rulebook, Imperial Imprint).

Everything here is plain data plus a few small lookup helpers. Character math
lives in character.py.
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

ATTRIBUTES = ["STR", "INT", "WIL", "DEX", "CON", "CHA"]
ATTRIBUTE_NAMES = {
    "STR": "Strength", "INT": "Intellect", "WIL": "Will",
    "DEX": "Dexterity", "CON": "Constitution", "CHA": "Charisma",
}

SAVES = ["paralysis", "death", "blast", "implements", "spells"]
SAVE_LABELS = {
    "paralysis": "Paralysis", "death": "Death", "blast": "Blast",
    "implements": "Implements", "spells": "Spells",
}


def attr_mod(score: int) -> int:
    """Attribute Modifiers table."""
    if score <= 3:
        return -3
    if score <= 5:
        return -2
    if score <= 8:
        return -1
    if score <= 12:
        return 0
    if score <= 15:
        return 1
    if score <= 17:
        return 2
    return 3


def xp_bonus(score: int) -> int:
    """Key Attribute experience adjustment, in percent."""
    if score >= 16:
        return 10
    if score >= 13:
        return 5
    return 0


# ---------------------------------------------------------------------------
# Combat progressions
# ---------------------------------------------------------------------------

def improvements(progression: str, level: int) -> int:
    """How many points attack/save throws have improved since 1st level.

    fighter: 2 points every 3 levels; thief/crusader: 2 points every 4 levels
    (1 per 2 levels); mage: 2 points every 6 levels (1 per 3 levels).
    """
    level = max(1, level)
    if progression == "fighter":
        return (2 * level - 1) // 3
    if progression == "thief":
        return (level - 1) // 2
    if progression == "mage":
        return (level - 1) // 3
    raise ValueError(progression)


NONPROFICIENT_ATTACK_THROW = 11  # attacks as a 0th level fighter


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

ARMOR_RANKS = {"none": 0, "very light": 1, "light": 2, "medium": 3, "heavy": 4}
STYLES = ["single", "missile", "dual", "two_handed", "weapon_and_shield"]
STYLE_LABELS = {
    "single": "Single weapon", "missile": "Missile weapon", "dual": "Dual weapon",
    "two_handed": "Two-handed weapon", "weapon_and_shield": "Weapon and shield",
}
ALL_STYLES = set(STYLES)


@dataclass
class WeaponProficiency:
    all: bool = False
    missile_all: bool = False               # "all missile weapons"
    melee_sizes: tuple[str, ...] = ()       # e.g. ("tiny", "small", "medium")
    categories: tuple[str, ...] = ()        # axes, bludgeons, bows, swords, spears, other
    weapons: tuple[str, ...] = ()           # specific weapon keys
    excluded: tuple[str, ...] = ()


@dataclass
class ClassDef:
    key: str
    name: str
    key_attributes: tuple[str, ...]
    hit_die: int
    xp: list[int]
    titles: list[str]
    attack_prog: str
    save_prog: str
    save_base: dict[str, int]
    weapons: WeaponProficiency
    armor: str                                # highest armor category allowed
    styles: set[str]
    hp_after_9: int                           # flat hp per level past 9th
    requirements: dict[str, int] = field(default_factory=dict)
    first_level_hp_bonus: int = 0             # e.g. elves roll 1d6+1 at 1st level
    damage_bonus: str = "none"                # none | all | melee | barbarian | ruinguard
    damage_bonus_levels: tuple[int, ...] = (1, 3, 6, 9, 12)
    cleave: str = "half"                      # level | half | none
    backstab: bool = False
    ambush: bool = False
    weapon_finesse: bool = False              # bladedancer class power
    graceful_fighting: bool = False           # bladedancer AC/initiative
    animal_reflexes: bool = False             # +1 initiative
    notes: str = ""
    source: str = "Revised Rulebook"
    # Supplement classes carry the book's own per-level table: attack, the five saves, damage_bonus,
    # and optionally unarmed_damage (e.g. "1d6") and ac_bonus.
    level_table: list[dict] | None = None
    # When a level-table ac_bonus applies: "unarmored" (no body armor) or "nimble" (leather or lighter and
    # no more than lightly encumbered).
    ac_bonus_condition: str | None = None
    ac_bonus_label: str = "class power"
    # Daily castings: {"slots": {pool: [[castings of spell level 1, 2, ...] per class level]},
    #                  "points": [spell points per class level]}
    spells: dict | None = None
    # Styles the player picks at creation: {"options": [styles], "pick": how many}. Styles in "options"
    # are only granted once chosen (until then, all of them are, as before the choice existed).
    style_choice: dict | None = None

    @property
    def max_level(self) -> int:
        return len(self.xp)

    def title(self, level: int) -> str:
        return self.titles[min(level, len(self.titles)) - 1]

    def row(self, level: int) -> dict | None:
        if not self.level_table:
            return None
        return self.level_table[max(1, min(level, len(self.level_table))) - 1]


FIGHTER_SAVES = {"paralysis": 13, "death": 14, "blast": 15, "implements": 16, "spells": 17}
THIEF_SAVES = {"paralysis": 13, "death": 13, "blast": 13, "implements": 14, "spells": 15}
CRUSADER_SAVES = {"paralysis": 13, "death": 10, "blast": 16, "implements": 13, "spells": 15}
MAGE_SAVES = {"paralysis": 13, "death": 13, "blast": 15, "implements": 11, "spells": 12}

ALL_WEAPONS = WeaponProficiency(all=True)
SKIRMISHER_WEAPONS = WeaponProficiency(missile_all=True, melee_sizes=("tiny", "small", "medium"))
CASTER_WEAPONS = WeaponProficiency(weapons=("club", "dagger", "silver_dagger", "dart", "staff"))

XP_FIGHTER = [0, 2000, 4000, 8000, 16000, 32000, 65000, 130000, 250000, 370000, 490000, 610000, 730000, 850000]
XP_THIEF = [0, 1250, 2500, 5000, 10000, 20000, 40000, 80000, 180000, 280000, 380000, 480000, 580000, 680000]
XP_MAGE = [0, 2500, 5000, 10000, 20000, 40000, 80000, 160000, 310000, 460000, 610000, 760000, 910000, 1060000]
XP_CRUSADER = [0, 1500, 3000, 6000, 12000, 24000, 50000, 100000, 200000, 300000, 400000, 500000, 600000, 700000]
XP_ASSASSIN = [0, 1750, 3500, 7000, 14000, 28000, 55000, 110000, 230000, 350000, 470000, 590000, 710000, 830000]
XP_PRIESTESS = [0, 2000, 4000, 8000, 16000, 32000, 65000, 130000, 230000, 330000, 430000, 530000, 630000, 730000]


def _titles(names: list[str], high: str, final: str, count: int = 14) -> list[str]:
    out = list(names)
    for lvl in range(len(names) + 1, count):
        out.append(f"{high}, {lvl}th level")
    out.append(final)
    return out


CLASSES: dict[str, ClassDef] = {}


def _add(c: ClassDef) -> None:
    CLASSES[c.key] = c


_add(ClassDef(
    "fighter", "Fighter", ("STR",), 8, XP_FIGHTER,
    _titles(["Man-at-Arms", "Warrior", "Swordmaster", "Hero", "Exemplar", "Myrmidon", "Champion",
             "Epic Hero", "Warlord"], "Warlord", "Overlord"),
    "fighter", "fighter", FIGHTER_SAVES, ALL_WEAPONS, "heavy", ALL_STYLES, 2,
    damage_bonus="all", cleave="level"))
_add(ClassDef(
    "explorer", "Explorer", ("CON",), 6, XP_FIGHTER,
    _titles(["Scout", "Outrider", "Forester", "Explorer", "Guide", "Tracker", "Wayfinder", "Ranger",
             "Warden"], "Warden", "Lord Warden"),
    "fighter", "fighter", FIGHTER_SAVES, SKIRMISHER_WEAPONS, "medium", ALL_STYLES, 2,
    damage_bonus="all", cleave="level", ambush=True, animal_reflexes=True,
    notes="Alertness (+1 to avoid surprise), Ambushing, Animal Reflexes (+1 initiative)."))
_add(ClassDef(
    "thief", "Thief", ("DEX",), 4, XP_THIEF,
    _titles(["Footpad", "Hood", "Robber", "Burglar", "Rogue", "Scoundrel", "Pilferer", "Thief",
             "Master Thief"], "Master Thief", "Prince of Thieves"),
    "thief", "thief", THIEF_SAVES, SKIRMISHER_WEAPONS, "light", {"single", "missile", "dual", "two_handed"}, 2,
    backstab=True))
_add(ClassDef(
    "mage", "Mage", ("INT",), 4, XP_MAGE,
    _titles(["Arcanist", "Seer", "Theurgist", "Magician", "Thaumaturge", "Enchanter", "Sorcerer", "Mage",
             "Wizard"], "Wizard", "Archmage"),
    "mage", "mage", MAGE_SAVES, CASTER_WEAPONS, "none", {"single", "missile", "two_handed"}, 1,
    cleave="none"))
_add(ClassDef(
    "crusader", "Crusader", ("WIL",), 6, XP_CRUSADER,
    _titles(["Catechist", "Acolyte", "Priest", "Curate", "Vicar", "Rector", "Prelate", "Bishop",
             "Patriarch"], "Patriarch", "Theocrat"),
    "thief", "thief", CRUSADER_SAVES,
    WeaponProficiency(weapons=("bola", "cestus", "club", "flail", "warhammer", "mace", "morning_star", "net",
                               "sling", "sap", "staff", "staff_sling", "whip")),
    "heavy", {"single", "missile", "weapon_and_shield", "two_handed"}, 1,
    notes="Weapon list assumes a crusader of Ammonar."))
_add(ClassDef(
    "venturer", "Venturer", ("CHA",), 6, XP_CRUSADER,
    _titles(["Tinker", "Trader", "Arbitrager", "Commissary", "Mercantilist", "Enterpriser", "Venturer",
             "Merchant Venturer", "Merchant Prince"], "Merchant Prince", "Mogul"),
    "thief", "thief", THIEF_SAVES,
    WeaponProficiency(weapons=("arbalest", "composite_bow", "crossbow", "dagger", "silver_dagger", "knife",
                               "long_bow", "short_bow", "short_sword")),
    "medium", {"single", "missile", "weapon_and_shield"}, 2))
_add(ClassDef(
    "assassin", "Assassin", ("STR", "DEX"), 6, XP_ASSASSIN,
    _titles(["Thug", "Enforcer", "Torturer", "Slayer", "Destroyer", "Executioner", "Blackguard", "Assassin",
             "Master Assassin"], "Master Assassin", "Grandfather of Assassins"),
    "fighter", "fighter", FIGHTER_SAVES, ALL_WEAPONS, "medium", ALL_STYLES, 2,
    damage_bonus="all", cleave="level", backstab=True,
    notes="Backstab, hiding and sneaking only in light armor or less."))
_add(ClassDef(
    "barbarian", "Barbarian", ("STR", "CON"), 8,
    [0, 2250, 4500, 9000, 18000, 36000, 70000, 140000, 260000, 380000, 500000, 620000, 740000, 860000],
    _titles(["Hunter", "Raider", "Marauder", "Plunderer", "Reaver", "Bloodletter", "Menace", "Scourge",
             "Warchief"], "Warchief", "Great Chieftain"),
    "fighter", "fighter", FIGHTER_SAVES, WeaponProficiency(), "medium", {"single", "missile"}, 2,
    damage_bonus="barbarian", cleave="level", animal_reflexes=True,
    notes="Animal Reflexes (+1 initiative, +1 to avoid surprise). Weapons and styles depend on region."))
_add(ClassDef(
    "bard", "Bard", ("DEX", "CHA"), 4, XP_ASSASSIN,
    _titles(["Reciter", "Versifier", "Archivist", "Annalist", "Chronicler", "Panegyrist", "Skald",
             "Rhapsodist", "Bard"], "Bard", "Master Bard"),
    "fighter", "fighter", FIGHTER_SAVES, SKIRMISHER_WEAPONS, "medium", ALL_STYLES, 2,
    damage_bonus="all", cleave="level"))
_add(ClassDef(
    "bladedancer", "Bladedancer", ("WIL", "DEX"), 6, XP_CRUSADER,
    _titles(["Blade-Initiate", "Blade-Daughter", "Blade-Singer", "Blade-Weaver", "Blade-Sister", "Blade-Adept",
             "Blade-Dancer", "Blade-Priestess", "Blade-Mistress"], "Blade-Mistress", "Mistress of All Blades"),
    "thief", "thief", CRUSADER_SAVES, WeaponProficiency(categories=("swords", "spears")),
    "light", {"single", "missile", "dual", "two_handed"}, 1,
    weapon_finesse=True, graceful_fighting=True,
    notes="Graceful Fighting: +1 init and AC (+2 at 7th, +3 at 13th) in light armor or less and <= 5 st."))
_add(ClassDef(
    "paladin", "Paladin", ("STR", "CHA"), 8,
    [0, 2750, 5500, 11000, 22000, 44000, 90000, 180000, 300000, 420000, 540000, 660000, 780000, 900000],
    _titles(["Bulwark", "Warder", "Defender", "Protector", "Guardian", "Sentinel", "Justiciar", "Paladin",
             "Paladin Lord"], "Paladin Lord", "Lord Protector"),
    "fighter", "fighter", FIGHTER_SAVES, WeaponProficiency(categories=("swords", "spears")),
    "heavy", ALL_STYLES, 2, damage_bonus="melee", cleave="level",
    notes="Aura of Protection: +1 AC and saves vs. evil creatures (situational)."))
_add(ClassDef(
    "priestess", "Priestess", ("WIL", "CHA"), 4, XP_PRIESTESS,
    _titles(["Novice", "Daughter", "Sister-Initiate", "Sister", "Sister-Disciple", "Priestess", "Mother",
             "Revered Mother", "Matriarch"], "Matriarch", "High Priestess"),
    "mage", "thief", CRUSADER_SAVES, CASTER_WEAPONS, "none", {"single", "missile", "two_handed"}, 1,
    cleave="none"))
_add(ClassDef(
    "shaman", "Shaman", ("WIL", "CON"), 6, XP_CRUSADER,
    _titles(["Spirit Whisperer", "Village Healer", "Tribal Priest", "Medicine Man", "Totem Bearer",
             "Witch Doctor", "Spirit Walker", "Tribal Elder", "Shaman"], "Shaman", "Grandfather of Totems"),
    "thief", "thief", CRUSADER_SAVES,
    WeaponProficiency(weapons=("dagger", "silver_dagger", "hand_axe", "short_sword", "staff_sling", "staff",
                               "spear")),
    "light", {"single", "missile", "weapon_and_shield", "two_handed"}, 1))
_add(ClassDef(
    "warlock", "Warlock", ("INT", "WIL"), 4, XP_MAGE,
    _titles(["Medium", "Occultist", "Spiritualist", "Hexgiver", "Cursebringer", "Maleficus", "Infernalist",
             "Warlock", "Dread Lord"], "Dread Lord", "Dread King"),
    "mage", "mage", MAGE_SAVES,
    WeaponProficiency(weapons=("dagger", "silver_dagger", "dart", "staff", "whip")),
    "none", {"single", "missile", "two_handed"}, 1, cleave="none"))
_add(ClassDef(
    "witch", "Witch", ("INT", "WIL"), 4, XP_PRIESTESS,
    _titles(["Initiate", "Seeress", "Siren", "Pythoness", "Sibyl", "Enchantress", "Sorceress", "Incantrix",
             "Witch"], "Witch", "Witch Queen"),
    "mage", "thief", CRUSADER_SAVES, CASTER_WEAPONS, "none", {"single", "missile", "two_handed"}, 1,
    cleave="none"))
_add(ClassDef(
    "craftpriest", "Dwarven Craftpriest", ("WIL",), 6,
    [0, 2400, 4800, 9600, 19200, 38400, 75000, 150000, 280000, 410000],
    ["Craft-Catechist", "Craft-Acolyte", "Craft-Priest", "Craft-Curate", "Craft-Vicar", "Craft-Rector",
     "Craft-Prelate", "Craft-Bishop", "Craft-Lord", "Craft-Lord, 10th level"],
    "thief", "thief", {"paralysis": 9, "death": 6, "blast": 13, "implements": 9, "spells": 11},
    WeaponProficiency(categories=("axes", "bludgeons")), "heavy",
    {"single", "missile", "weapon_and_shield", "two_handed"}, 2, requirements={"CON": 9}))
_add(ClassDef(
    "vaultguard", "Dwarven Vaultguard", ("STR",), 8,
    [0, 2200, 4400, 8800, 17600, 35200, 70000, 140000, 270000, 400000, 530000, 660000, 790000],
    _titles(["Sentry", "Warden", "Shieldbearer", "Defender", "Sentinel", "Guardian", "Champion", "Vaultguard",
             "Vaultlord"], "Vaultlord", "Vaultlord, 13th level", count=13),
    "fighter", "fighter", {"paralysis": 9, "death": 10, "blast": 12, "implements": 12, "spells": 13},
    WeaponProficiency(all=True, excluded=("long_bow", "two_handed_sword")), "heavy", ALL_STYLES, 3,
    requirements={"CON": 9}, damage_bonus="all", cleave="level"))
_add(ClassDef(
    "nightblade", "Elven Nightblade", ("DEX", "INT"), 6,
    [0, 2875, 5750, 11500, 23000, 46000, 90000, 180000, 330000, 480000, 630000],
    ["Arcanist-Avenger", "Seer-Enforcer", "Theurgist-Torturer", "Magician-Slayer", "Thaumaturge-Destroyer",
     "Enchanter-Executioner", "Sorcerer-Blackguard", "Mage-Assassin", "Nightblade", "Nightblade, 10th level",
     "Nightblade, 11th level"],
    "thief", "thief", {"paralysis": 12, "death": 13, "blast": 13, "implements": 14, "spells": 14},
    SKIRMISHER_WEAPONS, "light", {"single", "missile", "dual", "two_handed"}, 2,
    first_level_hp_bonus=1, backstab=True))
_add(ClassDef(
    "spellsword", "Elven Spellsword", ("STR", "INT"), 6,
    [0, 4000, 8000, 16000, 32000, 64000, 130000, 260000, 430000, 600000],
    ["Arcanist-Guardian", "Warrior-Seer", "Theurgist-Swordmaster", "Magician-Hero", "Thaumaturge-Exemplar",
     "Myrmidon-Enchanter", "Sorcerer-Champion", "Epic Hero-Mage", "Wizard-Lord", "Wizard-Lord, 10th level"],
    "fighter", "fighter", {"paralysis": 12, "death": 14, "blast": 15, "implements": 16, "spells": 16},
    ALL_WEAPONS, "heavy", ALL_STYLES, 2, first_level_hp_bonus=1,
    damage_bonus="all", damage_bonus_levels=(1, 3, 6, 9), cleave="level"))
_add(ClassDef(
    "wonderworker", "Nobiran Wonderworker", ("INT", "WIL"), 4,
    [0, 3125, 6250, 12500, 25000, 50000, 100000, 200000, 390000, 580000, 770000, 960000],
    ["Divine Arcanist", "Divine Seer", "Divine Theurgist", "Divine Magician", "Divine Thaumaturge",
     "Divine Enchanter", "Divine Sorcerer", "Divine Mage", "Divine Wizard", "Divine Wizard, 10th level",
     "Divine Wizard, 11th level", "Divine Wizard, 12th level"],
    "mage", "mage", {"paralysis": 11, "death": 11, "blast": 13, "implements": 9, "spells": 10},
    CASTER_WEAPONS, "none", {"single", "missile", "two_handed"}, 1,
    requirements={a: 11 for a in ATTRIBUTES}, first_level_hp_bonus=1, cleave="none"))
_add(ClassDef(
    "ruinguard", "Zaharan Ruinguard", ("STR", "INT"), 6,
    [0, 3700, 7400, 14800, 29600, 59200, 120000, 240000, 410000, 580000, 750000, 920000],
    ["Insignificant", "Ruinborn", "Ruinchild", "Son of Ruin", "Ruinwielder", "Ruinscourge", "Ruinmaster",
     "Father of Ruin", "Lord of Ruin", "Lord of Secrets", "Lord of Bindings", "Prince of Ruin"],
    "fighter", "fighter", {"paralysis": 11, "death": 12, "blast": 13, "implements": 14, "spells": 15},
    WeaponProficiency(weapons=("battle_axe", "great_axe", "flail", "sword", "two_handed_sword", "whip")),
    "heavy", {"single", "missile", "weapon_and_shield", "two_handed"}, 2,
    requirements={"INT": 9, "WIL": 9, "CHA": 9}, damage_bonus="ruinguard", cleave="level"))


# Revised Rulebook spell progressions: castings per day of spell levels 1..6, by class level.
_MAGE = [[1], [2], [2, 1], [2, 2], [2, 2, 1], [2, 2, 2], [3, 2, 2, 1], [3, 3, 2, 2], [3, 3, 3, 2, 1],
         [3, 3, 3, 3, 2], [4, 3, 3, 3, 2, 1], [4, 4, 3, 3, 3, 2], [4, 4, 4, 3, 3, 2], [4, 4, 4, 4, 3, 3]]
_PRIESTESS = [[2], [3], [3, 2], [3, 3], [3, 3, 2], [3, 3, 3], [5, 3, 3, 2], [5, 5, 3, 3], [5, 5, 5, 3, 2],
              [5, 5, 5, 5, 3], [6, 5, 5, 5, 3, 2], [6, 6, 5, 5, 5, 3], [6, 6, 6, 5, 5, 3], [6, 6, 6, 6, 5, 5]]
_HALF_CASTER = [[], [1], [2], [2], [2, 1], [2, 2], [2, 2, 1], [2, 2, 2, 1], [3, 2, 2, 1], [3, 2, 2, 2],
                [3, 2, 2, 2, 1], [4, 3, 3, 2, 1]]

RULEBOOK_SPELLS: dict[str, dict] = {
    "mage": {"slots": {"Arcane": _MAGE}},
    "warlock": {"slots": {"Arcane": _MAGE}},
    "crusader": {"slots": {"Divine": _MAGE}},
    "bladedancer": {"slots": {"Divine": _MAGE}},
    "shaman": {"slots": {"Divine": _MAGE}},
    "priestess": {"slots": {"Divine": _PRIESTESS}},
    "witch": {"slots": {"Divine": _PRIESTESS}},
    "craftpriest": {"slots": {"Divine": _MAGE[:10]}},
    "spellsword": {"slots": {"Arcane": _MAGE[:10]}},
    "nightblade": {"slots": {"Arcane": _HALF_CASTER[:11]}},
    "ruinguard": {"slots": {"Arcane": _HALF_CASTER[:12]}},
    "wonderworker": {"slots": {"Arcane": _MAGE[:12], "Divine": _MAGE[:12]}},
}

for _key, _table in RULEBOOK_SPELLS.items():
    CLASSES[_key].spells = _table


# Barbarian regional combat proficiencies
BARBARIAN_REGIONS: dict[str, dict] = {
    "jutland": {
        "label": "Jutland",
        "weapons": ("battle_axe", "dagger", "silver_dagger", "great_axe", "hand_axe", "javelin", "short_bow",
                    "spear", "sword", "two_handed_sword", "warhammer"),
        "styles": {"weapon_and_shield", "two_handed"},
        "natural": ["Climbing", "Seafaring"],
    },
    "skysostan": {
        "label": "Skysostan",
        "weapons": ("composite_bow", "dagger", "silver_dagger", "hand_axe", "javelin", "lance", "short_bow",
                    "short_sword", "sling", "spear", "whip"),
        "styles": {"dual", "weapon_and_shield"},
        "natural": ["Precise Shooting", "Riding"],
    },
    "ivory": {
        "label": "Ivory Kingdoms",
        "weapons": ("bola", "club", "dart", "dagger", "silver_dagger", "hand_axe", "javelin", "net", "short_bow",
                    "short_sword", "spear"),
        "styles": {"dual", "weapon_and_shield"},
        "natural": ["Running", "Endurance"],
    },
}


# ---------------------------------------------------------------------------
# Weapons, armor and gear
# ---------------------------------------------------------------------------

SIXTH = Fraction(1, 6)


@dataclass
class WeaponDef:
    key: str
    name: str
    category: str                      # axes, bludgeons, bows, swords, spears, other
    size: str | None                   # tiny/small/medium/large; None = missile-only
    damage: str                        # one-handed (or only) damage
    damage_2h: str | None = None       # two-handed damage for medium weapons
    missile: bool = False              # can make missile attacks
    thrown: bool = False
    ranges: tuple[int, int, int] | None = None
    enc: Fraction = SIXTH
    handy: bool = False
    special: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def melee(self) -> bool:
        return self.size is not None


WEAPONS: dict[str, WeaponDef] = {w.key: w for w in [
    WeaponDef("arbalest", "Arbalest", "bows", None, "1d8", missile=True, ranges=(180, 360, 480),
              enc=Fraction(1), handy=True, special="Cleave 2, Handy, Slow"),
    WeaponDef("crossbow", "Crossbow", "bows", None, "1d6", missile=True, ranges=(140, 280, 420),
              handy=True, special="Cleave 2, Handy, Slow"),
    WeaponDef("composite_bow", "Composite Bow", "bows", None, "1d6", missile=True, ranges=(120, 240, 360),
              enc=Fraction(1), special="Cleave 3 + STR mod"),
    WeaponDef("long_bow", "Long Bow", "bows", None, "1d6", missile=True, ranges=(120, 240, 360),
              enc=Fraction(1), special="Cleave 3 + STR mod", aliases=("longbow",)),
    WeaponDef("short_bow", "Short Bow", "bows", None, "1d6", missile=True, ranges=(75, 150, 300),
              aliases=("shortbow",)),
    WeaponDef("battle_axe", "Battle Axe", "axes", "medium", "1d6", "1d8",
              aliases=("bearded axe", "battle ax")),
    WeaponDef("great_axe", "Great Axe", "axes", "large", "1d10", enc=Fraction(1)),
    WeaponDef("hand_axe", "Hand Axe", "axes", "small", "1d6", missile=True, thrown=True, ranges=(15, 30, 45),
              special="Thrown", aliases=("francisca", "throwing axe", "tomahawk")),
    WeaponDef("club", "Club", "bludgeons", "tiny", "1d4"),
    WeaponDef("flail", "Flail", "bludgeons", "medium", "1d6", "1d8", aliases=("ball-and-chain",)),
    WeaponDef("mace", "Mace", "bludgeons", "medium", "1d6", "1d8"),
    WeaponDef("morning_star", "Morning Star", "bludgeons", "large", "1d10", enc=Fraction(1),
              aliases=("morningstar",)),
    WeaponDef("warhammer", "Warhammer", "bludgeons", "small", "1d6", missile=True, thrown=True,
              ranges=(15, 30, 45), special="Thrown", aliases=("war hammer",)),
    WeaponDef("knife", "Knife", "swords", "tiny", "1d3", missile=True, thrown=True, ranges=(15, 30, 45),
              special="Thrown"),
    WeaponDef("dagger", "Dagger", "swords", "tiny", "1d4", missile=True, thrown=True, ranges=(15, 30, 45),
              special="Thrown"),
    WeaponDef("silver_dagger", "Silver Dagger", "swords", "tiny", "1d4", missile=True, thrown=True,
              ranges=(15, 30, 45), special="Silver, Thrown"),
    WeaponDef("short_sword", "Short Sword", "swords", "small", "1d6", aliases=("scimitar", "gladius")),
    WeaponDef("sword", "Sword", "swords", "medium", "1d6", "1d8", aliases=("longsword", "long sword")),
    WeaponDef("two_handed_sword", "Two-Handed Sword", "swords", "large", "1d10", enc=Fraction(1),
              aliases=("greatsword", "great sword")),
    WeaponDef("dart", "Dart (5)", "spears", None, "1d4", missile=True, thrown=True, ranges=(15, 45, 75),
              special="Thrown", aliases=("darts",)),
    WeaponDef("javelin", "Javelin", "spears", "small", "1d6", missile=True, thrown=True, ranges=(30, 60, 120),
              special="Thrown"),
    WeaponDef("lance", "Lance", "spears", "large", "1d10", enc=Fraction(1), special="Impact, Long, Mounted"),
    WeaponDef("polearm", "Polearm", "spears", "large", "1d10", enc=Fraction(1), special="Impact, Long",
              aliases=("glaive", "halberd", "pike", "bill")),
    WeaponDef("spear", "Spear", "spears", "medium", "1d6", "1d8", missile=True, thrown=True,
              ranges=(30, 60, 120), enc=Fraction(1), special="Impact, Long, Thrown"),
    WeaponDef("bola", "Bola", "other", None, "1d2", missile=True, thrown=True, ranges=(15, 30, 45),
              special="Entangling, Thrown"),
    WeaponDef("military_oil", "Military Oil", "other", None, "1d8", missile=True, thrown=True,
              ranges=(15, 45, 75), special="Thrown"),
    WeaponDef("cestus", "Cestus", "other", "small", "1d3"),
    WeaponDef("net", "Net", "other", "medium", "0", missile=True, thrown=True, ranges=(10, 15, 20),
              enc=Fraction(1), special="Entangling, Thrown (no damage)"),
    WeaponDef("rock", "Rock", "other", "medium", "1d3", missile=True, thrown=True, ranges=(15, 30, 45),
              special="Thrown"),
    WeaponDef("sap", "Sap", "other", "tiny", "1d4", special="Incapacitating"),
    WeaponDef("sling", "Sling", "other", None, "1d4", missile=True, ranges=(60, 120, 240), handy=True,
              special="Handy"),
    WeaponDef("staff_sling", "Staff Sling", "other", "medium", "1d4", "1d6", missile=True, ranges=(75, 150, 300),
              enc=Fraction(1), aliases=("sling-staff", "staff-sling")),
    WeaponDef("staff", "Staff", "other", "medium", "1d4", "1d6", enc=Fraction(1),
              aliases=("quarterstaff", "walking staff")),
    WeaponDef("whip", "Whip", "other", "small", "1d2", special="Flexible", aliases=("scourge",)),
]}


@dataclass
class ArmorDef:
    key: str
    name: str
    category: str      # very light, light, medium, heavy, shield
    ac: int
    enc: Fraction
    special: str = ""
    aliases: tuple[str, ...] = ()


ARMORS: dict[str, ArmorDef] = {a.key: a for a in [
    ArmorDef("hide", "Hide and Fur Armor", "very light", 1, Fraction(1), aliases=("hide armor", "fur armor")),
    ArmorDef("padded", "Padded Armor", "very light", 1, Fraction(1)),
    ArmorDef("leather", "Leather Armor", "light", 2, Fraction(2)),
    ArmorDef("arena_light", "Arena Armor, Light", "light", 2, Fraction(2), "Revealing",
             aliases=("light arena armor",)),
    ArmorDef("ring_mail", "Ring Mail", "medium", 3, Fraction(3), aliases=("ring mail armor",)),
    ArmorDef("scale", "Scale Armor", "medium", 3, Fraction(3)),
    ArmorDef("chain_mail", "Chain Mail Armor", "medium", 4, Fraction(4), aliases=("chainmail", "chain mail")),
    ArmorDef("laminated_linen", "Laminated Linen Armor", "medium", 4, Fraction(4)),
    ArmorDef("arena_heavy", "Arena Armor, Heavy", "medium", 4, Fraction(4), "Revealing",
             aliases=("heavy arena armor",)),
    ArmorDef("banded_plate", "Banded Plate Armor", "heavy", 5, Fraction(5), aliases=("banded plate",)),
    ArmorDef("lamellar", "Lamellar Armor", "heavy", 5, Fraction(5)),
    ArmorDef("plate", "Plate Armor", "heavy", 6, Fraction(6), "Scarce", aliases=("plate armour",)),
    ArmorDef("shield", "Shield", "shield", 1, Fraction(1)),
    ArmorDef("mirror_shield", "Shield, Mirror", "shield", 1, Fraction(1)),
]}

# Matching order matters: try longer / more specific names first.
_ARMOR_MATCH_ORDER = ["arena_light", "arena_heavy", "banded_plate", "laminated_linen", "chain_mail", "ring_mail",
                      "lamellar", "scale", "padded", "hide", "leather", "plate", "mirror_shield", "shield"]


def _has_word(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?:e?s)?(?![a-z])", text) is not None


def find_weapon(text: str) -> WeaponDef | None:
    t = text.lower()
    if _has_word(t, "two-handed") and "sword" in t:
        return WEAPONS["two_handed_sword"]
    best: tuple[int, WeaponDef] | None = None
    for w in WEAPONS.values():
        for n in (w.name.lower().replace(" (5)", ""), w.key.replace("_", " "), *w.aliases):
            if n and _has_word(t, n) and (best is None or len(n) > best[0]):
                best = (len(n), w)
    return best[1] if best else None


def find_armor(text: str) -> ArmorDef | None:
    t = text.lower()
    for key in _ARMOR_MATCH_ORDER:
        a = ARMORS[key]
        names = [a.name.lower(), key.replace("_", " "), *a.aliases]
        if key == "leather":
            names = ["leather armor", "leather armour"]
        if key == "hide":
            names = ["hide armor", "hide and fur", "fur armor"]
        if key == "plate":
            names = ["plate armor", "plate armour", "plate mail"]
        if key == "scale":
            names = ["scale armor", "scale mail"]
        if key == "shield":
            names = ["shield"]
        if any(n in t for n in names):
            return a
    return None


def lookup_weapon(key_or_name: str) -> WeaponDef | None:
    if key_or_name in WEAPONS:
        return WEAPONS[key_or_name]
    return find_weapon(key_or_name)


def lookup_armor(key_or_name: str) -> ArmorDef | None:
    if key_or_name in ARMORS:
        return ARMORS[key_or_name]
    return find_armor(key_or_name)


# (keywords, stone per unit, units per bundle). First match wins.
GEAR_WEIGHTS: list[tuple[tuple[str, ...], Fraction, int]] = [
    (("iron rations", "standard rations", "rations"), Fraction(1), 1),
    (("torch",), Fraction(1), 6),
    (("iron spike",), SIXTH, 6),
    (("sling stone",), SIXTH, 30),
    (("arrow",), SIXTH, 20),
    (("bolt",), SIXTH, 20),
    (("rope",), Fraction(1), 1),
    (("miner's helm",), Fraction(1), 1),
    (("brewer's lab",), Fraction(1), 1),
    (("lantern",), Fraction(1), 1),
    (("laborer's tools", "craftsman's tools", "surgical saw, large"), Fraction(1), 1),
    (("blanket", "bedroll"), Fraction(1), 1),
    (("10' pole", "wooden pole"), Fraction(1), 1),
    (("saddle and tack", "riding saddle"), Fraction(1), 1),
    (("tent, small", "small tent"), Fraction(1), 1),
    (("banner",), Fraction(1), 1),
    (("musical instrument", "lyre", "harp", "lute", "drum"), Fraction(1), 1),
    (("spellbook", "spell book", "prayer book", "holy book", "grimoire"), Fraction(1, 2), 1),
]

# Worn items weigh 0 stone.
CLOTHING_WORDS = ("tunic", "pants", "dress", "robe", "cassock", "chiton", "belt", "girdle", "sash", "boots",
                  "shoes", "sandals", "gloves", "cloak", "loincloth", "breastwrap", "veil", "hat", "skullcap",
                  "gown", "arm-bands", "amulet", "ring", "necklace", "clothes", "outfit", "kilt", "toga",
                  "caparison", "headdress", "head dress", "circlet", "jewelry", "earrings", "bracelets")
# Things that travel on their own legs.
NOT_CARRIED_WORDS = ("horse", "mule", "pony", "camel", "familiar", "totem animal", "warhorse", "donkey", "cart")


# ---------------------------------------------------------------------------
# Encumbrance and speed
# ---------------------------------------------------------------------------

COINS_PER_STONE = 1000
COIN_TYPES = ["pp", "gp", "ep", "sp", "cp"]
COIN_VALUES_GP = {"pp": Fraction(5), "gp": Fraction(1), "ep": Fraction(1, 2), "sp": Fraction(1, 10),
                  "cp": Fraction(1, 100)}


def speed_for(enc: Fraction, strength_mod: int) -> tuple[int, str]:
    """Return (exploration speed in feet/turn, band label) for a given load."""
    if enc <= 5:
        return 120, "Unencumbered"
    if enc <= 7:
        return 90, "Lightly encumbered"
    if enc <= 10:
        return 60, "Heavily encumbered"
    if enc <= 20 + strength_mod:
        return 30, "Severely encumbered"
    return 0, "Overloaded"


def fmt_stone(st: Fraction) -> str:
    st = Fraction(st).limit_denominator(1000)
    if (st * 6).denominator == 1:
        whole, sixths = divmod(int(st * 6), 6)
        if sixths == 0:
            return f"{whole} st"
        return f"{whole} {sixths}/6 st" if whole else f"{sixths}/6 st"
    return f"{float(st):.2f} st"


# ---------------------------------------------------------------------------
# Animals
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnimalPreset:
    key: str
    name: str
    speed: int              # exploration speed (feet/turn) at normal load or less
    normal_load: int        # stone
    max_load: int
    food: Fraction          # stone per day
    water: Fraction
    size: str = "large"     # barding size
    note: str = ""


# Animal/Vehicle Speed and Encumbrance and the animal food & water table (RR pp. 161-162, 277)
ANIMAL_PRESETS: dict[str, AnimalPreset] = {p.key: p for p in [
    AnimalPreset("camel", "Camel", 150, 30, 60, Fraction(3), Fraction(6),
                 note="Desert dromedary: never dehydrated unless without water for more than six months."),
    AnimalPreset("dog_hunting", "Dog, hunting", 180, 2, 4, Fraction(1, 5), Fraction(2, 5), "man-sized",
                 "Scent: equivalent of Tracking 3 (sight hounds can't track but have 240' speed)."),
    AnimalPreset("dog_war", "Dog, war", 150, 6, 12, Fraction(3, 5), Fraction(6, 5), "man-sized"),
    AnimalPreset("donkey", "Donkey", 120, 15, 30, Fraction(3, 2), Fraction(3),
                 note="Efficient grazer; sure-footed (mountains ×2/3); freezes rather than flees when afraid."),
    AnimalPreset("elephant", "Elephant", 120, 180, 360, Fraction(18), Fraction(36), "gigantic"),
    AnimalPreset("horse_heavy", "Horse, heavy", 150, 40, 80, Fraction(4), Fraction(8)),
    AnimalPreset("horse_light", "Horse, light", 240, 20, 40, Fraction(2), Fraction(4)),
    AnimalPreset("horse_medium", "Horse, medium", 180, 30, 60, Fraction(3), Fraction(6)),
    AnimalPreset("horse_steppe", "Horse, steppe", 210, 25, 40, Fraction(2), Fraction(4),
                 note="Efficient grazer; can force march one day without penalty (+1 day per CON bonus)."),
    AnimalPreset("mule", "Mule", 150, 25, 50, Fraction(5, 2), Fraction(5),
                 note="Sure-footed (mountains ×2/3)."),
    AnimalPreset("ox", "Ox", 120, 45, 90, Fraction(9, 2), Fraction(9), note="Efficient grazer."),
]}

ANIMAL_SIZES = ["man-sized", "large", "huge", "gigantic", "colossal"]
# barding is sized for large creatures; others multiply its weight (RR p. 141)
BARDING_SIZE_FACTOR = {"man-sized": Fraction(2, 3), "large": Fraction(1), "huge": Fraction(3),
                       "gigantic": Fraction(12), "colossal": Fraction(60)}
# material: (AC bonus, encumbrance for a large creature)
BARDING = {"leather": (1, Fraction(3, 2)), "scale": (2, Fraction(3)), "chain": (3, Fraction(9, 2)),
           "lamellar": (4, Fraction(6)), "plate": (5, Fraction(15, 2))}
ANIMAL_FEED_SP_PER_STONE = 2   # feed for working animals


def barding_weight(material: str, size: str, half: bool = False) -> Fraction:
    w = BARDING[material][1] * BARDING_SIZE_FACTOR[size]
    return w / 2 if half else w


def monster_attack_throw(hd: str) -> int:
    """Attack throw value by Hit Dice (RR p. 296): '1/2' 12+, '1-1' 11+, '1' 10+ ... '20' -9+.
    A hp bonus ('2+1') rounds HD up."""
    whole, frac, bonus = parse_hd(hd)
    if frac or whole == 0:
        return 12
    if bonus < 0:
        return 11 if whole == 1 else 11 - whole
    return max(-9, 11 - whole - (1 if bonus > 0 else 0))


def parse_hd(hd: str) -> tuple[int, bool, int]:
    """'3+1' -> (3, False, 1); '1/2' -> (0, True, 0). Asterisks (special abilities) are ignored."""
    m = re.fullmatch(r"\s*(\d+)\s*(/\s*2)?\s*(?:([+-])\s*(\d+))?\s*\**\s*", hd or "")
    if not m:
        raise ValueError(f"Hit Dice should look like `2`, `1/2`, `3+1`, or `1-1`, not `{hd}`.")
    bonus = int(m.group(4) or 0) * (-1 if m.group(3) == "-" else 1)
    return (0 if m.group(2) else int(m.group(1))), bool(m.group(2)), bonus


# ---------------------------------------------------------------------------
# Proficiencies
# ---------------------------------------------------------------------------

def _load_json(name: str) -> dict:
    path = DATA_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


PROFICIENCY_LISTS: dict[str, list[str]] = _load_json("proficiencies.json")
TEMPLATES: dict[str, list[dict]] = _load_json("templates.json")


def all_proficiency_names() -> list[str]:
    names: set[str] = set()
    for lst in PROFICIENCY_LISTS.values():
        for n in lst:
            names.add(n.split(" (")[0])
    names.update(["Weapon Finesse", "Ambushing", "Goblin-Slaying", "Kin-Slaying", "Vermin-Slaying",
                  # Before All Others
                  "Dendromantic Cultivation", "Elven Weapons Training", "Human Bloodline", "Long Range Volleying",
                  "Memory Palace", "Sylvan Woodcraft",
                  # By This Axe
                  "Inventing", "Jury-Rigging", "Mechanical Engineering", "Personal Talisman", "Scavenging",
                  "Tinkering", "Prospecting", "Reliquarianism", "Sniping"])
    return sorted(names)


def normalize(s: str) -> str:
    return " ".join(s.lower().replace(".", "").split())


def proficiency_matches(prof: str, *needles: str) -> bool:
    """Case-, period- and hyphen-insensitive: 'Blind-Fighting' matches 'blind fighting'."""
    p = normalize(prof).replace("-", " ")
    return all(normalize(n).replace("-", " ") in p for n in needles)


STYLE_KEYWORDS = {
    "weapon_and_shield": ("shield",),
    "two_handed": ("two-handed", "two handed", "2h"),
    "dual": ("dual",),
    "missile": ("missile",),
    "single": ("single",),
}

# Weapon Focus / Martial Training groups -> predicate over WeaponDef
WEAPON_GROUPS: dict[str, tuple[tuple[str, ...], callable]] = {
    "axes": (("axe",), lambda w: w.category == "axes"),
    "bludgeons": (("mace", "flail", "hammer"), lambda w: w.key in ("mace", "flail", "warhammer", "morning_star")),
    "swords": (("sword", "dagger"), lambda w: w.category == "swords"),
    "bows": (("bow", "crossbow"), lambda w: w.category == "bows"),
    "spears": (("spear", "polearm"), lambda w: w.category == "spears" and w.key != "dart"),
    "slings_thrown": (("sling", "thrown"), lambda w: w.key in ("sling", "staff_sling") or w.thrown),
    "misc": (("bola", "net", "sap", "staff"), lambda w: w.key in ("bola", "net", "sling", "sap", "staff",
                                                                     "staff_sling")),
}


def weapon_groups_in(prof: str) -> list[str]:
    """Which weapon groups a 'Weapon Focus (...)' or 'Martial Training (...)' string names."""
    p = normalize(prof)
    inner = p[p.find("(") + 1:] if "(" in p else ""
    found = []
    for group, (words, _) in WEAPON_GROUPS.items():
        if any(w in inner for w in words):
            found.append(group)
    return found


def weapon_in_group(weapon: WeaponDef, group: str) -> bool:
    return WEAPON_GROUPS[group][1](weapon)


# ---------------------------------------------------------------------------
# Supplement classes (acks/data/classes/*.json)
# ---------------------------------------------------------------------------

SOURCES: list[str] = ["Revised Rulebook"]
SAVE_KEYS = ("attack", "paralysis", "death", "blast", "implements", "spells")


def validate_class_json(raw: dict) -> list[str]:
    """Problems that would make a supplement class unusable (empty list = fine)."""
    problems = []
    for f in ("key", "name", "source", "key_attributes", "hit_die", "levels", "weapons", "armor", "styles"):
        if f not in raw:
            problems.append(f"missing {f}")
    if problems:
        return problems
    levels = raw["levels"]
    if not levels:
        problems.append("no levels")
    for i, row in enumerate(levels, 1):
        for k in SAVE_KEYS + ("xp",):
            if not isinstance(row.get(k), int):
                problems.append(f"level {i}: {k} is {row.get(k)!r}")
    xps = [r.get("xp") for r in levels]
    if all(isinstance(x, int) for x in xps) and xps != sorted(xps):
        problems.append("xp not increasing")
    if raw["armor"] not in ARMOR_RANKS:
        problems.append(f"armor {raw['armor']!r}")
    for a in list(raw["key_attributes"]) + list(raw.get("requirements", {})):
        if a not in ATTRIBUTES:
            problems.append(f"attribute {a!r}")
    for k in raw["weapons"].get("weapons", []) + raw["weapons"].get("excluded", []):
        if k not in WEAPONS:
            problems.append(f"weapon {k!r}")
    for s in raw["styles"]:
        if s not in STYLES:
            problems.append(f"style {s!r}")
    choice = raw.get("style_choice")
    if choice:
        opts = choice.get("options", [])
        if any(s not in raw["styles"] for s in opts) or not 0 < choice.get("pick", 0) < len(opts):
            problems.append("style_choice")
    if raw.get("damage_bonus_applies_to", "none") not in ("all", "melee", "missile", "none"):
        problems.append("damage_bonus_applies_to")
    if raw.get("cleave", "half") not in ("level", "half", "none"):
        problems.append("cleave")
    return problems


def class_from_json(raw: dict) -> ClassDef:
    levels = raw["levels"]
    wp = raw["weapons"]
    return ClassDef(
        key=raw["key"], name=raw["name"], key_attributes=tuple(raw["key_attributes"]), hit_die=int(raw["hit_die"]),
        xp=[int(r["xp"]) for r in levels], titles=[r.get("title") or f"Level {i}" for i, r in enumerate(levels, 1)],
        attack_prog="fighter", save_prog="fighter", save_base={s: levels[0][s] for s in SAVES},
        weapons=WeaponProficiency(all=bool(wp.get("all")), missile_all=bool(wp.get("missile_all")),
                                  melee_sizes=tuple(wp.get("melee_sizes", [])),
                                  categories=tuple(wp.get("categories", [])), weapons=tuple(wp.get("weapons", [])),
                                  excluded=tuple(wp.get("excluded", []))),
        armor=raw["armor"], styles=set(raw["styles"]) | {"single", "missile"},
        hp_after_9=int(raw.get("hp_after_9") or 0), requirements=dict(raw.get("requirements") or {}),
        first_level_hp_bonus=int(raw.get("first_level_hp_bonus") or 0),
        damage_bonus=raw.get("damage_bonus_applies_to", "none"), cleave=raw.get("cleave", "half"),
        backstab=bool(raw.get("backstab")), ambush=bool(raw.get("ambush")),
        weapon_finesse=bool(raw.get("weapon_finesse")), animal_reflexes=bool(raw.get("animal_reflexes")),
        notes=raw.get("notes", ""), source=raw["source"], level_table=levels,
        ac_bonus_condition=raw.get("ac_bonus_condition"), ac_bonus_label=raw.get("ac_bonus_label", "class power"),
        spells=raw.get("spells"), style_choice=raw.get("style_choice"))


def style_choices(c: ClassDef) -> list[tuple[str, ...]]:
    """Every allowed pick for a class with a style choice, e.g. [("dual",), ("weapon_and_shield",)]."""
    if not c.style_choice:
        return []
    return list(itertools.combinations(c.style_choice["options"], c.style_choice["pick"]))


def style_choice_label(picks) -> str:
    return " + ".join(STYLE_LABELS[s] for s in picks)


def describe_styles(c: ClassDef) -> str:
    """Class styles for display, e.g. 'Two-handed weapon; choose 1 of Dual weapon or Weapon and shield'."""
    choice = set(c.style_choice["options"]) if c.style_choice else set()
    fixed = ", ".join(STYLE_LABELS[s] for s in STYLES if s in c.styles and s not in choice)
    if not choice:
        return fixed
    opts = " or ".join(STYLE_LABELS[s] for s in STYLES if s in choice)
    return f"{fixed}; choose {c.style_choice['pick']} of {opts}"


def load_supplement_classes(folder: Path = DATA_DIR / "classes") -> dict[str, list[str]]:
    """Load every class file in the folder. Returns {class key: problems} for any that were skipped."""
    skipped: dict[str, list[str]] = {}
    for path in sorted(folder.glob("*.json")):
        for raw in json.loads(path.read_text(encoding="utf-8")):
            problems = validate_class_json(raw)
            if problems:
                skipped[raw.get("key", path.name)] = problems
                continue
            c = class_from_json(raw)
            CLASSES[c.key] = c
            TEMPLATES[c.key] = raw.get("templates", [])
            PROFICIENCY_LISTS[c.key] = raw.get("proficiency_list", [])
            if c.source not in SOURCES:
                SOURCES.append(c.source)
    return skipped


SKIPPED_CLASSES = load_supplement_classes()


def classes_by_source(source: str) -> list[ClassDef]:
    return [c for c in CLASSES.values() if c.source == source]


# ---------------------------------------------------------------------------
# Homebrew weapons and armor (item["custom"] overrides, optionally on top of a catalog base)
# ---------------------------------------------------------------------------

DICE_RE = re.compile(r"^\d{0,2}d\d{1,3}$")
WEAPON_SIZES = ["tiny", "small", "medium", "large", "missile"]


def parse_custom_stats(damage: str | None = None, size: str | None = None, weapon_type: str | None = None,
                       range_text: str | None = None, thrown: bool | None = None, armor_ac: int | None = None,
                       armor_type: str | None = None) -> dict:
    """Validate user-typed stats into an item's "custom" dict. Raises ValueError with a friendly message."""
    custom: dict = {}
    if damage:
        parts = [p.strip().lower() for p in damage.replace(" ", "").split("/")]
        if len(parts) > 2 or not all(DICE_RE.match(p) for p in parts):
            raise ValueError("Damage must be dice like `1d12`, or `1d6/1d8` for one-handed/two-handed. "
                             "Put flat bonuses in `magic` or a `/modifier`.")
        custom["damage"] = parts[0] if parts[0][0] != "d" else "1" + parts[0]
        if len(parts) == 2:
            custom["damage_2h"] = parts[1] if parts[1][0] != "d" else "1" + parts[1]
    if size:
        custom["size"] = size
    if weapon_type:
        custom["category"] = weapon_type
    if range_text:
        nums = [n for n in re.split(r"[^\d]+", range_text) if n]
        if len(nums) != 3:
            raise ValueError("Range must be short/medium/long in feet, e.g. `30/60/120`.")
        rng = [int(n) for n in nums]
        if rng != sorted(rng):
            raise ValueError("Range bands must increase: short/medium/long.")
        custom["ranges"] = rng
    if thrown is not None:
        custom["thrown"] = thrown
    if armor_ac is not None:
        custom["ac"] = armor_ac
    if armor_type:
        custom["armor_type"] = armor_type
    return custom


def is_weapon_custom(custom: dict) -> bool:
    return any(k in custom for k in ("damage", "damage_2h", "size", "category", "ranges", "thrown"))


def is_armor_custom(custom: dict) -> bool:
    return any(k in custom for k in ("ac", "armor_type"))


def custom_weapon(base: WeaponDef | None, custom: dict, name: str) -> WeaponDef:
    from dataclasses import replace
    if base is None:
        size = custom.get("size") or ("missile" if custom.get("ranges") else "medium")
        base = WeaponDef("custom", name, custom.get("category", "other"), None if size == "missile" else size,
                         custom.get("damage", "1d6"))
    changes: dict = {"name": name}
    if "damage" in custom:
        changes["damage"] = custom["damage"]
        changes["damage_2h"] = custom.get("damage_2h")
    if "size" in custom:
        changes["size"] = None if custom["size"] == "missile" else custom["size"]
    if "category" in custom:
        changes["category"] = custom["category"]
    if "ranges" in custom:
        changes["ranges"] = tuple(custom["ranges"])
        changes["missile"] = True
    if "thrown" in custom:
        changes["thrown"] = bool(custom["thrown"])
        if custom["thrown"]:
            changes["missile"] = True
            changes.setdefault("ranges", base.ranges or (15, 30, 45))
    w = replace(base, **changes)
    if w.size is None and not w.missile:
        w = replace(w, missile=True, ranges=w.ranges or (15, 30, 45))
    if w.size not in ("medium",) and "damage_2h" not in custom and "damage" in custom:
        w = replace(w, damage_2h=None)
    return w


def custom_armor(base: ArmorDef | None, custom: dict, name: str) -> ArmorDef:
    from dataclasses import replace
    if base is None:
        cat = custom.get("armor_type", "light")
        ac = int(custom.get("ac", 1))
        base = ArmorDef("custom", name, cat, ac, Fraction(max(ac, 1)) if cat != "shield" else Fraction(1))
    changes: dict = {"name": name}
    if "ac" in custom:
        changes["ac"] = int(custom["ac"])
    if "armor_type" in custom:
        changes["category"] = custom["armor_type"]
    return replace(base, **changes)


# ---------------------------------------------------------------------------
# Class powers by level (acks/data/class_powers.json: {class key: [{level, name, summary}]})
# ---------------------------------------------------------------------------

CLASS_POWERS: dict[str, list[dict]] = {
    k: sorted(v, key=lambda p: int(p["level"])) for k, v in _load_json("class_powers.json").items()}


def class_powers(class_key: str) -> list[dict]:
    return CLASS_POWERS.get(class_key, [])


def power_paths(class_key: str) -> list[str]:
    """Paths a class chooses between (traditions, sects, dark paths, sigils): prefixes used by 2+ powers."""
    counts: dict[str, int] = {}
    for p in class_powers(class_key):
        name = p["name"]
        if ": " in name:
            prefix = name.split(": ", 1)[0]
            if prefix == "Optional":   # picks from a menu, not a path
                continue
            counts[prefix] = counts.get(prefix, 0) + 1
    paths = [k for k, n in counts.items() if n >= 2]
    return paths if len(paths) >= 2 else []


def power_path_of(power: dict, paths: list[str]) -> str | None:
    if ": " in power["name"]:
        prefix = power["name"].split(": ", 1)[0]
        if prefix in paths:
            return prefix
    return None


def is_optional_power(power: dict) -> bool:
    """Powers the class may pick from a menu (e.g. the sporecaster's options) rather than gains outright."""
    return power["name"].startswith("Optional: ")


# ---------------------------------------------------------------------------
# Book-verified corrections for classes defined in code (acks/data/class_overrides.json)
#   {class key: {"fields": {...}, "levels": {"4": {"attack": 8}}, "spells": {...}}}
# ---------------------------------------------------------------------------

def _materialize_levels(c: ClassDef) -> None:
    """Turn a progression-based class into an explicit per-level table so single values can be corrected."""
    if c.level_table:
        return
    rows = []
    for lvl in range(1, c.max_level + 1):
        row = {"level": lvl, "xp": c.xp[lvl - 1], "title": c.title(lvl),
               "attack": 10 - improvements(c.attack_prog, lvl),
               "damage_bonus": sum(1 for x in c.damage_bonus_levels if lvl >= x) if c.damage_bonus != "none" else 0}
        for s in SAVES:
            row[s] = c.save_base[s] - improvements(c.save_prog, lvl)
        rows.append(row)
    c.level_table = rows


def _set_class_field(c: ClassDef, field: str, value) -> None:
    if field == "key_attributes":
        c.key_attributes = tuple(value)
    elif field == "weapons":
        c.weapons = WeaponProficiency(all=bool(value.get("all")), missile_all=bool(value.get("missile_all")),
                                      melee_sizes=tuple(value.get("melee_sizes", [])),
                                      categories=tuple(value.get("categories", [])),
                                      weapons=tuple(value.get("weapons", [])),
                                      excluded=tuple(value.get("excluded", [])))
    elif field == "styles":
        c.styles = set(value) | {"single", "missile"}
    elif field == "hp_after_9":
        c.hp_after_9 = int(value)
    elif field == "damage_bonus_applies_to":
        c.damage_bonus = value
    elif field in ("requirements", "hit_die", "first_level_hp_bonus", "armor", "cleave", "backstab", "ambush",
                   "weapon_finesse", "animal_reflexes", "graceful_fighting", "notes"):
        setattr(c, field, value)
    else:
        raise ValueError(f"unsupported class field override {field!r}")


def apply_class_overrides(data: dict) -> list[str]:
    problems = []
    for key, ov in data.items():
        c = CLASSES.get(key)
        if c is None:
            problems.append(f"unknown class {key}")
            continue
        for fname, value in ov.get("fields", {}).items():
            try:
                _set_class_field(c, fname, value)
            except ValueError as e:
                problems.append(f"{key}: {e}")
        if ov.get("levels"):
            _materialize_levels(c)
            for lvl, changes in ov["levels"].items():
                row = c.level_table[int(lvl) - 1]
                row.update(changes)
                if "xp" in changes:
                    c.xp[int(lvl) - 1] = int(changes["xp"])
                if "title" in changes:
                    c.titles[int(lvl) - 1] = changes["title"]
        if "spells" in ov:
            c.spells = ov["spells"]
    return problems


OVERRIDE_PROBLEMS = apply_class_overrides(_load_json("class_overrides.json"))

# Per-level skill/throw tables (thief skills, listening, dendromancy...): {class key: {skill: [value per level]}}
CLASS_SKILLS: dict[str, dict[str, list]] = _load_json("class_skills.json")


def class_skills(class_key: str) -> dict[str, list]:
    return CLASS_SKILLS.get(class_key, {})
