import datetime
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from server.skillMethods import get_equipped_tool, calculate_final_qty, apply_gather_results
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

        # 1) registration & stamina & tool
        profile = await self.get_regen_user(user_id)
        if not profile:
            return await interaction.response.send_message("❌ You need to `/register` before mining!", ephemeral=True)
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message("😴 You’re out of stamina! Rest before mining.", ephemeral=True)

        tool_inst, template = await get_equipped_tool(db, user_id, "miningTool")
        if not tool_inst:
            return await interaction.response.send_message("❌ You must equip a mining tool first.", ephemeral=True)

        # 2) location & resources
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
            return await interaction.response.send_message("⛏️ There’s nothing to mine in this subarea.", ephemeral=True)

        candidates = [
            (item_name, _items_data[item_name])
            for item_name in subarea.get("resources", [])
            if item_name in _items_data and _items_data[item_name].get("type") == "mining"
        ]
        if not candidates:
            return await interaction.response.send_message("⚠️ No mining items available in this subarea!", ephemeral=True)

        keys, weights = zip(*[(k, info.get("weight", 10)) for k, info in candidates])
        picked_key = random.choices(keys, weights=weights, k=1)[0]
        item_info = _items_data[picked_key]

        # --- compute final qty using helper ---
        base_qty = random.randint(1, 3)
        sk = await db.skills.find_one({"id": user_id})
        mining_bonus = int(sk.get("miningBonus", 0)) if sk else 0

        final_qty, bonus_gained, _float_qty = calculate_final_qty(base_qty, tool_inst, template, mining_bonus)

        # apply DB updates via helper
        summary = await apply_gather_results(
            db=db,
            user_id=user_id,
            picked_key=picked_key,
            final_qty=final_qty,
            xp_per_unit=int(item_info.get("xp", 1)),
            skill_prefix="mining",
            skill_bonus_inc=2,
            essence_field="miningEssence",
            collection_key="ore"
        )

        # --- embed ---
        embed = discord.Embed(title="⛏️ Mining Results", color=discord.Color.blue(), timestamp=datetime.datetime.now())
        embed.add_field(name="Ores Mined", value=f"You extracted **{final_qty}** × **{item_info['name'].title()}**", inline=False)
        embed.add_field(name="Mining XP", value=f"⭐ {summary['xp_gain']:,} XP", inline=True)
        embed.add_field(name="Mining Essence", value=f"✨ {round(summary['xp_gain'] * 0.35, 2):,}", inline=True)
        embed.add_field(name="Stamina Remaining", value=f"💪 {profile['stamina'] - 1}", inline=False)
        if bonus_gained:
            embed.add_field(name="🎉 Bonus!", value="Your tool's extra-roll granted **+1** additional item!", inline=False)
        if summary["skill_leveled"]:
            embed.add_field(name="🏅 Level Up!", value=f"You’re now **Mining Level {summary['old_skill_level'] + 1}**\n🔋 +2 mining bonus!\n🛡️ +2 defense!", inline=False)
        if summary["collection_leveled"]:
            embed.add_field(name="📚 Collection Level!", value=f"Your **Ore Collection** is now **Level {summary['old_collection_level'] + 1}**", inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(MiningCog(bot), guilds=[discord.Object(id=GUILD_ID)])