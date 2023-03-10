import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import datetime
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']

class mining(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "mine",
        description = "Mine rocks for resources.")

    async def play(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            pass
        else:
            await interaction.response.send_message("Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        mining(bot),
        guilds = [discord.Object(id = 1047945458665914388)])