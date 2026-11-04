"""Discord embeds for character and animal sheets and roll results."""
from __future__ import annotations

from fractions import Fraction

import discord

from . import rules, spells
from .animal import Animal, AttackResult, attack_label
from .character import MODIFIER_TARGETS, AttackProfile, Character
from .dice import fmt_mod

SHEET_COLOR = discord.Color.from_rgb(139, 90, 43)
HIT_COLOR = discord.Color.from_rgb(46, 160, 67)
MISS_COLOR = discord.Color.from_rgb(200, 55, 55)
INFO_COLOR = discord.Color.from_rgb(88, 101, 242)

STYLE_NAMES = {"unarmed": "unarmed", "single": "single weapon", "dual": "dual weapons",
               "two_handed": "two-handed", "weapon_and_shield": "weapon & shield", "missile": "missile"}


def hp_bar(cur: int, mx: int, width: int = 12) -> str:
    mx = max(1, mx)
    filled = max(0, min(width, round(width * cur / mx)))
    return "█" * filled + "░" * (width - filled)


def hp_status(cur: int, mx: int) -> str:
    if cur <= 0:
        return "💀 **Unconscious / dying** — roll on Mortal Wounds when treated"
    if cur <= mx // 4:
        return "🩸 Badly wounded"
    if cur < mx:
        return "Wounded"
    return "Unhurt"


def _clip(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 2] + " …"


def needed_vs_ac0(p: AttackProfile) -> str:
    need = p.throw - p.bonus.total
    return f"{need}+"


def weapon_line(ch: Character, p: AttackProfile) -> str:
    style = STYLE_NAMES.get(p.style, p.style)
    weapon = p.weapon_name
    if p.off_hand_name:
        weapon += f" + {p.off_hand_name}"
    line = (f"**{weapon}** ({style})\n"
            f"Hit AC 0 on **{needed_vs_ac0(p)}** · {fmt_mod(p.bonus.total)} to hit · dmg **{p.damage_expression()}**")
    if p.nonproficient:
        line += f"\n⚠️ Non-proficient ({'; '.join(p.nonproficient)}): attacks as 0th-level fighter (11+)"
    return line


