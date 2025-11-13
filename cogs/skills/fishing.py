import datetime
import random
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from server.userMethods import regenerate_stamina, calculate_power_rating, unlock_collection_recipes

# Load the global items manifest
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

# Load areas data
_AREAS_PATH = Path("data/areas.json")
_areas_data: Dict[str, Any] = {}
if _AREAS_PATH.exists():
    _areas_data = json.loads(_AREAS_PATH.read_text(encoding="utf-8"))

def _get_items_by_type(item_type: str) -> List[Tuple[str, Dict[str, Any]]]:
    return [
        (k, info)
        for k, info in _items_data.items()
        if info.get("type") == item_type
    ]

class FishingCog(commands.Cog):
    """Handles `/fish`: catch fish, trash, coins, or crates, with full progression updates."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._fish_items = _get_items_by_type("fishing")
        self._trash_items = _get_items_by_type("trash")
        self._crate_rarities = ["common crate", "uncommon crate", "rare crate", "legendary crate"]

    async def get_regen_user(self, user_id: int) -> Dict | None:
        db = self.bot.db
        user = await db.general.find_one({"id": user_id})
        if not user:
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
        name="fish",
        description="🎣 Fish the waters for catches, treasure, and surprises!"
    )
    async def fish(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # 1) Ensure registered & has stamina & tool
        profile = await self.get_regen_user(user_id)
        if not profile:
            return await interaction.response.send_message(
                "❌ Please `/register` before you head out to fish!",
                ephemeral=True
            )
        
        if profile.get("inDungeon", False):
            return await interaction.response.send_message(
                "❌ You can't do this while in a dungeon! Complete or flee from your dungeon first.",
                ephemeral=True
            )
        
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message(
                "😴 You’re out of stamina! Rest or boost before fishing again.",
                ephemeral=True
            )
        
        equipment_doc = await db.equipment.find_one({"id": user_id})
        tool_iid = equipment_doc.get("fishingTool")
        if not tool_iid:
            return await interaction.response.send_message(
                "❌ You must equip a fishing tool first.",
                ephemeral=True
            )

        # make sure the instance actually exists in the player's instances array
        instances = equipment_doc.get("instances", [])
        if not any(inst.get("instance_id") == tool_iid for inst in instances):
            return await interaction.response.send_message(
                "❌ Your equipped fishing tool couldn't be found in your instances. "
                "If this persists, contact the dev.",
                ephemeral=True
            )

        # 2) Fetch current subarea
        area_doc = await db.areas.find_one({"id": user_id})
        if not area_doc:
            return await interaction.response.send_message(
                "❌ Couldn’t determine your current location!", ephemeral=True
            )

        player_area = area_doc.get("currentArea")
        player_sub = area_doc.get("currentSubarea")
        if not player_area or not player_sub:
            return await interaction.response.send_message(
                "❌ You’re not in a valid location!", ephemeral=True
            )

        area_info = _areas_data.get(player_area, {})
        subarea_info = area_info.get("sub_areas", {}).get(player_sub, {})
        if not subarea_info:
            return await interaction.response.send_message(
                "❌ Invalid subarea data!", ephemeral=True
            )

        # 3) Build available lists from subarea resources
        resources = subarea_info.get("resources", [])
        available_fish = [
            (k, info) for k, info in self._fish_items
            if k in resources
        ]
        available_trash = [
            (k, info) for k, info in self._trash_items
            if k in resources
        ]

        if not available_fish and not available_trash:
            return await interaction.response.send_message(
                "🎣 There’s nothing to catch in this subarea.", ephemeral=True
            )

        # 4) Load thresholds and roll
        treasure_chance = profile.get("treasureChance", 0)
        trash_chance = profile.get("trashChance", 100)
        roll = random.randint(1, 100)

        kind: str
        key: str
        qty: int
        xp_gain: int

        if roll <= treasure_chance:
            # Treasure: coins or crate
            if random.choice([True, False]):
                kind = "coins"
                qty = random.randint(10, 500)
                xp_gain = 3
            else:
                kind = "crate"
                key = random.choice(self._crate_rarities)
                qty = 1
                xp_gain = 4

        elif roll <= trash_chance and available_trash:
            kind = "trash"
            key, info = random.choices(
                [(k, i) for k, i in available_trash],
                weights=[i.get("weight", 10) for _, i in available_trash],
                k=1
            )[0]
            qty = random.randint(1, 2)
            xp_gain = info.get("xp", 1) * qty

        else:
            # Fish catch (fall back to fish if no trash)
            if not available_fish:
                # if no fish, treat as trash zone
                kind = "trash"
                key, info = random.choice(available_trash)
                qty = random.randint(1, 2)
                xp_gain = info.get("xp", 1) * qty
            else:
                kind = "fish"
                key, info = random.choices(
                    [(k, i) for k, i in available_fish],
                    weights=[i.get("weight", 10) for _, i in available_fish],
                    k=1
                )[0]
                qty = random.randint(1, 2)
                xp_gain = info.get("xp", 1) * qty

        essence_gain = round(xp_gain * 0.35, 2)

        # 5) Deduct stamina
        await db.general.update_one({"id": user_id}, {"$inc": {"stamina": -1}})

        # 6) Skill XP + level-up
        sk = await db.skills.find_one({"id": user_id})
        old_xp, old_lvl = sk["fishingXP"], sk["fishingLevel"]
        new_xp = old_xp + xp_gain
        lvl_thr = 50 * old_lvl + 10
        leveled_fish = False
        bonus_inc = 2
        if new_xp >= lvl_thr:
            leveled_fish = True
            leftover = new_xp - lvl_thr
            await db.skills.update_one(
                {"id": user_id},
                {"$set": {"fishingLevel": old_lvl + 1, "fishingXP": leftover},
                 "$inc": {"fishingBonus": bonus_inc}}
            )
            await db.general.update_one({"id": user_id}, {"$inc": {"accuracy": bonus_inc}})
        else:
            await db.skills.update_one({"id": user_id}, {"$set": {"fishingXP": new_xp}})
        await db.general.update_one({"id": user_id}, {"$inc": {"fishingEssence": essence_gain}})

        # 7) Handle loot/inventory/wallet
        wallet_inc = crate_inc = 0
        if kind == "coins":
            wallet_inc = qty
            await db.general.update_one({"id": user_id}, {"$inc": {"wallet": wallet_inc}})
        elif kind == "crate":
            crate_inc = qty
            idx = self._crate_rarities.index(key)
            await db.general.update_one(
                {"id": user_id},
                {"$inc": {f"crates.{idx}": crate_inc}}
            )
        else:
            await db.inventory.update_one({"id": user_id}, {"$inc": {key: qty}})
            coll = await db.collections.find_one({"id": user_id})
            old_c, old_cl = coll["fish"], coll["fishLevel"]
            new_c = old_c + qty
            coll_thr = 50 * old_cl + 50
            if new_c >= coll_thr:
                new_level = old_c + 1
                await db.collections.update_one(
                    {"id": user_id},
                    {"$set": {"fish": new_c, "fishLevel": old_cl + 1}}
                )
                # Unlock new recipes for this collection
                await unlock_collection_recipes(db, user_id, "fish", new_level)
                
            else:
                await db.collections.update_one({"id": user_id}, {"$set": {"fish": new_c}})

        # 8) Build embed
        embed = discord.Embed(
            title="🎣 Fishing Results",
            color=discord.Color.teal(),
            timestamp=datetime.datetime.now()
        )
        if kind == "coins":
            embed.add_field(name="💰 Treasure!", value=f"You reeled in **{wallet_inc:,} coins**", inline=False)
        elif kind == "crate":
            embed.add_field(name="📦 Crate!", value=f"You got a **{key.title()}**", inline=False)
        else:
            embed.add_field(
                name="🐟 Catch!",
                value=f"You caught **{qty}** × **{_items_data[key]['name'].title()}**",
                inline=False
            )

        embed.add_field(name="Fishing XP", value=f"⭐ {xp_gain:,} XP", inline=True)
        embed.add_field(name="Fishing Essence", value=f"✨ {essence_gain}", inline=True)
        embed.add_field(name="Stamina Remaining", value=f"{profile['stamina'] - 1}", inline=False)

        if leveled_fish:
            embed.add_field(
                name="🏅 Level Up!",
                value=(
                    f"You’re now **Fishing Level {old_lvl + 1}**\n"
                    f"🔋 +{bonus_inc} fishing bonus!\n"
                    f"🎯 +{bonus_inc} accuracy!"
                ), inline=False
            )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(FishingCog(bot), guilds=[discord.Object(id=GUILD_ID)])