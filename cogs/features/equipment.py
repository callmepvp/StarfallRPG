# cogs/features/equipment.py
from __future__ import annotations
import datetime
from typing import List, Dict, Any, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select

from pathlib import Path
import json

from settings import GUILD_ID

PAGE_SIZE = 10
INVENTORY_PAGE_SIZE = 10

_ITEM_TEMPLATES_PATH = Path("data/itemTemplates.json")
item_templates = {}
if _ITEM_TEMPLATES_PATH.exists():
    item_templates = json.loads(_ITEM_TEMPLATES_PATH.read_text(encoding="utf-8"))

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
    """Show equipped items + all item instances for a player, with paginated instance list."""

    ARMOR_SLOTS = [
        "head", "chest", "legs", "feet",
        "mainhand", "offhand",
        "accessory1", "accessory2",
    ]

    TOOL_SLOTS = [
        "fishingTool", "miningTool", "foragingTool", "farmingTool", "scavengingTool"
    ]

    SLOT_LABELS = {
        "head": "Head", "chest": "Chest", "legs": "Legs", "feet": "Feet",
        "mainhand": "Main Hand", "offhand": "Off Hand",
        "accessory1": "Accessory 1", "accessory2": "Accessory 2",
        "fishingTool": "Fishing Tool", "miningTool": "Mining Tool",
        "foragingTool": "Foraging Tool", "farmingTool": "Farming Tool",
        "scavengingTool": "Scavenging Tool"
    }

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _format_instance_line(self, inst: Dict[str, Any]) -> str:
        iid = inst.get("instance_id", "<no-id>")
        template = inst.get("template", "Unknown")
        custom = inst.get("custom_name")
        enchants = inst.get("enchants") or []
        name_part = template if not custom else f"{template} ({custom})"
        enchants_part = f" [enchants: {len(enchants)}]" if enchants else ""
        return f"`{iid}` — {name_part}{enchants_part}"

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

        # Build embed for equipped slots (UNCHANGED)
        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Equipment",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now()
        )

        for slot in self.ARMOR_SLOTS:
            label = self.SLOT_LABELS.get(slot, slot)
            iid = equip_doc.get(slot)
            if not iid:
                embed.add_field(name=label, value="*(empty)*", inline=True)
            else:
                inst = next((it for it in equip_doc.get("instances", []) if it.get("instance_id") == iid), None)
                if inst:
                    template = inst.get("template", "Unknown")
                    custom = inst.get("custom_name")
                    display = template if not custom else f"{template} ({custom})"
                    embed.add_field(name=label, value=f"{display}\n`{iid}`", inline=True)
                else:
                    embed.add_field(name=label, value=f"`{iid}` (missing)", inline=True)

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        for slot in self.TOOL_SLOTS:
            label = self.SLOT_LABELS.get(slot, slot)
            iid = equip_doc.get(slot)
            if not iid:
                embed.add_field(name=label, value="*(empty)*", inline=True)
            else:
                inst = next((it for it in equip_doc.get("instances", []) if it.get("instance_id") == iid), None)
                if inst:
                    template = inst.get("template", "Unknown")
                    custom = inst.get("custom_name")
                    display = template if not custom else f"{template} ({custom})"
                    embed.add_field(name=label, value=f"{display}\n`{iid}`", inline=True)
                else:
                    embed.add_field(name=label, value=f"`{iid}` (missing)", inline=True)

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
        
        # CHeck if alreay equipped
        for slot_name, slot_val in equip_doc.items():
            if slot_name in self.ARMOR_SLOTS + self.TOOL_SLOTS and slot_val == instance_id:
                return await interaction.response.send_message(
                    f"❌ This item (`{instance_id}`) is already equipped in **{self.SLOT_LABELS.get(slot_name, slot_name)}**.",
                    ephemeral=True
                )

        template_name = inst.get("template", "")
        template_data = item_templates.get(template_name)
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
            return await interaction.response.send_message(
                f"✅ Equipped `{template_name}` in **{self.SLOT_LABELS.get(slot_to_use, slot_to_use)}**.", ephemeral=True
            )
        elif len(empty_slots) == 0:
            return await interaction.response.send_message(
                f"❌ All allowed slots for `{template_name}` are occupied. Unequip one first.", ephemeral=True
            )
        else:
            # Multiple empty slots — ask user via dropdown
            class SlotSelect(discord.ui.Select):
                def __init__(self, slots: list[str], slot_labels: dict):
                    self.slot_labels = slot_labels
                    options = [
                        discord.SelectOption(label=self.slot_labels.get(slot, slot), value=slot)
                        for slot in slots
                    ]
                    super().__init__(placeholder="Choose a slot to equip", max_values=1, min_values=1, options=options)

                async def callback(self, interaction: discord.Interaction):
                    chosen_slot = self.values[0]  # ✅ Correctly access selected value
                    equip_doc[chosen_slot] = instance_id
                    await db.equipment.update_one({"id": user_id}, {"$set": {chosen_slot: instance_id}})
                    await interaction.response.edit_message(
                        content=f"✅ Equipped `{template_name}` in **{self.slot_labels.get(chosen_slot, chosen_slot)}**.",
                        view=None
                    )

            class SlotSelectView(discord.ui.View):
                def __init__(self, slots: list[str], slot_labels: dict, timeout=60):
                    super().__init__(timeout=timeout)
                    self.add_item(SlotSelect(slots, slot_labels))

            view = SlotSelectView(empty_slots, self.SLOT_LABELS)
            await interaction.response.send_message(
                f"⚠️ `{template_name}` can go into multiple slots. Choose one:",
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
                return await interaction.response.send_message(f"⚠️ Slot **{self.SLOT_LABELS.get(slot, slot)}** is already empty.", ephemeral=True)
            equip_doc[slot] = None
            await db.equipment.update_one({"id": user_id}, {"$set": {slot: None}})
            return await interaction.response.send_message(f"✅ Unequipped **{self.SLOT_LABELS.get(slot, slot)}**.", ephemeral=True)

        # Otherwise, treat as instance ID
        found_slot = None
        for s in self.TOOL_SLOTS + self.ARMOR_SLOTS:
            if equip_doc.get(s) == identifier:
                found_slot = s
                break
        if not found_slot:
            return await interaction.response.send_message(f"❌ No equipped item with ID `{identifier}` found.", ephemeral=True)

        equip_doc[found_slot] = None
        await db.equipment.update_one({"id": user_id}, {"$set": {found_slot: None}})
        await interaction.response.send_message(f"✅ Unequipped `{identifier}` from **{self.SLOT_LABELS.get(found_slot, found_slot)}**.", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EquipmentCog(bot), guilds=[discord.Object(id=GUILD_ID)])