def sheet_embed(ch: Character, owner_name: str | None = None) -> discord.Embed:
    d = ch.data
    c = ch.cls
    title_line = f"Level {ch.level} {c.name} — *{c.title(ch.level)}*"
    nxt = ch.xp_for_next()
    xp_line = f"XP **{d['xp']:,}**" + (f" / {nxt:,}" if nxt else " (max level)")
    bonus = ch.xp_bonus_pct()
    if bonus:
        xp_line += f" (+{bonus}% XP)"
    if ch.can_level():
        xp_line += " · ⬆️ **ready to level up!** `/levelup`"
    bits = [b for b in (d.get("alignment"), d.get("homeland"), d.get("sex"),
                        f"Age {d['age']}" if d.get("age") else "") if b]
    desc = [title_line, " · ".join(bits) if bits else "", xp_line]
    if d.get("template"):
        desc.append(f"Template: {d['template']}")
    e = discord.Embed(title=f"📜 {ch.name}", description="\n".join(x for x in desc if x), color=SHEET_COLOR)

    # attributes
    rows = []
    attrs = rules.ATTRIBUTES
    for row in (attrs[:3], attrs[3:]):
        rows.append("   ".join(f"{a} {ch.score(a):>2} ({fmt_mod(ch.mod(a))})" for a in row))
    e.add_field(name="Attributes", value="```\n" + "\n".join(rows) + "\n```", inline=False)

    # vitals
    hp = d["hp"]
    e.add_field(name="Hit Points",
                value=f"`{hp_bar(hp['current'], hp['max'])}`\n**{hp['current']} / {hp['max']}** · {ch.hit_dice_label()}\n"
                      f"{hp_status(hp['current'], hp['max'])}",
                inline=True)
    ac = ch.armor_class()
    e.add_field(name="Armor Class", value=f"**AC {ac.total}**\n-# {ac.describe()}", inline=True)
    init = ch.initiative_bonus()
    e.add_field(name="Attack Throw",
                value=f"**{ch.attack_throw()}+**\nInit {fmt_mod(init.total)} · Cleaves {ch.cleaves()}/rd",
                inline=True)

    # saves
    wil = ch.mod("WIL")
    save_cells = [f"{rules.SAVE_LABELS[s]:<11}{ch.save_target(s):>3}+" for s in rules.SAVES]
    save_text = "```\n" + "\n".join(
        "   ".join(save_cells[i:i + 2]) for i in range(0, len(save_cells), 2)) + "\n```"
    save_mods = ch.save_bonus("paralysis").total - wil
    note = f"Rolls add WIL {fmt_mod(wil)}"
    if save_mods:
        note += f" and {fmt_mod(save_mods)} from modifiers"
    e.add_field(name="Saving Throws", value=save_text + f"\n-# {note}", inline=False)

    # weapons
    melee = ch.melee_profile()
    e.add_field(name="⚔️ Melee", value=_clip(weapon_line(ch, melee)), inline=False)
    try:
        missile = ch.missile_profile()
        rng = f" · {missile.weapon.ranges[0]}'/{missile.weapon.ranges[1]}'/{missile.weapon.ranges[2]}'" \
            if missile.weapon and missile.weapon.ranges else ""
        e.add_field(name="🏹 Missile", value=_clip(weapon_line(ch, missile) + rng), inline=False)
    except ValueError:
        e.add_field(name="🏹 Missile", value="*none equipped*", inline=False)

    armor = ch.equipped("armor")
    shield = ch.equipped("shield")
    gear = []
    if armor:
        a = ch.armor_def()
        gear.append(f"**{armor['name']}** ({a.category}, AC {a.ac}{fmt_mod(armor.get('magic', 0)) if armor.get('magic') else ''})")
    else:
        gear.append("No armor")
    if shield:
        gear.append(f"**{shield['name']}**" + ("" if "weapon_and_shield" in ch.styles()
                                               else " (no weapon & shield style: no AC bonus)"))
    if not ch.armor_proficient():
        gear.append(f"⚠️ Not proficient with {ch.armor_category()} armor")
    e.add_field(name="🛡️ Armor", value="\n".join(gear), inline=True)

    enc = ch.encumbrance()
    sp = ch.speeds()
    e.add_field(
        name="🎒 Encumbrance",
        value=f"**{rules.fmt_stone(enc)}** / {ch.max_encumbrance()} st · {sp['band']}\n"
              f"Speed {sp['exploration']}' turn · {sp['combat']}' rd · run {sp['running']}' · {sp['expedition']} mi/day",
        inline=True)

    purse = d["purse"]
    coins = ", ".join(f"{purse[c]:,} {c}" for c in rules.COIN_TYPES if purse.get(c))
    if coins and any(purse.get(c) for c in rules.COIN_TYPES if c != "gp"):
        value = ch.purse_value_gp()
        coins += f"\n-# ≈ {float(value):,.2f} gp" if value.denominator != 1 else f"\n-# ≈ {int(value):,} gp"
    e.add_field(name="💰 Purse", value=coins or "*empty*", inline=True)

    spell_lines = spells.summary_lines(ch)
    if spell_lines:
        e.add_field(name="✨ Spell Slots", value=_clip("\n".join(spell_lines)) + "\n-# ◆ available · ◇ spent",
                    inline=False)

    profs = ", ".join(d["proficiencies"]) or "*none*"
    styles = ", ".join(rules.STYLE_LABELS[s] for s in rules.STYLES if s in ch.styles())
    if ch.style_choice_pending():
        styles += " · ⚠️ pick yours with `/character training style_choice`"
    e.add_field(name="Proficiencies", value=_clip(profs, 900) + f"\n-# Fighting styles: {styles}", inline=False)

    mods = d.get("modifiers", [])
    if mods:
        e.add_field(name="Active Modifiers", value=_clip("\n".join(
            f"• **{m['name']}**: {fmt_mod(int(m['value']))} {MODIFIER_TARGETS.get(m['target'], m['target'])}"
            for m in mods)), inline=False)
    have, upcoming = powers_split(ch)
    if have or upcoming:
        names = " · ".join(p["name"] for p in have) or "*none yet*"
        nxt = f"\n-# Next: {upcoming[0]['name']} at {_ordinal(upcoming[0]['level'])} level" if upcoming else ""
        e.add_field(name="🌟 Class Powers", value=_clip(names, 900) + nxt + "\n-# Details: Notes page or "
                    "`/character powers`", inline=False)
    skills = skill_line(ch)
    if skills:
        e.add_field(name="🎯 Class Skills", value=_clip(skills), inline=False)
    if (c.notes and not (have or upcoming)) or c.key == "barbarian":
        extra = c.notes if not (have or upcoming) else ""
        if c.key == "barbarian":
            region = rules.BARBARIAN_REGIONS.get(ch.options.get("barbarian_region", ""), {})
            extra += f" Region: {region.get('label', 'not set')}; damage bonus applies to " \
                     f"{ch.options.get('barbarian_damage', 'melee')} attacks."
        e.add_field(name="Class Notes", value=_clip(extra.strip()), inline=False)
    footer = f"Character #{ch.id}" if ch.id else "Preview"
    if owner_name:
        footer += f" · Player: {owner_name}"
    e.set_footer(text=footer)
    return e


