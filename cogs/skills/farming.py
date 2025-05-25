import datetime
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from settings import GUILD_ID

# Load full items catalog once at import time
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    import json
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})


def _get_farming_items() -> List[Tuple[str, Dict[str, Any]]]:
    """
    Returns a list of (item_key, item_info) pairs for all items
    where type == "farming".
    """
    return [
        (key, info)
        for key, info in _items_data.items()
        if info.get("type") == "farming"
    ]


class FarmingCog(commands.Cog):
    """Handles `/farm`—gather crops, gain XP & Essence, and advance your collections."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="farm",
        description="🌾 Farm the fields for crops, XP, and Essence!"
    )
    async def farm(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]

        # --- 1) Ensure user exists and has stamina ---
        user_id = interaction.user.id
        profile = await db.general.find_one({"id": user_id})
        if not profile:
            return await interaction.response.send_message(
                "❌ You need to `/register` before farming!",
                ephemeral=True
            )
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message(
                "😴 You’re out of stamina! Rest or use a potion before farming again.",
                ephemeral=True
            )

        # --- 2) Pick a random farming item weighted by its 'weight' ---
        candidates = _get_farming_items()
        if not candidates:
            return await interaction.response.send_message(
                "⚠️ No farming items are defined—check your configuration!",
                ephemeral=True
            )

        # Build choices & weights
        choices, weights = zip(*[
            (key, info.get("weight", 10)) for key, info in candidates
        ])
        picked_key = random.choices(choices, weights=weights, k=1)[0]
        item_info = _items_data[picked_key]

        # Determine quantity & XP
        quantity = random.randint(1, 3)
        xp_gain = item_info.get("xp", 1) * quantity
        essence_gain = round(xp_gain * 0.35, 2)

        # --- 3) Update DB: inventory, stamina, skill XP, essence, collections ---
        await db.inventory.update_one(
            {"id": user_id}, {"$inc": {picked_key: quantity}}
        )
        await db.general.update_one(
            {"id": user_id}, {"$inc": {"stamina": -1}}
        )
        # Skill XP & Level
        skill_doc = await db.skills.find_one({"id": user_id})
        old_xp = skill_doc["farmingXP"]
        old_lvl = skill_doc["farmingLevel"]
        new_xp = old_xp + xp_gain
        lvl_threshold = 50 * old_lvl + 10

        leveled_up = False
        bonus_increase = 2  # per-level bonus
        if new_xp >= lvl_threshold:
            leveled_up = True
            leftover = new_xp - lvl_threshold
            new_lvl = old_lvl + 1
            await db.skills.update_one(
                {"id": user_id},
                {"$set": {
                    "farmingLevel": new_lvl,
                    "farmingXP": leftover,
                }, "$inc": {"farmingBonus": bonus_increase}}
            )
        else:
            await db.skills.update_one(
                {"id": user_id},
                {"$set": {"farmingXP": new_xp}}
            )

        # Essence
        await db.general.update_one(
            {"id": user_id}, {"$inc": {"farmingEssence": essence_gain}}
        )
        # Collection
        coll_doc = await db.collections.find_one({"id": user_id})
        old_coll = coll_doc["crop"]
        old_coll_lvl = coll_doc["cropLevel"]
        new_coll = old_coll + quantity
        coll_threshold = 50 * old_coll_lvl + 50
        coll_leveled = False
        if new_coll >= coll_threshold:
            coll_leveled = True
            await db.collections.update_one(
                {"id": user_id},
                {"$set": {
                    "crop": new_coll,
                    "cropLevel": old_coll_lvl + 1
                }}
            )
        else:
            await db.collections.update_one(
                {"id": user_id}, {"$set": {"crop": new_coll}}
            )

        # --- 4) Build a embed response ---
        embed = discord.Embed(
            title="🌾 Farming Results",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(
            name="Crops Harvested",
            value=f"You gathered **{quantity}** × **{item_info['name'].title()}**",
            inline=False
        )
        embed.add_field(
            name="Farming XP",
            value=f"⭐ {xp_gain:,} XP",
            inline=True
        )
        embed.add_field(
            name="Farming Essence",
            value=f"✨ {essence_gain:,}",
            inline=True
        )
        embed.add_field(
            name="Stamina Remaining",
            value=f"💪 {profile['stamina'] - 1}",
            inline=False
        )

        if leveled_up:
            embed.add_field(
                name="🏅 Level Up!",
                value=(
                    f"You’re now **Farming Level {old_lvl + 1}**\n"
                    f"(+{bonus_increase} farming bonus!)"
                ),
                inline=False
            )
        if coll_leveled:
            embed.add_field(
                name="📚 Collection Milestone!",
                value=f"Your **Crop Collection** is now **Level {old_coll_lvl + 1}**",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FarmingCog(bot), guilds=[discord.Object(id=GUILD_ID)])