import datetime
import random
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from server.userMethods import regenerate_stamina, calculate_power_rating, has_skill_resources, unlock_collection_recipes

# Load items manifest & areas
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    import json
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

_AREAS_PATH = Path("data/areas.json")
_areas_data: Dict[str, Any] = {}
if _AREAS_PATH.exists():
    _areas_data = json.loads(_AREAS_PATH.read_text(encoding="utf-8"))

# Load item templates (for fallback multipliers)
_ITEM_TEMPLATES_PATH = Path("data/itemTemplates.json")
_item_templates: Dict[str, Any] = {}
if _ITEM_TEMPLATES_PATH.exists():
    import json as _json
    _item_templates = _json.loads(_ITEM_TEMPLATES_PATH.read_text(encoding="utf-8"))

class ScavengingCog(commands.Cog):
    """Handles `/scavenge`: gather herbs & ingredients, gain XP, Essence, and grow your herb collection."""

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
        name="scavenge",
        description="🌺 Scavenge the wilds for herbs and ingredients!"
    )
    async def scavenge(self, interaction: discord.Interaction) -> None:
        db = self.bot.db
        user_id = interaction.user.id

        # --- Registration & stamina & tool ---
        profile = await self.get_regen_user(user_id)
        if not profile:
            return await interaction.response.send_message("❌ You need to `/register` before scavenging!", ephemeral=True)
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message("😴 You’re out of stamina! Rest first.", ephemeral=True)

        equipment_doc = await db.equipment.find_one({"id": user_id})
        tool_iid = equipment_doc.get("scavengingTool")
        if not tool_iid:
            return await interaction.response.send_message("❌ You must equip a scavenging tool first.", ephemeral=True)

        instances = equipment_doc.get("instances", [])
        tool_inst = next((inst for inst in instances if inst.get("instance_id") == tool_iid), None)
        if not tool_inst:
            return await interaction.response.send_message(
                "❌ Your equipped scavenging tool couldn't be found in your instances. If this persists, contact the dev.",
                ephemeral=True
            )

        # --- Location & resources ---
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

        if not has_skill_resources(subarea, _items_data, "scavenging"):
            return await interaction.response.send_message("🔍 There’s nothing to scavenge in this subarea.", ephemeral=True)

        candidates = [(item_name, _items_data[item_name]) for item_name in subarea.get("resources", []) if item_name in _items_data and _items_data[item_name].get("type") == "scavenging"]
        if not candidates:
            return await interaction.response.send_message("⚠️ No scavenging items available in this subarea!", ephemeral=True)

        keys, weights = zip(*[(k, info.get("weight", 10)) for k, info in candidates])
        picked = random.choices(keys, weights=weights, k=1)[0]
        info = _items_data[picked]

        # --- Quantity calculation with tool & skill bonuses ---
        base_qty = random.randint(1, 3)
        sk = await db.skills.find_one({"id": user_id})
        scav_bonus = int(sk.get("scavengingBonus", 0)) if sk else 0

        tool_yield = tool_inst.get("yield_multiplier") or _item_templates.get(tool_inst.get("template"), {}).get("yield_multiplier") or 1.0
        tool_extra = tool_inst.get("extra_roll_chance") or _item_templates.get(tool_inst.get("template"), {}).get("extra_roll_chance") or 0.0

        skill_mult = 1.0 + (scav_bonus * 0.02)
        float_qty = base_qty * tool_yield * skill_mult
        integer_qty = math.floor(float_qty)
        if random.random() < (float_qty - integer_qty):
            integer_qty += 1

        extra_chance = tool_extra + scav_bonus * 0.005
        bonus_gained = False
        if random.random() < extra_chance:
            integer_qty += 1
            bonus_gained = True

        final_qty = max(0, int(integer_qty))
        xp_gain = info.get("xp", 1) * final_qty
        essence_gain = round(xp_gain * 0.35, 2)

        # --- Updates ---
        await db.inventory.update_one({"id": user_id}, {"$inc": {picked: final_qty}})
        await db.general.update_one({"id": user_id}, {"$inc": {"stamina": -1}})
        old_xp, old_lvl = sk["scavengingXP"], sk["scavengingLevel"]
        new_xp = old_xp + xp_gain
        lvl_thr = 50 * old_lvl + 10

        leveled = False
        bonus = 2
        if new_xp >= lvl_thr:
            leveled = True
            leftover = new_xp - lvl_thr
            await db.skills.update_one({"id": user_id}, {"$set": {"scavengingLevel": old_lvl + 1, "scavengingXP": leftover}, "$inc": {"scavengingBonus": bonus}})
            await db.general.update_one({"id": user_id}, {"$inc": {"evasion": bonus}})
        else:
            await db.skills.update_one({"id": user_id}, {"$set": {"scavengingXP": new_xp}})
        await db.general.update_one({"id": user_id}, {"$inc": {"scavengingEssence": essence_gain}})

        coll = await db.collections.find_one({"id": user_id})
        old_coll, old_coll_lvl = coll["herb"], coll["herbLevel"]
        new_coll = old_coll + final_qty
        coll_leveled = False
        if new_coll >= 50 * old_coll_lvl + 50:
            coll_leveled = True
            new_level = old_coll_lvl + 1
            await db.collections.update_one({"id": user_id}, {"$set": {"herb": new_coll, "herbLevel": old_coll_lvl + 1}})
            await unlock_collection_recipes(db, user_id, "herb", new_level)
        else:
            await db.collections.update_one({"id": user_id}, {"$set": {"herb": new_coll}})

        # --- Embed ---
        embed = discord.Embed(title="🪴 Scavenging Results", color=discord.Color.gold(), timestamp=datetime.datetime.now())
        embed.add_field(name="Herbs Gathered", value=f"You collected **{final_qty}** × **{info['name'].title()}**", inline=False)
        embed.add_field(name="Scavenging XP", value=f"⭐ {xp_gain:,} XP", inline=True)
        embed.add_field(name="Scavenging Essence", value=f"✨ {essence_gain:,}", inline=True)
        embed.add_field(name="Stamina Remaining", value=f"💪 {profile['stamina'] - 1}", inline=False)
        if bonus_gained:
            embed.add_field(name="🎉 Bonus!", value="Your tool's extra-roll granted **+1** additional item!", inline=False)
        if leveled:
            embed.add_field(name="🏅 Level Up!", value=f"Your **Scavenging** is now **Level {old_lvl + 1}** \n🔋 +{bonus} scavenging bonus!\n🎯 +{bonus} evasion!", inline=False)
        if coll_leveled:
            embed.add_field(name="📚 Collection Level!", value=f"Your **Herb Collection** is now **Level {old_coll_lvl + 1}**", inline=False)
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(ScavengingCog(bot), guilds=[discord.Object(id=GUILD_ID)])