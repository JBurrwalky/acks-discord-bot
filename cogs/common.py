"""Helpers shared by every cog: finding characters, permissions, autocomplete, sheet buttons."""
from __future__ import annotations

import os
import re
from fractions import Fraction

import discord
from discord import app_commands

from acks import embeds, rules, supplies
from acks.animal import Animal
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
            label = f"{c.name} — {embeds.level_label(c)}"
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
            out.append(app_commands.Choice(name=f"{c.name} — {embeds.level_label(c)}"[:100], value=str(c.id)))
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


# ---------------------------------------------------------------------------
# Giving items: any character or animal in the server can receive them
# ---------------------------------------------------------------------------

def resolve_recipient(interaction: discord.Interaction, ref: str) -> Character | Animal:
    """A character or an animal, from autocomplete ('c:12' / 'a:5') or a typed name. Anyone's will do."""
    store = storage(interaction)
    gid = guild_id(interaction)
    m = re.fullmatch(r"([ca]):(\d+)", ref.strip())
    if m:
        target = store.get(int(m.group(2))) if m.group(1) == "c" else store.get_animal(int(m.group(2)))
        if target and target.data["guild_id"] == gid:
            return target
        raise UserError("I couldn't find who that's for.")
    wanted = ref.strip().casefold()
    pool: list[Character | Animal] = [*store.list_for_guild(gid), *store.animals_for_guild(gid)]
    hits = [x for x in pool if x.name.casefold() == wanted] or [x for x in pool if wanted in x.name.casefold()]
    if not hits:
        raise UserError(f"There's no character or animal called **{ref}** in this server.")
    if len(hits) > 1:
        raise UserError(f"More than one character or animal matches **{ref}**: "
                        + ", ".join(holder_label(x) for x in hits[:10]) + ". Pick one from the list.")
    return hits[0]


def holder_label(x: Character | Animal) -> str:
    return f"🐴 {x.name} ({x.data['kind']})" if isinstance(x, Animal) else f"🧙 {x.name} ({embeds.level_label(x)})"


def load_line(x: Character | Animal) -> str:
    sp = x.speeds()
    limit = f" / {x.max_encumbrance()} st" if isinstance(x, Character) else \
        f" (normal {embeds.stone_number(x.data['normal_load'])} st)"
    return f"-# {x.name}: {rules.fmt_stone(x.encumbrance())}{limit} · {sp['band']} ({sp['exploration']}' / {sp['combat']}')"


async def recipient_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if interaction.guild_id is None:
        return []
    store = storage(interaction)
    cur = current.casefold()
    out = []
    for c in store.list_for_guild(interaction.guild_id):
        if cur in c.name.casefold():
            mine = "" if c.data["owner_id"] == interaction.user.id else " · other player"
            out.append(app_commands.Choice(name=f"{holder_label(c)}{mine}"[:100], value=f"c:{c.id}"))
    for a in store.animals_for_guild(interaction.guild_id):
        if cur in a.name.casefold() or cur in a.data["kind"].casefold():
            out.append(app_commands.Choice(name=holder_label(a)[:100], value=f"a:{a.id}"))
    return out[:25]


def give(interaction: discord.Interaction, giver: Character | Animal, it: dict, qty: int | None,
         target: Character | Animal) -> str:
    """Move an item between inventories, save both, and describe it (with both loads afterwards)."""
    try:
        moved, took, unequipped = giver.give_item(it["id"], qty, target)
    except ValueError as e:
        raise UserError(str(e)) from None
    save_holder(interaction, target)
    save_holder(interaction, giver)
    left = giver.item(it["id"])
    notes = []
    if unequipped:
        notes.append("taken off first" if isinstance(giver, Animal) else "unequipped first")
    if left:
        notes.append(f"{left['qty']} left")
    extra = f" ({', '.join(notes)})" if notes else ""
    hint = "\n-# Equip it with `/equip`." if isinstance(target, Character) and moved["kind"] in (
        "weapon", "armor", "shield") else ("\n-# Put it on with `/animal equip`." if isinstance(target, Animal)
                                            and moved["kind"] == "barding" else "")
    return (f"🎁 **{giver.name}** gives {took}× **{moved['name']}**{extra} to **{target.name}** "
            f"(#{moved['id']} in their gear).\n{load_line(giver)}\n{load_line(target)}{hint}")


UNIT_STONE = {"stone": Fraction(1), "items": Fraction(1, 6), "coins": Fraction(1, rules.COINS_PER_STONE)}


def add_supply(holder: Character | Animal, s: supplies.Supply, quantity: int, weight: float | None, unit: str,
               magic: int = 0, notes: str = "") -> str:
    """Add rations (as days), ammunition (one per shot) or feed (as stone). `weight`, if given, is for one of
    what was named (a week of rations, a quiver of arrows). Returns a description like '14 days of Iron rations'."""
    given = Fraction(str(weight)) * UNIT_STONE[unit] if weight is not None else None
    if s.kind == "feed":
        stone = quantity * (given if given is not None else rules.SIXTH)
        it = supplies.add_feed(holder, s.name, stone, notes)
        return f"**{it['name']}** (feed, #{it['id']}): {rules.fmt_stone(stone)}, now {rules.fmt_stone(supplies.feed_stone(holder))}"
    units = quantity * s.count
    each = given / s.count if given is not None else s.each
    it = holder.add_item(s.name, units, each, "stone", s.kind, s.base, magic, notes)
    what = f"{units} day{'s' if units != 1 else ''} of **{it['name']}**" if s.kind == "rations" \
        else f"{units}× **{it['name']}**"
    total = f"{it['qty']} days" if s.kind == "rations" else f"{it['qty']}"
    return f"{what} (#{it['id']}, {rules.fmt_stone(each * units)}; {total} in all)"


def save_holder(interaction: discord.Interaction, x: Character | Animal) -> None:
    if isinstance(x, Animal):
        try:
            storage(interaction).save_animal(x)
        except ValueError as e:
            raise UserError(str(e)) from None
    else:
        storage(interaction).save(x)


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
    employer = store.get(ch.employer_id) if store and ch.employer_id else None
    return embeds.sheet_embed(ch, owner.display_name if owner else None, employer.name if employer else None,
                              store.henchmen_of(ch) if store else None)


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
