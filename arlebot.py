import os
import warnings
import discord
import tomllib
from validators.config import ConfigValidator

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pydub.utils")

with open("config.toml", "rb") as f:
    data = tomllib.load(f)

arle_config: ConfigValidator = ConfigValidator.model_validate(data)
print(arle_config.model_dump_json(indent=4))
print("validated config file successfully")


def clear_terminal():
    print("\033[H\033[J")


clear_terminal()  # TODO : review use of clear terminal and it's usefulness after logs are added

intents = discord.Intents().all()
intents.message_content = True
intents.members = True

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")


extensions = [
    "cogs.discord-utils",
    "cogs.music",
    "cogs.moderation",
    "cogs.smashorpass",
]

if __name__ == "__main__":
    for extension in extensions:
        bot.load_extension(extension)


bot.run(arle_config.secrets.discord_token)
print("shutting down")
