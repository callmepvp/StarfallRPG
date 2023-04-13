import discord
import typing
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

#Misc Imports
import sys
import platform
import datetime
import os
import io

from json import loads
from pathlib import Path

from pymongo import MongoClient

START_TIME = datetime.datetime.now()

#Misc Functions
def countLines(directory):
    totalLines = 0
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r') as f:
                    lines = f.readlines()
                    totalLines += len(lines)
    return totalLines

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

    async def debug(self,interaction: discord.Interaction, option: typing.Literal['Profile Delete', 'Info'], argument: str, argument2: str = None):
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
                        #Has to look through: general, skills, collections, recipes, areas
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

                elif option == "Info":
                    """
                    The Info Command will show an embed of following data:
                    The Host System, Ping, Python and Discord.py Versions, Uptime, Line Count, Command Count
                    """
                    embed = discord.Embed(title="Bot Information", description="", color=discord.Color.random(), timestamp=datetime.datetime.now())
                    embed.add_field(name="Host", value=f"`{platform.system()}`", inline=False)
                    embed.add_field(name="Python Version", value=f"`{sys.version}`", inline=True)
                    embed.add_field(name="Discord.Py Version", value=f"`{discord.__version__}`", inline=True)
                    embed.add_field(name="Ping", value=f"`{self.bot.latency * 1000} ms`", inline=False)
                    embed.add_field(name="Uptime", value=f"`{datetime.datetime.now() - START_TIME}`", inline=True)

                    embed.add_field(name="Line Count", value=f"`{countLines(os.getcwd())}`", inline=False) #Add this to the nightly database update (Alongside leaderboards)
                    embed.add_field(name="Command Count", value=f"`{len([cmd for cmd in self.bot.commands if not cmd.hidden])}`", inline=True) #Do this in the nightly update manually and add to db

                    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar)
                    embed.set_footer(text="*Some quote here...*")

                    await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message(ephemeral=True, content="Not authorized to use this! Sorry.")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        debug(bot),
        guilds = [discord.Object(id = 1047945458665914388)])