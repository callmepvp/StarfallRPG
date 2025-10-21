# cogs/features/equipment.py
from __future__ import annotations
import datetime
from typing import List, Dict, Any, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select

from settings import GUILD_ID

PAGE_SIZE = 10
INVENTORY_PAGE_SIZE = 10

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
                discord.SelectOption(label="Instances", description="Your equipment instances", value="instances"),
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EquipmentCog(bot), guilds=[discord.Object(id=GUILD_ID)])