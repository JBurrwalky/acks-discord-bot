"""Step-by-step character creation wizard, following the Revised Rulebook's steps."""
from __future__ import annotations

import logging

import discord

from acks import embeds, rules, templates
from acks.character import Character, eligible_for, new_character_data
from acks.dice import d, fmt_mod, roll_drop_lowest

from .common import UserError, send_error, sheet_view, storage

log = logging.getLogger("acks.wizard")

WIZARD_COLOR = discord.Color.from_rgb(201, 162, 39)
ALIGNMENTS = ["Lawful", "Neutral", "Chaotic"]


class CreationWizard(discord.ui.View):
    """One ephemeral message that walks a player through creation."""

    def __init__(self, owner: discord.abc.User, guild_id: int):
        super().__init__(timeout=1800)
        self.owner = owner
        self.data = new_character_data(guild_id, owner.id)
        self.ch = Character(self.data)
        self.step = "attributes"
        self.prime: str | None = None
        self.secondary: list[str] = []
        self.attr_log: list[str] = []
        self.rolled_attrs = False
        self.hp_detail: str | None = None
        self.template_roll: int | None = None
        self.template_detail: str | None = None
        self.source = rules.SOURCES[0]
        self.style_pick: list[str] | None = None   # fighting styles picked on the class step
        self.message: discord.Message | None = None
        self.render()

    # ------------------------------------------------------------------
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("This wizard belongs to someone else. Start your own with `/create`.",
                                                    ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(content="⌛ Character creation timed out. Run `/create` to start again.",
                                        embeds=[], view=None)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        """Tell the player what broke instead of leaving Discord to say 'didn't respond'."""
        log.exception("Creation wizard error in %r", item, exc_info=error)
        await send_error(interaction, f"Something went wrong in the wizard (`{type(error).__name__}`). "
                                      "Details are in the bot's log.")

    async def refresh(self, interaction: discord.Interaction) -> None:
        self.render()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    # ------------------------------------------------------------------
    def embed(self) -> discord.Embed:
        step_no = ["attributes", "class", "hp", "template", "details"].index(self.step) + 1
        e = discord.Embed(title=f"🧙 New Adventurer — Step {step_no} of 5", color=WIZARD_COLOR)
        getattr(self, f"_embed_{self.step}")(e)
        return e

    def _attr_block(self) -> str:
        a = self.data["attributes"]
        total = sum(rules.attr_mod(a[x]) for x in rules.ATTRIBUTES)
        lines = [f"{x} {a[x]:>2} ({fmt_mod(rules.attr_mod(a[x]))})  {rules.ATTRIBUTE_NAMES[x]}"
                 for x in rules.ATTRIBUTES]
        return "```\n" + "\n".join(lines) + f"\n\nSum of modifiers: {fmt_mod(total)}\n```"

    def _embed_attributes(self, e: discord.Embed) -> None:
        e.description = (
            "**Roll your attributes.**\n"
            "• Pick **one** attribute for **5d6, drop the 2 lowest** (raised to 13 if lower).\n"
            "• Pick **two** attributes for **4d6, drop the lowest** (raised to 9 if lower).\n"
            "• The other three get **3d6**.\n"
            "Choose with the menus, then press **Roll attributes**. "
            "Or press **Enter scores** if your Judge uses another method.")
        if self.rolled_attrs:
            e.add_field(name="Your scores", value=self._attr_block(), inline=False)
            if self.attr_log:
                e.add_field(name="Rolls", value="\n".join(self.attr_log)[:1024], inline=False)
            total = sum(rules.attr_mod(v) for v in self.data["attributes"].values())
            if total < 0:
                e.add_field(name="Below average", value="Your modifiers total less than 0, so you may **re-roll**.",
                            inline=False)
        else:
            e.add_field(name="5d6 attribute", value=self.prime or "*not chosen*", inline=True)
            e.add_field(name="4d6 attributes", value=", ".join(self.secondary) or "*not chosen*", inline=True)

    def _embed_class(self, e: discord.Embed) -> None:
        a = self.data["attributes"]
        options = [c for c in rules.classes_by_source(self.source) if eligible_for(c, a)]
        book = f"Showing **{self.source}** classes; pick another book from the first menu.\n" \
            if len(rules.SOURCES) > 1 else ""
        e.description = ("**Choose a class.** Only classes whose key attributes (and any requirements) "
                         "you meet are listed.\n" + book + self._attr_block())
        if self.data["class_key"] and self.step == "class" and self.data.get("_class_chosen"):
            c = self.ch.cls
            e.add_field(name=c.name, value=(
                f"*{c.source}* · HD d{c.hit_die} · Key: {', '.join(c.key_attributes)} · Max level {c.max_level}\n"
                f"Armor: {c.armor} · Styles: {rules.describe_styles(c)}\n"
                f"XP bonus: +{self.ch.xp_bonus_pct()}%\n{c.notes}"), inline=False)
            if c.key == "barbarian":
                region = rules.BARBARIAN_REGIONS.get(self.ch.options.get("barbarian_region", ""))
                e.add_field(name="Barbarian", value=(
                    f"Region: **{region['label'] if region else 'choose one'}** · damage bonus on "
                    f"**{self.ch.options.get('barbarian_damage', 'melee')}** attacks"), inline=False)
            if c.style_choice:
                pick = c.style_choice["pick"]
                e.add_field(name="Fighting styles", value=(
                    f"Choose **{pick}** in the menu below: "
                    f"**{rules.style_choice_label(self.style_pick) if self.style_pick else 'not chosen yet'}**.\n"
                    "*A template that begins with a style will use that one instead.*"), inline=False)
        if not options:
            e.add_field(name="No eligible classes", value="Try another book, or go back and re-roll.")

    def _embed_hp(self, e: discord.Embed) -> None:
        c = self.ch.cls
        e.description = (f"**Roll hit points.** {c.name}s roll **1d{c.hit_die}"
                         f"{'+' + str(c.first_level_hp_bonus) if c.first_level_hp_bonus else ''}** at 1st level. "
                         f"A roll of 4 or less counts as 4, then add your CON modifier "
                         f"({fmt_mod(self.ch.mod('CON'))}).")
        if self.hp_detail:
            e.add_field(name="Hit points", value=self.hp_detail, inline=False)

    def _embed_template(self, e: discord.Embed) -> None:
        e.description = ("**Pick a template.** Roll 3d6 for your template; you may take the one rolled "
                         "or any **lower** one. Or skip templates and roll 3d6 × 10 gp to buy gear yourself.")
        if self.template_roll is not None:
            e.add_field(name="Template roll", value=f"🎲 3d6 = **{self.template_roll}**", inline=False)
        if self.template_detail:
            e.add_field(name="Selected", value=self.template_detail[:1024], inline=False)

    def _embed_details(self, e: discord.Embed) -> None:
        int_bonus = max(0, self.ch.mod("INT"))
        e.description = ("**Name your character** and fill in the details, then press **Create character**.\n"
                         "A preview of the finished sheet is below.")
        todo = []
        if not self.data.get("template"):
            todo.append("Choose 1 class proficiency and 1 general proficiency with `/proficiency add`.")
        if int_bonus:
            todo.append(f"Your Intellect lets you pick **{int_bonus}** more general proficienc"
                        f"{'y' if int_bonus == 1 else 'ies'} with `/proficiency add` (or leave slots open).")
        todo.append("Starting age, languages and spell repertoire can go in `/character notes`.")
        e.add_field(name="After creation", value="\n".join(f"• {t}" for t in todo), inline=False)

    # ------------------------------------------------------------------
    def render(self) -> None:
        self.clear_items()
        getattr(self, f"_render_{self.step}")()
        self.add_item(_CancelButton())

    def _render_attributes(self) -> None:
        if not self.rolled_attrs:
            self.add_item(_PrimeSelect(self))
            self.add_item(_SecondarySelect(self))
            roll_btn = _Button("Roll attributes", discord.ButtonStyle.success, self._do_roll_attrs, emoji="🎲")
            roll_btn.disabled = not (self.prime and len(self.secondary) == 2)
            self.add_item(roll_btn)
        else:
            total = sum(rules.attr_mod(v) for v in self.data["attributes"].values())
            reroll = _Button("Re-roll", discord.ButtonStyle.secondary, self._do_reroll, emoji="🔁")
            reroll.disabled = total >= 0
            self.add_item(reroll)
            self.add_item(_Button("Continue", discord.ButtonStyle.success, self._goto("class"), emoji="➡️"))
        self.add_item(_Button("Enter scores", discord.ButtonStyle.secondary, self._do_manual, emoji="✏️"))

    def _render_class(self) -> None:
        a = self.data["attributes"]
        if len(rules.SOURCES) > 1:
            self.add_item(_SourceSelect(self))
        options = [c for c in rules.classes_by_source(self.source) if eligible_for(c, a)]
        if options:
            self.add_item(_ClassSelect(self, options))
        if self.data.get("_class_chosen") and self.ch.cls.key == "barbarian":
            self.add_item(_BarbarianRegionSelect(self))
            self.add_item(_BarbarianDamageSelect(self))
        if self.data.get("_class_chosen") and self.ch.cls.style_choice:
            self.add_item(_StyleChoiceSelect(self))
        ready = bool(self.data.get("_class_chosen")) and (
            self.ch.cls.key != "barbarian" or self.ch.options.get("barbarian_region")) and (
            not self.ch.cls.style_choice or self.style_pick is not None)
        self.add_item(_Button("Back", discord.ButtonStyle.secondary, self._goto("attributes"), emoji="⬅️"))
        cont = _Button("Continue", discord.ButtonStyle.success, self._goto("hp"), emoji="➡️")
        cont.disabled = not ready
        self.add_item(cont)

    def _render_hp(self) -> None:
        rolled = self.hp_detail is not None
        b = _Button("Roll hit points", discord.ButtonStyle.success, self._do_roll_hp, emoji="🎲")
        b.disabled = rolled
        self.add_item(b)
        mx = _Button("Max HP (if your Judge allows)", discord.ButtonStyle.secondary, self._do_max_hp, emoji="✨")
        mx.disabled = rolled
        self.add_item(mx)
        cont = _Button("Continue", discord.ButtonStyle.success, self._goto("template"), emoji="➡️")
        cont.disabled = not rolled
        self.add_item(cont)

    def _render_template(self) -> None:
        if self.template_roll is None:
            self.add_item(_Button("Roll 3d6 for template", discord.ButtonStyle.success, self._do_roll_template,
                                  emoji="🎲"))
            self.add_item(_Button("No template (3d6×10 gp)", discord.ButtonStyle.secondary, self._do_no_template,
                                  emoji="💰"))
        else:
            self.add_item(_TemplateSelect(self))
        cont = _Button("Continue", discord.ButtonStyle.success, self._goto("details"), emoji="➡️")
        cont.disabled = not self.template_detail
        self.add_item(cont)

    def _render_details(self) -> None:
        self.add_item(_Button("Name & details", discord.ButtonStyle.primary, self._do_details, emoji="✏️"))
        create = _Button("Create character", discord.ButtonStyle.success, self._do_create, emoji="✅")
        create.disabled = self.data["name"] == "Unnamed"
        self.add_item(create)

    # ------------------------------------------------------------------
    def _goto(self, step: str):
        async def go(interaction: discord.Interaction) -> None:
            self.step = step
            if step == "details":
                self.render()
                await interaction.response.edit_message(embeds=[self.embed(), embeds.sheet_embed(self.ch)], view=self)
                return
            await self.refresh(interaction)
        return go

    async def _do_roll_attrs(self, interaction: discord.Interaction) -> None:
        a = self.data["attributes"]
        self.attr_log = []
        for attr in rules.ATTRIBUTES:
            if attr == self.prime:
                total, dice = roll_drop_lowest(5, 3)
                final = max(13, total)
                self.attr_log.append(f"**{attr}** 5d6 {dice} → keep 3 = {total}" + (" → 13" if final != total else ""))
            elif attr in self.secondary:
                total, dice = roll_drop_lowest(4, 3)
                final = max(9, total)
                self.attr_log.append(f"**{attr}** 4d6 {dice} → keep 3 = {total}" + (" → 9" if final != total else ""))
            else:
                dice = [d(6) for _ in range(3)]
                final = sum(dice)
                self.attr_log.append(f"**{attr}** 3d6 {dice} = {final}")
            a[attr] = final
        self.rolled_attrs = True
        self.data.pop("_class_chosen", None)
        await self.refresh(interaction)

    async def _do_reroll(self, interaction: discord.Interaction) -> None:
        self.rolled_attrs = False
        self.prime, self.secondary = None, []
        await self.refresh(interaction)

    async def _do_manual(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_ManualAttributesModal(self))

    async def _do_roll_hp(self, interaction: discord.Interaction) -> None:
        hp, detail = self.ch.roll_first_level_hp()
        self.data["hp"] = {"current": hp, "max": hp}
        self.hp_detail = detail
        await self.refresh(interaction)

    async def _do_max_hp(self, interaction: discord.Interaction) -> None:
        hp, detail = self.ch.roll_first_level_hp(maximize=True)
        self.data["hp"] = {"current": hp, "max": hp}
        self.hp_detail = detail + " *(Blessed by the Gods)*"
        await self.refresh(interaction)

    async def _do_roll_template(self, interaction: discord.Interaction) -> None:
        self.template_roll = sum(d(6) for _ in range(3))
        t = templates.template_for_roll(self.ch.cls.key, self.template_roll)
        if t:
            self.apply_template(t)
        await self.refresh(interaction)

    async def _do_no_template(self, interaction: discord.Interaction) -> None:
        self.reset_gear()
        gold, dice = templates.starting_gold_roll()
        self.data["purse"]["gp"] = gold
        self.data["template"] = ""
        self.template_roll = None
        self.template_detail = (f"**No template.** 3d6 {dice} × 10 = **{gold} gp**.\n"
                                "Buy gear with `/item add` and `/purse spend`, then `/equip` it.")
        await self.refresh(interaction)

    async def _do_details(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_DetailsModal(self))

    async def _do_create(self, interaction: discord.Interaction) -> None:
        if self.ch.id is not None:   # a second click must not save a duplicate
            raise UserError(f"**{self.ch.name}** has already been created.")
        self.data.pop("_class_chosen", None)
        store = storage(interaction)
        store.create(self.ch)
        store.set_active(self.data["guild_id"], self.owner.id, self.ch.id)
        self.stop()
        await interaction.response.edit_message(
            content=f"✅ **{self.ch.name}** has been created and is now your active character.",
            embeds=[], view=None)
        await interaction.followup.send(
            content=f"🎉 {interaction.user.mention} welcomes a new adventurer to the party!",
            embed=embeds.sheet_embed(self.ch, interaction.user.display_name), view=sheet_view(self.ch))

    # ------------------------------------------------------------------
    def reset_gear(self) -> None:
        self.data["items"] = []
        self.data["next_item_id"] = 1
        self.data["equipped"] = {"main": None, "off": None, "two_handed": False, "missile": None, "armor": None,
                                 "shield": None}
        self.data["purse"] = {c: 0 for c in rules.COIN_TYPES}
        self.data["proficiencies"] = ["Adventuring"] + self.natural_proficiencies()
        if self.style_pick is not None:
            self.data["options"]["style_choice"] = list(self.style_pick)

    def natural_proficiencies(self) -> list[str]:
        if self.ch.cls.key == "barbarian":
            region = rules.BARBARIAN_REGIONS.get(self.ch.options.get("barbarian_region", ""))
            return list(region["natural"]) if region else []
        return []

    def apply_template(self, t: dict) -> None:
        self.reset_gear()
        self.data["template"] = t["name"]
        styles, profs = templates.template_style(t)
        style_note = ""
        if styles and tuple(s for s in rules.STYLES if s in styles) in rules.style_choices(self.ch.cls):
            self.ch.set_style_choice(styles)
            changed = self.style_pick is not None and set(styles) != set(self.style_pick)
            style_note = (f"\n**Fighting style:** {rules.style_choice_label(self.ch.options['style_choice'])}"
                          + (" *(this template's style, in place of your pick)*" if changed else ""))
        for p in profs:
            if p not in self.data["proficiencies"]:
                self.data["proficiencies"].append(p)
        parsed = templates.parse_equipment(t["equipment"])
        for it in parsed.items:
            kind = it.kind if it.kind in ("weapon", "armor", "shield", "clothing", "animal") else "gear"
            self.ch.add_item(it.name, it.qty, it.stone_each, "stone", kind, it.base)
        for coin, amount in parsed.coins.items():
            self.data["purse"][coin] = self.data["purse"].get(coin, 0) + amount
        self.ch.auto_equip()
        book = f" (book: {t['book_encumbrance']})" if t.get("book_encumbrance") else ""
        caste = f"\nCaste: {t['caste']}" if t.get("caste") else ""
        self.template_detail = (
            f"**{t['name']}** ({t['roll_min']}–{t['roll_max']}){caste}\n"
            f"**Proficiencies:** {', '.join(profs)}{style_note}\n"
            f"**Equipment:** {t['equipment']}\n"
            f"**Encumbrance:** {rules.fmt_stone(self.ch.encumbrance())}{book}")


# ----------------------------------------------------------------------
# Components
# ----------------------------------------------------------------------

class _Button(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle, handler, emoji: str | None = None):
        super().__init__(label=label, style=style, emoji=emoji)
        self.handler = handler

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await self.handler(interaction)
        except UserError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)


