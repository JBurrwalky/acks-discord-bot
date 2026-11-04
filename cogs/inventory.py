"""Inventory, coins and equipment: /item ..., /purse ..., /equip, /unequip."""
from __future__ import annotations

from fractions import Fraction
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds, rules
from acks.character import SLOT_LABELS, Character
from acks.dice import fmt_mod

from .common import (UserError, catalog_autocomplete, character_autocomplete, equippable_autocomplete,
                     find_item, inventory_autocomplete, resolve_character, save)

Coin = Literal["pp", "gp", "ep", "sp", "cp"]
SlotChoice = Literal["main hand", "off hand", "both hands", "missile", "armor", "shield"]
SLOT_MAP = {"main hand": "main", "off hand": "off", "both hands": "both", "missile": "missile",
            "armor": "armor", "shield": "shield"}


def _catalog_by_exact_name(name: str) -> str | None:
    n = name.strip().lower()
    for w in rules.WEAPONS.values():
        if n in (w.name.lower(), w.name.lower().replace(" (5)", ""), w.key.replace("_", " "), *w.aliases):
            return w.key
    for a in rules.ARMORS.values():
        if n in (a.name.lower(), a.key.replace("_", " "), *a.aliases):
            return a.key
    return None


WeaponSize = Literal["tiny", "small", "medium", "large", "missile"]
WeaponType = Literal["axes", "bludgeons", "bows", "swords", "spears", "other"]
ArmorType = Literal["very light", "light", "medium", "heavy", "shield"]

ITEM_OPTION_HELP = {
    "name": "Item name (anything: 'Rope, 50 ft', 'Flametongue', 'Dragon-bone axe')",
    "quantity": "How many",
    "weight": "Weight of ONE item in the chosen unit (default: 1 item, or the weapon/armor's usual weight)",
    "unit": "stone, items (6 items = 1 stone), or coins (1,000 coins = 1 stone)",
    "base": "Book weapon/armor it works like (e.g. Sword). Homebrew stats below override it",
    "magic": "Magic bonus, e.g. 1 for a +1 sword (adds to hit and damage, or to AC)",
    "notes": "Any note (charges, properties...)",
    "damage": "Homebrew weapon damage dice: 1d12, or 1d6/1d8 for one-handed/two-handed",
    "size": "Homebrew weapon size (decides hands and fighting styles); 'missile' = bows, slings",
    "weapon_type": "Homebrew weapon group, used for class proficiency and Weapon Focus",
    "range": "Missile ranges in feet, short/medium/long, e.g. 30/60/120",
    "thrown": "Melee weapon that can also be thrown",
    "armor_ac": "Homebrew armor/shield AC (body armor 1-6+, shields usually 1)",
    "armor_type": "Homebrew armor weight class, used for class armor proficiency",
}


def _custom_stats(damage, size, weapon_type, range_text, thrown, armor_ac, armor_type) -> dict:
    try:
        return rules.parse_custom_stats(damage, size, weapon_type, range_text, thrown, armor_ac, armor_type)
    except ValueError as e:
        raise UserError(str(e)) from e


def _resolve_base(base: str | None, name_for_exact_match: str | None):
    """Find the catalog weapon/armor named by `base` (or exactly matching the item name)."""
    key = base or (_catalog_by_exact_name(name_for_exact_match) if name_for_exact_match else None)
    if not key:
        return None, None
    w, a = rules.WEAPONS.get(key), rules.ARMORS.get(key)
    if not w and not a:   # typed free text into `base` instead of picking from the list
        w = rules.lookup_weapon(key)
        a = None if w else rules.lookup_armor(key)
    if base and not w and not a:
        raise UserError(f"I don't know a weapon or armor called **{base}**. Pick one from the list, or leave "
                        f"`base` empty and give homebrew stats instead.")
    return w, a


def _kind_for(w, a, custom: dict) -> str:
    weaponish, armorish = rules.is_weapon_custom(custom), rules.is_armor_custom(custom)
    if weaponish and armorish:
        raise UserError("An item can have weapon stats or armor stats, not both.")
    if (weaponish and a) or (armorish and w):
        raise UserError("Those stats don't match the `base` (weapon stats on armor, or armor stats on a weapon).")
    if weaponish or w:
        return "weapon"
    if armorish or a:
        cat = custom.get("armor_type") or (a.category if a else "light")
        return "shield" if cat == "shield" else "armor"
    return "gear"


