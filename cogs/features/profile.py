import datetime
from typing import Any, Dict, List

import discord
from discord import app_commands
from discord.ext import commands

class ProfileCog(commands.Cog):
    """Displays detailed player profile info via `/profile`."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="profile",
        description="👤 Show your Starfall RPG profile."
    )
    async def profile(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # Fetch data
        gen = await db.general.find_one({"id": user_id})
        skl = await db.skills.find_one({"id": user_id})
        if not gen or not skl:
            return await interaction.response.send_message(
                "❌ You need to `/register` first.", ephemeral=True
            )

        # Account info
        display_name = gen.get("name", interaction.user.display_name)
        bio = gen.get("bio", "No biography set.")
        created_ts = gen.get("creation", None)
        if created_ts:
            created_dt = datetime.datetime.fromtimestamp(created_ts)
            created_str = created_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            created_str = "Unknown"

        wallet = gen.get("wallet", 0)
        stamina = gen.get("stamina", 0)
        max_inv = gen.get("maxInventory", 200)

        # Essence totals
        essence_keys = ["foragingEssence", "miningEssence", "farmingEssence",
                        "scavengingEssence", "fishingEssence"]
        essences: List[str] = []
        for key in essence_keys:
            val = round(gen.get(key, 0), 2)
            essences.append(f"{key.replace('Essence','').title()}: **{val:,}**")

        # Skill levels
        skill_keys = ["foragingLevel","miningLevel","farmingLevel",
                      "scavengingLevel","fishingLevel","craftingLevel", "combatLevel"]
        levels: List[int] = [ skl.get(k,0) for k in skill_keys ]
        avg_level = sum(levels)/len(levels) if levels else 0.0

        skills_display = "\n".join(
            f"{k.replace('Level','').title()}: **{skl.get(k,0)}**"
            for k in skill_keys
        ) + f"\n\n**Average Level:** **{avg_level:.2f}**"

        # Combat Stats
        hp = gen.get("hp", 100)
        max_hp = gen.get("maxHP", 100)
        strength = gen.get("strength", 0)
        defense = gen.get("defense", 0)
        evasion = gen.get("evasion", 0)
        accuracy = gen.get("accuracy", 0)

        # Build embed
        embed = discord.Embed(
            title=f"👤 Profile: {display_name}",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar)
        embed.add_field(name="📖 Biography", value=bio, inline=False)
        embed.add_field(name="🗓️ Member Since", value=created_str, inline=True)
        embed.add_field(name="💰 Wallet", value=f"{wallet:,} coins", inline=True)
        embed.add_field(name="💪 Current Stamina", value=f"{stamina}", inline=True)
        embed.add_field(name="🎒 Inventory Slots", value=f"{max_inv}", inline=True)

        embed.add_field(name="❤️ HP", value=f"{hp}/{max_hp}", inline=True)
        embed.add_field(name="💥 Strength", value=f"{strength}", inline=True)
        embed.add_field(name="🛡️ Defense", value=f"{defense}", inline=True)
        embed.add_field(name="🌀 Evasion", value=f"{evasion}", inline=True)
        embed.add_field(name="🎯 Accuracy", value=f"{accuracy}", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer

        embed.add_field(name="✨ Essences", value="\n".join(essences), inline=False)
        embed.add_field(name="⚔️ Skill Levels", value=skills_display, inline=False)

    
        embed.set_footer(text="Starfall RPG • profile")

        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(ProfileCog(bot), guilds=[discord.Object(id=GUILD_ID)])