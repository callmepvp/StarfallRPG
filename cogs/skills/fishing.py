import datetime
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

# Load the global items manifest
_ITEMS_PATH = Path("data/items.json")
_items_data: Dict[str, Any] = {}
if _ITEMS_PATH.exists():
    import json
    _items_data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8")).get("items", {})


def _get_items_by_type(item_type: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Return list of (key, info) filtered by info['type']==item_type."""
    return [
        (k, info)
        for k, info in _items_data.items()
        if info.get("type") == item_type
    ]

class FishingCog(commands.Cog):
    """Handles `/fish`: catch fish, trash, coins, or crates, with full progression updates."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._fish_items = _get_items_by_type("fishing")
        self._trash_items = _get_items_by_type("trash")
        self._crate_rarities = ["common crate", "uncommon crate", "rare crate", "legendary crate"]

    @app_commands.command(
        name="fish",
        description="🎣 Fish the waters for catches, treasure, and surprises!"
    )
    async def fish(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # 1) Ensure registered & has stamina
        profile = await db.general.find_one({"id": user_id})
        if not profile:
            return await interaction.response.send_message(
                "❌ Please `/register` before you head out to fish!",
                ephemeral=True
            )
        if profile.get("stamina", 0) <= 0:
            return await interaction.response.send_message(
                "😴 You’re out of stamina! Rest or boost before fishing again.",
                ephemeral=True
            )

        # 2) Load thresholds
        treasure_chance = profile.get("treasureChance", 0)
        trash_chance = profile.get("trashChance", 100)

        # 3) Roll outcome
        roll = random.randint(1, 100)
        kind: str
        key: str
        qty: int
        xp_gain: int
        essence_gain: float

        if roll <= treasure_chance:
            # Treasure: either coins or crate
            if random.choice([True, False]):
                kind = "coins"
                qty = random.randint(10, 500)
                xp_gain = 3
            else:
                kind = "crate"
                key = random.choice(self._crate_rarities)
                qty = 1
                xp_gain = 4
        elif roll <= trash_chance:
            # Trash catch
            selection = random.choices(
                [k for k, _ in self._trash_items],
                weights=[info.get("weight", 10) for _, info in self._trash_items],
                k=1
            )[0]
            kind = "trash"
            key = selection
            qty = random.randint(1, 2)
            xp_gain = _items_data[key].get("xp", 1) * qty
        else:
            # Fish catch
            selection = random.choices(
                [k for k, _ in self._fish_items],
                weights=[info.get("weight", 10) for _, info in self._fish_items],
                k=1
            )[0]
            kind = "fish"
            key = selection
            qty = random.randint(1, 2)
            xp_gain = _items_data[key].get("xp", 1) * qty

        essence_gain = round(xp_gain * 0.35, 2)

        # 4) Apply stamina cost
        await db.general.update_one({"id": user_id}, {"$inc": {"stamina": -1}})

        leveled_fish = False
        leveled_coll = False

        # 5) Handle XP, Essence, and level-ups for Fishing skill
        sk = await db.skills.find_one({"id": user_id})
        old_xp, old_lvl = sk["fishingXP"], sk["fishingLevel"]
        new_xp = old_xp + xp_gain
        lvl_thr = 50 * old_lvl + 10
        bonus_inc = 2

        if new_xp >= lvl_thr:
            leveled_fish = True
            leftover = new_xp - lvl_thr
            await db.skills.update_one(
                {"id": user_id},
                {"$set": {"fishingLevel": old_lvl + 1, "fishingXP": leftover},
                 "$inc": {"fishingBonus": bonus_inc}}
            )
        else:
            await db.skills.update_one({"id": user_id}, {"$set": {"fishingXP": new_xp}})

        await db.general.update_one(
            {"id": user_id}, {"$inc": {"fishingEssence": essence_gain}}
        )

        # 6) Handle catch-specific updates
        wallet_inc = 0
        crate_inc = 0
        if kind == "coins":
            wallet_inc = qty
            await db.general.update_one(
                {"id": user_id}, {"$inc": {"wallet": wallet_inc}}
            )
        elif kind == "crate":
            crate_inc = qty
            # find position
            idx = self._crate_rarities.index(key)
            await db.general.update_one(
                {"id": user_id},
                {"$inc": {f"crates.{idx}": crate_inc}}
            )
        else:
            # inventory + collection
            await db.inventory.update_one({"id": user_id}, {"$inc": {key: qty}})
            coll = await db.collections.find_one({"id": user_id})
            old_c, old_cl = coll["fish"], coll["fishLevel"]
            new_c = old_c + qty
            coll_thr = 50 * old_cl + 50
            if new_c >= coll_thr:
                leveled_coll = True
                await db.collections.update_one(
                    {"id": user_id},
                    {"$set": {"fish": new_c, "fishLevel": old_cl + 1}}
                )
            else:
                await db.collections.update_one(
                    {"id": user_id}, {"$set": {"fish": new_c}}
                )

        # 7) Build the embed response
        embed = discord.Embed(
            title="🎣 Fishing Results",
            color=discord.Color.teal(),
            timestamp=datetime.datetime.now()
        )
        # Description of catch
        if kind == "coins":
            embed.add_field(
                name="💰 Treasure!",
                value=f"You reeled in **{wallet_inc:,} coins**",
                inline=False
            )
        elif kind == "crate":
            embed.add_field(
                name="📦 Crate!",
                value=f"You got a **{key.title()}**",
                inline=False
            )
        else:
            embed.add_field(
                name="🐟 Catch!",
                value=f"You caught **{qty}** × **{_items_data[key]['name'].title()}**",
                inline=False
            )

        # Common fields
        embed.add_field(name="Fishing XP", value=f"⭐ {xp_gain:,} XP", inline=True)
        embed.add_field(name="Fishing Essence", value=f"✨ {essence_gain}", inline=True)
        embed.add_field(
            name="Stamina Remaining",
            value=f"💪 {profile['stamina'] - 1}",
            inline=False
        )

        if leveled_fish:
            embed.add_field(
                name="🏅 Level Up!",
                value=(
                    f"You’re now **Fishing Level {old_lvl + 1}**\n"
                    f"(+{bonus_inc} fishing bonus!)"
                ),
                inline=False
            )
        if leveled_coll:
            embed.add_field(
                name="📚 Collection Level!",
                value=f"Your **Fish Collection** is now **Level {old_cl + 1}**",
                inline=False
            )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(FishingCog(bot), guilds=[discord.Object(id=GUILD_ID)])