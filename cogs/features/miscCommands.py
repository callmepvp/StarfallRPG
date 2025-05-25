import datetime
from discord import app_commands, Interaction
from discord.ext import commands
import discord

from server.userMethods import regenerate_stamina
from settings import GUILD_ID

class MiscCommandCog(commands.Cog):
    """🧭 Miscellaneous helpful commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_regen_user(self, user_id: int) -> dict | None:
        db = self.bot.db
        user = await db.general.find_one({"id": user_id})
        if user is None:
            return None

        user = regenerate_stamina(user)
        await db.general.update_one(
            {"id": user_id},
            {"$set": {
                "stamina": user["stamina"],
                "lastStaminaUpdate": user["lastStaminaUpdate"]
            }}
        )
        return user

    @app_commands.command(
        name="rest",
        description="😴 Rest to recover HP by spending stamina (1 stamina = 2 HP)."
    )
    @app_commands.describe(target_hp="The total HP you want to rest up to.")
    async def rest(self, interaction: Interaction, target_hp: int):
        db = self.bot.db
        user_id = interaction.user.id

        user = await self.get_regen_user(user_id)
        if not user:
            return await interaction.response.send_message(
                "❌ You need to `/register` before you can rest.", ephemeral=True
            )

        current_hp = user.get("hp", 100)
        max_hp = user.get("maxHP", 100)

        if target_hp <= current_hp:
            return await interaction.response.send_message(
                f"⚠️ You're already at {current_hp} HP or more!", ephemeral=True
            )

        if target_hp > max_hp:
            return await interaction.response.send_message(
                f"⚠️ You can't heal past your max HP of {max_hp}.", ephemeral=True
            )

        hp_needed = target_hp - current_hp
        stamina_required = (hp_needed + 1) // 2  # Ceiling division

        if user.get("stamina", 0) < stamina_required:
            return await interaction.response.send_message(
                f"😩 You need **{stamina_required}** stamina to heal to {target_hp} HP, but you only have {user['stamina']}.",
                ephemeral=True
            )

        await db.general.update_one(
            {"id": user_id},
            {"$inc": {
                "hp": hp_needed,
                "stamina": -stamina_required
            }}
        )

        embed = discord.Embed(
            title="😴 You Rest...",
            description=(
                f"❤️ Healed from **{current_hp}** → **{target_hp}** HP\n"
                f"⚡ Used **{stamina_required}** stamina\n"
                f"💤 Take it easy, adventurer."
            ),
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(MiscCommandCog(bot), guilds=[discord.Object(id=GUILD_ID)])