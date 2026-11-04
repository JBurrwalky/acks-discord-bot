"""Initiative roster: /encounter ..., a setup wizard, and a live roster message with buttons.

One roster per channel, saved in the database so it survives bot restarts.
"""
from __future__ import annotations

import logging
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds
from acks import encounter as enc_rules
from acks.character import Character
from acks.dice import fmt_mod

from .common import (UserError, any_character_autocomplete, guild_id, is_judge, resolve_character, send_error,
                     storage)

log = logging.getLogger("acks.encounter")

SIDE_ICONS = {"party": "🛡️", "ally": "🤝", "enemy": "💀"}
ENCOUNTER_COLOR = discord.Color.from_rgb(170, 40, 40)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _channel_key(interaction: discord.Interaction) -> tuple[int, int]:
    if interaction.channel_id is None:
        raise UserError("Encounters run in a server channel.")
    return guild_id(interaction), interaction.channel_id


def load(interaction: discord.Interaction) -> dict:
    gid, cid = _channel_key(interaction)
    enc = storage(interaction).get_encounter(gid, cid)
    if enc is None:
        raise UserError("There's no encounter running in this channel. Start one with `/encounter start`.")
    return enc


def save(interaction: discord.Interaction, enc: dict) -> None:
    gid, cid = _channel_key(interaction)
    storage(interaction).save_encounter(gid, cid, enc)


def check_manager(interaction: discord.Interaction, enc: dict) -> None:
    if interaction.user.id != enc.get("owner_id") and not is_judge(interaction):
        raise UserError("Only the Judge or whoever started this encounter can change it.")


def char_lookup(interaction: discord.Interaction):
    store = storage(interaction)
    gid = interaction.guild_id

    def get(char_id: int) -> Character | None:
        ch = store.get(char_id)
        return ch if ch and ch.data["guild_id"] == gid else None
    return get


def roster_embed(enc: dict, characters) -> discord.Embed:
    rnd = enc["round"]
    e = discord.Embed(title=f"⚔️ Initiative — Round {rnd}" if rnd else "⚔️ Initiative — not rolled yet",
                      color=ENCOUNTER_COLOR)
    lines, prev = [], None
    for c in enc_rules.order(enc):
        tie = " ⇄" if c["total"] is not None and c["total"] == prev else ""
        prev = c["total"]
        num = f"`{c['total']:>3}`" if c["total"] is not None else "` — `"
        count = f" ×{c['count']}" if c["count"] > 1 else ""
        extra = ""
        if c["kind"] == "pc":
            ch = characters(c["char_id"])
            if ch:
                hp = ch.data["hp"]
                extra = f" · HP {hp['current']}/{hp['max']}" + (" 💀" if hp["current"] <= 0 else "")
        lines.append(f"{num}{tie} {SIDE_ICONS.get(c['side'], '')} **{c['name']}**{count} · "
                     f"{enc_rules.describe(c)}{extra}")
    text = "\n".join(lines) or "*Nobody in the roster yet. Use ➕ Add.*"
    if len(text) > 4000:
        text = text[:3990].rsplit("\n", 1)[0] + "\n…"
    e.description = text
    ties = enc_rules.tie_notes(enc)
    if ties:
        e.add_field(name="⇄ Ties", value="\n".join(ties)[:1024], inline=False)
    party, foes = enc_rules.side_size(enc, "party"), enc_rules.side_size(enc, "enemy")
    e.set_footer(text=f"Party & allies {party} · Enemies {foes} · Count down from the highest number. "
                      f"Everyone rolls again each round (🎲 Next round).")
    return e


def roster_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action in ("round", "add", "remove", "end"):
        view.add_item(EncounterButton(action))
    return view


async def refresh_roster_message(interaction: discord.Interaction, enc: dict) -> None:
    """Edit the posted roster message after a change made elsewhere (slash command, ephemeral menu)."""
    if not enc.get("message_id") or interaction.channel is None:
        return
    try:
        msg = interaction.channel.get_partial_message(enc["message_id"])
        await msg.edit(embed=roster_embed(enc, char_lookup(interaction)), view=roster_view())
    except (discord.HTTPException, AttributeError):
        pass


async def post_roster(interaction: discord.Interaction, enc: dict, content: str | None = None) -> None:
    """Send a fresh public roster message and remember it as the one to keep updated."""
    kwargs = dict(embed=roster_embed(enc, char_lookup(interaction)), view=roster_view())
    if interaction.response.is_done():
        msg = await interaction.followup.send(content=content, wait=True, **kwargs)
    else:
        await interaction.response.send_message(content=content, **kwargs)
        msg = await interaction.original_response()
    if msg is not None:
        enc["message_id"] = msg.id
        save(interaction, enc)


