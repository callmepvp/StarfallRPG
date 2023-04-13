import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import asyncio
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
areas = cluster['alphaworks']['areas']

class register(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "register",
        description = "Setup your profile!")

    async def register(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is None:
        
            embed = discord.Embed(title = f"Welcome to Alphaworks, {interaction.user.display_name}!", 
                                description = "*Before proceeding, please read this thoroughly!* \n\n **[1]** Do not abuse exploits or bugs of any kind. \n **[2]** Use only one account per person. \n\n:information_source: Starfall RPG processes some of your data such as username, ID and profile picture.", 
                                color = discord.Color.random(), 
                                timestamp = datetime.datetime.now())
            
            button = Button(label = "I understand.", style = discord.ButtonStyle.gray, emoji = "👌")
            async def button_callback(interaction: discord.Interaction):
                button.style = discord.ButtonStyle.green

                #Setup the profile and inventory on MongoDB
                inventory.insert_one({'id' : interaction.user.id})

                #Holds the data for all general stats on setup
                generalData = {
                    'id' : interaction.user.id,
                    'name' : interaction.user.display_name,
                    'creation' : time.time(),
                    'stamina' : 200,
                    'pickaxeTier' : 'h', 'axeTier' : 'h', 'hoeTier' : 'h', 'gloveTier' : 'h', 'rodTier' : 'h', #Tool Tiers > Necessary for limiting certain drops to certain tools
                    'miningEssence' : 0, 'foragingEssence' : 0, 'farmingEssence' : 0, 'scavengingEssence' : 0, 'fishingEssence' : 0, #Skill Essences
                    'treasureChance' : 1, 'trashChance' : 50 #Necessary fishing stats
                }

                general.insert_one(generalData)
                
                #Currently holds no use except for fishing (will be used later) (Might randomize starting location later)
                areaData = {
                    'id' : interaction.user.id,
                    'currentSubarea' : 'sunken lagoon', #Default spawning locations for every new player
                    'subareaType' : 'small', #Extra arguments for subareas, if needed
                    'currentArea' : 'plains'
                }

                areas.insert_one(areaData)

                #Holds the level, xp and bonus data for every skill => level and xp could be removed in the future & replaced with a total xp stat, which would calculate level on each command
                skillData = {
                    'id' : interaction.user.id,
                    'foragingLevel' : 0, 'foragingXP' : 0, 'foragingBonus' : 0,
                    'miningLevel' : 0, 'miningXP' : 0, 'miningBonus' : 0,
                    'farmingLevel' : 0, 'farmingXP' : 0, 'farmingBonus' : 0,
                    'craftingLevel' : 0, 'craftingXP' : 0, 'craftingBonus' : 0,
                    'scavengingLevel' : 0, 'scavengingXP' : 0, 'scavengingBonus' : 0,
                    'fishingLevel' : 0, 'fishingXP' : 0, 'fishingBonus' : 0
                }
                
                skills.insert_one(skillData)

                #Holds the data for the main collections ; These will most likely get a significant overhaul in the future
                collectionsData = {
                    'id' : interaction.user.id,
                    'wood' : 0, 'woodLevel' : 0,
                    'ore' : 0, 'oreLevel' : 0,
                    'crop' : 0, 'cropLevel' : 0,
                    'herb' : 0, 'herbLevel' : 0,
                    'fish' : 0, 'fishLevel' : 0
                }

                collections.insert_one(collectionsData)

                #Holds the data for all recipes that are given on setup, recipe data is saved as booleans
                recipeData = {
                    'id' : interaction.user.id,
                    'toolrod' : True
                }

                recipes.insert_one(recipeData)

                #Character Customization 1/x
                embed = discord.Embed(title = f"Choose Your Name, {interaction.user.display_name}! **(1/2)**", 
                                    description = "",
                                    color = discord.Color.random(), 
                                    timestamp = datetime.datetime.now())
                embed.set_footer(text="*Some quote here...*")
                            
                embed.add_field(name="Race", value="`TEST_RACE`", inline=False)
                embed.add_field(name="Race Bonus", value="`BONUS_1`", inline=True)
                embed.add_field(name="Race Bonus", value="`BONUS_2`", inline=True)
                embed.add_field(name="Lineage", value="`TEST_LINEAGE`", inline=False)
                embed.add_field(name="Area", value="`TEST_AREA`", inline=True) #Plains, Desert etc.
                embed.add_field(name="Sub-Region", value="`TEST_REGION`", inline=True) #Sunken Lagoon etc.

                embed.add_field(name="Name", value="**Who knows?**", inline=False)

                await interaction.response.edit_message(embed = embed, view = None)

                try: 
                    answer = await self.bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id and m.channel.id == interaction.channel_id, timeout=120.0)

                    #Character Customization 2/x
                    #Check if the given name is compatible and appropriate
                    embed.title = f"Customize Your Avatar, {answer.content}! **(2/2)**"
                    embed.clear_fields()
                    embed.set_image(url="https://i.ibb.co/QY3x3Vb/background.gif")

                    await answer.delete()
                    await interaction.edit_original_response(embed = embed)
                except asyncio.TimeoutError:
                    await interaction.edit_original_response(embed = None, view = None, content = "The registering process **timed out**. You have to **retry**.")

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