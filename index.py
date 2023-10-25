import discord
from discord.ext import commands

from json import loads
from pathlib import Path

import aiohttp
import os

#Retrieve Tokens
tokens = loads(Path("data/config.json").read_text())
DISCORD_TOKEN = tokens['DISCORD_TOKEN']
APPLICATION_ID = tokens['APPLICATION_ID']
PREFIX = tokens['PREFIX']

class Client(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix = PREFIX,
            intents = discord.Intents.all(),
            application_id = APPLICATION_ID)  
    
    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        for name in os.listdir("./cogs"):
            if name.endswith(".py"):
                await bot.load_extension("cogs.{}".format(name[:-3]))

        for name in os.listdir("./cogs/skills"):
            if name.endswith(".py"):
                await bot.load_extension("cogs.skills.{}".format(name[:-3]))

        await bot.tree.sync(guild = discord.Object(id = 1047945458665914388))

    async def close(self):
        await super().close()
        await self.session.close()

    async def on_ready(self):
        print(f'[INDEX] Online as {self.user}!')

bot = Client()
bot.run(DISCORD_TOKEN)