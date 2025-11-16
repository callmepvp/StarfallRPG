# cogs/features/equipment.py
from __future__ import annotations
import datetime
from typing import List, Dict, Any, Optional
import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select

from settings import GUILD_ID

PAGE_SIZE = 10
INVENTORY_PAGE_SIZE = 10

# Load ALL template files for instanced items
_ITEM_TEMPLATES_PATH = Path("data/itemTemplates.json")
_ARMOR_TEMPLATES_PATH = Path("data/armorTemplates.json")
_SET_BONUSES_PATH = Path("data/setBonuses.json")

# Dictionary to hold ALL templates from all files
all_templates: Dict[str, Any] = {}

# Load item templates (weapons, tools)
if _ITEM_TEMPLATES_PATH.exists():
    item_templates = json.loads(_ITEM_TEMPLATES_PATH.read_text(encoding="utf-8"))
    all_templates.update(item_templates)

# Load armor templates
if _ARMOR_TEMPLATES_PATH.exists():
    armor_templates = json.loads(_ARMOR_TEMPLATES_PATH.read_text(encoding="utf-8"))
    all_templates.update(armor_templates)

# Load set bonuses
set_bonuses_config: Dict[str, Any] = {}
if _SET_BONUSES_PATH.exists():
    set_bonuses_config = json.loads(_SET_BONUSES_PATH.read_text(encoding="utf-8"))

