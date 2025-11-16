import random
import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from server.userMethods import regenerate_stamina, calculate_power_rating

from settings import GUILD_ID

# Load armor templates and set bonuses
_ARMOR_TEMPLATES_PATH = Path("data/armorTemplates.json")
_SET_BONUSES_PATH = Path("data/setBonuses.json")

armor_templates: Dict[str, Any] = {}
set_bonuses_config: Dict[str, Any] = {}

if _ARMOR_TEMPLATES_PATH.exists():
    armor_templates = json.loads(_ARMOR_TEMPLATES_PATH.read_text(encoding="utf-8"))

if _SET_BONUSES_PATH.exists():
    set_bonuses_config = json.loads(_SET_BONUSES_PATH.read_text(encoding="utf-8"))

# Load mobs data
_MOBS_PATH = Path("data/huntMobs.json")
_mobs_data: Dict[str, Any] = {}
if _MOBS_PATH.exists():
    import json
    _mobs_data = json.loads(_MOBS_PATH.read_text(encoding="utf-8")).get("mobs", {})

# Load areas
_AREAS_PATH = Path("data/areas.json")
_areas_data: Dict[str, Any] = {}
if _AREAS_PATH.exists():
    _areas_data = json.loads(_AREAS_PATH.read_text(encoding="utf-8"))

