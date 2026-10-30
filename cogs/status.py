"""Hit points, modifiers and proficiencies: /hp ..., /modifier ..., /proficiency ..."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds, rules
from acks.character import MODIFIER_TARGETS, Character
from acks.dice import fmt_mod

from .common import UserError, character_autocomplete, resolve_character, save

TARGET_CHOICES = [app_commands.Choice(name=label, value=key) for key, label in MODIFIER_TARGETS.items()]


def _hp_line(ch: Character) -> str:
    hp = ch.data["hp"]
    return f"`{embeds.hp_bar(hp['current'], hp['max'])}` **{hp['current']} / {hp['max']}** — " \
           f"{embeds.hp_status(hp['current'], hp['max'])}"


class Status(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    hp = app_commands.Group(name="hp", description="Track hit points", guild_only=True)
    modifier = app_commands.Group(name="modifier", description="Bonuses and penalties from magic, spells, "
                                                                "conditions...", guild_only=True)
    proficiency = app_commands.Group(name="proficiency", description="Add or remove proficiencies", guild_only=True)

    # -- hit points --------------------------------------------------------
    @hp.command(name="damage", description="Subtract hit points")
    @app_commands.autocomplete(character=character_autocomplete)
    async def hp_damage(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 10000],
                        character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        ch.data["hp"]["current"] = int(ch.data["hp"]["current"]) - amount
        save(interaction, ch)
        await interaction.response.send_message(f"🩸 **{ch.name}** takes **{amount}** damage.\n{_hp_line(ch)}")

    @hp.command(name="heal", description="Add hit points (up to maximum)")
    @app_commands.autocomplete(character=character_autocomplete)
    async def hp_heal(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 10000],
                      character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        hp = ch.data["hp"]
        before = int(hp["current"])
        hp["current"] = min(int(hp["max"]), before + amount)
        save(interaction, ch)
        gained = hp["current"] - before
        await interaction.response.send_message(f"💚 **{ch.name}** heals **{gained}**.\n{_hp_line(ch)}")

    @hp.command(name="set", description="Set current and/or maximum hit points")
    @app_commands.autocomplete(character=character_autocomplete)
    async def hp_set(self, interaction: discord.Interaction, current: int | None = None,
                     maximum: app_commands.Range[int, 1, 10000] | None = None,
                     character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        if current is None and maximum is None:
            raise UserError("Pass `current`, `maximum`, or both.")
        if maximum is not None:
            ch.data["hp"]["max"] = maximum
        if current is not None:
            ch.data["hp"]["current"] = current
        save(interaction, ch)
        await interaction.response.send_message(f"📝 **{ch.name}**\n{_hp_line(ch)}")

    @hp.command(name="show", description="Show hit points")
    @app_commands.autocomplete(character=character_autocomplete)
    async def hp_show(self, interaction: discord.Interaction, character: str | None = None) -> None:
        ch = resolve_character(interaction, character, write=False)
        await interaction.response.send_message(f"**{ch.name}**\n{_hp_line(ch)}")

    # -- modifiers ---------------------------------------------------------
    @modifier.command(name="add", description="Add a bonus or penalty (ring of protection, bless, blinded...)")
    @app_commands.describe(name="Label, e.g. 'Ring of Protection +1'", target="What it modifies",
                           value="Amount, e.g. 1 or -4")
    @app_commands.choices(target=TARGET_CHOICES)
    @app_commands.autocomplete(character=character_autocomplete)
    async def mod_add(self, interaction: discord.Interaction, name: str, target: str,
                      value: app_commands.Range[int, -20, 20], character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        mods = ch.data.setdefault("modifiers", [])
        mods[:] = [m for m in mods if not (m["name"].lower() == name.lower() and m["target"] == target)]
        mods.append({"name": name.strip(), "target": target, "value": value})
        save(interaction, ch)
        await interaction.response.send_message(
            f"✨ **{ch.name}**: {name} gives {fmt_mod(value)} to {MODIFIER_TARGETS[target].lower()}. "
            f"(AC now {ch.ac()})")

    @modifier.command(name="remove", description="Remove a modifier")
    @app_commands.autocomplete(character=character_autocomplete)
    async def mod_remove(self, interaction: discord.Interaction, name: str, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        mods = ch.data.setdefault("modifiers", [])
        keep = [m for m in mods if m["name"].lower() != name.lower()]
        if len(keep) == len(mods):
            raise UserError(f"No modifier called **{name}** on {ch.name}.")
        mods[:] = keep
        save(interaction, ch)
        await interaction.response.send_message(f"🧹 Removed **{name}** from {ch.name}. (AC now {ch.ac()})")

    @mod_remove.autocomplete("name")
    async def _mod_name_ac(self, interaction: discord.Interaction, current: str):
        try:
            ch = resolve_character(interaction, getattr(interaction.namespace, "character", None), write=False)
        except UserError:
            return []
        names = sorted({m["name"] for m in ch.data.get("modifiers", [])})
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    @modifier.command(name="list", description="List active modifiers")
    @app_commands.autocomplete(character=character_autocomplete)
    async def mod_list(self, interaction: discord.Interaction, character: str | None = None) -> None:
        ch = resolve_character(interaction, character, write=False)
        mods = ch.data.get("modifiers", [])
        text = "\n".join(f"• **{m['name']}**: {fmt_mod(int(m['value']))} {MODIFIER_TARGETS[m['target']]}"
                         for m in mods) or "*No active modifiers.*"
        await interaction.response.send_message(f"**{ch.name}** modifiers:\n{text}", ephemeral=True)

    # -- proficiencies -----------------------------------------------------
    @proficiency.command(name="add", description="Add a proficiency (e.g. 'Weapon Focus (axes)')")
    @app_commands.autocomplete(character=character_autocomplete)
    async def prof_add(self, interaction: discord.Interaction, name: str, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        name = name.strip()
        ch.data["proficiencies"].append(name)
        save(interaction, ch)
        hint = ""
        n = rules.normalize(name)
        if "weapon focus" in n and "(" not in n:
            hint = "\n-# Tip: name the weapon group, e.g. `Weapon Focus (swords and daggers)`."
        if "fighting style" in n and "(" not in n:
            hint = "\n-# Tip: name the style, e.g. `Fighting Style Specialization (weapon and shield)`."
        if "martial training" in n and "(" not in n:
            hint = "\n-# Tip: name the weapons, e.g. `Martial Training (axes)`."
        await interaction.response.send_message(f"📚 **{ch.name}** learns **{name}**. (AC {ch.ac()}){hint}")

    @prof_add.autocomplete("name")
    async def _prof_add_ac(self, interaction: discord.Interaction, current: str):
        try:
            ch = resolve_character(interaction, getattr(interaction.namespace, "character", None), write=False)
            class_list = rules.PROFICIENCY_LISTS.get(ch.cls.key, [])
        except UserError:
            class_list = []
        general = rules.PROFICIENCY_LISTS.get("general", [])
        extras = ["Weapon Focus (axes)", "Weapon Focus (maces, flails, and hammers)",
                  "Weapon Focus (swords and daggers)", "Weapon Focus (bows and crossbows)",
                  "Weapon Focus (slings and thrown weapons)", "Weapon Focus (spears and polearms)",
                  "Fighting Style Specialization (weapon and shield)", "Fighting Style Specialization (dual weapon)",
                  "Fighting Style Specialization (two-handed weapon)", "Fighting Style Specialization (missile weapon)",
                  "Fighting Style Specialization (single weapon)", "Martial Training (axes)",
                  "Martial Training (bows/crossbows)", "Martial Training (flails/hammers/maces)",
                  "Martial Training (swords/daggers)", "Martial Training (spears/polearms)"]
        seen, out = set(), []
        for label, names in (("class", class_list), ("general", general), ("", extras),
                             ("", rules.all_proficiency_names())):
            for n in names:
                if n in seen or current.lower() not in n.lower():
                    continue
                seen.add(n)
                out.append(app_commands.Choice(name=f"{n}{f' ({label})' if label else ''}"[:100], value=n[:100]))
        return out[:25]

    @proficiency.command(name="remove", description="Remove a proficiency")
    @app_commands.autocomplete(character=character_autocomplete)
    async def prof_remove(self, interaction: discord.Interaction, name: str, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        profs = ch.data["proficiencies"]
        match = next((p for p in profs if p.lower() == name.lower()), None) or \
            next((p for p in profs if name.lower() in p.lower()), None)
        if not match:
            raise UserError(f"**{ch.name}** doesn't have **{name}**.")
        profs.remove(match)
        save(interaction, ch)
        await interaction.response.send_message(f"📚 **{ch.name}** loses **{match}**. (AC {ch.ac()})")

    @prof_remove.autocomplete("name")
    async def _prof_remove_ac(self, interaction: discord.Interaction, current: str):
        try:
            ch = resolve_character(interaction, getattr(interaction.namespace, "character", None), write=False)
        except UserError:
            return []
        return [app_commands.Choice(name=p[:100], value=p[:100]) for p in ch.data["proficiencies"]
                if current.lower() in p.lower()][:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Status(bot))
