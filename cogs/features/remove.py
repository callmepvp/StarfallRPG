# remove.py
from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

class Remove(commands.Cog):
    """Command to delete all data for a specific user across all collections."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = getattr(bot, "db", None)
        if self.db is None:
            raise RuntimeError("Bot does not have a 'db' attribute set.")

        # Collections to search (attribute access)
        self.collections_to_clear = [
            self.db.general,
            self.db.inventory,
            self.db.skills,
            self.db.collections,
            self.db.recipes,
            self.db.areas,
            self.db.equipment,
            self.db.quests
        ]

    @app_commands.command(
        name="remove",
        description="Delete all data for a specified user across all collections."
    )
    @app_commands.describe(user_id="The Discord ID of the user to remove.")
    async def remove(self, interaction: discord.Interaction, user_id: str) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ You must be an administrator to use this command.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        deleted_counts = {}
        for coll in self.collections_to_clear:
            result = await coll.delete_many({"id": int(user_id)})
            deleted_counts[coll.name] = result.deleted_count  # Motor collections have a .name attribute

        summary = "\n".join(f"**{name}**: {count} document(s) deleted"
                            for name, count in deleted_counts.items())

        await interaction.followup.send(
            f"🗑 Successfully removed all data for user ID `{user_id}`:\n{summary}",
            ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(Remove(bot), guilds=[discord.Object(id=GUILD_ID)])
