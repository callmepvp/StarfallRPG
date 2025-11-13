import json
import random
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button

# --- Load dungeon & mob data ---
_FLOORS_PATH = Path("data/dungeons/dungeonFloors.json")
_POOLS_PATH = Path("data/dungeons/dungeonPools.json")
_DUNGEON_MOBS_PATH = Path("data/dungeons/dungeonMobs.json")

dungeon_floors: Dict[str, Any] = {}
dungeon_pools: Dict[str, Any] = {}
dungeon_mobs: Dict[str, Any] = {}

if _FLOORS_PATH.exists():
    dungeon_floors = json.loads(_FLOORS_PATH.read_text(encoding="utf-8")).get("floors", {})
if _POOLS_PATH.exists():
    dungeon_pools = json.loads(_POOLS_PATH.read_text(encoding="utf-8"))
if _DUNGEON_MOBS_PATH.exists():
    dungeon_mobs = json.loads(_DUNGEON_MOBS_PATH.read_text(encoding="utf-8"))

class DungeonCog(commands.Cog):
    """Solo dungeon exploration system"""
    
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.active_dungeons = {}  # Track active dungeon runs

    async def get_player_data(self, user_id: int) -> Dict[str, Any]:
        """Fetch all player data needed for dungeon"""
        db = self.bot.db
        
        # Get base player stats
        player = await db.general.find_one({"id": user_id})
        if not player:
            return {}
            
        # Get equipment for stat calculation
        equipment = await db.equipment.find_one({"id": user_id}) or {}
        
        # Get skills
        skills = await db.skills.find_one({"id": user_id}) or {}
        
        return {
            **player,
            "equipment": equipment,
            "skills": skills
        }

    async def update_player_hp(self, user_id: int, current_hp: int):
        """Update player's HP in database immediately"""
        db = self.bot.db
        await db.general.update_one(
            {"id": user_id},
            {"$set": {"hp": current_hp}}
        )

    async def set_dungeon_status(self, user_id: int, in_dungeon: bool):
        """Set player's dungeon status in database"""
        db = self.bot.db
        await db.general.update_one(
            {"id": user_id},
            {"$set": {"inDungeon": in_dungeon}}
        )

    def calculate_combat_stats(self, player_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate final combat stats including equipment bonuses"""
        # Base stats from player level/attributes
        base_stats = {
            "str": player_data.get("strength", 0),
            "def": player_data.get("defense", 0),
            "eva": player_data.get("evasion", 0),
            "acc": player_data.get("accuracy", 0),
            "max_hp": player_data.get("maxHP", 100),
            "current_hp": min(player_data.get("hp", 100), player_data.get("maxHP", 100)),
            "crit_chance": 0.0,
            "skill_bonus": 0.0
        }
        
        # Apply equipment bonuses
        equipment = player_data.get("equipment", {})
        instances = equipment.get("instances", [])
        
        for item in instances:
            if item.get("equipped_in"):  # If item is equipped
                stats = item.get("stats", {})
                base_stats["str"] += stats.get("STR", 0)
                base_stats["eva"] += stats.get("EVA", 0)
                base_stats["crit_chance"] += stats.get("CRITPER", 0)
                base_stats["skill_bonus"] += stats.get("SKILL", 0)
        
        # Apply skill bonuses
        skills = player_data.get("skills", {})
        combat_level = skills.get("combatLevel", 1)
        base_stats["str"] += combat_level * 2
        base_stats["acc"] += combat_level * 2
        
        return base_stats

    @app_commands.command(
        name="dungeon",
        description="🗝️ Enter a dungeon and face combat challenges!"
    )
    @app_commands.describe(floor="The dungeon floor number")
    async def dungeon(self, interaction: discord.Interaction, floor: int = 1):
        """Start a dungeon run"""
        user_id = interaction.user.id
        
        # Check if player already in dungeon
        db = self.bot.db
        player_check = await db.general.find_one({"id": user_id})
        if player_check and player_check.get("inDungeon", False):
            return await interaction.response.send_message(
                "❌ You're already in a dungeon! Complete it first.",
                ephemeral=True
            )
        
        # Get player data
        player_data = await self.get_player_data(user_id)
        if not player_data:
            return await interaction.response.send_message(
                "❌ You need to `/register` first!",
                ephemeral=True
            )
        
        # Check floor exists
        floor_key = str(floor)
        if floor_key not in dungeon_floors:
            return await interaction.response.send_message(
                f"❌ Floor {floor} doesn't exist!",
                ephemeral=True
            )
        
        # Check if mobs are available
        pool_key = f"floor_{floor}"
        available_mobs = dungeon_pools.get(pool_key, {}).get("mobs", [])
        if not available_mobs:
            return await interaction.response.send_message(
                f"❌ No enemies configured for floor {floor}!",
                ephemeral=True
            )
        
        # Check if mob data is loaded
        if not dungeon_mobs:
            return await interaction.response.send_message(
                "❌ Mob data not loaded properly!",
                ephemeral=True
            )
        
        # Calculate player stats
        player_stats = self.calculate_combat_stats(player_data)
        
        # Set dungeon status
        await self.set_dungeon_status(user_id, True)
        
        # Start dungeon
        floor_data = dungeon_floors[floor_key]
        self.active_dungeons[user_id] = {
            "floor": floor,
            "player_stats": player_stats.copy(),
            "current_room": 0,
            "score": 0,
            "gold": 0,
            "loot": [],
            "completed": False
        }
        
        await interaction.response.send_message(
            f"🗝️ {interaction.user.mention} entered **Dungeon Floor {floor}**!\n"
            f"Prepare for adventuring...",
            ephemeral=False
        )
        
        # Start first room
        await self.start_next_room(interaction, user_id)

    async def start_next_room(self, interaction: discord.Interaction, user_id: int):
        """Start the next room in the dungeon"""
        dungeon_data = self.active_dungeons[user_id]
        floor = dungeon_data["floor"]
        room_index = dungeon_data["current_room"]
        
        floor_data = dungeon_floors[str(floor)]
        rooms = floor_data.get("rooms", [])
        
        if room_index >= len(rooms):
            # Dungeon completed
            await self.complete_dungeon(interaction, user_id)
            return
        
        room_data = rooms[room_index]
        room_type = room_data.get("type", "combat")
        
        if room_type == "combat":
            await self.start_combat_room(interaction, user_id, room_index + 1)
        else:
            # Skip non-combat rooms for now
            dungeon_data["current_room"] += 1
            await interaction.followup.send(
                f"🏃 Skipped {room_type} room {room_index + 1}",
                ephemeral=False
            )
            await self.start_next_room(interaction, user_id)

    async def start_combat_room(self, interaction: discord.Interaction, user_id: int, room_number: int):
        """Start a combat room"""
        dungeon_data = self.active_dungeons[user_id]
        floor = dungeon_data["floor"]
        
        # Get mobs for this floor
        pool_key = f"floor_{floor}"
        available_mobs = dungeon_pools.get(pool_key, {}).get("mobs", [])
        
        if not available_mobs:
            await interaction.followup.send("❌ No enemies available for this floor!")
            return
        
        # Select random mobs
        mob_count = 1  # Start with 1 mob per room
        selected_mob_keys = random.sample(available_mobs, min(mob_count, len(available_mobs)))
        
        # Create mob copies with current HP
        mobs = []
        for key in selected_mob_keys:
            if key in dungeon_mobs:
                mob = dungeon_mobs[key].copy()
                mob["current_hp"] = mob["stats"]["hp"]
                # Initialize combat-specific properties
                mob["is_defending"] = False
                mob["telegraphed_attack"] = None
                mob["telegraph_turns"] = 0
                mobs.append(mob)
        
        if not mobs:
            await interaction.followup.send("❌ Could not load enemy data!")
            return
        
        # Create combat view
        combat_view = DungeonCombatView(
            user_id=user_id,
            player_stats=dungeon_data["player_stats"],
            mobs=mobs,
            room_number=room_number,
            floor=floor,
            cog=self
        )
        
        embed = combat_view.create_combat_embed()
        await interaction.followup.send(embed=embed, view=combat_view)

    async def complete_dungeon(self, interaction: discord.Interaction, user_id: int):
        """Handle dungeon completion"""
        dungeon_data = self.active_dungeons.pop(user_id, None)
        
        # Clear dungeon status regardless
        await self.set_dungeon_status(user_id, False)
        
        if not dungeon_data:
            return
        
        # Calculate grade based on score
        score = dungeon_data["score"]
        grade = self.score_to_grade(score)
        
        # Update player rewards in database
        await self.give_dungeon_rewards(user_id, dungeon_data)
        
        # Send completion message
        embed = discord.Embed(
            title="🏆 Dungeon Completed!",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now()
        )
        
        embed.add_field(name="🎖️ Final Score", value=f"{score} ({grade})", inline=True)
        embed.add_field(name="🪙 Gold Earned", value=dungeon_data["gold"], inline=True)
        embed.add_field(
            name="❤️ HP Remaining", 
            value=f"{dungeon_data['player_stats']['current_hp']}/{dungeon_data['player_stats']['max_hp']}", 
            inline=True
        )
        
        if dungeon_data["loot"]:
            # Capitalize first letter of each word in loot items
            formatted_loot = []
            for item in dungeon_data["loot"]:
                # Replace underscores with spaces and title case
                formatted_item = item.replace('_', ' ').title()
                formatted_loot.append(formatted_item)
            
            loot_text = "\n".join(f"• {item}" for item in formatted_loot)
            embed.add_field(name="🎁 Loot Obtained", value=loot_text, inline=False)
        
        user = self.bot.get_user(user_id)
        if user:
            embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        
        await interaction.followup.send(embed=embed)

    async def give_dungeon_rewards(self, user_id: int, dungeon_data: Dict[str, Any]):
        """Update database with dungeon rewards"""
        db = self.bot.db
        
        # Update gold
        await db.general.update_one(
            {"id": user_id},
            {"$inc": {"wallet": dungeon_data["gold"]}}
        )
        
        # Update HP (final HP update)
        await db.general.update_one(
            {"id": user_id},
            {"$set": {"hp": dungeon_data["player_stats"]["current_hp"]}}
        )
        
        # Update inventory with loot
        for item_name in dungeon_data["loot"]:
            await db.inventory.update_one(
                {"id": user_id},
                {"$inc": {item_name: 1}},
                upsert=True
            )

    def score_to_grade(self, score: int) -> str:
        """Convert score to letter grade"""
        if score >= 90: return "S+"
        if score >= 80: return "S"
        if score >= 70: return "A"
        if score >= 60: return "B"
        if score >= 50: return "C"
        if score >= 40: return "D"
        return "F"

class DungeonCombatView(View):
    """Combat interface for dungeon rooms"""
    
    def __init__(self, user_id: int, player_stats: Dict[str, Any], mobs: List[Dict[str, Any]], 
                 room_number: int, floor: int, cog: DungeonCog):
        super().__init__(timeout=180)  # 3 minute timeout
        self.user_id = user_id
        self.player_stats = player_stats
        self.mobs = mobs
        self.current_mob_index = 0
        self.room_number = room_number
        self.floor = floor
        self.cog = cog
        self.combat_log = []
        self.player_focus = 0  # Focus meter for the combat
        self.player_is_defending = False  # Track if player defended this turn

    async def on_timeout(self):
        """Handle view timeout - treat as fleeing"""
        # Update HP in database before clearing dungeon
        await self.cog.update_player_hp(self.user_id, self.player_stats["current_hp"])
        await self.cog.set_dungeon_status(self.user_id, False)
        
        # Clear from active dungeons
        self.cog.active_dungeons.pop(self.user_id, None)

    def create_combat_embed(self) -> discord.Embed:
        """Create embed showing current combat state"""
        current_mob = self.mobs[self.current_mob_index]
        
        embed = discord.Embed(
            title=f"🗝️ Floor {self.floor} - Room {self.room_number}",
            color=discord.Color.red()
        )
        
        # Player info
        player_info = f"❤️ HP: {self.player_stats['current_hp']}/{self.player_stats['max_hp']}\n"
        player_info += f"💪 STR: {self.player_stats['str']}\n"
        player_info += f"🛡️ DEF: {self.player_stats['def']}\n"
        player_info += f"🎯 Focus: {self.player_focus}/100"  # Focus meter
        
        embed.add_field(
            name="👤 Player",
            value=player_info,
            inline=True
        )
        
        # Enemy info
        enemy_info = f"❤️ HP: {current_mob['current_hp']}/{current_mob['stats']['hp']}\n"
        enemy_info += f"💪 STR: {current_mob['stats']['str']}\n"
        enemy_info += f"🛡️ DEF: {current_mob['stats']['def']}\n"
        
        # Show if enemy is defending
        if current_mob.get('is_defending'):
            enemy_info += "🛡️ **Defending**\n"
        
        # Show telegraphed attack info
        if current_mob.get('telegraphed_attack'):
            turns_left = current_mob.get('telegraph_turns', 0)
            attack_name = current_mob['telegraphed_attack']['name']
            enemy_info += f"⚡ **{attack_name}** in {turns_left} turn{'s' if turns_left > 1 else ''}!\n"
        
        embed.add_field(
            name=f"👹 {current_mob['name']}",
            value=enemy_info,
            inline=True
        )
        
        # Combat log
        if self.combat_log:
            log_text = "\n".join(self.combat_log[-3:])  # Show last 3 actions
            embed.add_field(name="📜 Combat Log", value=log_text, inline=False)
        else:
            embed.add_field(name="📜 Combat Log", value="Combat started! Choose an action.", inline=False)
        
        return embed

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def attack_button(self, interaction: discord.Interaction, button: Button):
        """Handle attack action"""
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your combat!", ephemeral=True)
        
        await self.process_attack(interaction)

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def defend_button(self, interaction: discord.Interaction, button: Button):
        """Handle defend action"""
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your combat!", ephemeral=True)
        
        await self.process_defend(interaction)

    @discord.ui.button(label="Flee", style=discord.ButtonStyle.secondary, emoji="🏃")
    async def flee_button(self, interaction: discord.Interaction, button: Button):
        """Handle flee action"""
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your combat!", ephemeral=True)
        
        await self.process_flee(interaction)

    async def process_attack(self, interaction: discord.Interaction):
        """Process player attack"""
        current_mob = self.mobs[self.current_mob_index]
        self.player_is_defending = False
        
        # Check if mob is defending
        mob_defending = current_mob.get('is_defending', False)
        
        # Player attacks mob
        player_damage = self.calculate_damage(self.player_stats, current_mob["stats"])
        
        # Reduce damage if mob is defending
        if mob_defending:
            player_damage = max(1, player_damage // 2)
            self.combat_log.append(f"⚔️ You attack {current_mob['name']} for **{player_damage}** damage (reduced by defense)!")
            current_mob['is_defending'] = False  # Mob stops defending after being hit
        else:
            self.combat_log.append(f"⚔️ You attack {current_mob['name']} for **{player_damage}** damage!")
        
        current_mob["current_hp"] -= player_damage
        
        # Check if mob died
        if current_mob["current_hp"] <= 0:
            await self.handle_mob_defeated(interaction, current_mob)
            return
        
        # Mob's turn
        await self.process_mob_turn(interaction)

    async def process_defend(self, interaction: discord.Interaction):
        """Process player defend action"""
        current_mob = self.mobs[self.current_mob_index]
        self.player_is_defending = True
        
        # Gain focus for defending
        focus_gain = 15
        self.player_focus = min(100, self.player_focus + focus_gain)
        self.combat_log.append(f"🛡️ You brace for impact! Gained **{focus_gain}** focus.")
        
        # Mob's turn
        await self.process_mob_turn(interaction)

    async def process_mob_turn(self, interaction: discord.Interaction):
        """Process the mob's turn with AI behavior"""
        current_mob = self.mobs[self.current_mob_index]
        
        # Handle telegraphed attacks first
        if current_mob.get('telegraphed_attack'):
            turns_left = current_mob.get('telegraph_turns', 0) - 1
            current_mob['telegraph_turns'] = turns_left
            
            if turns_left <= 0:
                # Execute telegraphed attack
                await self.execute_telegraphed_attack(interaction, current_mob)
                return
            else:
                self.combat_log.append(f"⚡ {current_mob['name']} is charging {current_mob['telegraphed_attack']['name']}... ({turns_left} turns left)")
                # Mob doesn't do anything else while charging special attack
                await self.check_combat_status(interaction)
                return
        
        # Decide mob action based on behavior
        behavior = current_mob.get('behavior', 'aggressive')
        action_choice = random.random()
        
        # Behavior-based action probabilities
        if behavior == 'aggressive':
            defend_chance = 0.1  # 10% chance to defend
            special_attack_chance = 0.15  # 15% chance to start special attack
        elif behavior == 'ranged':
            defend_chance = 0.2  # 20% chance to defend  
            special_attack_chance = 0.25  # 25% chance to start special attack
        else:
            defend_chance = 0.3  # 30% chance to defend for other behaviors
            special_attack_chance = 0.1  # 10% chance to start special attack
        
        # Check if mob should start a special attack
        if action_choice < special_attack_chance and not current_mob.get('telegraphed_attack'):
            await self.start_mob_special_attack(interaction, current_mob)
            return
        
        # Check if mob should defend
        if action_choice < defend_chance + special_attack_chance:
            current_mob['is_defending'] = True
            self.combat_log.append(f"🛡️ {current_mob['name']} takes a defensive stance!")
            await self.check_combat_status(interaction)
            return
        
        # Default to normal attack
        await self.process_mob_attack(interaction)

    async def start_mob_special_attack(self, interaction: discord.Interaction, mob: Dict[str, Any]):
        """Start a telegraphed special attack for the mob"""
        special_attacks = mob.get('special_attacks', [])
        if not special_attacks:
            special_attack = {
                'name': 'Power Attack',
                'telegraph_turns': 1,
                'damage_multiplier': 2.0,
                'description': 'charges up a powerful attack!'
            }
        else:
            special_attack = random.choice(special_attacks)

        mob['telegraphed_attack'] = special_attack
        mob['telegraph_turns'] = special_attack['telegraph_turns']
        self.combat_log.append(f"⚡ {mob['name']} {special_attack['description']}")

        await self.check_combat_status(interaction)

    async def execute_telegraphed_attack(self, interaction: discord.Interaction, mob: Dict[str, Any]):
        """Execute a telegraphed special attack"""
        special_attack = mob['telegraphed_attack']
        base_damage = self.calculate_damage(mob["stats"], self.player_stats)
        special_damage = int(base_damage * special_attack['damage_multiplier'])
        
        # Check if player defended at the right time
        if self.player_is_defending:
            # Successful defend - greatly reduce damage
            special_damage = max(1, special_damage // 4)
            self.combat_log.append(f"💥 {mob['name']} uses **{special_attack['name']}** for **{special_damage}** damage (defended)!")
            # Gain extra focus for successfully defending a special attack
            focus_gain = 25
            self.player_focus = min(100, self.player_focus + focus_gain)
            self.combat_log.append(f"🎯 Well-timed defense! Gained **{focus_gain}** focus!")
        else:
            # Player didn't defend - full damage + potential stun
            special_damage = int(special_damage)
            self.combat_log.append(f"💥 {mob['name']} uses **{special_attack['name']}** for **{special_damage}** damage!")
            # 50% chance to stun if not defended
            if random.random() < 0.5:
                self.combat_log.append("😵 You are **stunned** and will be vulnerable next turn!")
                # Stun effect could be implemented here
        
        self.player_stats["current_hp"] -= special_damage
        # Update HP in database immediately
        await self.cog.update_player_hp(self.user_id, self.player_stats["current_hp"])
        
        mob['telegraphed_attack'] = None
        mob['telegraph_turns'] = 0
        
        await self.check_combat_status(interaction)

    async def process_mob_attack(self, interaction: discord.Interaction):
        """Process mob normal attack"""
        current_mob = self.mobs[self.current_mob_index]
        
        mob_damage = self.calculate_damage(current_mob["stats"], self.player_stats)
        
        # Check if player is defending
        if self.player_is_defending:
            mob_damage = max(1, mob_damage // 2)
            self.combat_log.append(f"👹 {current_mob['name']} attacks for **{mob_damage}** damage (reduced)!")
            # Gain focus for successful defense
            focus_gain = 10
            self.player_focus = min(100, self.player_focus + focus_gain)
        else:
            self.combat_log.append(f"👹 {current_mob['name']} attacks for **{mob_damage}** damage!")
        
        self.player_stats["current_hp"] -= mob_damage
        # Update HP in database immediately
        await self.cog.update_player_hp(self.user_id, self.player_stats["current_hp"])
        
        self.player_is_defending = False  # Reset defense after attack
        
        await self.check_combat_status(interaction)

    async def process_flee(self, interaction: discord.Interaction):
        """Process player flee action"""
        # Update HP in database before fleeing
        await self.cog.update_player_hp(self.user_id, self.player_stats["current_hp"])
        
        # 50% chance to flee successfully
        if random.random() < 0.5:
            self.combat_log.append("🏃 You successfully fled from combat!")
            await self.end_combat(interaction, victory=False, fled=True)
        else:
            self.combat_log.append("❌ Failed to flee!")
            
            # Mob gets a free attack
            current_mob = self.mobs[self.current_mob_index]
            mob_damage = self.calculate_damage(current_mob["stats"], self.player_stats)
            self.player_stats["current_hp"] -= mob_damage
            
            # Update HP in database after taking damage
            await self.cog.update_player_hp(self.user_id, self.player_stats["current_hp"])
            
            self.combat_log.append(f"👹 {current_mob['name']} attacks for **{mob_damage}** damage!")
            
            await self.check_combat_status(interaction)

    def calculate_damage(self, attacker_stats: Dict[str, Any], defender_stats: Dict[str, Any]) -> int:
        """Calculate damage between attacker and defender"""
        base_damage = max(1, attacker_stats["str"] - defender_stats["def"] // 2)
        
        # Add crit chance
        if hasattr(self, 'player_stats') and random.random() < self.player_stats.get("crit_chance", 0):
            base_damage *= 2
        
        return base_damage

    async def handle_mob_defeated(self, interaction: discord.Interaction, mob: Dict[str, Any]):
        """Handle when a mob is defeated"""
        dungeon_data = self.cog.active_dungeons.get(self.user_id)
        if not dungeon_data:
            return
        
        # Add rewards
        dungeon_data["score"] += 10
        gold_gain = random.randint(mob["gold"][0], mob["gold"][1])
        dungeon_data["gold"] += gold_gain
        
        self.combat_log.append(f"✅ {mob['name']} defeated! +10 score, +{gold_gain} gold")
        
        # Check for loot
        for loot_entry in mob.get("loot_table", []):
            if random.random() <= loot_entry["chance"]:
                item_name = loot_entry["item"]
                dungeon_data["loot"].append(item_name)
                self.combat_log.append(f"🎁 Found: {item_name}!")
        
        # Move to next mob or end combat
        self.current_mob_index += 1
        if self.current_mob_index >= len(self.mobs):
            await self.end_combat(interaction, victory=True)
        else:
            embed = self.create_combat_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    async def check_combat_status(self, interaction: discord.Interaction):
        """Check if combat should continue or end"""
        if self.player_stats["current_hp"] <= 0:
            self.combat_log.append("💀 You have been defeated!")
            await self.end_combat(interaction, victory=False)
        else:
            embed = self.create_combat_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    async def end_combat(self, interaction: discord.Interaction, victory: bool, fled: bool = False):
        """End the current combat"""
        dungeon_data = self.cog.active_dungeons.get(self.user_id)
        
        await self.cog.set_dungeon_status(self.user_id, False)
        
        if not dungeon_data:
            return
        
        if victory:
            # Move to next room
            dungeon_data["current_room"] += 1
            dungeon_data["player_stats"] = self.player_stats
            
            # Update original interaction's dungeon data
            self.cog.active_dungeons[self.user_id] = dungeon_data
            
            embed = discord.Embed(
                title="✅ Room Cleared!",
                description="Moving to next room...",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            
            # Start next room
            await self.cog.start_next_room(interaction, self.user_id)
            
        else:
            # Combat failed
            if fled:
                embed = discord.Embed(
                    title="🏃 Fled from Combat",
                    description="You escaped from the dungeon.",
                    color=discord.Color.orange()
                )
            else:
                embed = discord.Embed(
                    title="💀 Defeated",
                    description="You were defeated in combat.",
                    color=discord.Color.red()
                )
            
            # Clear dungeon data
            self.cog.active_dungeons.pop(self.user_id, None)
            await interaction.response.edit_message(embed=embed, view=None)

async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(DungeonCog(bot), guilds=[discord.Object(id=GUILD_ID)])