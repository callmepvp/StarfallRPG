# cogs/inventory.py

import math
from pathlib import Path
from typing import Any, Dict, List

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View

import json
# Load items manifest for names & emojis
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

ITEMS_PER_PAGE = 10  # adjust as desired

class InventoryView(View):
    def __init__(self, pages: List[str]):
        super().__init__(timeout=120.0)
        self.pages = pages
        self.current = 0
        # Disable prev on first page
        self.prev_button.disabled = True
        # Disable next if only one page
        self.next_button.disabled = len(pages) == 1

    @discord.ui.button(label="⏪ Prev", style=discord.ButtonStyle.gray)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        self.current -= 1
        self.next_button.disabled = False
        if self.current == 0:
            button.disabled = True
        await interaction.response.edit_message(content=self.pages[self.current], view=self)

    @discord.ui.button(label="Next ⏩", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        self.current += 1
        self.prev_button.disabled = False
        if self.current == len(self.pages) - 1:
            button.disabled = True
        await interaction.response.edit_message(content=self.pages[self.current], view=self)


class InventoryCog(commands.Cog):
    """Shows your inventory with paging."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="inventory",
        description="📦 View your inventory (paged)."
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
        # Filter out metadata fields
        item_entries = [
            (k, inv[k]) for k in inv.keys()
            if k not in ("_id", "id") and isinstance(inv[k], int) and inv[k] > 0
        ]
        if not item_entries:
            return await interaction.response.send_message(
                "📭 Your inventory is empty!", ephemeral=True
            )

        # Build lines
        lines: List[str] = []
        for key, qty in sorted(item_entries):
            emoji = _items_data.get(key, {}).get("emoji", "")
            name = _items_data.get(key, {}).get("name", key).title()
            lines.append(f"{qty} x {name} {emoji}".strip())

        # Paginate
        pages: List[str] = []
        total_pages = math.ceil(len(lines) / ITEMS_PER_PAGE)
        for p in range(total_pages):
            start = p * ITEMS_PER_PAGE
            end = start + ITEMS_PER_PAGE
            page_lines = lines[start:end]
            header = f"**Inventory** — {len(lines):,}/{max_slots:,} slots — Page {p+1}/{total_pages}\n\n"
            pages.append(header + "\n".join(page_lines))

        view = InventoryView(pages)
        await interaction.response.send_message(content=pages[0], view=view, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(InventoryCog(bot), guilds=[discord.Object(id=GUILD_ID)])
