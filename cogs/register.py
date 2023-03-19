import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import datetime
import time
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']
recipes = cluster['alphaworks']['recipes']

class register(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "register",
        description = "Setup your profile!")

    async def register(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is None:
        
            embed = discord.Embed(title = f"Welcome to Alphaworks, {interaction.user.display_name}!", 
                                description = "*Before proceeding, please read this thoroughly!* \n\n **[1]** Do not abuse exploits or bugs of any kind \n **[2]** Use only one account per person", 
                                color = discord.Color.random(), 
                                timestamp = datetime.datetime.now())

            button = Button(label = "I understand.", style = discord.ButtonStyle.gray, emoji = "👌")
            async def button_callback(interaction):
                button.style = discord.ButtonStyle.green

                #Setup the profile and inventory on MongoDB
                inventory.insert_one({'id' : interaction.user.id})

                generalData = {
                    'id' : interaction.user.id,
                    'name' : interaction.user.display_name,
                    'creation' : time.time(),
                    'stamina' : 200,
                    'pickaxeTier' : 'h', 'axeTier' : 'h', 'hoeTier' : 'h' #Tool Tiers > Necessary for limiting certain drops to certain tools
                }

                general.insert_one(generalData)

                skillData = {
                    'id' : interaction.user.id,
                    'foragingLevel' : 0, 'foragingXP' : 0, 'foragingBonus' : 0,
                    'miningLevel' : 0, 'miningXP' : 0, 'miningBonus' : 0,
                    'farmingLevel' : 0, 'farmingXP' : 0, 'farmingBonus' : 0
                }
                
                skills.insert_one(skillData)

                collectionsData = {
                    'id' : interaction.user.id,
                    'wood' : 0, 'woodLevel' : 0,
                    'ore' : 0, 'oreLevel' : 0,
                    'crop' : 0, 'cropLevel' : 0
                }

                collections.insert_one(collectionsData)

                recipeData = {
                    'id' : interaction.user.id,
                    'toolrod' : True
                }

                recipes.insert_one(recipeData)

                await interaction.response.edit_message(content="Profile Setup, Happy Playing!", embed = None, view = None)

            button.callback = button_callback

            view = View()
            view.add_item(button)

            await interaction.response.send_message(ephemeral = True, embed = embed, view = view)

        else:
            await interaction.response.send_message(ephemeral=True, content="Sorry, you already have an account setup. If you feel that this is an error, please contact me personally. [`pvp#7272`]")
    
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        register(bot),
        guilds = [discord.Object(id = 1047945458665914388)])