"""Animal sheets: /animal create, sheet, list, edit, attack, barding, item ..., ability ..., routine ..."""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds, rules, templates
from acks.animal import (Animal, attack_label, make_attack, new_animal_data, parse_attacks, roll_hd, routine_text,
                         store_stone)
from acks.storage import Storage

from .common import (UserError, any_character_autocomplete, character_autocomplete, guild_id, is_judge,
                     give, recipient_autocomplete, resolve_character, resolve_recipient, storage)

Size = Literal["man-sized", "large", "huge", "gigantic", "colossal"]
Material = Literal["leather", "scale", "chain", "lamellar", "plate"]
PRESET_CHOICES = [app_commands.Choice(name=p.name, value=p.key) for p in rules.ANIMAL_PRESETS.values()]

STAT_HELP = {
    "kind": "e.g. Medium warhorse, War dog",
    "owner": "Owning character (listed on their Inventory page)",
    "hd": "Hit Dice: 2, 1/2, 3+1...",
    "ac": "Natural AC, before barding",
    "attacks": "e.g. 2 hoof 1d6, bite 1d4",
    "attack_throw": "Default: from Hit Dice",
    "save_as": "e.g. F1",
    "speed": "Exploration speed (feet/turn), e.g. 180",
    "normal_load": "Stone carried at full speed",
    "max_load": "Stone carried at half speed (default 2× normal)",
    "size": "For barding weight",
    "food": "Stone/day (default normal load / 10)",
    "water": "Stone/day (default normal load / 5)",
}


def train_for_war(a: Animal, p: rules.AnimalPreset | None) -> None:
    """War training (RR p. 147, MM): +2 morale; horses also gain a hoof attack; camels still don't attack on a
    charge; war dogs already are trained; donkeys (and oxen) can't be."""
    war = p.war if p else "morale"
    if war is None:
        raise UserError(f"The books don't train {p.name.lower()}s for war. If your Judge allows it, set "
                        f"`morale` yourself and add the training with `/animal ability add`.")
    if war == "trained":
        return
    a.data["morale"] = int(a.data["morale"]) + 2
    if war == "hoof":
        hoof = next((at for at in a.attacks() if at["name"] == "hoof" and not at.get("alt")), None)
        if hoof:
            hoof["count"] += 1
    a.data["kind"] = f"{a.data['kind']} (war-trained)"
    a.data["abilities"].append("Trained for war (+2 morale). War camels don't attack when their rider charges."
                               if war == "no_charge" else rules.WAR_TRAINED_NOTE)


def _stone(x: float | None) -> Fraction | None:
    return None if x is None else Fraction(str(x)).limit_denominator(60)


# ---------------------------------------------------------------------------
# Finding animals and checking who may change them
# ---------------------------------------------------------------------------

def controller_id(store: Storage, a: Animal) -> int:
    """The player who controls an animal: its owner character's player, or whoever created it."""
    if a.owner_char is not None:
        ch = store.get(a.owner_char)
        if ch:
            return ch.data["owner_id"]
    return a.data["user_id"]


def resolve_animal(interaction: discord.Interaction, ref: str, *, write: bool = True) -> Animal:
    store = storage(interaction)
    gid = guild_id(interaction)
    a = None
    m = re.fullmatch(r"#?(\d+)", ref.strip())
    if m:
        a = store.get_animal(int(m.group(1)))
        if a and a.data["guild_id"] != gid:
            a = None
    if a is None:
        wanted = ref.strip().casefold()
        pool = store.animals_for_guild(gid)
        hits = [x for x in pool if x.name.casefold() == wanted] or [x for x in pool if wanted in x.name.casefold()]
        if len(hits) > 1:
            raise UserError(f"More than one animal matches **{ref}**: " + ", ".join(x.name for x in hits[:10]))
        a = hits[0] if hits else None
    if a is None:
        raise UserError(f"I couldn't find an animal called **{ref}**. See `/animal list`.")
    if write and controller_id(store, a) != interaction.user.id and not is_judge(interaction):
        raise UserError(f"**{a.name}** belongs to another player. Only they or a Judge can change it.")
    return a


def save_animal(interaction: discord.Interaction, a: Animal) -> None:
    try:
        storage(interaction).save_animal(a)
    except ValueError as e:
        raise UserError(str(e)) from None