def parse_combatant_form(name: str, modifier: str, count: str, side: str, individually: str) -> dict:
    try:
        mod = int(modifier.strip().replace("+", "") or 0)
        n = int(count.strip() or 1)
    except ValueError:
        raise UserError("The initiative modifier and number must be whole numbers (e.g. `-1`, `+2`, `4`).")
    if not -20 <= mod <= 20 or not 1 <= n <= 500:
        raise UserError("Keep the modifier between -20 and +20 and the number between 1 and 500.")
    s = side.strip().lower() or "enemy"
    side_key = "ally" if s.startswith(("a", "f", "p")) else "enemy"   # ally / friend / party
    each = individually.strip().lower().startswith(("y", "t", "1"))
    return {"name": name.strip(), "modifier": mod, "count": n, "side": side_key, "individually": each}


class CombatantModal(discord.ui.Modal, title="Add a combatant or group"):
    cname = discord.ui.TextInput(label="Name", placeholder="Goblins, Ogre chieftain, Hired spearmen…",
                                 max_length=60)
    modifier = discord.ui.TextInput(label="Initiative modifier", default="0", max_length=4,
                                    placeholder="e.g. -1, 0, +2")
    count = discord.ui.TextInput(label="How many", default="1", max_length=3)
    side = discord.ui.TextInput(label="Side: enemy or ally", default="enemy", max_length=10)
    individually = discord.ui.TextInput(label="Roll each one separately? (yes/no)", default="no", max_length=3)

    def __init__(self, on_done):
        super().__init__()
        self.on_done = on_done

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            entry = parse_combatant_form(self.cname.value, self.modifier.value, self.count.value, self.side.value,
                                         self.individually.value)
            await self.on_done(interaction, entry)
        except UserError as e:
            await send_error(interaction, str(e))

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Combatant form error", exc_info=error)
        await send_error(interaction, f"Something went wrong (`{type(error).__name__}`). Details are in the bot's log.")


# ---------------------------------------------------------------------------
# roster buttons (persistent across restarts; the channel identifies the encounter)
# ---------------------------------------------------------------------------

BUTTONS = {
    "round": ("Next round", "🎲", discord.ButtonStyle.success),
    "add": ("Add", "➕", discord.ButtonStyle.primary),
    "remove": ("Remove", "➖", discord.ButtonStyle.secondary),
    "end": ("End encounter", "🗑️", discord.ButtonStyle.danger),
}


class EncounterButton(discord.ui.DynamicItem[discord.ui.Button], template=r"acks:enc:(?P<action>\w+)"):
    def __init__(self, action: str):
        label, emoji, style = BUTTONS[action]
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"acks:enc:{action}"))
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            enc = load(interaction)
            check_manager(interaction, enc)
            await getattr(self, f"_{self.action}")(interaction, enc)
        except UserError as e:
            await send_error(interaction, str(e))

    async def _round(self, interaction: discord.Interaction, enc: dict) -> None:
        enc_rules.roll_round(enc, char_lookup(interaction))
        enc["message_id"] = interaction.message.id if interaction.message else enc.get("message_id")
        save(interaction, enc)
        await interaction.response.edit_message(embed=roster_embed(enc, char_lookup(interaction)),
                                                view=roster_view())

    async def _add(self, interaction: discord.Interaction, enc: dict) -> None:
        async def done(modal_ix: discord.Interaction, entry: dict) -> None:
            fresh = load(modal_ix)
            added = add_entry(modal_ix, fresh, entry)
            save(modal_ix, fresh)
            await modal_ix.response.edit_message(embed=roster_embed(fresh, char_lookup(modal_ix)),
                                                 view=roster_view())
            log.info("Added %s to encounter", ", ".join(a["name"] for a in added))
        await interaction.response.send_modal(CombatantModal(done))

    async def _remove(self, interaction: discord.Interaction, enc: dict) -> None:
        if not enc["combatants"]:
            raise UserError("The roster is already empty.")
        await interaction.response.send_message("Who leaves the fight?", view=RemoveView(enc), ephemeral=True)

    async def _end(self, interaction: discord.Interaction, enc: dict) -> None:
        await interaction.response.send_message(
            f"End this encounter and delete its roster ({len(enc['combatants'])} entries, round {enc['round']})?",
            view=ConfirmEnd(), ephemeral=True)


