import datetime
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from server.skillMethods import get_equipped_tool, calculate_final_qty, apply_gather_results
from server.userMethods import regenerate_stamina, calculate_power_rating, has_skill_resources

# Load full items catalog once at import time
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

class FarmingCog(commands.Cog):
    """Handles `/farm`—gather crops, gain XP & Essence, and advance your collections."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def get_regen_user(self, user_id: int) -> Dict | None:
        db = self.bot.db
        user = await db.general.find_one({"id": user_id})
        if not user:
            return None
        user = regenerate_stamina(user)
        user["powerRating"] = calculate_power_rating(user)
        await db.general.update_one(
            {"id": user_id},
            {"$set": {
                "stamina": user["stamina"],
                "lastStaminaUpdate": user["lastStaminaUpdate"],
                "powerRating": user["powerRating"]
            }}
        )
        return user

    @app_commands.command(
        name="farm",
        description="🌾 Farm the fields for crops, XP, and Essence!"
    )
    async def farm(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # --- 1) Registration & stamina & tool ---
        profile = await self.get_regen_user(user_id)
        if not profile:
            return await interaction.response.send_message("❌ You need to `/register` before farming!", ephemeral=True)

        if profile.get("inDungeon", False):
            return await interaction.response.send_message(
                "❌ You can't do this while in a dungeon! Complete or flee from your dungeon first.",
                ephemeral=True
            )
        
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message("😴 You’re out of stamina! Rest or use a potion before farming again.", ephemeral=True)

        tool_inst, template = await get_equipped_tool(db, user_id, "farmingTool")
        if not tool_inst:
            return await interaction.response.send_message("❌ You must equip a farming tool first.", ephemeral=True)

        # --- 2) Current location & available resources ---
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

        if not has_skill_resources(subarea, _items_data, "farming"):
            return await interaction.response.send_message("🌾 There’s nothing to farm in this subarea.", ephemeral=True)

        candidates = [(item_name, _items_data[item_name]) for item_name in subarea.get("resources", []) if item_name in _items_data and _items_data[item_name].get("type") == "farming"]
        if not candidates:
            return await interaction.response.send_message("⚠️ No farming items available in this subarea!", ephemeral=True)

        keys, weights = zip(*[(k, info.get("weight", 10)) for k, info in candidates])
        picked_key = random.choices(keys, weights=weights, k=1)[0]
        item_info = _items_data[picked_key]

        # --- 3) Determine quantity & XP with tool & skill bonuses ---
        base_qty = random.randint(1, 3)
        skill_doc = await db.skills.find_one({"id": user_id})
        farming_bonus = int(skill_doc.get("farmingBonus", 0)) if skill_doc else 0

        final_qty, bonus_gained, float_qty = calculate_final_qty(base_qty, tool_inst, template, farming_bonus)

        xp_per_unit = int(item_info.get("xp", 1))
        essence_field = "farmingEssence"

        # --- 4) Apply DB updates (inventory, stamina, xp, collections) ---
        summary = await apply_gather_results(
            db=db,
            user_id=user_id,
            picked_key=picked_key,
            final_qty=final_qty,
            xp_per_unit=xp_per_unit,
            skill_prefix="farming",
            skill_bonus_inc=5,
            essence_field=essence_field,
            collection_key="crop"
        )

        # --- 5) Build embed ---
        embed = discord.Embed(title="🌾 Farming Results", color=discord.Color.green(), timestamp=datetime.datetime.now())
        embed.add_field(name="Crops Harvested", value=f"You gathered **{final_qty}** × **{item_info['name'].title()}**", inline=False)
        embed.add_field(name="Farming XP", value=f"⭐ {summary['xp_gain']:,} XP", inline=True)
        embed.add_field(name="Farming Essence", value=f"✨ {round(summary['xp_gain'] * 0.35, 2):,}", inline=True)
        embed.add_field(name="Stamina Remaining", value=f"💪 {profile['stamina'] - 1}", inline=False)
        if bonus_gained:
            embed.add_field(name="🎉 Bonus!", value="Your tool's extra-roll granted **+1** additional item!", inline=False)
        if summary["skill_leveled"]:
            embed.add_field(name="🏅 Level Up!", value=f"You’re now **Farming Level {summary['old_skill_level'] + 1}**\n🔋 +5 Farming Bonus!", inline=False)
        if summary["collection_leveled"]:
            embed.add_field(name="📚 Collection Milestone!", value=f"Your **Crop Collection** is now **Level {summary['old_collection_level'] + 1}**", inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(FarmingCog(bot), guilds=[discord.Object(id=GUILD_ID)])