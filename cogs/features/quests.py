# cogs/features/quests.py
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

_QUESTS_PATH = Path("data/quests/quests.json")
_AREAS_PATH = Path("data/areas.json")


def _titleize_key(key: str) -> str:
    return key.replace("_", " ").title()


def _humanize_objective(obj: Dict[str, Any], cur: int, amount: int) -> str:
    t = obj.get("type", "").lower()
    target = obj.get("target", "")
    display_target = _titleize_key(target)

    if t == "explore":
        text = f"Explore {display_target}"
    elif t == "talk":
        text = f"Talk to the {display_target}"
    elif t == "collect":
        text = f"Obtain {display_target}"
    elif t == "fetch":
        text = f"Bring {display_target} to the quest giver"
    elif t in ("use_skill", "skill", "use"):
        if target.lower() == "fish":
            text = "Catch a Fish"
        else:
            text = f"Use {display_target} skill"
    elif t == "kill":
        text = f"Defeat {display_target}"
    else:
        text = f"{t.capitalize()} {display_target}"

    return f"• {text} — {cur}/{amount}"


class QuestCog(commands.Cog):
    """Quest templates (from JSON) + per-player quest storage in db.quests + update API."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self._file_cache: Dict[str, Dict[str, Any]] = {}
        if _QUESTS_PATH.exists():
            raw = json.loads(_QUESTS_PATH.read_text(encoding="utf-8"))
            for q in raw.get("quests", []):
                self._file_cache[q["quest_id"]] = q
        else:
            self._file_cache = {}

        self._areas_cache: Dict[str, Any] = {}
        if _AREAS_PATH.exists():
            try:
                raw_areas = json.loads(_AREAS_PATH.read_text(encoding="utf-8"))
                self._areas_cache = raw_areas
            except Exception:
                self._areas_cache = {}

    async def get_template(self, quest_id: str) -> Optional[Dict[str, Any]]:
        return self._file_cache.get(quest_id)

    async def list_templates(self) -> List[Dict[str, Any]]:
        return list(self._file_cache.values())

    async def get_player_doc(self, user_id: int) -> Dict[str, Any]:
        db = self.bot.db
        doc = await db.quests.find_one({"id": user_id})
        if not doc:
            doc = {"id": user_id, "active_quests": {}, "completed_quests": []}
            await db.quests.insert_one(doc)
        return doc

    async def save_player_doc(self, doc: Dict[str, Any]) -> None:
        db = self.bot.db
        await db.quests.update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)

    async def get_completed_quest_ids(self, user_id: int) -> List[str]:
        pdoc = await self.get_player_doc(user_id)
        completed = pdoc.get("completed_quests", []) or []
        return list(completed)

    async def get_unlocked_next_quests(self, user_id: int, tpl_or_id: Any) -> List[Dict[str, Any]]:
        tpl: Optional[Dict[str, Any]] = None
        if isinstance(tpl_or_id, str):
            tpl = await self.get_template(tpl_or_id)
        elif isinstance(tpl_or_id, dict):
            tpl = tpl_or_id
        if not tpl:
            return []

        next_ids: List[str] = []
        if tpl.get("next_quests"):
            if isinstance(tpl.get("next_quests"), list):
                next_ids = tpl.get("next_quests")
            else:
                next_ids = [tpl.get("next_quests")]
        elif tpl.get("next_quest"):
            next_ids = [tpl.get("next_quest")]

        if not next_ids:
            return []

        completed = set(await self.get_completed_quest_ids(user_id))

        unlocked: List[Dict[str, Any]] = []
        for nid in next_ids:
            try:
                cand = await self.get_template(nid)
                if not cand:
                    continue
                prereqs = cand.get("prereqs", []) or []
                if not isinstance(prereqs, list):
                    prereqs = [prereqs]
                if all(p in completed for p in prereqs):
                    unlocked.append(cand)
            except Exception:
                continue

        return unlocked

    @app_commands.command(name="quests", description="Show available & active quests.")
    async def quests(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        user_id = interaction.user.id
        pdoc = await self.get_player_doc(user_id)
        active = pdoc.get("active_quests", {})
        completed = set(pdoc.get("completed_quests", []))
        completed_ids = set(pdoc.get("completed_quests", []))

        embed = discord.Embed(title="📜 Quests", color=discord.Color.blurple())

        if active:
            for qid, pdata in active.items():
                tpl = await self.get_template(qid)
                if not tpl:
                    embed.add_field(name=f"{qid} (Template missing)", value="Contact an admin to restore the template.", inline=False)
                    continue

                objs = tpl.get("objectives", [])
                prog = pdata.get("objectives", {})
                lines: List[str] = []
                for o in objs:
                    key = f"{o['type']}:{o['target']}"
                    cur = prog.get(key, 0)
                    lines.append(_humanize_objective(o, cur, o["amount"]))

                value_text = "\n".join(lines) if lines else "No objectives listed."
                embed.add_field(name=f"🟢 {tpl.get('title')}", value=value_text, inline=False)
        else:
            embed.add_field(name="🟢 Active", value="None", inline=False)

        if completed_ids:
            completed_lines = []
            for qid in completed_ids:
                tpl = await self.get_template(qid)
                if not tpl:
                    continue
                completed_lines.append(f"{tpl.get('title', qid)}")
            embed.add_field(name="✅ Completed Quests", value="\n".join(completed_lines) if completed_lines else "None", inline=False)
        else:
            embed.add_field(name="✅ Completed Quests", value="None", inline=False)

        templates = await self.list_templates()
        avail_lines: List[str] = []
        for tpl in templates:
            qid = tpl["quest_id"]
            if qid in completed or qid in active:
                continue
            if tpl.get("npc_given", False):
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

        prereqs = set(tpl.get("prereqs", []))
        if prereqs - set(pdoc.get("completed_quests", [])):
            return await interaction.followup.send("⚠️ You don't meet quest prerequisites.", ephemeral=True)

        prog_map: Dict[str, int] = {}
        for o in tpl.get("objectives", []):
            prog_map[f"{o['type']}:{o['target']}"] = 0

        pdoc["active_quests"][quest_id] = {"objectives": prog_map, "status": "active"}
        await self.save_player_doc(pdoc)
        await interaction.followup.send(f"✅ Quest **'{tpl['title']}'** accepted.", ephemeral=True)

    async def accept_for_player(self, user_id: int, quest_id: str) -> bool:
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
        db = self.bot.db
        pdoc = await self.get_player_doc(user_id)
        active = pdoc.get("active_quests", {})
        if not active:
            return []

        area_doc = await db.areas.find_one({"id": user_id}) or {}
        current_sub = area_doc.get("currentSubarea")

        completions: List[Dict[str, Any]] = []
        changed = False

        for qid, qstate in list(active.items()):
            tpl = await self.get_template(qid)
            if not tpl:
                continue
            required_sub = tpl.get("sub_area")
            if required_sub:
                if current_sub != required_sub:
                    continue

            for o in tpl.get("objectives", []):
                if o["type"] == "fetch":
                    continue
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

            all_done = True
            for o2 in tpl.get("objectives", []):
                k2 = f"{o2['type']}:{o2['target']}"
                if qstate["objectives"].get(k2, 0) < o2["amount"]:
                    all_done = False
                    break
            if all_done:
                pdoc.setdefault("completed_quests", []).append(qid)
                pdoc["active_quests"].pop(qid, None)
                changed = True
                rewards_given = await self._grant_rewards(user_id, tpl.get("rewards", {}))
                completions.append({"quest_id": qid, "template": tpl, "rewards": rewards_given})

        if changed:
            await self.save_player_doc(pdoc)
        return completions

    async def can_turn_in(self, user_id: int, quest_id: str) -> Tuple[bool, List[Dict[str, Any]]]:
        db = self.bot.db
        tpl = await self.get_template(quest_id)
        if not tpl:
            return False, []

        fetch_objs = [o for o in tpl.get("objectives", []) if o.get("type") == "fetch"]
        if not fetch_objs:
            return False, []

        inv_doc = await db.inventory.find_one({"id": user_id}) or {}
        details: List[Dict[str, Any]] = []
        can = True
        for o in fetch_objs:
            item = o["target"]
            need = int(o["amount"])
            have = int(inv_doc.get(item, 0) or 0)
            details.append({"target": item, "need": need, "have": have})
            if have < need:
                can = False
        return can, details

    async def attempt_turnin(self, user_id: int, quest_id: str, npc_id: Optional[str] = None) -> Tuple[bool, str, List[Dict[str, Any]], Dict[str, Any]]:
        db = self.bot.db
        tpl = await self.get_template(quest_id)
        if not tpl:
            return False, "Quest template missing.", [], {}

        pdoc = await self.get_player_doc(user_id)
        if quest_id not in pdoc.get("active_quests", {}):
            return False, "You don't have that quest active.", [], {}

        can, details = await self.can_turn_in(user_id, quest_id)
        if not can:
            missing = [f"{d['target']} (need {d['need']}, have {d['have']})" for d in details if d['have'] < d['need']]
            return False, "You are missing: " + ", ".join(missing), [], {}

        inv_updates: Dict[str, int] = {}
        for d in details:
            item = d["target"]
            need = d["need"]
            inv_updates[item] = inv_updates.get(item, 0) - need

        for item, delta in inv_updates.items():
            await db.inventory.update_one({"id": user_id}, {"$inc": {item: delta}}, upsert=True)

        pdoc.setdefault("completed_quests", []).append(quest_id)
        pdoc["active_quests"].pop(quest_id, None)

        rewards_given = await self._grant_rewards(user_id, tpl.get("rewards", {}))
        await self.save_player_doc(pdoc)

        unlocked_templates = await self.get_unlocked_next_quests(user_id, tpl)

        title = tpl.get("title", quest_id)
        msg = f"✅ Quest **{title}** turned in."
        return True, msg, unlocked_templates, rewards_given

    async def _grant_rewards(self, user_id: int, rewards: Dict[str, Any]) -> Dict[str, Any]:
        db = self.bot.db
        result: Dict[str, Any] = {"gold": 0, "items": [], "equipment": []}
        if not rewards:
            return result

        if "gold" in rewards:
            rng = rewards["gold"]
            if isinstance(rng, list) and len(rng) == 2:
                amt = random.randint(rng[0], rng[1])
            else:
                amt = int(rng)
            await db.general.update_one({"id": user_id}, {"$inc": {"wallet": amt}}, upsert=True)
            result["gold"] = amt

        if "items" in rewards:
            for it in rewards["items"]:
                await db.inventory.update_one({"id": user_id}, {"$inc": {it: 1}}, upsert=True)
                result["items"].append({"id": it, "qty": 1})

        if "equipment" in rewards:
            for eq in rewards["equipment"]:
                # placeholder for equipment handling; still record to result
                result["equipment"].append(eq)
                # implement actual equipment add when you support instanced equipment
        return result


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(QuestCog(bot), guilds=[discord.Object(id=GUILD_ID)])