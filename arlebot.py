from timeit import default_timer as timer
import discord
import warnings
import tomllib
from validators.config import ConfigValidator
from utils.reboot import clear_terminal

start = timer()

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pydub.utils")


def main():
    with open("config.toml", "rb") as f:
        data = tomllib.load(f)

    arle_config: ConfigValidator = ConfigValidator.model_validate(data)
    # print(arle_config.model_dump_json(indent=4))
    # print("validated config file successfully")

    clear_terminal()  # TODO : review use of clear terminal and it's usefulness after logs are added

    intents = discord.Intents().all()
    intents.message_content = True
    intents.members = True

    bot = discord.Bot(intents=intents)

    @bot.event
    async def on_ready():
        end = timer()
        print(f"{bot.user} is ready and online in {end-start:.2f}s!")
        print(f"{bot.user} is connected to {bot.guilds}")

    extensions = [
        "cogs.discord-utils",
        "cogs.music",
        "cogs.moderation",
        "cogs.smashorpass",
    ]

    for extension in extensions:
        bot.load_extension(extension)

    bot.run(arle_config.secrets.discord_token)
    print("shutting down")


if __name__ == "__main__":
    main()
