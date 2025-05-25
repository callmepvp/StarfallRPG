from pathlib import Path
import json

_cfg = json.loads(Path("data/config.json").read_text(encoding="utf-8"))
DISCORD_TOKEN: str = _cfg["DISCORD_TOKEN"]
APPLICATION_ID: int = int(_cfg["APPLICATION_ID"])
COMMAND_PREFIX: str = _cfg["PREFIX"]
GUILD_ID: int = _cfg["GUILD_ID"]
DATABASE_URI: str = _cfg["DATABASE_TOKEN"]