def inventory_embed(ch: Character, animals: list[Animal] | None = None) -> discord.Embed:
    e = discord.Embed(title=f"🎒 {ch.name} — Inventory", color=SHEET_COLOR)
    eq = ch.data["equipped"]
    equipped_ids = {}
    for slot in ("main", "off", "missile", "armor", "shield"):
        if eq.get(slot) is not None:
            equipped_ids.setdefault(eq[slot], []).append(
                {"main": "2H" if eq.get("two_handed") else "main", "off": "off", "missile": "missile",
                 "armor": "worn", "shield": "shield"}[slot])
    lines = []
    for it in sorted(ch.items(), key=lambda i: (i["kind"] not in ("weapon", "armor", "shield"), i["name"].lower())):
        each = ch.item_stone_each(it)
        total = each * int(it["qty"])
        tag = f" `[{', '.join(equipped_ids[it['id']])}]`" if it["id"] in equipped_ids else ""
        magic = f" {fmt_mod(int(it['magic']))}" if it.get("magic") else ""
        qty = f"{it['qty']}× " if it["qty"] != 1 else ""
        weight = "worn" if it["kind"] == "clothing" else ("—" if it["kind"] == "animal" else rules.fmt_stone(total))
        extra = ""
        w = ch.item_weapon(it)
        if w:
            extra = f" · {w.damage}{'/' + w.damage_2h if w.damage_2h else ''}"
        a = ch.item_armor(it)
        if a:
            extra = f" · AC {fmt_mod(a.ac) if a.category == 'shield' else a.ac}"
        note = f" — *{it['notes']}*" if it.get("notes") else ""
        lines.append(f"`#{it['id']:>3}` {qty}**{it['name']}**{magic}{tag}{extra} · {weight}{note}")
    if not lines:
        lines = ["*Nothing carried.*"]
    chunk, chunks = "", []
    for line in lines:
        if len(chunk) + len(line) + 1 > 1000:
            chunks.append(chunk)
            chunk = ""
        chunk += line + "\n"
    chunks.append(chunk)
    for i, c in enumerate(chunks[:20]):
        e.add_field(name="Items" if i == 0 else "Items (cont.)", value=c, inline=False)
    coins = ch.coin_count()
    enc = ch.encumbrance()
    sp = ch.speeds()
    e.add_field(name="Coins", value=f"{coins:,} coins = {rules.fmt_stone(ch.coin_stone())}", inline=True)
    e.add_field(name="Total", value=f"**{rules.fmt_stone(enc)}** / {ch.max_encumbrance()} st\n{sp['band']} "
                                     f"({sp['exploration']}' / {sp['combat']}')", inline=True)
    if animals:
        e.add_field(name="🐴 Animals", value=_clip("\n".join(animal_line(a) for a in animals)), inline=False)
    e.set_footer(text="Item numbers (#) can be used with /item remove and /equip. 6 items = 1 stone; 1,000 coins = 1 stone.")
    return e


