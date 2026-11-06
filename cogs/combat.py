"""Dice: /mattack, /rattack, /save_*, /initiative, /roll."""
from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds, supplies
from acks.character import AttackProfile, Character
from acks.dice import d, fmt_mod, roll

from .common import UserError, character_autocomplete, resolve_character, save


def resolve_attack(ch: Character, p: AttackProfile, target_ac: int) -> discord.Embed:
    natural = d(20)
    total = natural + p.bonus.total
    need = p.throw + target_ac
    if natural == 20:
        hit = True
    elif natural == 1:
        hit = False
    else:
        hit = total >= need
    damage = None
    crit_note = None
    if hit:
        die = p.damage_die
        extra = p.extra_dice_on_hit
        if natural == 20 and p.weapon_focus:
            extra += 1
            crit_note = "Weapon Focus: natural 20 adds an extra die of damage."
        if die in ("0", ""):
            damage = (0, "this weapon deals no damage")
        else:
            n, _, sides = die.partition("d")
            dice_expr = f"{int(n or 1) + extra}d{sides}"
            r = roll(dice_expr)
            bonus = p.damage_bonus.total
            dmg_total = max(1, r.total + bonus)
            detail = f"{dice_expr} [{', '.join(map(str, r.dice))}]"
            if bonus:
                detail += f" {fmt_mod(bonus)}"
            if p.damage_bonus.parts:
                detail += f" — {p.damage_bonus.describe()}"
            if extra and p.extra_dice_on_hit:
                detail += f" — includes +{p.extra_dice_on_hit}d backstab/ambush"
            if r.total + bonus < 1:
                detail += " (minimum 1)"
            damage = (dmg_total, detail)
    return embeds.attack_embed(ch, p, target_ac, natural, hit, damage, crit_note)


Foe = Literal["goblinoid or giant", "human or demi-human", "ooze or vermin", "evil creature"]
FOE_KEYS = {"goblinoid or giant": "goblinoid", "human or demi-human": "kin", "ooze or vermin": "vermin",
            "evil creature": "evil"}
SaveSource = Literal["evil creature", "ooze or vermin"]
SAVE_SOURCE_KEYS = {"evil creature": "evil", "ooze or vermin": "vermin"}
SAVE_HELP = {"source": "Who or what caused it (paladin aura vs evil, Vermin-Slaying vs vermin)",
             "agility": "Agility could help avoid it, e.g. pit traps (Acrobatics +2)"}


