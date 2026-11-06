"""Class templates: look them up by 3d6 roll and turn their equipment text into items."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

from . import rules, supplies

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "a pair of": 2, "pair of": 2}
CONTAINER_WORDS = ("bowquiver", "pouch", "sack", "bag", "backpack", "purse", "quiver", "case", "satchel", "rucksack")


@dataclass
class ParsedItem:
    name: str
    qty: int
    stone_each: Fraction
    kind: str = "gear"          # gear | weapon | armor | shield | clothing | animal
    base: str | None = None
    known: bool = True          # False: not recognised, so counted as 1 item


@dataclass
class ParsedEquipment:
    items: list[ParsedItem] = field(default_factory=list)
    coins: dict[str, int] = field(default_factory=dict)

    def encumbrance(self) -> Fraction:
        return sum((i.stone_each * i.qty for i in self.items), Fraction(0))


def templates_for(class_key: str) -> list[dict]:
    return rules.TEMPLATES.get(class_key, [])


def template_for_roll(class_key: str, roll: int) -> dict | None:
    for t in templates_for(class_key):
        if t["roll_min"] <= roll <= t["roll_max"]:
            return t
    return None


# Before All Others templates name the fighting style they begin with, as a proficiency entry
# ("Dual Weapons") or in the template name ("Sentinel (Weapon and Shield)").
_STYLE_NAMES = {"dual weapon": "dual", "dual weapons": "dual", "weapon and shield": "weapon_and_shield",
                "two-handed weapon": "two_handed", "two handed weapon": "two_handed"}


def _style_name(text: str) -> str | None:
    return _STYLE_NAMES.get(text.strip().lower())


def template_style(t: dict) -> tuple[list[str], list[str]]:
    """(styles the template begins with, its proficiencies without those style entries)."""
    styles, profs = [], []
    for p in t["proficiencies"]:
        s = _style_name(p)
        if s:
            styles.append(s)
        else:
            profs.append(p)
    m = re.search(r"\(([^)]*)\)\s*$", t["name"])
    if m and _style_name(m.group(1)):
        styles.append(_style_name(m.group(1)))
    return list(dict.fromkeys(styles)), profs


def _split_pieces(text: str) -> list[str]:
    raw = [p.strip() for p in re.split(r",\s*(?![^()]*\))|\.\s+(?=\d)", text) if p.strip()]
    pieces: list[str] = []
    in_book = False
    for p in raw:
        if in_book:
            pieces[-1] += ", " + p
            if p.lower().startswith("and ") or ";" in p:
                in_book = False
            continue
        pieces.append(p)
        low = p.lower()
        if re.search(r"book with", low) and " and " not in low.split("book with", 1)[1]:
            in_book = True
    out: list[str] = []
    for p in pieces:
        out.extend(s.strip() for s in p.split(";") if s.strip())
    return out


def _split_weapon_pairs(piece: str) -> list[str]:
    """'Military-issue spear and short sword' -> two pieces, but leave 'tunic and pants' alone."""
    split = supplies.split_weapon_and_ammo(piece, rules.find_weapon)   # 'sling with 30 sling bullets'
    if split:
        return list(split)
    if " and " not in piece or "book" in piece.lower():
        return [piece]
    left, right = piece.split(" and ", 1)
    if rules.find_weapon(left) and rules.find_weapon(right):
        return [left.strip(), right.strip()]
    return [piece]


def _quantity(piece: str) -> tuple[int, str]:
    low = piece.lower()
    for word, n in WORD_NUMBERS.items():
        if low.startswith(word + " "):
            return n, piece[len(word) + 1:]
    m = re.match(r"(\d+)\s+(?!lb)(.*)", piece)
    if m and not re.match(r"\d+\s*(gp|sp|cp|pp|ep)\b", piece, re.I):
        return int(m.group(1)), m.group(2)
    return 1, piece


def _has(text: str, words) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?:e?s)?(?![a-z])", text) for w in words)


def parse_piece(piece: str) -> ParsedItem | tuple[str, int] | None:
    piece = piece.strip(" .")
    if not piece:
        return None
    low = piece.lower()
    coin = re.match(r"(\d+)\s*(pp|gp|ep|sp|cp)\b", low)
    if coin:
        return coin.group(2), int(coin.group(1))
    qty, rest = _quantity(piece)
    name = rest[0].upper() + rest[1:] if rest else piece
    rlow = rest.lower()

    if _has(rlow, rules.NOT_CARRIED_WORDS):
        return ParsedItem(name, qty, Fraction(0), "animal")
    if re.search(r"(spell|prayer|holy) ?book|grimoire", rlow):
        return ParsedItem(name, qty, Fraction(1, 2))
    s = supplies.recognize(piece)   # rations by the day, arrows/bolts/sling stones one at a time
    if s and s.kind in ("rations", "ammo"):
        return ParsedItem(s.name, s.count, s.each, s.kind, s.base)
    if "shield" in rlow or "armor" in rlow or "armour" in rlow or re.search(r"\bmail\b", rlow):
        a = rules.find_armor(rlow)
        if a:
            return ParsedItem(name, qty, a.enc, "shield" if a.category == "shield" else "armor", a.key)
    if "helmet" in rlow or "helm" in rlow.split():
        return ParsedItem(name, qty, rules.SIXTH)
    if not _has(rlow, ("quiver", "case", "bolts", "arrows", "stones", "holy symbol")):
        w = rules.find_weapon(rlow)
        if w:
            each = w.enc / 5 if w.key == "dart" else w.enc
            return ParsedItem(name, qty, each, "weapon", w.key)
    if not _has(rlow, CONTAINER_WORDS) and _has(rlow, rules.CLOTHING_WORDS):
        return ParsedItem(name, qty, Fraction(0), "clothing")
    if _has(rlow, CONTAINER_WORDS):
        return ParsedItem(name, qty, rules.SIXTH)   # quivers, cases, sacks: one item each
    if re.search(r"(?<![a-z])weeks?(?![a-z])", rlow):
        return ParsedItem(name, qty, Fraction(1))   # a week of food is a heavy item
    for words, stone, bundle in rules.GEAR_WEIGHTS:
        if _has(rlow, words):
            return ParsedItem(name, qty, stone / bundle)
    if "stakes" in rlow:
        return ParsedItem(name, 1, rules.SIXTH)
    return ParsedItem(name, qty, rules.SIXTH, known=False)


def item_weight(name: str) -> tuple[Fraction, bool]:
    """Stone for one of `name`, counted the way templates are, and whether the name was recognised.

    A count in the name is a bundle: 'Quiver with 20 arrows' and '20 arrows' are 1/6 stone, 'Arrows' is
    1/120 (20 to the item). Unrecognised things count as 1 item (1/6 stone).
    """
    parsed = parse_piece(name)
    if not isinstance(parsed, ParsedItem):
        return rules.SIXTH, False
    return parsed.stone_each * parsed.qty, parsed.known


def parse_equipment(text: str) -> ParsedEquipment:
    out = ParsedEquipment()
    for piece in _split_pieces(text):
        for sub in _split_weapon_pairs(piece):
            parsed = parse_piece(sub)
            if parsed is None:
                continue
            if isinstance(parsed, tuple):
                coin, amount = parsed
                out.coins[coin] = out.coins.get(coin, 0) + amount
            else:
                out.items.append(parsed)
    return out


def starting_gold_roll() -> tuple[int, list[int]]:
    """No-template option: 3d6 x 10 gp."""
    from .dice import d
    rolls = [d(6) for _ in range(3)]
    return sum(rolls) * 10, rolls