def add_entry(interaction: discord.Interaction, enc: dict, entry: dict) -> list[dict]:
    """Add an NPC/group from form values; mid-fight arrivals roll straight away for the current round."""
    try:
        added = enc_rules.add_npc(enc, entry["name"], entry["modifier"], entry["count"], entry["side"],
                                  entry["individually"])
    except ValueError as e:
        raise UserError(str(e)) from e
    if enc["round"] > 0:
        for c in added:
            enc_rules.roll_one(c, char_lookup(interaction))
    return added


class RemoveView(discord.ui.View):
    def __init__(self, enc: dict):
        super().__init__(timeout=300)
        self.add_item(RemoveSelect(enc))


class RemoveSelect(discord.ui.Select):
    def __init__(self, enc: dict):
        opts = [discord.SelectOption(
            label=f"{c['name']}{' ×' + str(c['count']) if c['count'] > 1 else ''}"[:100], value=str(c["id"]),
            description=f"{enc_rules.SIDES[c['side']]} · {enc_rules.describe(c)}"[:100])
            for c in enc_rules.order(enc)[:25]]
        super().__init__(placeholder="Choose combatants to remove", options=opts, min_values=1,
                         max_values=len(opts))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            enc = load(interaction)
            check_manager(interaction, enc)
            gone = []
            for v in self.values:
                try:
                    gone.append(enc_rules.remove(enc, int(v))["name"])
                except ValueError:
                    pass
            save(interaction, enc)
            await interaction.response.edit_message(content=f"➖ Removed {', '.join(gone) or 'nobody'}.", view=None)
            await refresh_roster_message(interaction, enc)
        except UserError as e:
            await send_error(interaction, str(e))


