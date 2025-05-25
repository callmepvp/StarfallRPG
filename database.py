from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from typing import Optional

class Database:
    """
    Async MongoDB wrapper using Motor.

    Attributes:
        client: The Motor client instance.
        general, inventory, skills, collections, recipes, areas:
            AsyncIOMotorCollection objects for each namespace.
    """

    def __init__(self, uri: str, db_name: str = "alphaworks") -> None:
        self.client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5_000)
        self.db = self.client[db_name]

        # Initialize collections
        self.general: AsyncIOMotorCollection = self.db["general"]
        self.inventory: AsyncIOMotorCollection = self.db["inventory"]
        self.skills: AsyncIOMotorCollection = self.db["skills"]
        self.collections: AsyncIOMotorCollection = self.db["collections"]
        self.recipes: AsyncIOMotorCollection = self.db["recipes"]
        self.areas: AsyncIOMotorCollection = self.db["areas"]

    async def ping(self) -> bool:
        """
        Verify connectivity to MongoDB.
        Returns True if ping succeeds, False otherwise.
        """
        try:
            await self.client.admin.command("ping")
            return True
        except Exception:
            return False

    def close(self) -> None:
        """
        Close the Motor client connection.
        """
        self.client.close()