def _default_weight(ch: Character, it: dict) -> tuple[Fraction, str]:
    """Usual weight for weapons/armor (armor: 1 stone per point of AC); 1 item for anything else."""
    w, a = ch.item_weapon(it), ch.item_armor(it)
    if w:
        return (Fraction(1) if w.size == "large" else w.enc), "stone"
    if a:
        return (Fraction(1) if a.category == "shield" else Fraction(max(a.ac, 1))), "stone"
    return Fraction(1), "items"


def _stats_text(ch: Character, it: dict) -> str:
    w, a = ch.item_weapon(it), ch.item_armor(it)
    if w:
        dmg = w.damage + (f"/{w.damage_2h}" if w.damage_2h else "")
        bits = [dmg, w.size or "missile", w.category]
        if w.ranges:
            bits.append("/".join(map(str, w.ranges)) + "'")
        if w.thrown and w.melee:
            bits.append("thrown")
        label = "homebrew weapon" if it.get("custom") else f"weapon ({w.name})"
        return f" · {label}: {', '.join(bits)}"
    if a:
        label = "homebrew " if it.get("custom") else ""
        return f" · {label}{a.category}{' armor' if a.category != 'shield' else ''} AC {a.ac}"
    return ""


def _status_line(ch: Character) -> str:
    sp = ch.speeds()
    return (f"-# Load {rules.fmt_stone(ch.encumbrance())} / {ch.max_encumbrance()} st · {sp['band']} "
            f"({sp['exploration']}' / {sp['combat']}') · AC {ch.ac()}")


def _equip_summary(ch: Character) -> str:
    eq = ch.data["equipped"]
    parts = []
    for slot in ("main", "off", "missile", "armor", "shield"):
        it = ch.item(eq.get(slot))
        if it:
            label = SLOT_LABELS[slot]
            if slot == "main" and eq.get("two_handed"):
                label = "Both hands"
            parts.append(f"{label}: **{it['name']}**")
    return " · ".join(parts) or "nothing equipped"


