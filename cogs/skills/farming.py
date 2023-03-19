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
farmingData = loads(Path("data/skills/farming.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']

class farming(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "farm",
        description = "Farm the bountiful fields for resources.")

    async def farming(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check

                #Choosing the farming item
                weights = []
                choices = []

                #Create a list of choices if the requirements are met
                tier = general.find_one({'id' : interaction.user.id})['hoeTier'] #Current Hoe Tier
                for item in list(farmingData):
                    if tier in farmingData[item][0]['tiers']:
                        choices.append(item)
                        weights.append(farmingData[item][0]['weight'])

                if len(choices) != 0:
                    crop = random.choices(choices, weights=weights)[0]
                    amount = random.randint(1, 2)

                    #Update inventory and send response
                    message = []

                    currentInventory = inventory.find_one({'id' : interaction.user.id, crop : {'$exists' : True}})
                    if currentInventory is None:
                        inventory.update_one({'id' : interaction.user.id}, {"$set":{crop : amount}})
                    else:
                        inventory.update_one({'id' : interaction.user.id}, {"$set":{crop : currentInventory[crop] + amount}})

                    message.append(f":seedling: You **Farmed**! You got **{amount}** x **{string.capwords(crop)}**!")

                    #Give skill XP
                    xp = farmingData[crop][0]['xp'] * amount
                    existingXP = skills.find_one({'id' : interaction.user.id})['farmingXP']
                    existingLevel = skills.find_one({'id' : interaction.user.id})['farmingLevel']
                    existingBonus = skills.find_one({'id' : interaction.user.id})['farmingBonus']
                    bonusAmount = 4 #Increase this skills bonus by this amount each level up
                    
                    if existingXP + xp >= (50*existingLevel+10):
                        leftoverXP = (existingXP + xp) - (50*existingLevel+10)
                        if leftoverXP == 0:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'farmingXP' : 0, 'farmingLevel' : existingLevel + 1}})
                        else:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'farmingXP' : leftoverXP, 'farmingLevel' : existingLevel + 1}})

                        skills.update_one({'id' : interaction.user.id}, {"$set":{'farmingBonus' : existingBonus + bonusAmount}})
                        message.append('\n' f':star: You gained **{xp} Farming** XP!' '\n' f'**[LEVEL UP]** Your **Farming** leveled up! You are now **Farming** level **{existingLevel + 1}**!' '\n' f'**[LEVEL BONUS]** **WIP** Bonus: **{existingBonus}** ⇒ **{existingBonus + bonusAmount}**')
                    else:
                        skills.update_one({'id' : interaction.user.id}, {"$set":{'farmingXP' : existingXP + xp}})
                        message.append('\n' f':star: You gained **{xp} Farming** XP!')
                    
                    #Give Collections
                    currentCrop = collections.find_one({'id' : interaction.user.id})['crop']
                    currentCropLevel = collections.find_one({'id' : interaction.user.id})['cropLevel']

                    if currentCrop + amount >= (currentCropLevel*50 + 50):
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'crop' : currentCrop + amount}})
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'cropLevel' : currentCropLevel + 1}})
                        message.append('\n' f'**[COLLECTION]** **Crop** Collection Level **{currentCropLevel}** ⇒ **{currentCropLevel + 1}**')
                    else:
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'crop' : currentCrop + amount}})

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