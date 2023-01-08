import discord
import interactions
from discord.ui import Button, View
import datetime
from discord import app_commands
from discord.ext import commands

class play(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "play",
        description = "Setup your profile!")

    async def play(self,interaction: discord.Interaction):
        
        embed = discord.Embed(title = f"Welcome to Starfall, {interaction.user.display_name}!", 
                            description = "*Before proceeding please read this thoroughly!* \n\n **[1]** Do not abuse exploits or bugs of any kind \n **[2]** Use only one account per person", 
                            color = discord.Color.random(), 
                            timestamp = datetime.datetime.now())

        button = Button(label = "I understand.", style = discord.ButtonStyle.gray, emoji = "👌")

        async def button_callback(interaction):
            button.style = discord.ButtonStyle.green
            await interaction.response.edit_message(content="Profile Setup, Happy Playing!", embed = None, view = None)

        button.callback = button_callback

        view = View()
        view.add_item(button)

        await interaction.response.send_message(ephemeral = True, embed = embed, view = view)
    
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        play(bot),
        guilds = [discord.Object(id = 1047945458665914388)])