# cogs/inventory.py

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, Select

import json
# Load items manifest for names & emojis
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

ITEMS_PER_PAGE = 10


class InventoryView(View):
    """
    View that shows Prev/Next buttons (row 0) and a dropdown to switch between
    Inventory and Equipment pages (row 1).
    """

    def __init__(self, owner_id: int, inventory_pages: List[str], equipment_pages: List[str], timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        # store both sets of pages
        self._inventory_pages = inventory_pages or ["*(no inventory)*"]
        self._equipment_pages = equipment_pages or ["*(no equipment)*"]

        # start showing inventory
        self.mode = "inventory"
        self.pages = list(self._inventory_pages)
        self.current = 0
        self.total_pages = max(1, len(self.pages))

        # Prev / Next buttons row=0
        self.prev_button = Button(emoji="⬅️", style=discord.ButtonStyle.gray, row=0)
        self.next_button = Button(emoji="➡️", style=discord.ButtonStyle.gray, row=0)
        self.prev_button.callback = self._on_prev
        self.next_button.callback = self._on_next

        # initial disabled states
        self.prev_button.disabled = True
        self.next_button.disabled = (self.total_pages == 1)

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

        # Selector row=1 (appears below buttons)
        self.selector = Select(
            placeholder="Switch view...",
            options=[
                discord.SelectOption(label="Inventory", description="Your collectible items", value="inventory"),
                discord.SelectOption(label="Equipment", description="Your item instances / tools", value="equipment"),
            ],
            min_values=1,
            max_values=1,
            row=1
        )
        self.selector.callback = self._on_select
        self.add_item(self.selector)

    def _update_pages(self) -> None:
        """Set self.pages to the currently selected mode's pages and adjust controls."""
        if self.mode == "inventory":
            self.pages = list(self._inventory_pages)
        else:
            self.pages = list(self._equipment_pages)
        self.total_pages = max(1, len(self.pages))
        if self.current >= self.total_pages:
            self.current = self.total_pages - 1
        self.prev_button.disabled = (self.current == 0)
        self.next_button.disabled = (self.current >= self.total_pages - 1)

    def _current_content(self) -> str:
        if not self.pages:
            return "*(no items)*"
        return self.pages[self.current]

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the command user may use these buttons.", ephemeral=True)
        if self.current <= 0:
            return await interaction.response.defer()
        self.current -= 1
        self._update_pages()
        await interaction.response.edit_message(content=self._current_content(), view=self)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the command user may use these buttons.", ephemeral=True)
        if self.current >= self.total_pages - 1:
            return await interaction.response.defer()
        self.current += 1
        self._update_pages()
        await interaction.response.edit_message(content=self._current_content(), view=self)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the command user may switch views.", ephemeral=True)
        selected = interaction.data["values"][0]
        self.mode = selected
        # reset to first page when switching
        self.current = 0
        self._update_pages()
        await interaction.response.edit_message(content=self._current_content(), view=self)

    async def on_timeout(self) -> None:
        # disable all controls when the view times out
        for item in self.children:
            item.disabled = True


class InventoryCog(commands.Cog):
    """Shows your inventories with paging."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="inventory",
        description="View your inventory."
    )
    async def inventory(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # Fetch user data
        gen = await db.general.find_one({"id": user_id})
        inv = await db.inventory.find_one({"id": user_id})
        if not gen or not inv:
            return await interaction.response.send_message(
                "❌ You need to `/register` first.", ephemeral=True
            )

        max_slots = gen.get("maxInventory", 200)

        # Build inventory pages using shared helper
        from utils.pagination import build_inventory_pages, build_instance_pages

        inventory_pages = build_inventory_pages(inv_doc=inv, items_manifest=_items_data, max_slots=max_slots, items_per_page=ITEMS_PER_PAGE)

        # Build equipment/instance pages for the dropdown (so Inventory view can switch to Equipment)
        equip_doc = await db.equipment.find_one({"id": user_id})
        instances = equip_doc.get("instances", []) if equip_doc else []
        equipment_pages = build_instance_pages(instances, page_size=15, title="Instances")

        # Create the view with both sets of pages
        view = InventoryView(owner_id=user_id, inventory_pages=inventory_pages, equipment_pages=equipment_pages, timeout=120.0)
        first_page = view._current_content()

        # Send the initial inventory page and attach view
        page_msg = await interaction.response.send_message(content=first_page, view=view, ephemeral=False)
        # store the message on the view so on_timeout can edit it
        view.message = page_msg


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(InventoryCog(bot), guilds=[discord.Object(id=GUILD_ID)])