def check_name(store: Storage, gid: int, name: str, except_id: int | None = None) -> str:
    name = " ".join(name.split())
    if not name or len(name) > 60:
        raise UserError("An animal's name must be 1 to 60 characters.")
    if re.fullmatch(r"#?\d+", name):
        raise UserError("An animal's name can't be just a number.")
    if store.animal_name_taken(gid, name, except_id):
        raise UserError(f"There's already an animal called **{name}** in this server. Animal names must be unique.")
    return name


def owner_name(store: Storage, a: Animal) -> str | None:
    ch = store.get(a.owner_char) if a.owner_char is not None else None
    return ch.name if ch else None


async def _animal_choices(interaction: discord.Interaction, current: str, write: bool) -> list[app_commands.Choice[str]]:
    if interaction.guild_id is None:
        return []
    store = storage(interaction)
    char_players = {c.id: c.data["owner_id"] for c in store.list_for_guild(interaction.guild_id)}
    judge = is_judge(interaction)
    cur = current.casefold()
    out = []
    for a in store.animals_for_guild(interaction.guild_id):
        player = char_players.get(a.owner_char, a.data["user_id"]) if a.owner_char is not None else a.data["user_id"]
        mine = player == interaction.user.id
        if write and not (mine or judge):
            continue
        if cur in a.name.casefold() or cur in a.data["kind"].casefold():
            label = f"{a.name} — {a.data['kind']}" + ("" if mine else " (other player)")
            out.append(app_commands.Choice(name=label[:100], value=str(a.id)))
    return out[:25]


async def animal_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return await _animal_choices(interaction, current, write=True)


async def any_animal_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return await _animal_choices(interaction, current, write=False)


def _animal_from_namespace(interaction: discord.Interaction) -> Animal | None:
    ref = getattr(interaction.namespace, "animal", None)
    if not ref:
        return None
    try:
        return resolve_animal(interaction, ref, write=False)
    except UserError:
        return None


async def animal_item_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    a = _animal_from_namespace(interaction)
    if not a:
        return []
    only_barding = interaction.command is not None and interaction.command.name == "equip"
    out = []
    for it in a.items():
        if only_barding and it.get("kind") != "barding":
            continue
        label = f"#{it['id']} {it['name']}" + (f" ×{it['qty']}" if it["qty"] != 1 else "")
        if current.casefold().lstrip("#") in label.casefold():
            out.append(app_commands.Choice(name=label[:100], value=str(it["id"])))
    return out[:25]


async def attack_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    a = _animal_from_namespace(interaction)
    if not a:
        return []
    return [app_commands.Choice(name=f"{'or ' if at.get('alt') else ''}{attack_label(at)} {at['damage']}"[:100],
                                value=str(i))
            for i, at in enumerate(a.attacks(), 1) if current.casefold() in at["name"].casefold()][:25]


async def ability_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    a = _animal_from_namespace(interaction)
    if not a:
        return []
    return [app_commands.Choice(name=f"{i}. {t}"[:100], value=str(i))
            for i, t in enumerate(a.data["abilities"], 1) if current.casefold() in t.casefold()][:25]


def _pick(seq: list, ref: str, what: str, a: Animal):
    """Find an attack or ability by its number (from autocomplete) or by text."""
    ref = ref.strip()
    if ref.isdigit() and 1 <= int(ref) <= len(seq):
        return int(ref) - 1
    text = (lambda x: x["name"]) if what == "attack" else (lambda x: x)
    hits = [i for i, x in enumerate(seq) if ref.casefold() in text(x).casefold()]
    if len(hits) != 1:
        raise UserError(f"**{a.name}** has {'no' if not hits else 'more than one'} {what} matching **{ref}**.")
    return hits[0]


def _find_item(a: Animal, ref: str) -> dict:
    m = re.fullmatch(r"#?(\d+)", ref.strip())
    if m and a.item(int(m.group(1))):
        return a.item(int(m.group(1)))
    hits = [i for i in a.items() if i["name"].casefold() == ref.strip().casefold()] or \
           [i for i in a.items() if ref.strip().casefold() in i["name"].casefold()]
    if len(hits) != 1:
        raise UserError(f"**{a.name}** isn't carrying {'anything called' if not hits else 'just one'} **{ref}**.")
    return hits[0]


