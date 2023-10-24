import discord
from discord.ui import Button, View
from discord import app_commands
from discord.ext import commands

import math
import random
import string
from json import loads
from pathlib import Path

from pymongo import MongoClient

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
fishingData = loads(Path("data/skills/fishing.json").read_text())
collectionData = loads(Path("data/collections/fish.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']
recipes = cluster['alphaworks']['recipes']
areas = cluster['alphaworks']['areas']

class fishing(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name = "fish",
        description = "Empty the waters around you for resources.")

    async def fishing(self,interaction: discord.Interaction):
        if general.find_one({'id' : interaction.user.id}) is not None:
            if general.find_one({'id' : interaction.user.id})['stamina'] != 0: #Stamina Check
                """
                Fishing Logic: (Probably doesn't make a lot of sense)
                Fishing XP, Fishing Essence, Fish Collection -> Connected terms

                There will be areas in the future (e.g. desert, taiga, plains) and those areas will have sub-areas, which
                might include some different bodies of water for fishing.
                Everyone starts out in the default plains area.

                If you're not at a water body then fishing XP and Essence are greatly decreased (-60%?).
                Similarly, fishing pond XP boosters are not applicable outside the ponds.

                Furthermore, outside of the ponds there's a large decrease in the amount of different fish that can be caught.
                Usually these fish are smaller and worse rarity fish. Every area has different outside-pond fish that can be caught.
                Additionally, trash chance is increased and treasure chance is 0%.

                Different fish drops are dictated by the size of the water body, not necessarily by every different sub-area fishing spot.
                Unlike other skills, fish aren't locked by tools, rather location.

                Tools are used to unlock better unlocks, but mainly for skill xp boosts and other perks. (Unlocking isn't the main perk)
                (Codes will later be changed into actual encrypted two letter codes)
                Tool Codes:
                h - hand -> Meaning no tool
                s - stone
                c - copper

                Area Codes:
                p - plains

                AREA Plains: (3)
                SUB AREA TYPE Water Bodies - Silver Bay (Large), Dragon Tear Lake (Small), Sunken Lagoon (Small)
                OPF (Outside-Pond Fish) -> Perch, Cod, Trout
                LPF (Large Pond Fish) -> OPF + Catfish, Carp
                SPF (Small Pond Fish) -> OPF + Bluegill
            
                Hand (Considering pond) - 50% Trash, 1% Treasure, 49% Fish
                Copper (...) - 45%, 2%, 53%
                """

                #Choosing the fishing item
                weights = []
                choices = []
                fishCompletion = False

                tier = general.find_one({'id' : interaction.user.id})['rodTier'] #Current fRod Tier
                currentSubSetting = areas.find_one({'id' : interaction.user.id})['subareaType'] #Current Subarea Type
                for item in list(fishingData):
                    if currentSubSetting in fishingData[item][0]['subareas'] and tier in fishingData[item][0]['tiers']:

                        #Calculate drop
                        choices.append(item)
                        weights.append(fishingData[item][0]['weight'])

                if len(choices) != 0:
                    treasureThreshold = general.find_one({'id' : interaction.user.id})['treasureChance']
                    trashThreshold = general.find_one({'id' : interaction.user.id})['trashChance']

                    #1, 50, 49 - Default values
                    #Give the right fishing drop based on fishing chance stats
                    percentage = random.randint(1, 100)

                    #necessary to differentiate between different fishing item types
                    fishType = None

                    if 0 < percentage <= treasureThreshold:
                        #Treasure
                        treasureChoice = random.choice(["coins", "crate"])
                        if treasureChoice == "coins":
                            """
                            Coins will be directly deposited to the players wallet
                            """
                            fish = treasureChoice
                            fishType = "coins"
                            amount = random.randint(10, 500)
                            fishCompletion = True

                        else:
                            """
                            The Crate System will allow players to get crates through certain actions

                            The Crates include:
                            Common, Uncommon, Rare, Legendary
                            """
                            crates = ["common crate", "uncommon crate", "rare crate", "legendary crate"]
                            fish = random.choice(crates)
                            cratePosition = crates.index(fish)
                            fishType = "crate"
                            amount = 1
                            fishCompletion = True
                        
                    elif treasureThreshold < percentage <= trashThreshold:
                        #Trash
                        #! maybe change the trashitems to pull it out of a fishingdata file, not hard-coded in
                        trashItems = ["rubber duck", "boot", "seaweed"]
                        fish = random.choice(trashItems)
                        fishType = "fish" #this is because trash items are treated as the same inventory objects as fish
                        amount = random.randint(1, 2)
                        fishCompletion = True

                    else:
                        #Fish
                        fish = random.choices(choices, weights=weights)[0]
                        fishType = "fish"
                        amount = random.randint(1, 2)
                        fishCompletion = True

                    #Update inventory and send response
                    message = []
                    message.append(f":fishing_pole_and_fish: You **Fished**! You got **{amount}** x **{string.capwords(fish)}**!")

                    if fishCompletion:
                        #we need to differentiate between inventory items and non-inventory items

                        #define some necessary variables
                        existingXP = skills.find_one({'id' : interaction.user.id})['fishingXP']
                        existingLevel = skills.find_one({'id' : interaction.user.id})['fishingLevel']
                        existingBonus = skills.find_one({'id' : interaction.user.id})['fishingBonus']
                        existingEssence = general.find_one({'id' : interaction.user.id})['fishingEssence']
                        bonusAmount = 4 #Increase this skills bonus by this amount each level up

                        if fishType == "fish":
                            xp = fishingData[fish][0]['xp'] * amount
                            currentInventory = inventory.find_one({'id' : interaction.user.id, fish : {'$exists' : True}})
                            if currentInventory is None:
                                inventory.update_one({'id' : interaction.user.id}, {"$set":{fish : amount}})
                            else:
                                inventory.update_one({'id' : interaction.user.id}, {"$set":{fish : currentInventory[fish] + amount}})
                            
                            #Give Collections
                            currentFish = collections.find_one({'id' : interaction.user.id})['fish']
                            currentFishLevel = collections.find_one({'id' : interaction.user.id})['fishLevel']

                            if currentFish + amount >= (currentFishLevel*50 + 50):
                                collections.update_one({'id' : interaction.user.id}, {"$set":{'fish' : currentFish + amount}})
                                collections.update_one({'id' : interaction.user.id}, {"$set":{'fishLevel' : currentFishLevel + 1}})
                                message.append('\n' f'**[COLLECTION]** **Fish** Collection Level **{currentFishLevel}** ⇒ **{currentFishLevel + 1}**')
                            
                                #Give collection rewards
                                for i in collectionData[f"{collections.find_one({'id' : interaction.user.id})['fishLevel']}"]:
                                    recipes.update_one({'id' : interaction.user.id}, {"$set":{i : True}}) #Update the users recipes
                            else:
                                collections.update_one({'id' : interaction.user.id}, {"$set":{'fish' : currentFish + amount}})
                        else:
                            #has to be something other than fish

                            xp = 4 #hardcoded treasure xp amount
                            if fishType == "crate":
                                message.append("\n :package: Treasure Catch! :package:")
                                #update the users crate list argument crates = []
                                currentCrates = general.find_one({'id' : interaction.user.id})['crates']
                                currentCrates[cratePosition] += 1
                                general.update_one({'id' : interaction.user.id}, {"$set":{'crates' : currentCrates}})

                            elif fishType == "coins":
                                currentCoins = general.find_one({'id' : interaction.user.id})['wallet']
                                general.update_one({'id' : interaction.user.id}, {"$set":{'wallet' : currentCoins + amount}})
                                message.append("\n :moneybag: Treasure Catch! :moneybag:")

                        #these will be given regardless of the type of item
                        #Give essence
                        essenceFormula = round((xp * 0.35), 2)
                        general.update_one({'id' : interaction.user.id}, {"$set":{'fishingEssence' : existingEssence + essenceFormula}})
                        message.append(f"\n :sparkles: You gained **{essenceFormula} Fishing Essence**!")

                        #Give skill XP
                        if existingXP + xp >= (50*existingLevel+10):
                            leftoverXP = (existingXP + xp) - (50*existingLevel+10)
                            if leftoverXP == 0:
                                skills.update_one({'id' : interaction.user.id}, {"$set":{'fishingXP' : 0, 'fishingLevel' : existingLevel + 1}})
                            else:
                                skills.update_one({'id' : interaction.user.id}, {"$set":{'fishingXP' : leftoverXP, 'fishingLevel' : existingLevel + 1}})

                            skills.update_one({'id' : interaction.user.id}, {"$set":{'fishingBonus' : existingBonus + bonusAmount}})
                            message.append('\n' f':star: You gained **{xp} Fishing** XP!' '\n' f'**[LEVEL UP]** Your **Fishing** leveled up! You are now **Fishing** level **{existingLevel + 1}**!' '\n' f'**[LEVEL BONUS]** **WIP** Bonus: **{existingBonus}** ⇒ **{existingBonus + bonusAmount}**')
                        else:
                            skills.update_one({'id' : interaction.user.id}, {"$set":{'fishingXP' : existingXP + xp}})
                            message.append('\n' f':star: You gained **{xp} Fishing** XP!')

                    await interaction.response.send_message(''.join(message))
                else:
                    await interaction.response.send_message(ephemeral=True, content="You don't have what it takes to fish!")
            else:
                await interaction.response.send_message(ephemeral=True, content="You don't have enough stamina!")
        else:
            await interaction.response.send_message(ephemeral=True, content="Please setup your account with `/register` before using this command.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        fishing(bot),
        guilds = [discord.Object(id = 1047945458665914388)])