class _CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger, emoji="✖️", row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.stop()
        await interaction.response.edit_message(content="Character creation cancelled.", embeds=[], view=None)


class _PrimeSelect(discord.ui.Select):
    def __init__(self, wiz: CreationWizard):
        opts = [discord.SelectOption(label=f"{a} — {rules.ATTRIBUTE_NAMES[a]}", value=a, default=(a == wiz.prime))
                for a in rules.ATTRIBUTES]
        super().__init__(placeholder="5d6 drop 2 (min 13): choose ONE attribute", options=opts, row=0)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wiz.prime = self.values[0]
        self.wiz.secondary = [s for s in self.wiz.secondary if s != self.wiz.prime]
        await self.wiz.refresh(interaction)


class _SecondarySelect(discord.ui.Select):
    def __init__(self, wiz: CreationWizard):
        opts = [discord.SelectOption(label=f"{a} — {rules.ATTRIBUTE_NAMES[a]}", value=a,
                                     default=(a in wiz.secondary))
                for a in rules.ATTRIBUTES if a != wiz.prime]
        super().__init__(placeholder="4d6 drop 1 (min 9): choose TWO attributes", options=opts,
                         min_values=2, max_values=2, row=1)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wiz.secondary = list(self.values)
        await self.wiz.refresh(interaction)