class ConfirmEnd(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="End and delete roster", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            enc = load(interaction)
            check_manager(interaction, enc)
        except UserError as e:
            await send_error(interaction, str(e))
            return
        gid, cid = _channel_key(interaction)
        storage(interaction).delete_encounter(gid, cid)
        self.stop()
        await interaction.response.edit_message(
            content="🗑️ Encounter ended and roster deleted. Start a new one with `/encounter start`.", view=None)
        if enc.get("message_id") and interaction.channel is not None:
            try:
                await interaction.channel.get_partial_message(enc["message_id"]).edit(
                    content=f"🏁 Encounter ended after {enc['round']} round(s).", view=None)
            except (discord.HTTPException, AttributeError):
                pass

    @discord.ui.button(label="Keep fighting", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Encounter kept.", view=None)


# ---------------------------------------------------------------------------
# setup wizard
# ---------------------------------------------------------------------------

class EncounterWizard(discord.ui.View):
    """Step 1: tick the party. Step 2: add other combatants and groups. Then roll."""

    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=1800)
        self.owner_id = interaction.user.id
        store = storage(interaction)
        gid = guild_id(interaction)
        active = store.active_character_ids(gid)
        chars = store.list_for_guild(gid)
        # active characters first, so they make the 25-option cut in big servers
        chars.sort(key=lambda c: (c.id not in active, c.name.lower()))
        self.characters = chars[:25]
        self.selected: list[int] = [c.id for c in self.characters if c.id in active]
        self.others: list[dict] = []
        self.step = "party"
        existing = store.get_encounter(gid, interaction.channel_id) if interaction.channel_id else None
        self.replacing = existing
        self.render()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This setup belongs to someone else.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        if isinstance(error, UserError):
            await send_error(interaction, str(error))
            return
        log.exception("Encounter wizard error", exc_info=error)
        await send_error(interaction, f"Something went wrong (`{type(error).__name__}`). Details are in the bot's log.")

    def embed(self) -> discord.Embed:
        e = discord.Embed(title=f"⚔️ New encounter — step {1 if self.step == 'party' else 2} of 2",
                          color=ENCOUNTER_COLOR)
        if self.step == "party":
            e.description = ("**Who's in the party?** Everyone's active character is ticked. Untick anyone who "
                             "isn't here, tick any extras, then press **Next**.\n"
                             "Each character's initiative bonus (DEX, Combat Reflexes, Animal Reflexes, "
                             "Graceful Fighting, fighting style…) comes from their sheet every round.")
            names = [c for c in self.characters if c.id in self.selected]
            e.add_field(name=f"Party ({len(names)})",
                        value="\n".join(f"🛡️ **{c.name}** · {fmt_mod(c.initiative_bonus().total)}"
                                        for c in names) or "*nobody yet*", inline=False)
            if not self.characters:
                e.add_field(name="No characters", value="Nobody in this server has a character yet. You can "
                                                        "still add combatants by hand in the next step.")
        else:
            e.description = ("**Add everyone else**: monsters, NPCs, hirelings, groups. Press **Add combatant** "
                             "once per combatant or group. A group shares one roll, as ACKS suggests for "
                             "identical monsters, unless you choose to roll each separately.\n"
                             "When the roster is ready, press **Roll initiative!**")
            lines = [f"🛡️ **{c.name}**" for c in self.characters if c.id in self.selected]
            lines += [f"{SIDE_ICONS[o['side']]} **{o['name']}**{' ×' + str(o['count']) if o['count'] > 1 else ''}"
                      f" · {fmt_mod(o['modifier'])}{' · rolls separately' if o['individually'] else ''}"
                      for o in self.others]
            e.add_field(name=f"Roster ({len(lines)})", value="\n".join(lines)[:1024] or "*empty*", inline=False)
        if self.replacing:
            e.add_field(name="⚠️ Replaces the current encounter",
                        value=f"This channel already has an encounter (round {self.replacing['round']}, "
                              f"{len(self.replacing['combatants'])} entries). Rolling will delete it.",
                        inline=False)
        return e

    def render(self) -> None:
        self.clear_items()
        if self.step == "party":
            if self.characters:
                self.add_item(PartySelect(self))
            self.add_item(WizardButton("Next: other combatants", "➡️", discord.ButtonStyle.primary, self._next))
        else:
            self.add_item(WizardButton("Add combatant", "➕", discord.ButtonStyle.primary, self._add))
            if self.others:
                self.add_item(PendingRemoveSelect(self))
            self.add_item(WizardButton("Back", "⬅️", discord.ButtonStyle.secondary, self._back))
            roll = WizardButton("Roll initiative!", "🎲", discord.ButtonStyle.success, self._roll)
            roll.disabled = not (self.selected or self.others)
            self.add_item(roll)
        self.add_item(WizardButton("Cancel", "✖️", discord.ButtonStyle.danger, self._cancel, row=4))

    async def refresh(self, interaction: discord.Interaction) -> None:
        self.render()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _next(self, interaction: discord.Interaction) -> None:
        self.step = "others"
        await self.refresh(interaction)

    async def _back(self, interaction: discord.Interaction) -> None:
        self.step = "party"
        await self.refresh(interaction)

    async def _add(self, interaction: discord.Interaction) -> None:
        async def done(modal_ix: discord.Interaction, entry: dict) -> None:
            self.others.append(entry)
            await self.refresh(modal_ix)
        await interaction.response.send_modal(CombatantModal(done))

    async def _cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(content="Encounter setup cancelled.", embeds=[], view=None)

    async def _roll(self, interaction: discord.Interaction) -> None:
        enc = enc_rules.new_encounter(self.owner_id)
        lookup = char_lookup(interaction)
        for cid in self.selected:
            ch = lookup(cid)
            if ch:
                enc_rules.add_character(enc, ch)
        for o in self.others:
            try:
                enc_rules.add_npc(enc, o["name"], o["modifier"], o["count"], o["side"], o["individually"])
            except ValueError as e:
                raise UserError(str(e)) from e
        enc_rules.roll_round(enc, lookup)
        save(interaction, enc)
        self.stop()
        await interaction.response.edit_message(
            content="✅ Initiative rolled. The roster is posted in the channel; use its buttons or "
                    "`/encounter` commands to run the fight.", embeds=[], view=None)
        await post_roster(interaction, enc)


class WizardButton(discord.ui.Button):
    def __init__(self, label: str, emoji: str, style: discord.ButtonStyle, handler, row: int | None = None):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.handler = handler

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.handler(interaction)


class PartySelect(discord.ui.Select):
    def __init__(self, wiz: EncounterWizard):
        opts = [discord.SelectOption(label=c.name[:100], value=str(c.id), default=c.id in wiz.selected,
                                     description=f"{embeds.level_label(c)} · init "
                                                 f"{fmt_mod(c.initiative_bonus().total)}"[:100])
                for c in wiz.characters]
        super().__init__(placeholder="Party members", options=opts, min_values=0, max_values=len(opts), row=0)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wiz.selected = [int(v) for v in self.values]
        await self.wiz.refresh(interaction)


class PendingRemoveSelect(discord.ui.Select):
    def __init__(self, wiz: EncounterWizard):
        opts = [discord.SelectOption(label=f"{o['name']}{' ×' + str(o['count']) if o['count'] > 1 else ''}"[:100],
                                     value=str(i)) for i, o in enumerate(wiz.others[:25])]
        super().__init__(placeholder="Remove a combatant you added", options=opts, row=1)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        del self.wiz.others[int(self.values[0])]
        await self.wiz.refresh(interaction)


# ---------------------------------------------------------------------------
# slash commands
# ---------------------------------------------------------------------------

async def roster_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    try:
        enc = load(interaction)
    except UserError:
        return []
    return [app_commands.Choice(name=f"{c['name']}{' ×' + str(c['count']) if c['count'] > 1 else ''}"[:100],
                                value=str(c["id"]))
            for c in enc_rules.order(enc) if current.lower() in c["name"].lower()][:25]


class Encounter(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(name="encounter", description="Initiative roster for a fight in this channel",
                               guild_only=True)

    @group.command(name="start", description="Set up a new encounter: party, other combatants, then roll")
    async def start(self, interaction: discord.Interaction) -> None:
        wiz = EncounterWizard(interaction)
        await interaction.response.send_message(embed=wiz.embed(), view=wiz, ephemeral=True)

    @group.command(name="show", description="Post the current initiative roster")
    async def show(self, interaction: discord.Interaction) -> None:
        enc = load(interaction)
        await post_roster(interaction, enc)

    @group.command(name="next_round", description="Start the next round: everyone rolls initiative again")
    async def next_round(self, interaction: discord.Interaction) -> None:
        enc = load(interaction)
        check_manager(interaction, enc)
        enc_rules.roll_round(enc, char_lookup(interaction))
        save(interaction, enc)
        await post_roster(interaction, enc)

    @group.command(name="add", description="Add a monster, NPC, or group (rolls now if the fight has started)")
    @app_commands.describe(name="Name, e.g. 'Goblins' or 'Ogre chieftain'", modifier="Initiative modifier",
                           count="How many in the group", side="Which side they fight on",
                           individually="Roll each one separately instead of one roll for the group")
    async def add(self, interaction: discord.Interaction, name: str,
                  modifier: app_commands.Range[int, -20, 20] = 0, count: app_commands.Range[int, 1, 500] = 1,
                  side: Literal["enemy", "ally"] = "enemy", individually: bool = False) -> None:
        enc = load(interaction)
        check_manager(interaction, enc)
        added = add_entry(interaction, enc,
                          {"name": name, "modifier": modifier, "count": count, "side": side,
                           "individually": individually})
        save(interaction, enc)
        rolled = ", ".join(f"{c['name']} ({c['total']})" for c in added if c["total"] is not None)
        await post_roster(interaction, enc, content=f"➕ Added {', '.join(c['name'] for c in added)}"
                                                    + (f" · rolled {rolled}" if rolled else ""))

    @group.command(name="add_character", description="Add a player character to the roster")
    @app_commands.autocomplete(character=any_character_autocomplete)
    async def add_character(self, interaction: discord.Interaction, character: str) -> None:
        enc = load(interaction)
        check_manager(interaction, enc)
        ch = resolve_character(interaction, character, write=False)
        try:
            c = enc_rules.add_character(enc, ch)
        except ValueError as e:
            raise UserError(str(e)) from e
        if enc["round"] > 0:
            enc_rules.roll_one(c, char_lookup(interaction))
        save(interaction, enc)
        await post_roster(interaction, enc, content=f"➕ **{ch.name}** joins the fight"
                                                    + (f" with initiative {c['total']}." if c["total"] else "."))

    @group.command(name="remove", description="Remove a combatant or group from the roster")
    @app_commands.autocomplete(combatant=roster_autocomplete)
    async def remove_cmd(self, interaction: discord.Interaction, combatant: str) -> None:
        enc = load(interaction)
        check_manager(interaction, enc)
        target = None
        if combatant.isdigit():
            target = next((c for c in enc["combatants"] if c["id"] == int(combatant)), None)
        if target is None:
            target = next((c for c in enc["combatants"] if c["name"].lower() == combatant.lower()), None)
        if target is None:
            raise UserError(f"**{combatant}** isn't in the roster.")
        enc_rules.remove(enc, target["id"])
        save(interaction, enc)
        await post_roster(interaction, enc, content=f"➖ Removed **{target['name']}**.")

    @group.command(name="end", description="End the encounter and delete its roster")
    async def end(self, interaction: discord.Interaction) -> None:
        enc = load(interaction)
        check_manager(interaction, enc)
        await interaction.response.send_message(
            f"End this encounter and delete its roster ({len(enc['combatants'])} entries, round {enc['round']})?",
            view=ConfirmEnd(), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    bot.add_dynamic_items(EncounterButton)
    await bot.add_cog(Encounter(bot))
