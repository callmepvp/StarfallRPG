from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Tuple

import json
import discord
from discord import app_commands
from discord.ext import commands

from settings import GUILD_ID

DATA_COLLECTIONS_DIR = Path("data/collections")

# Map DB keys to human friendly collection titles
COLLECTION_KEYS: List[Tuple[str, str]] = [
    ("wood", "Wood"),
    ("ore", "Ore"),
    ("crop", "Crop"),
    ("herb", "Herb"),
    ("fish", "Fish"),
]

class CollectionsCog(commands.Cog):
    """Show unlocked collection recipes and locked tiers for a user."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _load_collection_table(self, collection_key: str) -> Dict[str, List[str]]:
        """
        Loads data/collections/<collection_key>.json if present.
        Returns mapping of tier (string) -> list of recipe keys.
        """
        path = DATA_COLLECTIONS_DIR / f"{collection_key}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _gather_unlocked(
        self, table: Dict[str, List[str]], level: int
    ) -> Tuple[List[str], int]:
        """
        From a collection table and a user's level, return:
          - unlocked_recipes: list of recipe keys unlocked up to `level`
          - total_recipes: total number of recipes in the table
        Note: table keys are expected to be tier numbers as strings: "1", "2", ...
        """
        unlocked: List[str] = []
        total = 0
        for tier_str, recipes in table.items():
            try:
                tier = int(tier_str)
            except Exception:
                # If tier keys are not numeric, ignore them
                continue
            total += len(recipes or [])
            if tier <= level:
                unlocked.extend(recipes or [])
        return unlocked, total

    @app_commands.command(
        name="collections",
        description="View your collection progression and unlocked recipes."
    )
    async def collections(self, interaction: discord.Interaction) -> None:
        db = getattr(self.bot, "db", None)
        if db is None:
            return await interaction.response.send_message(
                "❌ Database is not configured on the bot.", ephemeral=True
            )

        user_id = interaction.user.id

        coll_doc = await db.collections.find_one({"id": user_id})
        if not coll_doc:
            return await interaction.response.send_message(
                "📭 You don't have any collection data yet. Try `/register` first.", ephemeral=True
            )

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Collections",
            color=discord.Color.teal()
        )

        grand_unlocked = 0
        grand_total = 0

        for key, pretty in COLLECTION_KEYS:
            level_key = f"{key}Level"
            level = int(coll_doc.get(level_key, 0))
            table = self._load_collection_table(key)

            unlocked, total = self._gather_unlocked(table, level)
            grand_unlocked += len(unlocked)
            grand_total += total

            # Build display lines
            if unlocked:
                # Capitalize recipe keys for readability (preserve underscores if any)
                unlocked_lines = ", ".join(r.replace("_", " ").title() for r in unlocked)
            else:
                unlocked_lines = "*None unlocked yet*"

            locked_count = max(0, total - len(unlocked))

            # Include small hint about locked tiers (not revealing recipes)
            # Determine next locked tier (first tier > level that has recipes)
            next_locked_tier = None
            for tier_str in sorted(table.keys(), key=lambda s: int(s) if s.isdigit() else 1_000_000):
                try:
                    tier = int(tier_str)
                except Exception:
                    continue
                if tier > level and (table.get(tier_str) or []):
                    next_locked_tier = tier
                    break

            footer_parts = []
            footer_parts.append(f"Level: {level}")
            if locked_count:
                footer_parts.append(f"Locked: {locked_count}")
            if next_locked_tier is not None:
                footer_parts.append(f"Next unlock @ **Tier {next_locked_tier}**")

            embed.add_field(
                name=f"🔸 {pretty}",
                value=f"{unlocked_lines}\n\n" + " · ".join(footer_parts),
                inline=False,
            )

        summary = f"Total unlocked: {grand_unlocked:,} / {grand_total:,} recipes"
        embed.set_footer(text=summary)

        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CollectionsCog(bot), guilds=[discord.Object(id=GUILD_ID)])
