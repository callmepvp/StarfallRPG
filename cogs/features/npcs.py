# cogs/features/npcs.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select, Button

_NPCS_PATH = Path("data/quests/npcs.json")
_npcs_data: Dict[str, Dict[str, Any]] = {}
if _NPCS_PATH.exists():
    try:
        _npcs_data = json.loads(_NPCS_PATH.read_text(encoding="utf-8"))
    except Exception:
        _npcs_data = {}

class NPCDialogueView(View):
    def __init__(self, npc_id: str, npc_data: Dict[str, Any], user_id: int, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.npc_id = npc_id
        self.npc_data = npc_data
        self.user_id = user_id
        self.current_node: str = "start" if "start" in npc_data.get("dialogue", {}) else next(iter(npc_data.get("dialogue", {})), None)
        if self.current_node is None:
            raise ValueError("NPC has no dialogue nodes")
        self._rebuild_buttons_for_node(self.current_node)

    def _clear_buttons(self):
        for child in list(self.children):
            self.remove_item(child)

    def _rebuild_buttons_for_node(self, node_key: str) -> None:
        self._clear_buttons()
        node = self.npc_data.get("dialogue", {}).get(node_key, {})
        options = node.get("options", [])

        for opt in options:
            label = opt.get("label", "…")

            # --- Quest Button ---
            if opt.get("action") == "give_quest" and "quest_id" in opt:
                quest_id = opt["quest_id"]
                btn = Button(label=label, style=discord.ButtonStyle.success)

                async def quest_cb(inter: discord.Interaction, qid=quest_id, _btn=btn):
                    quest_cog = inter.client.get_cog("QuestCog")
                    if not quest_cog:
                        return await inter.response.send_message("❌ Quest system unavailable.", ephemeral=True)

                    tpl = await quest_cog.get_template(quest_id)
                    quest_title = tpl.get("title", quest_id) if tpl else quest_id

                    success = await quest_cog.accept_for_player(inter.user.id, quest_id)
                    if success:
                        # Disable the button so it cannot be clicked again
                        _btn.disabled = True
                        await inter.response.edit_message(view=self)
                        await inter.followup.send(f"🟢 Quest accepted: **{quest_title}**", ephemeral=True)
                    else:
                        await inter.response.send_message(f"⚠️ You already have or completed the quest **{quest_title}**.", ephemeral=True)

                btn.callback = quest_cb
                self.add_item(btn)
                continue

            next_node = opt.get("next")
            if not next_node or next_node.lower() == "end":
                btn = Button(label=label, style=discord.ButtonStyle.secondary)
                async def end_cb(inter: discord.Interaction, _opt=opt):
                    final_text = _opt.get("text", "Farewell, traveler.")
                    embed = discord.Embed(
                        title=self.npc_data.get("name", "NPC"),
                        description=final_text,
                        color=discord.Color.dark_gold()
                    )
                    await inter.response.edit_message(embed=embed, view=None)
                    self.stop()
                btn.callback = end_cb
                self.add_item(btn)
            else:
                btn = Button(label=label, style=discord.ButtonStyle.primary)
                async def next_cb(inter: discord.Interaction, _next=next_node):
                    node_dict = self.npc_data.get("dialogue", {}).get(_next)
                    if not node_dict:
                        await inter.response.send_message("⚠️ Dialogue node missing.", ephemeral=True)
                        return
                    self.current_node = _next
                    self._rebuild_buttons_for_node(_next)
                    description = node_dict.get("text", "")
                    lore = node_dict.get("lore")
                    if lore:
                        description += f"\n\n{lore}"
                    embed = discord.Embed(
                        title=self.npc_data.get("name", "NPC"),
                        description=description,
                        color=discord.Color.gold()
                    )
                    await inter.response.edit_message(embed=embed, view=self)
                btn.callback = next_cb
                self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def on_timeout(self) -> None:
        pass

class TalkSelect(Select):
    def __init__(self, npcs_here: Dict[str, Dict[str, Any]], user_id: int):
        options = [discord.SelectOption(label=data.get("name", nid), value=nid) for nid, data in npcs_here.items()]
        super().__init__(placeholder="So many options...", min_values=1, max_values=1, options=options)
        self.npcs_here = npcs_here
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        npc_id = self.values[0]
        npc_data = self.npcs_here.get(npc_id)
        if not npc_data:
            return await interaction.response.send_message("❌ NPC data missing.", ephemeral=True)

        start_node_key = "start" if "start" in npc_data.get("dialogue", {}) else next(iter(npc_data.get("dialogue", {})), None)
        node = npc_data.get("dialogue", {}).get(start_node_key, {})
        description = node.get("text", "")
        lore = node.get("lore")
        if lore:
            description += f"\n\n{lore}"
        embed = discord.Embed(
            title=npc_data.get("name", "NPC"),
            description=description,
            color=discord.Color.gold()
        )

        view = NPCDialogueView(npc_id, npc_data, self.user_id)
        await interaction.response.edit_message(embed=embed, view=view)

        # Quest Integration
        try:
            quest_cog = interaction.client.get_cog("QuestCog")
            if quest_cog:
                completed_quests = await quest_cog.update_progress(self.user_id, "talk", npc_id, amount=1)

                if completed_quests:
                    # Notify completed quests
                    msg_lines = []
                    newly_unlocked = []
                    for q in completed_quests:
                        tpl = q.get("template", {})
                        title = tpl.get("title", "Unknown Quest")
                        msg_lines.append(f"✅ Quest '{title}' completed!")

                        # Check next_quest
                        next_q = tpl.get("next_quest")
                        if next_q:
                            unlocked_tpl = await quest_cog.get_template(next_q)
                            if unlocked_tpl:
                                newly_unlocked.append(f"🟡 New quest unlocked: '{unlocked_tpl.get('title','Unknown')}'")

                    if msg_lines or newly_unlocked:
                        await interaction.followup.send("\n".join(msg_lines + newly_unlocked), ephemeral=True)

        except Exception:
            pass

class TalkDropdownView(View):
    def __init__(self, npcs_here: Dict[str, Dict[str, Any]], user_id: int):
        super().__init__(timeout=120.0)
        self.add_item(TalkSelect(npcs_here, user_id))

class NPCCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="talk", description="Talk to NPCs in your current subarea.")
    async def talk(self, interaction: discord.Interaction) -> None:
        db = self.bot.db
        user_id = interaction.user.id

        player = await db.general.find_one({"id": user_id})
        if not player:
            return await interaction.response.send_message(
                "❌ You need to `/register` before you can talk to NPCs!", 
                ephemeral=True
            )

        if player.get("inDungeon", False):
            return await interaction.response.send_message(
                "❌ You can't talk to NPCs while in a dungeon! Complete or flee from your dungeon first.",
                ephemeral=True
            )

        area_doc = await db.areas.find_one({"id": user_id})
        if not area_doc:
            return await interaction.response.send_message("❌ Can't determine your location.", ephemeral=True)

        current_sub = area_doc.get("currentSubarea")
        if not current_sub:
            return await interaction.response.send_message("❌ You are not in a valid subarea.", ephemeral=True)

        npcs_here = {nid: n for nid, n in _npcs_data.items() if n.get("sub_area") == current_sub}
        if not npcs_here:
            return await interaction.response.send_message("ℹ️ There are no NPCs here to talk to.", ephemeral=True)

        view = TalkDropdownView(npcs_here, user_id)
        await interaction.response.send_message("Choose an NPC to speak to:", view=view, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(NPCCog(bot), guilds=[discord.Object(id=GUILD_ID)])