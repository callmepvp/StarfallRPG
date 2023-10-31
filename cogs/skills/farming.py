import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import math
import random
import string
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Import all data management methods
from ..functions.dataManagement import *

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
itemsData = loads(Path("data/items.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']

class farming(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "farm",
        description = "Farm the bountiful fields for resources.")

    async def farming(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check

                choices, weights = updateAndReturnAvailableResources(interaction.user.id, "farming")

                if len(choices) != 0:
                    choice = random.choices(choices, weights=weights)[0]
                    amount = random.randint(1, 2)
                    xp = itemsData["items"][choice]["xp"] * amount

                    message = []
                    message.append(f":ear_of_rice: You **Farmed**! You got **{amount}** x **{string.capwords(choice)}**!")
                        
                    updateInventory(interaction.user.id, choice, amount)
                    message = updateEssence(interaction.user.id, "farming", xp, message)
                    message = updateSkills(interaction.user.id, "farming", xp, message)
                    message = updateCollections(interaction.user.id, amount, "crop", message)

                    await interaction.response.send_message(''.join(message))

                else:
                    await interaction.response.send_message(ephemeral=True, content="You don't have what it takes to farm!")
            else:
                await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        farming(bot),
        guilds = [discord.Object(id = 1047945458665914388)])