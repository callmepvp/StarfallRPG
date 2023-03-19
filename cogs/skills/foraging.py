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
foragingData =loads(Path("data/skills/foraging.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']

#Hand > Wooden Axe > Copper Axe > Iron Axe > Steel Axe > Gold Axe

class foraging(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "forage",
        description = "Forage the woods for resources.")

    async def foraging(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check

                #Choosing the foraging item
                weights = []
                choices = []

                #Create a list of choices if the requirements are met
                tier = general.find_one({'id' : interaction.user.id})['axeTier'] #Current Axe Tier
                for item in list(foragingData):
                    if tier in foragingData[item][0]['tiers']:
                        choices.append(item)
                        weights.append(foragingData[item][0]['weight'])

                if len(choices) != 0:
                    wood = random.choices(choices, weights=weights)[0]
                    amount = random.randint(1, 2)

                    #Update inventory and send response
                    message = []

                    currentInventory = inventory.find_one({'id' : interaction.user.id, wood : {'$exists' : True}})
                    if currentInventory is None:
                        inventory.update_one({'id' : interaction.user.id}, {"$set":{wood : amount}})
                    else:
                        inventory.update_one({'id' : interaction.user.id}, {"$set":{wood : currentInventory[wood] + amount}})

                    message.append(f":axe: You **Foraged**! You got **{amount}** x **{string.capwords(wood)}**!")

                    #Give skill XP
                    xp = foragingData[wood][0]['xp'] * amount
                    existingXP = skills.find_one({'id' : interaction.user.id})['foragingXP']
                    existingLevel = skills.find_one({'id' : interaction.user.id})['foragingLevel']
                    existingBonus = skills.find_one({'id' : interaction.user.id})['foragingBonus']
                    bonusAmount = 1 #Increase this skills bonus by this amount each level up
                    
                    if existingXP + xp >= (50*existingLevel+10):
                        leftoverXP = (existingXP + xp) - (50*existingLevel+10)
                        if leftoverXP == 0:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'foragingXP' : 0, 'foragingLevel' : existingLevel + 1}})
                        else:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'foragingXP' : leftoverXP, 'foragingLevel' : existingLevel + 1}})

                        skills.update_one({'id' : interaction.user.id}, {"$set":{'foragingBonus' : existingBonus + bonusAmount}})
                        message.append('\n' f':star: You gained **{xp} Foraging** XP!' '\n' f'**[LEVEL UP]** Your **Foraging** leveled up! You are now **Foraging** level **{existingLevel + 1}**!' '\n' f'**[LEVEL BONUS]** **WIP** Bonus: **{existingBonus}** ⇒ **{existingBonus + bonusAmount}**')
                    else:
                        skills.update_one({'id' : interaction.user.id}, {"$set":{'foragingXP' : existingXP + xp}})
                        message.append('\n' f':star: You gained **{xp} Foraging** XP!')
                    
                    #Give Collections
                    currentWood = collections.find_one({'id' : interaction.user.id})['wood']
                    currentWoodLevel = collections.find_one({'id' : interaction.user.id})['woodLevel']

                    if currentWood + amount >= (currentWoodLevel*50 + 50):
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'wood' : currentWood + amount}})
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'woodLevel' : currentWoodLevel + 1}})
                        message.append('\n' f'**[COLLECTION]** **Wood** Collection Level **{currentWoodLevel}** ⇒ **{currentWoodLevel + 1}**')
                    else:
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'wood' : currentWood + amount}})

                    await interaction.response.send_message(''.join(message))
                else:
                    await interaction.response.send_message(ephemeral=True, content="You don't have a sufficient axe to forage!")
            else:
                await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        foraging(bot),
        guilds = [discord.Object(id = 1047945458665914388)])