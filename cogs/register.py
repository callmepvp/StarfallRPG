import datetime
import time
from typing import Optional, Dict, Any
import json

import string
import datetime

import discord, random
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View

from pathlib import Path

from database import Database
from settings import GUILD_ID


_CHARSET = string.ascii_uppercase + string.digits  # A-Z + 0-9
_ID_LENGTH = 5

def _make_instance_id(existing_ids: set[str] | None = None) -> str:
    """
    Generate a 5-character ID from A-Z0-9 that does not collide with existing_ids (if provided).
    """
    existing = existing_ids or set()
    while True:
        candidate = ''.join(random.choices(_CHARSET, k=_ID_LENGTH))
        if candidate not in existing:
            return candidate

## Starter Equipment Templates
_starters = {
    "fishingTool": "Wooden Fishing Rod",
    "miningTool": "Wooden Pickaxe",
    "foragingTool": "Wooden Axe",
    "farmingTool": "Wooden Hoe",
    "scavengingTool": "Wooden Machete",
}

ITEM_TEMPLATES_PATH = Path("data/itemTemplates.json")
QUESTS_FALLBACK_PATH = Path("data/quests/quests.json")

# Load the JSON file
item_templates: Dict[str, Any] = {}
if ITEM_TEMPLATES_PATH.exists():
    with ITEM_TEMPLATES_PATH.open(encoding="utf-8") as f:
        item_templates = json.load(f)
else:
    raise FileNotFoundError(f"{ITEM_TEMPLATES_PATH} not found. Make sure it exists!")

# (QUESTS_FALLBACK_PATH is only used in registration fallback if DB doesn't have the quest)
quest_file_cache: Dict[str, Any] = {}
if QUESTS_FALLBACK_PATH.exists():
    with QUESTS_FALLBACK_PATH.open(encoding="utf-8") as f:
        try:
            rawq = json.load(f)
            for q in rawq.get("quests", []):
                quest_file_cache[q["quest_id"]] = q
        except Exception:
            quest_file_cache = {}