class _SourceSelect(discord.ui.Select):
    def __init__(self, wiz: CreationWizard):
        a = wiz.data["attributes"]
        opts = []
        for src in rules.SOURCES:
            classes = rules.classes_by_source(src)
            ok = sum(1 for c in classes if eligible_for(c, a))
            opts.append(discord.SelectOption(label=src[:100], value=src, default=(src == wiz.source),
                                             description=f"{ok} of {len(classes)} classes available to you"))
        super().__init__(placeholder="Choose a book", options=opts[:25], row=0)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wiz.source = self.values[0]
        await self.wiz.refresh(interaction)


class _ClassSelect(discord.ui.Select):
    def __init__(self, wiz: CreationWizard, options: list[rules.ClassDef]):
        chosen = wiz.data["class_key"] if wiz.data.get("_class_chosen") else None
        opts = [discord.SelectOption(
            label=c.name, value=c.key, default=(c.key == chosen),
            description=f"d{c.hit_die} HD · key {'/'.join(c.key_attributes)} · {c.armor} armor"[:100])
            for c in options[:25]]
        super().__init__(placeholder="Choose your class", options=opts, row=1)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wiz.data["class_key"] = self.values[0]
        self.wiz.data["_class_chosen"] = True
        self.wiz.data["options"] = {}
        self.wiz.style_pick = None
        self.wiz.hp_detail = None
        self.wiz.template_detail = None
        self.wiz.template_roll = None
        self.wiz.reset_gear()
        await self.wiz.refresh(interaction)


