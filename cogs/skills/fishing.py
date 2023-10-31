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

class fishing(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "fish",
        description = "Empty the waters around you for resources.")

    async def fishing(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check
                
                fishCompletion = False
                choicesFish, choicesTrash, weightsFish, weightsTrash = updateAndReturnAvailableResources(interaction.user.id, "fishing", "fishingList")

                if len(choicesFish) != 0:
                    treasureThreshold = general.find_one({'id' : interaction.user.id})['treasureChance']
                    trashThreshold = general.find_one({'id' : interaction.user.id})['trashChance']

                    percentage = random.randint(1, 100)
                    choiceType = False
                    amount = 0
                    xp = 0
                    choice = False

                    if 0 < percentage <= treasureThreshold:
                        #Treasure
                        treasureChoice = random.choice(["coins", "crate"])
                        if treasureChoice == "coins":
                            choice = "coins"
                            xp = 3 #hardcoeded for coins
                            choiceType = "coins"
                            amount = random.randint(10, 500)
                        else:
                            '''
                            The Crate System will allow players to get crates through certain actions

                            The Crates include:
                            Common, Uncommon, Rare, Legendary
                            '''
                            crates = ["common crate", "uncommon crate", "rare crate", "legendary crate"]
                            choice = random.choice(crates)
                            xp = 4 #hardcoded for crates
                            choiceType = "crate"
                            amount = 1

                            cratePosition = crates.index(choice)

                    elif treasureThreshold < percentage <= trashThreshold:
                        #Trash
                        choice = random.choices(choicesTrash, weights=weightsTrash)[0]
                        amount = random.randint(1, 2)
                        xp = itemsData["items"][choice]["xp"] * amount
                        choiceType = "invItem"
                    else:
                        #Fish
                        choice = random.choices(choicesFish, weights=weightsFish)[0]
                        amount = random.randint(1, 2)
                        xp = itemsData["items"][choice]["xp"] * amount
                        choiceType = "invItem"

                    message = []
                    message.append(f":fish: You **Fished**! You got **{amount}** x **{string.capwords(choice)}**!")

                    message = updateEssence(interaction.user.id, "fishing", xp, message)
                    message = updateSkills(interaction.user.id, "fishing", xp, message)

                    if choiceType == "invItem":
                        updateInventory(interaction.user.id, choice, amount)
                        message = updateCollections(interaction.user.id, amount, "fish", message)

                    else:
                        if choiceType == "coins":
                            #give the coins
                            currentCoins = general.find_one({'id' : interaction.user.id})['wallet']
                            general.update_one({'id' : interaction.user.id}, {"$set":{'wallet' : currentCoins + amount}})
                            message.append("\n :moneybag: Treasure Catch! :moneybag:")

                        elif choiceType == "crate":
                            #update the crates
                            currentCrates = general.find_one({'id' : interaction.user.id})['crates']
                            currentCrates[cratePosition] += amount
                            general.update_one({'id' : interaction.user.id}, {"$set":{'crates' : currentCrates}})
                            message.append("\n :package: Treasure Catch! :package:")

                    await interaction.response.send_message(''.join(message))

                else:
                    await interaction.response.send_message(ephemeral=True, content="You don't have what it takes to fish!")
            else:
                await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        fishing(bot),
        guilds = [discord.Object(id = 1047945458665914388)])