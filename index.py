import json
import logging
from pathlib import Path
from typing import NoReturn, Optional

import aiohttp
import discord
from discord import Intents
from discord.ext import commands

from database import Database

# ——— Configuration —————————————————————————————————————————————————————————————
CONFIG_PATH = Path("data/config.json")


def load_config(path: Path) -> dict:
    """
    Load bot configuration from a JSON file.
    
    Raises:
        FileNotFoundError: If the config file is missing.
        ValueError: If the JSON is malformed.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path!r}")
    text = path.read_text(encoding="utf-8")
    return json.loads(text)

from settings import DISCORD_TOKEN, APPLICATION_ID, COMMAND_PREFIX, GUILD_ID, DATABASE_URI

# ——— Logging Setup —————————————————————————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot")


# ——— Bot Client ————————————————————————————————————————————————————————————————
class Client(commands.Bot):
    """
    The main bot client class.

    Attributes:
        session: HTTP session for external requests.
        db: Database wrapper for Mongo operations.
    """

    def __init__(self) -> None:
        intents = Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=COMMAND_PREFIX,
            intents=intents,
            application_id=APPLICATION_ID,
        )
        self.session: Optional[aiohttp.ClientSession] = None
        self.db: Optional[Database] = None

    async def setup_hook(self) -> None:
        """
        Called by discord.py when the bot starts up.
        - Opens an aiohttp session.
        - Initializes the async Database.
        - Dynamically loads all cog extensions.
        - Syncs the command tree to the development guild.
        """
        # HTTP session
        logger.info("Creating HTTP session…")
        self.session = aiohttp.ClientSession()

        # Database
        logger.info("Connecting to MongoDB…")
        self.db = Database(DATABASE_URI, db_name="alphaworks")
        connected = await self.db.connect(max_retries=3, backoff_seconds=0.5)
        if not connected:
            logger.error("❌ Could not connect to MongoDB. DB-backed features may fail.")


        # Load all top-level cogs
        for cog_path in Path("cogs").glob("*.py"):
            name = f"cogs.{cog_path.stem}"
            logger.debug("Loading extension %s", name)
            await self.load_extension(name)

        # Load sub-folder cogs
        for cog_path in Path("cogs/skills").glob("*.py"):
            name = f"cogs.skills.{cog_path.stem}"
            logger.debug("Loading extension %s", name)
            await self.load_extension(name)

        # Load sub-folder cogs
        for cog_path in Path("cogs/features").glob("*.py"):
            name = f"cogs.features.{cog_path.stem}"
            logger.debug("Loading extension %s", name)
            await self.load_extension(name)

        # Sync slash commands to a specific guild for faster updates during development
        logger.info("Syncing application commands to GUILD_ID=%d", GUILD_ID)
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))

    async def close(self) -> NoReturn:
        """
        Clean up resources on shutdown.
        """
        logger.info("Shutting down…")
        if self.session:
            await self.session.close()
        if self.db:
            self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        """
        Called when the bot is fully operational.
        """
        logger.info("Bot is online as %s (ID: %d)", self.user, self.user.id)


def main() -> None:
    """
    Entrypoint: instantiate the client and run the bot.
    """
    bot = Client()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()