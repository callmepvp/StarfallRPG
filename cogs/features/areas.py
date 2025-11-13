import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
import json
import datetime

from typing import NoReturn, Optional, Tuple

# Load areas data once
_AREAS_PATH = Path("data/areas.json")
_areas_data = {}
if _AREAS_PATH.exists():
    _areas_data = json.loads(_AREAS_PATH.read_text(encoding="utf-8"))

def find_subarea_by_key_or_name(query: str) -> Optional[Tuple[str, str]]:
    """
    Try to find a subarea matching a key or display name (case-insensitive).
    Returns (area_key, sub_key) or None if not found.
    """
    q = query.strip().lower()
    for area_key, area in _areas_data.items():
        sub_areas = area.get("sub_areas", {})
        # direct key match
        if q in sub_areas:
            return area_key, q
        # name match
        for sub_key, sub in sub_areas.items():
            name = sub.get("name", "")
            if isinstance(name, str) and name.strip().lower() == q:
                return area_key, sub_key
    return None

class AreaCommands(commands.Cog):
    
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    """Handles `/area` command to display current area and sub-area details."""
    @app_commands.command(
        name="area",
        description="View information about your current area and subarea."
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
            name="📝 Subarea Information", 
            value=sub_data.get('lore', 'No lore available.'), 
            inline=False
        )

        # Mobs
        mobs = sub_data.get('mobs', [])
        if mobs:
            embed.add_field(
                name="👾 Mobs", 
                value=", ".join(mob.replace('_', ' ').title() for mob in mobs),
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

    @app_commands.command(
        name="travel",
        description="🚶 Travel to a connected sub-area. Provide the sub-area key or display name."
    )
    @app_commands.describe(destination="The target sub-area (key like 'pond' or name like 'Pond').")
    async def travel(self, interaction: discord.Interaction, destination: str) -> None:
        """
        Travel command with cooldown.
        Stores lastTravel (epoch seconds) in db.areas per player.
        Default cooldown: 3600 seconds (1 hour). Change COOLDOWN_SECONDS below to adjust.
        """
        COOLDOWN_SECONDS = 3600  # 1 hour; change to desired value

        await interaction.response.defer(thinking=True)
        db = self.bot.db
        user_id = interaction.user.id
        
        player = await db.general.find_one({"id": user_id})
        if not player:
            return await interaction.followup.send(
                "❌ You need to `/register` before you can travel!", 
                ephemeral=True
            )

        if player.get("inDungeon", False):
            return await interaction.followup.send(
                "❌ You can't travel while in a dungeon! Complete or flee from your dungeon first.",
                ephemeral=True
            )

        # Resolve destination to (area_key, sub_key)
        dest = find_subarea_by_key_or_name(destination)
        if not dest:
            return await interaction.followup.send(
                "❌ Destination not found. Provide a valid sub-area key or display name.", ephemeral=True
            )
        dest_area_key, dest_sub_key = dest

        # Fetch user's current location document (and lastTravel)
        area_doc = await db.areas.find_one({"id": user_id})
        if not area_doc:
            return await interaction.followup.send(
                "❌ Couldn't determine your current location!", ephemeral=True
            )

        current_area_key = area_doc.get("currentArea")
        current_sub_key = area_doc.get("currentSubarea")
        if not current_area_key or not current_sub_key:
            return await interaction.followup.send(
                "❌ You're not in a valid area or sub-area!", ephemeral=True
            )

        # COOLDOWN CHECK
        now_ts = int(datetime.datetime.utcnow().timestamp())
        last_travel_ts = int(area_doc.get("lastTravel", 0) or 0)
        elapsed = now_ts - last_travel_ts
        if elapsed < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - elapsed
            mins = remaining // 60
            secs = remaining % 60
            time_str = f"{mins}m{secs}s" if mins > 0 else f"{secs}s"
            return await interaction.followup.send(
                f"⏳ You can't travel yet. Time until next travel: **{time_str}**.",
                ephemeral=True
            )

        # If already there
        if current_area_key == dest_area_key and current_sub_key == dest_sub_key:
            return await interaction.followup.send(
                "ℹ️ You're already in that sub-area.", ephemeral=True
            )

        # Get area & subarea data for current and destination
        current_area_data = _areas_data.get(current_area_key, {})
        current_sub_data = current_area_data.get("sub_areas", {}).get(current_sub_key, {})
        if not current_sub_data:
            return await interaction.followup.send(
                "❌ Current sub-area data is invalid. Contact an admin.", ephemeral=True
            )

        # Check connection: destination sub_key must be in current subarea connections
        connections = current_sub_data.get("connections", [])
        if dest_sub_key not in connections:
            # Not connected directly — show available connections
            friendly_connections = []
            for conn in connections:
                if conn in current_area_data.get("sub_areas", {}):
                    friendly_connections.append(current_area_data['sub_areas'][conn].get('name', conn))
                else:
                    found = False
                    for a_key, a_data in _areas_data.items():
                        if conn in a_data.get('sub_areas', {}):
                            friendly_connections.append(a_data['sub_areas'][conn].get('name', conn))
                            found = True
                            break
                    if not found:
                        friendly_connections.append(conn)
            readable = ", ".join(friendly_connections) if friendly_connections else "none"
            return await interaction.followup.send(
                f"❌ That destination isn't directly connected to your current sub-area.\n"
                f"Available connections from your location: {readable}",
                ephemeral=True
            )

        # All checks pass — perform the DB update (match your collection format)
        dest_area = _areas_data.get(dest_area_key, {})
        dest_sub = dest_area.get("sub_areas", {}).get(dest_sub_key, {})
        subarea_type = dest_sub.get("type") if isinstance(dest_sub, dict) else None

        update_result = await db.areas.update_one(
            {"id": user_id},
            {"$set": {
                "currentArea": dest_area_key,
                "currentSubarea": dest_sub_key,
                "subareaType": subarea_type,
                "lastTravel": now_ts  # record travel time for cooldown
            }}
        )

        # Build a success embed (use destination display name & descriptions)
        embed = discord.Embed(
            title=f"🚶 Moved to {dest_sub.get('name', dest_sub_key)}",
            description=dest_sub.get("lore", ""),
            color=discord.Color.green()
        )
        image_url = dest_sub.get("image")
        if image_url and isinstance(image_url, str) and image_url.startswith(('http://', 'https://')):
            embed.set_thumbnail(url=image_url)

        if dest_sub.get("mobs"):
            embed.add_field(name="👾 Mobs", value=", ".join(x.replace('_', ' ').title() for x in dest_sub["mobs"]), inline=False)
        if dest_sub.get("resources"):
            embed.add_field(name="🪵 Resources", value=", ".join(x.capitalize() for x in dest_sub["resources"]), inline=False)

        # Helpful footer showing cooldown length (human readable)
        cd_minutes = COOLDOWN_SECONDS // 60
        embed.set_footer(text=f"Travel cooldown: {cd_minutes} minute(s)")

        await interaction.followup.send(embed=embed)

        # --- Quest progress updates ---
        try:
            quest_cog: Optional[commands.Cog] = self.bot.get_cog("QuestCog")
            if quest_cog:
                completions = await quest_cog.update_progress(
                    user_id,
                    objective_type="explore",
                    target=dest_sub_key,
                    amount=1
                )
                if completions:
                    # Build a friendly quest update message
                    lines = []
                    newly_unlocked = []
                    for comp in completions:
                        tpl = comp["template"]
                        title = tpl.get("title", comp["quest_id"])
                        lines.append(f"✅ Quest completed: **{title}**")

                        # Check next_quest
                        next_q = tpl.get("next_quest")
                        if next_q:
                            unlocked_tpl = await quest_cog.get_template(next_q)
                            if unlocked_tpl:
                                newly_unlocked.append(f"🟡 New quest unlocked: '{unlocked_tpl.get('title','Unknown')}'")

                    await interaction.followup.send(
                        "\n".join(lines + newly_unlocked),
                        ephemeral=True
                    )
        except Exception as e:
            print(f"[WARN] Failed to update travel quest progress: {e}")


async def setup(bot: commands.Bot) -> None:
    from settings import GUILD_ID
    await bot.add_cog(AreaCommands(bot), guilds=[discord.Object(id=GUILD_ID)])