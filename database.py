# database.py
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

logger = logging.getLogger("bot.database")

class Database:
    """
    Async MongoDB wrapper using Motor.

    Use `await Database.connect()` to verify connectivity.
    After connect(), `self.db` is usable and collections are available.
    """

    def __init__(self, uri: str, db_name: str = "alphaworks", server_selection_timeout_ms: int = 5000) -> None:
        self._uri = uri
        self._db_name = db_name
        self._sstms = server_selection_timeout_ms

        # Create client lazily; we'll create it in connect() so we can control retries.
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None

        # Collections (populated after successful connect)
        self.general: Optional[AsyncIOMotorCollection] = None
        self.inventory: Optional[AsyncIOMotorCollection] = None
        self.skills: Optional[AsyncIOMotorCollection] = None
        self.collections: Optional[AsyncIOMotorCollection] = None
        self.recipes: Optional[AsyncIOMotorCollection] = None
        self.areas: Optional[AsyncIOMotorCollection] = None
        self.equipment: Optional[AsyncIOMotorCollection] = None

    async def connect(self, max_retries: int = 3, backoff_seconds: float = 0.5) -> bool:
        """
        Attempt to connect to MongoDB, retrying on transient failures.
        Returns True if connected and collections initialized, False otherwise.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                self.client = AsyncIOMotorClient(self._uri, serverSelectionTimeoutMS=self._sstms)
                # Resolve DB (use provided name)
                self.db = self.client[self._db_name]
                # Force a network round-trip to confirm connectivity
                await self.db.command("ping")
                # Initialize collection handles
                self.general = self.db["general"]
                self.inventory = self.db["inventory"]
                self.skills = self.db["skills"]
                self.collections = self.db["collections"]
                self.recipes = self.db["recipes"]
                self.areas = self.db["areas"]
                self.equipment = self.db["equipment"]
                logger.info("Connected to MongoDB (database=%s)", self._db_name)
                return True
            except Exception as exc:
                last_exc = exc
                logger.warning("MongoDB connect attempt %d/%d failed: %s", attempt, max_retries, exc)
                await asyncio.sleep(backoff_seconds * attempt)
        logger.error("Failed to connect to MongoDB after %d attempts. Last error: %s", max_retries, last_exc)
        return False

    async def ping(self) -> bool:
        """Quick ping — returns True if DB reachable (and client created)."""
        if not self.client or not self.db:
            return False
        try:
            await self.db.command("ping")
            return True
        except Exception as exc:
            logger.debug("Ping failed: %s", exc)
            return False

    def close(self) -> None:
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            logger.info("MongoDB client closed.")
