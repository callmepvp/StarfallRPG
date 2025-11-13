import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View

import random
import string
import time

from server.userMethods import regenerate_stamina, calculate_power_rating

# Load manifests once at import time
_ITEMS_PATH = Path("data/items.json")
_RECIPES_PATH = Path("data/recipes/craftingRecipes.json")

_items_data: Dict[str, Any] = {}
_recipes_data: Dict[str, List[Dict[str, str]]] = {}

if _ITEMS_PATH.exists():
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})

if _RECIPES_PATH.exists():
    _recipes_data = json.loads(_RECIPES_PATH.read_text(encoding="utf-8"))

# Load item templates for instanced items
_ITEM_TEMPLATES_PATH = Path("data/itemTemplates.json")
item_templates: Dict[str, Any] = {}
if _ITEM_TEMPLATES_PATH.exists():
    item_templates = json.loads(_ITEM_TEMPLATES_PATH.read_text(encoding="utf-8"))

#! basically a duplicate of the one in register.py
def make_short_id() -> str:
    """Generate a 5-character alphanumeric ID (A-Z, 0-9)."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(5))

class CraftingCog(commands.Cog):
    """Handles `/craft` via arguments or a dropdown menu, with full DB integration."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def get_regen_user(self, user_id: int) -> Dict | None:
        db = self.bot.db
        user = await db.general.find_one({"id": user_id})
        if user is None:
            return None

        user = regenerate_stamina(user)
        power = calculate_power_rating(user)
        user["powerRating"] = power
        await db.general.update_one(
            {"id": user_id},
            {"$set": {
                "stamina": user["stamina"],
                "lastStaminaUpdate": user["lastStaminaUpdate"],
                "powerRating": power
            }}
        )
        return user

    async def _perform_craft(
        self,
        interaction: discord.Interaction,
        recipe_key: str,
        amount: int
    ) -> Tuple[bool, str, int]:
        """
        Attempt to craft `amount` × `recipe_key`.
        Returns (success, message, xp_gain).
        """
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # 1) Verify user registered & stamina
        profile = await self.get_regen_user(user_id)
        if not profile:
            return False, "❌ You need to `/register` first!", 0
        
        if profile.get("inDungeon", False):
            return await interaction.response.send_message(
                "❌ You can't do this while in a dungeon! Complete or flee from your dungeon first.",
                ephemeral=True
            )
        
        if profile.get("stamina", 0) <= 0:
            return False, "😴 Not enough stamina to craft right now.", 0

        # 2) Lookup recipe
        recipe_list = _recipes_data.get(recipe_key.lower())
        if not recipe_list:
            return False, f"❌ No recipe for **{recipe_key}**.", 0
        recipe = recipe_list[0]  # assume one definition

        # 3) Check and consume ingredients (aggregate missing items)
        needs: List[Tuple[str, int]] = []
        for idx_str, item_name in ((k, v) for k, v in recipe.items() if not k.startswith("r")):
            ridx = f"r{idx_str}"
            req = int(recipe.get(ridx, "0")) * amount
            needs.append((item_name, req))

        def resolve_ingredient(name: str):
            if name == "anyFish":
                async def finder():
                    fish_keys = [k for k, i in _items_data.items() if i.get("type") == "fishing"]
                    inv = await db.inventory.find_one({"id": user_id})
                    for fk in fish_keys:
                        if inv.get(fk, 0) > 0:
                            return fk
                    return None
                return "inventory", finder
            elif name.endswith("Essence"):
                return "general", name
            else:
                return "inventory", name

        missing_items = []

        for ing, req in needs:
            loc, resolver = resolve_ingredient(ing)
            if callable(resolver):
                ing = await resolver()
                if not ing:
                    return False, f"❌ You have no fish to use for `{recipe_key}`.", 0
            col = getattr(db, loc)
            doc = await col.find_one({"id": user_id})
            have = doc.get(ing, 0)
            if have < req:
                missing_items.append((ing, req - have))

        if missing_items:
            missing_text = "\n".join([f"• **{amt} × {name.title()}**" for name, amt in missing_items])
            return False, f"❌ You're missing the following items:\n{missing_text}", 0

        # If we got here, consume the ingredients safely
        for ing, req in needs:
            loc, resolver = resolve_ingredient(ing)
            if callable(resolver):
                ing = await resolver()
            col = getattr(db, loc)
            await col.update_one({"id": user_id}, {"$inc": {ing: -req}})

        # 4) Give the crafted item OR create instances if it's a templated item
        # Try to find a matching template (case-insensitive)
        template_name = None
        for tname in item_templates.keys():
            if tname.lower() == recipe_key.lower():
                template_name = tname
                break

        created_instance_ids: List[str] = []
        if template_name:
            # We're crafting an equippable/instanced item. Create `amount` instances.
            now = int(time.time())
            # Fetch player's equipment doc to check used_ids and instances
            equip_doc = await db.equipment.find_one({"id": user_id})
            if not equip_doc:
                return False, "❌ You don't have equipment data yet, please /register.", 0

            used_ids = set(equip_doc.get("used_ids", []) or [])
            # also ensure we don't duplicate against existing instances' ids
            existing_ids = {inst.get("instance_id") for inst in (equip_doc.get("instances") or []) if inst.get("instance_id")}
            used_ids.update(existing_ids)

            template_data = item_templates[template_name]

            # create amount instances, storing each in equipment.instances and used_ids
            for _i in range(amount):
                # generate unique short id
                for _attempt in range(2000):
                    iid = make_short_id()
                    if iid not in used_ids:
                        break
                else:
                    # fallback to longer id if we couldn't find a short unique id
                    iid = f"I{int(time.time()*1000)}"

                tmpl = template_data or {}

                inst_doc = {
                    "instance_id": iid,
                    "template": template_name,
                    "enchants": [],
                    "custom_name": None,
                    "bound": False,
                    "created_at": now,
                    "slots": tmpl.get("equip_slots", []) if isinstance(tmpl.get("equip_slots", []), list) else [],
                    "stats": tmpl.get("stats", {}).copy() if isinstance(tmpl.get("stats", {}), dict) else {},
                    "tier": tmpl.get("tier", None)
                }

                # push the instance into equipment doc
                await db.equipment.update_one(
                    {"id": user_id},
                    {"$push": {"instances": inst_doc, "used_ids": iid}}
                )
                used_ids.add(iid)
                created_instance_ids.append(iid)

            # reduce stamina once per craft action (as before)
            await db.general.update_one({"id": user_id}, {"$inc": {"stamina": -1}})
        else:
            # not a templated item — keep previous behavior: add to inventory
            await db.inventory.update_one(
                {"id": user_id}, {"$inc": {recipe_key: amount}}
            )
            # reduce stamina
            await db.general.update_one({"id": user_id}, {"$inc": {"stamina": -1}})

        # 5) Compute XP = sum of all reqs
        item_info = _items_data.get(recipe_key.lower(), {})
        xp_gain = item_info.get("xp", 0) * amount

        # 6) Update crafting skill
        sk = await db.skills.find_one({"id": user_id})
        old_xp, old_lvl = sk["craftingXP"], sk["craftingLevel"]
        new_xp = old_xp + xp_gain
        lvl_thr = 50 * old_lvl + 10
        leveled = False
        bonus = 2
        if new_xp >= lvl_thr:
            leveled = True
            leftover = new_xp - lvl_thr
            await db.skills.update_one(
                {"id": user_id},
                {"$set": {"craftingLevel": old_lvl + 1, "craftingXP": leftover},
                 "$inc": {"craftingBonus": bonus}}
            )
        else:
            await db.skills.update_one(
                {"id": user_id}, {"$set": {"craftingXP": new_xp}}
            )

        # 7) Build response
        msg_lines = []
        if created_instance_ids:
            # show created instance ids
            ids_str = ", ".join(f"`{iid}`" for iid in created_instance_ids)
            msg_lines.append(f"🛠️ You crafted **{amount}** × **{template_name}** - created instances: {ids_str}")
            msg_lines.append(f"⭐ Gained **{xp_gain}** Crafting XP!")
        else:
            msg_lines.append(f"🛠️ You crafted **{amount}** × **{recipe_key.title()}**!")
            msg_lines.append(f"⭐ Gained **{xp_gain}** Crafting XP!")

        if leveled:
            msg_lines.append(f"🏅 Crafting Level Up! You’re now level **{old_lvl + 1}**!")

        return True, "\n".join(msg_lines), xp_gain

    @app_commands.command(
        name="craft",
        description="Craft items by name or pick from your known recipes."
    )
    @app_commands.describe(item="Recipe name", amount="Quantity to craft")
    async def craft(
        self,
        interaction: discord.Interaction,
        item: str = None,
        amount: int = 1
    ) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        prof = await db.general.find_one({"id": user_id})
        if not prof:
            return await interaction.response.send_message(
                "❌ Please `/register` first.", ephemeral=True
            )

        if item:
            success, msg, _ = await self._perform_craft(interaction, item.lower(), amount)
            await interaction.response.send_message(msg, ephemeral=not success)
        else:
            user_rec = await db.recipes.find_one({"id": user_id})
            opts = [
                discord.SelectOption(label=k.title())
                for k in user_rec.keys() if k not in {"_id", "id"}
            ]
            if not opts:
                return await interaction.response.send_message(
                    "⚠️ You know no recipes yet!", ephemeral=True
                )
            view = View()
            view.add_item(RecipeSelect(opts, self))
            await interaction.response.send_message(
                "Select a recipe to craft:", view=view, ephemeral=True
            )

class RecipeSelect(Select):
    def __init__(self, options: List[discord.SelectOption], cog: CraftingCog):
        super().__init__(
            placeholder="Choose recipe...",
            min_values=1, max_values=1,
            options=options
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        choice = self.values[0].lower()
        success, msg, _ = await self.cog._perform_craft(interaction, choice, 1)
        await interaction.response.edit_message(content=msg, view=None)

async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(CraftingCog(bot), guilds=[discord.Object(id=GUILD_ID)])