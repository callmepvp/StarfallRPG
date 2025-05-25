import datetime
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

# Load items manifest once
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    import json
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

def _get_foraging_items() -> List[Tuple[str, Dict[str, Any]]]:
    """
    Returns a list of (item_key, item_info) pairs for all items
    where type == "foraging".
    """
    return [
        (key, info)
        for key, info in _items_data.items()
        if info.get("type") == "foraging"
    ]

class ForagingCog(commands.Cog):
    """Handles `/forage`—gather wood & herbs, earn XP, Essence, and grow your wood collection."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="forage",
        description="🌲 Forage the wilds for wood and herbs!"
    )
    async def forage(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # 1) Check registration & stamina
        profile = await db.general.find_one({"id": user_id})
        if not profile:
            return await interaction.response.send_message(
                "❌ You need to `/register` before you can forage!",
                ephemeral=True
            )
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message(
                "😴 You’re out of stamina! Rest before foraging again.",
                ephemeral=True
            )

        # 2) Pick a random foraging item
        candidates = _get_foraging_items()
        if not candidates:
            return await interaction.response.send_message(
                "⚠️ No foraging items are defined—check your items.json!",
                ephemeral=True
            )

        keys, weights = zip(*[(k, info.get("weight", 10)) for k, info in candidates])
        picked = random.choices(keys, weights=weights, k=1)[0]
        info = _items_data[picked]

        qty = random.randint(1, 3)
        xp_gain = info.get("xp", 1) * qty
        essence_gain = round(xp_gain * 0.35, 2)

        # 3) Apply all updates
        # Inventory
        await db.inventory.update_one(
            {"id": user_id}, {"$inc": {picked: qty}}
        )
        # Stamina
        await db.general.update_one(
            {"id": user_id}, {"$inc": {"stamina": -1}}
        )
        # Skill XP & Level
        sk = await db.skills.find_one({"id": user_id})
        old_xp = sk["foragingXP"]
        old_lvl = sk["foragingLevel"]
        new_xp = old_xp + xp_gain
        threshold = 50 * old_lvl + 10

        leveled = False
        bonus_inc = 2
        if new_xp >= threshold:
            leveled = True
            leftover = new_xp - threshold
            await db.skills.update_one(
                {"id": user_id},
                {"$set": {"foragingLevel": old_lvl + 1, "foragingXP": leftover},
                 "$inc": {"foragingBonus": bonus_inc}}
            )
        else:
            await db.skills.update_one(
                {"id": user_id}, {"$set": {"foragingXP": new_xp}}
            )
        # Essence
        await db.general.update_one(
            {"id": user_id}, {"$inc": {"foragingEssence": essence_gain}}
        )
        # Collection (wood)
        coll = await db.collections.find_one({"id": user_id})
        old_coll = coll["wood"]
        old_coll_lvl = coll["woodLevel"]
        new_coll = old_coll + qty
        coll_thr = 50 * old_coll_lvl + 50

        coll_leveled = False
        if new_coll >= coll_thr:
            coll_leveled = True
            await db.collections.update_one(
                {"id": user_id},
                {"$set": {"wood": new_coll, "woodLevel": old_coll_lvl + 1}}
            )
        else:
            await db.collections.update_one(
                {"id": user_id}, {"$set": {"wood": new_coll}}
            )

        # 4) Build the embed response
        embed = discord.Embed(
            title="🌲 Foraging Results",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(
            name="Gathered Resources",
            value=f"You foraged **{qty}** × **{info['name'].title()}**",
            inline=False
        )
        embed.add_field(
            name="Foraging XP",
            value=f"⭐ {xp_gain:,} XP",
            inline=True
        )
        embed.add_field(
            name="Foraging Essence",
            value=f"✨ {essence_gain:,}",
            inline=True
        )
        embed.add_field(
            name="Stamina Remaining",
            value=f"💪 {profile['stamina'] - 1}",
            inline=False
        )

        if leveled:
            embed.add_field(
                name="🏅 Level Up!",
                value=(
                    f"You’re now **Foraging Level {old_lvl + 1}**\n"
                    f"(+{bonus_inc} foraging bonus!)"
                ),
                inline=False
            )
        if coll_leveled:
            embed.add_field(
                name="📚 Collection Milestone!",
                value=f"Your **Wood Collection** is now **Level {old_coll_lvl + 1}**",
                inline=False
            )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID  # or bot.config["GUILD_ID"]
    await bot.add_cog(ForagingCog(bot), guilds=[discord.Object(id=GUILD_ID)])