class PaginationView(View):
    def __init__(
        self,
        owner_id: int,
        instances_pages: List[str],
        inventory_pages: List[str],
        timeout: float = 180.0
    ):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

        # store both page lists
        self._instances_pages = instances_pages or ["*(no instances)*"]
        self._inventory_pages = inventory_pages or ["*(no inventory)*"]

        # start showing instances by default
        self.mode = "instances"
        self.pages = list(self._instances_pages)
        self.page = 0
        self.message: Optional[discord.Message] = None
        self.total_pages = max(1, len(self.pages))

        # Prev / Next buttons (row 0)
        self.prev_button = Button(emoji="⬅️", style=discord.ButtonStyle.gray, row=0)
        self.next_button = Button(emoji="➡️", style=discord.ButtonStyle.gray, row=0)
        self.prev_button.callback = self.on_prev
        self.next_button.callback = self.on_next

        # Initially disable prev if on first page
        if self.page == 0:
            self.prev_button.disabled = True
        if self.total_pages <= 1:
            self.next_button.disabled = True

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

        # Selector to switch between Instances and Inventory (row 1 -> appears below buttons)
        self.selector = Select(
            placeholder="Choose view...",
            options=[
                discord.SelectOption(label="Equipment", description="Your equipment instances", value="instances"),
                discord.SelectOption(label="Inventory", description="Your inventory items", value="inventory"),
            ],
            min_values=1,
            max_values=1,
            row=1
        )
        self.selector.callback = self.on_select
        self.add_item(self.selector)

    def _update_pages_for_mode(self) -> None:
        if self.mode == "instances":
            self.pages = list(self._instances_pages)
        else:
            self.pages = list(self._inventory_pages)
        self.total_pages = max(1, len(self.pages))
        # clamp page and button states
        if self.page >= self.total_pages:
            self.page = self.total_pages - 1
        self.prev_button.disabled = (self.page == 0)
        self.next_button.disabled = (self.page >= self.total_pages - 1)

    def _current_content(self) -> str:
        if not self.pages:
            return "*(no items)*"
        # header already included in pages entries
        return self.pages[self.page]

    async def on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the command user may switch lists.", ephemeral=True)

        selected = interaction.data["values"][0]
        self.mode = selected
        # reset to first page when switching
        self.page = 0
        self._update_pages_for_mode()
        await interaction.response.edit_message(content=self._current_content(), view=self)

    async def on_prev(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the command user may use these buttons.", ephemeral=True)
        if self.page <= 0:
            return await interaction.response.defer()
        self.page -= 1
        self._update_pages_for_mode()
        await interaction.response.edit_message(content=self._current_content(), view=self)

    async def on_next(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the command user may use these buttons.", ephemeral=True)
        if self.page >= self.total_pages - 1:
            return await interaction.response.defer()
        self.page += 1
        self._update_pages_for_mode()
        await interaction.response.edit_message(content=self._current_content(), view=self)

    async def on_timeout(self) -> None:
        # disable all controls
        for item in self.children:
            item.disabled = True


class EquipmentCog(commands.Cog):
    """Show equipped items + all owned item instances (paginated)."""

    ARMOR_SLOTS = [
        "head", "chest", "legs", "feet", "gloves"
    ]

    WEAPON_SLOTS = [
        "mainHand", "offHand"
    ]

    ACCESSORY_SLOTS = [
        "talisman1", "talisman2", "talisman3",
        "charm1", "charm2",
        "ring1", "ring2", "amulet"
    ]

    TOOL_SLOTS = [
        "fishingTool", "miningTool", "foragingTool", "farmingTool", "scavengingTool"
    ]

    # Combine all equipment slots
    ALL_EQUIPMENT_SLOTS = ARMOR_SLOTS + WEAPON_SLOTS + ACCESSORY_SLOTS + TOOL_SLOTS

    SLOT_LABELS = {
        # Armor slots
        "head": "Head", "chest": "Chest", "legs": "Legs", 
        "feet": "Feet", "gloves": "Gloves",
        # Weapon slots
        "mainHand": "Main Hand", "offHand": "Off Hand",
        # Accessory slots
        "talisman1": "Talisman 1", "talisman2": "Talisman 2", "talisman3": "Talisman 3",
        "charm1": "Charm 1", "charm2": "Charm 2",
        "ring1": "Ring 1", "ring2": "Ring 2", "amulet": "Amulet",
        # Tool slots
        "fishingTool": "Fishing Tool", "miningTool": "Mining Tool",
        "foragingTool": "Foraging Tool", "farmingTool": "Farming Tool",
        "scavengingTool": "Scavenging Tool"
    }

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _calculate_total_hp_bonus(self, user_id: int) -> int:
        """Calculate total HP bonus from armor pieces and set bonuses."""
        db = getattr(self.bot, "db", None)
        if not db:
            return 0
            
        equip_doc = await db.equipment.find_one({"id": user_id})
        if not equip_doc:
            return 0
        
        total_hp_bonus = 0
        
        # 1. Calculate HP from individual armor pieces
        for slot in self.ARMOR_SLOTS:
            instance_id = equip_doc.get(slot)
            if instance_id:
                instance = next((inst for inst in equip_doc.get("instances", []) 
                               if inst.get("instance_id") == instance_id), None)
                if instance and instance.get("stats", {}).get("HP"):
                    total_hp_bonus += instance["stats"]["HP"]
        
        # 2. Calculate HP from set bonuses
        set_counts = {}
        for slot in self.ARMOR_SLOTS:
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
                    total_hp_bonus += threshold_bonuses.get("HP", 0)
        
        return total_hp_bonus

    async def _update_player_hp(self, user_id: int) -> None:
        """Update player's maxHP and current HP based on equipment bonuses."""
        db = getattr(self.bot, "db", None)
        if not db:
            return
            
        # Calculate total HP bonus
        hp_bonus = await self._calculate_total_hp_bonus(user_id)
        
        # Get current player data
        player_data = await db.general.find_one({"id": user_id})
        if not player_data:
            return
            
        current_hp = player_data.get("hp", 100)
        base_max_hp = 100  # Base max HP without equipment
        
        new_max_hp = base_max_hp + hp_bonus
        
        # Ensure HP doesn't drop below 1
        if current_hp > new_max_hp:
            current_hp = new_max_hp
        if current_hp <= 0:
            current_hp = 1
            
        # Update player data
        await db.general.update_one(
            {"id": user_id},
            {"$set": {
                "maxHP": new_max_hp,
                "hp": current_hp
            }}
        )

    def _format_instance_line(self, inst: Dict[str, Any]) -> str:
        iid = inst.get("instance_id", "<no-id>")
        template = inst.get("template", "Unknown")
        custom = inst.get("custom_name")
        enchants = inst.get("enchants") or []
        name_part = template if not custom else f"{template} ({custom})"
        enchants_part = f" [enchants: {len(enchants)}]" if enchants else ""
        
        # Add item type and set info if available
        item_type = inst.get("type", "unknown")
        set_info = inst.get("set")
        type_part = f" [{item_type}]" if item_type != "unknown" else ""
        set_part = f" [{set_info}]" if set_info else ""
        
        return f"`{iid}` — {name_part}{type_part}{set_part}{enchants_part}"

    async def _calculate_set_bonuses(self, user_id: int) -> Dict[str, Any]:
        """Calculate active set bonuses from equipped armor"""
        db = getattr(self.bot, "db", None)
        if not db:
            return {}
            
        equip_doc = await db.equipment.find_one({"id": user_id})
        if not equip_doc:
            return {}
        
        # Count pieces per set from equipped armor
        set_counts = {}
        for slot in self.ARMOR_SLOTS:
            instance_id = equip_doc.get(slot)
            if instance_id:
                instance = next((inst for inst in equip_doc.get("instances", []) 
                               if inst.get("instance_id") == instance_id), None)
                if instance and instance.get("set"):
                    set_name = instance["set"]
                    set_counts[set_name] = set_counts.get(set_name, 0) + 1
        
        #! NB! The equipment command will NOT apply set bonuses, just show counts
        return set_counts

    @app_commands.command(
        name="equipment",
        description="View your equipped gear and all owned item instances (paginated)."
    )
    async def equipment(self, interaction: discord.Interaction) -> None:
        db = getattr(self.bot, "db", None)
        if db is None:
            return await interaction.response.send_message(
                "❌ Database is not configured on this bot.", ephemeral=True
            )

        user_id = interaction.user.id

        # Fetch player's equipment document
        equip_doc = await db.equipment.find_one({"id": user_id})
        if not equip_doc:
            return await interaction.response.send_message(
                "❌ No equipment profile found — you probably need to `/register`.", ephemeral=True
            )

        # Calculate set bonuses
        set_bonuses = await self._calculate_set_bonuses(user_id)

        # Build embed for equipped slots - using combined fields to avoid field limit
        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Equipment",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now()
        )

        # Helper function to format equipment lines
        def format_equipment_section(slots):
            lines = []
            for slot in slots:
                label = self.SLOT_LABELS.get(slot, slot)
                iid = equip_doc.get(slot)
                if not iid:
                    lines.append(f"**{label}:** *(empty)*")
                else:
                    inst = next((it for it in equip_doc.get("instances", []) if it.get("instance_id") == iid), None)
                    if inst:
                        template = inst.get("template", "Unknown")
                        custom = inst.get("custom_name")
                        display = template if not custom else f"{template} ({custom})"
                        lines.append(f"**{label}:** {display}\n`{iid}`")
                    else:
                        lines.append(f"**{label}:** `{iid}` (missing)")
            return "\n".join(lines)

        # Armor section - all in one field
        armor_text = format_equipment_section(self.ARMOR_SLOTS)
        embed.add_field(name="🛡️ Armor", value=armor_text, inline=False)

        # Weapons section - all in one field
        weapons_text = format_equipment_section(self.WEAPON_SLOTS)
        embed.add_field(name="⚔️ Weapons", value=weapons_text, inline=False)

        # Accessories section - split into two fields to avoid too much text
        accessory_slots_part1 = self.ACCESSORY_SLOTS[:4]  # First 4 accessories
        accessory_slots_part2 = self.ACCESSORY_SLOTS[4:]  # Remaining accessories
        
        accessories_text1 = format_equipment_section(accessory_slots_part1)
        accessories_text2 = format_equipment_section(accessory_slots_part2)
        
        embed.add_field(name="💎 Accessories", value=accessories_text1, inline=True)
        embed.add_field(name="\u200b", value=accessories_text2, inline=True)

        # Tools section - all in one field
        tools_text = format_equipment_section(self.TOOL_SLOTS)
        embed.add_field(name="🛠️ Tools", value=tools_text, inline=False)

        # Add set bonuses if any
        if set_bonuses:
            set_bonus_text = []
            for set_name, count in set_bonuses.items():
                set_bonus_text.append(f"**{set_name}**: {count}/5 pieces")
            embed.add_field(name="🎯 Active Set Bonuses", value="\n".join(set_bonus_text), inline=False)

        await interaction.response.send_message(embed=embed)

        # Prepare paginated pages with the helper
        from utils.pagination import build_instance_pages, build_inventory_pages
        instances = equip_doc.get("instances", []) or []
        instance_pages = build_instance_pages(instances, page_size=PAGE_SIZE, title="Instances")

        # inventory pages: fetch inv doc and build pages
        inv_doc = await db.inventory.find_one({"id": user_id})

        import json
        from pathlib import Path
        _ITEMS_PATH = Path("data/items.json")
        _items_data = {}
        if _ITEMS_PATH.exists():
            _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

        max_slots = (await db.general.find_one({"id": user_id})).get("maxInventory", 200)
        inventory_pages = build_inventory_pages(inv_doc=inv_doc, items_manifest=_items_data, max_slots=max_slots, items_per_page=INVENTORY_PAGE_SIZE)

        view = PaginationView(owner_id=user_id, instances_pages=instance_pages, inventory_pages=inventory_pages, timeout=180.0)
        first_page_content = view._current_content()

        # Send the paginated plaintext as a followup and store the message on the view
        page_msg = await interaction.followup.send(content=first_page_content, view=view, ephemeral=False)
        view.message = page_msg

    #### EQUIPPING COMMANDS
    @app_commands.command(
        name="equip",
        description="Equip an item using its instance ID."
    )
    @app_commands.describe(instance_id="The instance ID of the item you want to equip")
    async def equip(self, interaction: discord.Interaction, instance_id: str):
        db = getattr(self.bot, "db", None)
        if db is None:
            return await interaction.response.send_message("❌ Database not available.", ephemeral=True)

        user_id = interaction.user.id
        equip_doc = await db.equipment.find_one({"id": user_id})
        if not equip_doc:
            return await interaction.response.send_message("❌ No equipment profile found. Try `/register`.", ephemeral=True)

        # Find instance
        inst = next((it for it in equip_doc.get("instances", []) if it.get("instance_id") == instance_id), None)
        if not inst:
            return await interaction.response.send_message(
                f"❌ No item with ID `{instance_id}` found in your inventory.", ephemeral=True
            )
        
        # Check if already equipped
        for slot_name in self.ALL_EQUIPMENT_SLOTS:
            if equip_doc.get(slot_name) == instance_id:
                slot_label = self.SLOT_LABELS.get(slot_name, slot_name)
                return await interaction.response.send_message(
                    f"❌ This item (`{instance_id}`) is already equipped in **{slot_label}**.",
                    ephemeral=True
                )

        template_name = inst.get("template", "")
        template_data = all_templates.get(template_name)  # Use combined templates
        if not template_data:
            return await interaction.response.send_message(
                f"❌ Template `{template_name}` not found in item templates.", ephemeral=True
            )

        allowed_slots: list = template_data.get("equip_slots", [])
        if not allowed_slots:
            return await interaction.response.send_message(
                f"❌ `{template_name}` cannot be equipped in any slot.", ephemeral=True
            )

        empty_slots = [slot for slot in allowed_slots if not equip_doc.get(slot)]
        if len(empty_slots) == 1:
            # Only one empty slot, equip automatically
            slot_to_use = empty_slots[0]
            equip_doc[slot_to_use] = instance_id
            await db.equipment.update_one({"id": user_id}, {"$set": {slot_to_use: instance_id}})
            
            # Update HP if this is an armor piece
            if slot_to_use in self.ARMOR_SLOTS:
                await self._update_player_hp(user_id)
                
            slot_label = self.SLOT_LABELS.get(slot_to_use, slot_to_use)
            return await interaction.response.send_message(
                f"✅ Equipped `{template_name}` in **{slot_label}**.", ephemeral=True
            )
        elif len(empty_slots) == 0:
            slot_labels = [self.SLOT_LABELS.get(slot, slot) for slot in allowed_slots]
            return await interaction.response.send_message(
                f"❌ All allowed slots for `{template_name}` are occupied. Allowed slots: {', '.join(slot_labels)}. Unequip one first.", 
                ephemeral=True
            )
        else:
            # Multiple empty slots — ask user via dropdown
            class SlotSelect(discord.ui.Select):
                def __init__(self, slots: list[str], slot_labels: dict, cog: EquipmentCog, user_id: int):
                    self.slot_labels = slot_labels
                    self.cog = cog
                    self.user_id = user_id
                    options = [
                        discord.SelectOption(label=self.slot_labels.get(slot, slot), value=slot)
                        for slot in slots
                    ]
                    super().__init__(placeholder="Choose a slot to equip", max_values=1, min_values=1, options=options)

                async def callback(self, interaction: discord.Interaction):
                    chosen_slot = self.values[0]
                    equip_doc[chosen_slot] = instance_id
                    await db.equipment.update_one({"id": user_id}, {"$set": {chosen_slot: instance_id}})
                    
                    # Update HP if this is an armor piece
                    if chosen_slot in self.cog.ARMOR_SLOTS:
                        await self.cog._update_player_hp(self.user_id)
                        
                    slot_label = self.slot_labels.get(chosen_slot, chosen_slot)
                    await interaction.response.edit_message(
                        content=f"✅ Equipped `{template_name}` in **{slot_label}**.",
                        view=None
                    )

            class SlotSelectView(discord.ui.View):
                def __init__(self, slots: list[str], slot_labels: dict, cog: EquipmentCog, user_id: int, timeout=60):
                    super().__init__(timeout=timeout)
                    self.add_item(SlotSelect(slots, slot_labels, cog, user_id))

            view = SlotSelectView(empty_slots, self.SLOT_LABELS, self, user_id)
            slot_labels = [self.SLOT_LABELS.get(slot, slot) for slot in allowed_slots]
            await interaction.response.send_message(
                f"⚠️ `{template_name}` can go into multiple slots: {', '.join(slot_labels)}. Choose one:",
                view=view,
                ephemeral=True
            )

    @app_commands.command(
        name="unequip",
        description="Unequip an item either by instance ID or slot name.")
    @app_commands.describe(identifier="Either the instance ID or the slot name to unequip")
    async def unequip(self, interaction: discord.Interaction, identifier: str):
        db = getattr(self.bot, "db", None)
        if db is None:
            return await interaction.response.send_message("❌ Database not available.", ephemeral=True)

        user_id = interaction.user.id
        equip_doc = await db.equipment.find_one({"id": user_id})
        if not equip_doc:
            return await interaction.response.send_message("❌ No equipment profile found. Try `/register`.", ephemeral=True)

        identifier_lower = identifier.lower()

        # First check if identifier matches a slot name
        slot_map = {label.lower(): slot for slot, label in self.SLOT_LABELS.items()}
        if identifier_lower in slot_map:
            slot = slot_map[identifier_lower]
            if not equip_doc.get(slot):
                slot_label = self.SLOT_LABELS.get(slot, slot)
                return await interaction.response.send_message(f"⚠️ Slot **{slot_label}** is already empty.", ephemeral=True)
            
            # Get item name for better feedback
            instance_id = equip_doc.get(slot)
            instance = next((it for it in equip_doc.get("instances", []) if it.get("instance_id") == instance_id), None)
            item_name = instance.get("template", "Unknown") if instance else "Unknown"
            
            equip_doc[slot] = None
            await db.equipment.update_one({"id": user_id}, {"$set": {slot: None}})
            
            # Update HP if this was an armor piece
            if slot in self.ARMOR_SLOTS:
                await self._update_player_hp(user_id)
                
            slot_label = self.SLOT_LABELS.get(slot, slot)
            return await interaction.response.send_message(f"✅ Unequipped **{item_name}** from **{slot_label}**.", ephemeral=True)

        # Otherwise, treat as instance ID
        found_slot = None
        found_instance = None
        for slot in self.ALL_EQUIPMENT_SLOTS:
            if equip_doc.get(slot) == identifier:
                found_slot = slot
                found_instance = next((it for it in equip_doc.get("instances", []) if it.get("instance_id") == identifier), None)
                break
        
        if not found_slot:
            return await interaction.response.send_message(f"❌ No equipped item with ID `{identifier}` found.", ephemeral=True)

        item_name = found_instance.get("template", "Unknown") if found_instance else "Unknown"
        equip_doc[found_slot] = None
        await db.equipment.update_one({"id": user_id}, {"$set": {found_slot: None}})
        
        # Update HP if this was an armor piece
        if found_slot in self.ARMOR_SLOTS:
            await self._update_player_hp(user_id)
            
        slot_label = self.SLOT_LABELS.get(found_slot, found_slot)
        await interaction.response.send_message(f"✅ Unequipped **{item_name}** (`{identifier}`) from **{slot_label}**.", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EquipmentCog(bot), guilds=[discord.Object(id=GUILD_ID)])