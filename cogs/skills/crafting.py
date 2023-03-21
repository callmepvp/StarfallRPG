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
skills = cluster['alphaworks']['skills']

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

                #Try to fetch the input recipe
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

                        #Craft was successful => Give the item
                        currentInventory = inventory.find_one({'id' : interaction.user.id, item : {'$exists' : True}})
                        if currentInventory is None:
                            inventory.update_one({'id' : interaction.user.id}, {"$set":{item : amount}})
                        else:
                            inventory.update_one({'id' : interaction.user.id}, {"$set":{item : currentInventory[item] + amount}})

                        message = []
                        message.append(f":hammer_pick: You **Crafted**! You got **{amount}** x **{string.capwords(item)}**!")

                        #Calculate and give skill xp
                        #Current formula -> Multplies used item amount with 1 * amount crafted
                        #Should revamp this formula -> Maybe use the base xp of each item square rooted or divided * amount crafted
                        existingXP = skills.find_one({'id' : interaction.user.id})['craftingXP']
                        existingLevel = skills.find_one({'id' : interaction.user.id})['craftingLevel']
                        existingBonus = skills.find_one({'id' : interaction.user.id})['craftingBonus']
                        bonusAmount = 1 #Increase this skills bonus by this amount each level up
                        xp = 1 * amount
                        for w in range(int(len(recipe)/2)):
                            xp = xp * int(recipe["r" + str(w)])

                        if existingXP + xp >= (50*existingLevel+10):
                            leftoverXP = (existingXP + xp) - (50*existingLevel+10)
                            if leftoverXP == 0:
                                skills.update_one({'id' : interaction.user.id}, {"$set":{'craftingXP' : 0, 'craftingLevel' : existingLevel + 1}})
                            else:
                                skills.update_one({'id' : interaction.user.id}, {"$set":{'craftingXP' : leftoverXP, 'craftingLevel' : existingLevel + 1}})

                            skills.update_one({'id' : interaction.user.id}, {"$set":{'craftingBonus' : existingBonus + bonusAmount}})
                            message.append('\n' f':star: You gained **{xp} Crafting** XP!' '\n' f'**[LEVEL UP]** Your **Crafting** leveled up! You are now **Crafting** level **{existingLevel + 1}**!' '\n' f'**[LEVEL BONUS]** **WIP** Bonus: **{existingBonus}** ⇒ **{existingBonus + bonusAmount}**')
                        else:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'craftingXP' : existingXP + xp}})
                            message.append('\n' f':star: You gained **{xp} Crafting** XP!')
            else:
                await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        crafting(bot),
        guilds = [discord.Object(id = 1047945458665914388)])