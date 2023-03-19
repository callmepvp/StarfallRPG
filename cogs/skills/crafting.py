import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import random
import string
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
craftingData = loads(Path("data/recipes/craftingRecipes.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
recipes = cluster['alphaworks']['recipes']

class crafting(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "craft",
        description = "Sticks and stones may break your bones.")

    async def crafting(self,interaction: discord.Interaction, item: str, amount: int = 1):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check
                craftSuccess = False

                try:
                    recipe = craftingData[item][0]
                except:
                    await interaction.response.send_message(ephemeral=True, content = "This is not a valid recipe.")
                    return

                if recipes.find_one({'id' : interaction.user.id, item : {'$exists': True}}) is not None: #If recipe exists

                    #Check resources
                    checkedRes = 0
                    for i in range(int(len(recipe)/2)):
                        dir = inventory #Directory variable (Technically deprecated, but can't be bothered to change)

                        if dir.find_one({'id' : interaction.user.id, recipe[str(i)] : {'$exists': True}}):
                            if dir.find_one({'id' : interaction.user.id})[recipe[str(i)]] >= amount * int(recipe["r" + str(i)]):
                                checkedRes += 1

                            if checkedRes == int(len(recipe)/2):
                                craftSuccess = True
                                for j in range(checkedRes):

                                    if dir.find_one({'id' : interaction.user.id})[recipe[str(j)]] - amount * int(recipe["r" + str(j)]) != 0:
                                        dir.update_one({'id' : interaction.user.id}, {"$set":{recipe[str(j)] : dir.find_one({'id' : interaction.user.id})[recipe[str(j)]] - amount * int(recipe["r" + str(j)])}})
                                    else:
                                        dir.update_one({'id' : interaction.user.id}, {'$unset' : {recipe[str(j)] : ''}})

                    if not craftSuccess:
                        await interaction.response.send_message(ephemeral=True, content=f"You don't have enough resources to craft **{amount}** x **{string.capwords(item)}**!")
            else:
                await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        crafting(bot),
        guilds = [discord.Object(id = 1047945458665914388)])