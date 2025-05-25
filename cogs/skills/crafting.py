import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View

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
        if profile.get("stamina", 0) <= 0:
            return False, "😴 Not enough stamina to craft right now.", 0

        # 2) Lookup recipe
        recipe_list = _recipes_data.get(recipe_key.lower())
        if not recipe_list:
            return False, f"❌ No recipe for **{recipe_key}**.", 0
        recipe = recipe_list[0]  # assume one definition

        # 3) Check and consume ingredients
        needs: List[Tuple[str, int]] = []
        for idx_str, item_name in ((k, v) for k, v in recipe.items() if not k.startswith("r")):
            ridx = f"r{idx_str}"
            req = int(recipe.get(ridx, "0")) * amount
            needs.append((item_name, req))

        def resolve_ingredient(name: str):
            if name == "anyFish":
                async def finder():
                    fish_keys = [k for k,i in _items_data.items() if i.get("type")=="fishing"]
                    inv = await db.inventory.find_one({"id": user_id})
                    for fk in fish_keys:
                        if inv.get(fk,0) > 0:
                            return fk
                    return None
                return "inventory", finder
            elif name.endswith("Essence"):
                return "general", name
            else:
                return "inventory", name

        for ing, req in needs:
            loc, resolver = resolve_ingredient(ing)
            if callable(resolver):
                ing = await resolver()
                if not ing:
                    return False, f"❌ You have no fish to use for `{recipe_key}`.", 0
            col = getattr(db, loc)
            doc = await col.find_one({"id": user_id})
            if doc.get(ing, 0) < req:
                return False, f"❌ You lack **{req}** × **{ing.title()}**.", 0

        for ing, req in needs:
            loc, resolver = resolve_ingredient(ing)
            if callable(resolver):
                ing = await resolver()
            col = getattr(db, loc)
            await col.update_one({"id": user_id}, {"$inc": {ing: -req}})

        # 4) Give the crafted item & reduce stamina
        await db.inventory.update_one(
            {"id": user_id}, {"$inc": {recipe_key: amount}}
        )
        await db.general.update_one({"id": user_id}, {"$inc": {"stamina": -1}})

        # 5) Compute XP = sum of all reqs
        xp_gain = sum(req for _, req in needs)

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
        msg_lines = [
            f"🛠️ You crafted **{amount}** × **{recipe_key.title()}**!",
            f"⭐ Gained **{xp_gain}** Crafting XP!"
        ]
        if leveled:
            msg_lines.append(f"🏅 Crafting Level Up! You’re now level **{old_lvl + 1}**!")
        return True, "\n".join(msg_lines), xp_gain

    @app_commands.command(
        name="craft",
        description="🔨 Craft items by name or pick from your known recipes."
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