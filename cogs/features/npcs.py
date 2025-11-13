import json
from pathlib import Path
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select

_NPCS_PATH = Path("data/quests/npcs.json")
_npcs_data: Dict[str, dict] = {}
if _NPCS_PATH.exists():
    _npcs_data = json.loads(_NPCS_PATH.read_text(encoding="utf-8"))


# --------------------------
# NPC Dialogue System
# --------------------------
class NPCDialogueView(View):
    """Interactive dialogue for NPCs with buttons for options and shops."""

    def __init__(self, npc_data: dict, user_id: int):
        super().__init__(timeout=None)
        self.npc_data = npc_data
        self.user_id = user_id
        self.current_node_key = "start"
        self.update_buttons_for_node(self.current_node_key)

    def update_buttons_for_node(self, node_key: str):
        """Clear buttons and create new ones based on the dialogue node."""
        self.clear_items()
        node = self.npc_data.get("dialogue", {}).get(node_key)
        if not node:
            return
        for option in node.get("options", []):
            label = option.get("label", "???")
            if option.get("action") == "shop":
                self.add_item(Button(label=label, style=discord.ButtonStyle.green, custom_id=f"shop:{node_key}"))
            else:
                next_node = option.get("next", "")
                self.add_item(Button(label=label, style=discord.ButtonStyle.blurple, custom_id=f"node:{next_node}"))

        # Add end conversation button
        self.add_item(Button(label="End Conversation", style=discord.ButtonStyle.red, custom_id="end"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # restrict to the user who opened the dialogue
        return interaction.user.id == self.user_id

    async def on_timeout(self):
        # optional cleanup if needed
        pass

    @discord.ui.button(label="placeholder", style=discord.ButtonStyle.secondary, custom_id="placeholder", disabled=True)
    async def dummy(self, button: Button, interaction: discord.Interaction):
        # placeholder so View doesn't error out if empty
        pass

    async def button_callback(self, interaction: discord.Interaction, custom_id: str):
        if custom_id == "end":
            await interaction.response.edit_message(content="You end the conversation.", embed=None, view=None)
            self.stop()
            return

        if custom_id.startswith("node:"):
            next_node = custom_id.split(":", 1)[1]
            node = self.npc_data.get("dialogue", {}).get(next_node)
            if not node:
                await interaction.response.send_message("Dialogue node missing.", ephemeral=True)
                return
            embed = discord.Embed(
                title=self.npc_data.get("name", "NPC"),
                description=node.get("text", ""),
                color=discord.Color.gold()
            )
            self.current_node_key = next_node
            self.update_buttons_for_node(next_node)
            await interaction.response.edit_message(embed=embed, view=self)
        elif custom_id.startswith("shop:"):
            # placeholder shop handling
            embed = discord.Embed(
                title=f"{self.npc_data.get('name', 'NPC')} Shop",
                description="🛒 Shop coming soon! Placeholder for items.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class TalkSelect(Select):
    """Dropdown to select an NPC from the current subarea."""

    def __init__(self, npcs_here: Dict[str, dict], user_id: int):
        options = [discord.SelectOption(label=npc["name"], value=npc_id) for npc_id, npc in npcs_here.items()]
        super().__init__(placeholder="Choose an NPC to talk to...", min_values=1, max_values=1, options=options)
        self.npcs_here = npcs_here
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        npc_id = self.values[0]
        npc_data = self.npcs_here[npc_id]
        start_node = npc_data.get("dialogue", {}).get("start", {})
        embed = discord.Embed(
            title=npc_data.get("name", "NPC"),
            description=start_node.get("text", ""),
            color=discord.Color.gold()
        )
        view = NPCDialogueView(npc_data, interaction.user.id)
        # Attach callback for buttons dynamically
        for btn in view.children:
            btn.callback = lambda inter, cid=btn.custom_id: view.button_callback(inter, cid)
        await interaction.response.edit_message(embed=embed, view=view)


class TalkDropdownView(View):
    def __init__(self, npcs_here: Dict[str, dict], user_id: int):
        super().__init__(timeout=None)
        self.add_item(TalkSelect(npcs_here, user_id))


# --------------------------
# NPCCog for /talk
# --------------------------
class NPCCog(commands.Cog):
    """Talk to NPCs in your current subarea."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="talk", description="Talk to NPCs in your current subarea.")
    async def talk(self, interaction: discord.Interaction):
        db = self.bot.db
        user_id = interaction.user.id
        area_doc = await db.areas.find_one({"id": user_id})
        if not area_doc:
            return await interaction.response.send_message("❌ Can't determine your location.", ephemeral=True)

        current_sub = area_doc.get("currentSubarea")
        npcs_here = {nid: data for nid, data in _npcs_data.items() if data.get("sub_area") == current_sub}
        if not npcs_here:
            return await interaction.response.send_message("ℹ️ There are no NPCs here to talk to.", ephemeral=True)

        view = TalkDropdownView(npcs_here, user_id)
        await interaction.response.send_message("Choose an NPC to talk to:", view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    from settings import GUILD_ID
    await bot.add_cog(NPCCog(bot), guilds=[discord.Object(id=GUILD_ID)])