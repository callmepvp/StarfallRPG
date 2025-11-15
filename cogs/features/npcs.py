# cogs/features/npcs.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Optional, Set, List

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
    def __init__(
        self,
        npc_id: str,
        npc_data: Dict[str, Any],
        user_id: int,
        ready_turnins: Optional[Set[str]] = None,
        active_quests: Optional[Set[str]] = None,
        completed_quests: Optional[Set[str]] = None,
        timeout: float = 300.0,
    ):
        super().__init__(timeout=timeout)
        self.npc_id = npc_id
        self.npc_data = npc_data
        self.user_id = user_id
        self.ready_turnins = ready_turnins or set()
        self.active_quests = active_quests or set()
        self.completed_quests = completed_quests or set()
        self.current_node: str = "start" if "start" in npc_data.get("dialogue", {}) else next(iter(npc_data.get("dialogue", {})), None)
        if self.current_node is None:
            raise ValueError("NPC has no dialogue nodes")
        self._rebuild_buttons_for_node(self.current_node)

    def _clear_buttons(self):
        for child in list(self.children):
            self.remove_item(child)

    def _disable_quest_buttons(self, quest_id: str, completed: bool = False) -> None:
        """
        Disable (or remove) any buttons in this view that are tied to the given quest_id.
        If completed is True we also add it to self.completed_quests and remove from active_quests.
        Otherwise we mark it active in self.active_quests.
        """
        # Update local state first
        if completed:
            self.completed_quests.add(quest_id)
            if quest_id in self.active_quests:
                self.active_quests.remove(quest_id)
        else:
            self.active_quests.add(quest_id)

        # Disable all buttons with matching custom_id
        target_cid = f"quest:{quest_id}"
        for child in list(self.children):
            if isinstance(child, Button):
                cid = getattr(child, "custom_id", None)
                if cid == target_cid:
                    # If completed, remove the button entirely to avoid confusion.
                    if completed:
                        try:
                            self.remove_item(child)
                        except Exception:
                            # fallback to disabling
                            child.disabled = True
                    else:
                        child.disabled = True

    def _rebuild_buttons_for_node(self, node_key: str) -> None:
        self._clear_buttons()
        node = self.npc_data.get("dialogue", {}).get(node_key, {})
        options = node.get("options", [])

        for opt in options:
            label = opt.get("label", "…")

            # --- Quest Button --- (now supports accept OR turn-in)
            if opt.get("action") == "give_quest" and "quest_id" in opt:
                quest_id = opt["quest_id"]

                # If player already completed this quest -> DO NOT SHOW the button
                if quest_id in self.completed_quests:
                    continue

                # If player already has it active -> show but disabled
                is_active = quest_id in self.active_quests
                is_ready = quest_id in self.ready_turnins
                btn_label = label
                style = discord.ButtonStyle.success
                if is_ready:
                    btn_label = f"Turn in: {label}"
                    style = discord.ButtonStyle.primary

                # set custom_id so we can identify duplicates later
                btn = Button(label=btn_label, style=style, disabled=is_active and (not is_ready), custom_id=f"quest:{quest_id}")

                async def quest_cb(inter: discord.Interaction, qid=quest_id, _btn=btn, _opt=opt):
                    quest_cog = inter.client.get_cog("QuestCog")
                    if not quest_cog:
                        return await inter.response.send_message("❌ Quest system unavailable.", ephemeral=True)

                    # fresh check for turn-in
                    try:
                        can_turn, _ = await quest_cog.can_turn_in(inter.user.id, qid)
                        if can_turn:
                            ok, msg, unlocked, rewards = await quest_cog.attempt_turnin(inter.user.id, qid, npc_id=self.npc_id)
                            if ok:
                                # disable/remove all buttons for this quest in the view
                                self._disable_quest_buttons(qid, completed=True)
                                # update the message view
                                try:
                                    await inter.response.edit_message(view=self)
                                except Exception:
                                    # if edit_message already used, fallback to followup
                                    pass

                                # build messages (rewards + unlocked)
                                unlocked_lines = [f"🟡 New quest unlocked: '{u.get('title','Unknown')}'" for u in unlocked]
                                reward_lines = []
                                if rewards:
                                    if rewards.get("gold"):
                                        reward_lines.append(f"+{rewards['gold']} gold")
                                    for it in rewards.get("items", []):
                                        reward_lines.append(f"+{it['qty']}x {it['id']}")
                                    for eq in rewards.get("equipment", []):
                                        reward_lines.append(f"+{eq}")
                                lines = [msg]
                                if reward_lines:
                                    lines.append("Rewards: " + ", ".join(reward_lines))
                                if unlocked_lines:
                                    lines += unlocked_lines
                                await inter.followup.send("\n".join(lines), ephemeral=True)
                                return
                            else:
                                await inter.response.send_message(msg, ephemeral=True)
                                return
                    except Exception:
                        # if any helper fails, continue to accept flow
                        pass

                    # Otherwise try to accept the quest (legacy behaviour)
                    tpl = await quest_cog.get_template(qid)
                    quest_title = tpl.get("title", qid) if tpl else qid

                    success = await quest_cog.accept_for_player(inter.user.id, qid)
                    if success:
                        # mark it active in view and disable all duplicate buttons immediately
                        self._disable_quest_buttons(qid, completed=False)
                        try:
                            await inter.response.edit_message(view=self)
                        except Exception:
                            pass
                        await inter.followup.send(f"🟢 Quest accepted: **{quest_title}**", ephemeral=True)
                    else:
                        await inter.response.send_message(f"⚠️ You already have or completed the quest **{quest_title}**.", ephemeral=True)

                btn.callback = quest_cb
                self.add_item(btn)
                continue

            next_node = opt.get("next")
            if not next_node or next_node.lower() == "end":
                btn = Button(label=label, style=discord.ButtonStyle.secondary)

                async def end_cb(inter: discord.Interaction, _opt=opt, _npc_data=self.npc_data):
                    end_node = _npc_data.get("dialogue", {}).get(_opt.get("next") or "end", {})
                    final_text = end_node.get("text", "Farewell, traveler.")
                    lore_text = end_node.get("lore")
                    if lore_text:
                        final_text += f"\n\n{lore_text}"

                    embed = discord.Embed(
                        title=_npc_data.get("name", "NPC"),
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

        ready_turnins: Set[str] = set()
        active_quests: Set[str] = set()
        completed_quests: Set[str] = set()
        try:
            quest_cog = interaction.client.get_cog("QuestCog")
            if quest_cog:
                # determine active / completed quests for this user
                pdoc = await quest_cog.get_player_doc(self.user_id)
                active_quests = set(pdoc.get("active_quests", {}).keys())
                completed_quests = set(pdoc.get("completed_quests", []))

                options = node.get("options", [])
                for opt in options:
                    if opt.get("action") == "give_quest" and "quest_id" in opt:
                        qid = opt["quest_id"]
                        # only check turn-in readiness for quests not yet completed
                        if qid not in completed_quests:
                            can_turn, _ = await quest_cog.can_turn_in(self.user_id, qid)
                            if can_turn:
                                ready_turnins.add(qid)
        except Exception:
            ready_turnins = set()
            active_quests = set()
            completed_quests = set()

        view = NPCDialogueView(npc_id, npc_data, self.user_id, ready_turnins, active_quests, completed_quests)
        await interaction.response.edit_message(embed=embed, view=view)

        # Quest Integration: propagate 'talk' progress & show completion/unlocked messages
        try:
            quest_cog = interaction.client.get_cog("QuestCog")
            if quest_cog:
                completed = await quest_cog.update_progress(self.user_id, "talk", npc_id, amount=1)

                if completed:
                    msg_lines = []
                    newly_unlocked = []
                    for comp in completed:
                        tpl = comp.get("template", {}) or {}
                        title = tpl.get("title", "Unknown Quest")
                        rewards = comp.get("rewards", {}) or {}
                        reward_lines = []
                        if rewards:
                            if rewards.get("gold"):
                                reward_lines.append(f"+{rewards['gold']} gold")
                            for it in rewards.get("items", []):
                                reward_lines.append(f"+{it['qty']}x {it['id']}")
                            for eq in rewards.get("equipment", []):
                                reward_lines.append(f"+{eq}")
                        msg_lines.append(f"✅ Quest '{title}' completed!")
                        if reward_lines:
                            msg_lines.append("Rewards: " + ", ".join(reward_lines))

                        try:
                            unlocked_templates = await quest_cog.get_unlocked_next_quests(self.user_id, tpl)
                            for ut in unlocked_templates:
                                newly_unlocked.append(f"🟡 New quest unlocked: '{ut.get('title','Unknown')}'")
                        except Exception:
                            next_q = tpl.get("next_quest")
                            if next_q:
                                try:
                                    unlocked_tpl = await quest_cog.get_template(next_q)
                                    if unlocked_tpl:
                                        newly_unlocked.append(f"🟡 New quest unlocked: '{unlocked_tpl.get('title','Unknown')}'")
                                except Exception:
                                    continue

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