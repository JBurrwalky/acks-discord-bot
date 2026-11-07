"""Who has a proficiency, and at what rank: taken proficiencies plus class powers and thief-style skills.

Ranks of a taken proficiency: each repeated entry is a rank, and a number after the name sets it
("Healing 3" is 3 ranks). Class powers count when they name the proficiency ("Alertness"), grant ranks
("One rank of Tracking proficiency", "Equals 3 ranks of Healing", "Gains Seduction proficiency"), or work
"as" it ("as Caving proficiency"). Per-level class skills such as a thief's Lockpicking show their throw.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import embeds, rules
from .character import Character

PARTY_PROFICIENCIES: dict[str, list[str]] = {
    "Survival": ["Survival", "Tracking", "Trapping", "Hunting", "Navigation", "Driving", "Naturalism",
                 "Mountaineering", "Seafaring", "Mapping", "Passing without Trace", "Beast Friendship", "Healing",
                 "Animal Husbandry"],
    "Dungeon": ["Alertness", "Trapfinding", "Lockpicking", "Dungeonbashing Expertise", "Caving"],
    "Social": ["Mystic Aura", "Diplomacy", "Seduction", "Intimidation", "Performance", "Disguise", "Bribery"],
}

# Other spellings that mean the same proficiency
ALIASES = {"dungeonbashing expertise": ["dungeon bashing", "dungeonbashing"]}
# Per-level class skills that stand in for a proficiency (skill name -> proficiency)
SKILL_FOR = {"lockpicking": "Lockpicking", "open locks": "Lockpicking", "find traps": "Trapfinding"}

_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4}


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").replace(".", "").split())


def _names(prof: str) -> list[str]:
    return [_norm(prof)] + ALIASES.get(_norm(prof), [])


@dataclass
class Holding:
    """One character's standing in one proficiency."""
    ranks: int = 0                                         # from the proficiency list
    specs: list[str] = field(default_factory=list)         # "chanting" from "Performance (chanting)"
    class_ranks: int = 0                                   # from class powers that grant ranks
    powers: list[str] = field(default_factory=list)        # class powers that give or act as it
    skill: str | None = None                               # "18+" for a thief's Lockpicking

    @property
    def total(self) -> int:
        return self.ranks + self.class_ranks


def split_entry(entry: str) -> tuple[str, str | None, int]:
    """'Performance (chanting) 2' -> ('Performance', 'chanting', 2)."""
    s = entry.strip()
    rank = 1
    m = re.match(r"^(.*?)\s+(\d+)$", s)
    if m:
        s, rank = m.group(1).strip(), int(m.group(2))
    spec = None
    m = re.match(r"^(.*?)\s*\((.*)\)$", s)
    if m:
        s, spec = m.group(1).strip(), m.group(2).strip()
    return s, spec, rank


def _power_grant(power: dict, prof: str) -> tuple[bool, int]:
    """(does this power give `prof`, how many ranks it grants)."""
    name = _norm(power["name"].split(": ", 1)[-1])
    text = _norm(power.get("summary", ""))
    for n in _names(prof):
        p = re.escape(n)
        m = re.search(rf"\b(\d+|a|an|one|two|three|four) ranks? of (?:the )?{p}\b", text)
        if m:
            return True, int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1)]
        if re.search(rf"\bgains? {p} proficiency\b", text):
            return True, 1
        if name == n or re.search(rf"\bas {p}( proficiency)?\)|\bas {p} proficiency\b", text):
            return True, 0
    return False, 0


def holdings(ch: Character) -> dict[str, Holding]:
    """Proficiency name (from PARTY_PROFICIENCIES) -> this character's holding, for the ones they have."""
    wanted = [p for group in PARTY_PROFICIENCIES.values() for p in group]
    out: dict[str, Holding] = {}
    for entry in ch.data["proficiencies"]:
        base, spec, rank = split_entry(entry)
        for prof in wanted:
            if _norm(base) in _names(prof):
                h = out.setdefault(prof, Holding())
                h.ranks += rank
                if spec:
                    h.specs.append(spec)
    skills = {}
    for name, values in rules.class_skills(ch.cls.key).items():
        prof = SKILL_FOR.get(_norm(name))
        if prof and values and not ch.zero_level:
            v = values[min(ch.level, len(values)) - 1]
            if v not in (None, "-"):
                skills[prof] = f"{v}+" if isinstance(v, int) else str(v)
    for prof, value in skills.items():
        out.setdefault(prof, Holding()).skill = value
    if not ch.zero_level:
        have, _ = embeds.powers_split(ch)
        for power in have:
            for prof in wanted:
                if prof in skills and _norm(power["name"]) in _names(prof):
                    continue   # the thief's Lockpicking power is the skill already shown
                gives, ranks = _power_grant(power, prof)
                if gives:
                    h = out.setdefault(prof, Holding())
                    h.class_ranks += ranks
                    h.powers.append(power["name"])
    return out


def describe(name: str, h: Holding, prof: str) -> str:
    """'**Luthielle** 4 (1 + 3 from class power)', 'Oculon skill 18+', 'Thrain (as Expert Caving)'."""
    bits = [name]
    if h.total:
        bits.append(f"**{h.total}**")
    if h.skill:
        bits.append(f"skill {h.skill}")
    sources = ["class power" if _norm(pw.split(": ", 1)[-1]) in _names(prof) else pw for pw in h.powers]
    notes = []
    if h.specs:
        notes.append(", ".join(h.specs))
    if h.class_ranks:
        src = ", ".join(sources)
        notes.append(f"{h.ranks} + {h.class_ranks} from {src}" if h.ranks else f"from {src}")
    elif sources:
        notes.append(", ".join(x if x == "class power" else f"as {x}" for x in sources))
    return " ".join(bits) + (f" ({'; '.join(notes)})" if notes else "")
