"""ACKS II character sheet bot for Discord.

Run:  python bot.py      (reads DISCORD_TOKEN and friends from .env)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from acks.storage import Storage  # noqa: E402
from cogs.common import SheetPageButton, UserError, send_error  # noqa: E402

log = logging.getLogger("acks")

EXTENSIONS = ["cogs.characters", "cogs.combat", "cogs.inventory", "cogs.status", "cogs.spells", "cogs.encounter",
              "cogs.help"]


class ACKSBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default(),
                         help_command=None)
        db_path = os.getenv("DATABASE_PATH", str(ROOT / "data" / "acks.db"))
        self.storage = Storage(db_path)
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        self.add_dynamic_items(SheetPageButton)
        self._synced_guilds: set[int] = set()

    async def sync_guild(self, guild: discord.abc.Snowflake) -> None:
        """Register commands directly in one server; guild commands show up instantly."""
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        self._synced_guilds.add(guild.id)
        log.info("Synced %d commands to server %s", len(synced), getattr(guild, "name", guild.id))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s) in %d server(s)", self.user, self.user.id if self.user else "?",
                 len(self.guilds))
        guild_id = os.getenv("GUILD_ID")
        targets = [discord.Object(id=int(guild_id))] if guild_id else list(self.guilds)
        for guild in targets:
            if guild.id not in self._synced_guilds:
                await self.sync_guild(guild)
        if not targets:
            log.warning("The bot isn't in any server yet. Invite it with the OAuth2 URL Generator "
                        "(scopes: bot, applications.commands).")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        if not os.getenv("GUILD_ID"):
            await self.sync_guild(guild)

    async def on_app_command_error(self, interaction: discord.Interaction,
                                   error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, UserError):
            await send_error(interaction, str(original))
            return
        if isinstance(error, app_commands.CheckFailure):
            await send_error(interaction, "You can't use that command here.")
            return
        log.exception("Command failed", exc_info=original)
        # only the error type goes to Discord; the full message (which could name local paths) stays in the log
        await send_error(interaction, f"Something went wrong (`{type(original).__name__}`). Details are in the bot's log.")

    async def close(self) -> None:
        await super().close()
        self.storage.close()


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_TOKEN in a .env file next to bot.py (see .env.example).")
    discord.utils.setup_logging(level=logging.INFO)
    ACKSBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
