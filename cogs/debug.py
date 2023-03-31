import discord
import typing
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import io
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
craftingData = loads(Path("data/recipes/craftingRecipes.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']
OWNER_ID = data['OWNER_ID']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']
recipes = cluster['alphaworks']['recipes']
areas = cluster['alphaworks']['areas']

class debug(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "debug",
        description = "Doesn't work, does it?")

    async def debug(self,interaction: discord.Interaction, option: typing.Literal['Profile Delete'], argument: str, argument2: str = None):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if interaction.user.id == OWNER_ID:
                
                if option == 'Profile Delete':
                    #Delete any profile from the database
                    if general.find_one({'id' : int(argument)}) is not None:
                        await interaction.response.defer() #Acknowledged the interaction
                        name = general.find_one({'id' : int(argument)})['name']
                        
                        savedData = "" #Save all data as a string

                        #In the future add a check to see if the amount of collections on the database match the ones in the array
                        directories = [general, skills, collections, recipes, inventory, areas]
                        #Has to look through: general, skills, collections, recipes
                        for directory in directories: #Add all data from each document to a string and delete the document
                            for key, value in directory.find_one({'id' : int(argument)}).items():
                                if int(len(directory.find_one({'id' : int(argument)}).items())) > 2:
                                    if key != '_id':
                                        if key != 'id':
                                            savedData = savedData + str(key) + " -> " + str(value) + "\n"
                            
                            directory.delete_one({'id' : int(argument)})
                        
                        #Construct the .txt file to send
                        fileData = discord.File(io.BytesIO(savedData.encode()), filename=f"data_{int(argument)}.txt")
                        channel = self.bot.get_channel(1087847199221747804) #Hardcoded channel ID for the debug log (Change if necessary); will later be an option
                        await channel.send(f"**{interaction.user.display_name}** deleted the profile of **{name}**! \nDeleted ID: **{int(argument)}** \nStaff ID: **{interaction.user.id}** \nReason: **{str(argument2)}**", file=fileData)
                        await interaction.followup.send(ephemeral=True, content=f"Successfully deleted profile with ID **{int(argument)}** with the name **{name}**! Bye!")
                    else:
                        await interaction.response.send_message(ephemeral=True, content="ID was not found on the database!")
            else:
                await interaction.response.send_message(ephemeral=True, content="Not authorized to use this! Sorry.")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        debug(bot),
        guilds = [discord.Object(id = 1047945458665914388)])