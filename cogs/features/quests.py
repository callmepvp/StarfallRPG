# cogs/features/quests.py
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

_QUESTS_PATH = Path("data/quests/quests.json")
_AREAS_PATH = Path("data/areas.json")


def _titleize_key(key: str) -> str:
    """Convert a snake_case key into a readable title (e.g. 'lynthaven' -> 'Lynthaven')."""
    return key.replace("_", " ").title()


def _humanize_objective(obj: Dict[str, Any], cur: int, amount: int) -> str:
    """
    Turn an objective template into a readable line.
    Examples:
      {type: explore, target: lynthaven} -> "Explore Lynthaven — 0/1"
      {type: talk, target: blacksmith}  -> "Talk to the Blacksmith — 0/1"
      {type: collect, target: oak}      -> "Obtain Oak — 2/5"
      {type: use_skill, target: fish}   -> "Catch a Fish — 0/1"   (custom phrasing for fish)
      {type: kill, target: goblin}      -> "Defeat Goblin — 1/3"
    """
    t = obj.get("type", "").lower()
    target = obj.get("target", "")
    display_target = _titleize_key(target)

    if t == "explore":
        text = f"Explore {display_target}"
    elif t == "talk":
        text = f"Talk to the {display_target}"
    elif t == "collect":
        text = f"Obtain {display_target}"
    elif t in ("use_skill", "skill", "use"):
        # special-case "fish" to make it more natural
        if target.lower() == "fish":
            text = "Catch a Fish"
        else:
            text = f"Use {display_target} skill"
    elif t == "kill":
        text = f"Defeat {display_target}"
    else:
        # fallback: "<Type> <Target>"
        text = f"{t.capitalize()} {display_target}"

    return f"• {text} — {cur}/{amount}"