def _ordinal(n: int) -> str:
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def skill_line(ch: Character) -> str:
    """Current value of each per-level class skill, e.g. 'Climbing 4+ · Hiding 17+'."""
    cells: list[str] = []
    groups: dict[str, list[str]] = {}   # "Rebuke Undead (Skeleton)" -> grouped under "Rebuke Undead"
    for name, values in rules.class_skills(ch.cls.key).items():
        if not values:
            continue
        v = values[min(ch.level, len(values)) - 1]
        if v is None or v == "-":
            continue
        shown = f"{v}+" if isinstance(v, int) else str(v)
        if name.endswith(")") and " (" in name:
            group, sub = name[:-1].split(" (", 1)
            groups.setdefault(group, []).append(f"{sub} {shown}")
        else:
            cells.append(f"{name} {shown}")
    for group, entries in groups.items():
        legend = " (R = rebuked automatically, D = destroyed)" if "rebuke" in group.lower() or "turn" in group.lower() \
            else ""
        cells.append(f"**{group}**: {', '.join(entries)}{legend}")
    return " · ".join(cells)


def powers_split(ch: Character) -> tuple[list[dict], list[dict]]:
    """(powers the character has at their level, powers still to come).

    Path powers ("Elementalism: Fiery Soul") only show for the path chosen with /character path.
    """
    paths = rules.power_paths(ch.cls.key)
    chosen = ch.options.get("power_path")
    powers = []
    for p in rules.class_powers(ch.cls.key):
        path = rules.power_path_of(p, paths)
        if (path and path != chosen) or rules.is_optional_power(p):
            continue
        powers.append(p)
    return ([p for p in powers if int(p["level"]) <= ch.level],
            [p for p in powers if int(p["level"]) > ch.level])


def _power_fields(e: discord.Embed, title: str, powers: list[dict], budget: int, show_level: bool) -> None:
    """Add powers as 'name: summary' lines, split across fields; stop before the embed budget runs out."""
    chunk, first = "", True
    for p in powers:
        lvl = f"`{_ordinal(p['level'])}` " if show_level else ""
        line = f"{lvl}**{p['name']}**: {p.get('summary', '')}\n"
        if len(chunk) + len(line) > 1000:
            if len(e) + len(chunk) + 40 > budget:
                chunk += "…"
                break
            e.add_field(name=title if first else f"{title} (cont.)", value=chunk, inline=False)
            chunk, first = "", False
        chunk += line
    if chunk and len(e) + len(chunk) + 40 <= budget:
        e.add_field(name=title if first else f"{title} (cont.)", value=chunk, inline=False)


def powers_embed(ch: Character, all_levels: bool = False) -> discord.Embed:
    have, upcoming = powers_split(ch)
    e = discord.Embed(title=f"🌟 {ch.name} — {ch.cls.name} powers (level {ch.level})", color=SHEET_COLOR)
    if not (have or upcoming):
        e.description = "*No class power list for this class yet.*"
        return e
    skills = skill_line(ch)
    if skills:
        e.add_field(name=f"🎯 Class skills at level {ch.level}", value=_clip(skills), inline=False)
    _power_fields(e, "Class powers", have, 5600 if all_levels else 5800, show_level=True)
    if upcoming:
        if all_levels:
            _power_fields(e, "Still to come", upcoming, 5800, show_level=True)
        else:
            e.add_field(name="Still to come", value=_clip(" · ".join(
                f"{p['name']} ({_ordinal(p['level'])})" for p in upcoming)), inline=False)
    options = [p for p in rules.class_powers(ch.cls.key) if rules.is_optional_power(p)]
    if options:
        e.add_field(name="Optional powers to choose from", value=_clip(" · ".join(
            p["name"].removeprefix("Optional: ") for p in options) + "\n-# Record your picks in `/character notes`."),
            inline=False)
    e.set_footer(text=f"{ch.cls.source} · summaries paraphrase the book; check it for full rules")
    return e


def notes_embed(ch: Character) -> discord.Embed:
    d = ch.data
    e = discord.Embed(title=f"📖 {ch.name} — Background & Notes", color=SHEET_COLOR)
    e.add_field(name="Description", value=_clip(d.get("description") or "*No description yet. Use `/character edit`.*"),
                inline=False)
    e.add_field(name="Notes", value=_clip(d.get("notes") or "*No notes yet. Use `/character notes`.*"), inline=False)
    hd = ch.cls
    e.add_field(name="Class", value=f"{hd.name} · HD d{hd.hit_die} · Key: {', '.join(hd.key_attributes)}\n"
                                    f"Armor: {hd.armor} · Styles: "
                                    f"{', '.join(rules.STYLE_LABELS[s] for s in rules.STYLES if s in ch.styles())}",
                inline=False)
    have, upcoming = powers_split(ch)
    if have:
        _power_fields(e, "🌟 Class powers", have, 5700, show_level=True)
    if upcoming:
        nxt = upcoming[0]
        e.add_field(name="Next power", value=_clip(f"{nxt['name']} at {_ordinal(nxt['level'])} level: "
                                                    f"{nxt.get('summary', '')}"), inline=False)
    return e


