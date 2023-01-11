import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import datetime
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']

class register(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "register",
        description = "Setup your profile!")

    async def play(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is None:
        
            embed = discord.Embed(title = f"Welcome to Alphaworks, {interaction.user.display_name}!", 
                                description = "*Before proceeding, please read this thoroughly!* \n\n **[1]** Do not abuse exploits or bugs of any kind \n **[2]** Use only one account per person", 
                                color = discord.Color.random(), 
                                timestamp = datetime.datetime.now())

            embed.set_author(name = interaction.user)

            button = Button(label = "I understand.", style = discord.ButtonStyle.gray, emoji = "👌")
            async def button_callback(interaction):
                button.style = discord.ButtonStyle.green

                #Setup the profile and inventory on MongoDB
                inventory.insert_one({'id' : interaction.user.id})
                general.insert_one({'id' : interaction.user.id, 'name' : interaction.user.display_name})

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