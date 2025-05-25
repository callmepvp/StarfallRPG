import datetime
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View

from database import Database
from settings import GUILD_ID

class CharacterCustomizationModal(Modal):
    """Modal for choosing your character’s display name and brief bio."""
    name = TextInput(
        label="Your Character’s Name",
        placeholder="Enter the name you'll be known by in Starfall",
        max_length=32,
    )
    bio = TextInput(
        label="Short Bio",
        style=discord.TextStyle.paragraph,
        placeholder="Describe yourself in one sentence",
        required=False,
        max_length=100,
    )

    def __init__(self, user_id: int, db: "Database"):
        super().__init__(title="Customize Your Avatar")
        self.user_id = user_id
        self.db = db

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Save the custom name and bio, then confirm registration."""
        # Update the general document with the chosen name & bio
        await self.db.general.update_one(
            {"id": self.user_id},
            {"$set": {"name": self.name.value, "bio": self.bio.value}},
        )

        embed = discord.Embed(
            title="Registration Complete!",
            description=(
                f"Welcome, **{self.name.value}**!\n"
                "You’ve been fully registered and can now explore Starfall."
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class RegisterCog(commands.Cog):
    """Handles the `/register` command and new-user onboarding."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="register",
        description="Setup your Starfall profile and get started!"
    )
    async def register(self, interaction: discord.Interaction) -> None:
        """
        1) Checks if the user already has a profile.
        2) Shows the Terms & Conditions embed with a confirmation button.
        3) On confirmation, seeds all MongoDB collections for that user.
        4) Launches a Modal to collect name & bio.
        """
        user_id = interaction.user.id
        db = self.bot.db

        # Step 1: refuse if already registered
        existing = await db.general.find_one({"id": user_id})
        if existing:
            return await interaction.response.send_message(
                "You already have an account! If this is an error, contact the dev.",
                ephemeral=True,
            )

        # Step 2: Terms & Conditions
        terms = (
            "**Before proceeding, please read carefully!**\n\n"
            "1. Do not exploit bugs or use multiple accounts.\n"
            "2. Your Discord username, ID, and avatar will be stored for gameplay.\n"
        )
        embed = discord.Embed(
            title=f"Welcome to Starfall, {interaction.user.display_name}!",
            description=terms,
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(),
        )
        embed.set_footer(text="Click “I understand” to continue.")

        button = Button(label="I understand", style=discord.ButtonStyle.gray)
        async def on_accept(button_inter: discord.Interaction) -> None:
            button.disabled = True

            # Step 3: seed all collections
            now = time.time()
            await db.inventory.insert_one({"id": user_id})
            await db.general.insert_one({
                "id": user_id,
                "name": interaction.user.display_name,
                "bio": "",
                "maxInventory": 200,
                "maxStamina": 200,
                "lastStaminaUpdate": now,
                "maxHP": 100,
                "wallet": 0,
                "creation": now,
                "stamina": 200,
                "crates": [0, 0, 0, 0],
                "miningEssence": 0,
                "foragingEssence": 0,
                "farmingEssence": 0,
                "scavengingEssence": 0,
                "fishingEssence": 0,
                "treasureChance": 1,
                "trashChance": 50,
                "hp": 100,
                "strength": 1,
                "defense": 1,
                "evasion": 1,
                "accuracy": 1,
                "powerRating": 0 
            })
            await db.areas.insert_one({
                "id": user_id,
                "currentArea": "plains",
                "currentSubarea": "pond",
                "subareaType": "small"
            })
            await db.skills.insert_one({
                "id": user_id,
                **{f"{sk}{prop}": 0 for sk in ("foraging","mining","farming","crafting","scavenging","fishing", "combat") for prop in ("Level","XP","Bonus")},
                **{f"{sk}Tier": "1hand" for sk in ("mining","foraging","farming","scavenging","fishing")},
            })
            await db.collections.insert_one({
                "id": user_id,
                "wood": 0, "woodLevel": 0,
                "ore": 0, "oreLevel": 0,
                "crop": 0, "cropLevel": 0,
                "herb": 0, "herbLevel": 0,
                "fish": 0, "fishLevel": 0,
            })
            await db.recipes.insert_one({"id": user_id, "toolrod": True})

    
            modal = CharacterCustomizationModal(user_id, db)
            await button_inter.response.send_modal(modal)

        button.callback = on_accept
        view = View(timeout=120.0)
        view.add_item(button)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RegisterCog(bot), guilds=[discord.Object(id=GUILD_ID)])