class Inventory(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    item = app_commands.Group(name="item", description="Add, remove, and list inventory items", guild_only=True)
    purse = app_commands.Group(name="purse", description="Track coins (1,000 coins = 1 stone)", guild_only=True)

    # -- items -------------------------------------------------------------
    @item.command(name="add", description="Add an item to inventory (any item; homebrew weapon/armor stats allowed)")
    @app_commands.describe(**ITEM_OPTION_HELP)
    @app_commands.autocomplete(base=catalog_autocomplete, character=character_autocomplete)
    async def item_add(self, interaction: discord.Interaction, name: str,
                       quantity: app_commands.Range[int, 1, 100000] = 1,
                       weight: app_commands.Range[float, 0, 10000] | None = None,
                       unit: Literal["stone", "items", "coins"] = "items",
                       base: str | None = None, magic: app_commands.Range[int, -5, 10] = 0,
                       notes: str | None = None,
                       damage: str | None = None, size: WeaponSize | None = None,
                       weapon_type: WeaponType | None = None, range: str | None = None,
                       thrown: bool | None = None, armor_ac: app_commands.Range[int, 0, 12] | None = None,
                       armor_type: ArmorType | None = None,
                       character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        custom = _custom_stats(damage, size, weapon_type, range, thrown, armor_ac, armor_type)
        w, a = _resolve_base(base, name if not custom else None)
        kind = _kind_for(w, a, custom)
        base_key = (w or a).key if (w or a) else None
        it = {"kind": kind, "base": base_key, "custom": custom, "name": name.strip()}
        if weight is None:
            weight_val, unit = _default_weight(ch, it)
        else:
            weight_val = Fraction(str(weight))
        it = ch.add_item(name.strip(), quantity, weight_val, unit, kind, base_key, magic, notes or "", custom or None)
        save(interaction, ch)
        each = ch.item_stone_each(it)
        desc = f"{quantity}× " if quantity != 1 else ""
        await interaction.response.send_message(
            f"➕ **{ch.name}** adds {desc}**{name}**{f' {fmt_mod(magic)}' if magic else ''}{_stats_text(ch, it)} "
            f"(#{it['id']}, {rules.fmt_stone(each * quantity)})\n{_status_line(ch)}"
            + ("\n-# Equip it with `/equip`." if kind != "gear" else ""))

    @item.command(name="remove", description="Remove (drop, use up, sell) an item")
    @app_commands.describe(item="Item to remove", quantity="How many (default: all of them)")
    @app_commands.autocomplete(item=inventory_autocomplete, character=character_autocomplete)
    async def item_remove(self, interaction: discord.Interaction, item: str,
                          quantity: app_commands.Range[int, 1, 100000] | None = None,
                          character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        it = find_item(ch, item)
        removed, n = ch.remove_item(it["id"], quantity)
        save(interaction, ch)
        left = f" ({removed['qty']} left)" if removed["qty"] > 0 else ""
        await interaction.response.send_message(
            f"➖ **{ch.name}** removes {n}× **{removed['name']}**{left}\n{_status_line(ch)}")

    @item.command(name="list", description="Show inventory and encumbrance")
    @app_commands.autocomplete(character=character_autocomplete)
    async def item_list(self, interaction: discord.Interaction, character: str | None = None,
                        private: bool = False) -> None:
        ch = resolve_character(interaction, character, write=False)
        await interaction.response.send_message(embed=embeds.inventory_embed(ch), ephemeral=private)

    @item.command(name="edit", description="Change an item's name, weight, magic, notes, or weapon/armor stats")
    @app_commands.describe(**ITEM_OPTION_HELP, clear_stats="Remove all homebrew stats from the item")
    @app_commands.autocomplete(item=inventory_autocomplete, base=catalog_autocomplete,
                               character=character_autocomplete)
    async def item_edit(self, interaction: discord.Interaction, item: str, name: str | None = None,
                        weight: app_commands.Range[float, 0, 10000] | None = None,
                        unit: Literal["stone", "items", "coins"] | None = None,
                        magic: app_commands.Range[int, -5, 10] | None = None, notes: str | None = None,
                        quantity: app_commands.Range[int, 1, 100000] | None = None,
                        base: str | None = None,
                        damage: str | None = None, size: WeaponSize | None = None,
                        weapon_type: WeaponType | None = None, range: str | None = None,
                        thrown: bool | None = None, armor_ac: app_commands.Range[int, 0, 12] | None = None,
                        armor_type: ArmorType | None = None, clear_stats: bool = False,
                        character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        it = find_item(ch, item)
        new_custom = _custom_stats(damage, size, weapon_type, range, thrown, armor_ac, armor_type)
        was_equipped: list[str] = []
        reequipped: list[str] = []
        if base or new_custom or clear_stats:
            custom = {} if clear_stats else dict(it.get("custom") or {})
            custom.update(new_custom)
            if base:
                w, a = _resolve_base(base, None)
            else:
                w, a = rules.WEAPONS.get(it.get("base") or ""), rules.ARMORS.get(it.get("base") or "")
            kind = _kind_for(w, a, custom)
            was_equipped = [s for s in ("main", "off", "missile", "armor", "shield")
                            if ch.data["equipped"].get(s) == it["id"]]
            it["kind"], it["base"] = kind, ((w or a).key if (w or a) else None)
            if custom:
                it["custom"] = custom
            else:
                it.pop("custom", None)
            two_handed = ch.data["equipped"].get("two_handed")
            for slot in was_equipped:
                ch.data["equipped"][slot] = None
            for slot in was_equipped:   # put it back where it was, unless the new stats no longer fit there
                try:
                    ch.equip(it["id"], "both" if slot == "main" and two_handed else slot)
                    reequipped.append(slot)
                except ValueError:
                    pass
        if name:
            it["name"] = name.strip()
        if weight is not None:
            it["weight"] = str(Fraction(str(weight)).limit_denominator(10000))
        if unit:
            it["unit"] = unit
        if magic is not None:
            it["magic"] = magic
        if notes is not None:
            it["notes"] = notes
        if quantity is not None:
            it["qty"] = quantity
        save(interaction, ch)
        note = ""
        if len(reequipped) < len(was_equipped):
            note = "\n-# With its new stats it no longer fits the slot it was in, so it was unequipped."
        await interaction.response.send_message(
            f"📝 Updated **{it['name']}** (#{it['id']}){_stats_text(ch, it)}.\n{_status_line(ch)}{note}")

    # -- coins -------------------------------------------------------------
    @purse.command(name="add", description="Add coins")
    @app_commands.autocomplete(character=character_autocomplete)
    async def purse_add(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 10_000_000],
                        coin: Coin = "gp", character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        ch.data["purse"][coin] = int(ch.data["purse"].get(coin, 0)) + amount
        save(interaction, ch)
        await interaction.response.send_message(f"💰 **{ch.name}** gains {amount:,} {coin}.\n{_status_line(ch)}")

    @purse.command(name="spend", description="Spend or lose coins (makes change from other coins if needed)")
    @app_commands.describe(make_change="If short of this coin, break larger coins or pay in smaller ones (default: on)")
    @app_commands.autocomplete(character=character_autocomplete)
    async def purse_spend(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 10_000_000],
                          coin: Coin = "gp", make_change: bool = True, character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        try:
            broken, paid = ch.spend_coins(amount, coin, make_change)
        except ValueError as e:
            raise UserError(str(e)) from None
        save(interaction, ch)
        parts = []
        if broken:
            into = sum((n * rules.COIN_VALUES_GP[c] for c, n in broken.items()), Fraction(0)) / rules.COIN_VALUES_GP[coin]
            parts.append("broke " + ", ".join(f"{n:,} {c}" for c, n in broken.items()) + f" into {int(into):,} {coin}")
        if paid:
            parts.append("paid " + ", ".join(f"{n:,} {c}" for c, n in paid.items()))
        if broken or paid:
            parts.append(f"{ch.data['purse'][coin]:,} {coin} left")
        note = f" ({'; '.join(parts)})" if parts else ""
        await interaction.response.send_message(f"💸 **{ch.name}** spends {amount:,} {coin}{note}.\n{_status_line(ch)}")

    @purse.command(name="set", description="Set coin counts directly")
    @app_commands.autocomplete(character=character_autocomplete)
    async def purse_set(self, interaction: discord.Interaction, pp: int | None = None, gp: int | None = None,
                        ep: int | None = None, sp: int | None = None, cp: int | None = None,
                        character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        for coin, val in (("pp", pp), ("gp", gp), ("ep", ep), ("sp", sp), ("cp", cp)):
            if val is not None:
                ch.data["purse"][coin] = max(0, val)
        save(interaction, ch)
        p = ch.data["purse"]
        await interaction.response.send_message(
            f"💰 **{ch.name}**: " + ", ".join(f"{p[c]:,} {c}" for c in rules.COIN_TYPES) + f"\n{_status_line(ch)}")

    # -- equipment ---------------------------------------------------------
    @app_commands.command(name="equip", description="Equip a weapon, armor, or shield (updates AC and attacks)")
    @app_commands.guild_only()
    @app_commands.describe(item="Weapon, armor, or shield from your inventory",
                           slot="Where to equip it (guessed if left out)")
    @app_commands.autocomplete(item=equippable_autocomplete, character=character_autocomplete)
    async def equip(self, interaction: discord.Interaction, item: str, slot: SlotChoice | None = None,
                    character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        it = find_item(ch, item)
        if slot:
            target = SLOT_MAP[slot]
        elif it["kind"] == "armor":
            target = "armor"
        elif it["kind"] == "shield":
            target = "shield"
        elif it["kind"] == "weapon":
            w = ch.item_weapon(it)
            target = "main" if w and w.melee else "missile"
            if w and w.size == "large":
                target = "both"
        else:
            raise UserError(f"**{it['name']}** isn't a weapon, armor, or shield. Give it a `base` with "
                            f"`/item add` to make it equippable.")
        old_ac = ch.ac()
        try:
            notes = ch.equip(it["id"], target)
        except ValueError as e:
            raise UserError(str(e)) from e
        save(interaction, ch)
        new_ac = ch.ac()
        msg = f"🛡️ **{ch.name}** equips **{it['name']}**"
        msg += {"main": " in the main hand", "off": " in the off hand", "both": " in both hands",
                "missile": " as a missile weapon", "armor": "", "shield": ""}[target]
        if notes:
            msg += f" ({'; '.join(notes)})"
        if new_ac != old_ac:
            msg += f"\nAC {old_ac} → **{new_ac}**"
        warn = ch.melee_nonproficiency() if target != "missile" else ch.missile_nonproficiency()
        if warn:
            msg += f"\n⚠️ Non-proficient: {'; '.join(warn)} — attacks as a 0th-level fighter."
        if it["kind"] == "shield" and "weapon_and_shield" not in ch.styles():
            msg += "\n⚠️ This class lacks the weapon & shield fighting style, so the shield gives no AC bonus."
        msg += f"\n-# {_equip_summary(ch)}"
        await interaction.response.send_message(msg)

    @app_commands.command(name="unequip", description="Unequip a slot")
    @app_commands.guild_only()
    @app_commands.autocomplete(character=character_autocomplete)
    async def unequip(self, interaction: discord.Interaction,
                      slot: Literal["main hand", "off hand", "missile", "armor", "shield", "all"],
                      character: str | None = None) -> None:
        ch = resolve_character(interaction, character)
        old_ac = ch.ac()
        key = {"main hand": "main", "off hand": "off"}.get(slot, slot)
        ch.unequip(key)
        save(interaction, ch)
        msg = f"🧺 **{ch.name}** unequips {slot}."
        if ch.ac() != old_ac:
            msg += f"\nAC {old_ac} → **{ch.ac()}**"
        msg += f"\n-# {_equip_summary(ch)}"
        await interaction.response.send_message(msg)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Inventory(bot))
