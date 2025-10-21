import datetime
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from server.userMethods import regenerate_stamina, calculate_power_rating, has_skill_resources

# Load items manifest
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    import json
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

# Load areas data
_AREAS_PATH = Path("data/areas.json")
_areas_data: Dict[str, Any] = {}
if _AREAS_PATH.exists():
    _areas_data = json.loads(_AREAS_PATH.read_text(encoding="utf-8"))

class MiningCog(commands.Cog):
    """Handles `/mine`: mine ore, gain XP, Essence, collections & level-ups."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def get_regen_user(self, user_id: int) -> Dict | None:
        db = self.bot.db
        user = await db.general.find_one({"id": user_id})
        if user is None:
            return None

        user = regenerate_stamina(user)
        power = calculate_power_rating(user)
        user["powerRating"] = power
        await db.general.update_one(
            {"id": user_id},
            {"$set": {
                "stamina": user["stamina"],
                "lastStaminaUpdate": user["lastStaminaUpdate"],
                "powerRating": power
            }}
        )
        return user

    @app_commands.command(
        name="mine",
        description="⛏️ Mine rocks for ores and minerals!"
    )
    async def mine(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # 1) Registration & stamina & tool
        profile = await self.get_regen_user(user_id)
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
        
        equipment_doc = await db.equipment.find_one({"id": user_id})
        tool_iid = equipment_doc.get("miningTool")
        if not tool_iid:
            return await interaction.response.send_message(
                "❌ You must equip a mining tool first.",
                ephemeral=True
            )

        # make sure the instance actually exists in the player's instances array
        instances = equipment_doc.get("instances", [])
        if not any(inst.get("instance_id") == tool_iid for inst in instances):
            return await interaction.response.send_message(
                "❌ Your equipped mining tool couldn't be found in your instances. "
                "If this persists, contact the dev.",
                ephemeral=True
            )

        # 2) Get current location and check for mining resources
        area_doc = await db.areas.find_one({"id": user_id})
        if not area_doc:
            return await interaction.response.send_message("❌ Couldn't determine your current location!", ephemeral=True)
        
        player_area = area_doc.get("currentArea")
        player_subarea = area_doc.get("currentSubarea")

        if not player_area or not player_subarea:
            return await interaction.response.send_message("❌ You're not in a valid location!", ephemeral=True)

        area = _areas_data.get(player_area, {})
        subarea = area.get("sub_areas", {}).get(player_subarea, {})

        if not subarea:
            return await interaction.response.send_message("❌ Invalid subarea data!", ephemeral=True)

        if not has_skill_resources(subarea, _items_data, "mining"):
            return await interaction.response.send_message(
                "⛏️ There’s nothing to mine in this subarea.",
                ephemeral=True
            )

        candidates = [
            (item_name, _items_data[item_name])
            for item_name in subarea.get("resources", [])
            if item_name in _items_data and _items_data[item_name].get("type") == "mining"
        ]

        if not candidates:
            return await interaction.response.send_message(
                "⚠️ No mining items available in this subarea!",
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

            await db.general.update_one(
                {"id": user_id},
                {"$inc": {"defense": bonus}}
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
                value=(f"You’re now **Mining Level {old_lvl + 1}**\n"
                    f"🔋 +{bonus} mining bonus!\n"
                    f"🛡️ +{bonus} defense!"),
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