"""/party: a multi-page summary of the party — roster, composition and best attributes, travel and food, HP.

The party is every player's active character (as /encounter start pre-fills it), the henchmen they employ, and
the animals they own.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds, rules, supplies
from acks.animal import Animal
from acks.character import Character
from acks.dice import fmt_mod
from acks.storage import Storage

from .common import UserError, guild_id, storage

PAGES = {"roster": ("Roster", "👥"), "composition": ("Composition", "📊"), "travel": ("Travel & food", "🧭"),
         "hp": ("Hit points", "❤️")}
COLOR = embeds.SHEET_COLOR


@dataclass
class Party:
    pcs: list[Character] = field(default_factory=list)
    henchmen: dict[int, list[Character]] = field(default_factory=dict)   # employer id -> henchmen
    animals: list[Animal] = field(default_factory=list)
    names: dict[int, str] = field(default_factory=dict)                   # character id -> name

    @property
    def characters(self) -> list[Character]:
        return self.pcs + [h for hs in self.henchmen.values() for h in hs]


def gather(store: Storage, gid: int) -> Party:
    everyone = store.list_for_guild(gid)
    active = store.active_character_ids(gid)
    members = {c.id: c for c in everyone if c.id in active}
    grew = True
    while grew:   # henchmen of anyone in the party, and their henchmen in turn
        new = {c.id: c for c in everyone if c.employer_id in members and c.id not in members}
        members.update(new)
        grew = bool(new)
    p = Party(names={c.id: c.name for c in everyone})
    for c in sorted(members.values(), key=lambda c: c.name.casefold()):
        if c.employer_id:
            p.henchmen.setdefault(c.employer_id, []).append(c)
        else:
            p.pcs.append(c)
    p.animals = [a for a in store.animals_for_guild(gid) if a.owner_char in members]
    return p


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def _fields(e: discord.Embed, title: str, lines: list[str], inline: bool = False) -> None:
    """Add `lines` under `title`, spilling into more fields when one is full."""
    chunk, n = "", 0
    for line in lines or ["*none*"]:
        if len(chunk) + len(line) + 1 > 1000:
            e.add_field(name=title if n == 0 else f"{title} (cont.)", value=chunk, inline=inline)
            chunk, n = "", n + 1
        chunk += line + "\n"
    e.add_field(name=title if n == 0 else f"{title} (cont.)", value=chunk, inline=inline)


def _who(c: Character) -> str:
    return f"**{c.name}** · {embeds.level_label(c)}"


def roster_page(p: Party) -> discord.Embed:
    e = discord.Embed(title="👥 Party roster", color=COLOR,
                      description=f"{len(p.pcs)} player character(s), {len(p.characters) - len(p.pcs)} henchm"
                                  f"{'a' if len(p.characters) - len(p.pcs) == 1 else 'e'}n, {len(p.animals)} animal(s).")
    _fields(e, "🧙 Player characters", [f"{_who(c)} · <@{c.data['owner_id']}>" for c in p.pcs])
    lines = []
    for employer, hs in sorted(p.henchmen.items(), key=lambda kv: p.names.get(kv[0], "").casefold()):
        lines.append(f"__{p.names.get(employer, '?')}__")
        lines += [f"└ {_who(h)}" for h in hs]
    _fields(e, "🤝 Henchmen (by employer)", lines)
    lines = []
    by_kind: dict[str, list[Animal]] = defaultdict(list)
    for a in p.animals:
        by_kind[a.data["kind"]].append(a)
    for kind in sorted(by_kind, key=str.casefold):
        lines.append(f"__{kind}__")
        for a in sorted(by_kind[kind], key=lambda a: (p.names.get(a.owner_char, "").casefold(), a.name.casefold())):
            lines.append(f"└ **{a.name}** · owned by {p.names.get(a.owner_char, '?')}")
    _fields(e, "🐴 Animals (by type and owner)", lines)
    return e


def composition_page(p: Party) -> discord.Embed:
    chars = p.characters
    e = discord.Embed(title="📊 Party composition", color=COLOR)
    by_class: dict[str, list[Character]] = defaultdict(list)
    for c in chars:
        by_class[c.cls.name].append(c)
    lines = []
    for name in sorted(by_class, key=lambda n: (-len(by_class[n]), n)):
        levels = ", ".join(embeds.level_label(c).split(" ")[0] for c in sorted(by_class[name], key=lambda c: c.level))
        lines.append(f"**{name}** ×{len(by_class[name])} ({levels})")
    _fields(e, "By class", lines, inline=True)
    by_level: dict[int, int] = defaultdict(int)
    for c in chars:
        by_level[c.level if not c.zero_level else 0] += 1
    lines = [f"**{'0th' if lvl == 0 else f'Level {lvl}'}**: {n}" for lvl, n in sorted(by_level.items())]
    leveled = [c.level for c in chars if not c.zero_level]
    if leveled:
        lines.append(f"-# Average level {sum(leveled) / len(leveled):.1f} (0th-level members not counted)")
    _fields(e, "By level", lines, inline=True)
    lines = []
    for attr in rules.ATTRIBUTES:
        best = max(c.score(attr) for c in chars)
        winners = [c for c in chars if c.score(attr) == best]
        names = ", ".join(f"{c.name}{' (henchman)' if c.employer_id else ''}" for c in winners)
        lines.append(f"**{attr}** {best} ({fmt_mod(rules.attr_mod(best))}) · {names}")
    _fields(e, "🏆 Best attributes", lines)
    return e


def _speed_line(x: Character | Animal) -> str:
    sp = x.speeds()
    return (f"**{x.name}**: {sp['exploration']}' / turn · {sp['combat']}' / round · run {sp['running']}' · "
            f"{sp['expedition']} miles / day\n-# {sp['band']}")


def travel_page(p: Party) -> discord.Embed:
    e = discord.Embed(title="🧭 Travel and food", color=COLOR)
    chars = p.characters
    slow_c = min(chars, key=lambda c: (c.speeds()["exploration"], c.speeds()["expedition"]))
    e.add_field(name="🐢 Slowest member", value=_speed_line(slow_c), inline=False)
    if p.animals:
        slow_a = min(p.animals, key=lambda a: (a.speeds()["exploration"], a.speeds()["expedition"]))
        e.add_field(name="🐢 Slowest animal", value=_speed_line(slow_a), inline=False)
    everyone: list[Character | Animal] = [*chars, *p.animals]
    pace = min(everyone, key=lambda x: x.speeds()["exploration"])
    sp = pace.speeds()
    e.add_field(name="Party pace", inline=False,
                value=f"The party moves at **{pace.name}**'s pace: **{sp['exploration']}'** per turn, "
                      f"**{sp['expedition']} miles** per day." + ("\n⚠️ Someone is overloaded and can't move."
                                                                 if sp["exploration"] == 0 else ""))
    total = sum(supplies.ration_days(c) for c in chars)
    people = len(chars)
    lines = [f"**{total}** days of rations in all · feeds all **{people}** for **{total // people}** day"
             f"{'s' if total // people != 1 else ''}" + (f" (+{total % people} spare)" if total % people else "")]
    lines += [f"{c.name}: {supplies.ration_days(c)} day{'s' if supplies.ration_days(c) != 1 else ''}"
              + (" ⚠️" if not supplies.ration_days(c) else "")
              for c in sorted(chars, key=lambda c: supplies.ration_days(c))]
    _fields(e, "🍞 Rations", lines)
    if p.animals:
        _fields(e, "🌾 Animal feed", [f"{a.name}: {embeds.feed_days(a)} · needs {rules.fmt_stone(a.daily_food())}/day"
                                     for a in p.animals])
    return e


def hp_page(p: Party) -> discord.Embed:
    e = discord.Embed(title="❤️ Party hit points", color=COLOR)

    def line(x: Character | Animal) -> str:
        hp = x.data["hp"]
        down = " 💀" if hp["current"] <= 0 else ""
        return f"`{embeds.hp_bar(hp['current'], hp['max'], 8)}` **{x.name}** {hp['current']}/{hp['max']}{down}"

    _fields(e, "🧙 Player characters", [line(c) for c in p.pcs])
    if p.henchmen:
        groups = sorted(p.henchmen.items(), key=lambda kv: p.names.get(kv[0], "").casefold())
        _fields(e, "🤝 Henchmen", [f"{line(h)} · {p.names.get(emp, '?')}'s" for emp, hs in groups for h in hs])
    if p.animals:
        _fields(e, "🐴 Animals", [line(a) for a in p.animals])
    cur = sum(x.data["hp"]["current"] for x in p.characters)
    mx = sum(x.data["hp"]["max"] for x in p.characters)
    e.set_footer(text=f"Characters' total: {cur}/{mx} HP")
    return e


BUILDERS = {"roster": roster_page, "composition": composition_page, "travel": travel_page, "hp": hp_page}


def page_embed(p: Party, page: str) -> discord.Embed:
    e = BUILDERS[page](p)
    footer = e.footer.text + " · " if e.footer and e.footer.text else ""
    e.set_footer(text=f"{footer}Party = everyone's active character, their henchmen, and their animals")
    return e


class PartyView(discord.ui.View):
    """Page buttons; each click re-reads the party so the numbers are current."""

    def __init__(self, gid: int, page: str = "roster"):
        super().__init__(timeout=900)
        self.gid = gid
        for key, (label, emoji) in PAGES.items():
            b = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.primary if key == page
                                  else discord.ButtonStyle.secondary)
            b.callback = self._goto(key)
            self.add_item(b)

    def _goto(self, page: str):
        async def go(interaction: discord.Interaction) -> None:
            p = gather(storage(interaction), self.gid)
            if not p.characters:
                await interaction.response.edit_message(content="The party is empty now.", embed=None, view=None)
                return
            await interaction.response.edit_message(embed=page_embed(p, page), view=PartyView(self.gid, page))
        return go


class PartyStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="party", description="Party stats: roster, composition, best attributes, travel, food, HP")
    @app_commands.guild_only()
    @app_commands.describe(page="Which page to open", private="Only show it to you")
    @app_commands.choices(page=[app_commands.Choice(name=label, value=key) for key, (label, _) in PAGES.items()])
    async def party(self, interaction: discord.Interaction, page: str = "roster", private: bool = False) -> None:
        gid = guild_id(interaction)
        p = gather(storage(interaction), gid)
        if not p.characters:
            raise UserError("Nobody is in the party yet: the party is every player's active character "
                            "(`/character select`), their henchmen, and their animals.")
        await interaction.response.send_message(embed=page_embed(p, page), view=PartyView(gid, page),
                                                ephemeral=private)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PartyStats(bot))
