import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import string
import random
import datetime
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
miningData = loads(Path("data/skills/mining.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']

class mining(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "mine",
        description = "Mine rocks for resources.")

    async def play(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check

                #Choosing the mining item
                weights = []
                choices = []

                #Create a list of choices if the requirements are met
                tier = general.find_one({'id' : interaction.user.id})['pickaxeTier'] #Current Pick Tier
                for item in list(miningData):
                    if tier in miningData[item][0]['tiers']:
                        choices.append(item)
                        weights.append(miningData[item][0]['weight'])

                if len(choices) != 0:
                    ore = random.choices(choices, weights=weights)[0]
                    amount = random.randint(1, 2)

                    #Update inventory and send response
                    message = []

                    currentInventory = inventory.find_one({'id' : interaction.user.id, ore : {'$exists' : True}})
                    if currentInventory is None:
                        inventory.update_one({'id' : interaction.user.id}, {"$set":{ore : amount}})
                    else:
                        inventory.update_one({'id' : interaction.user.id}, {"$set":{ore : currentInventory[ore] + amount}})

                    message.append(f":pick: You **Mined**! You got **{amount}** x **{string.capwords(ore)}**!")

                    #Give skill XP
                    xp = miningData[ore][0]['xp'] * amount
                    existingXP = skills.find_one({'id' : interaction.user.id})['miningXP']
                    existingLevel = skills.find_one({'id' : interaction.user.id})['miningLevel']
                    existingBonus = skills.find_one({'id' : interaction.user.id})['miningBonus']
                    bonusAmount = 2 #Increase this skills bonus by this amount each level up
                    
                    if existingXP + xp >= (50*existingLevel+10):
                        leftoverXP = (existingXP + xp) - (50*existingLevel+10)
                        if leftoverXP == 0:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'miningXP' : 0, 'miningLevel' : existingLevel + 1}})
                        else:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'miningXP' : leftoverXP, 'miningLevel' : existingLevel + 1}})

                        skills.update_one({'id' : interaction.user.id}, {"$set":{'miningBonus' : existingBonus + bonusAmount}})
                        message.append('\n' f':star: You gained **{xp} Mining** XP!' '\n' f'**[LEVEL UP]** Your **Mining** leveled up! You are now **Mining** level **{existingLevel + 1}**!' '\n' f'**[LEVEL BONUS]** **WIP** Bonus: **{existingBonus}** ⇒ **{existingBonus + bonusAmount}**')
                    else:
                        skills.update_one({'id' : interaction.user.id}, {"$set":{'miningXP' : existingXP + xp}})
                        message.append('\n' f':star: You gained **{xp} Mining** XP!')
                    
                    #Give Collections
                    currentOre = collections.find_one({'id' : interaction.user.id})['ore']
                    currentOreLevel = collections.find_one({'id' : interaction.user.id})['oreLevel']

                    if currentOre + amount >= (currentOreLevel*50 + 50):
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'ore' : currentOre + amount}})
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'oreLevel' : currentOreLevel + 1}})
                        message.append('\n' f'**[COLLECTION]** **Ore** Collection Level **{currentOreLevel}** ⇒ **{currentOreLevel + 1}**')
                    else:
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'ore' : currentOre + amount}})

                    await interaction.response.send_message(''.join(message))
                else:
                    await interaction.response.send_message(ephemeral=True, content="You don't have a sufficient pickaxe to mine!")
            else:
                await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")
        else:
            await interaction.response.send_message("Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        mining(bot),
        guilds = [discord.Object(id = 1047945458665914388)])