"""One-off generator: pulls class templates and proficiency lists out of the
ACKS II Revised Rulebook markdown chunks and writes them to acks/data/*.json.

Usage:
    python tools/extract_book_data.py "<path to ACKSII_Revised_Rulebook_chunks.json>"
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "acks" / "data"

# Heading text in the book -> class key used by the bot
CLASS_HEADINGS = {
    "fighter": "fighter", "explorer": "explorer", "thief": "thief", "mage": "mage",
    "crusader": "crusader", "venturer": "venturer", "assassin": "assassin",
    "barbarian": "barbarian", "bard": "bard", "bladedancer": "bladedancer",
    "paladin": "paladin", "priestess": "priestess", "shaman": "shaman",
    "warlock": "warlock", "witch": "witch", "dwarven craftpriest": "craftpriest",
    "dwarven vaultguard": "vaultguard", "elven nightblade": "nightblade",
    "elven spellsword": "spellsword", "nobiran wonderworker": "wonderworker",
    "zaharan ruinguard": "ruinguard",
}

# Proficiency names that the markdown split across <br> lines
JOIN_PREFIXES = ("Fighting Style", "Fight. Style Spec.", "Fighting Style Spec.", "Mastery of")

# Rows where the markdown lost the <br> separators entirely
PROF_OVERRIDES = {
    ("craftpriest", "Runeseer"): ["Prophecy", "Performance (chanting)", "Craft (rune-carving) 3",
                                  "Knowledge (astrology)"],
    ("ruinguard", "Warmaster"): ["Combat Ferocity", "Military Strategy",
                                 "Weapon Focus (maces, flails, and hammers)"],
}


def clean(s: str) -> str:
    s = re.sub(r"</?(i|b)>", "", s)
    s = s.replace("–", "-").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def split_profs(cell: str) -> list[str]:
    parts = [clean(p) for p in cell.split("<br>") if clean(p)]
    out: list[str] = []
    for p in parts:
        if out and (p.startswith("(") or p == "Specialization" or out[-1] in JOIN_PREFIXES
                    or out[-1].endswith("Style")):
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


def class_for_heading(heading: str) -> str | None:
    h = clean(re.sub(r"<[^>]+>|[#*]", "", heading)).lower()
    h = h.replace(" templates", "").strip()
    return CLASS_HEADINGS.get(h)


def extract_templates(chunks: list[dict]) -> dict:
    templates: dict[str, list[dict]] = {}
    for c in chunks:
        if not re.search("templates", c["heading"], re.I):
            continue
        key = class_for_heading(c["heading"])
        if not key:
            continue
        for line in c["text"].splitlines():
            if not line.startswith("|"):
                continue
            cells = [x.strip() for x in line.strip().strip("|").split("|")]
            m = re.match(r"(\d+)\s*[-–]\s*(\d+)", cells[0])
            if not m:
                continue
            has_caste = len(cells) >= 5
            name_cell = cells[1]
            prof_cell = cells[3] if has_caste else cells[2]
            equip_cell = cells[4] if has_caste else cells[3]
            name = clean(name_cell.replace("<br>", " "))
            equipment = clean(equip_cell.replace("<br>", " "))
            # "(enc. 4 4/6 st)" or a bare "(4 4/6 st)" at the end of the list
            enc_pat = r",?\s*\((?:enc\.\s*)?(\d[^()]*?\bst\b[^()]*)\)\s*$"
            enc = re.search(enc_pat, equipment)
            profs = PROF_OVERRIDES.get((key, name)) or split_profs(prof_cell)
            entry = {
                "roll_min": int(m.group(1)),
                "roll_max": int(m.group(2)),
                "name": name,
                "caste": clean(cells[2].replace("<br>", " ")) if has_caste else None,
                "proficiencies": profs,
                "equipment": re.sub(enc_pat, "", equipment).strip(" ,"),
                "book_encumbrance": re.sub(r"\bst st\b", "st", enc.group(1).strip()) if enc else None,
            }
            bucket = templates.setdefault(key, [])
            if not any(t["roll_min"] == entry["roll_min"] for t in bucket):
                bucket.append(entry)
    for bucket in templates.values():
        bucket.sort(key=lambda t: t["roll_min"])
    return templates


def extract_proficiencies(chunks: list[dict]) -> dict:
    lists: dict[str, list[str]] = {}
    for c in chunks:
        if "PROFICIENCY LISTS" not in c["heading"]:
            continue
        for m in re.finditer(r"\*\*([A-Za-z ]+) Proficiency List:\*\*\s*([^\n]+)", c["text"]):
            label = m.group(1).strip().lower()
            key = "general" if label == "general" else CLASS_HEADINGS.get(label)
            if not key:
                continue
            # split on commas that are not inside parentheses
            names = [clean(n) for n in re.split(r",\s*(?![^()]*\))", m.group(2)) if clean(n)]
            lists[key] = names
    return lists


def main() -> None:
    src = Path(sys.argv[1])
    chunks = json.loads(src.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    templates = extract_templates(chunks)
    profs = extract_proficiencies(chunks)
    (OUT / "templates.json").write_text(json.dumps(templates, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "proficiencies.json").write_text(json.dumps(profs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"templates: {len(templates)} classes, {sum(len(v) for v in templates.values())} rows")
    print(f"proficiency lists: {sorted(profs)}")


if __name__ == "__main__":
    main()