class _BarbarianRegionSelect(discord.ui.Select):
    def __init__(self, wiz: CreationWizard):
        cur = wiz.ch.options.get("barbarian_region")
        opts = [discord.SelectOption(label=r["label"], value=k, default=(k == cur),
                                     description=f"Natural proficiencies: {', '.join(r['natural'])}")
                for k, r in rules.BARBARIAN_REGIONS.items()]
        super().__init__(placeholder="Barbarian homeland region", options=opts, row=2)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wiz.ch.options["barbarian_region"] = self.values[0]
        self.wiz.reset_gear()
        self.wiz.template_detail = None
        self.wiz.template_roll = None
        await self.wiz.refresh(interaction)


class _BarbarianDamageSelect(discord.ui.Select):
    def __init__(self, wiz: CreationWizard):
        cur = wiz.ch.options.get("barbarian_damage", "melee")
        opts = [discord.SelectOption(label="Damage bonus: melee attacks", value="melee", default=cur == "melee"),
                discord.SelectOption(label="Damage bonus: missile attacks", value="missile",
                                     default=cur == "missile")]
        super().__init__(placeholder="Barbarian damage bonus", options=opts, row=3)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wiz.ch.options["barbarian_damage"] = self.values[0]
        await self.wiz.refresh(interaction)


