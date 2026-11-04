"""Helpers shared by every cog: finding characters, permissions, autocomplete, sheet buttons."""
from __future__ import annotations

import os
import re

import discord
from discord import app_commands

from acks import embeds, rules
from acks.character import Character
from acks.storage import Storage

JUDGE_ROLE = os.getenv("JUDGE_ROLE", "Judge")


class UserError(Exception):
    """An error whose message should be shown to the user as-is."""


def storage(interaction: discord.Interaction) -> Storage:
    return interaction.client.storage  # type: ignore[attr-defined]


def is_judge(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_guild:
        return True
    return any(r.name.lower() == JUDGE_ROLE.lower() for r in member.roles)


def guild_id(interaction: discord.Interaction) -> int:
    if interaction.guild_id is None:
        raise UserError("Character commands only work inside a server.")
    return interaction.guild_id


def resolve_character(interaction: discord.Interaction, ref: str | None, *, write: bool = True) -> Character:
    """Find a character by autocomplete id, name, or the user's active character.

    write=True requires the caller to own the character or be a Judge.
    """
    store = storage(interaction)
    gid = guild_id(interaction)
    ch: Character | None = None
    if ref:
        m = re.fullmatch(r"#?(\d+)", ref.strip())
        if m:
            ch = store.get(int(m.group(1)))
            if ch and ch.data["guild_id"] != gid:
                ch = None
        if ch is None:
            pool = store.list_for_user(gid, interaction.user.id)
            if not write or is_judge(interaction):
                pool += [c for c in store.list_for_guild(gid) if c.id not in {p.id for p in pool}]
            wanted = ref.strip().lower()
            exact = [c for c in pool if c.name.lower() == wanted]
            partial = [c for c in pool if wanted in c.name.lower()]
            hits = exact or partial
            if len(hits) > 1:
                raise UserError(f"More than one character matches **{ref}**: "
                                + ", ".join(f"{c.name} (#{c.id})" for c in hits[:10]))
            ch = hits[0] if hits else None
        if ch is None:
            raise UserError(f"I couldn't find a character called **{ref}**.")
    else:
        ch = store.get_active(gid, interaction.user.id)
        if ch is None:
            mine = store.list_for_user(gid, interaction.user.id)
            if not mine:
                raise UserError("You don't have a character yet. Start one with `/create`.")
            raise UserError("You have several characters. Pick one with `/character select`, "
                            "or pass the `character` option.")
    if write and ch.data["owner_id"] != interaction.user.id and not is_judge(interaction):
        raise UserError(f"**{ch.name}** belongs to another player. Only they or a Judge can change it.")
    return ch


def save(interaction: discord.Interaction, ch: Character) -> None:
    storage(interaction).save(ch)


async def character_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if interaction.guild_id is None:
        return []
    store = storage(interaction)
    mine = store.list_for_user(interaction.guild_id, interaction.user.id)
    pool = list(mine)
    if is_judge(interaction):
        pool += [c for c in store.list_for_guild(interaction.guild_id) if c.data["owner_id"] != interaction.user.id]
    cur = current.lower()
    out = []
    for c in pool:
        if cur in c.name.lower():
            label = f"{c.name} — L{c.level} {c.cls.name}"
            if c.data["owner_id"] != interaction.user.id:
                label += " (other player)"
            out.append(app_commands.Choice(name=label[:100], value=str(c.id)))
    return out[:25]


async def any_character_autocomplete(interaction: discord.Interaction,
                                     current: str) -> list[app_commands.Choice[str]]:
    """For read-only commands: every character in the server."""
    if interaction.guild_id is None:
        return []
    cur = current.lower()
    out = []
    for c in storage(interaction).list_for_guild(interaction.guild_id):
        if cur in c.name.lower():
            out.append(app_commands.Choice(name=f"{c.name} — L{c.level} {c.cls.name}"[:100], value=str(c.id)))
    return out[:25]


def _active_for_autocomplete(interaction: discord.Interaction) -> Character | None:
    ref = getattr(interaction.namespace, "character", None)
    try:
        return resolve_character(interaction, ref, write=False)
    except UserError:
        return None


async def inventory_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    ch = _active_for_autocomplete(interaction)
    if not ch:
        return []
    cur = current.lower().lstrip("#")
    out = []
    for it in ch.items():
        label = f"#{it['id']} {it['name']}" + (f" ×{it['qty']}" if it["qty"] != 1 else "")
        if cur in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=str(it["id"])))
    return out[:25]