def attack_embed(ch: Character, p: AttackProfile, target_ac: int, roll: int, hit: bool,
                 damage: tuple[int, str] | None, crit_note: str | None) -> discord.Embed:
    total = roll + p.bonus.total
    need = p.throw + target_ac
    icon = "🗡️" if p.kind == "melee" else "🏹"
    verdict = "HIT" if hit else "MISS"
    e = discord.Embed(
        title=f"{icon} {ch.name} → AC {target_ac}: **{verdict}**",
        color=HIT_COLOR if hit else MISS_COLOR)
    weapon = p.weapon_name + (f" + {p.off_hand_name}" if p.off_hand_name else "")
    nat = " (natural 20!)" if roll == 20 else (" (natural 1!)" if roll == 1 else "")
    lines = [
        f"**{weapon}** · {STYLE_NAMES.get(p.style, p.style)}",
        f"🎲 d20 **{roll}**{nat} {fmt_mod(p.bonus.total)} = **{total}**  vs  **{need}+**",
        f"-# Needed {need}+ = attack throw {p.throw}+ {fmt_mod(target_ac)} target AC",
        f"-# Modifiers: {p.bonus.describe()}",
    ]
    if not hit and roll != 1 and total >= p.throw:
        lines.append("-# The blow glanced off the target's armor.")
    if damage:
        dmg_total, dmg_detail = damage
        lines.append(f"💥 Damage **{dmg_total}**  ({dmg_detail})")
    if crit_note:
        lines.append(f"⭐ {crit_note}")
    if p.nonproficient:
        lines.append(f"⚠️ Non-proficient: {'; '.join(p.nonproficient)} — attacks as 0th-level fighter, "
                     f"no attribute bonuses or class powers.")
    for n in p.notes:
        lines.append(f"-# {n}")
    e.description = "\n".join(lines)
    return e


def save_embed(ch: Character, save: str, roll: int, bonus, target: int) -> discord.Embed:
    total = roll + bonus.total
    if roll == 20:
        ok = True
    elif roll == 1:
        ok = False
    else:
        ok = total >= target
    nat = " (natural 20!)" if roll == 20 else (" (natural 1!)" if roll == 1 else "")
    e = discord.Embed(title=f"🛡️ {ch.name} — {rules.SAVE_LABELS[save]} save: **{'SUCCESS' if ok else 'FAILURE'}**",
                      color=HIT_COLOR if ok else MISS_COLOR)
    e.description = (f"🎲 d20 **{roll}**{nat} {fmt_mod(bonus.total)} = **{total}**  vs  **{target}+**\n"
                     f"-# Modifiers: {bonus.describe()}")
    return e


# ---------------------------------------------------------------------------
# Animals
# ---------------------------------------------------------------------------

def stone_number(x) -> str:
    return rules.fmt_stone(Fraction(str(x))).removesuffix(" st")


def animal_line(a: Animal) -> str:
    """One line for a character's inventory page and /animal list."""
    sp = a.speeds()
    hp = a.data["hp"]
    return (f"**{a.name}** ({a.data['kind']}) · AC {a.ac()} · HP {hp['current']}/{hp['max']} · "
            f"{rules.fmt_stone(a.encumbrance())} / {stone_number(a.data['normal_load'])} st · {sp['exploration']}'")


