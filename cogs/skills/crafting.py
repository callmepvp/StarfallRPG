import discord
from discord.ui import Button, View, Select
from discord import app_commands
from discord.ext import commands

import typing
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

#Directory Grabbing Function (For Essences)
def getDirectory(inputRecipe):
    
    #Check, whether the recipe item is an essence (Special case -> Essences are stored in general)
    if inputRecipe != "miningEssence" and "farmingEssence" and "scavengingEssence" and "foragingEssence":
        return inventory
    else:
        return general

class crafting(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        
    #The actual crafting logic
    async def craft(self, interaction: discord.Interaction, item: str, amount: int = 1, selectedOption = False):
        if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check
            craftSuccess = False

            #Try to fetch the input recipe
            try:
                recipe = craftingData[item][0]
            except:
                if selectedOption:
                    await interaction.edit_original_response(content = "This is not a valid recipe.")
                else:
                    await interaction.response.send_message(ephemeral=True, content = "This is not a valid recipe.")
                return

            if recipes.find_one({'id' : interaction.user.id, item : {'$exists': True}}) is not None: #If recipe exists

                #Check resources
                checkedRes = 0
                for i in range(int(len(recipe)/2)):
 
                    dir = getDirectory(recipe[str(i)])

                    #Check the item and quantities
                    if dir.find_one({'id' : interaction.user.id, recipe[str(i)] : {'$exists': True}}): #Check if the item exists
                        if dir.find_one({'id' : interaction.user.id})[recipe[str(i)]] >= amount * int(recipe["r" + str(i)]): #Check if there's enough of the item
                            checkedRes += 1
                
                        #All resources exist in enough quantities
                        if checkedRes == int(len(recipe)/2):
                            craftSuccess = True
                            for j in range(checkedRes):
                                
                                dir = getDirectory(recipe[str(j)])

                                #Remove materials
                                if dir.find_one({'id' : interaction.user.id})[recipe[str(j)]] - amount * int(recipe["r" + str(j)]) != 0:
                                    dir.update_one({'id' : interaction.user.id}, {"$set":{recipe[str(j)] : dir.find_one({'id' : interaction.user.id})[recipe[str(j)]] - amount * int(recipe["r" + str(j)])}})
                                else:
                                    dir.update_one({'id' : interaction.user.id}, {'$unset' : {recipe[str(j)] : ''}})

                if not craftSuccess:
                    if selectedOption:
                        await interaction.edit_original_response(content=f"You don't have enough resources to craft **{amount}** x **{string.capwords(item)}**!")
                    else:
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

                    if selectedOption:
                        await interaction.edit_original_response(content=f"{''.join(message)}")
                    else:
                        await interaction.response.send_message(''.join(message))
        else:
            await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")

    @app_commands.command(
        name = "craft",
        description = "Sticks and stones may break your bones.")

    async def crafting(self,interaction: discord.Interaction, item: str = None, amount: int = 1):
        if general.find_one({'id' : interaction.user.id}) is not None:

            if item != None: #If an exact recipe is specified
                await self.craft(interaction, item, amount)
            else:
                #A specific recipe is not specified, send a dropdown menu
                view = DropdownView(interaction.user.id, interaction, self)
                await interaction.response.send_message("Your available crafting recipes:", view=view)
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

class Dropdown(discord.ui.Select):
    def __init__(self, user_id, interaction: discord.Interaction, mainClass: crafting):
        super().__init__(placeholder="Choose a recipe!", min_values=1, max_values=1, options=self.get_options(user_id))     
        self.id = user_id
        self.interaction = interaction
        self.mainClass = mainClass
    
    #Get the users available recipes
    def get_options(self, user_id):
        options = []

        data = recipes.find_one({'id' : int(user_id)})
        for item in data.items():
            if item[0] != '_id':
                if item[0] != 'id':
                    options.append(discord.SelectOption(label=f"{item[0]}", emoji="🥢"))

        return options

    #Sends the response message, when an option is selected
    async def callback(self, interaction: discord.Interaction):
        selectedOption = True #Necessary because the code can't differentiate between a straight input and a list-chosen 
        await self.interaction.edit_original_response(content=f"You chose **{string.capwords(self.values[0])}**!", view=None)
        await self.mainClass.craft(self.interaction, self.values[0], 1, selectedOption)
    
    #Check if the right user is editing the dropdown
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.interaction.user.id == self.id
    
    #Reset the dropdown menu
    async def on_timeout(self) -> None:
        await self.interaction.edit_original_response(content="Request Timed Out!", view=None)

class DropdownView(discord.ui.View):
    def __init__(self, user_id, interaction: discord.Interaction, mainClass: crafting):
        super().__init__()
        self.add_item(Dropdown(user_id, interaction, mainClass))

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        crafting(bot),
        guilds = [discord.Object(id = 1047945458665914388)])