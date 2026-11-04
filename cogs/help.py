"""/help: lists every command, built from the registered command tree so it never goes stale."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from acks import embeds

# Display order and grouping. Commands not listed here land in "Other".
CATEGORIES: list[tuple[str, list[str]]] = [
    ("🧙 Characters", ["create", "sheet", "character", "xp", "levelup"]),
    ("⚔️ Combat", ["mattack", "rattack", "initiative", "encounter"]),
    ("🛡️ Saving Throws", ["save_paralysis", "save_death", "save_blast", "save_implements", "save_spells"]),
    ("🎒 Inventory & Equipment", ["item", "purse", "equip", "unequip"]),
    ("🐴 Animals", ["animal"]),
    ("❤️ Hit Points, Modifiers & Proficiencies", ["hp", "modifier", "proficiency"]),
    ("✨ Spells", ["spell"]),
    ("🎲 Dice", ["roll", "throw"]),
    ("❓ Help", ["help"]),
]


def _lines_for(cmd: app_commands.Command | app_commands.Group) -> list[str]:
    if isinstance(cmd, app_commands.Group):
        lines = []
        for sub in cmd.commands:
            if isinstance(sub, app_commands.Group):   # e.g. /animal item add
                lines += [f"`/{cmd.name} {sub.name} {leaf.name}` — {leaf.description}" for leaf in sub.commands]
            else:
                lines.append(f"`/{cmd.name} {sub.name}` — {sub.description}")
        return lines
    required = " ".join(p.name for p in cmd.parameters if p.required)
    usage = f"/{cmd.name}" + (f" {required}" if required else "")
    return [f"`{usage}` — {cmd.description}"]


def help_embeds(tree: app_commands.CommandTree) -> list[discord.Embed]:
    cmds = {c.name: c for c in tree.get_commands()}
    seen: set[str] = set()
    sections: list[tuple[str, list[str]]] = []
    for title, names in CATEGORIES:
        lines = []
        for n in names:
            if n in cmds:
                lines += _lines_for(cmds[n])
                seen.add(n)
        if lines:
            sections.append((title, lines))
    leftovers = [line for n, c in sorted(cmds.items()) if n not in seen for line in _lines_for(c)]
    if leftovers:
        sections.append(("Other", leftovers))

    first = discord.Embed(
        title="📖 ACKS II Character Manager — Commands",
        description=("Most commands act on your **active character** (set it with `/character select`) "
                     "or take an optional `character` option. Start with `/create`.\n"
                     "Judges (Manage Server permission or the Judge role) can edit anyone's character."),
        color=embeds.INFO_COLOR)
    out = [first]
    current = first
    for title, lines in sections:
        # split long sections across fields (1,024 chars each), and embeds (6,000 chars each)
        chunks, chunk = [], ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1024:
                chunks.append(chunk)
                chunk = ""
            chunk += line + "\n"
        chunks.append(chunk)
        for i, c in enumerate(chunks):
            name = title if i == 0 else f"{title} (cont.)"
            if len(current) + len(name) + len(c) > 5800 or len(current.fields) >= 25:
                current = discord.Embed(color=embeds.INFO_COLOR)
                out.append(current)
            current.add_field(name=name, value=c, inline=False)
    out[-1].set_footer(text="Tip: type / and click the bot's icon to browse commands with their options.")
    return out


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="List all of the bot's commands")
    @app_commands.describe(public="Post the list in the channel instead of only showing it to you")
    async def help(self, interaction: discord.Interaction, public: bool = False) -> None:
        await interaction.response.send_message(embeds=help_embeds(interaction.client.tree)[:10],
                                                ephemeral=not public)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