class CharacterCustomizationModal(Modal):
    """Modal for choosing your character’s display name and brief bio."""
    name = TextInput(
        label="Your Character’s Name",
        placeholder="Enter the name you'll be known by in Starfall",
        max_length=32,
    )
    bio = TextInput(
        label="Short Bio",
        style=discord.TextStyle.paragraph,
        placeholder="Describe yourself in one sentence",
        required=False,
        max_length=100,
    )

    def __init__(self, user_id: int, db: "Database"):
        super().__init__(title="Customize Your Avatar")
        self.user_id = user_id
        self.db = db

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Save the custom name and bio, then confirm registration."""
        # Update the general document with the chosen name & bio
        await self.db.general.update_one(
            {"id": self.user_id},
            {"$set": {"name": self.name.value, "bio": self.bio.value}},
        )

        embed = discord.Embed(
            title="Registration Complete!",
            description=(
                f"Welcome, **{self.name.value}**!\n"
                "You’ve been fully registered and can now explore Starfall."
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class RegisterCog(commands.Cog):
    """Handles the `/register` command and new-user onboarding."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="register",
        description="Setup your Starfall profile and get started!"
    )
    async def register(self, interaction: discord.Interaction) -> None:
        """
        1) Checks if the user already has a profile.
        2) Shows the Terms & Conditions embed with a confirmation button.
        3) On confirmation, seeds all MongoDB collections for that user.
        4) Launches a Modal to collect name & bio.
        """
        user_id = interaction.user.id
        db = self.bot.db

        # Step 1: refuse if already registered
        existing = await db.general.find_one({"id": user_id})
        if existing:
            return await interaction.response.send_message(
                "You already have an account! If this is an error, contact the dev.",
                ephemeral=True,
            )

        # Step 2: Terms & Conditions
        terms = (
            "**Before proceeding, please read carefully!**\n\n"
            "1. Do not exploit bugs or use multiple accounts.\n"
            "2. Your Discord username, ID, and avatar will be stored for gameplay.\n"
        )
        embed = discord.Embed(
            title=f"Welcome to Starfall, {interaction.user.display_name}!",
            description=terms,
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(),
        )
        embed.set_footer(text="Click “I understand” to continue.")

        button = Button(label="I understand", style=discord.ButtonStyle.gray)
        async def on_accept(button_inter: discord.Interaction) -> None:
            button.disabled = True

            # Step 3: seed all collections
            now = time.time()
            await db.inventory.insert_one({"id": user_id})
            await db.general.insert_one({
                "id": user_id,
                "name": interaction.user.display_name,
                "bio": "",
                "maxInventory": 200,
                "maxStamina": 200,
                "lastStaminaUpdate": now,
                "maxHP": 100,
                "wallet": 0,
                "creation": now,
                "stamina": 200,
                "crates": [0, 0, 0, 0],
                "miningEssence": 0,
                "foragingEssence": 0,
                "farmingEssence": 0,
                "scavengingEssence": 0,
                "fishingEssence": 0,
                "treasureChance": 1,
                "trashChance": 50,
                "hp": 100,
                "strength": 1,
                "defense": 1,
                "evasion": 1,
                "accuracy": 1,
                "powerRating": 0,
                "inDungeon": False
            })
            await db.areas.insert_one({
                "id": user_id,
                "currentArea": "plains",
                "currentSubarea": "pond",
                "subareaType": "small",
                "lastTravel": int(time.time()) - 86400
            })
            await db.skills.insert_one({
                "id": user_id,
                **{f"{sk}{prop}": 0 for sk in ("foraging","mining","farming","crafting","scavenging","fishing", "combat") for prop in ("Level","XP","Bonus")}
            })
            await db.collections.insert_one({
                "id": user_id,
                "wood": 0, "woodLevel": 0,
                "ore": 0, "oreLevel": 0,
                "crop": 0, "cropLevel": 0,
                "herb": 0, "herbLevel": 0,
                "fish": 0, "fishLevel": 0,
            })
            await db.recipes.insert_one({
                "id": user_id,
                "toolrod": True,
                "wooden helmet": True,
                "wooden chestplate": True,
                "wooden leggings": True,
                "wooden boots": True,
                "wooden gloves": True,
            })

            ## SETUP THE EQUIPPED TOOLS AND INSTANCES
            instances = []
            slot_refs = {}
            used_ids = set()

            # generate unique 5-char ids per-player (check within this player's created instances)
            for slot, template_name in _starters.items():
                iid = _make_instance_id(existing_ids=used_ids)
                used_ids.add(iid)

                tmpl = item_templates.get(template_name, {})

                # instance doc stored inside the player's equipment doc
                inst_doc = {
                    "instance_id": iid,
                    "template": template_name,
                    "enchants": [],
                    "custom_name": None,
                    "bound": False,
                    "created_at": now,
                    "slots": tmpl.get("equip_slots", []),
                    "stats": tmpl.get("stats", {}).copy() if isinstance(tmpl.get("stats", {}), dict) else {},
                    "tier": tmpl.get("tier", None)
                }
                instances.append(inst_doc)
                slot_refs[slot] = iid

            # convert used_ids to list for storage
            used_ids_list = list(used_ids)

            await db.equipment.insert_one({
                "id": user_id,
                "head": None,
                "chest": None,
                "legs": None,
                "feet": None,
                "gloves": None,
                "mainHand": None,
                "offHand": None,
                "talisman1": None,
                "talisman2": None,
                "talisman3": None,
                "charm1": None,
                "charm2": None,
                "ring1": None,
                "ring2": None,
                "amulet": None,
                # action tools point to instance_ids created above
                "fishingTool": slot_refs["fishingTool"],
                "miningTool": slot_refs["miningTool"],
                "foragingTool": slot_refs["foragingTool"],
                "farmingTool": slot_refs["farmingTool"],
                "scavengingTool": slot_refs["scavengingTool"],
                # all item instances owned by this player (including the equipped ones)
                "instances": instances,
                # store used short ids for quick uniqueness checks later
                "used_ids": used_ids_list,
            })

            # ----------------------------
            # NEW: Initialize player_quests with the first quest active
            # ----------------------------
            try:
                # Use the file-backed quest templates (we do NOT read player templates from db.quests)
                quest_tpl = quest_file_cache.get("wayfarers_welcome")

                if quest_tpl:
                    # Build objective progress map: keys like "type:target" => 0
                    prog_map = {}
                    for o in quest_tpl.get("objectives", []):
                        key = f"{o['type']}:{o['target']}"
                        prog_map[key] = 0

                    player_quests_doc = {
                        "id": user_id,
                        "active_quests": {
                            "wayfarers_welcome": {
                                "objectives": prog_map,
                                "status": "active"
                            }
                        },
                        "completed_quests": []
                    }
                else:
                    # If the JSON is missing the template, fall back to an empty per-player record
                    player_quests_doc = {
                        "player_id": user_id,
                        "active_quests": {},
                        "completed_quests": []
                    }

                await db.quests.insert_one(player_quests_doc)
            except Exception as e:
                # Log but don't crash registration if quests initialization fails
                print("Warning: failed to initialize player_quests for new user:", e)
                try:
                    await db.quests.insert_one({
                        "player_id": user_id,
                        "active_quests": {},
                        "completed_quests": []
                    })
                except Exception:
                    pass



    
            modal = CharacterCustomizationModal(user_id, db)
            await button_inter.response.send_modal(modal)

        button.callback = on_accept
        view = View(timeout=120.0)
        view.add_item(button)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RegisterCog(bot), guilds=[discord.Object(id=GUILD_ID)])