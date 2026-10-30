"""Spell slot tracking: /spell slots, cast, refresh, set_slots, set_points."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds, spells
from acks.character import Character

from .common import UserError, character_autocomplete, resolve_character, save


def slots_embed(ch: Character) -> discord.Embed:
    e = discord.Embed(title=f"✨ {ch.name} — Spell slots", color=embeds.INFO_COLOR)
    lines = spells.summary_lines(ch)
    e.description = "\n".join(lines) if lines else (
        "*No spell slots.* If this character casts spells, set them with `/spell set_slots` "
        "(or `/spell set_points` for spell points).")
    e.set_footer(text="◆ available · ◇ spent · /spell cast to spend, /spell refresh to restore")
    return e


async def pool_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    try:
        ch = resolve_character(interaction, getattr(interaction.namespace, "character", None), write=False)
    except UserError:
        return []
    names = list(spells.slot_pools(ch)) + list(spells.point_pools(ch))
    for default in ("Arcane", "Divine", "Spells"):
        if default not in names:
            names.append(default)
    return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except spells.SpellError as e:
        raise UserError(str(e)) from e


class Spells(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(name="spell", description="Track spell slots: spend and refresh", guild_only=True)

    @group.command(name="slots", description="Show remaining spell slots")
    @app_commands.autocomplete(character=character_autocomplete)
    async def slots(self, interaction: discord.Interaction, character: str | None = None,
                    private: bool = False) -> None:
        ch = resolve_character(interaction, character, write=False)
        await interaction.response.send_message(embed=slots_embed(ch), ephemeral=private)

    @group.command(name="cast", description="Spend a spell slot (or spell points)")
    @app_commands.describe(level="Spell level of the slot to spend", pool="Arcane or Divine, if the class has both",
                           count="How many slots to spend (default 1)",
                           points="For spell-point casters: how many points to spend",
                           spell="Optional: the spell's name, for the table")
    @app_commands.autocomplete(pool=pool_autocomplete, character=character_autocomplete)
    async def cast(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 9] | None = None,
                   pool: str | None = None, count: app_commands.Range[int, 1, 20] = 1,
                   points: app_commands.Range[int, 1, 200] | None = None, spell: str | None = None,
                   character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        what = f" **{spell}**" if spell else ""
        if points is not None:
            name, left, mx = _run(spells.spend_points, ch, points, pool)
            msg = f"✨ **{ch.name}** casts{what}, spending {points} spell point{'s' if points != 1 else ''} " \
                  f"({left} / {mx} left)."
        elif level is not None:
            name, left, mx = _run(spells.cast, ch, level, pool, count)
            slots_word = f"{count} level {level} {spells.slot_word(name)}slot{'s' if count != 1 else ''}"
            msg = f"✨ **{ch.name}** casts{what}, spending {slots_word} ({left} / {mx} left at level {level})."
        else:
            raise UserError("Give the spell `level` of the slot to spend (or `points` for spell-point casters).")
        save(interaction, ch)
        await interaction.response.send_message(msg + "\n" + "\n".join(spells.summary_lines(ch)))

    @group.command(name="refresh", description="Restore one slot of a spell level, or all slots")
    @app_commands.describe(level="Restore slots of this spell level only (leave empty to restore ALL slots)",
                           count="With level: how many slots to restore (default 1)",
                           pool="Only this pool (Arcane/Divine); default all")
    @app_commands.autocomplete(pool=pool_autocomplete, character=character_autocomplete)
    async def refresh(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 9] | None = None,
                      count: app_commands.Range[int, 1, 20] = 1, pool: str | None = None,
                      character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        if level is None:
            result = _run(spells.refresh, ch, None, pool)
        else:
            result = _run(spells.refresh, ch, level, pool, count)
        save(interaction, ch)
        await interaction.response.send_message(f"🔄 **{ch.name}**: {result}.\n" + "\n".join(spells.summary_lines(ch)))

    @group.command(name="set_slots", description="Set how many slots a spell level has (overrides the class table)")
    @app_commands.describe(level="Spell level", slots="Slots per day at that level (0 removes the level)",
                           pool="Pool name, e.g. Arcane, Divine, or Spells (default: the class's pool)",
                           reset="Go back to the class table for this level")
    @app_commands.autocomplete(pool=pool_autocomplete, character=character_autocomplete)
    async def set_slots(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 9],
                        slots: app_commands.Range[int, 0, 20] | None = None, pool: str | None = None,
                        reset: bool = False, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        if slots is None and not reset:
            raise UserError("Give `slots`, or `reset:True` to go back to the class table.")
        existing = list(spells.slot_pools(ch))
        name = pool or (existing[0] if len(existing) == 1 else "Spells")
        if not pool and len(existing) > 1:
            raise UserError(f"**{ch.name}** has more than one pool ({', '.join(existing)}). Choose one with `pool`.")
        match = next((p for p in existing if p.lower() == name.lower()), name.strip().title())
        spells.set_slots(ch, level, None if reset else slots, match)
        save(interaction, ch)
        await interaction.response.send_message(f"📝 **{ch.name}**: level {level} {spells.slot_word(match)}slots "
                                                f"{'reset to the class table' if reset else f'set to {slots}'}.\n"
                                                + ("\n".join(spells.summary_lines(ch)) or "*no slots*"))

    @group.command(name="set_points", description="Set maximum spell points (overrides the class table)")
    @app_commands.autocomplete(character=character_autocomplete)
    async def set_points(self, interaction: discord.Interaction,
                         points: app_commands.Range[int, 0, 500] | None = None, reset: bool = False,
                         character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        if points is None and not reset:
            raise UserError("Give `points`, or `reset:True` to go back to the class table.")
        spells.set_points(ch, None if reset else points)
        save(interaction, ch)
        await interaction.response.send_message(f"📝 **{ch.name}**: spell points "
                                                f"{'reset to the class table' if reset else f'set to {points}'}.\n"
                                                + ("\n".join(spells.summary_lines(ch)) or "*no spell points*"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Spells(bot))
