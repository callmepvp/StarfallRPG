import datetime
import random
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from server.userMethods import regenerate_stamina, calculate_power_rating, has_skill_resources, unlock_collection_recipes

# Load items manifest once
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

# Load item templates (to fallback to template multipliers if instance lacks them)
_ITEM_TEMPLATES_PATH = Path("data/itemTemplates.json")
_item_templates: Dict[str, Any] = {}
if _ITEM_TEMPLATES_PATH.exists():
    import json as _json
    _item_templates = _json.loads(_ITEM_TEMPLATES_PATH.read_text(encoding="utf-8"))

class ForagingCog(commands.Cog):
    """Handles `/forage`—gather wood & herbs, earn XP, Essence, and grow your wood collection."""

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
        name="forage",
        description="🌲 Forage the wilds for wood and herbs!"
    )
    async def forage(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # 1) Check registration & stamina & tool
        profile = await self.get_regen_user(user_id)
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

        equipment_doc = await db.equipment.find_one({"id": user_id})
        if not equipment_doc:
            return await interaction.response.send_message(
                "❌ You must have an equipment profile. Please register or contact the dev.",
                ephemeral=True
            )

        tool_iid = equipment_doc.get("foragingTool")
        if not tool_iid:
            return await interaction.response.send_message(
                "❌ You must equip a foraging tool first.",
                ephemeral=True
            )

        # make sure the instance actually exists in the player's instances array and keep the instance
        instances = equipment_doc.get("instances", [])
        tool_inst = next((inst for inst in instances if inst.get("instance_id") == tool_iid), None)
        if not tool_inst:
            return await interaction.response.send_message(
                "❌ Your equipped foraging tool couldn't be found in your instances. "
                "If this persists, contact the dev.",
                ephemeral=True
            )

        # 2) Get current location
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

        if not has_skill_resources(subarea, _items_data, "foraging"):
            return await interaction.response.send_message(
                "🍄 There’s nothing to forage in this subarea.",
                ephemeral=True
            )

        candidates = [
            (item_name, _items_data[item_name])
            for item_name in subarea.get("resources", [])
            if item_name in _items_data and _items_data[item_name].get("type") == "foraging"
        ]

        if not candidates:
            return await interaction.response.send_message(
                "⚠️ No foraging items available in this subarea!",
                ephemeral=True
            )

        keys, weights = zip(*[(k, info.get("weight", 10)) for k, info in candidates])
        picked = random.choices(keys, weights=weights, k=1)[0]
        info = _items_data[picked]

        # base amount (1-3 as before)
        base_qty = random.randint(1, 3)

        # --- NEW: compute final integer quantity using tool + skill bonuses ---
        # Fetch player's foraging skill doc to read foragingBonus
        sk = await db.skills.find_one({"id": user_id})
        foraging_bonus = int(sk.get("foragingBonus", 0)) if sk else 0

        # tool multipliers: prefer instance-stored values, fallback to template values, else defaults
        tool_yield = (tool_inst.get("yield_multiplier")
                      or _item_templates.get(tool_inst.get("template"), {}).get("yield_multiplier")
                      or 1.0)
        tool_extra_chance = (tool_inst.get("extra_roll_chance")
                             or _item_templates.get(tool_inst.get("template"), {}).get("extra_roll_chance")
                             or 0.0)
        # skill bonus converts to percentage (2% per bonus point)
        skill_multiplier = 1.0 + (foraging_bonus * 0.02)

        float_yield = base_qty * tool_yield * skill_multiplier
        integer_yield = math.floor(float_yield)
        fractional = float_yield - integer_yield
        if random.random() < fractional:
            integer_yield += 1

        # extra-roll: small chance to get +1 (skill contributes a little)
        extra_skill_contribution = foraging_bonus * 0.005  # 0.5% per bonus point
        total_extra_chance = tool_extra_chance + extra_skill_contribution
        bonus_gained = False
        if random.random() < total_extra_chance:
            integer_yield += 1
            bonus_gained = True

        final_qty = max(0, int(integer_yield))  # ensure integer >= 0

        # 3) Apply all updates (use final_qty everywhere)
        # Inventory
        await db.inventory.update_one(
            {"id": user_id}, {"$inc": {picked: final_qty}}
        )
        # Stamina
        await db.general.update_one(
            {"id": user_id}, {"$inc": {"stamina": -1}}
        )

        # Skill XP & Level (use final_qty)
        old_xp = sk["foragingXP"]
        old_lvl = sk["foragingLevel"]
        xp_gain = info.get("xp", 1) * final_qty
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

            await db.general.update_one(
                {"id": user_id},
                {"$inc": {"strength": bonus_inc}}
            )
        else:
            await db.skills.update_one(
                {"id": user_id}, {"$set": {"foragingXP": new_xp}}
            )

        # Essence (use xp_gain)
        essence_gain = round(xp_gain * 0.35, 2)
        await db.general.update_one(
            {"id": user_id}, {"$inc": {"foragingEssence": essence_gain}}
        )

        # Collection (wood) — use final_qty
        coll = await db.collections.find_one({"id": user_id})
        old_coll = coll["wood"]
        old_coll_lvl = coll["woodLevel"]
        new_coll = old_coll + final_qty
        coll_thr = 50 * old_coll_lvl + 50

        coll_leveled = False
        if new_coll >= coll_thr:
            coll_leveled = True
            new_level = old_coll_lvl + 1
            await db.collections.update_one(
                {"id": user_id},
                {"$set": {"wood": new_coll, "woodLevel": old_coll_lvl + 1}}
            )
            # Unlock new recipes for this collection
            await unlock_collection_recipes(db, user_id, "wood", new_level)
        else:
            await db.collections.update_one(
                {"id": user_id}, {"$set": {"wood": new_coll}}
            )

        # 4) Build the embed response (do NOT show calculation details)
        embed = discord.Embed(
            title="🌲 Foraging Results",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(
            name="Gathered Resources",
            value=f"You foraged **{final_qty}** × **{info['name'].title()}**",
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

        # Show bonus-roll success if it occurred
        if bonus_gained:
            embed.add_field(
                name="🎉 Bonus!",
                value="Your tool's extra-roll granted **+1** additional item!",
                inline=False
            )

        if leveled:
            embed.add_field(
                name="🏅 Level Up!",
                value=(
                    f"You’re now **Foraging Level {old_lvl + 1}**\n"
                    f"🔋 +{bonus_inc} foraging bonus!\n"
                    f"💪 +{bonus_inc} strength!"
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