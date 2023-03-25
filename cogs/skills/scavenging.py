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
scavengingData = loads(Path("data/skills/scavenging.json").read_text())
collectionData = loads(Path("data/collections/herb.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']
recipes = cluster['alphaworks']['recipes']

class scavenging(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "scavenge",
        description = "Scavenge the grounds for useful herbs.")

    async def scavenging(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check

                #Choosing the scavenging item
                weights = []
                choices = []

                #Create a list of choices if the requirements are met
                tier = general.find_one({'id' : interaction.user.id})['gloveTier'] #Current Hoe Tier
                for item in list(scavengingData):
                    if tier in scavengingData[item][0]['tiers']:
                        choices.append(item)
                        weights.append(scavengingData[item][0]['weight'])

                if len(choices) != 0:
                    herb = random.choices(choices, weights=weights)[0]
                    amount = random.randint(1, 2)

                    #Update inventory and send response
                    message = []

                    currentInventory = inventory.find_one({'id' : interaction.user.id, herb : {'$exists' : True}})
                    if currentInventory is None:
                        inventory.update_one({'id' : interaction.user.id}, {"$set":{herb : amount}})
                    else:
                        inventory.update_one({'id' : interaction.user.id}, {"$set":{herb : currentInventory[herb] + amount}})

                    message.append(f":herb: You **Scavenged**! You got **{amount}** x **{string.capwords(herb)}**!")

                    #Give skill XP
                    xp = scavengingData[herb][0]['xp'] * amount
                    existingXP = skills.find_one({'id' : interaction.user.id})['scavengingXP']
                    existingLevel = skills.find_one({'id' : interaction.user.id})['scavengingLevel']
                    existingBonus = skills.find_one({'id' : interaction.user.id})['scavengingBonus']
                    existingEssence = general.find_one({'id' : interaction.user.id})['scavengingEssence']
                    bonusAmount = 1 #Increase this skills bonus by this amount each level up

                    #Give essence
                    essenceFormula = round((xp * 0.35), 2)
                    general.update_one({'id' : interaction.user.id}, {"$set":{'scavengingEssence' : existingEssence + essenceFormula}})
                    message.append(f"\n :sparkles: You gained **{essenceFormula} Scavenging Essence**!")
                    
                    if existingXP + xp >= (50*existingLevel+10):
                        leftoverXP = (existingXP + xp) - (50*existingLevel+10)
                        if leftoverXP == 0:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'scavengingXP' : 0, 'scavengingLevel' : existingLevel + 1}})
                        else:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'scavengingXP' : leftoverXP, 'scavengingLevel' : existingLevel + 1}})

                        skills.update_one({'id' : interaction.user.id}, {"$set":{'scavengingBonus' : existingBonus + bonusAmount}})
                        message.append('\n' f':star: You gained **{xp} Scavenging** XP!' '\n' f'**[LEVEL UP]** Your **Scavenging** leveled up! You are now **Scavenging** level **{existingLevel + 1}**!' '\n' f'**[LEVEL BONUS]** **WIP** Bonus: **{existingBonus}** ⇒ **{existingBonus + bonusAmount}**')
                    else:
                        skills.update_one({'id' : interaction.user.id}, {"$set":{'scavengingXP' : existingXP + xp}})
                        message.append('\n' f':star: You gained **{xp} Scavenging** XP!')
                    
                    #Give Collections
                    currentHerb = collections.find_one({'id' : interaction.user.id})['herb']
                    currentHerbLevel = collections.find_one({'id' : interaction.user.id})['herbLevel']

                    if currentHerb + amount >= (currentHerbLevel*50 + 50):
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'herb' : currentHerb + amount}})
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'herbLevel' : currentHerbLevel + 1}})
                        message.append('\n' f'**[COLLECTION]** **Herb** Collection Level **{currentHerbLevel}** ⇒ **{currentHerbLevel + 1}**')
                    
                        #Give collection rewards
                        for i in collectionData[f"{collections.find_one({'id' : interaction.user.id})['herbLevel']}"]:
                            recipes.update_one({'id' : interaction.user.id}, {"$set":{i : True}}) #Update the users recipes
                    else:
                        collections.update_one({'id' : interaction.user.id}, {"$set":{'herb' : currentHerb + amount}})

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