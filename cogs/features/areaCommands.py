import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
import json

# Load areas data once
_AREAS_PATH = Path("data/areas.json")
_areas_data = {}
if _AREAS_PATH.exists():
    _areas_data = json.loads(_AREAS_PATH.read_text(encoding="utf-8"))

class AreaCommands(commands.Cog):
    """Handles `/area` command to display current area and sub-area details."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="area",
        description="🌍 View information about your current area and sub-area."
    )
    async def area(self, interaction: discord.Interaction) -> None:
        db = self.bot.db  # type: ignore[attr-defined]
        user_id = interaction.user.id

        # Fetch user's current location document
        area_doc = await db.areas.find_one({"id": user_id})
        if not area_doc:
            return await interaction.response.send_message(
                "❌ Couldn't determine your current location!", ephemeral=True
            )

        current_area_key = area_doc.get("currentArea")
        current_sub_key = area_doc.get("currentSubarea")
        if not current_area_key or not current_sub_key:
            return await interaction.response.send_message(
                "❌ You're not in a valid area or sub-area!", ephemeral=True
            )

        # Retrieve area and sub-area data
        area_data = _areas_data.get(current_area_key, {})
        sub_data = area_data.get("sub_areas", {}).get(current_sub_key, {})

        if not area_data or not sub_data:
            return await interaction.response.send_message(
                "❌ Invalid area or sub-area data!", ephemeral=True
            )

        # Build embed
        embed = discord.Embed(
            title=f"🌍 **{area_data.get('name', 'Unknown')}** - **{sub_data.get('name', 'Unknown')}**",
            description=f"📜 {area_data.get('lore', '')}",
            color=discord.Color.blurple()
        )
        # Validate and set image URL
        image_url = sub_data.get('image')
        if image_url and isinstance(image_url, str) and image_url.startswith(('http://', 'https://')):
            embed.set_thumbnail(url=image_url)

        # Sub-area lore only
        embed.add_field(
            name="📝 Sub-Area Lore", 
            value=sub_data.get('lore', 'No lore available.'), 
            inline=False
        )

        # Mobs
        mobs = sub_data.get('mobs', [])
        if mobs:
            embed.add_field(
                name="👾 Mobs", 
                value=", ".join(f"{mob.capitalize()}" for mob in mobs), 
                inline=False
            )

        # Resources (uppercase)
        resources = sub_data.get('resources', [])
        if resources:
            embed.add_field(
                name="🪵 Resources", 
                value=", ".join(res.capitalize() for res in resources), 
                inline=False
            )

        # Connections
        connections = sub_data.get('connections', [])
        if connections:
            connected_names = [
                area_data['sub_areas'][conn].get('name', conn)
                for conn in connections
                if conn in area_data.get('sub_areas', {})
            ]
            if connected_names:
                embed.add_field(
                    name="🔗 Connections", 
                    value=", ".join(connected_names), 
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(AreaCommands(bot), guilds=[discord.Object(id=GUILD_ID)])