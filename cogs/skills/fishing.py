import datetime
import random
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from server.skillMethods import get_equipped_tool, calculate_final_qty, apply_gather_results
from server.userMethods import regenerate_stamina, calculate_power_rating, has_skill_resources

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

class FishingCog(commands.Cog):
    """Handles `/fish`: catch fish, trash, coins, or crates, with full progression updates."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
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
                "😴 You're out of stamina! Rest or boost before fishing again.",
                ephemeral=True
            )

        # Get equipped fishing tool with stats
        tool_inst, template = await get_equipped_tool(db, user_id, "fishingTool")
        if not tool_inst:
            return await interaction.response.send_message(
                "❌ You must equip a fishing tool first.",
                ephemeral=True
            )

        # 2) Fetch current subarea
        area_doc = await db.areas.find_one({"id": user_id})
        if not area_doc:
            return await interaction.response.send_message(
                "❌ Couldn't determine your current location!", ephemeral=True
            )

        player_area = area_doc.get("currentArea")
        player_sub = area_doc.get("currentSubarea")
        if not player_area or not player_sub:
            return await interaction.response.send_message(
                "❌ You're not in a valid location!", ephemeral=True
            )

        area_info = _areas_data.get(player_area, {})
        subarea_info = area_info.get("sub_areas", {}).get(player_sub, {})
        if not subarea_info:
            return await interaction.response.send_message(
                "❌ Invalid subarea data!", ephemeral=True
            )

        # Check if area has fishing resources
        if not has_skill_resources(subarea_info, _items_data, "fishing"):
            return await interaction.response.send_message(
                "🎣 There's nothing to catch in this subarea.", ephemeral=True
            )

        # 3) Build available lists from subarea resources
        resources = subarea_info.get("resources", [])
        available_fish = [
            (k, info) for k, info in _items_data.items() 
            if k in resources and info.get("type") == "fishing"
        ]
        available_trash = [
            (k, info) for k, info in _items_data.items()
            if k in resources and info.get("type") == "trash"
        ]

        if not available_fish and not available_trash:
            return await interaction.response.send_message(
                "🎣 There's nothing to catch in this subarea.", ephemeral=True
            )

        # 4) Apply tool bonuses to treasure chance and crate rarity
        base_treasure_chance = profile.get("treasureChance", 0)
        base_trash_chance = profile.get("trashChance", 100)
        
        # Get tool stats
        tool_rare_mult = tool_inst.get("stats", {}).get("rare_multiplier", 
                      template.get("stats", {}).get("rare_multiplier", 1.0)) if template else 1.0
        
        # Apply rare multiplier to treasure chance
        effective_treasure_chance = base_treasure_chance * tool_rare_mult
        
        # 5) Load fishing skill bonus
        skill_doc = await db.skills.find_one({"id": user_id})
        fishing_bonus = int(skill_doc.get("fishingBonus", 0)) if skill_doc else 0

        # 6) Determine catch type with modified treasure chance
        roll = random.randint(1, 100)
        kind: str
        key: str
        base_qty: int
        xp_per_unit: int

        if roll <= effective_treasure_chance:
            # Treasure: coins or crate
            if random.choice([True, False]):
                kind = "coins"
                # Apply yield multiplier to coin amount
                tool_yield = tool_inst.get("stats", {}).get("yield_multiplier", 
                          template.get("stats", {}).get("yield_multiplier", 1.0)) if template else 1.0
                base_coin_qty = random.randint(10, 500)
                base_qty = max(1, int(base_coin_qty * tool_yield))
                xp_per_unit = 3
            else:
                kind = "crate"
                # Apply rare multiplier to crate rarity selection
                base_weights = [50, 30, 15, 5]  # common, uncommon, rare, legendary
                adjusted_weights = [
                    base_weights[0],  # common unchanged
                    base_weights[1],  # uncommon unchanged  
                    base_weights[2] * tool_rare_mult,  # rare boosted
                    base_weights[3] * tool_rare_mult   # legendary boosted
                ]
                key = random.choices(self._crate_rarities, weights=adjusted_weights, k=1)[0]
                base_qty = 1
                xp_per_unit = 4

        elif roll <= base_trash_chance and available_trash:
            kind = "trash"
            key, info = random.choices(
                [(k, i) for k, i in available_trash],
                weights=[i.get("weight", 10) for _, i in available_trash],
                k=1
            )[0]
            base_qty = random.randint(1, 2)
            xp_per_unit = info.get("xp", 1)

        else:
            # Fish catch (fall back to fish if no trash)
            if not available_fish:
                # if no fish, treat as trash zone
                kind = "trash"
                key, info = random.choice(available_trash)
                base_qty = random.randint(1, 2)
                xp_per_unit = info.get("xp", 1)
            else:
                kind = "fish"
                key, info = random.choices(
                    [(k, i) for k, i in available_fish],
                    weights=[i.get("weight", 10) for _, i in available_fish],
                    k=1
                )[0]
                base_qty = random.randint(1, 2)
                xp_per_unit = info.get("xp", 1)

        # 7) Apply tool and skill bonuses to quantity for fish/trash
        bonus_gained = False
        if kind in ["fish", "trash"]:
            final_qty, bonus_gained, float_qty = calculate_final_qty(base_qty, tool_inst, template, fishing_bonus)
        else:
            final_qty = base_qty  # coins/crates already had multipliers applied

        # 8) Handle different outcome types
        embed = discord.Embed(
            title="🎣 Fishing Results",
            color=discord.Color.teal(),
            timestamp=datetime.datetime.now()
        )

        if kind == "coins":
            # Handle coins separately
            await db.general.update_one({"id": user_id}, {
                "$inc": {
                    "stamina": -1,
                    "wallet": final_qty
                }
            })
            
            # Update skill and essence manually for coins
            xp_gain = xp_per_unit * final_qty
            essence_gain = round(xp_gain * 0.35, 2)
            
            skill_summary = await self._update_fishing_skill(db, user_id, xp_gain, essence_gain)
            
            embed.add_field(name="💰 Treasure!", value=f"You reeled in **{final_qty:,} coins**", inline=False)
            embed.add_field(name="Fishing XP", value=f"⭐ {xp_gain:,} XP", inline=True)
            embed.add_field(name="Fishing Essence", value=f"✨ {essence_gain}", inline=True)

        elif kind == "crate":
            # Handle crate separately
            await db.general.update_one({"id": user_id}, {
                "$inc": {"stamina": -1},
                "$inc": {f"crates.{self._crate_rarities.index(key)}": final_qty}
            })
            
            # Update skill and essence manually for crate
            xp_gain = xp_per_unit * final_qty
            essence_gain = round(xp_gain * 0.35, 2)
            
            skill_summary = await self._update_fishing_skill(db, user_id, xp_gain, essence_gain)
            
            embed.add_field(name="📦 Crate!", value=f"You got a **{key.title()}**", inline=False)
            embed.add_field(name="Fishing XP", value=f"⭐ {xp_gain:,} XP", inline=True)
            embed.add_field(name="Fishing Essence", value=f"✨ {essence_gain}", inline=True)

        else:
            # Use apply_gather_results for fish/trash
            collection_key = "fish" if kind == "fish" else None
            
            summary = await apply_gather_results(
                db=db,
                user_id=user_id,
                picked_key=key,
                final_qty=final_qty,
                xp_per_unit=xp_per_unit,
                skill_prefix="fishing",
                skill_bonus_inc=2,
                essence_field="fishingEssence",
                collection_key=collection_key
            )

            # Also update accuracy for fishing level ups
            if summary["skill_leveled"]:
                await db.general.update_one({"id": user_id}, {"$inc": {"accuracy": 2}})

            item_name = _items_data[key]['name'].title()
            embed.add_field(
                name="🐟 Catch!" if kind == "fish" else "🗑️ Trash!",
                value=f"You caught **{final_qty}** × **{item_name}**",
                inline=False
            )
            embed.add_field(name="Fishing XP", value=f"⭐ {summary['xp_gain']:,} XP", inline=True)
            embed.add_field(name="Fishing Essence", value=f"✨ {round(summary['xp_gain'] * 0.35, 2):,}", inline=True)

            if bonus_gained:
                embed.add_field(name="🎉 Bonus!", value="Your tool's extra-roll granted **+1** additional item!", inline=False)
            if summary["skill_leveled"]:
                embed.add_field(
                    name="🏅 Level Up!",
                    value=f"You're now **Fishing Level {summary['old_skill_level'] + 1}**\n🔋 +2 fishing bonus!\n🎯 +2 accuracy!",
                    inline=False
                )
            if summary["collection_leveled"] and kind == "fish":
                embed.add_field(
                    name="📚 Collection Milestone!", 
                    value=f"Your **Fish Collection** is now **Level {summary['old_collection_level'] + 1}**", 
                    inline=False
                )

        embed.add_field(name="Stamina Remaining", value=f"💪 {profile['stamina'] - 1}", inline=False)
        await interaction.response.send_message(embed=embed)

    async def _update_fishing_skill(self, db, user_id: int, xp_gain: int, essence_gain: float) -> Dict[str, Any]:
        """Helper to update fishing skill for coin/crate outcomes"""
        skill_doc = await db.skills.find_one({"id": user_id})
        old_xp = int(skill_doc.get("fishingXP", 0))
        old_lvl = int(skill_doc.get("fishingLevel", 0))

        new_xp = old_xp + xp_gain
        lvl_thr = 50 * old_lvl + 10

        leveled = False
        if new_xp >= lvl_thr:
            leveled = True
            leftover = new_xp - lvl_thr
            await db.skills.update_one(
                {"id": user_id},
                {
                    "$set": {"fishingLevel": old_lvl + 1, "fishingXP": leftover},
                    "$inc": {"fishingBonus": 2}
                }
            )
            await db.general.update_one({"id": user_id}, {"$inc": {"accuracy": 2}})
        else:
            await db.skills.update_one({"id": user_id}, {"$set": {"fishingXP": new_xp}})

        await db.general.update_one({"id": user_id}, {"$inc": {"fishingEssence": essence_gain}})

        return {
            "leveled": leveled,
            "old_level": old_lvl,
            "new_level": old_lvl + 1 if leveled else old_lvl
        }


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(FishingCog(bot), guilds=[discord.Object(id=GUILD_ID)])