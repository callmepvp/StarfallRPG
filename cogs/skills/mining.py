import datetime
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

# Load items manifest
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    import json
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})


def _get_mining_items() -> List[Tuple[str, Dict[str, Any]]]:
    return [
        (key, info)
        for key, info in _items_data.items()
        if info.get("type") == "mining"
    ]


class MiningCog(commands.Cog):
    """Handles `/mine`: mine ore, gain XP, Essence, collections & level-ups."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="mine",
        description="⛏️ Mine rocks for ores and minerals!"
    )
    async def mine(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # 1) Registration & stamina
        profile = await db.general.find_one({"id": user_id})
        if not profile:
            return await interaction.response.send_message(
                "❌ You need to `/register` before mining!",
                ephemeral=True
            )
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message(
                "😴 You’re out of stamina! Rest before mining.",
                ephemeral=True
            )

        # 2) Pick a random mining item
        candidates = _get_mining_items()
        if not candidates:
            return await interaction.response.send_message(
                "⚠️ No mining items defined—check items.json!",
                ephemeral=True
            )

        keys, weights = zip(*[(k, info.get("weight", 10)) for k, info in candidates])
        picked = random.choices(keys, weights=weights, k=1)[0]
        info = _items_data[picked]

        qty = random.randint(1, 3)
        xp_gain = info.get("xp", 1) * qty
        essence_gain = round(xp_gain * 0.35, 2)

        # 3) Updates
        await db.inventory.update_one({"id": user_id}, {"$inc": {picked: qty}})
        await db.general.update_one({"id": user_id}, {"$inc": {"stamina": -1}})
        sk = await db.skills.find_one({"id": user_id})
        old_xp, old_lvl = sk["miningXP"], sk["miningLevel"]
        new_xp = old_xp + xp_gain
        lvl_thr = 50 * old_lvl + 10

        leveled = False
        bonus = 2
        if new_xp >= lvl_thr:
            leveled = True
            leftover = new_xp - lvl_thr
            await db.skills.update_one(
                {"id": user_id},
                {"$set": {"miningLevel": old_lvl + 1, "miningXP": leftover},
                 "$inc": {"miningBonus": bonus}}
            )
        else:
            await db.skills.update_one({"id": user_id}, {"$set": {"miningXP": new_xp}})

        await db.general.update_one({"id": user_id}, {"$inc": {"miningEssence": essence_gain}})

        coll = await db.collections.find_one({"id": user_id})
        old_coll, old_coll_lvl = coll["ore"], coll["oreLevel"]
        new_coll = old_coll + qty
        coll_thr = 50 * old_coll_lvl + 50

        coll_leveled = False
        if new_coll >= coll_thr:
            coll_leveled = True
            await db.collections.update_one(
                {"id": user_id},
                {"$set": {"ore": new_coll, "oreLevel": old_coll_lvl + 1}}
            )
        else:
            await db.collections.update_one({"id": user_id}, {"$set": {"ore": new_coll}})

        # 4) Embed
        embed = discord.Embed(
            title="⛏️ Mining Results",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(
            name="Ores Mined",
            value=f"You extracted **{qty}** × **{info['name'].title()}**",
            inline=False
        )
        embed.add_field(name="Mining XP", value=f"⭐ {xp_gain:,} XP", inline=True)
        embed.add_field(name="Mining Essence", value=f"✨ {essence_gain:,}", inline=True)
        embed.add_field(
            name="Stamina Remaining",
            value=f"💪 {profile['stamina'] - 1}",
            inline=False
        )
        if leveled:
            embed.add_field(
                name="🏅 Level Up!",
                value=f"You’re now **Mining Level {old_lvl + 1}** \n(+{bonus} mining bonus!)",
                inline=False
            )
        if coll_leveled:
            embed.add_field(
                name="📚 Collection Level!", 
                value=f"Your **Ore Collection** is now **Level {old_coll_lvl + 1}**",
                inline=False
            )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(MiningCog(bot), guilds=[discord.Object(id=GUILD_ID)])