def _status(a: Animal) -> str:
    sp = a.speeds()
    return (f"-# {a.name}: AC {a.ac()} · {rules.fmt_stone(a.encumbrance())} carried "
            f"(normal {embeds.stone_number(a.data['normal_load'])} st) · {sp['exploration']}' / {sp['combat']}' "
            f"· {sp['band']}")


# ---------------------------------------------------------------------------
# The cog
# ---------------------------------------------------------------------------

class Animals(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    animal = app_commands.Group(name="animal", description="Animal sheets: mounts, pack animals, war dogs...",
                                guild_only=True)
    item = app_commands.Group(name="item", description="An animal's packs and gear", parent=animal)
    ability = app_commands.Group(name="ability", description="An animal's special powers and abilities",
                                 parent=animal)
    routine = app_commands.Group(name="routine", description="An animal's attack routine", parent=animal)

    def _apply_stats(self, interaction: discord.Interaction, a: Animal, *, kind=None, owner=None, hd=None, ac=None,
                     attacks=None, attack_throw=None, save_as=None, morale=None, speed=None, normal_load=None,
                     max_load=None, size=None, food=None, water=None) -> None:
        d = a.data
        try:
            if hd is not None:
                rules.parse_hd(hd)
                d["hd"] = hd.strip()
            if attacks is not None:
                d["attacks"] = parse_attacks(attacks)
        except ValueError as e:
            raise UserError(str(e)) from None
        if owner is not None:
            d["owner_char"] = resolve_character(interaction, owner, write=True).id
        for key, val in (("kind", kind), ("ac", ac), ("attack_throw", attack_throw), ("morale", morale),
                         ("speed", speed), ("size", size)):
            if val is not None:
                d[key] = " ".join(val.split())[:60] if isinstance(val, str) else val
        if save_as is not None:
            d["save"] = save_as.strip()[:20]
        for key, val in (("normal_load", normal_load), ("max_load", max_load), ("food", food), ("water", water)):
            if val is not None:
                d[key] = store_stone(_stone(val))
        if Fraction(str(d["max_load"])) < Fraction(str(d["normal_load"])):
            raise UserError("The maximum load can't be less than the normal load.")

    # -- create, show, list ---------------------------------------------------
    @animal.command(name="create", description="Create an animal sheet (mount, pack animal, war dog...)")
    @app_commands.describe(name="Unique name", preset="Fill in the book's stats", hp="Default: rolled",
                           war_trained="+2 morale (and an extra hoof for horses)", **STAT_HELP)
    @app_commands.rename(save_as="save")
    @app_commands.choices(preset=PRESET_CHOICES)
    @app_commands.autocomplete(owner=character_autocomplete)
    async def create(self, interaction: discord.Interaction, name: str, preset: str | None = None,
                     war_trained: bool = False, kind: str | None = None, owner: str | None = None,
                     hd: str | None = None, hp: app_commands.Range[int, 1, 2000] | None = None,
                     ac: app_commands.Range[int, -5, 30] | None = None, attacks: str | None = None,
                     attack_throw: app_commands.Range[int, -10, 20] | None = None,
                     save_as: str | None = None, morale: app_commands.Range[int, -6, 6] | None = None,
                     speed: app_commands.Range[int, 0, 2000] | None = None,
                     normal_load: app_commands.Range[float, 0, 100000] | None = None,
                     max_load: app_commands.Range[float, 0, 100000] | None = None, size: Size | None = None,
                     food: app_commands.Range[float, 0, 1000] | None = None,
                     water: app_commands.Range[float, 0, 1000] | None = None) -> None:
        store = storage(interaction)
        gid = guild_id(interaction)
        a = Animal(new_animal_data(gid, interaction.user.id, check_name(store, gid, name)))
        d = a.data
        p = rules.ANIMAL_PRESETS.get(preset or "")
        if p:
            d.update(kind=p.name, speed=p.speed, normal_load=p.normal_load, max_load=p.max_load,
                     food=store_stone(p.food), water=store_stone(p.water), size=p.size, ac=p.ac, hd=p.hd,
                     attacks=parse_attacks(p.attacks), save=p.save, morale=p.morale, abilities=list(p.abilities))
        elif speed is None or normal_load is None:
            raise UserError("Pick a `preset`, or give at least `speed` and `normal_load` (the rest have defaults).")
        else:
            nl = _stone(normal_load)
            d.update(normal_load=store_stone(nl), max_load=store_stone(nl * 2), food=store_stone(nl / 10),
                     water=store_stone(nl / 5))
        if war_trained:
            train_for_war(a, p)
        self._apply_stats(interaction, a, kind=kind, owner=owner, hd=hd, ac=ac, attacks=attacks,
                          attack_throw=attack_throw, save_as=save_as, morale=morale, speed=speed,
                          normal_load=normal_load, max_load=max_load, size=size, food=food, water=water)
        note = ""
        if hp is None:
            hp, detail = roll_hd(d["hd"])
            note = f" HP rolled from {d['hd']} HD: {detail} = **{hp}**."
        d["hp"] = {"current": hp, "max": hp}
        save_animal(interaction, a)
        todo = "attacks with `/animal routine add`, " if not a.attacks() else ""
        await interaction.response.send_message(
            f"🐴 Created **{a.name}**.{note} Add {todo}gear with `/animal item add` and barding with `/animal barding`.",
            embed=embeds.animal_embed(a, owner_name(store, a)))

    @animal.command(name="sheet", description="Show an animal's sheet")
    @app_commands.describe(private="Only show it to you")
    @app_commands.autocomplete(animal=any_animal_autocomplete)
    async def sheet(self, interaction: discord.Interaction, animal: str, private: bool = False) -> None:
        a = resolve_animal(interaction, animal, write=False)
        await interaction.response.send_message(embed=embeds.animal_embed(a, owner_name(storage(interaction), a)),
                                                ephemeral=private)

    @animal.command(name="list", description="List the server's animals, or one character's")
    @app_commands.describe(character="Only this character's animals")
    @app_commands.autocomplete(character=any_character_autocomplete)
    async def list_(self, interaction: discord.Interaction, character: str | None = None) -> None:
        store = storage(interaction)
        if character:
            ch = resolve_character(interaction, character, write=False)
            animals, title = store.animals_owned_by(ch.id), f"🐴 {ch.name}'s animals"
        else:
            animals, title = store.animals_for_guild(guild_id(interaction)), "🐴 Animals"
        if not animals:
            raise UserError("No animals yet. Make one with `/animal create`.")
        names = {c.id: c.name for c in store.list_for_guild(guild_id(interaction))}
        lines = [embeds.animal_line(a) + (f" · {names[a.owner_char]}" if not character and a.owner_char in names
                                          else "") for a in animals]
        e = discord.Embed(title=title, description="\n".join(lines)[:4000], color=embeds.SHEET_COLOR)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @animal.command(name="edit", description="Change an animal's name, owner, stats, or notes")
    @app_commands.describe(clear_owner="Remove its owner", notes="Replaces the old notes",
                           **(STAT_HELP | {"attacks": "Replaces the whole routine, e.g. 2 hoof 1d6"}))
    @app_commands.rename(save_as="save")
    @app_commands.autocomplete(animal=animal_autocomplete, owner=character_autocomplete)
    async def edit(self, interaction: discord.Interaction, animal: str, name: str | None = None,
                   kind: str | None = None, owner: str | None = None, clear_owner: bool = False,
                   hd: str | None = None, hp_max: app_commands.Range[int, 1, 2000] | None = None,
                   ac: app_commands.Range[int, -5, 30] | None = None, attacks: str | None = None,
                   attack_throw: app_commands.Range[int, -10, 20] | None = None, save_as: str | None = None,
                   morale: app_commands.Range[int, -6, 6] | None = None,
                   speed: app_commands.Range[int, 0, 2000] | None = None,
                   normal_load: app_commands.Range[float, 0, 100000] | None = None,
                   max_load: app_commands.Range[float, 0, 100000] | None = None, size: Size | None = None,
                   food: app_commands.Range[float, 0, 1000] | None = None,
                   water: app_commands.Range[float, 0, 1000] | None = None,
                   notes: app_commands.Range[str, 0, 1000] | None = None) -> None:
        store = storage(interaction)
        a = resolve_animal(interaction, animal)
        if name is not None:
            a.data["name"] = check_name(store, a.data["guild_id"], name, except_id=a.id)
        if clear_owner:
            a.data["owner_char"] = None
        self._apply_stats(interaction, a, kind=kind, owner=owner, hd=hd, ac=ac, attacks=attacks,
                          attack_throw=attack_throw, save_as=save_as, morale=morale, speed=speed,
                          normal_load=normal_load, max_load=max_load, size=size, food=food, water=water)
        if hp_max is not None:
            a.set_max_hp(hp_max)
        if notes is not None:
            a.data["notes"] = notes.strip()
        save_animal(interaction, a)
        await interaction.response.send_message(f"📝 Updated **{a.name}**.",
                                                embed=embeds.animal_embed(a, owner_name(store, a)))

    @animal.command(name="delete", description="Permanently delete an animal")
    @app_commands.autocomplete(animal=animal_autocomplete)
    async def delete(self, interaction: discord.Interaction, animal: str) -> None:
        a = resolve_animal(interaction, animal)
        await interaction.response.send_message(
            f"Really delete **{a.name}** ({a.data['kind']}) and everything it carries? This can't be undone.",
            view=ConfirmDeleteAnimal(interaction.user.id, a.id, a.name), ephemeral=True)

    # -- hit points and attacks ---------------------------------------------
    @animal.command(name="hp", description="Damage, heal, or set an animal's hit points")
    @app_commands.describe(set="Set current HP")
    @app_commands.autocomplete(animal=animal_autocomplete)
    async def hp(self, interaction: discord.Interaction, animal: str,
                 damage: app_commands.Range[int, 1, 2000] | None = None,
                 heal: app_commands.Range[int, 1, 2000] | None = None,
                 set: app_commands.Range[int, 0, 2000] | None = None) -> None:
        a = resolve_animal(interaction, animal)
        hp = a.data["hp"]
        if set is not None:
            hp["current"] = min(set, hp["max"])
        hp["current"] = max(0, min(hp["max"], hp["current"] - (damage or 0) + (heal or 0)))   # 0 hp = down
        save_animal(interaction, a)
        down = " 💀 It's down: unconscious and possibly slain." if hp["current"] <= 0 else ""
        await interaction.response.send_message(
            f"❤️ **{a.name}**: {hp['current']}/{hp['max']} HP {embeds.hp_bar(hp['current'], hp['max'])}{down}")

    @animal.command(name="attack", description="Roll an animal's attack routine (or one attack) against an AC")
    @app_commands.describe(attack="Just this attack (default: all)", situational="Modifier to every attack")
    @app_commands.autocomplete(animal=animal_autocomplete, attack=attack_autocomplete)
    async def attack(self, interaction: discord.Interaction, animal: str, target_ac: app_commands.Range[int, -10, 30],
                     attack: str | None = None, situational: int = 0) -> None:
        a = resolve_animal(interaction, animal)
        if not a.attacks():
            raise UserError(f"**{a.name}** has no attacks yet. Add them with `/animal routine add`.")
        if attack:
            chosen = [a.attacks()[_pick(a.attacks(), attack, "attack", a)]]
        else:   # the routine; alternatives ("or trample") are rolled by picking them
            chosen = [at for at in a.attacks() if not at.get("alt")] or a.attacks()[:1]
        results = [a.roll_attack(at, target_ac, situational) for at in chosen for _ in range(at["count"])]
        await interaction.response.send_message(embed=embeds.animal_attack_embed(a, target_ac, results, situational))

    # -- barding --------------------------------------------------------------
    @animal.command(name="barding", description="Add book barding (weighed for the animal's size) and put it on")
    @app_commands.describe(material="Leather +1, scale +2, chain +3, lamellar +4, plate +5 AC",
                           half="Half weight; no AC when flanked", spiked="+1 damage per die",
                           equip="Put it on now", size="Default: the animal's size")
    @app_commands.autocomplete(animal=animal_autocomplete)
    async def barding(self, interaction: discord.Interaction, animal: str, material: Material, half: bool = False,
                      spiked: bool = False, magic: app_commands.Range[int, 0, 5] = 0, equip: bool = True,
                      size: Size | None = None) -> None:
        a = resolve_animal(interaction, animal)
        size = size or a.data.get("size", "large")
        weight = rules.barding_weight(material, size, half)
        name = f"{'Half-' if half else ''}{material.title()} barding" + (" (spiked)" if spiked else "")
        if size != "large":
            name += f", {size}"
        it = a.add_item(name, 1, weight, "stone", kind="barding", magic=magic,
                        custom={"ac": rules.BARDING[material][0], "spiked": spiked})
        if equip:
            a.equip_barding(it["id"])
        save_animal(interaction, a)
        await interaction.response.send_message(
            f"🛡️ **{a.name}** {'now wears' if equip else 'carries'} **{name}** ({rules.fmt_stone(weight)}).\n{_status(a)}")

    @animal.command(name="equip", description="Put barding from the animal's gear on it")
    @app_commands.autocomplete(animal=animal_autocomplete, item=animal_item_autocomplete)
    async def equip(self, interaction: discord.Interaction, animal: str, item: str) -> None:
        a = resolve_animal(interaction, animal)
        try:
            it = a.equip_barding(_find_item(a, item)["id"])
        except ValueError as e:
            raise UserError(str(e)) from None
        save_animal(interaction, a)
        await interaction.response.send_message(f"🛡️ **{a.name}** now wears **{it['name']}**.\n{_status(a)}")

    @animal.command(name="unequip", description="Take an animal's barding off (it stays in its gear)")
    @app_commands.autocomplete(animal=animal_autocomplete)
    async def unequip(self, interaction: discord.Interaction, animal: str) -> None:
        a = resolve_animal(interaction, animal)
        it = a.unequip_barding()
        if it is None:
            raise UserError(f"**{a.name}** isn't wearing barding.")
        save_animal(interaction, a)
        await interaction.response.send_message(f"**{a.name}** takes off **{it['name']}**.\n{_status(a)}")

    # -- /animal item ---------------------------------------------------------
    @item.command(name="add", description="Load gear onto an animal (counts against its load)")
    @app_commands.describe(weight="Weight of each (default: its usual weight)", unit="6 items or 1,000 coins = 1 stone",
                           barding_ac="Makes it barding with this AC bonus", spiked="Barding: +1 damage per die")
    @app_commands.autocomplete(animal=animal_autocomplete)
    async def item_add(self, interaction: discord.Interaction, animal: str, name: app_commands.Range[str, 1, 80],
                       quantity: app_commands.Range[int, 1, 100000] = 1,
                       weight: app_commands.Range[float, 0, 100000] | None = None,
                       unit: Literal["stone", "items", "coins"] = "stone", notes: str = "",
                       barding_ac: app_commands.Range[int, 0, 10] | None = None, spiked: bool = False) -> None:
        a = resolve_animal(interaction, animal)
        custom = {"ac": barding_ac, "spiked": spiked} if barding_ac is not None else None
        guessed = ""
        if weight is not None:
            each = _stone(weight)
        elif custom:   # homebrew barding weighs like book barding of the same AC, for this animal's size
            material = list(rules.BARDING)[min(max(barding_ac, 1), 5) - 1]
            each, unit = rules.barding_weight(material, a.data.get("size", "large")), "stone"
            guessed = f" (weighed like {material} barding; set `weight` to change)"
        else:
            each, known = templates.item_weight(name)
            unit = "stone"
            guessed = "" if known else " (not a recognised item, so counted as 1 item; set `weight` to change)"
        it = a.add_item(name.strip(), quantity, each, unit, kind="barding" if custom else "gear",
                        notes=notes.strip()[:200], custom=custom)
        save_animal(interaction, a)
        hint = " Put it on with `/animal equip`." if custom else ""
        total = rules.fmt_stone(a.item_stone_each(it) * quantity)
        await interaction.response.send_message(
            f"🎒 **{a.name}** carries {quantity}× **{it['name']}** (#{it['id']}, {total}){guessed}.{hint}\n{_status(a)}")

    @item.command(name="remove", description="Unload gear from an animal")
    @app_commands.describe(quantity="How many (default: all of them)")
    @app_commands.autocomplete(animal=animal_autocomplete, item=animal_item_autocomplete)
    async def item_remove(self, interaction: discord.Interaction, animal: str, item: str,
                          quantity: app_commands.Range[int, 1, 100000] | None = None) -> None:
        a = resolve_animal(interaction, animal)
        it, took = a.remove_item(_find_item(a, item)["id"], quantity)
        save_animal(interaction, a)
        await interaction.response.send_message(f"🎒 Removed {took}× **{it['name']}** from **{a.name}**.\n{_status(a)}")

    @item.command(name="give", description="Move gear from an animal to a character or another animal (anyone's)")
    @app_commands.describe(to="Who receives it", quantity="How many (default: all of them)")
    @app_commands.autocomplete(animal=animal_autocomplete, item=animal_item_autocomplete, to=recipient_autocomplete)
    async def item_give(self, interaction: discord.Interaction, animal: str, item: str, to: str,
                        quantity: app_commands.Range[int, 1, 100000] | None = None) -> None:
        a = resolve_animal(interaction, animal)
        it = _find_item(a, item)
        target = resolve_recipient(interaction, to)
        await interaction.response.send_message(give(interaction, a, it, quantity, target))

    # -- /animal ability ------------------------------------------------------
    @ability.command(name="add", description="Add a special power or ability")
    @app_commands.describe(text="e.g. Night vision; Trained for war")
    @app_commands.autocomplete(animal=animal_autocomplete)
    async def ability_add(self, interaction: discord.Interaction, animal: str,
                          text: app_commands.Range[str, 1, 300]) -> None:
        a = resolve_animal(interaction, animal)
        a.data["abilities"].append(text.strip())
        save_animal(interaction, a)
        await interaction.response.send_message(f"✨ **{a.name}** gains: {text.strip()}")

    @ability.command(name="remove", description="Remove a special power or ability")
    @app_commands.autocomplete(animal=animal_autocomplete, ability=ability_autocomplete)
    async def ability_remove(self, interaction: discord.Interaction, animal: str, ability: str) -> None:
        a = resolve_animal(interaction, animal)
        gone = a.data["abilities"].pop(_pick(a.data["abilities"], ability, "ability", a))
        save_animal(interaction, a)
        await interaction.response.send_message(f"✨ Removed from **{a.name}**: {gone}")

    # -- /animal routine ------------------------------------------------------
    @routine.command(name="add", description="Add an attack to the animal's routine")
    @app_commands.describe(name="e.g. hoof, bite", damage="e.g. 1d6 or 1d4+1", count="Times per round",
                           alternative="Made instead of the routine (e.g. trample)")
    @app_commands.autocomplete(animal=animal_autocomplete)
    async def routine_add(self, interaction: discord.Interaction, animal: str, name: app_commands.Range[str, 1, 40],
                          damage: str, count: app_commands.Range[int, 1, 10] = 1, alternative: bool = False) -> None:
        a = resolve_animal(interaction, animal)
        try:
            at = make_attack(name, damage, count, alternative)
        except ValueError as e:
            raise UserError(str(e)) from None
        a.attacks().append(at)
        save_animal(interaction, a)
        await interaction.response.send_message(f"⚔️ **{a.name}** attacks: {routine_text(a.attacks())}")

    @routine.command(name="remove", description="Remove an attack from the animal's routine")
    @app_commands.autocomplete(animal=animal_autocomplete, attack=attack_autocomplete)
    async def routine_remove(self, interaction: discord.Interaction, animal: str, attack: str) -> None:
        a = resolve_animal(interaction, animal)
        gone = a.attacks().pop(_pick(a.attacks(), attack, "attack", a))
        save_animal(interaction, a)
        await interaction.response.send_message(f"⚔️ Removed **{attack_label(gone)}** from **{a.name}**'s attacks.")


class ConfirmDeleteAnimal(discord.ui.View):
    def __init__(self, user_id: int, animal_id: int, name: str):
        super().__init__(timeout=60)
        self.user_id, self.animal_id, self.name = user_id, animal_id, name

    @discord.ui.button(label="Delete forever", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        storage(interaction).delete_animal(self.animal_id)
        self.stop()
        await interaction.response.edit_message(content=f"🗑️ **{self.name}** has been deleted.", view=None)

    @discord.ui.button(label="Keep", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Kept.", view=None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Animals(bot))