async def equippable_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    ch = _active_for_autocomplete(interaction)
    if not ch:
        return []
    cur = current.lower().lstrip("#")
    out = []
    for it in ch.items():
        if it["kind"] not in ("weapon", "armor", "shield"):
            continue
        label = f"#{it['id']} {it['name']} ({it['kind']})"
        if cur in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=str(it["id"])))
    return out[:25]


def find_item(ch: Character, ref: str) -> dict:
    ref = ref.strip()
    m = re.fullmatch(r"#?(\d+)", ref)
    if m:
        it = ch.item(int(m.group(1)))
        if it:
            return it
    hits = [i for i in ch.items() if i["name"].lower() == ref.lower()] or \
           [i for i in ch.items() if ref.lower() in i["name"].lower()]
    if not hits:
        raise UserError(f"**{ch.name}** isn't carrying anything called **{ref}**. See `/item list`.")
    if len(hits) > 1:
        raise UserError("Which one? " + ", ".join(f"#{i['id']} {i['name']}" for i in hits[:10]))
    return hits[0]


async def catalog_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cur = current.lower()
    out = []
    for w in rules.WEAPONS.values():
        label = f"{w.name} — weapon {w.damage}{'/' + w.damage_2h if w.damage_2h else ''}"
        if cur in label.lower():
            out.append(app_commands.Choice(name=label, value=w.key))
    for a in rules.ARMORS.values():
        label = f"{a.name} — {a.category}{' armor' if a.category != 'shield' else ''} AC {a.ac}"
        if cur in label.lower():
            out.append(app_commands.Choice(name=label, value=a.key))
    return out[:25]


async def send_error(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(f"⚠️ {message}", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ {message}", ephemeral=True)


# ---------------------------------------------------------------------------
# Sheet page buttons (persistent across bot restarts)
# ---------------------------------------------------------------------------

PAGES = {"sheet": "Sheet", "inventory": "Inventory", "notes": "Notes"}


def page_embed(ch: Character, page: str, guild: discord.Guild | None, store: Storage | None = None) -> discord.Embed:
    if page == "inventory":
        return embeds.inventory_embed(ch, store.animals_owned_by(ch.id) if store else None)
    if page == "notes":
        return embeds.notes_embed(ch)
    owner = guild.get_member(ch.data["owner_id"]) if guild else None
    return embeds.sheet_embed(ch, owner.display_name if owner else None)


class SheetPageButton(discord.ui.DynamicItem[discord.ui.Button], template=r"acks:page:(?P<cid>\d+):(?P<page>\w+)"):
    def __init__(self, char_id: int, page: str, active: bool = False):
        super().__init__(discord.ui.Button(
            label=PAGES[page], custom_id=f"acks:page:{char_id}:{page}",
            style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
            emoji={"sheet": "📜", "inventory": "🎒", "notes": "📖"}[page]))
        self.char_id = char_id
        self.page = page

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["cid"]), match["page"])

    async def callback(self, interaction: discord.Interaction) -> None:
        ch = storage(interaction).get(self.char_id)
        if ch is None:
            await interaction.response.send_message("That character no longer exists.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=page_embed(ch, self.page, interaction.guild, storage(interaction)),
                                                view=sheet_view(ch, self.page))


def sheet_view(ch: Character, page: str = "sheet") -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for p in PAGES:
        view.add_item(SheetPageButton(ch.id, p, active=(p == page)))
    return view