class _StyleChoiceSelect(discord.ui.Select):
    def __init__(self, wiz: CreationWizard):
        c = wiz.ch.cls
        cur = set(wiz.style_pick or ())
        opts = [discord.SelectOption(label=rules.STYLE_LABELS[s], value=s, default=s in cur)
                for s in rules.STYLES if s in c.style_choice["options"]]
        pick = c.style_choice["pick"]
        super().__init__(placeholder=f"Choose {pick} fighting style{'s' if pick > 1 else ''}", options=opts,
                         min_values=pick, max_values=pick, row=2)
        self.wiz = wiz

    async def callback(self, interaction: discord.Interaction) -> None:
        self.wiz.ch.set_style_choice(self.values)
        self.wiz.style_pick = list(self.wiz.ch.options["style_choice"])
        await self.wiz.refresh(interaction)


class _TemplateSelect(discord.ui.Select):
    def __init__(self, wiz: CreationWizard):
        allowed = [t for t in templates.templates_for(wiz.ch.cls.key) if t["roll_min"] <= (wiz.template_roll or 0)]
        current = wiz.data.get("template")
        opts = [discord.SelectOption(label=f"{t['roll_min']}–{t['roll_max']}: {t['name']}"[:100], value=str(i),
                                     default=(t["name"] == current),
                                     description=", ".join(t["proficiencies"])[:100])
                for i, t in enumerate(allowed)]
        if not opts:
            opts = [discord.SelectOption(label="No templates available", value="-1")]
        super().__init__(placeholder="Take the rolled template or a lower one", options=opts, row=0)
        self.wiz = wiz
        self.allowed = allowed

    async def callback(self, interaction: discord.Interaction) -> None:
        idx = int(self.values[0])
        if idx >= 0:
            self.wiz.apply_template(self.allowed[idx])
        await self.wiz.refresh(interaction)


