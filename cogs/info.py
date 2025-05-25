# cogs/misc.py

import os
import sys
import platform
import datetime
from pathlib import Path
from typing import NoReturn

import discord
from discord import app_commands
from discord.ext import commands

START_TIME = datetime.datetime.utcnow()

def count_lines(directory: Path) -> int:
    """
    Count all Python source lines under the given directory.
    """
    total = 0
    for path in directory.rglob("*.py"):
        try:
            total += len(path.read_text(encoding="utf-8").splitlines())
        except Exception:
            continue
    return total

class InfoCog(commands.Cog):
    """Provides bot and environment information via `/info`."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="info",
        description="📰 Show bot status, uptime, versions, and code statistics."
    )
    async def info(self, interaction: discord.Interaction) -> None:
        # Only allow registered users
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id
        profile = await db.general.find_one({"id": user_id})
        if not profile:
            return await interaction.response.send_message(
                "❌ Please `/register` before using this command.",
                ephemeral=True
            )

        # Build embed
        now = datetime.datetime.utcnow()
        uptime = now - START_TIME
        line_count = count_lines(Path(os.getcwd()))
        text_cmds = len([c for c in self.bot.commands if not c.hidden])
        slash_cmds = len(self.bot.tree.get_commands())
        total_cmds = text_cmds + slash_cmds

        embed = discord.Embed(
            title="🤖 Bot Information",
            color=discord.Color.blurple(),
            timestamp=now
        )
        embed.add_field(name="Host OS",      value=f"`{platform.system()}`", inline=True)
        embed.add_field(name="Python",       value=f"`{sys.version.split()[0]}`", inline=True)
        embed.add_field(name="discord.py",   value=f"`{discord.__version__}`", inline=True)
        embed.add_field(name="Ping",         value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        embed.add_field(name="Uptime",       value=f"`{str(uptime).split('.')[0]}`", inline=True)
        embed.add_field(name="Code Lines",   value=f"`{line_count:,}`", inline=True)
        embed.add_field(name="Text Commands",  value=f"`{text_cmds}`", inline=True)
        embed.add_field(name="Slash Commands", value=f"`{slash_cmds}`", inline=True)

        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar
        )
        embed.set_footer(text="Starfall RPG • info")

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot) -> NoReturn:
    from settings import GUILD_ID
    await bot.add_cog(
        InfoCog(bot),
        guilds=[discord.Object(id=GUILD_ID)]
    )