class QuestCog(commands.Cog):
    """Quest templates (from JSON) + per-player quest storage in db.quests + update API."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Load templates from JSON once on startup (this is the canonical template source)
        self._file_cache: Dict[str, Dict[str, Any]] = {}
        if _QUESTS_PATH.exists():
            raw = json.loads(_QUESTS_PATH.read_text(encoding="utf-8"))
            for q in raw.get("quests", []):
                self._file_cache[q["quest_id"]] = q
        else:
            self._file_cache = {}

        # Optional: load areas for nicer sub_area name mapping (fallback to titleizing)
        self._areas_cache: Dict[str, Any] = {}
        if _AREAS_PATH.exists():
            try:
                raw_areas = json.loads(_AREAS_PATH.read_text(encoding="utf-8"))
                self._areas_cache = raw_areas
            except Exception:
                self._areas_cache = {}

    async def get_template(self, quest_id: str) -> Optional[Dict[str, Any]]:
        """Return the quest template from the JSON file cache (templates are file-backed)."""
        return self._file_cache.get(quest_id)

    async def list_templates(self) -> List[Dict[str, Any]]:
        """Return a list of all templates from the JSON file cache."""
        return list(self._file_cache.values())

    async def get_player_doc(self, user_id: int) -> Dict[str, Any]:
        """
        Get (or create) the per-player quest document.
        Document format:
          { "user_id": 123, "active_quests": { "<qid>": {"objectives": {...}, "status": "active"} }, "completed_quests": [...] }
        Uses db.quests as the per-player collection (as requested).
        """
        db = self.bot.db
        doc = await db.quests.find_one({"user_id": user_id})
        if not doc:
            doc = {"user_id": user_id, "active_quests": {}, "completed_quests": []}
            await db.quests.insert_one(doc)
        return doc

    async def save_player_doc(self, doc: Dict[str, Any]) -> None:
        db = self.bot.db
        await db.quests.update_one({"user_id": doc["user_id"]}, {"$set": doc}, upsert=True)

    @app_commands.command(name="quests", description="Show available & active quests.")
    async def quests(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        user_id = interaction.user.id
        pdoc = await self.get_player_doc(user_id)
        active = pdoc.get("active_quests", {})
        completed = set(pdoc.get("completed_quests", []))

        embed = discord.Embed(title="📜 Quests", color=discord.Color.blurple())

        # Active quests: each quest gets its own field with bullet-point objectives
        if active:
            for qid, pdata in active.items():
                tpl = await self.get_template(qid)
                if not tpl:
                    embed.add_field(name=f"{qid} (Template missing)", value="Contact an admin to restore the template.", inline=False)
                    continue

                objs = tpl.get("objectives", [])
                prog = pdata.get("objectives", {})
                # Build bullet list lines
                lines: List[str] = []
                for o in objs:
                    key = f"{o['type']}:{o['target']}"
                    cur = prog.get(key, 0)
                    lines.append(_humanize_objective(o, cur, o["amount"]))

                # Join lines with newline; ensure there's something to show
                value_text = "\n".join(lines) if lines else "No objectives listed."
                # Field name: quest title (show quest id in footer if desired)
                embed.add_field(name=f"🟢 {tpl.get('title')}", value=value_text, inline=False)
        else:
            embed.add_field(name="🟢 Active", value="None", inline=False)

        # Available templates (from JSON) — show nicer sub-area names when possible
        templates = await self.list_templates()
        avail_lines: List[str] = []
        for tpl in templates:
            qid = tpl["quest_id"]
            if qid in completed or qid in active:
                continue
            prereqs = set(tpl.get("prereqs", []))
            if prereqs - completed:
                continue
            sub = tpl.get("sub_area")
            if sub:
                found_name = None
                for area_key, area_val in self._areas_cache.items():
                    sa = area_val.get("sub_areas", {})
                    if sub in sa:
                        found_name = sa[sub].get("name") or _titleize_key(sub)
                        break
                display_sub = found_name or _titleize_key(sub)
            else:
                display_sub = "Various"
            avail_lines.append(f"**{tpl['title']}** — Area: {display_sub} (id: `{qid}`)")

        embed.add_field(name="🟡 Available Quests", value="\n".join(avail_lines) if avail_lines else "None", inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="quest_accept", description="Accept a quest by ID/Name.")
    @app_commands.describe(quest_id="The id/name to accept (see /quests).")
    async def quest_accept(self, interaction: discord.Interaction, quest_id: str) -> None:
        await interaction.response.defer(thinking=True)
        user_id = interaction.user.id
        tpl = await self.get_template(quest_id)
        if not tpl:
            return await interaction.followup.send("❌ No such quest template found.", ephemeral=True)

        pdoc = await self.get_player_doc(user_id)
        if quest_id in pdoc.get("active_quests", {}) or quest_id in pdoc.get("completed_quests", []):
            return await interaction.followup.send("ℹ️ You already have or completed this quest.", ephemeral=True)

        # check prereqs
        prereqs = set(tpl.get("prereqs", []))
        if prereqs - set(pdoc.get("completed_quests", [])):
            return await interaction.followup.send("⚠️ You don't meet quest prerequisites.", ephemeral=True)

        # init progress map
        prog_map: Dict[str, int] = {}
        for o in tpl.get("objectives", []):
            prog_map[f"{o['type']}:{o['target']}"] = 0

        pdoc["active_quests"][quest_id] = {"objectives": prog_map, "status": "active"}
        await self.save_player_doc(pdoc)
        await interaction.followup.send(f"✅ Quest **{tpl['title']}** accepted.", ephemeral=True)

    async def accept_for_player(self, user_id: int, quest_id: str) -> bool:
        """Programmatically accept a quest for a player. Returns True on success."""
        tpl = await self.get_template(quest_id)
        if not tpl:
            return False
        pdoc = await self.get_player_doc(user_id)
        if quest_id in pdoc.get("active_quests", {}) or quest_id in pdoc.get("completed_quests", []):
            return False
        prereqs = set(tpl.get("prereqs", []))
        if prereqs - set(pdoc.get("completed_quests", [])):
            return False
        prog_map: Dict[str, int] = {}
        for o in tpl.get("objectives", []):
            prog_map[f"{o['type']}:{o['target']}"] = 0
        pdoc["active_quests"][quest_id] = {"objectives": prog_map, "status": "active"}
        await self.save_player_doc(pdoc)
        return True

    async def update_progress(self, user_id: int, objective_type: str, target: str, amount: int = 1) -> List[Dict[str, Any]]:
        """
        Update active quests for a player.
        Enforces quest.sub_area gating: if template has a sub_area, progress only counts
        if player is currently in that sub_area (based on db.areas).
        Returns a list of completion events (each dict has quest_id and template).
        """
        db = self.bot.db
        pdoc = await self.get_player_doc(user_id)
        active = pdoc.get("active_quests", {})
        if not active:
            return []

        # fetch player's current location for gating
        area_doc = await db.areas.find_one({"id": user_id}) or {}
        current_sub = area_doc.get("currentSubarea")

        completions: List[Dict[str, Any]] = []
        changed = False

        for qid, qstate in list(active.items()):
            tpl = await self.get_template(qid)
            if not tpl:
                continue
            # gating: if template specifies a sub_area, ensure player is in that subarea
            required_sub = tpl.get("sub_area")
            if required_sub:
                if current_sub != required_sub:
                    # skip this quest for progress if not in correct subarea
                    continue

            for o in tpl.get("objectives", []):
                if o["type"] != objective_type:
                    continue
                if o["target"] != target:
                    continue
                key = f"{o['type']}:{o['target']}"
                cur = qstate["objectives"].get(key, 0)
                new = min(o["amount"], cur + amount)
                if new != cur:
                    qstate["objectives"][key] = new
                    changed = True

            # check overall completion for this quest
            all_done = True
            for o2 in tpl.get("objectives", []):
                k2 = f"{o2['type']}:{o2['target']}"
                if qstate["objectives"].get(k2, 0) < o2["amount"]:
                    all_done = False
                    break
            if all_done:
                # complete quest: move to completed_quests, remove from active
                pdoc.setdefault("completed_quests", []).append(qid)
                pdoc["active_quests"].pop(qid, None)
                changed = True
                # grant rewards
                await self._grant_rewards(user_id, tpl.get("rewards", {}))
                completions.append({"quest_id": qid, "template": tpl})

        if changed:
            await self.save_player_doc(pdoc)
        return completions

    async def _grant_rewards(self, user_id: int, rewards: Dict[str, Any]) -> None:
        """Simple reward processing - adapt to your DB schema."""
        db = self.bot.db
        if not rewards:
            return
        if "gold" in rewards:
            rng = rewards["gold"]
            if isinstance(rng, list) and len(rng) == 2:
                amt = random.randint(rng[0], rng[1])
            else:
                amt = int(rng)
            await db.general.update_one({"id": user_id}, {"$inc": {"wallet": amt}}, upsert=True)
        if "items" in rewards:
            for it in rewards["items"]:
                await db.inventory.update_one({"id": user_id}, {"$inc": {it: 1}}, upsert=True)
        if "equipment" in rewards:
            pass
            #! ADD FUNCTIONALITY

async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(QuestCog(bot), guilds=[discord.Object(id=GUILD_ID)])