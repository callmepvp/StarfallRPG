import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import random
import string
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Import all data management methods
from ..functions.dataManagement import *

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
scavengingData = loads(Path("data/skills/scavenging.json").read_text())
collectionData = loads(Path("data/collections/herb.json").read_text())
itemsData = loads(Path("data/items.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']
recipes = cluster['alphaworks']['recipes']
areas = cluster['alphaworks']['areas']

#the form to get items without using a for loop: print(itemsData['items'].get("hand", {}).get("plains", [])) -> [{'name': 'silverleaf'}, {'name': 'needlegrass'}]

class scavenging(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "scavenge",
        description = "Scavenge the grounds for useful herbs.")

    async def scavenging(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check

                choices, weights = updateAndReturnAvailableResources(interaction.user.id, "scavenging")

                if len(choices) != 0:
                    choice = random.choices(choices, weights=weights)[0]
                    amount = random.randint(1, 2)
                    xp = itemsData["items"][choice]["xp"] * amount

                    message = []
                    message.append(f":herb: You **Scavenged**! You got **{amount}** x **{string.capwords(choice)}**!")
                      
                    updateInventory(interaction.user.id, choice, amount)
                    message = updateEssence(interaction.user.id, "scavenging", xp, message)
                    message = updateSkills(interaction.user.id, "scavenging", xp, message)
                    message = updateCollections(interaction.user.id, amount, "herb", message)

                    await interaction.response.send_message(''.join(message))

                else:
                    await interaction.response.send_message(ephemeral=True, content="You don't have what it takes to scavenge!")
            else:
                await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        scavenging(bot),
        guilds = [discord.Object(id = 1047945458665914388)])