def animal_embed(a: Animal, owner_name: str | None = None) -> discord.Embed:
    d = a.data
    hp = d["hp"]
    e = discord.Embed(title=f"🐴 {a.name}", color=SHEET_COLOR)
    lines = [f"*{d['kind']}*" + (f" · owned by **{owner_name}**" if owner_name else "")]
    lines.append(f"**HD** {d['hd']} · **HP** {hp['current']}/{hp['max']} {hp_bar(hp['current'], hp['max'])}")
    ac = a.armor_class()
    stats = [f"**AC** {a.ac()}" + (f" ({ac.describe()})" if len(ac.parts) > 1 else ""),
             f"**Attack throw** {a.attack_throw()}+"]
    if d.get("save"):
        stats.append(f"**Save** {d['save']}")
    stats.append(f"**Morale** {fmt_mod(int(d.get('morale', 0)))}")
    lines.append(" · ".join(stats))
    if hp["current"] <= 0:
        lines.append("💀 **Down**: an animal at 0 hp is unconscious and possibly slain")
    e.description = "\n".join(lines)

    if a.attacks():
        title = "⚔️ Attacks" + (" (spiked barding: +1 per die)" if a.spiked() else "")
        e.add_field(name=title, inline=False, value=_clip("\n".join(
            ("*or* " if at.get("alt") else "") + f"{attack_label(at)} **{a.damage_expression(at)}**"
            for at in a.attacks())))
    sp = a.speeds()
    e.add_field(name="🐾 Speed", inline=True,
                value=f"{sp['exploration']}' / {sp['combat']}' · run {sp['running']}'\n"
                      f"{sp['expedition']} miles/day\n-# {sp['band']}")
    e.add_field(name="⚖️ Load", inline=True,
                value=f"**{rules.fmt_stone(a.encumbrance())}** carried\nNormal {stone_number(d['normal_load'])} st · "
                      f"max {stone_number(d['max_load'])} st")
    feed_sp = a.daily_food() * rules.ANIMAL_FEED_SP_PER_STONE
    e.add_field(name="🌾 Daily needs", inline=True,
                value=f"Food {rules.fmt_stone(a.daily_food())}\nWater {rules.fmt_stone(a.daily_water())}\n"
                      f"-# working-animal feed ≈ {float(feed_sp):g} sp/day")
    if d.get("abilities"):
        e.add_field(name="✨ Special abilities", inline=False,
                    value=_clip("\n".join(f"{i}. {t}" for i, t in enumerate(d["abilities"], 1))))
    items = []
    for it in a.items():
        tag = " `[worn]`" if it["id"] == d.get("barding") else ""
        extra = ""
        if it.get("kind") == "barding":
            bs = a.barding_stats(it)
            extra = f" · AC +{int(bs.get('ac', 0)) + int(it.get('magic', 0))}" + (" · spiked" if bs.get("spiked") else "")
        qty = f"{it['qty']}× " if it["qty"] != 1 else ""
        note = f" — *{it['notes']}*" if it.get("notes") else ""
        items.append(f"`#{it['id']:>3}` {qty}**{it['name']}**{tag}{extra} · "
                     f"{rules.fmt_stone(a.item_stone_each(it) * int(it['qty']))}{note}")
    e.add_field(name="🎒 Carrying", value=_clip("\n".join(items)) if items else "*Nothing carried.*", inline=False)
    if d.get("notes"):
        e.add_field(name="📖 Notes", value=_clip(d["notes"]), inline=False)
    e.set_footer(text=f"Animal #{a.id} · item numbers (#) work with /animal item remove and /animal equip")
    return e


def animal_attack_embed(a: Animal, target_ac: int, results: list[AttackResult], situational: int) -> discord.Embed:
    hits = sum(r.hit for r in results)
    damage = sum(r.damage or 0 for r in results)
    e = discord.Embed(title=f"🐾 {a.name} → AC {target_ac}: {hits}/{len(results)} hit"
                            + (f", **{damage}** damage" if hits else ""),
                      color=HIT_COLOR if hits else MISS_COLOR)
    lines = []
    for r in results:
        nat = " (natural 20!)" if r.natural == 20 else (" (natural 1!)" if r.natural == 1 else "")
        mod = f" {fmt_mod(situational)}" if situational else ""
        line = (f"**{r.attack['name']}**: 🎲 **{r.natural}**{nat}{mod} = {r.total} vs {r.need}+ → "
                + ("**HIT**" if r.hit else "MISS"))
        if r.hit:
            line += f" · 💥 **{r.damage}** ({r.damage_detail})"
        lines.append(line)
    lines.append(f"-# Needed = attack throw {a.attack_throw()}+ {fmt_mod(target_ac)} target AC")
    e.description = _clip("\n".join(lines), 4000)
    return e
