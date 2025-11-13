import datetime
from pathlib import Path
from typing import Any, Dict

import discord
from discord import app_commands
from discord.ext import commands

# Load items manifest
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    import json
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

# Load item templates for instances
_ITEM_TEMPLATES_PATH = Path("data/itemTemplates.json")
_item_templates: Dict[str, Any] = {}
if _ITEM_TEMPLATES_PATH.exists():
    import json
    _item_templates = json.loads(_ITEM_TEMPLATES_PATH.read_text(encoding="utf-8"))

class InspectCog(commands.Cog):
    """Allows players to inspect items in their inventory or equipped tools/weapons."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def get_inventory(self, user_id: int) -> Dict[str, int]:
        """Fetch the user's inventory as a dictionary {item_name: quantity}."""
        db = self.bot.db
        inv_doc = await db.inventory.find_one({"id": user_id})
        return inv_doc if inv_doc else {}

    async def get_equipment(self, user_id: int) -> Dict[str, Any]:
        """Fetch user's equipment instances."""
        db = self.bot.db
        equip_doc = await db.equipment.find_one({"id": user_id})
        return equip_doc if equip_doc else {}

    @app_commands.command(
        name="inspect",
        description="🔍 Inspect an item in your inventory or your equipment instances."
    )
    @app_commands.describe(item_name="The item or instance ID you want to inspect.")
    async def inspect(self, interaction: discord.Interaction, item_name: str) -> None:
        db = self.bot.db
        user_id = interaction.user.id

        inventory = await self.get_inventory(user_id)
        equipment = await self.get_equipment(user_id)
        instances = equipment.get("instances", [])

        item_key = item_name.lower().replace(" ", "_")

        # First, check if the item exists in inventory
        if item_key in _items_data:
            quantity = inventory.get(item_key, 0)
            if quantity <= 0:
                return await interaction.response.send_message(
                    f"❌ You do not have any **{_items_data[item_key]['name'].title()}** in your inventory.", ephemeral=True
                )

            info = _items_data[item_key]
            lines = [
                f"🔹 **Name:** {info['name'].title()}",
                f"📝 **Description:** {info.get('description', 'No description available.')}\n",
                f"🗂 **Type:** {info['type'].title()}",
                f"🌟 **Rarity:** {info.get('rarity', 'Common').title()}",
                f"📦 **Quantity Owned:** {quantity}",
                f"⚡ **XP per Harvest:** {info.get('xp', 1)}"
            ]

            # Add related equipment instances of this template
            related_instances = [inst for inst in instances if inst.get("template", "").lower().replace(" ", "_") == item_key]
            if related_instances:
                lines.append("\n🛡 **Equipment Instances:**")
                for inst in related_instances:
                    inst_lines = [
                        f"  🔹 ID: {inst.get('instance_id')}",
                        f"    🌟 Tier: {inst.get('tier', 'Unknown').title()}"
                    ]
                    stats = inst.get("stats", {})
                    if stats:
                        stat_str = ", ".join(f"{k.upper()}: {v}" for k, v in stats.items())
                        inst_lines.append(f"    ⚡ Stats: {stat_str}")
                    equipped_slots = inst.get("equipped_in", [])
                    if equipped_slots:
                        inst_lines.append(f"    🟢 Equipped In: {', '.join(equipped_slots)}")
                    else:
                        inst_lines.append(f"    ⚪ Equipped: Not equipped")
                    lines.extend(inst_lines)

            formatted_text = "\n".join(lines)
            return await interaction.response.send_message(formatted_text, ephemeral=False)

        # If not in inventory, maybe it's an instance ID
        instance_match = next((inst for inst in instances if inst.get("instance_id") == item_name), None)
        if instance_match:
            tmpl = _item_templates.get(instance_match.get("template", ""), {})
            description = tmpl.get("description", "No description available.")
            inst_type = tmpl.get("type", "Unknown").title()
            inst_tier = instance_match.get("tier", "Unknown").title()

            lines = [
                f"🔹 **Instance ID:** {instance_match.get('instance_id')}",
                f"🛠 Name: {instance_match.get('template', 'Unknown')}",
                f"📝 Description: {description}\n",
                f"🗂 Type: {inst_type}",
                f"🌟 Tier: {inst_tier}"
            ]

            stats = instance_match.get("stats", {})
            if stats:
                stat_str = ", ".join(f"{k.upper()}: {v}" for k, v in stats.items())
                lines.append(f"⚡ Stats: {stat_str}")

            formatted_text = "\n".join(lines)
            return await interaction.response.send_message(formatted_text, ephemeral=False)

        # Neither inventory nor instance found
        return await interaction.response.send_message(
            f"❌ Item or instance '{item_name}' does not exist.", ephemeral=True
        )

async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(InspectCog(bot), guilds=[discord.Object(id=GUILD_ID)])