async def _ammo_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Stacks of the ammunition the equipped missile weapon shoots."""
    try:
        ch = resolve_character(interaction, getattr(interaction.namespace, "character", None), write=False)
    except UserError:
        return []
    base = supplies.ammo_for(ch.equipped("missile"))
    return [app_commands.Choice(name=f"{it['name']} ×{it['qty']}"[:100], value=str(it["id"]))
            for it in ch.items() if base and it.get("kind") == "ammo" and it.get("base") == base
            and current.lower() in it["name"].lower()][:25]


def _conditions(raging: bool, mounted: bool, blind: bool) -> set[str]:
    return {name for name, on in (("berserk", raging), ("mounted", mounted), ("blind", blind)) if on}


class Combat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="mattack", description="Melee attack with your equipped weapon(s)")
    @app_commands.guild_only()
    @app_commands.describe(target_ac="Target's Armor Class",
                           situational="Extra modifier (e.g. +2 flanking, +1 higher ground)",
                           backstab="Backstab/ambush a vulnerable target (+4, extra damage dice)",
                           raging="In a berserker rage (Berserkergang: +2 to hit, -2 AC)",
                           mounted="Attacking from horseback (Mounted Combat: +1)",
                           blind="Blinded or the target is invisible (-4, or -2 with Blind Fighting)",
                           foe="Target type, for Goblin-/Kin-/Vermin-Slaying and the paladin's aura")
    @app_commands.autocomplete(character=character_autocomplete)
    async def mattack(self, interaction: discord.Interaction, target_ac: app_commands.Range[int, -10, 30],
                      situational: int = 0, backstab: bool = False, raging: bool = False, mounted: bool = False,
                      blind: bool = False, foe: Foe | None = None, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        p = ch.melee_profile(situational=situational, sneak=backstab,
                             conditions=_conditions(raging, mounted, blind), foe=FOE_KEYS.get(foe))
        await interaction.response.send_message(embed=resolve_attack(ch, p, target_ac))

    @app_commands.command(name="rattack", description="Missile attack with your equipped ranged weapon")
    @app_commands.guild_only()
    @app_commands.describe(target_ac="Target's Armor Class", range="Range band (medium -2, long -5)",
                           situational="Extra modifier (e.g. -2 waist-high cover, -4 chest-high cover)",
                           backstab="Backstab/ambush a vulnerable target (short range, or long with Sniping)",
                           raging="In a berserker rage (Berserkergang: +2 with thrown weapons)",
                           mounted="Shooting from horseback (Mounted Combat: +1)",
                           blind="Blinded or the target is invisible (-4, or -2 with Blind Fighting)",
                           foe="Target type, for Goblin-/Kin-/Vermin-Slaying and the paladin's aura",
                           ammo="Which arrows/bolts/stones to shoot (default: the biggest stack)",
                           use_ammo="Use up an arrow, bolt, stone, or the thrown weapon (default: yes)")
    @app_commands.autocomplete(character=character_autocomplete, ammo=_ammo_autocomplete)
    async def rattack(self, interaction: discord.Interaction, target_ac: app_commands.Range[int, -10, 30],
                      range: Literal["short", "medium", "long"] = "short", situational: int = 0,
                      backstab: bool = False, raging: bool = False, mounted: bool = False, blind: bool = False,
                      foe: Foe | None = None, ammo: str | None = None, use_ammo: bool = True,
                      character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        try:
            p = ch.missile_profile(range_band=range, situational=situational, sneak=backstab,
                                   conditions=_conditions(raging, mounted, blind), foe=FOE_KEYS.get(foe))
        except ValueError as e:
            raise UserError(str(e)) from e
        weapon_item = ch.equipped("missile")
        base = supplies.ammo_for(weapon_item)
        shot = None   # the stack this shot comes out of
        if use_ammo and base:
            shot = supplies.ammo_stack(ch, base, ammo)
            if shot is None:
                kind = supplies.AMMO[base][0].lower()
                special = supplies.special_ammo(ch, base) if not ammo else []
                if special:
                    raise UserError(f"**{ch.name}** has only special {kind} left ("
                                    + ", ".join(f"{it['qty']}× {it['name']}" for it in special)
                                    + "). Pick them with the `ammo` option to shoot them.")
                raise UserError(f"**{ch.name}** has no {kind} for the {weapon_item['name']}"
                                + (f" called **{ammo}**" if ammo else "")
                                + f". Add some with `/item add name:{supplies.AMMO[base][0]} quantity:20`, "
                                  f"or shoot with `use_ammo:False`.")
        elif use_ammo and p.weapon and p.weapon.thrown:
            shot = weapon_item
        embed = resolve_attack(ch, p, target_ac)
        if shot:
            name = shot["name"]
            left_stack, _ = ch.remove_item(shot["id"], 1)
            save(interaction, ch)
            rest = int(left_stack["qty"])
            if base:
                total = supplies.ammo_count(ch, base)
                note = f"🎯 Shot from **{name}**: {rest} left"
                note += f" ({supplies.ammo_label(base, total)} in all)." if total != rest else "."
                if rest == 0:
                    note += " ⚠️ That was the last one!" if total == 0 else " That stack is used up."
            else:
                note = (f"🎯 Thrown from **{name}**: {rest} left." if rest
                        else f"🎯 Threw the last of the **{name}**: the missile slot is empty.")
            embed.description += f"\n{note}"
        await interaction.response.send_message(embed=embed)

    async def _save(self, interaction: discord.Interaction, save: str, situational: int, source: str | None,
                    agility: bool, character: str | None) -> None:
        ch = resolve_character(interaction, character)
        bonus = ch.save_bonus(save, foe=SAVE_SOURCE_KEYS.get(source), agility=agility)
        bonus.add("situational", situational)
        await interaction.response.send_message(
            embed=embeds.save_embed(ch, save, d(20), bonus, ch.save_target(save)))

    @app_commands.command(name="save_paralysis", description="Paralysis save (paralysis, petrification, sleep, fear)")
    @app_commands.guild_only()
    @app_commands.describe(situational="Extra modifier, e.g. -2 per size category smaller", **SAVE_HELP)
    @app_commands.autocomplete(character=character_autocomplete)
    async def save_paralysis(self, interaction: discord.Interaction, situational: int = 0,
                             source: SaveSource | None = None, agility: bool = False,
                             character: str | None = None) -> None:
        await self._save(interaction, "paralysis", situational, source, agility, character)

    @app_commands.command(name="save_death", description="Death save (instant death, disease, poison, blindness)")
    @app_commands.guild_only()
    @app_commands.describe(situational="Extra modifier", **SAVE_HELP)
    @app_commands.autocomplete(character=character_autocomplete)
    async def save_death(self, interaction: discord.Interaction, situational: int = 0,
                         source: SaveSource | None = None, agility: bool = False,
                         character: str | None = None) -> None:
        await self._save(interaction, "death", situational, source, agility, character)

    @app_commands.command(name="save_blast", description="Blast save (fireballs, breath weapons, collapses)")
    @app_commands.guild_only()
    @app_commands.describe(situational="Extra modifier, e.g. cover", **SAVE_HELP)
    @app_commands.autocomplete(character=character_autocomplete)
    async def save_blast(self, interaction: discord.Interaction, situational: int = 0,
                         source: SaveSource | None = None, agility: bool = False,
                         character: str | None = None) -> None:
        await self._save(interaction, "blast", situational, source, agility, character)

    @app_commands.command(name="save_implements", description="Implements save (wands, rods, staffs, rings)")
    @app_commands.guild_only()
    @app_commands.describe(situational="Extra modifier", **SAVE_HELP)
    @app_commands.autocomplete(character=character_autocomplete)
    async def save_implements(self, interaction: discord.Interaction, situational: int = 0,
                              source: SaveSource | None = None, agility: bool = False,
                              character: str | None = None) -> None:
        await self._save(interaction, "implements", situational, source, agility, character)

    @app_commands.command(name="save_spells", description="Spells save (any other cast spell)")
    @app_commands.guild_only()
    @app_commands.describe(situational="Extra modifier", **SAVE_HELP)
    @app_commands.autocomplete(character=character_autocomplete)
    async def save_spells(self, interaction: discord.Interaction, situational: int = 0,
                          source: SaveSource | None = None, agility: bool = False,
                          character: str | None = None) -> None:
        await self._save(interaction, "spells", situational, source, agility, character)

    @app_commands.command(name="initiative", description="Roll initiative (1d6 + modifiers)")
    @app_commands.guild_only()
    @app_commands.describe(casting="Casting a spell this round (Battle Magic +1; Combat Reflexes doesn't apply)")
    @app_commands.autocomplete(character=character_autocomplete)
    async def initiative(self, interaction: discord.Interaction, situational: int = 0, casting: bool = False,
                         character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        b = ch.initiative_bonus(casting=casting)
        b.add("situational", situational)
        r = d(6)
        e = discord.Embed(title=f"⏱️ {ch.name} — Initiative **{r + b.total}**", color=embeds.INFO_COLOR,
                          description=f"🎲 d6 **{r}** {fmt_mod(b.total)}\n-# Modifiers: {b.describe()}")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="roll", description="Roll dice, e.g. 1d20+2, 3d6, 4d6kh3")
    @app_commands.describe(dice="Dice expression", reason="What the roll is for")
    async def roll_cmd(self, interaction: discord.Interaction, dice: str, reason: str | None = None) -> None:
        try:
            r = roll(dice)
        except ValueError as e:
            raise UserError(str(e)) from e
        title = f"🎲 {interaction.user.display_name}" + (f" — {reason}" if reason else "")
        e = discord.Embed(title=title, description=f"`{dice}` → {r.detail()} = **{r.total}**",
                          color=embeds.INFO_COLOR)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="throw", description="Roll a proficiency or other d20 throw against a target")
    @app_commands.describe(target="Target number (e.g. 11 for an 11+ throw)", modifier="Total modifier",
                           reason="What the throw is for")
    async def throw(self, interaction: discord.Interaction, target: int, modifier: int = 0,
                    reason: str | None = None) -> None:
        r = d(20)
        total = r + modifier
        ok = r == 20 or (r != 1 and total >= target)
        title = f"{'✅' if ok else '❌'} {interaction.user.display_name}" + (f" — {reason}" if reason else "")
        e = discord.Embed(title=title, color=embeds.HIT_COLOR if ok else embeds.MISS_COLOR,
                          description=f"🎲 d20 **{r}** {fmt_mod(modifier)} = **{total}** vs **{target}+** — "
                                      f"**{'SUCCESS' if ok else 'FAILURE'}**")
        await interaction.response.send_message(embed=e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Combat(bot))
