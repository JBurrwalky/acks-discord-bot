"""Character management: /create, /sheet, /character ..., /xp, /levelup."""
from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds, rules

from .common import (UserError, any_character_autocomplete, catalog_autocomplete, character_autocomplete, guild_id,
                     is_judge, page_embed, resolve_character, save, sheet_view, storage)
from .wizard import CreationWizard

Page = Literal["sheet", "inventory", "notes"]


async def _path_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    try:
        ch = resolve_character(interaction, getattr(interaction.namespace, "character", None), write=False)
    except UserError:
        return []
    return [app_commands.Choice(name=p, value=p) for p in rules.power_paths(ch.cls.key)
            if current.lower() in p.lower()][:25]


async def _style_choice_autocomplete(interaction: discord.Interaction,
                                     current: str) -> list[app_commands.Choice[str]]:
    try:
        ch = resolve_character(interaction, getattr(interaction.namespace, "character", None), write=False)
    except UserError:
        return []
    out = []
    for picks in rules.style_choices(ch.cls):
        label = rules.style_choice_label(picks)
        if current.lower() in label.lower():
            out.append(app_commands.Choice(name=label, value=",".join(picks)))
    return out[:25]


class Characters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    character = app_commands.Group(name="character", description="Manage your ACKS II characters",
                                   guild_only=True)

    # -- creation & display --------------------------------------------
    @app_commands.command(name="create", description="Create a new ACKS II character with a step-by-step wizard")
    @app_commands.guild_only()
    async def create(self, interaction: discord.Interaction) -> None:
        wiz = CreationWizard(interaction.user, guild_id(interaction))
        await interaction.response.send_message(embed=wiz.embed(), view=wiz, ephemeral=True)
        wiz.message = await interaction.original_response()

    @app_commands.command(name="sheet", description="Show a character sheet")
    @app_commands.guild_only()
    @app_commands.describe(character="Whose sheet (defaults to your active character)",
                           page="Which page to open", private="Only show it to you")
    @app_commands.autocomplete(character=any_character_autocomplete)
    async def sheet(self, interaction: discord.Interaction, character: str | None = None, page: Page = "sheet",
                    private: bool = False) -> None:
        ch = resolve_character(interaction, character, write=False)
        await interaction.response.send_message(embed=page_embed(ch, page, interaction.guild, storage(interaction)),
                                                view=sheet_view(ch, page), ephemeral=private)

    # -- /character group ------------------------------------------------
    @character.command(name="list", description="List your characters (Judges see everyone's)")
    async def list_(self, interaction: discord.Interaction) -> None:
        store = storage(interaction)
        gid = guild_id(interaction)
        chars = store.list_for_guild(gid) if is_judge(interaction) else store.list_for_user(gid, interaction.user.id)
        active = store.get_active(gid, interaction.user.id)
        if not chars:
            raise UserError("No characters yet. Start one with `/create`.")
        lines = []
        for c in chars:
            hp = c.data["hp"]
            mark = "⭐ " if active and c.id == active.id else ""
            owner = "" if c.data["owner_id"] == interaction.user.id else f" · <@{c.data['owner_id']}>"
            lines.append(f"{mark}**{c.name}** (#{c.id}) — L{c.level} {c.cls.name} · HP {hp['current']}/{hp['max']} "
                         f"· AC {c.ac()}{owner}")
        e = discord.Embed(title="Characters", description="\n".join(lines)[:4000], color=embeds.SHEET_COLOR)
        e.set_footer(text="⭐ = your active character")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @character.command(name="select", description="Choose which of your characters commands act on")
    @app_commands.autocomplete(character=character_autocomplete)
    async def select(self, interaction: discord.Interaction, character: str) -> None:
        ch = resolve_character(interaction, character, write=True)
        storage(interaction).set_active(guild_id(interaction), interaction.user.id, ch.id)
        await interaction.response.send_message(f"⭐ **{ch.name}** is now your active character.", ephemeral=True)

    @character.command(name="delete", description="Permanently delete a character")
    @app_commands.autocomplete(character=character_autocomplete)
    async def delete(self, interaction: discord.Interaction, character: str) -> None:
        ch = resolve_character(interaction, character, write=True)
        view = ConfirmDelete(interaction.user.id, ch.id, ch.name)
        await interaction.response.send_message(
            f"Really delete **{ch.name}** (L{ch.level} {ch.cls.name})? This can't be undone.", view=view,
            ephemeral=True)

    @character.command(name="edit", description="Edit name, alignment, homeland and description")
    @app_commands.autocomplete(character=character_autocomplete)
    async def edit(self, interaction: discord.Interaction, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        await interaction.response.send_modal(EditDetailsModal(ch))

    @character.command(name="notes", description="Edit free-form notes (spells, languages, contacts...)")
    @app_commands.autocomplete(character=character_autocomplete)
    async def notes(self, interaction: discord.Interaction, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        await interaction.response.send_modal(NotesModal(ch))

    @character.command(name="attributes", description="Set attribute scores (corrections, aging, magic)")
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(str_="Strength", int_="Intellect", wil="Will", dex="Dexterity", con="Constitution",
                           cha="Charisma")
    @app_commands.rename(str_="str", int_="int")
    async def attributes(self, interaction: discord.Interaction,
                         str_: app_commands.Range[int, 3, 18] | None = None,
                         int_: app_commands.Range[int, 3, 18] | None = None,
                         wil: app_commands.Range[int, 3, 18] | None = None,
                         dex: app_commands.Range[int, 3, 18] | None = None,
                         con: app_commands.Range[int, 3, 18] | None = None,
                         cha: app_commands.Range[int, 3, 18] | None = None,
                         character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        changes = []
        for attr, val in zip(rules.ATTRIBUTES, (str_, int_, wil, dex, con, cha)):
            if val is not None and val != ch.score(attr):
                changes.append(f"{attr} {ch.score(attr)} → {val}")
                ch.data["attributes"][attr] = val
        if not changes:
            raise UserError("Nothing to change. Pass one or more scores, e.g. `/character attributes str:14`.")
        save(interaction, ch)
        await interaction.response.send_message(f"📝 **{ch.name}**: " + ", ".join(changes))

    @character.command(name="set_level", description="Set level directly (Judge corrections). Use /levelup normally.")
    @app_commands.autocomplete(character=character_autocomplete)
    async def set_level(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 14],
                        character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        if level > ch.cls.max_level:
            raise UserError(f"{ch.cls.name}s max out at level {ch.cls.max_level}.")
        ch.data["level"] = level
        save(interaction, ch)
        await interaction.response.send_message(
            f"📝 **{ch.name}** is now level {level} ({ch.cls.title(level)}). Adjust HP with `/hp set` if needed.")

    @character.command(name="barbarian", description="Set a barbarian's region and damage-bonus type")
    @app_commands.autocomplete(character=character_autocomplete)
    async def barbarian(self, interaction: discord.Interaction,
                        region: Literal["jutland", "skysostan", "ivory"] | None = None,
                        damage_bonus: Literal["melee", "missile"] | None = None,
                        character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        if ch.cls.key != "barbarian":
            raise UserError(f"**{ch.name}** isn't a barbarian.")
        if region:
            ch.options["barbarian_region"] = region
        if damage_bonus:
            ch.options["barbarian_damage"] = damage_bonus
        save(interaction, ch)
        r = rules.BARBARIAN_REGIONS.get(ch.options.get("barbarian_region", ""), {})
        await interaction.response.send_message(
            f"🪓 **{ch.name}**: region {r.get('label', 'unset')}, damage bonus on "
            f"{ch.options.get('barbarian_damage', 'melee')} attacks.")

    @character.command(name="training",
                       description="Extra armor, weapons, or fighting styles from class choices and powers")
    @app_commands.describe(
        armor="Heaviest armor the character may wear (e.g. from a sigil or class power)",
        add_weapon="A weapon the character is trained in beyond the class list",
        remove_weapon="Undo an added weapon",
        style_choice="The fighting style(s) your class picks (e.g. dual weapons OR weapon and shield)",
        dual="Grant or remove the dual weapon style (class powers, Judge rulings)",
        two_handed="Two-handed weapon style", weapon_and_shield="Weapon and shield style",
        reset="Clear all training changes and go back to the class defaults")
    @app_commands.autocomplete(add_weapon=catalog_autocomplete, style_choice=_style_choice_autocomplete,
                               character=character_autocomplete)
    async def training(self, interaction: discord.Interaction,
                       armor: Literal["class default", "very light", "light", "medium", "heavy"] | None = None,
                       add_weapon: str | None = None, remove_weapon: str | None = None,
                       style_choice: str | None = None, dual: bool | None = None, two_handed: bool | None = None,
                       weapon_and_shield: bool | None = None, reset: bool = False,
                       character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        opts = ch.options
        if style_choice:
            if not ch.cls.style_choice:
                raise UserError(f"{ch.cls.name}s don't choose fighting styles; use `dual`, `two_handed` or "
                                f"`weapon_and_shield` to grant or remove one.")
            labels = {k: v.lower() for k, v in rules.STYLE_LABELS.items()}
            picks = [s for s in rules.STYLES if s in style_choice.split(",") or labels[s] in style_choice.lower()]
            try:
                ch.set_style_choice(picks)
            except ValueError as e:
                raise UserError(str(e)) from None
        if reset:
            for k in ("armor_override", "extra_weapons", "style_overrides"):
                opts.pop(k, None)
        if armor == "class default":
            opts.pop("armor_override", None)
        elif armor:
            opts["armor_override"] = armor
        for ref, adding in ((add_weapon, True), (remove_weapon, False)):
            if not ref:
                continue
            w = rules.WEAPONS.get(ref) or rules.lookup_weapon(ref)
            if not w:
                raise UserError(f"I don't know a weapon called **{ref}**.")
            extra = opts.setdefault("extra_weapons", [])
            if adding and w.key not in extra:
                extra.append(w.key)
            elif not adding and w.key in extra:
                extra.remove(w.key)
        for style, val in (("dual", dual), ("two_handed", two_handed), ("weapon_and_shield", weapon_and_shield)):
            if val is not None:
                opts.setdefault("style_overrides", {})[style] = val
        save(interaction, ch)
        weapons = ", ".join(rules.WEAPONS[k].name for k in opts.get("extra_weapons", [])) or "none"
        styles = ", ".join(rules.STYLE_LABELS[s] for s in rules.STYLES if s in ch.styles())
        await interaction.response.send_message(
            f"🎓 **{ch.name}** training — armor up to **{opts.get('armor_override') or ch.cls.armor}** · "
            f"extra weapons: {weapons} · styles: {styles}\nAC {ch.ac()} · attack throw {ch.attack_throw()}+")

    @character.command(name="powers", description="List class powers for the character's level")
    @app_commands.describe(all_levels="Also describe the powers still to come", private="Only show it to you")
    @app_commands.autocomplete(character=any_character_autocomplete)
    async def powers(self, interaction: discord.Interaction, all_levels: bool = False, private: bool = False,
                     character: str | None = None) -> None:
        ch = resolve_character(interaction, character, write=False)
        e = embeds.powers_embed(ch, all_levels)
        paths = rules.power_paths(ch.cls.key)
        if paths and not ch.options.get("power_path"):
            e.description = (f"This class follows one of: **{', '.join(paths)}**. Pick it with "
                             f"`/character path` to see that path's powers.")
        await interaction.response.send_message(embed=e, ephemeral=private)

    @character.command(name="path", description="Choose a tradition, sect, dark path, or sigil (decides path powers)")
    @app_commands.autocomplete(path=_path_autocomplete, character=character_autocomplete)
    async def path(self, interaction: discord.Interaction, path: str, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        paths = rules.power_paths(ch.cls.key)
        if not paths:
            raise UserError(f"{ch.cls.name}s don't choose a path with its own powers.")
        match = next((p for p in paths if p.lower() == path.lower()), None) or \
            next((p for p in paths if path.lower() in p.lower()), None)
        if not match:
            raise UserError(f"Choose one of: {', '.join(paths)}.")
        ch.options["power_path"] = match
        save(interaction, ch)
        have, _ = embeds.powers_split(ch)
        gained = [p["name"] for p in have if p["name"].startswith(match + ":")]
        await interaction.response.send_message(
            f"🧭 **{ch.name}** follows **{match}**." + (f" Path powers so far: {', '.join(gained)}." if gained else ""))

    @character.command(name="give", description="Hand a character to another player (Judges only)")
    @app_commands.autocomplete(character=any_character_autocomplete)
    async def give(self, interaction: discord.Interaction, character: str, player: discord.Member) -> None:
        if not is_judge(interaction):
            raise UserError("Only a Judge can reassign characters.")
        ch = resolve_character(interaction, character, write=True)
        ch.data["owner_id"] = player.id
        save(interaction, ch)
        await interaction.response.send_message(f"🤝 **{ch.name}** now belongs to {player.mention}.")

    # -- experience --------------------------------------------------------
    @app_commands.command(name="xp", description="Award (or remove) experience points")
    @app_commands.guild_only()
    @app_commands.describe(amount="XP to add (negative to remove)",
                           apply_bonus="Apply the key-attribute XP bonus (default yes)")
    @app_commands.autocomplete(character=character_autocomplete)
    async def xp(self, interaction: discord.Interaction, amount: int, apply_bonus: bool = True,
                 character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        pct = ch.xp_bonus_pct() if apply_bonus and amount > 0 else 0
        gained = amount + (amount * pct) // 100
        ch.data["xp"] = max(0, int(ch.data["xp"]) + gained)
        save(interaction, ch)
        msg = f"✨ **{ch.name}** {'gains' if gained >= 0 else 'loses'} **{abs(gained):,} XP**"
        if pct:
            msg += f" ({amount:,} +{pct}%)"
        nxt = ch.xp_for_next()
        msg += f" → {ch.data['xp']:,}" + (f" / {nxt:,}" if nxt else "")
        if ch.can_level():
            msg += f"\n⬆️ Enough XP for level {ch.level + 1}! Use `/levelup`."
        await interaction.response.send_message(msg)

    @app_commands.command(name="levelup", description="Advance a level and re-roll hit points")
    @app_commands.guild_only()
    @app_commands.describe(force="Judge only: level up even without enough XP")
    @app_commands.autocomplete(character=character_autocomplete)
    async def levelup(self, interaction: discord.Interaction, force: bool = False,
                      character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        if not ch.can_level():
            if not (force and is_judge(interaction)):
                nxt = ch.xp_for_next()
                if nxt is None:
                    raise UserError(f"**{ch.name}** is already at maximum level.")
                raise UserError(f"**{ch.name}** needs {nxt:,} XP for level {ch.level + 1} "
                                f"(has {ch.data['xp']:,}).")
        try:
            old, new, detail = ch.level_up()
        except ValueError as e:
            raise UserError(str(e)) from e
        save(interaction, ch)
        e = discord.Embed(title=f"⬆️ {ch.name} reaches level {ch.level}!",
                          description=f"*{ch.cls.title(ch.level)}*", color=embeds.HIT_COLOR)
        e.add_field(name="Hit points", value=f"{detail}\nMax HP **{old} → {new}**", inline=False)
        e.add_field(name="Attack throw", value=f"{ch.attack_throw()}+", inline=True)
        e.add_field(name="Saves", value=" · ".join(f"{rules.SAVE_LABELS[s][:4]} {ch.save_target(s)}+"
                                                  for s in rules.SAVES), inline=True)
        e.set_footer(text="Check your class for new powers, proficiencies, and spells.")
        await interaction.response.send_message(embed=e)


class ConfirmDelete(discord.ui.View):
    def __init__(self, user_id: int, char_id: int, name: str):
        super().__init__(timeout=60)
        self.user_id, self.char_id, self.name = user_id, char_id, name

    @discord.ui.button(label="Delete forever", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        orphans = storage(interaction).delete(self.char_id)
        self.stop()
        note = ("\n-# Their animals now have no owner: " + ", ".join(f"**{a.name}**" for a in orphans)
                + ". Give them a new one with `/animal edit owner:`.") if orphans else ""
        await interaction.response.edit_message(content=f"🗑️ **{self.name}** has been deleted.{note}", view=None)

    @discord.ui.button(label="Keep", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Kept.", view=None)


class EditDetailsModal(discord.ui.Modal, title="Edit character"):
    char_name = discord.ui.TextInput(label="Name", max_length=60)
    alignment = discord.ui.TextInput(label="Alignment", max_length=20, required=False)
    homeland = discord.ui.TextInput(label="Homeland", required=False, max_length=60)
    sex_age = discord.ui.TextInput(label="Sex and age (e.g. 'Female, 22')", required=False, max_length=40)
    bio = discord.ui.TextInput(label="Appearance, background, personality", required=False,
                               style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, ch):
        super().__init__()
        self.ch = ch
        d = ch.data
        self.char_name.default = d["name"]
        self.alignment.default = d.get("alignment") or None
        self.homeland.default = d.get("homeland") or None
        self.sex_age.default = ", ".join(x for x in (d.get("sex"), str(d.get("age") or "")) if x) or None
        self.bio.default = d.get("description") or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        d = self.ch.data
        d["name"] = self.char_name.value.strip() or d["name"]
        d["alignment"] = self.alignment.value.strip()
        d["homeland"] = self.homeland.value.strip()
        parts = [p.strip() for p in self.sex_age.value.split(",")]
        d["sex"] = parts[0] if parts and parts[0] else ""
        d["age"] = parts[1] if len(parts) > 1 else ""
        d["description"] = self.bio.value.strip()
        save(interaction, self.ch)
        await interaction.response.send_message(f"📝 Updated **{self.ch.name}**.", ephemeral=True)


class NotesModal(discord.ui.Modal, title="Character notes"):
    text = discord.ui.TextInput(label="Notes", style=discord.TextStyle.paragraph, required=False,
                                max_length=4000)

    def __init__(self, ch):
        super().__init__()
        self.ch = ch
        self.text.default = ch.data.get("notes") or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.ch.data["notes"] = self.text.value
        save(interaction, self.ch)
        await interaction.response.send_message(f"📖 Notes saved for **{self.ch.name}**.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Characters(bot))