class _ManualAttributesModal(discord.ui.Modal, title="Enter attribute scores"):
    scores = discord.ui.TextInput(label="STR INT WIL DEX CON CHA (six numbers)", placeholder="13 10 9 12 15 8",
                                  max_length=40)

    def __init__(self, wiz: CreationWizard):
        super().__init__()
        self.wiz = wiz

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Creation wizard form error", exc_info=error)
        await send_error(interaction, f"Something went wrong (`{type(error).__name__}`). Details are in the bot's log.")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parts = self.scores.value.replace(",", " ").split()
        if len(parts) != 6 or not all(p.isdigit() and 3 <= int(p) <= 18 for p in parts):
            await interaction.response.send_message("⚠️ Enter exactly six scores from 3 to 18, in the order "
                                                    "STR INT WIL DEX CON CHA.", ephemeral=True)
            return
        for attr, val in zip(rules.ATTRIBUTES, parts):
            self.wiz.data["attributes"][attr] = int(val)
        self.wiz.rolled_attrs = True
        self.wiz.attr_log = ["*Entered manually.*"]
        self.wiz.data.pop("_class_chosen", None)
        await self.wiz.refresh(interaction)


class _DetailsModal(discord.ui.Modal, title="Character details"):
    char_name = discord.ui.TextInput(label="Name", max_length=60)
    alignment = discord.ui.TextInput(label="Alignment (Lawful, Neutral, or Chaotic)", default="Neutral",
                                     max_length=20)
    homeland = discord.ui.TextInput(label="Homeland", required=False, max_length=60)
    sex_age = discord.ui.TextInput(label="Sex and age (e.g. 'Male, 19')", required=False, max_length=40)
    bio = discord.ui.TextInput(label="Appearance, background, personality", required=False,
                                       style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, wiz: CreationWizard):
        super().__init__()
        self.wiz = wiz
        d = wiz.data
        if d["name"] != "Unnamed":
            self.char_name.default = d["name"]
        self.alignment.default = d.get("alignment") or "Neutral"
        self.homeland.default = d.get("homeland") or None
        sa = ", ".join(x for x in (d.get("sex"), str(d.get("age") or "")) if x)
        self.sex_age.default = sa or None
        self.bio.default = d.get("description") or None

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Creation wizard form error", exc_info=error)
        await send_error(interaction, f"Something went wrong (`{type(error).__name__}`). Details are in the bot's log.")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        d = self.wiz.data
        d["name"] = self.char_name.value.strip() or "Unnamed"
        align = self.alignment.value.strip().capitalize()
        d["alignment"] = next((a for a in ALIGNMENTS if a.lower().startswith(align.lower()[:3])), align) \
            if align else "Neutral"
        d["homeland"] = self.homeland.value.strip()
        parts = [p.strip() for p in self.sex_age.value.split(",")]
        d["sex"] = parts[0] if parts and parts[0] else ""
        d["age"] = parts[1] if len(parts) > 1 else ""
        d["description"] = self.bio.value.strip()
        self.wiz.render()
        await interaction.response.edit_message(embeds=[self.wiz.embed(), embeds.sheet_embed(self.wiz.ch)],
                                                view=self.wiz)