class CombatCog(commands.Cog):
    """⚔️ Engage in combat with dangerous creatures and reap rewards!"""

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

    def _get_area_mobs(self, area: str, subarea: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Get mobs available in the player's current subarea of an area,
        fetching full mob details from _mobs_data.
        """
        normalized_area = area.lower()
        normalized_subarea = subarea.lower()

        # Defensive checks
        if normalized_area not in _areas_data:
            return []

        sub_areas = _areas_data[normalized_area].get("sub_areas", {})
        if normalized_subarea not in sub_areas:
            return []

        mob_ids = sub_areas[normalized_subarea].get("mobs", [])
        mobs = []
        for mob_id in mob_ids:
            mob_info = _mobs_data.get(mob_id)
            if mob_info:
                mobs.append((mob_id, mob_info))

        return mobs
    
    async def _get_armor_and_set_bonuses(self, user_id: int) -> Dict[str, int]:
        """Calculate total bonuses from equipped armor and set bonuses."""
        db = self.bot.db
        equip_doc = await db.equipment.find_one({"id": user_id}) or {}
        
        bonuses = {
            "HP": 0,
            "STR": 0,
            "DEF": 0,
            "EVA": 0
        }
        
        # 1. Calculate bonuses from individual armor pieces
        armor_slots = ["head", "chest", "legs", "feet", "gloves"]
        for slot in armor_slots:
            instance_id = equip_doc.get(slot)
            if instance_id:
                instance = next((inst for inst in equip_doc.get("instances", []) 
                            if inst.get("instance_id") == instance_id), None)
                if instance and instance.get("stats"):
                    stats = instance.get("stats", {})
                    for stat, value in stats.items():
                        if stat in bonuses:
                            bonuses[stat] += value
        
        # 2. Calculate bonuses from set bonuses
        set_counts = {}
        for slot in armor_slots:
            instance_id = equip_doc.get(slot)
            if instance_id:
                instance = next((inst for inst in equip_doc.get("instances", []) 
                            if inst.get("instance_id") == instance_id), None)
                if instance and instance.get("set"):
                    set_name = instance["set"]
                    set_counts[set_name] = set_counts.get(set_name, 0) + 1
        
        for set_name, count in set_counts.items():
            set_config = set_bonuses_config.get(set_name, {})
            for threshold in ["2", "4", "5"]:
                if count >= int(threshold) and threshold in set_config:
                    threshold_bonuses = set_config[threshold]
                    for stat, value in threshold_bonuses.items():
                        if stat in bonuses:
                            bonuses[stat] += value
        
        return bonuses

    async def _calculate_stats(self, user_id: int) -> Dict[str, int]:
        """Calculate player's combat stats with proper HP handling."""
        db = self.bot.db
        general = await db.general.find_one({"id": user_id})
        skills = await db.skills.find_one({"id": user_id})
        
        # Get armor and set bonuses
        equipment_bonuses = await self._get_armor_and_set_bonuses(user_id)
        
        max_hp = general["maxHP"] + equipment_bonuses["HP"]  # Add HP bonus to max HP
        current_hp = min(general["hp"], max_hp)  # Ensure HP doesn't exceed max
        
        return {
            "current_hp": current_hp,
            "max_hp": max_hp,
            "str": general["strength"] + skills["combatLevel"] * 2 + equipment_bonuses["STR"],
            "def": general["defense"] + skills["miningLevel"] * 1 + equipment_bonuses["DEF"],
            "eva": general["evasion"] + skills["foragingLevel"] * 1 + equipment_bonuses["EVA"],
            "acc": general["accuracy"] + skills["combatLevel"] * 2
        }

    async def _handle_combat_level_up(self, user_id: int, xp_gain: int) -> Tuple[int, int, bool]:
        """Process combat XP and level ups, updating max HP in database."""
        db = self.bot.db
        leveled_up = False
        
        # Atomic operation to get current state
        result = await db.skills.find_one_and_update(
            {"id": user_id},
            {"$inc": {"combatXP": xp_gain}},
            return_document=True
        )
        
        old_level = result["combatLevel"]
        total_xp = result["combatXP"]
        new_level = old_level
        
        # Calculate level progression
        while True:
            xp_required = 50 * new_level + 10
            if total_xp < xp_required:
                break
            total_xp -= xp_required
            new_level += 1
            leveled_up = True
        
        if leveled_up:
            levels_gained = new_level - old_level
            
            # Update skills collection with combatBonus
            await db.skills.update_one(
                {"id": user_id},
                {"$set": {
                    "combatLevel": new_level,
                    "combatXP": total_xp
                },
                "$inc": {
                    "combatBonus": levels_gained * 2  # Add combatBonus
                }}
            )
            
            # Update max HP and strength in general collection
            await db.general.update_one(
                {"id": user_id},
                {"$inc": {
                    "maxHP": levels_gained * 5,
                    "strength": levels_gained * 2  # Add strength
                }}
            )
        
        return (new_level - old_level, new_level, leveled_up)

    def _calculate_mob_power(self, mob: Dict[str, Any]) -> int:
        """Calculate a mob's power rating (excluding HP)."""
        stats = mob.get("stats", {})
        return stats.get("str", 0) + stats.get("def", 0) + stats.get("eva", 0) + stats.get("acc", 0)

    def _get_balanced_mob(self, player_power: int, mobs: List[Tuple[str, Dict[str, Any]]], range_padding: int = 10) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Select a mob with a power rating within ±padding range of the player's."""
        eligible = [
            (mob_id, mob) for mob_id, mob in mobs
            if player_power - range_padding <= self._calculate_mob_power(mob) <= player_power + range_padding
        ]
        if eligible:
            return random.choice(eligible)
        return random.choice(mobs) if mobs else None

    @app_commands.command(
        name="hunt",
        description="⚔️ Seek out dangerous creatures to battle and loot!"
    )
    async def hunt(self, interaction: discord.Interaction) -> None:
        db = self.bot.db
        user_id = interaction.user.id

        # --- 1) Verify player readiness ---
        profile = await self.get_regen_user(user_id)
        if not profile:
            return await interaction.response.send_message(
                "🛡️ You need to `/register` before hunting!",
                ephemeral=True
            )
        
        if profile.get("inDungeon", False):
            return await interaction.response.send_message(
                "❌ You can't do this while in a dungeon! Complete or flee from your dungeon first.",
                ephemeral=True
            )
        
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message(
                "😴 You're too exhausted to hunt! Rest or use a stamina potion.",
                ephemeral=True
            )

        # --- 2) Get available mobs ---
        area_data = await db.areas.find_one({"id": user_id})
        if not area_data:
            return await interaction.response.send_message(
                "⚠️ Your location data could not be found.",
                ephemeral=True
            )
        
        current_area = area_data.get("currentArea", "").lower()
        current_subarea = area_data.get("currentSubarea", "").lower()

        available_mobs = self._get_area_mobs(current_area, current_subarea)
        if not available_mobs:
            return await interaction.response.send_message(
                f"🌄 No dangerous creatures found in {current_subarea.replace('_', ' ').title()}!",
                ephemeral=True
            )

        # --- 3) Combat simulation ---
        mob_choice = self._get_balanced_mob(profile["powerRating"], available_mobs, range_padding=5)
        if not mob_choice:
            return await interaction.response.send_message(
                "⚠️ Couldn't find a suitable creature to battle.",
                ephemeral=True
            )
        mob_id, mob = mob_choice

        # base player stats
        player_stats = await self._calculate_stats(user_id)
        mob_hp = mob["stats"]["hp"]
        player_hp = player_stats["current_hp"]

        # --- read weapon stats from equipped main hand (if present) and apply on-the-fly ---
        equip_doc = await db.equipment.find_one({"id": user_id}) or {}
        # try a few slot name variants to be safe
        mainhand_iid = equip_doc.get("mainHand") or equip_doc.get("mainhand") or equip_doc.get("mainhand_id") or equip_doc.get("main_hand")
        weapon_stats = {}
        weapon_skill_bonus = 0.0
        if mainhand_iid:
            instances = equip_doc.get("instances", []) or []
            inst = next((it for it in instances if it.get("instance_id") == mainhand_iid), None)
            if inst:
                # prefer inst-level stats, or fall back to template-level 'stats' if instance doesn't store them
                weapon_stats = inst.get("stats") or {}
                # allow template fallback if available
                if not weapon_stats:
                    # (we don't import here to keep behavior identical to prior code; instances should ideally have stats)
                    weapon_stats = inst.get("template_stats", {}) or {}
                    
        # defensive casts
        w_str = float(weapon_stats.get("STR", 0) or 0)
        w_eva = float(weapon_stats.get("EVA", 0) or 0)
        w_crit = float(weapon_stats.get("CRITPER", 0) or 0)
        w_skill = float(weapon_stats.get("SKILL", 0) or 0)
        weapon_skill_bonus = w_skill

        # apply weapon STR/EVA and armor bonuses to the runtime-only player stats
        player_stats["str"] = int(player_stats["str"] + round(w_str))
        player_stats["eva"] = int(player_stats["eva"] + round(w_eva))
        player_stats["def"] = int(player_stats["def"])  # DEF already includes armor bonuses

        combat_log = []
        # keep track of whether we got crits for log messages
        while player_hp > 0 and mob_hp > 0:
            # Player attack
            hit_chance = player_stats["acc"] / (player_stats["acc"] + mob["stats"]["eva"])
            if random.random() <= hit_chance:
                # base damage calculation (as before)
                damage = max(1, player_stats["str"] - mob["stats"]["def"] // 2)

                # roll crit using weapon crit% (only weapon provides crit in this design)
                is_crit = random.random() < w_crit if w_crit > 0 else False
                if is_crit:
                    damage = int(max(1, damage * 2))  # crit doubles damage
                    combat_log.append(f"💥 CRITICAL HIT! You dealt **{damage}** damage to {mob['name']}!")

                else:
                    combat_log.append(f"🗡️ You hit {mob['name']} for **{damage}** damage!")

                mob_hp -= damage
            else:
                combat_log.append(f"✖️ You missed {mob['name']}.")

            # Mob attack
            if mob_hp > 0:
                mob_hit_chance = mob["stats"]["acc"] / (mob["stats"]["acc"] + player_stats["eva"])
                if random.random() <= mob_hit_chance:
                    mob_damage = max(1, mob["stats"]["str"] - player_stats["def"] // 2)
                    player_hp = max(0, player_hp - mob_damage)
                    combat_log.append(f"🩸 {mob['name']} hits you for **{mob_damage}** damage!")
                else:
                    combat_log.append(f"🛡️ {mob['name']} missed you.")

        victory = player_hp > 0

        # --- 4) Process results ---
        base_xp = mob["xp"]
        # weapon SKILL increases combat XP gained slightly (multiplicative)
        xp_multiplier = 1.0 + weapon_skill_bonus
        if victory:
            xp_gain = int(base_xp * xp_multiplier)
        else:
            xp_gain = int(base_xp * 0.2 * xp_multiplier)

        levels_gained, new_level, leveled_up = await self._handle_combat_level_up(user_id, xp_gain)

        # Update player state
        updates = {
            "$inc": {"stamina": -1},
            "$set": {
                "hp": max(0, min(player_hp, player_stats["max_hp"]))
            }
        }
        
        loot = []
        gold_gain = 0
        gold_loss = 0
        if victory:
            gold_gain = random.randint(*mob["gold"])
            updates["$inc"]["wallet"] = gold_gain
            
            # Process loot
            for entry in mob["loot_table"]:
                if random.random() <= entry["chance"]:
                    qty = random.randint(*entry.get("quantity", [1, 1]))
                    loot.append((entry["item"], qty))
                    await db.inventory.update_one(
                        {"id": user_id}, {"$inc": {entry["item"]: qty}}
                    )
        else:
            gold_loss = min(profile["wallet"], random.randint(10, 25))
            stamina_loss = random.randint(10, 25)
            new_stamina = max(0, profile["stamina"] - stamina_loss)

            await db.general.update_one({"id": user_id}, {
                "$inc": {"wallet": -gold_loss},
                "$set": {"stamina": new_stamina}
            })

        await db.general.update_one({"id": user_id}, updates)

        # --- 5) Build embed ---
        result_lines = [
            f"**{'VICTORY! 🏆' if victory else 'DEFEAT! ☠️'}**",
            f"• XP Gained: ⭐ {xp_gain}{' (Partial)' if not victory else ''}",
            f"• {'Gold Earned' if victory else 'Lost Gold'}: 🪙 {gold_gain if victory else gold_loss}",
            f"• {'Stamina Lost' if not victory else 'Stamina Left'}: ⚡ {profile['stamina']-1 if victory else stamina_loss}",
            f"• Remaining HP: ❤️ {min(player_hp, player_stats['max_hp'] + levels_gained*5)}/{player_stats['max_hp'] + levels_gained*5}",
        ]

        embed = discord.Embed(
            title=f"⚔️ Combat with {mob['name']}",
            color=discord.Color.green() if victory else discord.Color.red(),
            description="\n".join(result_lines),
            timestamp=datetime.datetime.now()
        )

        # Add loot display if victorious
        if victory and loot:
            loot_text = "\n".join(
                f"• {item.replace('_', ' ').title()} ×{qty}"
                for item, qty in loot
            )
            embed.add_field(
                name="🎁 Loot Obtained",
                value=loot_text,
                inline=False
            )

        if leveled_up:
            embed.add_field(
                name="🎖️ Combat Level Up!",
                value=(
                    f"You're now Combat Level **{new_level}**!\n"
                    f"❤️ +{levels_gained*5} Max HP!\n"
                    f"💪 +{levels_gained*2} Strength!\n"
                    f"⚔️ +{levels_gained*2} Combat Bonus!"
                ),
                inline=False
            )

        if combat_log:
            # show only last 3 actions
            embed.add_field(
                name="Combat Log (Last 3 Actions)",
                value="\n".join(combat_log[-3:]),
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CombatCog(bot), guilds=[discord.Object(id=GUILD_ID)])